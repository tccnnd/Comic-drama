from __future__ import annotations

import os
import re
from typing import Any

from backend.config_utils import coerce_float as _coerce_float
from backend.llm_hub import llm_client
from scripts.director_classifier import (
    DirectorClassificationError,
    apply_default_classification,
    apply_llm_classification,
    apply_rules_classification,
    classify_scenes_batch,
)
from scripts.rw_config import *  # noqa: F401,F403  - re-exports config constants
from scripts.rw_models import SceneValidationError, StoryScene
from scripts.rw_prompts import (
    DIRECTOR_SYSTEM_PROMPT,
    _call_llm_chat_content,
    anime_visual_prompt,
    call_llm_script_storyboard,
    extract_json_object,
    script_storyboard_prompt,
    storyboard_prompt,
)
from scripts.rw_styles import normalize_audio_manifest, normalize_crop_box
from scripts.rw_voice import infer_voice_profile, split_dialogue_speaker


def build_rule_storyboard(story: str) -> list[StoryScene]:
    compact_story = " ".join(story.strip().split())
    premise = (
        compact_story[:28] if compact_story else "一个被轻视的主角，在命运翻转前夕被推到悬崖边"
    )

    return [
        StoryScene(
            scene=1,
            duration=4.2,
            title="夜雨开局",
            visual=anime_visual_prompt(
                f"雨夜山门外，浑身狼狈的主角咬牙抬头，掌心攥着破损信物，镜头先给脸部特写再拉到宗门山阶，开场钩子：{premise}",
                title="夜雨开局",
                characters=["主角"],
                camera="slow_push_in",
                emotion="压抑",
            ),
            dialogue="主角：这一次，我不会再把自己交出去。",
            camera="slow_push_in",
            emotion="压抑",
            characters=["主角"],
            bg_color="0x182033",
            accent_color="0x4ea3ff",
        ),
        StoryScene(
            scene=2,
            duration=4.0,
            title="旧伤被翻开",
            visual=anime_visual_prompt(
                "昏黄灯下，桌面摊开残旧线索和门派旧卷，旁边闪过前世记忆的碎影，镜头切到主角指节发白，情绪开始抬升。",
                title="旧伤被翻开",
                characters=["主角"],
                camera="tilt_down",
                emotion="疑问",
            ),
            dialogue="主角：这些痕迹，和我记忆里的那一夜对上了。",
            camera="tilt_down",
            emotion="疑问",
            characters=["主角"],
            bg_color="0x211a2e",
            accent_color="0xb879ff",
        ),
        StoryScene(
            scene=3,
            duration=4.1,
            title="当众受辱",
            visual=anime_visual_prompt(
                "宗门广场，众人围观，反派居高临下地冷笑，主角被逼退半步却没有低头，镜头从反派嘴角切到主角眼神变化，冲突直线拉满。",
                title="当众受辱",
                characters=["主角", "反派"],
                camera="pan_left",
                emotion="压迫",
            ),
            dialogue="反派：你还敢回来？今天就让你彻底认清自己。",
            camera="pan_left",
            emotion="压迫",
            characters=["主角", "反派"],
            bg_color="0x2a2420",
            accent_color="0xffb347",
        ),
        StoryScene(
            scene=4,
            duration=4.3,
            title="力量苏醒",
            visual=anime_visual_prompt(
                "强光破开云层，主角体内的旧力量被激活，衣摆与发丝被风掀起，镜头做一次正面抬升，情绪从压抑转为爆发。",
                title="力量苏醒",
                characters=["主角"],
                camera="dramatic_reveal",
                emotion="觉醒",
            ),
            dialogue="主角：够了。接下来，该轮到我了。",
            camera="dramatic_reveal",
            emotion="觉醒",
            characters=["主角"],
            bg_color="0x14291f",
            accent_color="0x43d18d",
        ),
        StoryScene(
            scene=5,
            duration=4.4,
            title="第一集钩子",
            visual=anime_visual_prompt(
                "角色群像被拉开距离，主角站在前景，身后宗门灯火一盏盏亮起，镜头缓慢后撤，留下悬念和下一集的战斗预告。",
                title="第一集钩子",
                characters=["主角", "反派"],
                camera="slow_zoom_out",
                emotion="反转",
            ),
            dialogue="主角：从今天开始，规矩由我来改。",
            camera="slow_zoom_out",
            emotion="反转",
            characters=["主角", "反派"],
            bg_color="0x2b1d25",
            accent_color="0xff5d8f",
        ),
    ]


def _raw_scene_number(raw: dict[str, Any]) -> int | None:
    for key in ("scene", "order", "scene_id"):
        value = raw.get(key)
        if value in (None, ""):
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            if isinstance(value, str):
                match = re.search(r"(\d+)$", value.strip())
                if match:
                    number = int(match.group(1))
                else:
                    continue
            else:
                continue
        if number > 0:
            return number
    return None


