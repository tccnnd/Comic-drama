from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from scripts.rw_models import StoryScene
from backend.config_utils import env_bool, env_float
from backend.llm_hub import llm_client
from scripts.prompt_compiler import PromptCompiler, find_project_root
from scripts.rw_voice import infer_voice_profile
from scripts.rw_planning import build_shot_plan, build_scene_temporal_spec


ANIME_STYLE_SUFFIX = (
    "日系番剧风格，像真正的动画正片而不是解说稿。"
    "角色表演要明确，镜头要有动作感和情绪推进，"
    "避免旁白总结、海报感、信息板感、漫画气泡和条漫分格感。"
)

ANIME_STYLE_SUFFIX_EXTRA = (
    "日系二维动画，动漫角色，清晰线稿，赛璐璐上色，平涂，电影级分镜构图。"
    "像真正的动画正片而不是解说稿。"
    "角色表演要明确，表情自然但有张力，镜头要有动作感和情绪推进。"
    "人物设定要跟随角色名、台词身份和角色设定，不要跨性别或跨年龄漂移。"
    "避免写实摄影感、真人皮肤质感、3D感、海报感、信息板感、漫画气泡和条漫分格感。"
)

ANIME_NEGATIVE_PROMPT_EXTRA = "sketch, lineart, monochrome, greyscale, black and white, uncolored, pencil drawing, rough sketch, low quality, blurry, realistic, photorealistic, live action, 3d, cgi, skin pores, photo, bad anatomy, deformed face, duplicate face, extra head"


DIRECTOR_SYSTEM_PROMPT = """
你只输出可解析 JSON，不要 Markdown，不要解释。
你是一位深谙短剧、番剧节奏的资深视觉导演，目标是把中文故事/剧本拆成可直接生产竖屏漫剧的视频分镜，而不是解说稿。

导演资产库：
1. camera_movement 只能从以下值中选择：
   - dramatic_push：震惊、愤怒、对峙、反转、揭露真相、强台词爆发、物理撞击、雷鸣、刀剑碰撞。
   - melancholy_pan：内心独白、悲伤、回忆、沉默对视、环境扫视、雨夜压抑。
   - establishing_tilt：场景开端、宗门/宫殿/高楼/山门展示、新角色首次登场或全身展示。
   - slow_push_in：普通对话、轻微情绪推进。
   - slow_zoom_out：失落、距离感、结尾留悬念。
   - pan_left / pan_right / tilt_down / tilt_up：明确需要横移或上下摇镜时使用。
2. camera_speed 必须是 0.35 到 3.0 的数字：
   - dramatic_push 通常 1.2 到 1.6。
   - melancholy_pan 通常 0.55 到 0.9。
   - establishing_tilt 通常 0.8 到 1.2。
3. audio_manifest.sfx_trigger：
   - 无音效时使用 {"file": "", "timestamp_ms": 0, "volume": 0.65}。
   - 有巴掌/拳脚/撞击时 file 使用 "hit" 或 "slap"。
   - 有雷鸣/闪电时 file 使用 "thunder"。
   - 有爆炸/门被撞开/重物坠落时 file 使用 "boom"。
   - 有钢笔、杯子、钥匙等小物件掉落时 file 使用 "drop"。
   - 有刀剑破空、转场压迫时 file 使用 "whoosh"。
   - timestamp_ms 要根据动作发生位置估算：开场动作 0-500；台词中段爆发按每秒 4-5 个汉字推算；结尾反转通常落在分镜后 60%-80%。
4. 角色库约束：
   - characters 数组必须使用统一角色名，禁止同一个角色混用“他/那人/陆总”等代称。
   - dialogue 应尽量是角色台词，避免旁白总结。
""".strip()


def anime_visual_prompt(base: str, *, title: str = "", characters: list[str] | None = None, camera: str = "", emotion: str = "") -> str:
    parts = ["竖屏动漫番剧分镜", base.strip(), ANIME_STYLE_SUFFIX, ANIME_STYLE_SUFFIX_EXTRA]
    if title.strip():
        parts.append(f"场景标题：{title.strip()}")
    if characters:
        chars = "、".join(item for item in characters[:4] if str(item).strip())
        if chars:
            parts.append(f"角色：{chars}")
    if camera.strip():
        parts.append(f"镜头：{camera.strip()}")
    if emotion.strip():
        parts.append(f"情绪：{emotion.strip()}")
    return "；".join(part for part in parts if part)


def anime_video_prompt(
    base: str,
    *,
    title: str = "",
    characters: list[str] | None = None,
    camera: str = "",
    emotion: str = "",
    duration: float = 0.0,
) -> str:
    parts = [
        "vertical 9:16 anime drama video",
        "cinematic time-continuous animation",
        "stable character identity across frames",
        "coherent scene motion and lighting continuity",
        "character and environment relation remains stable",
        "not a still image pan, real video motion with acting",
        base.strip(),
        ANIME_STYLE_SUFFIX,
        ANIME_STYLE_SUFFIX_EXTRA,
    ]
    if duration > 0:
        parts.append(f"duration: {float(duration):.1f}s")
    if title.strip():
        parts.append(f"scene title: {title.strip()}")
    if characters:
        chars = ", ".join(item for item in characters[:4] if str(item).strip())
        if chars:
            parts.append(f"characters: {chars}")
    if camera.strip():
        parts.append(f"camera movement: {camera.strip()}")
    if emotion.strip():
        parts.append(f"emotion: {emotion.strip()}")
    return ", ".join(part for part in parts if part)


def infer_character_appearance_hint(scene: "StoryScene") -> str:
    names = " ".join([scene.speaker or "", *(scene.characters or [])])
    voice_profile = str(scene.voice_profile or infer_voice_profile(scene.speaker, scene.characters)).strip()
    if voice_profile == "female_lead" or any(token in names for token in {"晚", "女", "她", "姐", "妹", "娘", "妃", "姬"}):
        return "主要人物为年轻女性，黑色长发，清秀但克制，五官稳定，服装端庄，避免男性化脸型。"
    if voice_profile in {"male_lead", "antagonist"} or any(token in names for token in {"男", "他", "少爷", "公子", "叔", "父", "总"}):
        return "主要人物为成年男性或少年男性，短发或束发，五官稳定，服装端庄，避免女性化脸型。"
    return "主要人物五官稳定、发型和服装在全片保持一致。"


def clean_comfyui_visual_prompt(text: str) -> str:
    """Clean and normalize a visual prompt for ComfyUI/SD consumption.

    Removes Chinese narrative instructions and formatting artifacts while
    preserving quality tags, character descriptions, and visual keywords.
    """
    raw = " ".join(str(text or "").split())
    if not raw:
        return ""

    raw = re.sub(r"日系番剧风格[^。！？]*[。！？]?", "", raw)
    raw = re.sub(r"镜头要有动作感和情绪推进[^。！？]*[。！？]?", "", raw)
    raw = re.sub(r"避免旁白总结[^。！？]*[。！？]?", "", raw)
    raw = re.sub(r"\[[^\]]+\]", "", raw)
    raw = re.sub(r"\s*--ar\s+\d+:\d+\s*--niji\s+\d+.*$", "", raw)
    raw = re.sub(r"\([^)]*Webtoon[^)]*\)\s*", "", raw)
    raw = re.sub(r"^(竖屏动漫番剧分镜|竖屏动态漫画分镜|番剧分镜)\s*[；;,，]?\s*", "", raw)
    raw = re.sub(r"^分镜\s*\d+\s*[；;,，]?\s*", "", raw)
    raw = raw.replace("场景标题：", " ").replace("角色：", " ").replace("镜头：", " ").replace("情绪：", " ")
    raw = raw.replace("音效：", " ").replace("旁白：", " ").replace("台词：", " ")
    # Normalize separators: convert Chinese semicolons/commas to standard commas
    raw = raw.replace("；", ", ").replace("，", ", ").replace("、", ", ")
    raw = re.sub(r"\s+", " ", raw).strip(" ；;,，。")
    # Collapse multiple commas
    raw = re.sub(r",\s*,+", ",", raw)
    raw = re.sub(r"^\s*,\s*", "", raw)
    return raw.strip(", ")