def validate_scene(raw: dict[str, Any], index: int) -> None:
    if not isinstance(raw, dict):
        raise SceneValidationError(
            f"分镜 #{index} 不是 JSON 对象，实际类型 {type(raw).__name__}", {}, field="scene"
        )

    scene_number = _raw_scene_number(raw)
    if scene_number is None:
        raise SceneValidationError("缺失或非法的 scene/order 字段", raw, field="scene")

    visual = raw.get("visual") or raw.get("visual_prompt")
    if not isinstance(visual, str) or not visual.strip():
        raise SceneValidationError("visual 不能为空", raw, field="visual")

    duration_value = (
        raw.get("duration")
        if raw.get("duration") not in (None, "")
        else raw.get("duration_seconds")
    )
    try:
        duration = float(duration_value)
    except (TypeError, ValueError):
        raise SceneValidationError(f"duration 不是数字: {duration_value!r}", raw, field="duration")
    if duration <= 0:
        raise SceneValidationError(f"duration 必须 > 0，实际 {duration}", raw, field="duration")

    camera = raw.get("camera") or raw.get("camera_movement")
    if not isinstance(camera, str) or not camera.strip():
        raise SceneValidationError("camera 不能为空", raw, field="camera")

    emotion = raw.get("emotion")
    if not isinstance(emotion, str) or not emotion.strip():
        raise SceneValidationError("emotion 不能为空", raw, field="emotion")

    if "characters" not in raw or not isinstance(raw.get("characters"), list):
        raise SceneValidationError("characters 必须是数组", raw, field="characters")

    camera_speed = raw.get("camera_speed")
    try:
        camera_speed_value = float(camera_speed)
    except (TypeError, ValueError):
        raise SceneValidationError(
            f"camera_speed 不是数字: {camera_speed!r}", raw, field="camera_speed"
        )
    if not 0.35 <= camera_speed_value <= 3.0:
        raise SceneValidationError(
            f"camera_speed 超出范围: {camera_speed_value}", raw, field="camera_speed"
        )

    audio_manifest = raw.get("audio_manifest")
    if not isinstance(audio_manifest, dict):
        raise SceneValidationError("audio_manifest 必须是对象", raw, field="audio_manifest")
    sfx_trigger = audio_manifest.get("sfx_trigger")
    if not isinstance(sfx_trigger, dict):
        raise SceneValidationError(
            "audio_manifest.sfx_trigger 必须是对象", raw, field="audio_manifest.sfx_trigger"
        )


def make_failed_placeholder(
    raw: dict[str, Any], index: int, err: SceneValidationError
) -> StoryScene:
    safe_raw = dict(raw or {})
    try:
        safe_duration = float(safe_raw.get("duration_seconds") or safe_raw.get("duration") or 3.0)
    except (TypeError, ValueError):
        safe_duration = 3.0
    safe_duration = min(6.0, max(3.0, safe_duration))
    safe_raw["duration"] = safe_duration
    safe_raw["duration_seconds"] = safe_duration
    safe_raw["visual"] = str(
        safe_raw.get("visual") or safe_raw.get("visual_prompt") or "占位分镜"
    ).strip()
    safe_raw["visual_prompt"] = str(
        safe_raw.get("visual_prompt") or safe_raw.get("visual") or safe_raw["visual"]
    ).strip()
    safe_raw["dialogue"] = str(safe_raw.get("dialogue") or "")
    safe_raw["camera"] = (
        str(safe_raw.get("camera") or safe_raw.get("camera_movement") or "slow_push_in").strip()
        or "slow_push_in"
    )
    safe_raw["emotion"] = str(safe_raw.get("emotion") or "calm").strip() or "calm"
    safe_raw["characters"] = (
        safe_raw.get("characters") if isinstance(safe_raw.get("characters"), list) else []
    )
    safe_raw["camera_speed"] = safe_raw.get("camera_speed") or 1.0
    safe_raw["audio_manifest"] = normalize_audio_manifest(safe_raw.get("audio_manifest"))
    safe_raw["title"] = str(safe_raw.get("title") or "校验失败分镜").strip()
    safe_raw["speaker"] = str(safe_raw.get("speaker") or "").strip()
    safe_raw["voice_profile"] = str(safe_raw.get("voice_profile") or "")
    safe_raw["voice_engine"] = str(safe_raw.get("voice_engine") or "")
    safe_raw["voice_id"] = str(safe_raw.get("voice_id") or "")
    safe_raw["reference_audio_path"] = str(safe_raw.get("reference_audio_path") or "")
    safe_raw["reference_text"] = str(safe_raw.get("reference_text") or "")
    safe_raw["voice_emotion"] = str(safe_raw.get("voice_emotion") or safe_raw.get("emotion") or "")
    safe_raw["voice_rate"] = safe_raw.get("voice_rate") or 1.0
    safe_raw["voice_pitch"] = safe_raw.get("voice_pitch") or 0.0
    safe_raw["voice_volume"] = safe_raw.get("voice_volume") or 1.0
    safe_raw["rhythm_preset"] = str(safe_raw.get("rhythm_preset") or "balanced")
    safe_raw["sfx_type"] = str(safe_raw.get("sfx_type") or "auto")
    safe_raw["subtitle_preset"] = str(safe_raw.get("subtitle_preset") or "standard")
    safe_raw["camera_intensity"] = safe_raw.get("camera_intensity") or 1.0
    safe_raw["episode_rhythm"] = str(safe_raw.get("episode_rhythm") or "classic_four_act")
    safe_raw["episode_phase"] = str(safe_raw.get("episode_phase") or "setup")
    try:
        phase_index = int(safe_raw.get("episode_phase_index") or index)
    except (TypeError, ValueError):
        phase_index = index
    try:
        phase_total = int(safe_raw.get("episode_phase_total") or max(index, 1))
    except (TypeError, ValueError):
        phase_total = max(index, 1)
    safe_raw["episode_phase_index"] = max(1, phase_index)
    safe_raw["episode_phase_total"] = max(1, phase_total)

    scene = coerce_scene(safe_raw, index)
    scene.validation_failed = True
    scene.error_message = err.to_error_message()
    scene.raw_llm_output = dict(raw or {})
    return scene