def scene_consistency_spec(scene: StoryScene) -> dict[str, Any]:
    bible = deepcopy(scene.production_bible) if isinstance(scene.production_bible, dict) else {}
    current = bible.get("current_scene") if isinstance(bible.get("current_scene"), dict) else {}
    return {
        "version": 1,
        "kind": "scene_consistency_spec",
        "scene": scene.scene,
        "title": scene.title,
        "active_characters": current.get("active_characters") if isinstance(current, dict) else [],
        "character_prompt": scene.character_prompt_compilation,
        "negative_prompt": scene.negative_prompt_compilation,
        "primary_reference": {
            "path": scene.primary_reference_image_path,
            "meta": deepcopy(scene.primary_reference_meta) if isinstance(scene.primary_reference_meta, dict) else {},
        },
        "rules": bible.get("rules") if isinstance(bible.get("rules"), dict) else {
            "preserve_character_identity": True,
            "keep_lighting_continuous_within_scene": True,
            "keep_environment_geometry_stable": True,
        },
    }


def temporal_spec_prompt_lines(temporal_spec: dict[str, Any], consistency_spec: dict[str, Any]) -> list[str]:
    lines = [
        "Generate a real continuous video, not a still image with pan/zoom.",
        "Keep motion temporally coherent across the whole shot.",
        "Keep characters physically grounded in the environment with stable lighting and scale.",
    ]
    shots = temporal_spec.get("shots") if isinstance(temporal_spec, dict) else []
    if isinstance(shots, list) and shots:
        compact = []
        for shot in shots[:6]:
            if not isinstance(shot, dict):
                continue
            compact.append(
                f"{shot.get('shot_order')}: {shot.get('label')} {shot.get('camera_movement')} "
                f"{shot.get('duration_seconds')}s focus=({shot.get('center_x')},{shot.get('center_y')})"
            )
        if compact:
            lines.append("Shot timing plan: " + " | ".join(compact))
    active = consistency_spec.get("active_characters") if isinstance(consistency_spec, dict) else []
    if isinstance(active, list) and active:
        character_bits = []
        for character in active[:4]:
            if not isinstance(character, dict):
                continue
            bit = ", ".join(
                str(character.get(key) or "").strip()
                for key in ("name", "appearance_core", "clothing_style")
                if str(character.get(key) or "").strip()
            )
            if bit:
                character_bits.append(bit)
        if character_bits:
            lines.append("Character continuity: " + " | ".join(character_bits))
    return lines


def _scene_prompt_mapping(scene: StoryScene | dict[str, Any]) -> dict[str, Any]:
    if isinstance(scene, dict):
        return deepcopy(scene)
    payload = asdict(scene)
    for key in ("director_plan", "shot_plan"):
        value = getattr(scene, key, None)
        if value is not None:
            payload[key] = deepcopy(value)
    return payload


def _existing_scene_shot_plan(scene: StoryScene | dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(scene, dict):
        value = scene.get("shot_plan")
    else:
        value = getattr(scene, "shot_plan", None)
    return value if isinstance(value, dict) else None


def _prototype_constraint_prompt_line(label: str, directive: str, values: Any) -> str | None:
    if not isinstance(values, list):
        return None
    items = [str(item).strip() for item in values if str(item).strip()]
    if not items:
        return None
    return f"{label} {directive}: {', '.join(items)}"


def _shot_visual_content_prompt_lines(shot_plan: dict[str, Any]) -> list[str]:
    shots = shot_plan.get("shots") if isinstance(shot_plan, dict) else []
    if not isinstance(shots, list):
        return []
    lines: list[str] = []
    for index, shot in enumerate(shots[:6], start=1):
        if not isinstance(shot, dict):
            continue
        visual_content = shot.get("visual_content")
        if not isinstance(visual_content, dict) or not visual_content:
            continue
        visual_prototype = shot.get("visual_prototype") if isinstance(shot.get("visual_prototype"), dict) else {}
        constraints = visual_prototype.get("constraints") if isinstance(visual_prototype.get("constraints"), dict) else {}
        camera_language = shot.get("camera_language") if isinstance(shot.get("camera_language"), dict) else {}
        parts = [
            f"shot {int(shot.get('shot_order') or index)} visual content",
            f"visual_content_source: {visual_content.get('_source')}",
            f"prototype_id: {visual_prototype.get('id')}",
            f"prototype_mode: {visual_prototype.get('mode')}",
            _prototype_constraint_prompt_line("prototype_constraints_hard", "MUST PRESERVE", constraints.get("hard")),
            _prototype_constraint_prompt_line("prototype_constraints_soft", "SHOULD PRESERVE", constraints.get("soft")),
            _prototype_constraint_prompt_line("prototype_constraints_guidelines", "GUIDE", constraints.get("guidelines")),
            f"shot_description: {visual_content.get('shot_description')}",
            f"foreground: {visual_content.get('foreground')}",
            f"midground: {visual_content.get('midground')}",
            f"background: {visual_content.get('background')}",
            f"composition: {visual_content.get('composition')}",
            f"motion: {visual_content.get('motion')}",
            f"lighting: {visual_content.get('lighting')}",
            f"focus: {visual_content.get('focus')}",
            f"shot_size: {shot.get('shot_size')}",
            f"camera_language: {camera_language.get('movement')}; {camera_language.get('lens')}; {camera_language.get('depth_of_field')}",
            f"dramatic_intent: {shot.get('dramatic_intent')}",
        ]
        lines.append(
            "; ".join(
                str(part).strip()
                for part in parts
                if part is not None and str(part).strip() and not str(part).endswith(": None")
            )
        )
    return lines


def _scene_visual_prompt_source(scene: StoryScene, duration: float) -> tuple[str, bool]:
    existing_shot_plan = _existing_scene_shot_plan(scene)
    if existing_shot_plan is not None:
        visual_lines = _shot_visual_content_prompt_lines(existing_shot_plan)
        if visual_lines:
            return "\n".join(visual_lines), True
        return clean_comfyui_visual_prompt(scene.visual), False

    scene_payload = _scene_prompt_mapping(scene)
    scene_payload.setdefault("duration_seconds", duration)
    visual_lines = _shot_visual_content_prompt_lines(build_shot_plan(scene_payload))
    if visual_lines:
        return "\n".join(visual_lines), True
    return clean_comfyui_visual_prompt(scene.visual), False


def build_scene_video_prompts(scene: StoryScene, duration: float, run_dir: Path) -> tuple[str, str]:
    """Build optimized positive and negative prompts for scene video generation.

    Prompt structure:
    1. Quality tags (masterpiece, best quality)
    2. Structured shot visual_content when available, else cleaned scene visual
    3. Character appearance anchors
    4. Motion/composition tags
    """
    # Quality prefix for better generation
    quality_prefix = "masterpiece, best quality, full color, vibrant colors, digital painting, colored, highly detailed"

    visual_source, uses_visual_content = _scene_visual_prompt_source(scene, duration)
    prompt_parts = [quality_prefix, visual_source, infer_character_appearance_hint(scene)]
    if scene.character_prompt_compilation:
        prompt_parts.append(str(scene.character_prompt_compilation).strip())
    if scene.character_descriptions:
        prompt_parts.append(f"character descriptions: {scene.character_descriptions}")
    if uses_visual_content:
        prompt_parts.append("visual_content is the primary visual source; dialogue is context only")
    prompt_parts.append(
        "continuous motion, expressive acting, consistent lighting, stable character-environment relationship, cinematic composition"
    )
    temporal_spec = (
        deepcopy(scene.temporal_spec)
        if isinstance(scene.temporal_spec, dict) and scene.temporal_spec
        else build_scene_temporal_spec(
            scene,
            duration,
            width=int(env_float("VIDEO_WIDTH", default=1080)),
            height=int(env_float("VIDEO_HEIGHT", default=1920)),
            fps=int(env_float("VIDEO_FPS", default=24)),
        )
    )
    consistency = scene_consistency_spec(scene)
    scene.temporal_spec = temporal_spec
    prompt_parts.extend(temporal_spec_prompt_lines(temporal_spec, consistency))
    prompt_text = anime_video_prompt(
        ", ".join(part for part in prompt_parts if str(part).strip()),
        title=scene.title,
        characters=scene.characters,
        camera=scene.camera,
        emotion=scene.emotion,
        duration=duration,
    )
    project_root = find_project_root(run_dir)
    if project_root is not None:
        compiler = PromptCompiler(project_root)
        prompt_source_parts = [visual_source]
        if scene.character_prompt_compilation:
            prompt_source_parts.append(str(scene.character_prompt_compilation).strip())
        if scene.character_descriptions:
            prompt_source_parts.append(f"character descriptions: {scene.character_descriptions}")
        if uses_visual_content:
            prompt_source_parts.append("visual_content is the primary visual source; dialogue is context only")
        compiled = compiler.compile(
            ", ".join(part for part in prompt_source_parts if str(part).strip()),
            list(scene.characters or []),
            speaker=scene.speaker,
        )
        compiled_positive = ", ".join(
            part for part in [compiled.positive, *temporal_spec_prompt_lines(temporal_spec, consistency)] if str(part).strip()
        )
        prompt_text = anime_video_prompt(
            compiled_positive,
            title=scene.title,
            characters=scene.characters,
            camera=scene.camera,
            emotion=scene.emotion,
            duration=duration,
        )

    negative_text = ", ".join(
        part
        for part in [
            "worst quality, low quality, normal quality",
            ANIME_NEGATIVE_PROMPT_EXTRA,
            "bad anatomy, bad hands, extra fingers, fewer fingers, extra limbs, deformed, disfigured, watermark, text, signature",
            scene.negative_prompt_compilation,
        ]
        if part
    )
    return prompt_text, negative_text


def storyboard_prompt(story: str, scene_count: int) -> str:
    return f"""
你是一个动画番剧分镜导演。请把用户故事拆成 {scene_count} 个镜头，输出要像真正的动漫第一集，而不是解说稿或漫画旁白稿。

硬性要求：
- 只输出 JSON，不要 Markdown，不要解释。
- JSON 顶层必须是对象，包含 scenes 数组。
- 每个 scene 必须包含：scene, duration, title, visual, dialogue, camera, emotion, characters, camera_speed, audio_manifest。
- scene 从 1 开始连续编号。
- duration 使用 3.0 到 6.0 之间的数字。
- visual 要是中文动画镜头描述，适合后续生图，必须包含构图、环境、角色动作、表情、光影和镜头节奏。
- dialogue 要像角色台词，不要写旁白总结、解说口吻或剧情概述。
- camera 只能用 snake_case，优先使用 dramatic_push, melancholy_pan, establishing_tilt, slow_push_in, slow_zoom_out, pan_left, pan_right, tilt_down, tilt_up。
- camera_speed 必须是数字，范围 0.35 到 3.0。
- audio_manifest 必须包含 bgm_style 和 sfx_trigger；sfx_trigger 必须包含 file, timestamp_ms, volume。
- characters 是中文字符串数组。
- 每个 scene 尽量包含明确角色表演、对视、反应或冲突，不要写成纯说明文字。
- 如果必须有旁白，只能放在极少数开场或转场处，主体仍然以台词推进。

输出格式示例：
{{
  "scenes": [
    {{
      "scene": 1,
      "duration": 4.2,
      "title": "雨夜对峙",
      "visual": "竖屏9:16，雨夜山门前，少年满身泥水抬头，远处长老冷眼俯视，冷色月光切出脸部阴影。",
      "dialogue": "少年：今日这一掌，我记下了。",
      "camera": "dramatic_push",
      "camera_speed": 1.35,
      "emotion": "压抑、愤怒",
      "characters": ["少年", "长老"],
      "audio_manifest": {{
        "bgm_style": "tense",
        "sfx_trigger": {{"file": "thunder", "timestamp_ms": 350, "volume": 0.7}}
      }}
    }}
  ]
}}

用户故事：
{story}
""".strip()


def extract_json_object(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM response did not contain a JSON object.")
    return json.loads(stripped[start : end + 1])


def post_llm_chat_completion(base_url: str, api_key: str, payload: dict, timeout: int = 300) -> str:
    def _request(request_payload: dict) -> str:
        data = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{base_url}/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")

    use_json_mode = env_bool("LLM_JSON_MODE", default=True)
    request_payload = {**payload}
    if use_json_mode:
        request_payload["response_format"] = {"type": "json_object"}

    try:
        return _request(request_payload)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if use_json_mode and exc.code in {400, 422}:
            print(f"[planner] LLM JSON mode unavailable, retrying without response_format: HTTP {exc.code}: {detail}")
            try:
                return _request(payload)
            except HTTPError as retry_exc:
                retry_detail = retry_exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"LLM HTTP {retry_exc.code}: {retry_detail}") from retry_exc
            except URLError as retry_exc:
                raise RuntimeError(f"LLM request failed: {retry_exc}") from retry_exc
        raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"LLM request failed: {exc}") from exc