def _apply_director_rule_recommendation(scene: StoryScene) -> None:
    text = " ".join(
        str(part or "").strip()
        for part in [
            scene.title,
            scene.visual,
            scene.dialogue,
            scene.speaker,
            " ".join(scene.characters or []),
            scene.emotion,
            scene.camera,
        ]
        if str(part or "").strip()
    ).lower()

    def has(*tokens: str) -> bool:
        return any(token.lower() in text for token in tokens)

    camera = str(scene.camera or "").strip().lower()
    if has(
        "震惊", "愤怒", "对峙", "反转", "揭露", "爆发", "冲突", "撞", "打", "雷", "刀", "dramatic"
    ):
        camera_movement = "dramatic_push"
    elif (
        has("悲", "哭", "回忆", "沉默", "雨", "压抑", "独白", "melancholy")
        or camera == "melancholy_pan"
    ):
        camera_movement = "melancholy_pan"
    elif (
        has("场景", "开端", "登场", "全景", "环境", "宗门", "宫殿", "山门", "高楼", "establish")
        or camera == "establishing_tilt"
    ):
        camera_movement = "establishing_tilt"
    elif camera == "slow_zoom_out":
        camera_movement = "pull_back"
    elif camera == "slow_push_in":
        camera_movement = "slow_push"
    else:
        camera_movement = "static"

    if has("怒", "火", "气", "愤"):
        emotion_tone = "anger"
    elif has("悲", "哭", "泪", "伤", "难过", "失落"):
        emotion_tone = "sadness"
    elif has("喜", "笑", "高兴", "开心", "兴奋"):
        emotion_tone = "joy"
    elif has("惊", "震", "愣", "错愕"):
        emotion_tone = "surprise"
    elif has("怕", "恐", "害怕", "惊恐"):
        emotion_tone = "fear"
    elif has("紧", "压", "危机", "对峙", "逼", "张"):
        emotion_tone = "tension"
    elif has("平静", "冷静", "日常", "安静", "calm"):
        emotion_tone = "calm"
    else:
        emotion_tone = "neutral"

    manifest = scene.audio_manifest if isinstance(scene.audio_manifest, dict) else {}
    sfx_trigger = manifest.get("sfx_trigger") if isinstance(manifest, dict) else {}
    sfx_file = str(sfx_trigger.get("file") if isinstance(sfx_trigger, dict) else "").strip().lower()
    if sfx_file in {"boom", "drop", "whoosh", "thunder", "hit"}:
        sfx_type = sfx_file
    elif has("雷", "闪电"):
        sfx_type = "thunder"
    elif has("爆", "撞", "砸", "拍桌", "击"):
        sfx_type = "boom" if has("爆") else "hit"
    elif has("掉", "落", "轻响"):
        sfx_type = "drop"
    elif has("风", "转身", "掠过", "whoosh"):
        sfx_type = "whoosh"
    else:
        sfx_type = "none"

    characters_count = len(scene.characters or [])
    if has("环境", "空镜", "远景", "建筑", "场景", "山门", "宫殿", "高楼"):
        scene_intent = "establishing"
    elif characters_count >= 3:
        scene_intent = "group"
    elif characters_count == 2 or has("对话", "对视", "交谈", "问", "答", "台词"):
        scene_intent = "dialogue"
    elif has("动作", "打斗", "冲突", "击", "撞", "追", "跑"):
        scene_intent = "action"
    elif has("反应", "表情", "回头", "愣", "看向", "惊讶"):
        scene_intent = "reaction"
    else:
        scene_intent = "transition"

    duration = float(scene.duration or 4.0)
    if duration <= 3.6 or camera_movement == "dramatic_push" or scene_intent == "action":
        pacing = "fast"
    elif duration >= 5.0 or camera_movement in {"melancholy_pan", "establishing_tilt", "pull_back"}:
        pacing = "slow"
    else:
        pacing = "medium"

    if has("环境", "空镜", "建筑", "山门", "宫殿", "高楼") or not scene.characters:
        subject_focus = "environment"
    elif characters_count >= 3:
        subject_focus = "group"
    elif characters_count == 2 or has("对视", "对话", "双人"):
        subject_focus = "two_shot"
    else:
        subject_focus = "single_character"

    scene.camera_movement = camera_movement
    scene.emotion_tone = emotion_tone
    scene.sfx_type = sfx_type
    scene.scene_intent = scene_intent
    scene.pacing = pacing
    scene.subject_focus = subject_focus