def _call_llm_chat_content(system_prompt: str, user_prompt: str, model: str = "") -> str:
    """Call LLM via the unified hub client."""
    return llm_client.chat(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        task="director_classify",
        model=model,
        temperature=0.2,
    )


def script_storyboard_prompt(script: str, max_scenes: int, script_hint: str = "") -> str:
    script_with_hint = script.strip()
    hint_text = script_hint.strip()
    if hint_text:
        script_with_hint = f"【识别提示】{hint_text}\n\n{script_with_hint}"
    return f"""
你是动画番剧剧本识别器和短剧导演。把用户粘贴的原始剧本/小说整理成可编辑、可直接生产的竖屏动漫分镜，而不是旁白解说稿。
硬性要求：
- 只输出 JSON，不要 Markdown，不要解释
- 顶层对象必须包含 scenes 数组
- scenes 数组最多 {max_scenes} 项
- 每个 scene 必须包含 title, visual, dialogue, camera, emotion, characters, speaker, duration, camera_speed, audio_manifest
- duration 使用 3.0 到 7.0 之间的数字
- dialogue 需要保留角色台词格式，例如“林晚：我不会再回头”
- camera 只允许 snake_case，优先使用 dramatic_push, melancholy_pan, establishing_tilt, slow_push_in, slow_zoom_out, pan_left, pan_right, tilt_down, tilt_up
- camera_speed 必须是 0.35 到 3.0 的数字；爆发镜头 1.2-1.6，悲伤横移 0.55-0.9，环境/登场摇镜 0.8-1.2
- audio_manifest 必须包含 bgm_style 和 sfx_trigger；sfx_trigger 必须包含 file, timestamp_ms, volume
- characters 必须是中文角色名数组
- 优先识别角色台词、对视、反应、动作和冲突，不要把剧情总结写成旁白
- 如果剧本里真的有旁白，只能少量保留，主体仍然应当是角色台词推进

导演字段规则：
- 震惊、愤怒、反转、对峙、巴掌、拳脚、撞击、雷鸣、刀剑碰撞：camera 使用 dramatic_push，并配 hit/slap/thunder/boom/whoosh 音效。
- 钢笔、杯子、钥匙等小物件掉落：保留当前情绪镜头，并配 drop 音效，timestamp_ms 通常在 0-500。
- 内心独白、回忆、悲伤、沉默、雨夜压抑：camera 使用 melancholy_pan，通常不加重击音效。
- 场景开端、宗门/宫殿/山门/高楼展示、新角色初次登场或全身展示：camera 使用 establishing_tilt。
- timestamp_ms 按动作发生位置推算：动作先发生为 0-500；台词中段爆发按每秒 4-5 个汉字估算；结尾反转在分镜后 60%-80%。

输出格式示例：
{{
  "scenes": [
    {{
      "title": "山门受辱",
      "visual": "竖屏9:16，华山山门前，少年衣衫破旧跪在雨水里，几名弟子居高临下，冷色光影压住画面。",
      "dialogue": "弟子甲：废柴也配进内门？",
      "camera": "dramatic_push",
      "camera_speed": 1.35,
      "emotion": "屈辱、压迫",
      "characters": ["少年", "弟子甲"],
      "speaker": "弟子甲",
      "duration": 4.0,
      "audio_manifest": {{
        "bgm_style": "tense",
        "sfx_trigger": {{"file": "hit", "timestamp_ms": 900, "volume": 0.7}}
      }}
    }}
  ]
}}
用户剧本：
{script_with_hint}
""".strip()


def call_llm_script_storyboard(script: str, max_scenes: int, script_hint: str = "") -> list[StoryScene]:
    content = llm_client.chat(
        system_prompt=DIRECTOR_SYSTEM_PROMPT,
        user_prompt=script_storyboard_prompt(script, max_scenes, script_hint=script_hint),
        task="script_storyboard",
        temperature=0.3,
    )
    parsed = extract_json_object(content)
    raw_scenes = parsed.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("LLM JSON must contain a non-empty scenes array.")
    from scripts.run_workflow import coerce_scene
    return [coerce_scene(raw, idx) for idx, raw in enumerate(raw_scenes[:max_scenes], start=1)]