def _apply_director_classification_to_scenes(
    scenes: list[StoryScene], model: str | None = None
) -> None:
    """Apply director classification to scenes.

    Uses rule-based classification by default for speed.
    Set DIRECTOR_USE_LLM=1 in .env to use LLM classification (slower but more accurate).
    """
    use_llm = os.environ.get("DIRECTOR_USE_LLM", "0").strip().lower() in {"1", "true", "yes"}

    if not use_llm:
        # Fast path: rule-based classification (instant)
        for scene in scenes:
            if getattr(scene, "validation_failed", False):
                apply_default_classification(scene, reason="validation_failed")
                continue
            try:
                apply_rules_classification(scene, _apply_director_rule_recommendation)
            except Exception as exc:
                apply_default_classification(scene, reason=str(exc))
        return

    # Slow path: LLM classification
    model_name = (model or os.environ.get("LLM_MODEL", "").strip()).strip()
    eligible: list[tuple[int, StoryScene]] = [
        (index, scene)
        for index, scene in enumerate(scenes)
        if not getattr(scene, "validation_failed", False)
    ]

    for batch_start in range(0, len(eligible), 10):
        batch = eligible[batch_start : batch_start + 10]
        if not batch:
            continue
        batch_scenes = [scene for _, scene in batch]
        try:
            classifications = classify_scenes_batch(
                batch_scenes,
                call_llm_fn=_call_llm_chat_content,
                model=model_name,
            )
            for scene, classification in zip(batch_scenes, classifications):
                apply_llm_classification(scene, classification, model_name=model_name)
        except DirectorClassificationError as exc:
            print(f"[director] LLM classification failed, falling back to rules: {exc}")
            for _, scene in batch:
                try:
                    apply_rules_classification(
                        scene, _apply_director_rule_recommendation, reason=str(exc)
                    )
                except Exception as rule_exc:
                    apply_default_classification(scene, reason=str(rule_exc))
        except Exception as exc:
            print(
                f"[director] Unexpected director classification error, falling back to rules: {exc}"
            )
            for _, scene in batch:
                try:
                    apply_rules_classification(
                        scene, _apply_director_rule_recommendation, reason=f"unexpected: {exc}"
                    )
                except Exception as rule_exc:
                    apply_default_classification(scene, reason=str(rule_exc))

    for scene in scenes:
        if getattr(scene, "director_meta", None) is None:
            apply_default_classification(scene, reason="validation_failed, skipped classification")


def coerce_scene(raw: dict, index: int) -> StoryScene:
    bg_color, accent_color = DEFAULT_PALETTE[(index - 1) % len(DEFAULT_PALETTE)]
    duration = float(raw.get("duration") or raw.get("duration_seconds") or 4.0)
    duration = min(6.0, max(3.0, duration))

    characters = raw.get("characters") or []
    if not isinstance(characters, list):
        characters = [str(characters)]
    characters = [str(item).strip() for item in characters if str(item).strip()]

    dialogue_speaker = split_dialogue_speaker(str(raw.get("dialogue") or ""))[0]
    speaker = str(
        raw.get("speaker") or dialogue_speaker or (characters[0] if len(characters) == 1 else "")
    )
    voice_profile = str(raw.get("voice_profile") or infer_voice_profile(speaker, characters))

    return StoryScene(
        scene=index,
        duration=duration,
        title=str(raw.get("title") or f"第{index}幕")[:24],
        visual=str(
            raw.get("visual")
            or raw.get("visual_prompt")
            or "竖屏动漫番剧分镜，角色在强情绪场景中对峙，光影对比鲜明。"
        ),
        dialogue=str(raw.get("dialogue") or "主角：这一次，我不会再退。"),
        camera=str(raw.get("camera") or raw.get("camera_movement") or "slow_push_in"),
        emotion=str(raw.get("emotion") or "压抑"),
        characters=characters or ["主角"],
        bg_color=str(raw.get("bg_color") or bg_color),
        accent_color=str(raw.get("accent_color") or accent_color),
        speaker=speaker,
        voice_profile=voice_profile,
        voice_engine=str(raw.get("voice_engine") or ""),
        voice_id=str(raw.get("voice_id") or ""),
        reference_audio_path=str(raw.get("reference_audio_path") or ""),
        reference_text=str(raw.get("reference_text") or ""),
        voice_emotion=str(raw.get("voice_emotion") or raw.get("emotion") or ""),
        voice_rate=_coerce_float(raw.get("voice_rate"), 1.0, 0.5, 2.0),
        voice_pitch=_coerce_float(raw.get("voice_pitch"), 0.0, -24.0, 24.0),
        voice_volume=_coerce_float(raw.get("voice_volume"), 1.0, 0.1, 3.0),
        rhythm_preset=str(raw.get("rhythm_preset") or "balanced"),
        sfx_type=str(raw.get("sfx_type") or "auto"),
        audio_manifest=normalize_audio_manifest(raw.get("audio_manifest")),
        subtitle_preset=str(raw.get("subtitle_preset") or "standard"),
        camera_intensity=_coerce_float(raw.get("camera_intensity"), 1.0, 0.1, 3.0),
        camera_speed=_coerce_float(raw.get("camera_speed"), 1.0, 0.35, 3.0),
        crop_box=normalize_crop_box(raw.get("crop_box")),
        character_descriptions=str(raw.get("character_descriptions") or ""),
        character_references=(
            raw.get("character_references")
            if isinstance(raw.get("character_references"), list)
            else []
        ),
        primary_reference_image_path=str(raw.get("primary_reference_image_path") or ""),
        primary_reference_image_abs_path=str(raw.get("primary_reference_image_abs_path") or ""),
    )


def call_llm_storyboard(story: str, scene_count: int) -> list[StoryScene]:
    content = llm_client.chat(
        system_prompt=DIRECTOR_SYSTEM_PROMPT,
        user_prompt=storyboard_prompt(story, scene_count),
        task="storyboard",
        temperature=0.7,
    )
    parsed = extract_json_object(content)
    raw_scenes = parsed.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("LLM JSON must contain a non-empty scenes array.")
    scenes: list[StoryScene] = []
    for idx, raw in enumerate(raw_scenes[:scene_count], start=1):
        try:
            validate_scene(raw, idx)
            scenes.append(coerce_scene(raw, idx))
        except SceneValidationError as exc:
            print(f"[planner] Scene {idx} validation failed: {exc.to_error_message()}")
            scenes.append(make_failed_placeholder(raw if isinstance(raw, dict) else {}, idx, exc))
        except Exception as exc:
            fallback = raw if isinstance(raw, dict) else {}
            print(f"[planner] Scene {idx} coercion failed: {exc}")
            scenes.append(
                make_failed_placeholder(
                    fallback,
                    idx,
                    SceneValidationError(f"分镜转换失败: {exc}", fallback),
                )
            )
    return scenes


def build_storyboard(story: str, planner: str, scene_count: int) -> tuple[list[StoryScene], str]:
    if planner == "rule":
        scenes = build_rule_storyboard(story)
        _apply_director_classification_to_scenes(scenes)
        return scenes, "rule"
    if planner == "llm":
        scenes = call_llm_storyboard(story, scene_count)
        _apply_director_classification_to_scenes(scenes)
        return scenes, "llm"

    try:
        scenes = call_llm_storyboard(story, scene_count)
        _apply_director_classification_to_scenes(scenes)
        return scenes, "llm"
    except Exception as exc:
        print(f"[planner] LLM unavailable, falling back to rule planner: {exc}")
        scenes = build_rule_storyboard(story)
        _apply_director_classification_to_scenes(scenes)
        return scenes, "rule"


# --- Script analysis helpers (effective override versions) ---


def _clean_script_label(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"^(?:\[[^\]]{1,12}\]|【[^】]{1,12}】)\s*", "", text)
    text = re.sub(r"[（(][^（）()]{0,18}[）)]\s*$", "", text)
    text = text.strip(" \t\r\n:：-—–－[]【】《》「」『』")
    if "/" in text or "／" in text:
        text = next((part.strip() for part in re.split(r"[/／]", text) if part.strip()), text)
    return text.strip()


def _looks_like_speaker_label(line: str) -> bool:
    candidate = _clean_script_label(line)
    if not candidate or len(candidate) > 16:
        return False
    if candidate in SCRIPT_ROLE_IGNORE:
        return False
    if candidate.startswith(("AI漫剧剧本", "第", "场景", "镜头", "分镜")):
        return False
    if any(
        token in candidate
        for token in (
            "剧本",
            "标题",
            "类型",
            "作者",
            "编剧",
            "提示",
            "提示词",
            "画面",
            "氛围",
            "音效",
            "说明",
            "备注",
            "简介",
            "梗概",
        )
    ):
        return False
    if any(char in candidate for char in "，。！？；;,.!?：:—-（）()[]【】《》「」『』 "):
        return False
    return bool(SCRIPT_SPEAKER_TOKEN_RE.match(candidate))


def _looks_like_scene_heading(line: str) -> tuple[str, str] | None:
    raw = str(line or "").strip().lstrip("【［[")
    raw = raw.rstrip("】］]")
    if _is_script_cue_line(raw):
        return None
    fallback = SCRIPT_HEADING_FALLBACK_RE.match(raw)
    if fallback:
        index = str(fallback.group("number") or fallback.group("label_number") or "").strip()
        if fallback.group("hash"):
            title = str(fallback.group("hash") or "").lstrip("#").strip()
        else:
            title = str(fallback.group("trailing") or "").strip()
            title = re.sub(r"^\s*[:：\-—、.．]\s*", "", title).strip()
        return index, title or raw
    match = SCRIPT_HEADING_RE.match(raw)
    if not match:
        return None
    index = str(match.group("index") or match.group("scene_index") or "").strip()
    title = raw
    if raw.startswith("#"):
        title = raw.lstrip("#").strip()
    elif "场景" in raw or "镜头" in raw:
        title = re.sub(r"^\s*(?:场景|镜头)\s*\d{1,3}\s*[:：\-—]?\s*", "", raw).strip()
    elif index:
        title = re.sub(
            r"^\s*第\s*[\d一二三四五六七八九十百]{1,6}\s*(?:场|幕|节|镜头)\s*[:：\-—]?\s*", "", raw
        ).strip()
    return index, title


def _split_script_dialogue(line: str) -> tuple[str, str]:
    stripped = str(line or "").strip()
    if not stripped:
        return "", ""
    if _looks_like_scene_heading(stripped) or _is_script_cue_line(stripped):
        return "", stripped
    for separator in SCRIPT_DIALOGUE_SEPARATORS:
        if separator not in stripped:
            continue
        speaker, spoken = stripped.split(separator, 1)
        speaker = _clean_script_label(speaker)
        spoken = spoken.strip()
        if speaker and spoken and _looks_like_speaker_label(speaker):
            return speaker, spoken
    return "", stripped


def _is_script_cue_line(line: str) -> bool:
    stripped = str(line or "").strip()
    if not stripped:
        return False
    return stripped.startswith(
        ("(", "（", "[", "【", "「", "『", "*", "﹙", "《")
    ) and stripped.endswith((")", "）", "]", "】", "」", "』", "*", "﹚", "》"))


def _normalize_script_lines(script: str) -> list[str]:
    raw_lines = str(script or "").replace("\r\n", "\n").replace("\r", "\n").splitlines()
    normalized: list[str] = []
    index = 0
    while index < len(raw_lines):
        stripped = raw_lines[index].strip()
        if not stripped:
            normalized.append("")
            index += 1
            continue

        if (
            _looks_like_scene_heading(stripped)
            or _is_script_cue_line(stripped)
            or _split_script_dialogue(stripped)[0]
        ):
            normalized.append(stripped)
            index += 1
            continue

        next_line = raw_lines[index + 1].strip() if index + 1 < len(raw_lines) else ""
        if (
            _looks_like_speaker_label(stripped)
            and next_line
            and not _looks_like_scene_heading(next_line)
            and not _is_script_cue_line(next_line)
        ):
            normalized.append(f"{_clean_script_label(stripped)}：{next_line}")
            index += 2
            continue

        chunks = [
            chunk.strip()
            for chunk in re.split(r"(?<=[。！？!?；;…])\s*", stripped)
            if chunk.strip()
        ]
        if len(chunks) > 1 and len(stripped) > 100:
            normalized.extend(chunks)
        else:
            normalized.append(stripped)
        index += 1
    return normalized


def _script_block_char_count(block: list[str]) -> int:
    return sum(len(line) for line in block)


def _split_script_paragraphs(script: str) -> list[list[str]]:
    paragraphs: list[list[str]] = []
    current: list[str] = []
    for line in _normalize_script_lines(script.strip()):
        if not line:
            if current:
                paragraphs.append(current)
                current = []
            continue

        is_heading = _looks_like_scene_heading(line) is not None
        is_dialogue = bool(_split_script_dialogue(line)[0])
        is_cue = _is_script_cue_line(line)
        dialogue_count = sum(1 for item in current if _split_script_dialogue(item)[0])
        should_start_new = False

        if current and is_heading:
            should_start_new = True
        elif current and not is_dialogue and not is_cue and dialogue_count >= 2:
            should_start_new = True
        elif current and _script_block_char_count(current) >= 420:
            should_start_new = True

        if should_start_new:
            paragraphs.append(current)
            current = []
        current.append(line)

    if current:
        paragraphs.append(current)
    return _merge_script_shot_blocks(paragraphs)


def _is_storyboard_shot_heading(line: str) -> bool:
    stripped = str(line or "").strip().strip("【】[]")
    return bool(
        re.match(
            r"^(?:分镜|镜头|shot)\s*[0-9一二三四五六七八九十百两]{1,6}\b", stripped, re.IGNORECASE
        )
    )


def _merge_script_shot_blocks(blocks: list[list[str]]) -> list[list[str]]:
    merged: list[list[str]] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        if (
            len(block) == 1
            and _is_storyboard_shot_heading(block[0])
            and index + 1 < len(blocks)
            and not _is_storyboard_shot_heading(blocks[index + 1][0] if blocks[index + 1] else "")
        ):
            merged.append([*block, *blocks[index + 1]])
            index += 2
            continue
        merged.append(block)
        index += 1
    return merged


def _strip_brackets(text: str) -> str:
    return text.strip().strip(" \t\r\n[]()（）【】「」“”*＊")


def _merge_script_text(lines: list[str]) -> str:
    return " ".join(line.strip() for line in lines if line.strip())


def _infer_script_camera(text: str) -> str:
    lowered = text.lower()
    for tokens, camera in SCRIPT_CAMERA_RULES:
        if any(token.lower() in lowered for token in tokens):
            return camera
    return "slow_push_in"


def _infer_script_emotion(text: str) -> str:
    for tokens, emotion in SCRIPT_EMOTION_RULES:
        if any(token in text for token in tokens):
            return emotion
    return "neutral"


def _derive_script_scene_title(
    index: int, heading: str, visual_lines: list[str], dialogue_lines: list[str]
) -> str:
    heading = heading.strip()
    if heading:
        return heading[:24]
    for source in (visual_lines, dialogue_lines):
        for line in source:
            clean = re.sub(r"[【】\[\]（）()】【：:，。！？!?、\s]+", " ", line).strip()
            if clean:
                return clean[:20]
    return f"第{index}场"


def _build_scene_block(index: int, block_lines: list[str], max_scenes: int) -> dict[str, object]:
    heading = ""
    visual_lines: list[str] = []
    dialogue_lines: list[str] = []
    characters: list[str] = []
    speaker = ""
    camera_hint = ""
    emotion_hint = ""

    remaining_lines = list(block_lines)
    maybe_heading = _looks_like_scene_heading(remaining_lines[0]) if remaining_lines else None
    if maybe_heading:
        _, heading = maybe_heading
        remaining_lines = remaining_lines[1:]

    for line in remaining_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _is_script_cue_line(stripped):
            cue = _strip_brackets(stripped)
            if cue:
                visual_lines.append(cue)
                camera_hint = camera_hint or _infer_script_camera(cue)
                emotion_hint = emotion_hint or _infer_script_emotion(cue)
            continue

        line_speaker, spoken = _split_script_dialogue(stripped)
        if line_speaker:
            speaker = speaker or line_speaker
            if line_speaker not in characters and line_speaker not in SCRIPT_ROLE_IGNORE:
                characters.append(line_speaker)
            dialogue_lines.append(f"{line_speaker}：{spoken}")
            emotion_hint = emotion_hint or _infer_script_emotion(spoken)
            continue

        if stripped not in {"", "—", "–", "-", "……"}:
            visual_lines.append(stripped)
            camera_hint = camera_hint or _infer_script_camera(stripped)
            emotion_hint = emotion_hint or _infer_script_emotion(stripped)

    scene_text = _merge_script_text(block_lines)
    if not speaker and characters:
        speaker = characters[0]
    if not speaker and dialogue_lines:
        speaker = _split_script_dialogue(dialogue_lines[0])[0]

    title = _derive_script_scene_title(index, heading, visual_lines, dialogue_lines)
    visual_prompt = anime_visual_prompt(
        "，".join(item for item in [heading, *visual_lines] if item),
        title=title,
        characters=characters,
        camera=camera_hint or "slow_push_in",
        emotion=emotion_hint or "neutral",
    )
    dialogue = "\n".join(dialogue_lines).strip()
    if not dialogue and scene_text:
        dialogue = scene_text[:120]

    duration = 3.2
    duration += min(2.0, len(dialogue) / 80.0)
    duration += min(1.2, len(visual_lines) * 0.25)
    duration = max(3.0, min(7.0, duration))

    return {
        "title": title,
        "visual": visual_prompt[:500],
        "dialogue": dialogue[:500],
        "camera": camera_hint or "slow_push_in",
        "emotion": emotion_hint or "neutral",
        "characters": characters[:4],
        "speaker": speaker,
        "duration": duration,
    }


def _compress_script_blocks(blocks: list[list[str]], max_scenes: int) -> list[list[str]]:
    if max_scenes <= 0 or len(blocks) <= max_scenes:
        return blocks
    head = blocks[: max_scenes - 1]
    tail = [line for block in blocks[max_scenes - 1 :] for line in block]
    return head + [tail]


def build_rule_script_storyboard(script: str, max_scenes: int = 12) -> list[StoryScene]:
    compact = script.strip()
    if not compact:
        return build_rule_storyboard(script)

    blocks = _split_script_paragraphs(compact)
    if not blocks:
        return build_rule_storyboard(script)

    if len(blocks) == 1 and len(blocks[0]) > 1:
        line_blocks = [[line] for line in blocks[0] if str(line).strip()]
        if len(line_blocks) >= 2:
            blocks = line_blocks

    shot_blocks = [block for block in blocks if block and _is_storyboard_shot_heading(block[0])]
    if len(shot_blocks) >= 2:
        blocks = shot_blocks

    blocks = _compress_script_blocks(blocks, max_scenes)
    parsed: list[StoryScene] = []
    for index, block in enumerate(blocks, start=1):
        raw = _build_scene_block(index, block, max_scenes)
        parsed.append(coerce_scene(raw, index))
    return parsed


def build_script_storyboard(
    script: str,
    planner: str,
    max_scenes: int = 12,
    script_hint: str = "",
) -> tuple[list[StoryScene], str]:
    if planner == "rule":
        scenes = build_rule_script_storyboard(script, max_scenes=max_scenes)
        _apply_director_classification_to_scenes(scenes)
        return scenes, "rule"
    if planner == "llm":
        scenes = call_llm_script_storyboard(script, max_scenes=max_scenes, script_hint=script_hint)
        _apply_director_classification_to_scenes(scenes)
        return scenes, "llm"

    try:
        scenes = call_llm_script_storyboard(script, max_scenes=max_scenes, script_hint=script_hint)
        _apply_director_classification_to_scenes(scenes)
        return scenes, "llm"
    except Exception as exc:
        print(
            f"[planner] LLM unavailable for script recognition, falling back to rule planner: {exc}"
        )
        scenes = build_rule_script_storyboard(script, max_scenes=max_scenes)
        _apply_director_classification_to_scenes(scenes)
        return scenes, "rule"


def _collect_script_role_counts(script: str) -> dict[str, dict[str, object]]:
    counts: dict[str, dict[str, object]] = {}
    for scene_index, block in enumerate(_split_script_paragraphs(script), start=1):
        for line in block:
            speaker, spoken = _split_script_dialogue(line)
            if not speaker or speaker in SCRIPT_ROLE_IGNORE:
                continue
            item = counts.setdefault(
                speaker,
                {
                    "name": speaker,
                    "mentions": 0,
                    "first_scene": scene_index,
                    "dialogue_chars": 0,
                },
            )
            item["mentions"] = int(item["mentions"]) + 1
            item["dialogue_chars"] = int(item["dialogue_chars"]) + len(spoken)
            item["first_scene"] = min(int(item["first_scene"]), scene_index)
    return counts


def _event_summary_lines(block: list[str]) -> tuple[list[str], list[str], list[str]]:
    title = ""
    visual_lines: list[str] = []
    dialogue_lines: list[str] = []
    remaining_lines = list(block)
    maybe_heading = _looks_like_scene_heading(remaining_lines[0]) if remaining_lines else None
    if maybe_heading:
        _, title = maybe_heading
        remaining_lines = remaining_lines[1:]

    for line in remaining_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _is_script_cue_line(stripped):
            cue = _strip_brackets(stripped)
            if cue:
                visual_lines.append(cue)
            continue
        speaker, spoken = _split_script_dialogue(stripped)
        if speaker:
            dialogue_lines.append(f"{speaker}：{spoken}")
            continue
        visual_lines.append(stripped)
    return [title], visual_lines, dialogue_lines


def analyze_script_text(script: str, max_events: int = 12) -> dict[str, object]:
    paragraphs = _split_script_paragraphs(script)
    role_counts = _collect_script_role_counts(script)
    events: list[dict[str, object]] = []
    format_summary = {
        "heading_count": 0,
        "dialogue_line_count": 0,
        "cue_count": 0,
        "narrative_line_count": 0,
    }
    warnings: list[str] = []

    if not paragraphs:
        return {
            "mode": "rule",
            "source_length": len(script),
            "roles": [],
            "events": [],
            "event_count": 0,
            "role_count": 0,
            "format_summary": format_summary,
            "warnings": ["未识别到有效内容，请粘贴剧本或小说正文。"],
        }

    for block in paragraphs:
        if block and _looks_like_scene_heading(block[0]):
            format_summary["heading_count"] += 1
        for line in block:
            if _is_script_cue_line(line):
                format_summary["cue_count"] += 1
                continue
            speaker, _spoken = _split_script_dialogue(line)
            if speaker:
                format_summary["dialogue_line_count"] += 1
            else:
                format_summary["narrative_line_count"] += 1

    compressed = _compress_script_blocks(paragraphs, max_events)
    for index, block in enumerate(compressed, start=1):
        title_parts, visual_lines, dialogue_lines = _event_summary_lines(block)
        title = next((part for part in title_parts if part.strip()), "") or f"事件 {index}"
        summary_source = " ".join([*visual_lines, *dialogue_lines]).strip()
        characters: list[str] = []
        for line in block:
            speaker, _spoken = _split_script_dialogue(line)
            if speaker and speaker not in SCRIPT_ROLE_IGNORE and speaker not in characters:
                characters.append(speaker)
        events.append(
            {
                "event_id": f"e_{index:03d}",
                "index": index,
                "title": title[:32],
                "summary": (summary_source or title)[:240],
                "camera": _infer_script_camera(summary_source or title),
                "emotion": _infer_script_emotion(summary_source or title),
                "characters": characters[:6],
                "dialogue": "\n".join(dialogue_lines)[:400],
                "source_lines": list(block),
            }
        )

    roles = sorted(
        role_counts.values(),
        key=lambda item: (
            -int(item.get("mentions", 0)),
            int(item.get("first_scene", 0)),
            str(item.get("name", "")),
        ),
    )
    for role in roles:
        name = str(role.get("name") or "")
        mentions = max(1, int(role.get("mentions", 0)))
        dialogue_chars = int(role.get("dialogue_chars", 0))
        role["voice_profile"] = infer_voice_profile(name, [name])
        role["emotion"] = _infer_script_emotion(name)
        role["suggested_voice_engine"] = "edge"
        role["importance"] = round(min(100.0, mentions * 18 + dialogue_chars / 12.0), 1)
        role["summary"] = f"{mentions} 次提及，首见于第 {int(role.get('first_scene', 0))} 段"

    if len(paragraphs) > len(compressed):
        warnings.append(f"已将 {len(paragraphs)} 个段落压缩为 {len(compressed)} 个预览镜头。")
    if not role_counts:
        warnings.append("未识别到明确角色，可能是纯叙述文本或台词格式较松散。")
    if format_summary["dialogue_line_count"] == 0:
        warnings.append("未识别到明确台词行，请优先使用“角色：台词”的格式。")

    return {
        "mode": "rule",
        "source_length": len(script),
        "roles": roles,
        "events": events,
        "event_count": len(events),
        "role_count": len(roles),
        "format_summary": format_summary,
        "warnings": warnings,
    }


def validate_script_text(script: str) -> None:
    text = str(script or "").strip()
    if not text:
        raise ValueError("Script text is required.")
    if not is_script_text_garbled(text):
        return
    if re.search(r"[\u4e00-\u9fffA-Za-z]", text):
        return
    damaged_marks = text.count("?") + text.count("�")
    if damaged_marks >= max(4, len(text) // 5):
        raise ValueError("剧本文本疑似编码损坏：请重新从原始来源粘贴，不要使用已经变成 ? 的内容。")


def is_script_text_garbled(script: str) -> bool:
    text = str(script or "").strip()
    if not text:
        return False
    if re.search(r"[\u4e00-\u9fffA-Za-z]", text):
        return False
    damaged_marks = text.count("?") + text.count("�")
    return damaged_marks >= max(4, len(text) // 5)


def analyze_script_workflow(
    script: str,
    planner: str,
    max_scenes: int = 12,
    script_hint: str = "",
) -> tuple[dict[str, object], list[StoryScene], str]:
    validate_script_text(script)
    analysis = analyze_script_text(script, max_events=max_scenes)
    scenes, planner_used = build_script_storyboard(
        script, planner, max_scenes=max_scenes, script_hint=script_hint
    )
    analysis["planner_used"] = planner_used
    if script_hint.strip():
        analysis["script_hint"] = script_hint.strip()
    analysis["scenes"] = [
        {
            "scene_id": f"scene_{order:03d}",
            "index": order,
            "title": scene.title,
            "camera": scene.camera,
            "emotion": scene.emotion,
            "characters": list(scene.characters),
            "speaker": scene.speaker or "",
            "dialogue": scene.dialogue,
            "visual": scene.visual,
            "duration": scene.duration,
        }
        for order, scene in enumerate(scenes, start=1)
    ]
    return analysis, scenes, planner_used
