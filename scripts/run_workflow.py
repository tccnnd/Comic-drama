from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import re
import subprocess
import shutil
import wave
import textwrap
import time
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from typing import Any

try:
    import imageio_ffmpeg
except ImportError:  # pragma: no cover - optional runtime dependency
    imageio_ffmpeg = None
from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont
try:
    import pyttsx3
except ImportError:  # pragma: no cover - optional runtime dependency
    pyttsx3 = None

from scripts import tts_engines
from scripts.director_classifier import (
    DirectorClassificationError,
    VISUAL_CONTENT_FIELDS,
    apply_default_classification,
    apply_llm_classification,
    apply_rules_classification,
    build_director_plan,
    build_shot_visual_content,
    classify_scenes_batch,
)
from scripts.bgm_matcher import select_bgm_for_scene
from scripts.comfyui_patcher import patch_workflow
from scripts.prompt_compiler import PromptCompiler, find_project_root
from scripts.subtitle_style import build_ass_document
from scripts.comfyui_ssh_tunnel import ensure_comfyui_tunnel
from scripts.video_provider_adapters import VideoRenderRequest, render_remote_video_provider
from video_providers import get_video_provider_spec, normalize_video_provider as resolve_video_provider_name
from backend.video_generation import VideoGenerationResult, generation_meta_from_result, video_fallback_mode

edge_tts = tts_engines.edge_tts


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORY = ROOT / "inputs" / "sample_story.txt"
OUTPUTS = ROOT / "outputs"
WORKFLOWS = ROOT / "workflows"
AUDIO_ASSETS = ROOT / "assets" / "audio"
AUDIO_ASSET_EXTENSIONS = (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg")
DEFAULT_PALETTE = [
    ("0x182033", "0x4ea3ff"),
    ("0x211a2e", "0xb879ff"),
    ("0x2a2420", "0xffb347"),
    ("0x14291f", "0x43d18d"),
    ("0x2b1d25", "0xff5d8f"),
    ("0x1d2430", "0xffd166"),
    ("0x102824", "0x2dd4bf"),
    ("0x271a1a", "0xff6b6b"),
]

DEFAULT_SUBTITLE_STYLE = {
    "font_name": "Microsoft YaHei",
    "font_size": 34,
    "margin_v": 120,
    "outline": 2,
    "shadow": 0,
    "alignment": 2,
    "show_speaker": True,
    "burn_in": True,
}

DEFAULT_AUDIO_STYLE = {
    "master_lufs": -16.0,
    "true_peak": -1.5,
    "loudness_range": 11.0,
    "limiter_level": 0.98,
    "bgm_path": "",
    "bgm_gain_db": -18.0,
    "duck_threshold": 0.08,
    "duck_ratio": 8.0,
    "duck_attack_ms": 20,
    "duck_release_ms": 250,
}
DEFAULT_AUDIO_MANIFEST = {
    "bgm_style": "",
    "bgm_file": "",
    "bgm_gain_db": "",
    "sfx_trigger": {"file": "", "timestamp_ms": 0, "volume": 0.65},
    "sfx_triggers": [],
}
DEFAULT_CROP_BOX = {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}
MIN_CROP_BOX_SIZE = 0.05

EPISODE_PHASES = ("opening", "setup", "reversal", "finale")
DEFAULT_EPISODE_PACING = {
    "preset": "classic_four_act",
    "auto_assign": True,
    "phase_order": list(EPISODE_PHASES),
}


def get_ffmpeg_exe() -> str:
    if imageio_ffmpeg is not None:
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    raise RuntimeError("FFmpeg executable not found. Install imageio-ffmpeg or add ffmpeg to PATH.")


DEFAULT_SUBPROCESS_TIMEOUTS = {
    "ffprobe": 15,
    "tts": 90,
    "ffmpeg_audio": 60,
    "ffmpeg_render": 180,
    "ffmpeg_concat": 300,
    "comfyui": 180,
}


def render_timeout(duration_seconds: float) -> int:
    return max(60, min(600, int(float(duration_seconds) * 8 + 30)))


def concat_timeout(item_count: int) -> int:
    return max(DEFAULT_SUBPROCESS_TIMEOUTS["ffmpeg_concat"], min(900, DEFAULT_SUBPROCESS_TIMEOUTS["ffmpeg_concat"] + max(0, item_count) * 10))


def _stderr_excerpt(stderr: str | None, limit: int = 4000) -> str:
    text = str(stderr or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def run_guarded(
    cmd: list[str],
    *,
    cwd: Path | str | None = None,
    timeout: int | float | None = None,
    stage: str = "command",
) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
        raise RuntimeError(f"{stage} timed out after {timeout}s: {' '.join(str(item) for item in cmd[:6])}")
    if proc.returncode != 0:
        raise RuntimeError(f"{stage} failed with exit code {proc.returncode}:\n{_stderr_excerpt(stderr)}")
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)

ANIME_STYLE_SUFFIX = (
    "日系番剧风格，像真正的动画正片而不是解说稿。"
    "角色表演要明确，镜头要有动作感和情绪推进，"
    "避免旁白总结、海报感、信息板感、漫画气泡和条漫分格感。"
)

ANIME_NEGATIVE_PROMPT = (
    "低质量，模糊，像解说封面，文字海报，漫画分镜板，"
    "旁白字幕块，信息图，过度扁平，畸形手指，重复脸，水印"
)


ANIME_STYLE_SUFFIX_EXTRA = (
    "日系二维动画，动漫角色，清晰线稿，赛璐璐上色，平涂，电影级分镜构图。"
    "像真正的动画正片而不是解说稿。"
    "角色表演要明确，表情自然但有张力，镜头要有动作感和情绪推进。"
    "人物设定要跟随角色名、台词身份和角色设定，不要跨性别或跨年龄漂移。"
    "避免写实摄影感、真人皮肤质感、3D感、海报感、信息板感、漫画气泡和条漫分格感。"
)

ANIME_NEGATIVE_PROMPT_EXTRA = "sketch, lineart, monochrome, greyscale, black and white, uncolored, pencil drawing, rough sketch, low quality, blurry, realistic, photorealistic, live action, 3d, cgi, skin pores, photo, bad anatomy, deformed face, duplicate face, extra head"

COMFYUI_STYLE_PRESETS = {
    "anime_fallback": {
        "positive_suffix": "anime style, cel shading, manga style, flat color, 2d illustration, clean lineart, expressive anime character acting",
        "negative_suffix": "photorealistic, realistic skin, dslr, photograph, live action, 3d render, cgi, skin pores",
    },
    "anime_v5": {
        "positive_suffix": "",
        "negative_suffix": "",
    },
}


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


@dataclass
class StoryScene:
    scene: int
    duration: float
    title: str
    visual: str
    dialogue: str
    camera: str
    emotion: str
    characters: list[str]
    bg_color: str
    accent_color: str
    speaker: str = ""
    voice_profile: str = ""
    voice_engine: str = ""
    voice_id: str = ""
    reference_audio_path: str = ""
    reference_text: str = ""
    voice_emotion: str = ""
    voice_rate: float = 1.0
    voice_pitch: float = 0.0
    voice_volume: float = 1.0
    rhythm_preset: str = "balanced"
    sfx_type: str = "auto"
    audio_manifest: dict[str, object] = field(default_factory=dict)
    subtitle_preset: str = "standard"
    camera_intensity: float = 1.0
    camera_speed: float = 1.0
    episode_rhythm: str = "classic_four_act"
    episode_phase: str = "setup"
    episode_phase_index: int = 1
    episode_phase_total: int = 4
    crop_box: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_CROP_BOX))
    character_descriptions: str = ""
    character_references: list[dict] = field(default_factory=list)
    primary_reference_image_path: str = ""
    primary_reference_image_abs_path: str = ""
    primary_reference_meta: dict[str, Any] | None = None
    consistency_meta: dict[str, Any] | None = None
    camera_movement: str = ""
    emotion_tone: str = ""
    scene_intent: str = ""
    pacing: str = ""
    subject_focus: str = ""
    director_meta: dict[str, Any] | None = None
    production_bible: dict[str, Any] = field(default_factory=dict)
    temporal_spec: dict[str, Any] = field(default_factory=dict)
    character_prompt_compilation: str = ""
    negative_prompt_compilation: str = ""
    validation_failed: bool = False
    error_message: str = ""
    raw_llm_output: dict[str, Any] = field(default_factory=dict)


def wrap_cn(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=True, replace_whitespace=False))


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def load_env_file(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env_value(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def env_optional_value(name: str, default: str = "") -> str:
    if name in os.environ:
        return os.environ.get(name, "").strip()
    return default


def env_float(*names: str, default: float) -> float:
    raw = env_value(*names, default="")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def env_bool(*names: str, default: bool = False) -> bool:
    raw = env_value(*names, default="")
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() <= 0:
            return 0.0
        return handle.getnframes() / float(handle.getframerate())


def media_duration(ffmpeg: str, path: Path) -> float:
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr or "")
    if not match:
        raise RuntimeError(f"Unable to probe media duration: {path}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def write_silent_wav(path: Path, duration: float, sample_rate: int = 44100) -> None:
    duration = max(0.25, float(duration))
    frame_count = int(math.ceil(duration * sample_rate))
    ensure_parent(path)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        silent = b"\x00\x00" * 2 * frame_count
        handle.writeframes(silent)


DEFAULT_VOICE_PRESETS = {
    "default": "zh-CN-XiaoxiaoNeural",
    "voice_map": {
        "narrator": "zh-CN-YunxiNeural",
        "female_lead": "zh-CN-XiaoxiaoNeural",
        "male_lead": "zh-CN-YunxiNeural",
        "antagonist": "zh-CN-YunjianNeural",
        "host": "zh-CN-YunyangNeural",
        "child": "zh-CN-XiaobeiNeural",
    },
}


def voice_presets_path() -> Path:
    return Path(env_value("VOICE_PRESETS_PATH", default=str(ROOT / "voice_presets.json")))


def load_voice_presets() -> dict:
    path = voice_presets_path()
    if path.exists():
        try:
            data = load_json(path)
            if isinstance(data, dict):
                return data
        except Exception as exc:
            print(f"[tts] Failed to load voice presets from {path}: {exc}")
    return DEFAULT_VOICE_PRESETS


def split_dialogue_speaker(text: str) -> tuple[str, str]:
    match = re.match(r"^\s*([^：:\n]{1,16})[：:]\s*(.+)$", text.strip(), re.S)
    if not match:
        return "", text.strip()
    return match.group(1).strip(), match.group(2).strip()


def split_dialogue_lines(text: str) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    last_speaker = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        speaker, spoken = split_dialogue_speaker(line)
        if speaker:
            lines.append((speaker, spoken))
            last_speaker = speaker
        elif last_speaker and not line.startswith(("旁白", "解说")):
            lines.append((last_speaker, line))
        else:
            lines.append(("", line))
    return lines


def infer_voice_profile(speaker: str, characters: list[str]) -> str:
    speaker = speaker.strip()
    if not speaker or speaker in {"旁白", "解说"}:
        return "narrator"
    if speaker in {"主持人", "主播", "记者"}:
        return "host"
    if speaker in {"反派", "对手", "老板"} or any(token in speaker for token in {"虎", "护法", "魔", "敌", "贼", "恶", "妖"}):
        return "antagonist"
    if any(token in speaker for token in {"姐", "妹", "她", "女", "娘", "妃", "姬", "嫣", "雪", "月", "晚"}):
        return "female_lead"
    return "male_lead"


def resolve_voice_name(scene: StoryScene) -> tuple[str, str, str]:
    presets = load_voice_presets()
    voice_map = presets.get("voice_map", {})
    if not isinstance(voice_map, dict):
        voice_map = {}
    default_voice = str(presets.get("default", "zh-CN-XiaoxiaoNeural"))

    explicit_voice = (scene.voice_id or "").strip()
    if explicit_voice:
        dialogue_speaker, _ = split_dialogue_speaker(scene.dialogue)
        speaker = (scene.speaker or dialogue_speaker or "旁白").strip()
        profile = (scene.voice_profile or infer_voice_profile(speaker, scene.characters)).strip()
        return speaker, profile, explicit_voice

    dialogue_speaker, _ = split_dialogue_speaker(scene.dialogue)
    speaker = (scene.speaker or dialogue_speaker or "旁白").strip()
    profile = (scene.voice_profile or infer_voice_profile(speaker, scene.characters)).strip()

    for key in (speaker, profile, dialogue_speaker):
        if not key:
            continue
        mapped = voice_map.get(key)
        if mapped:
            return speaker, profile, str(mapped)

    return speaker, profile, default_voice


def resolve_voice_engine(scene: StoryScene, provider: str) -> str:
    engine = tts_engines.normalize_engine_name(scene.voice_engine)
    if engine in {"auto", ""}:
        return tts_engines.normalize_engine_name(provider)
    return engine


def local_tts_engine(preferred_voice: str = "", rate_scale: float = 1.0, volume_scale: float = 1.0) -> pyttsx3.Engine:
    return tts_engines.local_tts_engine(preferred_voice, rate_scale=rate_scale, volume_scale=volume_scale)


def synthesize_local_tts(text: str, out_path: Path, preferred_voice: str = "", rate_scale: float = 1.0, volume_scale: float = 1.0) -> None:
    tts_engines.synthesize_local_tts(
        text,
        out_path,
        preferred_voice=preferred_voice,
        rate_scale=rate_scale,
        volume_scale=volume_scale,
    )


def synthesize_windows_sapi_tts(
    text: str,
    out_path: Path,
    preferred_voice: str = "",
    rate_scale: float = 1.0,
    volume_scale: float = 1.0,
) -> None:
    tts_engines.synthesize_windows_sapi_tts(
        text,
        out_path,
        preferred_voice=preferred_voice,
        rate_scale=rate_scale,
        volume_scale=volume_scale,
    )


def format_edge_rate(rate: float) -> str:
    return tts_engines.format_edge_rate(rate)


def format_edge_volume(volume: float) -> str:
    return tts_engines.format_edge_volume(volume)


def format_edge_pitch(pitch: float) -> str:
    return tts_engines.format_edge_pitch(pitch)


async def synthesize_edge_tts_async(
    text: str,
    out_path: Path,
    voice: str,
    rate: float = 1.0,
    volume: float = 1.0,
    pitch: float = 0.0,
) -> None:
    await tts_engines.synthesize_edge_tts_async(text, out_path, voice, rate=rate, volume=volume, pitch=pitch)


def synthesize_edge_tts(text: str, out_path: Path, voice: str, rate: float = 1.0, volume: float = 1.0, pitch: float = 0.0) -> None:
    tts_engines.synthesize_edge_tts(text, out_path, voice, rate=rate, volume=volume, pitch=pitch)


def convert_audio_to_wav(ffmpeg: str, input_path: Path, out_path: Path) -> Path:
    result = run_guarded(
        [ffmpeg, "-y", "-i", str(input_path), str(out_path)],
        cwd=out_path.parent,
        timeout=DEFAULT_SUBPROCESS_TIMEOUTS["ffmpeg_audio"],
        stage="ffmpeg_audio",
    )
    return out_path


def concat_audio_segments(ffmpeg: str, segments: list[Path], out_path: Path, run_dir: Path) -> Path:
    concat_file = run_dir / f"{out_path.stem}_audio_concat.txt"
    write_text(concat_file, "\n".join(f"file '{segment.name}'" for segment in segments))
    result = run_guarded(
        [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(out_path)],
        cwd=run_dir,
        timeout=concat_timeout(len(segments)),
        stage="ffmpeg_concat_audio",
    )
    return out_path


def synthesize_voice_fragment(
    ffmpeg: str,
    text: str,
    voice: str,
    provider: str,
    out_wav: Path,
    segment_prefix: str,
    voice_id: str = "",
    reference_audio_path: str = "",
    reference_text: str = "",
    emotion: str = "",
    rate_scale: float = 1.0,
    volume_scale: float = 1.0,
    pitch_shift: float = 0.0,
) -> float:
    if not text.strip():
        write_silent_wav(out_wav, 0.4)
        return wav_duration(out_wav)

    for candidate in tts_engines.engine_chain(provider):
        try:
            if candidate == "edge":
                mp3_path = out_wav.with_suffix(".mp3")
                edge_voice = env_value("TTS_EDGE_VOICE", default=voice)
                synthesize_edge_tts(text, mp3_path, edge_voice, rate=rate_scale, volume=volume_scale, pitch=pitch_shift)
                convert_audio_to_wav(ffmpeg, mp3_path, out_wav)
                if mp3_path.exists():
                    mp3_path.unlink()
                return wav_duration(out_wav)
            if candidate == "local":
                synthesize_local_tts(text, out_wav, preferred_voice=voice, rate_scale=rate_scale, volume_scale=volume_scale)
                return wav_duration(out_wav)
            if candidate == "silent":
                write_silent_wav(out_wav, max(0.4, min(2.0, len(text) / 10)))
                return wav_duration(out_wav)
            if tts_engines.is_external_engine(candidate):
                tts_engines.synthesize_external_tts(
                    candidate,
                    text,
                    out_wav,
                    voice,
                    voice_id=voice_id,
                    reference_audio_path=reference_audio_path,
                    reference_text=reference_text,
                    emotion=emotion,
                    rate=rate_scale,
                    pitch=pitch_shift,
                    volume=volume_scale,
                )
                return wav_duration(out_wav)
        except Exception as exc:
            print(f"[tts] {candidate} unavailable for {segment_prefix}, trying next backend: {exc}")

    write_silent_wav(out_wav, max(0.4, min(2.0, len(text) / 10)))
    return wav_duration(out_wav)


def resolve_dialogue_voice(scene: StoryScene, speaker: str, spoken_text: str) -> tuple[str, str, str]:
    segment_scene = StoryScene(
        scene=scene.scene,
        duration=scene.duration,
        title=scene.title,
        visual=scene.visual,
        dialogue=spoken_text,
        camera=scene.camera,
        emotion=scene.emotion,
        characters=scene.characters,
        bg_color=scene.bg_color,
        accent_color=scene.accent_color,
        speaker=speaker,
        voice_profile=infer_voice_profile(speaker, scene.characters),
    )
    return resolve_voice_name(segment_scene)


def default_subtitle_style() -> dict:
    return dict(DEFAULT_SUBTITLE_STYLE)


def _coerce_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _coerce_float(value: object, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def default_episode_pacing() -> dict:
    return {
        "preset": DEFAULT_EPISODE_PACING["preset"],
        "auto_assign": DEFAULT_EPISODE_PACING["auto_assign"],
        "phase_order": list(DEFAULT_EPISODE_PACING["phase_order"]),
    }


def normalize_episode_phase(value: object, default: str = "setup") -> str:
    phase = str(value or "").strip().lower().replace("-", "_")
    if phase in EPISODE_PHASES:
        return phase
    fallback = str(default or "setup").strip().lower().replace("-", "_")
    if default == "":
        return ""
    return fallback if fallback in EPISODE_PHASES else "setup"


def normalize_episode_pacing(pacing: dict | None = None) -> dict:
    merged = default_episode_pacing()
    if isinstance(pacing, dict):
        merged.update({key: value for key, value in pacing.items() if value is not None})
    preset = str(merged.get("preset") or DEFAULT_EPISODE_PACING["preset"]).strip().lower().replace("-", "_")
    if preset not in {"classic_four_act", "fast_hook", "slow_burn"}:
        preset = DEFAULT_EPISODE_PACING["preset"]
    phase_order = merged.get("phase_order")
    if not isinstance(phase_order, list):
        phase_order = list(EPISODE_PHASES)
    cleaned_order = [normalize_episode_phase(item, "") for item in phase_order]
    cleaned_order = [item for item in cleaned_order if item]
    if not cleaned_order:
        cleaned_order = list(EPISODE_PHASES)
    return {
        "preset": preset,
        "auto_assign": _coerce_bool(merged.get("auto_assign"), DEFAULT_EPISODE_PACING["auto_assign"]),
        "phase_order": cleaned_order,
    }


def infer_episode_phase(scene_index: int, scene_count: int, pacing: dict | None = None) -> str:
    normalized = normalize_episode_pacing(pacing)
    phases = normalized["phase_order"]
    total = max(1, int(scene_count or 1))
    index = max(1, min(total, int(scene_index or 1)))
    if total == 1:
        return phases[-1] if phases else "finale"
    if index == 1:
        return phases[0] if phases else "opening"
    if index == total:
        return phases[-1] if phases else "finale"
    if len(phases) >= 3 and index >= total - 1:
        return phases[-2]
    return phases[1] if len(phases) > 1 else "setup"


def apply_episode_pacing_to_scenes(scenes: list[StoryScene], pacing: dict | None = None) -> list[StoryScene]:
    normalized = normalize_episode_pacing(pacing)
    total = max(1, len(scenes))
    for index, scene in enumerate(scenes, start=1):
        phase = normalize_episode_phase(scene.episode_phase, "")
        if not phase or normalized["auto_assign"]:
            phase = infer_episode_phase(index, total, normalized)
        scene.episode_rhythm = normalized["preset"]
        scene.episode_phase = phase
        scene.episode_phase_index = index
        scene.episode_phase_total = total
    return scenes


def normalize_subtitle_style(style: dict | None = None) -> dict:
    merged = default_subtitle_style()
    if isinstance(style, dict):
        merged.update({key: value for key, value in style.items() if value is not None})
    merged["font_name"] = str(merged.get("font_name") or DEFAULT_SUBTITLE_STYLE["font_name"]).strip()
    merged["font_size"] = _coerce_int(merged.get("font_size"), DEFAULT_SUBTITLE_STYLE["font_size"], 12, 96)
    merged["margin_v"] = _coerce_int(merged.get("margin_v"), DEFAULT_SUBTITLE_STYLE["margin_v"], 0, 600)
    merged["outline"] = _coerce_int(merged.get("outline"), DEFAULT_SUBTITLE_STYLE["outline"], 0, 8)
    merged["shadow"] = _coerce_int(merged.get("shadow"), DEFAULT_SUBTITLE_STYLE["shadow"], 0, 8)
    merged["alignment"] = _coerce_int(merged.get("alignment"), DEFAULT_SUBTITLE_STYLE["alignment"], 1, 9)
    merged["show_speaker"] = _coerce_bool(merged.get("show_speaker"), DEFAULT_SUBTITLE_STYLE["show_speaker"])
    merged["burn_in"] = _coerce_bool(merged.get("burn_in"), DEFAULT_SUBTITLE_STYLE["burn_in"])
    return merged


def default_audio_style() -> dict:
    return dict(DEFAULT_AUDIO_STYLE)


def normalize_audio_style(style: dict | None = None) -> dict:
    merged = default_audio_style()
    if isinstance(style, dict):
        merged.update({key: value for key, value in style.items() if value is not None})
    merged["master_lufs"] = _coerce_float(merged.get("master_lufs"), DEFAULT_AUDIO_STYLE["master_lufs"], -30.0, -6.0)
    merged["true_peak"] = _coerce_float(merged.get("true_peak"), DEFAULT_AUDIO_STYLE["true_peak"], -6.0, 0.0)
    merged["loudness_range"] = _coerce_float(merged.get("loudness_range"), DEFAULT_AUDIO_STYLE["loudness_range"], 5.0, 20.0)
    merged["limiter_level"] = _coerce_float(merged.get("limiter_level"), DEFAULT_AUDIO_STYLE["limiter_level"], 0.5, 0.999)
    merged["bgm_path"] = str(merged.get("bgm_path") or "").strip()
    merged["bgm_gain_db"] = _coerce_float(merged.get("bgm_gain_db"), DEFAULT_AUDIO_STYLE["bgm_gain_db"], -60.0, 0.0)
    merged["duck_threshold"] = _coerce_float(merged.get("duck_threshold"), DEFAULT_AUDIO_STYLE["duck_threshold"], 0.01, 1.0)
    merged["duck_ratio"] = _coerce_float(merged.get("duck_ratio"), DEFAULT_AUDIO_STYLE["duck_ratio"], 1.0, 20.0)
    merged["duck_attack_ms"] = _coerce_int(merged.get("duck_attack_ms"), DEFAULT_AUDIO_STYLE["duck_attack_ms"], 1, 1000)
    merged["duck_release_ms"] = _coerce_int(merged.get("duck_release_ms"), DEFAULT_AUDIO_STYLE["duck_release_ms"], 10, 5000)
    return merged


def _subtitle_rolls(pacing: str, emotion: str) -> tuple[int, int]:
    pacing = str(pacing or "").strip().lower()
    emotion = str(emotion or "").strip().lower()
    if pacing == "fast" or emotion == "anger":
        return 40, 120
    if pacing == "slow" or emotion in {"sadness", "calm"}:
        return 120, 350
    return 80, 200


def write_scene_subtitles(
    scene_id: str,
    dialogue_segments: list[tuple[str, str]],
    durations: list[float],
    path: Path,
    subtitle_style: dict | None = None,
    ass_path: Path | None = None,
    emotion_tone: str = "",
    pacing: str = "",
    default_speaker: str = "",
) -> None:
    style = normalize_subtitle_style(subtitle_style)
    pre_roll_ms, post_roll_ms = _subtitle_rolls(pacing, emotion_tone)
    pre_roll = pre_roll_ms / 1000.0
    post_roll = post_roll_ms / 1000.0
    min_duration = 0.80
    total_duration = max(0.0, sum(max(0.0, float(duration)) for duration in durations))
    scene_end_cap = total_duration - 0.05 if total_duration > 0.05 else total_duration
    cursor = 0.0
    segments: list[tuple[float, float, str, str]] = []
    for (speaker, spoken_text), duration in zip(dialogue_segments, durations):
        effective_speaker = speaker or default_speaker
        text = format_subtitle_text(effective_speaker, spoken_text, style)
        if not text:
            cursor += duration
            continue
        audio_start = cursor
        audio_end = cursor + duration
        segments.append((audio_start, audio_end, effective_speaker, text))
        cursor += duration
    entries: list[tuple[float, float, str]] = []
    ass_entries: list[tuple[float, float, str, str, str]] = []
    for index, (audio_start, audio_end, effective_speaker, text) in enumerate(segments):
        sub_start = max(0.0, audio_start - pre_roll)
        raw_end = audio_end + post_roll
        if index + 1 < len(segments):
            next_audio_start = segments[index + 1][0]
            next_start = max(0.0, next_audio_start - pre_roll)
            sub_end = min(raw_end, next_start - 0.02)
        else:
            sub_end = raw_end
        sub_end = min(sub_end, scene_end_cap)
        if sub_end <= sub_start:
            sub_end = min(scene_end_cap, sub_start + max(0.25, audio_end - audio_start))
        if sub_end - sub_start < min_duration and sub_end < scene_end_cap:
            sub_end = min(scene_end_cap, sub_start + min_duration)
        entries.append((sub_start, sub_end, text))
        ass_entries.append((sub_start, sub_end, text, effective_speaker, emotion_tone))
    write_srt_entries(entries, path)
    if ass_path is not None:
        write_ass_entries(ass_entries, ass_path, style)


def ass_timestamp(seconds: float) -> str:
    centiseconds = int(round(max(0.0, float(seconds)) * 100))
    hours, rem = divmod(centiseconds, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, centiseconds = divmod(rem, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{centiseconds:02}"


def ass_escape_text(text: str) -> str:
    value = str(text or "")
    return (
        value.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\r", "")
        .replace("\n", r"\N")
    )


def write_ass_entries(entries: list[tuple], path: Path, subtitle_style: dict | None = None) -> None:
    style = normalize_subtitle_style(subtitle_style)
    write_text(path, build_ass_document(entries, style))


def ffmpeg_escape_filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:")


def burn_subtitles_to_video(
    ffmpeg: str,
    video_path: Path,
    subtitles_path: Path,
    out_path: Path,
    subtitle_style: dict | None = None,
    timeout_s: int | None = None,
) -> Path:
    style = normalize_subtitle_style(subtitle_style)
    fonts_dir = Path("C:/Windows/Fonts")
    force_style = ",".join(
        [
            f"FontName={style['font_name']}",
            f"FontSize={style['font_size']}",
            f"Outline={style['outline']}",
            f"Shadow={style['shadow']}",
            f"Alignment={style['alignment']}",
            f"MarginV={style['margin_v']}",
        ]
    )
    subtitle_filter = (
        f"subtitles='{ffmpeg_escape_filter_path(subtitles_path)}'"
        f":fontsdir='{ffmpeg_escape_filter_path(fonts_dir)}'"
        f":force_style='{force_style}'"
    )
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-vf",
        subtitle_filter,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        str(out_path),
    ]
    run_guarded(cmd, cwd=out_path.parent, timeout=timeout_s or DEFAULT_SUBPROCESS_TIMEOUTS["ffmpeg_render"], stage="ffmpeg_burn_subtitles")
    return out_path


def db_to_linear(value_db: float) -> float:
    return 10 ** (float(value_db) / 20.0)


def normalize_audio_track(ffmpeg: str, input_path: Path, out_path: Path, audio_style: dict | None = None) -> Path:
    style = normalize_audio_style(audio_style)
    audio_filter = ",".join(
        [
            f"loudnorm=I={style['master_lufs']}:TP={style['true_peak']}:LRA={style['loudness_range']}:linear=true:print_format=summary",
            f"alimiter=limit={style['limiter_level']}",
        ]
    )
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-af",
        audio_filter,
        "-c:a",
        "pcm_s16le",
        str(out_path),
    ]
    run_guarded(cmd, cwd=out_path.parent, timeout=DEFAULT_SUBPROCESS_TIMEOUTS["ffmpeg_audio"], stage="ffmpeg_normalize_audio")
    return out_path


def resolve_path(base_dir: Path | None, raw_path: str) -> Path | None:
    value = str(raw_path or "").strip()
    if not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute() or base_dir is None:
        return candidate
    return (base_dir / candidate).resolve()


def mix_voice_with_bgm(
    ffmpeg: str,
    voice_path: Path,
    out_path: Path,
    duration: float,
    audio_style: dict | None = None,
    project_root: Path | None = None,
) -> Path:
    style = normalize_audio_style(audio_style)
    bgm_path = resolve_path(project_root, style.get("bgm_path", ""))
    if bgm_path is None or not bgm_path.exists():
        return voice_path

    bgm_gain = db_to_linear(style["bgm_gain_db"])
    fade_duration = min(1.0, max(0.12, float(duration) / 5.0))
    fade_out_start = max(0.0, float(duration) - fade_duration)
    filter_complex = ";".join(
        [
            (
                f"[1:a]volume={bgm_gain:.6f},"
                f"afade=t=in:st=0:d={fade_duration:.3f},"
                f"afade=t=out:st={fade_out_start:.3f}:d={fade_duration:.3f},"
                "aformat=sample_rates=48000:channel_layouts=stereo[bgm]"
            ),
            f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo[voice]",
            (
                f"[bgm][voice]sidechaincompress=threshold={style['duck_threshold']}:ratio={style['duck_ratio']}"
                f":attack={style['duck_attack_ms']}:release={style['duck_release_ms']}:makeup=1[ducked]"
            ),
            "[voice][ducked]amix=inputs=2:duration=first:normalize=0[mixed]",
            (
                f"[mixed]loudnorm=I={style['master_lufs']}:TP={style['true_peak']}:LRA={style['loudness_range']}:linear=true:print_format=summary"
                f",alimiter=limit={style['limiter_level']}[final]"
            ),
        ]
    )
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(voice_path),
        "-stream_loop",
        "-1",
        "-i",
        str(bgm_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[final]",
        "-t",
        f"{max(0.25, float(duration)):.3f}",
        "-c:a",
        "pcm_s16le",
        str(out_path),
    ]
    run_guarded(
        cmd,
        cwd=out_path.parent,
        timeout=max(60, min(180, int(max(0.25, float(duration)) * 4 + 20))),
        stage="ffmpeg_mix_voice_bgm",
    )
    return out_path


def audio_manifest_dict(scene: StoryScene) -> dict[str, object]:
    return scene.audio_manifest if isinstance(scene.audio_manifest, dict) else {}


def resolve_audio_asset(kind: str, value: object, project_root: Path | None = None) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = resolve_path(project_root, raw)
    if candidate and candidate.exists():
        return candidate

    asset_dir = AUDIO_ASSETS / kind
    raw_path = Path(raw)
    names = [raw_path.name]
    if raw_path.suffix:
        names.append(raw)
    else:
        names.extend(f"{raw}{suffix}" for suffix in AUDIO_ASSET_EXTENSIONS)
    for name in dict.fromkeys(names):
        candidate = asset_dir / name
        if candidate.exists():
            return candidate
    return None


def normalize_sfx_kind(value: object) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "slap": "hit",
        "punch": "hit",
        "impact": "hit",
        "knock": "hit",
        "table": "boom",
        "desk": "boom",
        "slam": "boom",
        "explosion": "boom",
        "thunder": "thunder",
        "lightning": "thunder",
        "drop": "drop",
        "fall": "drop",
        "pen": "drop",
        "whoosh": "whoosh",
        "spark": "spark",
        "hit": "hit",
        "boom": "boom",
    }
    return aliases.get(raw, raw)


def scene_audio_style(scene: StoryScene, audio_style: dict | None = None, project_root: Path | None = None) -> dict:
    style = normalize_audio_style(audio_style)
    manifest = audio_manifest_dict(scene)
    bgm_root = AUDIO_ASSETS / "bgm"
    selection = select_bgm_for_scene(scene, manifest, bgm_root=bgm_root, project_root=project_root)
    if selection.path is not None:
        style["bgm_path"] = str(selection.path)
        if selection.style:
            style["bgm_style"] = selection.style
        if selection.source:
            style["bgm_source"] = selection.source
    elif manifest.get("bgm_file") or manifest.get("bgm_path") or manifest.get("bgm_style"):
        bgm_value = manifest.get("bgm_file") or manifest.get("bgm_path") or manifest.get("bgm_style")
        bgm_path = resolve_audio_asset("bgm", bgm_value, project_root=project_root)
        if bgm_path is not None:
            style["bgm_path"] = str(bgm_path)
    if manifest.get("bgm_gain_db") not in (None, ""):
        style["bgm_gain_db"] = _coerce_float(manifest.get("bgm_gain_db"), style["bgm_gain_db"], -60.0, 0.0)
    return style


def render_voice_track(
    ffmpeg: str,
    scene: StoryScene,
    run_dir: Path,
    provider: str,
    write_subtitles: bool = True,
    subtitle_style: dict | None = None,
    audio_style: dict | None = None,
) -> tuple[Path, float]:
    style = normalize_subtitle_style(subtitle_style)
    audio_settings = normalize_audio_style(audio_style)
    scene_id = f"{scene.scene:02}"
    text = scene.dialogue.strip()
    raw_wav = run_dir / f"scene_{scene_id}_voice_raw.wav"
    voice_wav = run_dir / f"scene_{scene_id}_voice.wav"
    subtitle_path = run_dir / f"scene_{scene_id}_dialogue.srt"
    subtitle_ass_path = run_dir / f"scene_{scene_id}_dialogue.ass"
    effective_provider = resolve_voice_engine(scene, provider)

    if not text:
        write_silent_wav(raw_wav, scene.duration)
        if write_subtitles:
            subtitle_path.write_text("", encoding="utf-8")
            subtitle_ass_path.write_text("", encoding="utf-8")
        normalize_audio_track(ffmpeg, raw_wav, voice_wav, audio_settings)
        return voice_wav, wav_duration(voice_wav)

    dialogue_segments = split_dialogue_lines(text)
    if not dialogue_segments:
        write_silent_wav(raw_wav, scene.duration)
        if write_subtitles:
            subtitle_path.write_text("", encoding="utf-8")
            subtitle_ass_path.write_text("", encoding="utf-8")
        normalize_audio_track(ffmpeg, raw_wav, voice_wav, audio_settings)
        return voice_wav, wav_duration(voice_wav)

    if effective_provider == "silent":
        write_silent_wav(raw_wav, scene.duration)
        if write_subtitles:
            if len(dialogue_segments) == 1:
                fallback_durations = [scene.duration]
            else:
                per_segment = scene.duration / max(1, len(dialogue_segments))
                fallback_durations = [per_segment for _ in dialogue_segments]
            write_scene_subtitles(
                scene_id,
                dialogue_segments,
                fallback_durations,
                subtitle_path,
                style,
                ass_path=subtitle_ass_path,
                emotion_tone=scene.emotion_tone,
                pacing=scene.pacing,
                default_speaker=scene.speaker,
            )
        normalize_audio_track(ffmpeg, raw_wav, voice_wav, audio_settings)
        return voice_wav, wav_duration(voice_wav)

    segment_paths: list[Path] = []
    segment_durations: list[float] = []
    single_segment = len(dialogue_segments) == 1
    for index, (speaker, spoken_text) in enumerate(dialogue_segments, start=1):
        segment_speaker = speaker or scene.speaker or "旁白"
        _, _, voice_name = resolve_dialogue_voice(scene, segment_speaker, spoken_text)
        segment_wav = raw_wav if single_segment else run_dir / f"scene_{scene_id}_voice_{index:02}.wav"
        try:
            duration = synthesize_voice_fragment(
                ffmpeg,
                spoken_text,
                voice_name,
                effective_provider,
                segment_wav,
                f"scene_{scene_id}_{index:02}",
                voice_id=scene.voice_id,
                reference_audio_path=scene.reference_audio_path,
                reference_text=scene.reference_text or spoken_text,
                emotion=scene.voice_emotion or scene.emotion,
                rate_scale=float(scene.voice_rate or 1.0),
                volume_scale=float(scene.voice_volume or 1.0),
                pitch_shift=float(scene.voice_pitch or 0.0),
            )
        except Exception as exc:
            print(f"[tts] Segment synthesis failed for scene {scene_id} line {index}: {exc}")
            write_silent_wav(segment_wav, max(0.4, scene.duration / max(1, len(dialogue_segments))))
            duration = wav_duration(segment_wav)
        segment_durations.append(duration)
        segment_paths.append(segment_wav)

    if not segment_paths:
        write_silent_wav(raw_wav, scene.duration)
        if write_subtitles:
            subtitle_path.write_text("", encoding="utf-8")
            subtitle_ass_path.write_text("", encoding="utf-8")
        normalize_audio_track(ffmpeg, raw_wav, voice_wav, audio_settings)
        return voice_wav, wav_duration(voice_wav)

    if not single_segment:
        concat_audio_segments(ffmpeg, segment_paths, raw_wav, run_dir)
    if write_subtitles:
        write_scene_subtitles(
            scene_id,
            dialogue_segments,
            segment_durations,
            subtitle_path,
            style,
            ass_path=subtitle_ass_path,
            emotion_tone=scene.emotion_tone,
            pacing=scene.pacing,
            default_speaker=scene.speaker,
        )
    normalize_audio_track(ffmpeg, raw_wav, voice_wav, audio_settings)
    return voice_wav, wav_duration(voice_wav)


def build_rule_storyboard(story: str) -> list[StoryScene]:
    compact_story = " ".join(story.strip().split())
    premise = compact_story[:28] if compact_story else "一个被轻视的主角，在命运翻转前夕被推到悬崖边"

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


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def replace_placeholders(obj: object, replacements: dict[str, object]) -> object:
    if isinstance(obj, dict):
        return {key: replace_placeholders(value, replacements) for key, value in obj.items()}
    if isinstance(obj, list):
        return [replace_placeholders(item, replacements) for item in obj]
    if isinstance(obj, str):
        result = obj
        for key, value in replacements.items():
            result = result.replace(key, str(value))
        return result
    return obj


def unresolved_placeholders(obj: object, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            found.extend(unresolved_placeholders(value, f"{path}.{key}"))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            found.extend(unresolved_placeholders(value, f"{path}[{index}]"))
    elif isinstance(obj, str) and "__" in obj:
        found.append(f"{path}: {obj}")
    return found


def comfyui_style_preset() -> dict[str, str]:
    preset_name = env_value("COMFYUI_STYLE_PRESET", default="").strip().lower()
    preset = COMFYUI_STYLE_PRESETS.get(preset_name)
    return preset if preset is not None else {"positive_suffix": "", "negative_suffix": ""}


def append_prompt_suffix(text: str, suffix: str) -> str:
    clean_text = str(text or "").strip()
    clean_suffix = str(suffix or "").strip()
    if clean_text and clean_suffix:
        return f"{clean_text}, {clean_suffix}"
    return clean_text or clean_suffix


def inject_comfyui_workflow(
    template: object,
    *,
    checkpoint_name: str,
    lora_name: str,
    style_preset: dict[str, str] | None = None,
) -> dict:
    if not isinstance(template, dict):
        raise ValueError("ComfyUI workflow template must be a JSON object.")
    checkpoint_name = str(checkpoint_name or "").strip()
    if not checkpoint_name:
        raise ValueError("COMFYUI_CHECKPOINT_NAME / COMFYUI_VIDEO_CHECKPOINT_NAME is required for ComfyUI rendering.")

    graph = deepcopy(template)
    checkpoint_node_id: str | None = None
    lora_node_id: str | None = None

    for node_id, node in graph.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        class_type = node.get("class_type")
        if class_type == "CheckpointLoaderSimple":
            checkpoint_node_id = str(node_id)
            inputs["ckpt_name"] = checkpoint_name
        elif class_type == "UNETLoader":
            checkpoint_node_id = str(node_id)
            inputs["unet_name"] = checkpoint_name
        elif class_type == "LoraLoader":
            lora_node_id = str(node_id)

    if checkpoint_node_id is None:
        raise ValueError("ComfyUI workflow is missing CheckpointLoaderSimple or UNETLoader.")

    if lora_node_id and not str(lora_name or "").strip():
        for node in graph.values():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                continue
            for input_name, input_value in list(inputs.items()):
                if (
                    isinstance(input_value, list)
                    and len(input_value) == 2
                    and str(input_value[0]) == lora_node_id
                ):
                    inputs[input_name] = [checkpoint_node_id, input_value[1]]
        del graph[lora_node_id]
    elif lora_node_id:
        lora_node = graph.get(lora_node_id)
        if isinstance(lora_node, dict) and isinstance(lora_node.get("inputs"), dict):
            lora_node["inputs"]["lora_name"] = str(lora_name or "").strip()

    preset = style_preset or {}
    positive_suffix = str(preset.get("positive_suffix") or "").strip()
    negative_suffix = str(preset.get("negative_suffix") or "").strip()
    if positive_suffix or negative_suffix:
        for node in graph.values():
            if not isinstance(node, dict) or node.get("class_type") != "CLIPTextEncode":
                continue
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                continue
            text = inputs.get("text")
            if not isinstance(text, str):
                continue
            if "__NEGATIVE__" in text:
                inputs["text"] = append_prompt_suffix(text, negative_suffix)
            else:
                inputs["text"] = append_prompt_suffix(text, positive_suffix)

    return graph


def write_debug_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def font_candidates() -> list[Path]:
    return [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/simsun.ttc"),
    ]


def pick_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = font_candidates()
    if bold:
        candidates = [p for p in candidates if "bd" in p.name.lower()] + [p for p in candidates if "bd" not in p.name.lower()]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    normalized = value.replace("0x", "#")
    return ImageColor.getrgb(normalized)


def blend_color(value: str, factor: float) -> tuple[int, int, int]:
    r, g, b = hex_to_rgb(value)
    target = (12, 16, 26)
    return (
        int(r * (1 - factor) + target[0] * factor),
        int(g * (1 - factor) + target[1] * factor),
        int(b * (1 - factor) + target[2] * factor),
    )


def wrap_for_pixels(text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    for ch in text:
        trial = current + ch
        if font.getlength(trial) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


def draw_paragraph(draw: ImageDraw.ImageDraw, text: str, box: tuple[int, int, int, int], font, fill, spacing: int = 14) -> None:
    x0, y0, x1, y1 = box
    y = y0
    line_height = None
    for paragraph in text.splitlines():
        wrapped = wrap_for_pixels(paragraph, font, x1 - x0)
        for line in wrapped:
            bbox = draw.textbbox((x0, y), line, font=font)
            line_height = bbox[3] - bbox[1]
            if y + line_height > y1:
                draw.text((x0, max(y0, y1 - line_height)), "…", font=font, fill=fill)
                return
            draw.text((x0, y), line, font=font, fill=fill)
            y = bbox[3] + spacing
        y += spacing // 2


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalize_crop_box(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return dict(DEFAULT_CROP_BOX)

    def _crop_float(name: str, default: float) -> float:
        try:
            number = float(value.get(name, default))
        except (TypeError, ValueError):
            number = default
        if not math.isfinite(number):
            number = default
        return number

    x = clamp(_crop_float("x", 0.0), 0.0, 1.0)
    y = clamp(_crop_float("y", 0.0), 0.0, 1.0)
    width = clamp(_crop_float("width", 1.0), MIN_CROP_BOX_SIZE, 1.0)
    height = clamp(_crop_float("height", 1.0), MIN_CROP_BOX_SIZE, 1.0)
    if x + width > 1.0:
        x = max(0.0, 1.0 - width)
    if y + height > 1.0:
        y = max(0.0, 1.0 - height)
    return {"x": x, "y": y, "width": width, "height": height}


def apply_crop_box(image: Image.Image, crop_box: object, target_size: tuple[int, int] = (1080, 1920)) -> Image.Image:
    width, height = image.size
    if width <= 0 or height <= 0:
        return image.resize(target_size, Image.Resampling.LANCZOS)
    box = normalize_crop_box(crop_box)
    x0 = int(round(box["x"] * width))
    y0 = int(round(box["y"] * height))
    crop_w = max(1, int(round(box["width"] * width)))
    crop_h = max(1, int(round(box["height"] * height)))
    x0 = int(clamp(x0, 0, max(0, width - crop_w)))
    y0 = int(clamp(y0, 0, max(0, height - crop_h)))
    x1 = min(width, x0 + crop_w)
    y1 = min(height, y0 + crop_h)
    return image.crop((x0, y0, x1, y1)).resize(target_size, Image.Resampling.LANCZOS)


def split_text_chunks(text: str, parts: int = 2) -> list[str]:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return [""] * max(1, parts)
    if parts <= 1:
        return [cleaned]

    targets = max(1, math.ceil(len(cleaned) / parts))
    chunks: list[str] = []
    start = 0
    for index in range(parts - 1):
        end = min(len(cleaned), start + targets)
        while end < len(cleaned) and cleaned[end] not in "。！？!?，,；;":
            end += 1
        piece = cleaned[start:end].strip()
        if not piece:
            piece = cleaned[start:min(len(cleaned), start + targets)].strip()
            end = min(len(cleaned), start + targets)
        chunks.append(piece)
        start = end
    chunks.append(cleaned[start:].strip())
    return [chunk for chunk in chunks if chunk] or [cleaned]


def focal_crop(image: Image.Image, zoom: float, center_x: float, center_y: float) -> Image.Image:
    width, height = image.size
    zoom = max(1.0, zoom)
    crop_w = int(width / zoom)
    crop_h = int(height / zoom)
    x0 = int(clamp(center_x * width - crop_w / 2, 0, max(0, width - crop_w)))
    y0 = int(clamp(center_y * height - crop_h / 2, 0, max(0, height - crop_h)))
    return image.crop((x0, y0, x0 + crop_w, y0 + crop_h)).resize((width, height), Image.Resampling.LANCZOS)


def emotion_stamp(emotion: str) -> str:
    value = emotion.strip()
    if not value:
        return ""
    for keyword, stamp in (
        ("震撼", "轰"),
        ("压迫", "压"),
        ("反转", "!!"),
        ("决绝", "啪"),
        ("悬疑", "?"),
        ("愤怒", "怒"),
        ("悲伤", "痛"),
    ):
        if keyword in value:
            return stamp
    return value[:2]


def build_scene_beats(scene: StoryScene, total_duration: float, spoken_text: str) -> list[dict[str, object]]:
    speaker = scene.speaker or split_dialogue_speaker(scene.dialogue)[0] or "narrator"
    visual_chunks = split_text_chunks(scene.visual, 2)
    dialogue_chunks = split_text_chunks(spoken_text or scene.dialogue, 3)

    rhythm = (scene.rhythm_preset or "balanced").strip().lower()
    episode_rhythm = (scene.episode_rhythm or "classic_four_act").strip().lower().replace("-", "_")
    phase = normalize_episode_phase(scene.episode_phase, "setup")
    phase_weights = {
        "opening": (0.34, 0.26, 0.18, 0.22),
        "setup": (0.18, 0.42, 0.22, 0.18),
        "reversal": (0.14, 0.22, 0.42, 0.22),
        "finale": (0.16, 0.20, 0.22, 0.42),
    }
    weights = list(phase_weights.get(phase, phase_weights["setup"]))
    if episode_rhythm == "fast_hook" or rhythm == "fast":
        weights = [weights[0] + 0.06, max(0.12, weights[1] - 0.05), weights[2] + 0.04, max(0.12, weights[3] - 0.05)]
    elif episode_rhythm == "slow_burn" or rhythm == "slow":
        weights = [max(0.12, weights[0] - 0.04), weights[1] + 0.08, max(0.12, weights[2] - 0.02), max(0.12, weights[3] - 0.02)]
    elif rhythm == "dialogue":
        weights = [0.14, 0.54, 0.18, 0.14]
    elif rhythm == "suspense":
        weights = [0.16, 0.24, 0.38, 0.22]

    weight_total = sum(weights) or 1.0
    weights = [weight / weight_total for weight in weights]
    minimum = 0.45 if total_duration < 3.0 else 0.65
    durations = [max(minimum, float(total_duration) * weight) for weight in weights]
    if sum(durations) > total_duration:
        scale = max(0.25, float(total_duration)) / sum(durations)
        durations = [max(0.25, duration * scale) for duration in durations]
    durations[-1] = max(0.25, float(total_duration) - sum(durations[:-1]))
    intensity = clamp(float(scene.camera_intensity or 1.0), 0.5, 1.8)
    pacing = str(getattr(scene, "pacing", "") or "").strip().lower()
    emotion_tone = str(getattr(scene, "emotion_tone", "") or "").strip().lower()
    motion_boost = 1.0
    if pacing == "fast" or emotion_tone in {"anger", "fear", "tension", "surprise"}:
        motion_boost = 1.10
    elif pacing == "slow" or emotion_tone in {"sadness", "calm"}:
        motion_boost = 0.96

    def _zoom(value: float) -> float:
        return 1.0 + (value - 1.0) * intensity * motion_boost

    def _hold_ratios(label: str) -> tuple[float, float]:
        if label == "OPENING":
            hold_in, hold_out = 0.18, 0.18
        elif label == "SETUP":
            hold_in, hold_out = 0.12, 0.12
        elif label == "REVERSAL":
            hold_in, hold_out = 0.08, 0.10
        else:
            hold_in, hold_out = 0.10, 0.20
        if scene.camera == "dramatic_push":
            hold_in = min(hold_in, 0.08)
            hold_out = max(hold_out, 0.15)
        elif scene.camera in {"slow_push", "slow_push_in"}:
            hold_in = max(hold_in, 0.15)
            hold_out = max(hold_out, 0.15)
        elif scene.camera in {"melancholy_pan", "establishing_tilt"}:
            hold_in = max(hold_in, 0.10)
            hold_out = max(hold_out, 0.14)
        return hold_in, hold_out

    first_dialogue = dialogue_chunks[0] if dialogue_chunks else spoken_text
    middle_dialogue = dialogue_chunks[1] if len(dialogue_chunks) > 1 else first_dialogue
    final_dialogue = dialogue_chunks[-1] if dialogue_chunks else spoken_text
    visual_open = visual_chunks[0] if visual_chunks else scene.visual
    visual_setup = visual_chunks[-1] if visual_chunks else scene.visual
    phase_caption = f"{phase.upper()} {scene.episode_phase_index}/{scene.episode_phase_total}"
    opening_hold = _hold_ratios("OPENING")
    setup_hold = _hold_ratios("SETUP")
    reversal_hold = _hold_ratios("REVERSAL")
    finale_hold = _hold_ratios("FINALE")

    return [
        {
            "label": "OPENING",
            "beat_type": "OPENING",
            "caption": scene.title,
            "bubble": visual_open,
            "zoom": _zoom(1.05 if phase == "opening" else 1.07),
            "hold_in_ratio": opening_hold[0],
            "hold_out_ratio": opening_hold[1],
            "center_x": 0.50,
            "center_y": 0.42,
            "duration": durations[0],
        },
        {
            "label": "SETUP",
            "beat_type": "SETUP",
            "caption": speaker,
            "bubble": first_dialogue or visual_setup,
            "zoom": _zoom(1.15 if phase == "setup" else 1.12),
            "hold_in_ratio": setup_hold[0],
            "hold_out_ratio": setup_hold[1],
            "center_x": 0.52,
            "center_y": 0.50,
            "duration": durations[1],
        },
        {
            "label": "REVERSAL",
            "beat_type": "REVERSAL",
            "caption": emotion_stamp(scene.emotion) or "TURN",
            "bubble": middle_dialogue or final_dialogue or visual_setup,
            "zoom": _zoom(1.30 if phase == "reversal" else 1.23),
            "hold_in_ratio": reversal_hold[0],
            "hold_out_ratio": reversal_hold[1],
            "center_x": 0.56,
            "center_y": 0.60,
            "duration": durations[2],
        },
        {
            "label": "FINALE",
            "beat_type": "FINALE",
            "caption": phase_caption,
            "bubble": final_dialogue or visual_setup,
            "zoom": _zoom(1.36 if phase == "finale" else 1.27),
            "hold_in_ratio": finale_hold[0],
            "hold_out_ratio": finale_hold[1],
            "center_x": 0.54,
            "center_y": 0.56,
            "duration": durations[3],
        },
    ]


def build_scene_graph(scene: StoryScene) -> dict[str, object]:
    spoken_text = split_dialogue_speaker(scene.dialogue)[1] or scene.dialogue
    beat_specs = build_scene_beats(scene, float(scene.duration or 0.0), spoken_text)
    camera_track = {
        "movement": str(scene.camera_movement or scene.camera or "").strip(),
        "speed": float(scene.camera_speed or 1.0),
        "shot_count": len(beat_specs),
        "beat_labels": [str(beat.get("label") or "") for beat in beat_specs],
        "beat_types": [str(beat.get("beat_type") or "") for beat in beat_specs],
    }
    cursor = 0.0
    shots: list[dict[str, object]] = []
    for index, beat in enumerate(beat_specs, start=1):
        duration = max(0.25, float(beat.get("duration") or 0.0))
        shots.append(
            {
                "shot_id": f"scene_{scene.scene:03d}_shot_{index:02d}",
                "shot_order": index,
                "label": str(beat.get("label") or beat.get("beat_type") or f"SHOT {index}").strip(),
                "beat_type": str(beat.get("beat_type") or "").strip(),
                "title": str(scene.title or "").strip(),
                "caption": str(beat.get("caption") or "").strip(),
                "bubble": str(beat.get("bubble") or "").strip(),
                "start_seconds": round(cursor, 3),
                "duration_seconds": round(duration, 3),
                "end_seconds": round(min(float(scene.duration or 0.0), cursor + duration), 3),
                "camera_movement": str(scene.camera_movement or scene.camera or "").strip(),
                "camera_speed": float(scene.camera_speed or 1.0),
                "zoom": float(beat.get("zoom") or 1.0),
                "hold_in_ratio": float(beat.get("hold_in_ratio") or 0.0),
                "hold_out_ratio": float(beat.get("hold_out_ratio") or 0.0),
                "center_x": float(beat.get("center_x") or 0.5),
                "center_y": float(beat.get("center_y") or 0.5),
                "speaker": str(scene.speaker or split_dialogue_speaker(scene.dialogue)[0] or "").strip(),
                "dialogue": spoken_text.strip(),
                "emotion": str(scene.emotion_tone or scene.emotion or "").strip(),
                "scene_intent": str(scene.scene_intent or "").strip(),
                "subject_focus": str(scene.subject_focus or "").strip(),
            }
        )
        cursor += duration
    return {"camera_track": camera_track, "shots": shots}


def build_scene_temporal_spec(scene: StoryScene, duration: float, *, width: int = 1080, height: int = 1920, fps: int = 24) -> dict[str, Any]:
    graph = deepcopy(build_scene_graph(scene))
    shots: list[dict[str, Any]] = []
    for raw in graph.get("shots", []) or []:
        if not isinstance(raw, dict):
            continue
        shots.append(
            {
                "shot_id": raw.get("shot_id"),
                "shot_order": raw.get("shot_order"),
                "label": raw.get("label"),
                "beat_type": raw.get("beat_type"),
                "start_seconds": raw.get("start_seconds"),
                "duration_seconds": raw.get("duration_seconds"),
                "end_seconds": raw.get("end_seconds"),
                "camera_movement": raw.get("camera_movement"),
                "camera_speed": raw.get("camera_speed"),
                "zoom": raw.get("zoom"),
                "hold_in_ratio": raw.get("hold_in_ratio"),
                "hold_out_ratio": raw.get("hold_out_ratio"),
                "center_x": raw.get("center_x"),
                "center_y": raw.get("center_y"),
                "caption": raw.get("caption"),
                "bubble": raw.get("bubble"),
                "speaker": raw.get("speaker"),
                "dialogue": raw.get("dialogue"),
                "emotion": raw.get("emotion"),
                "scene_intent": raw.get("scene_intent"),
                "subject_focus": raw.get("subject_focus"),
            }
        )
    return {
        "version": 1,
        "kind": "scene_temporal_video_spec",
        "scene": scene.scene,
        "title": scene.title,
        "duration_seconds": round(float(duration or scene.duration or 0.0), 3),
        "size": {"width": int(width), "height": int(height), "fps": int(fps)},
        "camera_track": graph.get("camera_track") or {},
        "shots": shots,
        "continuity_rules": {
            "generate_continuous_video": True,
            "avoid_static_pan_only_motion": True,
            "preserve_character_environment_contact": True,
            "preserve_lighting_direction": True,
            "preserve_scene_geometry": True,
        },
    }


def _timeline_scene_field(scene: dict[str, Any], key: str, default: Any = "") -> Any:
    if isinstance(scene, dict) and key in scene:
        value = scene.get(key)
        if value not in (None, ""):
            return value
    assets = scene.get("assets") if isinstance(scene, dict) and isinstance(scene.get("assets"), dict) else {}
    if isinstance(assets, dict) and key in assets:
        value = assets.get(key)
        if value not in (None, ""):
            return value
    return default


def _scene_media_reference(scene: dict[str, Any], kind: str) -> dict[str, str]:
    if kind == "image":
        path = str(_timeline_scene_field(scene, "keyframe", "") or _timeline_scene_field(scene, "image_path", "") or _timeline_scene_field(scene, "primary_reference_image_path", "")).strip()
        url = str(_timeline_scene_field(scene, "keyframe_url", "") or _timeline_scene_field(scene, "image_url", "") or _timeline_scene_field(scene, "primary_reference_image_url", "")).strip()
    elif kind == "audio":
        path = str(_timeline_scene_field(scene, "voice", "") or _timeline_scene_field(scene, "audio_path", "") or _timeline_scene_field(scene, "reference_audio_path", "")).strip()
        url = str(_timeline_scene_field(scene, "voice_url", "") or _timeline_scene_field(scene, "audio_url", "") or _timeline_scene_field(scene, "reference_audio_url", "")).strip()
    elif kind == "video":
        path = str(_timeline_scene_field(scene, "video", "") or _timeline_scene_field(scene, "video_path", "") or _timeline_scene_field(scene, "final_video_path", "")).strip()
        url = str(_timeline_scene_field(scene, "video_url", "") or _timeline_scene_field(scene, "final_video_url", "")).strip()
    else:
        path = str(_timeline_scene_field(scene, "subtitle_path", "") or _timeline_scene_field(scene, "subtitles_path", "")).strip()
        url = str(_timeline_scene_field(scene, "subtitle_url", "") or _timeline_scene_field(scene, "subtitles_url", "")).strip()
    return {"path": path, "url": url}


def _scene_duration_seconds(scene: dict[str, Any]) -> float:
    duration = scene.get("duration_seconds") or scene.get("clip_duration") or scene.get("voice_duration") or 0.0
    try:
        return round(max(0.25, float(duration)), 3)
    except (TypeError, ValueError):
        return 4.0


def normalize_shot_plan_visual_content(scene: dict[str, Any], shot_plan: dict[str, Any]) -> dict[str, Any]:
    """Ensure each shot carries the additive director-interpretation fields."""
    if not isinstance(scene, dict):
        scene = {}
    if not isinstance(shot_plan, dict):
        return shot_plan
    shots = shot_plan.get("shots")
    if not isinstance(shots, list):
        return shot_plan

    for shot in shots:
        if not isinstance(shot, dict):
            continue
        generated = build_shot_visual_content(scene, shot)

        if not str(shot.get("shot_size") or "").strip():
            shot["shot_size"] = generated["shot_size"]
        if not str(shot.get("dramatic_intent") or "").strip():
            shot["dramatic_intent"] = generated["dramatic_intent"]

        visual_prototype = shot.get("visual_prototype")
        if not isinstance(visual_prototype, dict):
            visual_prototype = {}
        shot["visual_prototype"] = _merge_default_dict(generated["visual_prototype"], visual_prototype)

        camera_language = shot.get("camera_language")
        if not isinstance(camera_language, dict):
            camera_language = {}
        shot["camera_language"] = _merge_default_dict(generated["camera_language"], camera_language)

        visual_content = shot.get("visual_content")
        if not isinstance(visual_content, dict):
            visual_content = {}
        elif "_source" not in visual_content and any(str(visual_content.get(key) or "").strip() for key in VISUAL_CONTENT_FIELDS):
            visual_content = {**visual_content, "_source": "legacy"}
        shot["visual_content"] = _merge_default_dict(generated["visual_content"], visual_content)

    return shot_plan


def _merge_default_dict(defaults: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(defaults)
    for key, value in current.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        merged[key] = deepcopy(value)
    return merged


def build_shot_plan(scene: dict[str, Any]) -> dict[str, Any]:
    """Build the persisted, scene-relative shot plan contract for a scene."""
    if not isinstance(scene, dict):
        scene = {}
    order = int(scene.get("order") or scene.get("scene") or 1)
    scene_id = str(scene.get("scene_id") or f"scene_{order:03d}").strip()
    duration = _scene_duration_seconds(scene)
    temporal_spec = scene.get("temporal_spec") if isinstance(scene.get("temporal_spec"), dict) else {}
    shots_source = temporal_spec.get("shots") if isinstance(temporal_spec, dict) else None
    if not isinstance(shots_source, list) or not shots_source:
        shots_source = []
    source = "temporal_spec" if shots_source else "synthesized"

    shot_timeline: list[dict[str, Any]] = []
    cursor = 0.0
    for shot_index, raw_shot in enumerate(shots_source or [], start=1):
        if not isinstance(raw_shot, dict):
            continue
        try:
            raw_duration = float(raw_shot.get("duration_seconds") or raw_shot.get("duration") or 0.0)
        except (TypeError, ValueError):
            raw_duration = 0.0
        shot_duration = max(0.25, raw_duration)
        shot_start = round(cursor, 3)
        shot_end = round(shot_start + shot_duration, 3)
        shot_timeline.append(
            {
                "shot_id": str(raw_shot.get("shot_id") or f"{scene_id}_shot_{shot_index:02d}"),
                "shot_order": int(raw_shot.get("shot_order") or shot_index),
                "label": str(raw_shot.get("label") or raw_shot.get("beat_type") or f"SHOT {shot_index}").strip(),
                "beat_type": str(raw_shot.get("beat_type") or "").strip(),
                "start_seconds": shot_start,
                "duration_seconds": round(shot_duration, 3),
                "end_seconds": shot_end,
                "camera_movement": str(raw_shot.get("camera_movement") or scene.get("camera_movement") or scene.get("camera") or "").strip(),
                "camera_speed": float(raw_shot.get("camera_speed") or scene.get("camera_speed") or 1.0),
                "zoom": float(raw_shot.get("zoom") or 1.0),
                "hold_in_ratio": float(raw_shot.get("hold_in_ratio") or 0.0),
                "hold_out_ratio": float(raw_shot.get("hold_out_ratio") or 0.0),
                "center_x": float(raw_shot.get("center_x") or 0.5),
                "center_y": float(raw_shot.get("center_y") or 0.5),
                "speaker": str(raw_shot.get("speaker") or scene.get("speaker") or "").strip(),
                "dialogue": str(raw_shot.get("dialogue") or scene.get("dialogue") or "").strip(),
                "emotion": str(raw_shot.get("emotion") or scene.get("emotion_tone") or scene.get("emotion") or "").strip(),
                "scene_intent": str(raw_shot.get("scene_intent") or scene.get("scene_intent") or "").strip(),
                "subject_focus": str(raw_shot.get("subject_focus") or scene.get("subject_focus") or "").strip(),
            }
        )
        cursor += shot_duration

    if shot_timeline:
        total_shot_duration = sum(float(shot.get("duration_seconds") or 0.0) for shot in shot_timeline)
        if total_shot_duration > 0.0 and abs(total_shot_duration - duration) > 0.001:
            scale = duration / total_shot_duration
            cursor = 0.0
            for shot_index, shot in enumerate(shot_timeline):
                shot_start = round(cursor, 3)
                if shot_index == len(shot_timeline) - 1:
                    shot_duration = max(0.001, round(duration - cursor, 3))
                else:
                    shot_duration = max(0.001, round(float(shot.get("duration_seconds") or 0.0) * scale, 3))
                shot["start_seconds"] = shot_start
                shot["duration_seconds"] = shot_duration
                shot["end_seconds"] = round(shot_start + shot_duration, 3)
                cursor += shot_duration

    if not shot_timeline:
        shot_timeline.append(
            {
                "shot_id": f"{scene_id}_shot_01",
                "shot_order": 1,
                "label": "SHOT 1",
                "beat_type": "",
                "start_seconds": 0.0,
                "duration_seconds": duration,
                "end_seconds": duration,
                "camera_movement": str(scene.get("camera_movement") or scene.get("camera") or "").strip(),
                "camera_speed": float(scene.get("camera_speed") or 1.0),
                "zoom": 1.0,
                "hold_in_ratio": 0.0,
                "hold_out_ratio": 0.0,
                "center_x": 0.5,
                "center_y": 0.5,
                "speaker": str(scene.get("speaker") or "").strip(),
                "dialogue": str(scene.get("dialogue") or "").strip(),
                "emotion": str(scene.get("emotion_tone") or scene.get("emotion") or "").strip(),
                "scene_intent": str(scene.get("scene_intent") or "").strip(),
                "subject_focus": str(scene.get("subject_focus") or "").strip(),
            }
        )
        source = "synthesized"

    shot_plan = {
        "version": 1,
        "scene_id": scene_id,
        "scene_order": order,
        "duration_seconds": duration,
        "shot_count": len(shot_timeline),
        "source": source,
        "shots": shot_timeline,
    }
    return normalize_shot_plan_visual_content(scene, shot_plan)


def build_canonical_timeline(project: dict[str, Any]) -> dict[str, Any]:
    scenes_raw = project.get("scenes", []) if isinstance(project, dict) else []
    scenes: list[dict[str, Any]] = [scene for scene in scenes_raw if isinstance(scene, dict)]
    scenes.sort(key=lambda scene: int(scene.get("order") or 0))

    project_id = str(project.get("project_id") or "").strip() if isinstance(project, dict) else ""
    title = str(project.get("title") or "").strip() if isinstance(project, dict) else ""
    settings = project.get("settings") if isinstance(project, dict) and isinstance(project.get("settings"), dict) else {}
    size = {"width": 1080, "height": 1920, "fps": 24}
    total_duration = 0.0
    picture_items: list[dict[str, Any]] = []
    audio_items: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    scene_index: list[dict[str, Any]] = []
    real_video_scene_count = 0
    fallback_scene_count = 0

    for index, scene in enumerate(scenes, start=1):
        order = int(scene.get("order") or index)
        scene_id = str(scene.get("scene_id") or f"scene_{order:03d}").strip()
        scene_title = str(scene.get("title") or f"Scene {order}").strip()
        duration = _scene_duration_seconds(scene)
        start_seconds = round(total_duration, 3)
        end_seconds = round(start_seconds + duration, 3)
        total_duration = end_seconds
        temporal_spec = scene.get("temporal_spec") if isinstance(scene.get("temporal_spec"), dict) else {}
        shot_plan = build_shot_plan(scene)
        shot_timeline = deepcopy(shot_plan.get("shots") or [])
        video_ref = _scene_media_reference(scene, "video")
        image_ref = _scene_media_reference(scene, "image")
        picture_ref = video_ref if video_ref.get("path") or video_ref.get("url") else image_ref
        generation_meta = deepcopy(scene.get("generation_meta") or {}) if isinstance(scene.get("generation_meta"), dict) else {}
        if generation_meta.get("is_real_video") is True:
            real_video_scene_count += 1
        if generation_meta.get("fallback_used") is True:
            fallback_scene_count += 1
        picture_item = {
            "item_type": "clip",
            "clip_id": f"{scene_id}_picture",
            "scene_id": scene_id,
            "scene_order": order,
            "name": scene_title,
            "start_seconds": start_seconds,
            "duration_seconds": duration,
            "end_seconds": end_seconds,
            "source_range": {"start_seconds": 0.0, "duration_seconds": duration},
            "media_reference": picture_ref,
            "metadata": {
                "emotion_tone": str(scene.get("emotion_tone") or scene.get("emotion") or "").strip(),
                "pacing": str(scene.get("pacing") or "").strip(),
                "camera_movement": str(scene.get("camera_movement") or scene.get("camera") or "").strip(),
                "scene_intent": str(scene.get("scene_intent") or "").strip(),
                "subject_focus": str(scene.get("subject_focus") or "").strip(),
                "production_bible": deepcopy(scene.get("production_bible") or {}) if isinstance(scene.get("production_bible"), dict) else {},
                "temporal_spec": deepcopy(temporal_spec) if isinstance(temporal_spec, dict) else {},
                "shot_plan_source": str(shot_plan.get("source") or "").strip(),
                "generation": generation_meta,
            },
            "shot_timeline": shot_timeline,
        }
        audio_item = {
            "item_type": "clip",
            "clip_id": f"{scene_id}_audio",
            "scene_id": scene_id,
            "scene_order": order,
            "name": scene_title,
            "start_seconds": start_seconds,
            "duration_seconds": duration,
            "end_seconds": end_seconds,
            "source_range": {"start_seconds": 0.0, "duration_seconds": duration},
            "media_reference": _scene_media_reference(scene, "audio"),
            "metadata": {
                "speaker": str(scene.get("speaker") or "").strip(),
                "voice_profile": str(scene.get("voice_profile") or "").strip(),
                "voice_engine": str(scene.get("voice_engine") or "").strip(),
                "voice_id": str(scene.get("voice_id") or "").strip(),
                "emotion_tone": str(scene.get("emotion_tone") or scene.get("emotion") or "").strip(),
            },
        }
        picture_items.append(picture_item)
        audio_items.append(audio_item)
        scene_index.append(
            {
                "scene_id": scene_id,
                "scene_order": order,
                "title": scene_title,
                "clip_id": picture_item["clip_id"],
                "shot_count": len(shot_timeline),
                "start_seconds": start_seconds,
                "duration_seconds": duration,
                "end_seconds": end_seconds,
            }
        )
        if index < len(scenes):
            next_scene = scenes[index]
            next_order = int(next_scene.get("order") or index + 1)
            next_scene_id = str(next_scene.get("scene_id") or f"scene_{next_order:03d}").strip()
            transition_kind = _scene_transition(scene.get("emotion_tone") or scene.get("emotion") or "", next_scene.get("emotion_tone") or next_scene.get("emotion") or "")
            transition_duration = 0.0 if transition_kind == "cut" else 0.2 if transition_kind == "xfade" else 0.3
            transitions.append(
                {
                    "transition_id": f"{scene_id}_to_{next_scene_id}",
                    "from_scene_id": scene_id,
                    "to_scene_id": next_scene_id,
                    "from_order": order,
                    "to_order": next_order,
                    "kind": transition_kind,
                    "duration_seconds": transition_duration,
                }
            )

    return {
        "version": 1,
        "kind": "canonical_timeline",
        "schema": "otio-inspired",
        "project_id": project_id,
        "title": title or "Storyboard Timeline",
        "frame_rate": int(size["fps"]),
        "resolution": {"width": int(size["width"]), "height": int(size["height"])},
        "duration_seconds": round(total_duration, 3),
        "scene_count": len(scene_index),
        "shot_count": sum(len(item.get("shot_timeline") or []) for item in picture_items),
        "summary": {
            "scene_count": len(scene_index),
            "shot_count": sum(len(item.get("shot_timeline") or []) for item in picture_items),
            "transition_count": len(transitions),
            "real_video_scene_count": real_video_scene_count,
            "fallback_scene_count": fallback_scene_count,
        },
        "metadata": {
            "project_id": project_id,
            "title": title,
            "style_id": str(project.get("style_id") or "").strip() if isinstance(project, dict) else "",
            "episode_pacing": deepcopy(settings.get("episode_pacing")) if isinstance(settings.get("episode_pacing"), dict) else {},
            "production_bible": deepcopy(project.get("production_bible") or {}) if isinstance(project, dict) and isinstance(project.get("production_bible"), dict) else {},
        },
        "tracks": [
            {
                "track_id": "picture",
                "track_type": "video",
                "name": "Picture",
                "children": picture_items,
            },
            {
                "track_id": "dialogue",
                "track_type": "audio",
                "name": "Dialogue",
                "children": audio_items,
            },
        ],
        "transitions": transitions,
        "scene_index": scene_index,
    }


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


def create_keyframe(scene: StoryScene, run_dir: Path) -> Path:
    scene_id = f"{scene.scene:02}"
    out = run_dir / f"scene_{scene_id}_keyframe.png"
    size = (1080, 1920)
    base = Image.new("RGBA", size, hex_to_rgb(scene.bg_color) + (255,))
    draw = ImageDraw.Draw(base, "RGBA")

    top_rgb = blend_color(scene.bg_color, 0.12)
    bottom_rgb = blend_color(scene.bg_color, 0.62)
    for y in range(size[1]):
        t = y / max(1, size[1] - 1)
        rgb = (
            int(top_rgb[0] * (1 - t) + bottom_rgb[0] * t),
            int(top_rgb[1] * (1 - t) + bottom_rgb[1] * t),
            int(top_rgb[2] * (1 - t) + bottom_rgb[2] * t),
        )
        draw.line((0, y, size[0], y), fill=rgb + (255,))

    rng = random.Random(scene.scene * 17)
    accent = hex_to_rgb(scene.accent_color)

    rain = Image.new("RGBA", size, (0, 0, 0, 0))
    rain_draw = ImageDraw.Draw(rain, "RGBA")
    for _ in range(140):
        x = rng.randint(-80, size[0] + 80)
        y = rng.randint(0, size[1])
        length = rng.randint(40, 180)
        alpha = rng.randint(14, 38)
        rain_draw.line((x, y, x + 18, y + length), fill=accent + (alpha,), width=rng.randint(1, 2))
    rain = rain.filter(ImageFilter.GaussianBlur(0.5))
    base = Image.alpha_composite(base, rain)

    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow, "RGBA")
    glow_draw.ellipse((-140, 140, 980, 980), fill=accent + (68,))
    glow_draw.ellipse((250, 1120, 1220, 1860), fill=(255, 255, 255, 16))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    base = Image.alpha_composite(base, glow)
    draw = ImageDraw.Draw(base, "RGBA")

    horizon_y = 1210
    draw.rectangle((0, horizon_y, size[0], size[1]), fill=(0, 0, 0, 42))
    draw.polygon([(0, 1180), (260, 1020), (420, 1110), (720, 980), (1080, 1120), (1080, 1920), (0, 1920)], fill=(8, 10, 18, 122))

    silhouette = [(200, 1460), (250, 1170), (320, 1080), (390, 1160), (420, 1480), (360, 1600), (240, 1600)]
    draw.polygon(silhouette, fill=(8, 8, 12, 210))
    draw.ellipse((318, 1032, 430, 1148), fill=(18, 18, 24, 220))
    draw.polygon([(630, 1540), (690, 1220), (760, 1120), (840, 1200), (862, 1510), (792, 1640), (650, 1640)], fill=(12, 12, 18, 200))
    draw.ellipse((742, 1068, 870, 1184), fill=(24, 24, 30, 220))

    title_font = pick_font(64, bold=True)
    subtitle_font = pick_font(34, bold=True)
    meta_font = pick_font(24, bold=True)
    body_font = pick_font(40, bold=True)

    title_box = (60, 70, 430, 216)
    draw.rounded_rectangle(title_box, radius=24, fill=(6, 8, 14, 190), outline=accent + (180,), width=3)
    draw.text((92, 98), scene.title, font=title_font, fill=(255, 255, 255, 255))
    draw.text((92, 166), scene.camera, font=meta_font, fill=accent + (255,))

    bottom_box = (74, 1602, 1006, 1838)
    draw.rounded_rectangle(bottom_box, radius=30, fill=(8, 10, 16, 202), outline=accent + (160,), width=3)
    draw.text((108, 1640), scene.emotion, font=subtitle_font, fill=accent + (255,))
    draw_paragraph(draw, scene.dialogue, (108, 1698, 962, 1810), body_font, (245, 245, 245, 255), spacing=10)

    for idx, character in enumerate(scene.characters[:3]):
        chip_x = 600 + idx * 150
        draw.rounded_rectangle((chip_x, 96, chip_x + 128, 146), radius=18, fill=accent + (34,), outline=accent + (160,), width=2)
        draw.text((chip_x + 16, 105), character[:6], font=meta_font, fill=(250, 250, 250, 240))

    for _ in range(28):
        x = rng.randint(0, size[0])
        y = rng.randint(0, size[1])
        length = rng.randint(20, 80)
        draw.line((x, y, x + rng.randint(-16, 16), y + length), fill=(255, 255, 255, rng.randint(18, 42)), width=1)

    base = base.filter(ImageFilter.GaussianBlur(0.2))
    base.convert("RGB").save(out, quality=95)
    return out


def compose_comic_frame(
    source_image: Image.Image,
    scene: StoryScene,
    beat: dict[str, object],
    run_dir: Path,
    scene_id: str,
    beat_index: int,
    beat_total: int,
) -> Path:
    size = source_image.size
    frame = focal_crop(
        source_image,
        float(beat["zoom"]),
        float(beat["center_x"]),
        float(beat["center_y"]),
    ).convert("RGBA")
    accent = hex_to_rgb(scene.accent_color)

    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay, "RGBA")
    overlay_draw.rectangle((0, 0, size[0], 132), fill=(6, 8, 14, 72))
    overlay_draw.rectangle((0, size[1] - 250, size[0], size[1]), fill=(6, 8, 14, 140))
    overlay_draw.rectangle((0, size[1] - 266, size[0], size[1] - 256), fill=accent + (180,))
    overlay_draw.rounded_rectangle((52, 44, 360, 140), radius=22, fill=(10, 12, 20, 168), outline=accent + (160,), width=2)
    overlay_draw.rounded_rectangle((size[0] - 264, 44, size[0] - 52, 140), radius=22, fill=accent + (34,), outline=accent + (160,), width=2)
    overlay_draw.rounded_rectangle((64, size[1] - 206, size[0] - 64, size[1] - 72), radius=26, fill=(8, 10, 16, 190), outline=(255, 255, 255, 54), width=2)
    frame = Image.alpha_composite(frame, overlay)
    draw = ImageDraw.Draw(frame, "RGBA")

    display_index = max(1, int(beat_index))
    title_font = pick_font(32, bold=True)
    meta_font = pick_font(22, bold=True)
    body_font = pick_font(36, bold=True)

    draw.text((78, 66), scene.title, font=title_font, fill=(255, 255, 255, 255))
    draw.text((78, 104), str(beat["label"])[:18], font=meta_font, fill=accent + (255,))
    draw.text((size[0] - 236, 66), f"{display_index}/{beat_total}", font=meta_font, fill=(250, 250, 250, 220))
    draw.text((size[0] - 236, 104), str(beat["caption"])[:10], font=meta_font, fill=(250, 250, 250, 180))

    subtitle = str(beat["bubble"]) or scene.dialogue
    draw_paragraph(draw, subtitle, (92, size[1] - 184, size[0] - 92, size[1] - 88), body_font, (245, 245, 245, 255), spacing=8)

    footer = f"{scene.camera}  |  {scene.emotion}"
    footer_bbox = draw.textbbox((0, 0), footer, font=meta_font)
    draw.text(((size[0] - (footer_bbox[2] - footer_bbox[0])) / 2, size[1] - 54), footer, font=meta_font, fill=(240, 240, 240, 180))

    out = run_dir / f"scene_{scene_id}_beat_{display_index}.png"
    frame.convert("RGB").save(out, quality=95)
    return out


def comfyui_base_url() -> str:
    tunnel_url = ensure_comfyui_tunnel()
    if tunnel_url:
        return tunnel_url.rstrip("/")
    return env_value("COMFYUI_BASE_URL", "COMFYUI_URL", default="http://127.0.0.1:8188").rstrip("/")


def comfyui_auth_headers() -> dict[str, str]:
    raw = env_value("COMFYUI_AUTH_HEADER", default="").strip()
    if raw and ":" in raw:
        key, value = raw.split(":", 1)
        return {key.strip(): value.strip()}
    api_key = env_value("COMFYUI_API_KEY", default="").strip()
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def comfyui_workflow_path() -> Path:
    raw = env_value("COMFYUI_WORKFLOW_PATH", default=str(WORKFLOWS / "comfyui_keyframe_template.json"))
    return Path(raw)


def comfyui_video_workflow_path() -> Path:
    raw = env_value("COMFYUI_VIDEO_WORKFLOW_PATH", "VIDEO_WORKFLOW_PATH", default=str(WORKFLOWS / "comfyui_video_template.json"))
    return Path(raw)


def comfyui_input_dir() -> Path | None:
    raw = env_value("COMFYUI_INPUT_DIR", default="").strip()
    return Path(raw) if raw else None


def comfyui_reference_mode() -> str:
    return env_value("COMFYUI_REFERENCE_MODE", default="auto").strip().lower() or "auto"


def comfyui_is_local() -> bool:
    parsed = urlparse(comfyui_base_url())
    return parsed.hostname in {"127.0.0.1", "localhost", "::1", None}


def default_comfyui_reference_image_path() -> Path:
    return OUTPUTS / "comfyui_default_reference.png"


def ensure_default_comfyui_reference_image() -> Path:
    path = default_comfyui_reference_image_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    size = (512, 768)
    base = Image.new("RGBA", size, (28, 24, 32, 255))
    draw = ImageDraw.Draw(base, "RGBA")

    for y in range(size[1]):
        blend = y / max(1, size[1] - 1)
        r = int(28 + 38 * blend)
        g = int(24 + 20 * blend)
        b = int(32 + 24 * blend)
        draw.line((0, y, size[0], y), fill=(r, g, b, 255))

    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow, "RGBA")
    glow_draw.ellipse((44, 64, 468, 724), fill=(92, 124, 160, 60))
    glow_draw.ellipse((108, 116, 404, 660), fill=(38, 48, 70, 110))
    glow = glow.filter(ImageFilter.GaussianBlur(44))
    base = Image.alpha_composite(base, glow)
    draw = ImageDraw.Draw(base, "RGBA")

    draw.ellipse((158, 146, 354, 366), fill=(202, 176, 158, 255))
    draw.polygon([(158, 166), (182, 122), (234, 94), (286, 92), (334, 120), (356, 168), (350, 206), (322, 182), (288, 170), (228, 170), (190, 182)], fill=(16, 16, 20, 255))
    draw.polygon([(168, 204), (178, 294), (170, 388), (184, 456), (214, 510), (236, 548), (144, 534), (126, 398), (134, 282)], fill=(16, 16, 20, 240))
    draw.polygon([(344, 204), (334, 294), (342, 388), (328, 456), (298, 510), (276, 548), (368, 534), (386, 398), (378, 282)], fill=(16, 16, 20, 240))
    draw.polygon([(174, 136), (202, 108), (230, 96), (258, 92), (290, 98), (318, 118), (300, 134), (270, 126), (236, 124), (198, 132)], fill=(10, 10, 14, 255))
    draw.polygon([(140, 154), (154, 214), (138, 266), (126, 230), (122, 182)], fill=(10, 10, 14, 220))
    draw.polygon([(374, 154), (360, 214), (376, 266), (388, 230), (392, 182)], fill=(10, 10, 14, 220))

    draw.arc((194, 210, 242, 238), start=180, end=360, fill=(50, 38, 30, 255), width=4)
    draw.arc((268, 210, 316, 238), start=180, end=360, fill=(50, 38, 30, 255), width=4)
    draw.line((238, 258, 246, 298), fill=(116, 84, 76, 180), width=3)
    draw.line((218, 318, 286, 318), fill=(88, 52, 60, 190), width=4)
    draw.line((182, 224, 206, 220), fill=(48, 34, 32, 180), width=4)
    draw.line((306, 220, 330, 224), fill=(48, 34, 32, 180), width=4)
    draw.line((196, 286, 184, 302), fill=(122, 86, 82, 140), width=2)
    draw.line((304, 286, 316, 302), fill=(122, 86, 82, 140), width=2)
    draw.ellipse((166, 252, 182, 262), fill=(120, 74, 76, 68))
    draw.ellipse((330, 252, 346, 262), fill=(120, 74, 76, 68))

    robe = [(94, 620), (160, 444), (206, 384), (256, 404), (306, 384), (354, 444), (418, 620), (392, 748), (120, 748)]
    draw.polygon(robe, fill=(92, 96, 104, 255))
    collar = [(194, 394), (256, 452), (318, 394), (344, 426), (256, 506), (168, 426)]
    draw.polygon(collar, fill=(176, 172, 160, 255))
    draw.polygon([(206, 458), (256, 540), (304, 458), (332, 468), (286, 572), (226, 572), (180, 468)], fill=(64, 68, 76, 255))

    for x in range(4):
        draw.line((126 + x * 24, 560, 378 - x * 20, 726), fill=(46, 50, 58, 120), width=3)

    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow, "RGBA")
    shadow_draw.ellipse((104, 130, 410, 420), fill=(0, 0, 0, 42))
    shadow_draw.ellipse((140, 410, 372, 754), fill=(0, 0, 0, 64))
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    base = Image.alpha_composite(base, shadow)

    draw = ImageDraw.Draw(base, "RGBA")
    draw.ellipse((204, 226, 228, 246), fill=(30, 24, 28, 255))
    draw.ellipse((284, 226, 308, 246), fill=(30, 24, 28, 255))
    draw.line((226, 250, 246, 258), fill=(108, 76, 68, 180), width=2)
    draw.line((282, 250, 302, 258), fill=(108, 76, 68, 180), width=2)
    base.convert("RGB").save(path, quality=95)
    return path


def comfyui_upload_image(source: Path, *, subfolder: str = "comicdrama_refs") -> dict[str, str]:
    boundary = f"----comicdrama{random.randint(100000000, 999999999)}"
    filename = source.name
    content_type = "image/png"
    if source.suffix.lower() in {".jpg", ".jpeg"}:
        content_type = "image/jpeg"
    elif source.suffix.lower() == ".webp":
        content_type = "image/webp"
    image_bytes = source.read_bytes()

    def form_field(name: str, value: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")

    body = bytearray()
    body.extend(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    body.extend(image_bytes)
    body.extend(b"\r\n")
    body.extend(form_field("type", "input"))
    body.extend(form_field("subfolder", subfolder))
    body.extend(form_field("overwrite", "true"))
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    request = Request(
        f"{comfyui_base_url()}/upload/image",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", **comfyui_auth_headers()},
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ComfyUI image upload failed with HTTP {exc.code}: {body_text}") from exc

    name = str(payload.get("name") or filename)
    remote_subfolder = str(payload.get("subfolder") or subfolder).strip("/")
    load_name = f"{remote_subfolder}/{name}" if remote_subfolder else name
    return {"source": str(source), "load_image": load_name, "absolute": load_name}


def prepare_comfyui_reference_image(scene: StoryScene) -> dict[str, str]:
    raw_path = (scene.primary_reference_image_abs_path or scene.primary_reference_image_path or "").strip()
    placeholder = False
    if not raw_path:
        source = ensure_default_comfyui_reference_image()
        placeholder = True
    else:
        source = Path(raw_path)
        if not source.is_file():
            source = ensure_default_comfyui_reference_image()
            placeholder = True

    absolute = str(source.resolve())
    mode = comfyui_reference_mode()
    if mode == "upload" or (mode == "auto" and not comfyui_is_local()):
        uploaded = comfyui_upload_image(source)
        uploaded["placeholder"] = placeholder
        return uploaded
    if mode == "absolute":
        return {"source": raw_path or "__generated_default_reference__", "load_image": absolute, "absolute": absolute, "placeholder": placeholder}

    input_dir = comfyui_input_dir()
    if not input_dir:
        if mode == "auto" and not comfyui_is_local():
            uploaded = comfyui_upload_image(source)
            uploaded["placeholder"] = placeholder
            return uploaded
        return {"source": raw_path or "__generated_default_reference__", "load_image": absolute, "absolute": absolute, "placeholder": placeholder}

    target_dir = input_dir / "comicdrama_refs"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_name = f"scene_{scene.scene:02}_{source.stem}{source.suffix.lower() or '.png'}"
    target = target_dir / target_name
    shutil.copy2(source, target)
    load_name = f"comicdrama_refs/{target.name}"
    return {"source": raw_path or "__generated_default_reference__", "load_image": load_name, "absolute": str(target.resolve()), "placeholder": placeholder}


def _build_consistency_meta(scene: StoryScene, reference_info: dict[str, str], ip_adapter_weight: float) -> dict[str, Any]:
    primary_meta = scene.primary_reference_meta if isinstance(scene.primary_reference_meta, dict) else {}
    warnings = [str(item) for item in (primary_meta.get("warnings") or []) if str(item).strip()]
    placeholder = bool(reference_info.get("placeholder"))
    if placeholder:
        warnings.append("使用占位参考图，IPAdapter 权重已降级")

    load_image = str(reference_info.get("load_image") or "").strip() or None
    source_value = str(reference_info.get("source") or reference_info.get("absolute") or "").strip()
    reference_path = source_value if source_value and Path(source_value).exists() else None
    absolute = bool(load_image and Path(load_image).is_absolute())

    return {
        "reference_path": reference_path,
        "load_image": load_image,
        "absolute": absolute,
        "placeholder": placeholder,
        "crop_method": primary_meta.get("crop_method"),
        "ip_adapter_weight": ip_adapter_weight,
        "warnings": warnings,
        "errors": [],
        "injected_at": time.time(),
    }


def _initial_consistency_meta(scene: StoryScene) -> dict[str, Any]:
    primary_meta = scene.primary_reference_meta if isinstance(scene.primary_reference_meta, dict) else {}
    warnings = [str(item) for item in (primary_meta.get("warnings") or []) if str(item).strip()]
    reference_path = None
    raw_abs = str(scene.primary_reference_image_abs_path or "").strip()
    raw_rel = str(scene.primary_reference_image_path or "").strip()
    if raw_abs and Path(raw_abs).is_file():
        reference_path = str(Path(raw_abs).resolve())
    elif raw_rel and Path(raw_rel).is_file():
        reference_path = str(Path(raw_rel).resolve())

    return {
        "reference_path": reference_path,
        "load_image": None,
        "absolute": False,
        "placeholder": True,
        "crop_method": primary_meta.get("crop_method"),
        "ip_adapter_weight": None,
        "warnings": warnings,
        "errors": [],
        "injected_at": time.time(),
    }


def submit_comfyui_prompt(workflow: dict, prompt_id: str, client_id: str) -> dict:
    payload = {
        "prompt": workflow,
        "client_id": client_id,
        "prompt_id": prompt_id,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    url = f"{comfyui_base_url()}/prompt"
    request = Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    for k, v in comfyui_auth_headers().items():
        request.add_header(k, v)
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ComfyUI /prompt failed with HTTP {exc.code}: {body}") from exc


def poll_comfyui_history(prompt_id: str, timeout_s: int = 300) -> dict:
    deadline = time.time() + timeout_s
    url = f"{comfyui_base_url()}/history/{prompt_id}"
    while time.time() < deadline:
        try:
            req = Request(url)
            for k, v in comfyui_auth_headers().items():
                req.add_header(k, v)
            with urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if prompt_id in payload:
                return payload[prompt_id]
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError(f"Timed out waiting for ComfyUI prompt {prompt_id}")


def download_comfyui_image(image_info: dict, out_path: Path) -> None:
    from urllib.parse import urlencode

    query = {
        "filename": image_info["filename"],
        "subfolder": image_info.get("subfolder", ""),
        "type": image_info.get("type", "output"),
    }
    url = f"{comfyui_base_url()}/view?{urlencode(query)}"
    req = Request(url)
    for k, v in comfyui_auth_headers().items():
        req.add_header(k, v)
    with urlopen(req, timeout=60) as response:
        out_path.write_bytes(response.read())


def download_comfyui_asset(asset_info: dict, out_path: Path) -> None:
    from urllib.parse import urlencode

    query = {
        "filename": asset_info["filename"],
        "subfolder": asset_info.get("subfolder", ""),
        "type": asset_info.get("type", "output"),
    }
    url = f"{comfyui_base_url()}/view?{urlencode(query)}"
    req = Request(url)
    for k, v in comfyui_auth_headers().items():
        req.add_header(k, v)
    with urlopen(req, timeout=60) as response:
        out_path.write_bytes(response.read())


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
            f"hard_constraints: {', '.join(str(item) for item in constraints.get('hard', []) if item)}",
            f"soft_constraints: {', '.join(str(item) for item in constraints.get('soft', []) if item)}",
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
        lines.append("; ".join(str(part).strip() for part in parts if str(part).strip() and not str(part).endswith(": None")))
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


def render_scene_video_comfyui(scene: StoryScene, keyframe_path: Path, duration: float, out_path: Path, run_dir: Path) -> Path:
    workflow_path = comfyui_video_workflow_path()
    if not workflow_path.exists():
        raise FileNotFoundError(f"ComfyUI video workflow template not found: {workflow_path}")

    run_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = run_dir / "debug"
    prompt_text, negative_text = build_scene_video_prompts(scene, duration, run_dir)
    temporal_spec = scene.temporal_spec or build_scene_temporal_spec(
        scene,
        duration,
        width=int(env_float("VIDEO_WIDTH", default=1080)),
        height=int(env_float("VIDEO_HEIGHT", default=1920)),
        fps=int(env_float("VIDEO_FPS", default=24)),
    )
    consistency_spec = scene_consistency_spec(scene)

    workflow = load_json(workflow_path)
    prompt_id = f"comicdrama-video-{scene.scene:02}-{int(time.time() * 1000)}"
    client_id = f"client-{random.randint(100000, 999999)}"
    keyframe_info = comfyui_upload_image(keyframe_path)
    replacements = {
        "__PROMPT__": prompt_text,
        "__NEGATIVE__": negative_text,
        "__SEED__": scene.scene * 20011 + 97,
        "__WIDTH__": int(env_float("VIDEO_WIDTH", default=1080)),
        "__HEIGHT__": int(env_float("VIDEO_HEIGHT", default=1920)),
        "__STEPS__": int(env_float("VIDEO_STEPS", default=18)),
        "__CFG__": env_float("VIDEO_CFG", default=6.5),
        "__DURATION__": float(duration),
        "__DURATION_SECONDS__": float(duration),
        "__FPS__": int(env_float("VIDEO_FPS", default=24)),
        "__PRIMARY_REFERENCE_IMAGE__": keyframe_info["load_image"],
        "__REFERENCE_IMAGE__": keyframe_info["load_image"],
        "__KEYFRAME_IMAGE__": keyframe_info["load_image"],
        "__SCENE_TITLE__": scene.title,
        "__SCENE_DIALOGUE__": scene.dialogue,
        "__SCENE_CAMERA__": scene.camera,
        "__SCENE_EMOTION__": scene.emotion,
        "__CHARACTER_DESCRIPTIONS__": scene.character_descriptions,
        "__VIDEO_CHECKPOINT_NAME__": comfyui_checkpoint_name(),
        "__VIDEO_LORA_NAME__": comfyui_lora_name(),
        "__VIDEO_LORA_STRENGTH_MODEL__": env_float("COMFYUI_VIDEO_LORA_STRENGTH_MODEL", default=0.7),
        "__VIDEO_LORA_STRENGTH_CLIP__": env_float("COMFYUI_VIDEO_LORA_STRENGTH_CLIP", default=0.7),
        "__VIDEO_IP_ADAPTER_WEIGHT__": env_float("COMFYUI_VIDEO_IP_ADAPTER_WEIGHT", default=0.65),
    }
    injected = replace_placeholders(workflow, replacements)
    if not isinstance(injected, dict):
        raise ValueError("ComfyUI video workflow template must resolve to a JSON object.")
    unresolved = unresolved_placeholders(injected)
    if unresolved:
        write_debug_json(debug_dir / f"scene_{scene.scene:02}_video_unresolved.json", unresolved)
        raise ValueError(f"ComfyUI video workflow has unresolved placeholders: {', '.join(unresolved[:5])}")

    write_debug_json(
        debug_dir / f"scene_{scene.scene:02}_video_request_meta.json",
        {
            "scene": scene.scene,
            "title": scene.title,
            "base_url": comfyui_base_url(),
            "workflow_path": str(workflow_path),
            "prompt_id": prompt_id,
            "client_id": client_id,
            "keyframe_info": keyframe_info,
            "duration": duration,
            "prompt_text": prompt_text,
            "temporal_spec": temporal_spec,
            "consistency_spec": consistency_spec,
        },
    )
    write_debug_json(debug_dir / f"scene_{scene.scene:02}_video_filled_workflow.json", injected)

    try:
        submit_response = submit_comfyui_prompt(injected, prompt_id, client_id)
        write_debug_json(debug_dir / f"scene_{scene.scene:02}_video_submit_response.json", submit_response)
        prompt_id = str(submit_response.get("prompt_id", prompt_id))
        history = poll_comfyui_history(prompt_id, timeout_s=max(300, int(max(30.0, duration) * 60)))
        write_debug_json(debug_dir / f"scene_{scene.scene:02}_video_history.json", history)
        status = history.get("status", {})
        status_str = str(status.get("status_str") or "").lower()
        completed = status.get("completed")
        if completed is False or status_str in {"error", "failed", "failure"}:
            raise RuntimeError(f"ComfyUI video workflow failed: {json.dumps(status, ensure_ascii=False)}")
    except Exception as exc:
        raise RuntimeError(f"ComfyUI video generation failed: {exc}") from exc

    outputs = history.get("outputs", {})
    for node_id, node_output in outputs.items():
        for field in ("videos", "gifs"):
            items = node_output.get(field) or []
            if not items:
                continue
            asset_info = items[0]
            filename = str(asset_info.get("filename") or "")
            suffix = Path(filename).suffix.lower() or ".mp4"
            download_path = out_path if suffix == out_path.suffix.lower() else out_path.with_name(f"{out_path.stem}_source{suffix}")
            download_comfyui_asset(asset_info, download_path)
            if download_path != out_path:
                ffmpeg = get_ffmpeg_exe()
                run_guarded(
                    [
                        ffmpeg,
                        "-y",
                        "-i",
                        str(download_path),
                        "-t",
                        f"{float(duration):.3f}",
                        "-an",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "medium",
                        "-crf",
                        "18",
                        "-pix_fmt",
                        "yuv420p",
                        str(out_path),
                    ],
                    cwd=run_dir,
                    timeout=render_timeout(duration) + 300,
                    stage="ffmpeg_transcode_comfyui_video",
                )
            write_debug_json(
                debug_dir / f"scene_{scene.scene:02}_video_downloaded_asset.json",
                {"node_id": node_id, "field": field, "asset": asset_info, "output_path": str(out_path)},
            )
            return out_path

    raise RuntimeError(f"ComfyUI video workflow completed but returned no video media. Debug: {debug_dir}")


def render_keyframe_comfyui(scene: StoryScene, run_dir: Path) -> Path:
    workflow_path = comfyui_workflow_path()
    if not workflow_path.exists():
        raise FileNotFoundError(f"ComfyUI workflow template not found: {workflow_path}")
    run_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = run_dir / "debug"

    # Quality prefix for better keyframe generation
    quality_prefix = "masterpiece, best quality, full color, vibrant colors, digital painting, colored, highly detailed"

    prompt_parts = [quality_prefix, clean_comfyui_visual_prompt(scene.visual)]
    prompt_parts.append(infer_character_appearance_hint(scene))
    if scene.character_prompt_compilation:
        prompt_parts.append(scene.character_prompt_compilation)
    if scene.character_descriptions:
        prompt_parts.append(scene.character_descriptions)
    # Add composition tags
    prompt_parts.append("cinematic composition, dramatic lighting")
    prompt_text = anime_visual_prompt(
        ", ".join(part for part in prompt_parts if part),
        title=scene.title,
        characters=scene.characters,
        camera=scene.camera,
        emotion=scene.emotion,
    )
    project_root = find_project_root(run_dir)
    if project_root is not None:
        compiler = PromptCompiler(project_root)
        prompt_source_parts = [clean_comfyui_visual_prompt(scene.visual)]
        if scene.character_prompt_compilation:
            prompt_source_parts.append(str(scene.character_prompt_compilation).strip())
        if scene.character_descriptions:
            prompt_source_parts.append(scene.character_descriptions)
        compiled = compiler.compile(
            ", ".join(part for part in prompt_source_parts if part),
            list(scene.characters or []),
            speaker=scene.speaker,
        )
        # Prepend quality tags to compiled output
        compiled_with_quality = ", ".join(
            part for part in [quality_prefix, compiled.positive, "cinematic composition, dramatic lighting"] if str(part).strip()
        )
        prompt_text = anime_visual_prompt(
            compiled_with_quality,
            title=scene.title,
            characters=scene.characters,
            camera=scene.camera,
            emotion=scene.emotion,
        )
    references_json = json.dumps(scene.character_references or [], ensure_ascii=False)
    scene.consistency_meta = _initial_consistency_meta(scene)
    try:
        reference_info = prepare_comfyui_reference_image(scene)
    except Exception as exc:
        scene.consistency_meta.setdefault("errors", []).append(str(exc))
        raise
    workflow = load_json(workflow_path)
    prompt_id = f"comicdrama-{scene.scene:02}-{int(time.time() * 1000)}"
    client_id = f"client-{random.randint(100000, 999999)}"
    ip_adapter_weight = env_float("COMFYUI_IP_ADAPTER_WEIGHT", default=0.65)
    if reference_info.get("placeholder"):
        ip_adapter_weight = min(ip_adapter_weight, env_float("COMFYUI_PLACEHOLDER_IP_ADAPTER_WEIGHT", default=0.0))
    checkpoint_name = comfyui_checkpoint_name()
    lora_name = comfyui_lora_name()
    style_preset = comfyui_style_preset()
    replacements = {
        "__PROMPT__": prompt_text,
        "__NEGATIVE__": ", ".join(
            part
            for part in [
                "worst quality, low quality, normal quality",
                ANIME_NEGATIVE_PROMPT_EXTRA,
                "bad anatomy, bad hands, extra fingers, fewer fingers, extra limbs, deformed, disfigured, watermark, text, signature",
                scene.negative_prompt_compilation,
            ]
            if part
        ),
        "__SEED__": scene.scene * 10007,
        "__WIDTH__": int(env_float("COMFYUI_WIDTH", default=1080)),
        "__HEIGHT__": int(env_float("COMFYUI_HEIGHT", default=1920)),
        "__STEPS__": int(env_float("COMFYUI_STEPS", default=20)),
        "__CFG__": env_float("COMFYUI_CFG", default=7.0),
        "__TITLE__": scene.title,
        "__VISUAL__": prompt_text,
        "__DIALOGUE__": scene.dialogue,
        "__CHARACTER_DESCRIPTIONS__": scene.character_descriptions,
        "__REFERENCE_IMAGE_PATHS_JSON__": references_json,
        "__PRIMARY_REFERENCE_IMAGE__": reference_info["load_image"],
        "__PRIMARY_REFERENCE_IMAGE_ABS__": reference_info["absolute"],
        "__PRIMARY_REFERENCE_SOURCE__": reference_info["source"],
        "__IP_ADAPTER_IMAGE__": reference_info["load_image"],
        "__FACEID_IMAGE__": reference_info["load_image"],
        "__FACEID_LORA_STRENGTH__": env_float("COMFYUI_FACEID_LORA_STRENGTH", default=0.6),
        "__IP_ADAPTER_WEIGHT__": ip_adapter_weight,
        "__FACEID_WEIGHT__": env_float("COMFYUI_FACEID_WEIGHT", default=2.0),
        "__LORA_NAME__": lora_name,
        "__LORA_STRENGTH_MODEL__": env_float("COMFYUI_LORA_STRENGTH_MODEL", default=0.8),
        "__LORA_STRENGTH_CLIP__": env_float("COMFYUI_LORA_STRENGTH_CLIP", default=0.8),
        "__CHARACTER_COUNT__": len(scene.character_references or []),
    }
    scene.consistency_meta = _build_consistency_meta(scene, reference_info, ip_adapter_weight)
    workflow = patch_workflow(
        workflow,
        positive_prompt="__PROMPT__\n__CHARACTER_DESCRIPTIONS__",
        negative_prompt="blurry, noisy, messy, lowres, jpeg, artifacts, ill, distorted, malformed, watermark, __NEGATIVE__",
        reference_image_filename="__PRIMARY_REFERENCE_IMAGE__",
        ipadapter_weight=ip_adapter_weight,
    )
    injected = inject_comfyui_workflow(
        workflow,
        checkpoint_name=checkpoint_name,
        lora_name=lora_name,
        style_preset=style_preset,
    )
    filled = replace_placeholders(injected, replacements)
    if not isinstance(filled, dict):
        raise ValueError("ComfyUI workflow template must resolve to a JSON object.")
    unresolved = unresolved_placeholders(filled)
    if unresolved:
        write_debug_json(debug_dir / f"scene_{scene.scene:02}_comfyui_unresolved.json", unresolved)
        raise ValueError(f"ComfyUI workflow has unresolved placeholders: {', '.join(unresolved[:5])}")

    write_debug_json(
        debug_dir / f"scene_{scene.scene:02}_comfyui_request_meta.json",
        {
            "scene": scene.scene,
            "title": scene.title,
            "base_url": comfyui_base_url(),
            "workflow_path": str(workflow_path),
            "prompt_id": prompt_id,
            "client_id": client_id,
            "reference_info": reference_info,
            "ip_adapter_weight": ip_adapter_weight,
            "checkpoint_name": checkpoint_name,
            "lora_name": lora_name,
            "style_preset": env_value("COMFYUI_STYLE_PRESET", default=""),
            "prompt_text": prompt_text,
        },
    )
    write_debug_json(debug_dir / f"scene_{scene.scene:02}_filled_workflow.json", filled)

    try:
        submit_response = submit_comfyui_prompt(filled, prompt_id, client_id)
        write_debug_json(debug_dir / f"scene_{scene.scene:02}_submit_response.json", submit_response)
        prompt_id = str(submit_response.get("prompt_id", prompt_id))
        history = poll_comfyui_history(prompt_id)
        write_debug_json(debug_dir / f"scene_{scene.scene:02}_history.json", history)
        status = history.get("status", {})
        status_str = str(status.get("status_str") or "").lower()
        completed = status.get("completed")
        if completed is False or status_str in {"error", "failed", "failure"}:
            raise RuntimeError(f"ComfyUI workflow failed: {json.dumps(status, ensure_ascii=False)}")
    except Exception as exc:
        if isinstance(scene.consistency_meta, dict):
            errors = scene.consistency_meta.setdefault("errors", [])
            if str(exc) not in errors:
                errors.append(str(exc))
        raise

    outputs = history.get("outputs", {})
    save_image_node_ids = [
        node_id
        for node_id, node in filled.items()
        if isinstance(node, dict) and node.get("class_type") == "SaveImage"
    ]
    ordered_node_ids = save_image_node_ids + [node_id for node_id in outputs.keys() if node_id not in save_image_node_ids]
    for node_id in ordered_node_ids:
        node_output = outputs.get(node_id, {})
        images = node_output.get("images") or []
        if images:
            out = run_dir / f"scene_{scene.scene:02}_keyframe.png"
            download_comfyui_image(images[0], out)
            write_debug_json(
                debug_dir / f"scene_{scene.scene:02}_downloaded_image.json",
                {"node_id": node_id, "image": images[0], "output_path": str(out)},
            )
            return out
    raise RuntimeError(f"ComfyUI workflow completed but returned no images. Debug: {debug_dir}")


def generate_keyframe(scene: StoryScene, run_dir: Path, provider: str) -> Path:
    provider = (provider or "auto").strip().lower()
    if provider == "local":
        return create_keyframe(scene, run_dir)
    if provider == "comfyui":
        return render_keyframe_comfyui(scene, run_dir)
    if provider == "cloud":
        return _generate_keyframe_cloud(scene, run_dir)
    # Auto mode: try ComfyUI -> cloud -> local
    try:
        return render_keyframe_comfyui(scene, run_dir)
    except Exception as exc:
        if isinstance(scene.consistency_meta, dict):
            errors = scene.consistency_meta.setdefault("errors", [])
            if str(exc) not in errors:
                errors.append(str(exc))
        if env_bool("COMFYUI_STRICT", "KEYFRAME_STRICT", default=False):
            raise
        print(f"[keyframe] ComfyUI unavailable, trying cloud provider: {exc}")
        # Try cloud text-to-image
        try:
            return _generate_keyframe_cloud(scene, run_dir)
        except Exception as cloud_exc:
            print(f"[keyframe] Cloud provider also failed: {cloud_exc}")
            if isinstance(scene.consistency_meta, dict):
                scene.consistency_meta.setdefault("fallback_used", "local_keyframe")
            print("[keyframe] Falling back to local renderer")
            return create_keyframe(scene, run_dir)


def _generate_keyframe_cloud(scene: StoryScene, run_dir: Path) -> Path:
    """Generate keyframe via cloud text-to-image API."""
    from backend.keyframe_providers import generate_keyframe_dashscope, build_keyframe_prompt

    # Build character info for prompt
    characters: list[dict] = []
    for ref in (scene.character_references or []) if hasattr(scene, "character_references") else []:
        if isinstance(ref, dict):
            characters.append(ref)

    # Build prompt
    positive, negative = build_keyframe_prompt(
        scene.visual,
        characters,
        style_suffix=scene.character_prompt_compilation or "",
    )

    scene_id = f"{scene.scene:02}"
    output_path = run_dir / f"scene_{scene_id}_keyframe.png"
    width = int(env_float("COMFYUI_WIDTH", default=832))
    height = int(env_float("COMFYUI_HEIGHT", default=1216))

    result = generate_keyframe_dashscope(
        prompt=positive,
        negative_prompt=negative,
        width=width,
        height=height,
        output_path=output_path,
    )
    if result and result.exists():
        return result
    raise RuntimeError("Cloud keyframe generation failed or returned no image")


def normalize_video_provider(provider: str | None = None) -> str:
    return resolve_video_provider_name(provider)


def comfyui_checkpoint_name() -> str:
    return env_value("COMFYUI_CHECKPOINT_NAME", "COMFYUI_VIDEO_CHECKPOINT_NAME", default="")


def comfyui_lora_name() -> str:
    return env_optional_value("COMFYUI_LORA_NAME", default=env_optional_value("COMFYUI_VIDEO_LORA_NAME", default=""))


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


def normalize_audio_manifest(manifest: object | None) -> dict[str, Any]:
    merged = deepcopy(DEFAULT_AUDIO_MANIFEST)
    if not isinstance(manifest, dict):
        return merged
    for key, value in manifest.items():
        if key == "sfx_trigger" and isinstance(value, dict):
            merged["sfx_trigger"].update(value)
        elif key == "sfx_triggers" and isinstance(value, list):
            merged["sfx_triggers"] = deepcopy(value)
        elif value is not None:
            merged[key] = deepcopy(value)
    if not isinstance(merged.get("sfx_trigger"), dict):
        merged["sfx_trigger"] = deepcopy(DEFAULT_AUDIO_MANIFEST["sfx_trigger"])
    return merged


class SceneValidationError(ValueError):
    def __init__(self, reason: str, raw: dict[str, Any], field: str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.raw = raw
        self.field = field

    def to_error_message(self) -> str:
        if self.field:
            return f"[{self.field}] {self.reason}"
        return self.reason


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
        raise SceneValidationError(f"分镜 #{index} 不是 JSON 对象，实际类型 {type(raw).__name__}", {}, field="scene")

    scene_number = _raw_scene_number(raw)
    if scene_number is None:
        raise SceneValidationError("缺失或非法的 scene/order 字段", raw, field="scene")

    visual = raw.get("visual") or raw.get("visual_prompt")
    if not isinstance(visual, str) or not visual.strip():
        raise SceneValidationError("visual 不能为空", raw, field="visual")

    duration_value = raw.get("duration") if raw.get("duration") not in (None, "") else raw.get("duration_seconds")
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
        raise SceneValidationError(f"camera_speed 不是数字: {camera_speed!r}", raw, field="camera_speed")
    if not 0.35 <= camera_speed_value <= 3.0:
        raise SceneValidationError(f"camera_speed 超出范围: {camera_speed_value}", raw, field="camera_speed")

    audio_manifest = raw.get("audio_manifest")
    if not isinstance(audio_manifest, dict):
        raise SceneValidationError("audio_manifest 必须是对象", raw, field="audio_manifest")
    sfx_trigger = audio_manifest.get("sfx_trigger")
    if not isinstance(sfx_trigger, dict):
        raise SceneValidationError("audio_manifest.sfx_trigger 必须是对象", raw, field="audio_manifest.sfx_trigger")


def make_failed_placeholder(raw: dict[str, Any], index: int, err: SceneValidationError) -> StoryScene:
    safe_raw = dict(raw or {})
    try:
        safe_duration = float(safe_raw.get("duration_seconds") or safe_raw.get("duration") or 3.0)
    except (TypeError, ValueError):
        safe_duration = 3.0
    safe_duration = min(6.0, max(3.0, safe_duration))
    safe_raw["duration"] = safe_duration
    safe_raw["duration_seconds"] = safe_duration
    safe_raw["visual"] = str(safe_raw.get("visual") or safe_raw.get("visual_prompt") or "占位分镜").strip()
    safe_raw["visual_prompt"] = str(safe_raw.get("visual_prompt") or safe_raw.get("visual") or safe_raw["visual"]).strip()
    safe_raw["dialogue"] = str(safe_raw.get("dialogue") or "")
    safe_raw["camera"] = str(safe_raw.get("camera") or safe_raw.get("camera_movement") or "slow_push_in").strip() or "slow_push_in"
    safe_raw["emotion"] = str(safe_raw.get("emotion") or "calm").strip() or "calm"
    safe_raw["characters"] = safe_raw.get("characters") if isinstance(safe_raw.get("characters"), list) else []
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
    load_env_file()
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "").strip().rstrip("/")
    resolved_model = (model or os.environ.get("LLM_MODEL", "").strip()).strip()
    if not api_key or not base_url or not resolved_model:
        raise RuntimeError("Missing LLM_API_KEY, LLM_BASE_URL, or LLM_MODEL. Configure .env or use rule mode.")

    payload = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }
    body = post_llm_chat_completion(base_url, api_key, payload)
    response_json = json.loads(body)
    return response_json["choices"][0]["message"]["content"]


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
    if has("震惊", "愤怒", "对峙", "反转", "揭露", "爆发", "冲突", "撞", "打", "雷", "刀", "dramatic"):
        camera_movement = "dramatic_push"
    elif has("悲", "哭", "回忆", "沉默", "雨", "压抑", "独白", "melancholy") or camera == "melancholy_pan":
        camera_movement = "melancholy_pan"
    elif has("场景", "开端", "登场", "全景", "环境", "宗门", "宫殿", "山门", "高楼", "establish") or camera == "establishing_tilt":
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


def _apply_director_classification_to_scenes(scenes: list[StoryScene], model: str | None = None) -> None:
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
        (index, scene) for index, scene in enumerate(scenes) if not getattr(scene, "validation_failed", False)
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
                    apply_rules_classification(scene, _apply_director_rule_recommendation, reason=str(exc))
                except Exception as rule_exc:
                    apply_default_classification(scene, reason=str(rule_exc))
        except Exception as exc:
            print(f"[director] Unexpected director classification error, falling back to rules: {exc}")
            for _, scene in batch:
                try:
                    apply_rules_classification(scene, _apply_director_rule_recommendation, reason=f"unexpected: {exc}")
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
    speaker = str(raw.get("speaker") or dialogue_speaker or (characters[0] if len(characters) == 1 else ""))
    voice_profile = str(raw.get("voice_profile") or infer_voice_profile(speaker, characters))

    return StoryScene(
        scene=index,
        duration=duration,
        title=str(raw.get("title") or f"第{index}幕")[:24],
        visual=str(raw.get("visual") or raw.get("visual_prompt") or "竖屏动漫番剧分镜，角色在强情绪场景中对峙，光影对比鲜明。"),
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
        character_references=raw.get("character_references") if isinstance(raw.get("character_references"), list) else [],
        primary_reference_image_path=str(raw.get("primary_reference_image_path") or ""),
        primary_reference_image_abs_path=str(raw.get("primary_reference_image_abs_path") or ""),
    )


def call_llm_storyboard(story: str, scene_count: int) -> list[StoryScene]:
    load_env_file()
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "").strip().rstrip("/")
    model = os.environ.get("LLM_MODEL", "").strip()

    if not api_key or not base_url or not model:
        raise RuntimeError("Missing LLM_API_KEY, LLM_BASE_URL, or LLM_MODEL. Configure .env or use --planner rule.")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": DIRECTOR_SYSTEM_PROMPT,
            },
            {"role": "user", "content": storyboard_prompt(story, scene_count)},
        ],
        "temperature": 0.7,
    }
    body = post_llm_chat_completion(base_url, api_key, payload)
    response_json = json.loads(body)
    content = response_json["choices"][0]["message"]["content"]
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


SCRIPT_HEADING_RE = re.compile(
    r"^\s*(?:第\s*)?(?P<index>\d{1,3})\s*(?:场|幕|节|scene)\s*[:：.\-、]?\s*(?P<title>.*)$",
    re.IGNORECASE,
)
SCRIPT_SCENE_MARKERS = ("场景", "镜头", "Scene", "scene", "第", "#")
SCRIPT_CAMERA_RULES = [
    (("慢推", "推进", "推近", "拉近", "zoom in", "push in", "dolly in"), "slow_push_in"),
    (("慢拉", "拉远", "拉开", "zoom out", "pull out", "dolly out"), "slow_zoom_out"),
    (("左移", "向左", "pan left", "左摇"), "pan_left"),
    (("右移", "向右", "pan right", "右摇"), "pan_right"),
    (("俯拍", "俯视", "tilt down", "下压"), "tilt_down"),
    (("仰拍", "仰视", "tilt up", "上仰"), "tilt_up"),
    (("特写", "近景", "close-up", "close up", "reveal"), "dramatic_reveal"),
]
SCRIPT_EMOTION_RULES = [
    (("开心", "高兴", "兴奋", "惊喜", "笑", "雀跃"), "happy"),
    (("愤怒", "生气", "怒", "火大", "暴怒", "愤慨"), "angry"),
    (("难过", "悲伤", "哭", "落泪", "委屈", "心酸"), "sad"),
    (("震惊", "错愕", "愣住", "吃惊", "惊讶"), "shocked"),
    (("紧张", "压迫", "焦灼", "忐忑", "慌张"), "tense"),
    (("平静", "冷静", "镇定", "沉稳"), "calm"),
]


def _is_script_cue_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return stripped.startswith(("(", "（", "[", "【", "「", "“", "*")) and stripped.endswith(
        (")", "）", "]", "】", "」", "”", "*")
    )


def _normalize_script_lines(script: str) -> list[str]:
    lines: list[str] = []
    for raw_line in script.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            lines.append("")
            continue
        if _looks_like_scene_heading(stripped) or _split_script_dialogue(stripped)[0] or _is_script_cue_line(stripped):
            lines.append(stripped)
            continue
        chunks = [chunk.strip() for chunk in re.split(r"(?<=[。！？!?；;])\s*", stripped) if chunk.strip()]
        if len(chunks) > 1 and len(stripped) > 80:
            lines.extend(chunks)
        else:
            lines.append(stripped)
    return lines


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
        current_dialogue_count = sum(1 for item in current if _split_script_dialogue(item)[0])
        should_start_new = False
        if current and is_heading:
            should_start_new = True
        elif current and not is_dialogue and not is_cue and current_dialogue_count >= 2:
            should_start_new = True
        elif current and _script_block_char_count(current) >= 360:
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
    return bool(re.match(r"^(?:分镜|镜头|shot)\s*[0-9一二三四五六七八九十百两]{1,6}\b", stripped, re.IGNORECASE))


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


def _split_script_dialogue(line: str) -> tuple[str, str]:
    match = re.match(r"^\s*([^：:\n]{1,24})\s*[:：]\s*(.+)$", line.strip(), re.S)
    if not match:
        return "", line.strip()
    speaker = match.group(1).strip()
    spoken = match.group(2).strip()
    return speaker, spoken


def _looks_like_scene_heading(line: str) -> tuple[str, str] | None:
    raw = line.strip().lstrip("【[")
    raw = raw.rstrip("】]")
    if _is_script_cue_line(raw):
        return None
    match = SCRIPT_HEADING_RE.match(raw)
    if match:
        return str(match.group("index")), str(match.group("title") or "").strip()
    if raw.startswith("#"):
        title = raw.lstrip("#").strip()
        return "", title
    if any(marker in raw[:8] for marker in SCRIPT_SCENE_MARKERS) and len(raw) <= 40:
        return "", raw
    return None


def _split_script_dialogue(line: str) -> tuple[str, str]:
    match = re.match(r"^\s*([^\n:：]{1,24})\s*[:：]\s*(.+)$", line.strip(), re.S)
    if not match:
        return "", line.strip()
    speaker = match.group(1).strip()
    spoken = match.group(2).strip()
    if not speaker or any(mark in speaker for mark in "，。！？!?；;、（）()[]【】"):
        return "", line.strip()
    return speaker, spoken


def _strip_brackets(text: str) -> str:
    return re.sub(r"^[\s\[\(（【]+|[\]\)）】\s]+$", "", text.strip())


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


def _derive_script_scene_title(index: int, heading: str, visual_lines: list[str], dialogue_lines: list[str]) -> str:
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
            if line_speaker not in characters and line_speaker not in {"旁白", "解说", "播音", "字幕"}:
                characters.append(line_speaker)
            dialogue_lines.append(f"{line_speaker}：{spoken}")
            emotion_hint = emotion_hint or _infer_script_emotion(spoken)
            continue

        if stripped not in {"", "——", "…"}:
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
        "；".join(item for item in [heading, *visual_lines] if item),
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
    load_env_file()
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "").strip().rstrip("/")
    model = os.environ.get("LLM_MODEL", "").strip()

    if not api_key or not base_url or not model:
        raise RuntimeError("Missing LLM_API_KEY, LLM_BASE_URL, or LLM_MODEL. Configure .env or use rule mode.")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": DIRECTOR_SYSTEM_PROMPT,
            },
            {"role": "user", "content": script_storyboard_prompt(script, max_scenes, script_hint=script_hint)},
        ],
        "temperature": 0.3,
    }
    body = post_llm_chat_completion(base_url, api_key, payload)
    response_json = json.loads(body)
    content = response_json["choices"][0]["message"]["content"]
    parsed = extract_json_object(content)
    raw_scenes = parsed.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("LLM JSON must contain a non-empty scenes array.")
    return [coerce_scene(raw, idx) for idx, raw in enumerate(raw_scenes[:max_scenes], start=1)]


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
        print(f"[planner] LLM unavailable for script recognition, falling back to rule planner: {exc}")
        scenes = build_rule_script_storyboard(script, max_scenes=max_scenes)
        _apply_director_classification_to_scenes(scenes)
        return scenes, "rule"


SCRIPT_ROLE_IGNORE = {
    "旁白",
    "解说",
    "播音",
    "字幕",
    "画外音",
    "AI漫剧剧本",
    "剧本",
    "标题",
    "类型",
    "作者",
    "编剧",
    "提示",
    "提示词",
    "画面",
    "氛围",
    "场景",
    "镜头",
    "音效",
    "说明",
    "备注",
    "简介",
    "梗概",
    "对白",
}


def _collect_script_role_counts(script: str) -> dict[str, dict[str, object]]:
    counts: dict[str, dict[str, object]] = {}
    paragraphs = _split_script_paragraphs(script)
    for scene_index, block in enumerate(paragraphs, start=1):
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
    if not paragraphs:
        return {
            "mode": "rule",
            "source_length": len(script),
            "roles": [],
            "events": [],
            "event_count": 0,
        }

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
        key=lambda item: (-int(item.get("mentions", 0)), int(item.get("first_scene", 0)), str(item.get("name", ""))),
    )
    for role in roles:
        name = str(role.get("name") or "")
        role["voice_profile"] = infer_voice_profile(name, [name])
        role["emotion"] = _infer_script_emotion(name)
        role["suggested_voice_engine"] = "edge"
        role["summary"] = f"{role['mentions']} 次提及"

    return {
        "mode": "rule",
        "source_length": len(script),
        "roles": roles,
        "events": events,
        "event_count": len(events),
        "role_count": len(roles),
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
    scenes, planner_used = build_script_storyboard(script, planner, max_scenes=max_scenes, script_hint=script_hint)
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


def srt_timestamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def format_subtitle_text(speaker: str, text: str, subtitle_style: dict | None = None) -> str:
    style = normalize_subtitle_style(subtitle_style)
    speaker = speaker.strip()
    text = text.strip()
    if not text:
        return ""
    if speaker and style.get("show_speaker", True):
        return f"{speaker}：{text}"
    return text


def write_srt_entries(entries: list[tuple[float, float, str]], path: Path) -> None:
    chunks: list[str] = []
    index = 1
    for start, end, text in entries:
        if not text.strip():
            continue
        chunks.append(
            f"{index}\n"
            f"{srt_timestamp(start)} --> {srt_timestamp(end)}\n"
            f"{text.strip()}\n"
        )
        index += 1
    write_text(path, "\n".join(chunks))


def write_srt(scenes: list[StoryScene], path: Path) -> None:
    cursor = 0.0
    entries: list[tuple[float, float, str]] = []
    for scene in scenes:
        start = cursor
        end = cursor + scene.duration
        entries.append((start, end, scene.dialogue))
        cursor = end
    write_srt_entries(entries, path)


def write_srt_from_durations(scenes: list[StoryScene], durations: list[float], path: Path) -> None:
    cursor = 0.0
    entries: list[tuple[float, float, str]] = []
    for scene, duration in zip(scenes, durations):
        start = cursor
        end = cursor + duration
        entries.append((start, end, scene.dialogue))
        cursor = end
    write_srt_entries(entries, path)


def parse_srt_timestamp(value: str) -> float:
    match = re.match(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})$", value.strip())
    if not match:
        return 0.0
    hours, minutes, seconds, millis = map(int, match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def parse_srt_entries(path: Path) -> list[tuple[float, float, str]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    entries: list[tuple[float, float, str]] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip("\r") for line in block.splitlines() if line.strip("\r")]
        if len(lines) < 2:
            continue
        time_line = lines[1] if "-->" in lines[1] else lines[0]
        body_lines = lines[2:] if "-->" in lines[1] else lines[1:]
        match = re.match(r"(.+?)\s*-->\s*(.+)", time_line)
        if not match:
            continue
        start = parse_srt_timestamp(match.group(1))
        end = parse_srt_timestamp(match.group(2))
        text_body = "\n".join(body_lines).strip()
        if text_body:
            entries.append((start, end, text_body))
    return entries


def offset_srt_entries(entries: list[tuple[float, float, str]], offset: float) -> list[tuple[float, float, str]]:
    return [(start + offset, end + offset, text) for start, end, text in entries]


def _scene_field(scene: StoryScene | dict | None, field: str, default: object = "") -> object:
    if scene is None:
        return default
    if isinstance(scene, dict):
        return scene.get(field, default)
    return getattr(scene, field, default)


def _scene_subtitle_emotion(scene: StoryScene | dict | None) -> str:
    tone = str(_scene_field(scene, "emotion_tone", "") or "").strip()
    if tone:
        return tone
    meta = _scene_field(scene, "director_meta", None)
    if isinstance(meta, dict):
        return str(meta.get("emotion_tone") or "").strip()
    return ""


def _scene_dialogue_segments(scene: StoryScene | dict | None) -> list[tuple[str, str]]:
    dialogue = str(_scene_field(scene, "dialogue", "") or "")
    segments = split_dialogue_lines(dialogue)
    if segments:
        return segments
    speaker = str(_scene_field(scene, "speaker", "") or "").strip()
    return [(speaker, dialogue.strip())] if dialogue.strip() else []


def stitch_scene_subtitles(
    scene_files: list[Path],
    durations: list[float],
    path: Path,
    fallback_scenes: list[StoryScene] | None = None,
    ass_path: Path | None = None,
    subtitle_style: dict | None = None,
) -> None:
    cursor = 0.0
    entries: list[tuple[float, float, str]] = []
    ass_entries: list[tuple[float, float, str, str, str]] = []
    for index, scene_file in enumerate(scene_files):
        scene = fallback_scenes[index] if fallback_scenes is not None and index < len(fallback_scenes) else None
        local_entries = parse_srt_entries(scene_file)
        if not local_entries and scene is not None:
            local_entries = [(0.0, durations[index], str(_scene_field(scene, "dialogue", "") or "").strip())]
        offset_entries = offset_srt_entries(local_entries, cursor)
        entries.extend(offset_entries)
        scene_segments = _scene_dialogue_segments(scene)
        emotion_tone = _scene_subtitle_emotion(scene)
        scene_speaker = str(_scene_field(scene, "speaker", "") or "").strip()
        for local_index, (start, end, text) in enumerate(offset_entries):
            speaker = scene_speaker
            if local_index < len(scene_segments) and scene_segments[local_index][0]:
                speaker = scene_segments[local_index][0]
            ass_entries.append((start, end, text, speaker, emotion_tone))
        cursor += durations[index] if index < len(durations) else 0.0
    write_srt_entries(entries, path)
    if ass_path is not None:
        write_ass_entries(ass_entries if ass_entries else entries, ass_path, subtitle_style)


def windows_fontfile() -> str | None:
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/simsun.ttc"),
    ]
    for item in candidates:
        if item.exists():
            return str(item).replace("\\", "/").replace(":", "\\:")
    return None


def drawtext(textfile: str, y: int, size: int, color: str = "white", box: bool = True) -> str:
    font = windows_fontfile()
    options = [
        f"textfile='{textfile}'",
        f"fontcolor={color}",
        f"fontsize={size}",
        "line_spacing=12",
        "x=(w-text_w)/2",
        f"y={y}",
    ]
    if font:
        options.insert(1, f"fontfile='{font}'")
    if box:
        options.extend(["box=1", "boxcolor=black@0.42", "boxborderw=24"])
    return "drawtext=" + ":".join(options)


def camera_zoompan_filter(
    camera: str,
    duration: float,
    zoom_limit: float,
    speed: float = 1.0,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    hold_in_ratio: float = 0.12,
    hold_out_ratio: float = 0.12,
) -> str:
    camera = (camera or "slow_push_in").strip().lower()
    frames = max(1, int(max(0.25, duration) * 30))
    speed = clamp(float(speed or 1.0), 0.35, 3.0)
    hold_in_ratio = clamp(float(hold_in_ratio or 0.0), 0.0, 0.45)
    hold_out_ratio = clamp(float(hold_out_ratio or 0.0), 0.0, 0.45)
    hold_in_frames = max(0, int(frames * hold_in_ratio))
    hold_out_frames = max(0, int(frames * hold_out_ratio))
    if hold_in_frames + hold_out_frames >= frames:
        overflow = hold_in_frames + hold_out_frames - (frames - 1)
        if overflow > 0:
            reduce_out = min(overflow, hold_out_frames)
            hold_out_frames -= reduce_out
            overflow -= reduce_out
            if overflow > 0:
                hold_in_frames = max(0, hold_in_frames - overflow)
    hold_out_start = max(hold_in_frames + 1, frames - hold_out_frames)
    motion_frames = max(1, hold_out_start - hold_in_frames)
    motion_progress = f"min(1,max(0,(on-{hold_in_frames})/{max(1, motion_frames - 1)}))"
    progress = f"if(lt(on,{hold_in_frames}),0,if(gte(on,{hold_out_start}),1,{motion_progress}))"
    ease_in = f"({progress})*({progress})"
    ease_out = f"1-(1-({progress}))*(1-({progress}))"
    zoom_limit = max(1.02, float(zoom_limit))
    focus_x = clamp(float(focus_x), 0.0, 1.0)
    focus_y = clamp(float(focus_y), 0.0, 1.0)
    focus_x_expr = f"iw*{focus_x:.3f}"
    focus_y_expr = f"ih*{focus_y:.3f}"

    zoom_in = f"min({zoom_limit:.3f},1+({zoom_limit:.3f}-1)*({ease_out}))"
    zoom_out = f"max(1.000,{zoom_limit:.3f}-({zoom_limit:.3f}-1)*({ease_out}))"
    center_x = "iw/2-(iw/zoom/2)"
    center_y = "ih/2-(ih/zoom/2)"
    max_x = "(iw-iw/zoom)"
    max_y = "(ih-ih/zoom)"

    if camera == "dramatic_push":
        target_zoom = min(max(zoom_limit + 0.05, 1.30), 1.46)
        return (
            f"zoompan=z='min({target_zoom:.3f},1+({target_zoom:.3f}-1)*({ease_out}))'"
            f":x='min(max({focus_x_expr}-(iw/zoom/2),0),(iw-iw/zoom))'"
            f":y='min(max({focus_y_expr}-(ih/zoom/2),0),(ih-ih/zoom))'"
            ":d=1:s=1080x1920:fps=30"
        )
    if camera == "melancholy_pan":
        return (
            "zoompan=z='1.180'"
            f":x='min(max((iw-(iw/zoom))*({progress}),0),(iw-iw/zoom))'"
            f":y='min(max({focus_y_expr}-(ih/zoom/2),0),(ih-ih/zoom))'"
            ":d=1:s=1080x1920:fps=30"
        )
    if camera == "establishing_tilt":
        return (
            "zoompan=z='1.200'"
            f":x='min(max({focus_x_expr}-(iw/zoom/2),0),(iw-iw/zoom))'"
            f":y='min(max({max_y}*(1-({progress})),0),(ih-ih/zoom))'"
            ":d=1:s=1080x1920:fps=30"
        )
    if camera == "slow_zoom_out":
        return (
            f"zoompan=z='{zoom_out}'"
            f":x='min(max({focus_x_expr}-(iw/zoom/2),0),(iw-iw/zoom))'"
            f":y='min(max({focus_y_expr}-(ih/zoom/2),0),(ih-ih/zoom))'"
            ":d=1:s=1080x1920:fps=30"
        )
    if camera == "pan_left":
        return f"zoompan=z='min({zoom_limit:.3f},1.100+0.00012*on)':x='min(max({max_x}*(1-{progress}),0),(iw-iw/zoom))':y='min(max({focus_y_expr}-(ih/zoom/2),0),(ih-ih/zoom))':d=1:s=1080x1920:fps=30"
    if camera == "pan_right":
        return f"zoompan=z='min({zoom_limit:.3f},1.100+0.00012*on)':x='min(max({max_x}*{progress},0),(iw-iw/zoom))':y='min(max({focus_y_expr}-(ih/zoom/2),0),(ih-ih/zoom))':d=1:s=1080x1920:fps=30"
    if camera == "tilt_down":
        return f"zoompan=z='min({zoom_limit:.3f},1.080+0.00010*on)':x='min(max({focus_x_expr}-(iw/zoom/2),0),(iw-iw/zoom))':y='min(max({max_y}*{progress},0),(ih-ih/zoom))':d=1:s=1080x1920:fps=30"
    if camera == "tilt_up":
        return f"zoompan=z='min({zoom_limit:.3f},1.080+0.00010*on)':x='min(max({focus_x_expr}-(iw/zoom/2),0),(iw-iw/zoom))':y='min(max({max_y}*(1-{progress}),0),(ih-ih/zoom))':d=1:s=1080x1920:fps=30"
    if camera == "dramatic_reveal":
        return (
            f"zoompan=z='min({zoom_limit + 0.030:.3f},1+0.00075*on)'"
            f":x='min(max({focus_x_expr}-(iw/zoom/2)+8*sin(on*0.65),0),(iw-iw/zoom))'"
            f":y='min(max({focus_y_expr}-(ih/zoom/2)+6*sin(on*0.93),0),(ih-ih/zoom))'"
            ":d=1:s=1080x1920:fps=30"
        )
    if camera == "pull_back":
        return (
            f"zoompan=z='max(1.0,{zoom_limit:.3f}-(0.20*({progress})))'"
            f":x='min(max({focus_x_expr}-(iw/zoom/2),0),(iw-iw/zoom))'"
            f":y='min(max({focus_y_expr}-(ih/zoom/2),0),(ih-ih/zoom))'"
            ":d=1:s=1080x1920:fps=30"
        )
    if camera == "slow_push":
        target_zoom = max(zoom_limit, 1.17)
        return (
            f"zoompan=z='min({target_zoom:.3f},1+({target_zoom:.3f}-1)*({ease_out}))'"
            f":x='min(max({focus_x_expr}-(iw/zoom/2),0),(iw-iw/zoom))'"
            f":y='min(max({focus_y_expr}-(ih/zoom/2),0),(ih-ih/zoom))'"
            ":d=1:s=1080x1920:fps=30"
        )
    return (
        f"zoompan=z='{zoom_in}'"
        f":x='min(max({focus_x_expr}-(iw/zoom/2),0),(iw-iw/zoom))'"
        f":y='min(max({focus_y_expr}-(ih/zoom/2),0),(ih-ih/zoom))'"
        ":d=1:s=1080x1920:fps=30"
    )


def render_silent_visual_segment(
    ffmpeg: str,
    image_path: Path,
    duration: float,
    out_path: Path,
    zoom_limit: float,
    camera: str = "slow_push_in",
    beat_index: int = 1,
    camera_speed: float = 1.0,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    hold_in_ratio: float = 0.12,
    hold_out_ratio: float = 0.12,
    screen_shake: bool = False,
) -> Path:
    duration = max(0.25, float(duration))
    fade_out_start = max(0.0, duration - 0.18)
    reveal_filter = "eq=contrast=1.08:saturation=1.05"
    if beat_index >= 3 or camera == "dramatic_reveal":
        reveal_filter = "eq=contrast=1.16:saturation=1.12"
    filter_parts = [
        "scale=1080:1920",
        camera_zoompan_filter(
            camera,
            duration,
            zoom_limit,
            speed=camera_speed,
            focus_x=focus_x,
            focus_y=focus_y,
            hold_in_ratio=hold_in_ratio,
            hold_out_ratio=hold_out_ratio,
        ),
    ]
    if screen_shake:
        filter_parts.append("crop=1060:1884:x='10+10*sin(n*1.9)':y='18+14*sin(n*2.7)',scale=1080:1920")
    filter_parts.extend(
        [
            reveal_filter,
            f"fade=t=in:st=0:d=0.10,fade=t=out:st={fade_out_start:.3f}:d=0.18",
            "format=yuv420p",
        ]
    )
    video_filter = ",".join(filter_parts)
    cmd = [
        ffmpeg,
        "-y",
        "-loop",
        "1",
        "-i",
        str(image_path),
        "-vf",
        video_filter,
        "-t",
        f"{duration:.3f}",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        str(out_path),
    ]
    run_guarded(
        cmd,
        cwd=out_path.parent,
        timeout=render_timeout(duration),
        stage="ffmpeg_render_segment",
    )
    return out_path


def concat_video_segments(
    ffmpeg: str,
    clips: list[Path],
    out_path: Path,
    run_dir: Path,
    durations: list[float] | None = None,
    transition_duration: float = 0.24,
) -> Path:
    def _concat_copy(stage: str = "ffmpeg_concat_video") -> Path:
        concat_file = run_dir / f"{out_path.stem}_concat.txt"
        lines = [f"file '{clip.name}'" for clip in clips]
        write_text(concat_file, "\n".join(lines))
        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(out_path),
        ]
        run_guarded(cmd, cwd=run_dir, timeout=concat_timeout(len(clips)), stage=stage)
        return out_path

    if len(clips) <= 1 or not durations or len(durations) != len(clips) or not env_bool("COMICDRAMA_ENABLE_XFADE", default=False):
        return _concat_copy()

    xfades = ["fade", "smoothleft", "wipeleft", "fadeblack"]
    filter_parts: list[str] = []
    for index, clip in enumerate(clips):
        filter_parts.append(f"[{index}:v]settb=AVTB,fps=30,setpts=PTS-STARTPTS,format=yuv420p[v{index}]")
    current = "v0"
    current_duration = float(durations[0])
    for index in range(1, len(clips)):
        next_label = f"v{index}"
        transition = xfades[(index - 1) % len(xfades)]
        available = max(0.05, current_duration + float(durations[index]) - transition_duration)
        offset = max(0.0, available - transition_duration)
        out_label = f"x{index}"
        filter_parts.append(
            f"[{current}][{next_label}]xfade=transition={transition}:duration={transition_duration:.3f}:offset={offset:.3f}[{out_label}]"
        )
        current = out_label
        current_duration = available
    cmd = [ffmpeg, "-y"]
    for clip in clips:
        cmd.extend(["-i", str(clip)])
    cmd.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            f"[{current}]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(out_path),
        ]
    )
    try:
        run_guarded(cmd, cwd=run_dir, timeout=concat_timeout(len(clips)) + 120, stage="ffmpeg_concat_video_xfade")
    except Exception as exc:
        print(f"[video] xfade failed for {out_path.name}: {exc}; falling back to concat")
        return _concat_copy(stage="ffmpeg_concat_video_fallback")
    return out_path


def mux_audio_to_visual(ffmpeg: str, visual_path: Path, voice_path: Path, out_path: Path) -> Path:
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(visual_path),
        "-i",
        str(voice_path),
        "-shortest",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(out_path),
    ]
    run_guarded(cmd, cwd=out_path.parent, timeout=DEFAULT_SUBPROCESS_TIMEOUTS["ffmpeg_audio"], stage="ffmpeg_mux_audio")
    return out_path


def write_tone_sfx(path: Path, kind: str, duration: float = 0.32, sample_rate: int = 44100) -> Path:
    ensure_parent(path)
    kind = (kind or "whoosh").strip().lower()
    duration = max(0.08, min(0.8, float(duration)))
    frame_count = int(sample_rate * duration)
    rng = random.Random(f"{path.name}:{kind}")
    frames = bytearray()
    for frame in range(frame_count):
        t = frame / sample_rate
        p = frame / max(1, frame_count - 1)
        if kind in {"hit", "slap"}:
            freq = 120 + 70 * (1 - p)
            envelope = math.exp(-9.0 * p)
            sample = math.sin(2 * math.pi * freq * t) * envelope
            sample += (rng.random() * 2 - 1) * 0.16 * math.exp(-15.0 * p)
        elif kind == "boom":
            freq = 72 + 50 * (1 - p)
            envelope = math.exp(-5.5 * p)
            sample = math.sin(2 * math.pi * freq * t) * envelope
            sample += (rng.random() * 2 - 1) * 0.11 * math.exp(-10.0 * p)
        elif kind == "thunder":
            rumble = math.sin(2 * math.pi * (52 + 18 * math.sin(9 * t)) * t)
            crack = (rng.random() * 2 - 1) * math.exp(-18.0 * p)
            envelope = math.exp(-2.8 * p)
            sample = rumble * envelope * 0.45 + crack * 0.2
        elif kind == "drop":
            ping = math.sin(2 * math.pi * 1250 * t) * math.exp(-20.0 * p)
            thud = math.sin(2 * math.pi * 180 * t) * math.exp(-14.0 * p)
            sample = ping * 0.28 + thud * 0.22
        elif kind == "spark":
            freq = 900 + 800 * p
            envelope = math.sin(math.pi * p) * 0.32
            sample = math.sin(2 * math.pi * freq * t) * envelope
        else:
            freq = 260 + 620 * p
            envelope = math.sin(math.pi * p) * 0.28
            sample = math.sin(2 * math.pi * freq * t) * envelope
            sample += (rng.random() * 2 - 1) * 0.035 * envelope
        value = int(clamp(sample, -1.0, 1.0) * 32767)
        frames.extend(value.to_bytes(2, "little", signed=True))
        frames.extend(value.to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(frames))
    return path


def sfx_kind_for_scene(scene: StoryScene) -> str:
    explicit = normalize_sfx_kind(scene.sfx_type or "auto")
    if explicit in {"none", "off", "silent"}:
        return "none"
    if explicit in {"whoosh", "hit", "spark", "boom", "thunder", "drop"}:
        return explicit
    text = f"{scene.camera} {scene.emotion}".lower()
    if "dramatic" in text or "reveal" in text or "shocked" in text or "angry" in text:
        return "hit"
    if "happy" in text or "calm" in text:
        return "spark"
    return "whoosh"


def _beat_sfx_triggers(
    scene: StoryScene,
    beat_specs: list[dict[str, object]],
    duration: float,
    run_dir: Path,
) -> list[dict[str, object]]:
    if not beat_specs:
        return []

    emotion_tone = str(getattr(scene, "emotion_tone", "") or scene.emotion or "").strip().lower()
    intense_scene = emotion_tone in {"anger", "fear", "tension", "surprise"}
    triggers: list[dict[str, object]] = []
    boundary_cursor = 0.0
    boundary_floor = 0.35
    boundary_ceiling = max(0.4, float(duration) - 0.18)
    min_gap_ms = 800

    for index, beat in enumerate(beat_specs[:-1], start=1):
        boundary_cursor += float(beat.get("duration") or 0.0)
        if boundary_cursor <= boundary_floor or boundary_cursor >= boundary_ceiling:
            continue

        beat_label = str(beat.get("beat_type") or beat.get("label") or "").strip().upper()
        if beat_label == "REVERSAL":
            kind = "hit"
            gain_db = -18.0
            sfx_duration = 0.30
            offset_ms = -30
        elif beat_label == "FINALE":
            kind = "whoosh"
            gain_db = -20.0
            sfx_duration = 0.30
            offset_ms = -50
        elif beat_label == "OPENING":
            kind = "whoosh"
            gain_db = -24.0
            sfx_duration = 0.22
            offset_ms = -40
        else:
            kind = "hit" if intense_scene else "whoosh"
            gain_db = -20.0 if kind == "hit" else -24.0
            sfx_duration = 0.28 if kind == "hit" else 0.24
            offset_ms = -30

        if intense_scene and beat_label != "REVERSAL":
            gain_db -= 3.0

        delay_ms = max(0, int(boundary_cursor * 1000) + offset_ms)
        if triggers:
            prev_delay = int(triggers[-1].get("delay_ms") or 0)
            prev_gain = float(triggers[-1].get("gain_db") or -120.0)
            if delay_ms - prev_delay < min_gap_ms:
                if gain_db <= prev_gain:
                    continue
                triggers.pop()

        sfx_path = write_tone_sfx(
            run_dir / f"scene_{scene.scene:02}_sfx_beatcut_{index}.wav",
            kind,
            sfx_duration,
        )
        triggers.append(
            {
                "path": sfx_path,
                "delay_ms": delay_ms,
                "volume": db_to_linear(gain_db),
                "gain_db": gain_db,
            }
        )

    return triggers


def scene_sfx_triggers(scene: StoryScene, run_dir: Path, duration: float, project_root: Path | None = None) -> list[dict[str, object]]:
    manifest = audio_manifest_dict(scene)
    raw_triggers: list[object] = []
    if isinstance(manifest.get("sfx_triggers"), list):
        raw_triggers.extend(manifest["sfx_triggers"])
    if isinstance(manifest.get("sfx_trigger"), dict):
        raw_triggers.append(manifest["sfx_trigger"])

    triggers: list[dict[str, object]] = []
    for item in raw_triggers:
        if not isinstance(item, dict):
            continue
        file_value = item.get("file") or item.get("path") or item.get("style") or item.get("name")
        sfx_path = resolve_audio_asset("sfx", file_value, project_root=project_root)
        generated_kind = normalize_sfx_kind(file_value)
        if sfx_path is None and generated_kind in {"whoosh", "hit", "spark", "boom", "thunder", "drop"}:
            sfx_path = write_tone_sfx(
                run_dir / f"scene_{scene.scene:02}_sfx_{generated_kind}_{len(triggers) + 1}.wav",
                generated_kind,
                0.42 if generated_kind in {"boom", "thunder"} else 0.28,
            )
        if sfx_path is None:
            continue
        timestamp_ms = _coerce_int(item.get("timestamp_ms"), 0, 0, int(max(0.0, duration) * 1000))
        volume = _coerce_float(item.get("volume"), 0.65, 0.0, 2.0)
        triggers.append({"path": sfx_path, "delay_ms": timestamp_ms, "volume": volume, "source": "manifest"})

    spoken_text = split_dialogue_speaker(scene.dialogue)[1]
    beat_specs = build_scene_beats(scene, duration, spoken_text)
    for trigger in _beat_sfx_triggers(scene, beat_specs, duration, run_dir):
        trigger["source"] = "auto_beat"
        triggers.append(trigger)

    beat_kind = sfx_kind_for_scene(scene)
    if beat_kind != "none":
        start_sfx = write_tone_sfx(run_dir / f"scene_{scene.scene:02}_sfx_start.wav", "whoosh", 0.26)
        beat_sfx = write_tone_sfx(run_dir / f"scene_{scene.scene:02}_sfx_beat.wav", beat_kind, 0.34)
        beat_delay_ms = int(max(400, min(float(duration) * 1000 - 360, float(duration) * 1000 * 0.66)))
        triggers.append({"path": start_sfx, "delay_ms": 0, "volume": 0.22, "source": "auto_scene"})
        triggers.append({"path": beat_sfx, "delay_ms": beat_delay_ms, "volume": 0.18, "source": "auto_scene"})

    ranked_sources = {"manifest": 0, "auto_beat": 1, "auto_scene": 2}
    triggers.sort(
        key=lambda item: (
            int(item.get("delay_ms") or 0),
            ranked_sources.get(str(item.get("source") or ""), 99),
            -float(item.get("volume") or 0.0),
        )
    )

    deduped: list[dict[str, object]] = []
    for trigger in triggers:
        if not deduped:
            deduped.append(trigger)
            continue
        current_delay = int(trigger.get("delay_ms") or 0)
        prev_delay = int(deduped[-1].get("delay_ms") or 0)
        if current_delay - prev_delay < 100:
            current_rank = ranked_sources.get(str(trigger.get("source") or ""), 99)
            prev_rank = ranked_sources.get(str(deduped[-1].get("source") or ""), 99)
            current_volume = float(trigger.get("volume") or 0.0)
            prev_volume = float(deduped[-1].get("volume") or 0.0)
            if current_rank < prev_rank or (current_rank == prev_rank and current_volume > prev_volume):
                deduped[-1] = trigger
            continue
        deduped.append(trigger)

    return deduped[:12]


def scene_should_screen_shake(scene: StoryScene) -> bool:
    tokens = f"{scene.sfx_type} {scene.camera} {scene.emotion}".lower()
    manifest = audio_manifest_dict(scene)
    for key in ("sfx_trigger", "sfx_triggers"):
        value = manifest.get(key)
        if isinstance(value, dict):
            tokens += " " + " ".join(str(item or "") for item in value.values()).lower()
        elif isinstance(value, list):
            tokens += " " + " ".join(
                " ".join(str(item_value or "") for item_value in item.values()).lower()
                for item in value
                if isinstance(item, dict)
            )
    return any(token in tokens for token in ("hit", "impact", "slap", "punch", "thunder", "boom", "explosion", "击", "打", "雷", "巴掌", "轰", "拍", "巨响"))


def mix_scene_sfx(
    ffmpeg: str,
    voice_path: Path,
    scene: StoryScene,
    run_dir: Path,
    duration: float,
    project_root: Path | None = None,
) -> Path:
    if not voice_path.exists():
        return voice_path
    scene_id = f"{scene.scene:02}"
    triggers = scene_sfx_triggers(scene, run_dir, duration, project_root=project_root)
    if not triggers:
        return voice_path
    out_path = run_dir / f"scene_{scene_id}_voice_sfx.wav"
    filter_parts = ["[0:a]aformat=sample_rates=48000:channel_layouts=stereo[voice]"]
    mix_inputs = ["[voice]"]
    for index, trigger in enumerate(triggers, start=1):
        delay_ms = int(trigger.get("delay_ms") or 0)
        gain_db = trigger.get("gain_db")
        if gain_db not in (None, ""):
            volume = db_to_linear(_coerce_float(gain_db, 0.0, -60.0, 12.0))
        else:
            volume = float(trigger.get("volume") or 0.65)
        filter_parts.append(
            f"[{index}:a]volume={volume:.4f},adelay={delay_ms}|{delay_ms},aformat=sample_rates=48000:channel_layouts=stereo[s{index}]"
        )
        mix_inputs.append(f"[s{index}]")
    filter_parts.append(
        "".join(mix_inputs)
        + f"amix=inputs={len(mix_inputs)}:duration=first:normalize=0,alimiter=limit=0.96[mixed]"
    )
    filter_complex = ";".join(filter_parts)
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(voice_path),
    ]
    for trigger in triggers:
        cmd.extend(["-i", str(trigger["path"])])
    cmd.extend([
        "-filter_complex",
        filter_complex,
        "-map",
        "[mixed]",
        "-c:a",
        "pcm_s16le",
        str(out_path),
    ])
    try:
        run_guarded(cmd, cwd=run_dir, timeout=DEFAULT_SUBPROCESS_TIMEOUTS["ffmpeg_audio"], stage="ffmpeg_mix_sfx")
    except Exception as exc:
        print(f"[audio] SFX mix failed for scene {scene_id}: {exc}")
        return voice_path
    return out_path


def apply_scene_grade(ffmpeg: str, input_path: Path, out_path: Path, scene: StoryScene) -> Path:
    strength = clamp(float(scene.camera_intensity or 1.0), 0.7, 1.8)
    contrast = 1.03 + 0.03 * strength
    saturation = 1.05 + 0.05 * strength
    brightness = 0.004 * (strength - 1.0)
    sharpness = 0.55 + 0.18 * strength
    vignette = max(8.0, 14.0 - 2.0 * strength)
    filter_chain = ",".join(
        [
            "scale=1080:1920:flags=lanczos",
            f"eq=contrast={contrast:.3f}:brightness={brightness:.3f}:saturation={saturation:.3f}:gamma=1.00",
            f"unsharp=5:5:{sharpness:.3f}:5:5:0.000",
            f"vignette=PI/{vignette:.3f}",
            "format=yuv420p",
        ]
    )
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-vf",
        filter_chain,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-c:a",
        "copy",
        str(out_path),
    ]
    run_guarded(cmd, cwd=out_path.parent, timeout=DEFAULT_SUBPROCESS_TIMEOUTS["ffmpeg_render"], stage="ffmpeg_apply_grade")
    return out_path


def render_clip_with_meta(
    ffmpeg: str,
    scene: StoryScene,
    run_dir: Path,
    keyframe_provider: str,
    voice_provider: str,
    clip_duration: float,
    voice_path: Path,
    subtitle_style: dict | None = None,
    audio_style: dict | None = None,
    project_root: Path | None = None,
    keyframe_path: Path | None = None,
    video_provider: str = "auto",
) -> tuple[Path, VideoGenerationResult]:
    style = normalize_subtitle_style(subtitle_style)
    audio_settings = normalize_audio_style(audio_style)
    scene_id = f"{scene.scene:02}"
    keyframe = keyframe_path if keyframe_path and keyframe_path.exists() else generate_keyframe(scene, run_dir, keyframe_provider)
    out = run_dir / f"clip_{scene_id}.mp4"
    muxed = run_dir / f"clip_{scene_id}_muxed.mp4"
    graded = run_dir / f"clip_{scene_id}_graded.mp4"
    visual_path = run_dir / f"scene_{scene_id}_visual.mp4"
    subtitle_path = run_dir / f"scene_{scene_id}_dialogue.srt"
    subtitle_ass_path = run_dir / f"scene_{scene_id}_dialogue.ass"
    scene_audio = mix_voice_with_bgm(
        ffmpeg,
        voice_path,
        run_dir / f"scene_{scene_id}_mix.wav",
        clip_duration,
        scene_audio_style(scene, audio_settings, project_root=project_root),
        project_root=project_root,
    )
    scene_audio = mix_scene_sfx(ffmpeg, scene_audio, scene, run_dir, clip_duration, project_root=project_root)

    visual_generated = False
    provider_spec = get_video_provider_spec(video_provider)
    provider = provider_spec.id
    fallback_mode = video_fallback_mode()
    if env_bool(f"{provider.upper().replace('-', '_')}_VIDEO_STRICT", default=False):
        fallback_mode = "strict"
    attempts = 1
    last_error = ""
    warnings: list[str] = []
    used_backend = provider_spec.backend
    fallback_used = False
    if provider_spec.backend == "comfyui":
        try:
            print(f"[video] Rendering scene {scene_id} with {provider_spec.label} video provider")
            render_scene_video_comfyui(scene, keyframe, clip_duration, visual_path, run_dir)
            visual_generated = True
        except Exception as exc:
            last_error = str(exc)
            if env_bool("VIDEO_STRICT", "COMFYUI_VIDEO_STRICT", default=False) or fallback_mode == "strict":
                raise
            fallback_used = True
            used_backend = "local"
            if fallback_mode == "report":
                warnings.append(f"{provider_spec.label} video provider failed; using local 2.5D fallback.")
            print(f"[video] {provider_spec.label} video provider failed for scene {scene_id}; falling back to 2.5D clip: {exc}")
    elif provider_spec.backend == "remote":
        max_retries = int(env_float("VIDEO_MAX_RETRIES", default=2))
        retry_delay = env_float("VIDEO_RETRY_DELAY_SECONDS", default=5.0)
        last_exc = None
        for attempt in range(1, max_retries + 2):
            attempts = attempt
            try:
                print(f"[video] Rendering scene {scene_id} with {provider_spec.label} remote video provider (attempt {attempt}/{max_retries + 1})")
                prompt_text, negative_text = build_scene_video_prompts(scene, clip_duration, run_dir)
                temporal_spec = scene.temporal_spec or build_scene_temporal_spec(
                    scene,
                    clip_duration,
                    width=int(env_float("VIDEO_WIDTH", default=1080)),
                    height=int(env_float("VIDEO_HEIGHT", default=1920)),
                    fps=int(env_float("VIDEO_FPS", default=24)),
                )
                consistency_spec = scene_consistency_spec(scene)
                render_remote_video_provider(
                    VideoRenderRequest(
                        scene=scene.scene,
                        title=scene.title,
                        prompt=prompt_text,
                        negative_prompt=negative_text,
                        keyframe_path=keyframe,
                        out_path=visual_path,
                        run_dir=run_dir,
                        duration=clip_duration,
                        width=int(env_float("VIDEO_WIDTH", default=1080)),
                        height=int(env_float("VIDEO_HEIGHT", default=1920)),
                        fps=int(env_float("VIDEO_FPS", default=24)),
                        camera=scene.camera,
                        emotion=scene.emotion,
                        dialogue=scene.dialogue,
                        characters=tuple(scene.characters or []),
                        temporal_spec=temporal_spec,
                        consistency_spec=consistency_spec,
                    ),
                    provider_spec,
                    ffmpeg=ffmpeg,
                    run_guarded=run_guarded,
                    timeout_s=render_timeout(clip_duration) + 300,
                )
                visual_generated = True
                break
            except Exception as exc:
                last_exc = exc
                last_error = str(exc)
                if attempt <= max_retries:
                    # Use longer backoff for rate limiting / quota errors
                    error_str = str(exc).lower()
                    if "429" in error_str or "quota" in error_str or "饱和" in error_str:
                        backoff = max(retry_delay, 30.0)  # At least 30s for quota issues
                        print(f"[video] {provider_spec.label} attempt {attempt} rate-limited for scene {scene_id}. Waiting {backoff:.0f}s...")
                    else:
                        backoff = retry_delay
                        print(f"[video] {provider_spec.label} attempt {attempt} failed for scene {scene_id}: {exc}. Retrying in {backoff:.0f}s...")
                    time.sleep(backoff)
                    retry_delay = min(retry_delay * 2.0, 120.0)
                else:
                    strict_name = f"{provider.upper().replace('-', '_')}_VIDEO_STRICT"
                    if env_bool("VIDEO_STRICT", strict_name, default=False) or fallback_mode == "strict":
                        raise
                    fallback_used = True
                    used_backend = "local"
                    if fallback_mode == "report":
                        warnings.append(
                            f"{provider_spec.label} remote video provider failed after {attempt} attempts; using local 2.5D fallback."
                        )
                    print(f"[video] {provider_spec.label} remote video provider failed for scene {scene_id} after {attempt} attempts; falling back to 2.5D clip: {exc}")
    elif provider_spec.backend != "local":
        raise ValueError(f"Unsupported video provider backend: {provider_spec.backend}")

    if not visual_generated:
        d = clip_duration
        spoken_text = split_dialogue_speaker(scene.dialogue)[1]
        beat_specs = build_scene_beats(scene, d, spoken_text)
        screen_shake = scene_should_screen_shake(scene)

        with Image.open(keyframe) as source:
            base_image = apply_crop_box(source.convert("RGBA"), scene.crop_box)
        beat_segments: list[Path] = []
        for idx, beat in enumerate(beat_specs, start=1):
            frame_path = compose_comic_frame(base_image, scene, beat, run_dir, scene_id, idx, len(beat_specs))
            segment_path = run_dir / f"scene_{scene_id}_beat_{idx}.mp4"
            render_silent_visual_segment(
                ffmpeg,
                frame_path,
                float(beat["duration"]),
                segment_path,
                float(beat["zoom"]) + 0.06,
                scene.camera,
                idx,
                camera_speed=float(scene.camera_speed or 1.0),
                focus_x=float(beat.get("center_x", 0.5)),
                focus_y=float(beat.get("center_y", 0.5)),
                hold_in_ratio=float(beat.get("hold_in_ratio", 0.12)),
                hold_out_ratio=float(beat.get("hold_out_ratio", 0.12)),
                screen_shake=screen_shake and idx >= 3,
            )
            beat_segments.append(segment_path)

        concat_video_segments(
            ffmpeg,
            beat_segments,
            visual_path,
            run_dir,
            durations=[float(beat["duration"]) for beat in beat_specs],
            transition_duration=0.22,
        )
    mux_audio_to_visual(ffmpeg, visual_path, scene_audio, muxed)
    try:
        apply_scene_grade(ffmpeg, muxed, graded, scene)
    except Exception as exc:
        print(f"[video] Cinematic grade failed for scene {scene_id}: {exc}")
        graded = muxed

    subtitle_source = subtitle_ass_path if subtitle_ass_path.exists() and subtitle_ass_path.read_text(encoding="utf-8").strip() else subtitle_path
    if style.get("burn_in", True) and subtitle_source.exists() and subtitle_source.read_text(encoding="utf-8").strip():
        try:
            burn_subtitles_to_video(ffmpeg, graded, subtitle_source, out, style, timeout_s=render_timeout(clip_duration))
        except Exception as exc:
            print(f"[video] Subtitle burn failed for scene {scene_id}: {exc}")
            if graded != out:
                graded.replace(out)
        finally:
            if muxed.exists():
                muxed.unlink()
            if graded.exists() and graded != out:
                graded.unlink()
    else:
        if graded != out:
            graded.replace(out)
    result = VideoGenerationResult(
        scene_order=scene.scene,
        provider_id=provider_spec.id,
        provider_label=provider_spec.label,
        success=True,
        is_real_video=bool(visual_generated and provider_spec.backend in {"comfyui", "remote"} and not fallback_used),
        attempts=attempts,
        duration_seconds=clip_duration,
        output_path=str(out),
        error=last_error if fallback_used else "",
        warnings=warnings,
        backend=used_backend,
        fallback_used=fallback_used,
    )
    return out, result


def render_clip(
    ffmpeg: str,
    scene: StoryScene,
    run_dir: Path,
    keyframe_provider: str,
    voice_provider: str,
    clip_duration: float,
    voice_path: Path,
    subtitle_style: dict | None = None,
    audio_style: dict | None = None,
    project_root: Path | None = None,
    keyframe_path: Path | None = None,
    video_provider: str = "auto",
) -> Path:
    clip_path, _ = render_clip_with_meta(
        ffmpeg,
        scene,
        run_dir,
        keyframe_provider,
        voice_provider,
        clip_duration,
        voice_path,
        subtitle_style,
        audio_style,
        project_root,
        keyframe_path=keyframe_path,
        video_provider=video_provider,
    )
    return clip_path


def _normalize_scene_emotion(value: object) -> str:
    emotion = str(value or "").strip().lower()
    aliases = {
        "angry": "anger",
        "tense": "tension",
        "tense_scene": "tension",
        "fearful": "fear",
        "scared": "fear",
        "panic": "fear",
        "happy": "joy",
        "joyful": "joy",
        "sad": "sadness",
        "sorrow": "sadness",
        "melancholy": "sadness",
        "neutral": "neutral",
    }
    return aliases.get(emotion, emotion)


def _scene_transition(prev_emotion: str, next_emotion: str) -> str:
    prev = _normalize_scene_emotion(prev_emotion)
    nxt = _normalize_scene_emotion(next_emotion)
    if not prev or not nxt or prev == nxt:
        return "cut"

    black = {
        ("anger", "sadness"),
        ("anger", "calm"),
        ("fear", "calm"),
        ("tension", "calm"),
        ("joy", "sadness"),
        ("joy", "anger"),
    }
    xfade = {
        ("calm", "tension"),
        ("calm", "anger"),
        ("calm", "fear"),
        ("calm", "sadness"),
        ("calm", "surprise"),
        ("calm", "joy"),
        ("tension", "fear"),
        ("tension", "sadness"),
        ("sadness", "joy"),
        ("sadness", "calm"),
        ("sadness", "tension"),
        ("surprise", "sadness"),
        ("surprise", "calm"),
        ("fear", "sadness"),
    }

    pair = (prev, nxt)
    if pair in black:
        return "black"
    if pair in xfade:
        return "xfade"
    return "cut"


def _concat_cut_pair(ffmpeg: str, first: Path, second: Path, out_path: Path, run_dir: Path, stage: str) -> None:
    filter_complex = ";".join(
        [
            "[0:v]setpts=PTS-STARTPTS,fps=30,format=yuv420p[v0]",
            "[1:v]setpts=PTS-STARTPTS,fps=30,format=yuv420p[v1]",
            "[0:a]asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo[a0]",
            "[1:a]asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo[a1]",
            "[v0][v1]concat=n=2:v=1:a=0[v]",
            "[a0][a1]concat=n=2:v=0:a=1[a]",
        ]
    )
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(first),
        "-i",
        str(second),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(out_path),
    ]
    run_guarded(cmd, cwd=run_dir, timeout=concat_timeout(2) + 120, stage=stage)


def _concat_xfade_pair(
    ffmpeg: str,
    first: Path,
    second: Path,
    out_path: Path,
    run_dir: Path,
    first_duration: float,
) -> bool:
    fade_duration = 0.2
    if float(first_duration) <= fade_duration + 0.1:
        print(
            f"[video] xfade skipped for short segment ({float(first_duration):.3f}s); falling back to cut"
        )
        _concat_cut_pair(ffmpeg, first, second, out_path, run_dir, "ffmpeg_concat_video_xfade_short_fallback")
        return False
    offset = max(0.0, float(first_duration) - fade_duration - 0.05)
    filter_complex = ";".join(
        [
            "[0:v]setpts=PTS-STARTPTS,fps=30,format=yuv420p[v0]",
            "[1:v]setpts=PTS-STARTPTS,fps=30,format=yuv420p[v1]",
            "[0:a]asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo[a0]",
            "[1:a]asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo[a1]",
            f"[v0][v1]xfade=transition=fade:duration={fade_duration:.3f}:offset={offset:.3f}[v]",
            f"[a0][a1]acrossfade=d={fade_duration:.3f}:c1=tri:c2=tri[a]",
        ]
    )
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(first),
        "-i",
        str(second),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(out_path),
    ]
    run_guarded(cmd, cwd=run_dir, timeout=concat_timeout(2) + 120, stage="ffmpeg_concat_video_xfade")
    return True


def _concat_black_pair(
    ffmpeg: str,
    first: Path,
    second: Path,
    out_path: Path,
    run_dir: Path,
    first_duration: float,
    second_duration: float,
) -> None:
    fade_duration = 0.15
    first_fade_start = max(0.0, float(first_duration) - fade_duration)
    filter_complex = ";".join(
        [
            f"[0:v]setpts=PTS-STARTPTS,fps=30,format=yuv420p,fade=t=out:st={first_fade_start:.3f}:d={fade_duration:.3f}[v0]",
            f"[1:v]setpts=PTS-STARTPTS,fps=30,format=yuv420p,fade=t=in:st=0:d={fade_duration:.3f}[v1]",
            f"[0:a]asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo,afade=t=out:st={first_fade_start:.3f}:d={fade_duration:.3f}[a0]",
            f"[1:a]asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo,afade=t=in:st=0:d={fade_duration:.3f}[a1]",
            "[v0][v1]concat=n=2:v=1:a=0[v]",
            "[a0][a1]concat=n=2:v=0:a=1[a]",
        ]
    )
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(first),
        "-i",
        str(second),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(out_path),
    ]
    run_guarded(cmd, cwd=run_dir, timeout=concat_timeout(2) + 120, stage="ffmpeg_concat_video_black")


def concat_clips(
    ffmpeg: str,
    clips: list[Path],
    scenes: list[StoryScene],
    durations: list[float],
    run_dir: Path,
) -> Path:
    out = run_dir / "comic_drama_demo.mp4"
    if not clips:
        raise ValueError("No clips to concatenate")
    if len(clips) != len(scenes) or len(clips) != len(durations):
        concat_file = run_dir / "concat.txt"
        lines = [f"file '{clip.name}'" for clip in clips]
        write_text(concat_file, "\n".join(lines))
        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(out),
        ]
        run_guarded(cmd, cwd=run_dir, timeout=concat_timeout(len(clips)), stage="ffmpeg_concat_clips")
        return out

    current_path = clips[0]
    current_duration = media_duration(ffmpeg, current_path)

    for index in range(1, len(clips)):
        next_clip = clips[index]
        next_duration = media_duration(ffmpeg, next_clip)
        prev_scene = scenes[index - 1]
        next_scene = scenes[index]
        transition = _scene_transition(prev_scene.emotion_tone, next_scene.emotion_tone)
        print(
            f"[debug] scene transition {index}->{index + 1}: "
            f"{_normalize_scene_emotion(prev_scene.emotion_tone)} -> "
            f"{_normalize_scene_emotion(next_scene.emotion_tone)} = {transition}"
        )

        stage_out = run_dir / f"transition_{index:02d}.mp4"
        try:
            if transition == "xfade":
                used_xfade = _concat_xfade_pair(ffmpeg, current_path, next_clip, stage_out, run_dir, current_duration)
                if used_xfade:
                    current_duration = max(0.0, current_duration + next_duration - 0.2)
                else:
                    current_duration = current_duration + next_duration
            elif transition == "black":
                _concat_black_pair(ffmpeg, current_path, next_clip, stage_out, run_dir, current_duration, next_duration)
                current_duration = current_duration + next_duration
            else:
                _concat_cut_pair(ffmpeg, current_path, next_clip, stage_out, run_dir, "ffmpeg_concat_clips_cut")
                current_duration = current_duration + next_duration
        except Exception as exc:
            if transition != "cut":
                print(
                    f"[video] transition {index}->{index + 1} ({transition}) failed: {exc}; falling back to cut"
                )
            if stage_out.exists():
                try:
                    stage_out.unlink()
                except OSError:
                    pass
            _concat_cut_pair(ffmpeg, current_path, next_clip, stage_out, run_dir, "ffmpeg_concat_clips_cut_fallback")
            current_duration = current_duration + next_duration

        current_path = stage_out

    if current_path != out:
        shutil.copy2(current_path, out)
    faststart_out = out.with_name(f"{out.stem}_faststart{out.suffix}")
    try:
        run_guarded(
            [
                ffmpeg,
                "-y",
                "-i",
                str(out),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(faststart_out),
            ],
            cwd=run_dir,
            timeout=concat_timeout(1),
            stage="ffmpeg_faststart_remux",
        )
        faststart_out.replace(out)
    except Exception as exc:
        print(f"[video] faststart remux failed for {out.name}: {exc}")
        if faststart_out.exists():
            try:
                faststart_out.unlink()
            except OSError:
                pass
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local comic-drama workflow MVP.")
    parser.add_argument("--story", "--input", dest="story", type=Path, default=DEFAULT_STORY, help="Path to a story text file.")
    parser.add_argument("--run-id", default=None, help="Optional output run id.")
    parser.add_argument("--planner", choices=["auto", "rule", "llm"], default="auto", help="Storyboard planner to use.")
    parser.add_argument("--scene-count", type=int, default=5, help="Number of storyboard scenes for LLM planning.")
    parser.add_argument("--keyframe-provider", choices=["auto", "local", "comfyui"], default="auto", help="Keyframe renderer backend.")
    parser.add_argument("--video-provider", type=str, default="auto", help="Scene video provider id (for example: auto, local, comfyui).")
    parser.add_argument("--voice-provider", choices=["auto", "edge", "local", "silent"], default="auto", help="Voice renderer backend.")
    args = parser.parse_args()

    load_env_file()

    story = args.story.read_text(encoding="utf-8")
    run_id = args.run_id or time.strftime("run_%Y%m%d_%H%M%S")
    run_dir = OUTPUTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg = get_ffmpeg_exe()
    scene_count = min(12, max(1, args.scene_count))
    scenes, planner_used = build_storyboard(story, args.planner, scene_count)
    apply_episode_pacing_to_scenes(scenes, default_episode_pacing())
    keyframe_provider = args.keyframe_provider
    if keyframe_provider == "auto":
        keyframe_provider = env_value("KEYFRAME_PROVIDER", default="auto").lower()
    video_provider = normalize_video_provider(args.video_provider)
    voice_provider = args.voice_provider
    if voice_provider == "auto":
        voice_provider = env_value("TTS_PROVIDER", default="auto").lower()

    assets = []
    for scene in scenes:
        print(f"[1/5] Preparing scene {scene.scene}: {scene.title}")
        keyframe_path = generate_keyframe(scene, run_dir, keyframe_provider)
        voice_path, voice_duration = render_voice_track(ffmpeg, scene, run_dir, voice_provider)
        clip_duration = max(scene.duration, voice_duration)
        assets.append(
            {
                "scene": scene,
                "keyframe": keyframe_path,
                "voice": voice_path,
                "voice_duration": voice_duration,
                "clip_duration": clip_duration,
                "subtitle": run_dir / f"scene_{scene.scene:02}_dialogue.srt",
            }
        )

    storyboard_path = run_dir / "storyboard.json"
    storyboard_scenes: list[dict[str, object]] = []
    storyboard_shot_count = 0
    for item in assets:
        scene_graph = build_scene_graph(item["scene"])
        storyboard_scene = {
            **asdict(item["scene"]),
            "voice_duration": item["voice_duration"],
            "clip_duration": item["clip_duration"],
            "keyframe": str(item["keyframe"]),
            "voice": str(item["voice"]),
            **scene_graph,
        }
        storyboard_scene["director_plan"] = build_director_plan(storyboard_scene)
        storyboard_scene["shot_plan"] = build_shot_plan(storyboard_scene)
        storyboard_scenes.append(storyboard_scene)
        storyboard_shot_count += len(scene_graph.get("shots") or [])
    canonical_timeline = build_canonical_timeline(
        {
            "project_id": run_dir.name,
            "title": str(storyboard_scenes[0].get("title") or "Storyboard Timeline") if storyboard_scenes else "Storyboard Timeline",
            "scenes": storyboard_scenes,
        }
    )
    canonical_timeline_path = run_dir / "canonical_timeline.json"
    canonical_timeline_path.write_text(json.dumps(canonical_timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    storyboard_path.write_text(
        json.dumps(
            {
                "story": story,
                "planner": planner_used,
                "keyframe_provider": keyframe_provider,
                "video_provider": video_provider,
                "voice_provider": voice_provider,
                "canonical_timeline_path": str(canonical_timeline_path),
                "canonical_timeline": canonical_timeline,
                "scenes": storyboard_scenes,
                "scene_graph": {
                    "version": 1,
                    "scene_count": len(storyboard_scenes),
                    "shot_count": storyboard_shot_count,
                },
            },
            ensure_ascii=False,
            indent=2,
            ),
            encoding="utf-8",
        )
    stitch_scene_subtitles(
        [item["subtitle"] for item in assets],
        [item["clip_duration"] for item in assets],
        run_dir / "subtitles.srt",
        fallback_scenes=[item["scene"] for item in assets],
        ass_path=run_dir / "subtitles.ass",
    )

    print(f"[2/5] Storyboard written: {storyboard_path}")
    clips = []
    render_results: list[VideoGenerationResult] = []
    for index, item in enumerate(assets):
        scene = item["scene"]
        print(f"[3/5] Rendering scene {scene.scene}: {scene.title}")
        clip_path, render_result = render_clip_with_meta(
            ffmpeg,
            scene,
            run_dir,
            keyframe_provider,
            voice_provider,
            item["clip_duration"],
            item["voice"],
            keyframe_path=item["keyframe"],
            video_provider=video_provider,
        )
        clips.append(clip_path)
        render_results.append(render_result)
        storyboard_scene = storyboard_scenes[index]
        storyboard_scene["video"] = str(clip_path)
        storyboard_scene["generation_meta"] = generation_meta_from_result(
            render_result,
            requested_provider=video_provider,
            fallback_mode=video_fallback_mode(),
        )
        storyboard_scene["shot_plan"] = build_shot_plan(storyboard_scene)

    canonical_timeline = build_canonical_timeline(
        {
            "project_id": run_dir.name,
            "title": str(storyboard_scenes[0].get("title") or "Storyboard Timeline") if storyboard_scenes else "Storyboard Timeline",
            "scenes": storyboard_scenes,
        }
    )
    canonical_timeline_path.write_text(json.dumps(canonical_timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    storyboard_path.write_text(
        json.dumps(
            {
                "story": story,
                "planner": planner_used,
                "keyframe_provider": keyframe_provider,
                "video_provider": video_provider,
                "voice_provider": voice_provider,
                "canonical_timeline_path": str(canonical_timeline_path),
                "canonical_timeline": canonical_timeline,
                "scenes": storyboard_scenes,
                "scene_graph": {
                    "version": 1,
                    "scene_count": len(storyboard_scenes),
                    "shot_count": storyboard_shot_count,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("[4/5] Concatenating clips")
    final_video = concat_clips(ffmpeg, clips, [item["scene"] for item in assets], [item["clip_duration"] for item in assets], run_dir)
    manifest = {
        "run_id": run_id,
        "planner": planner_used,
        "keyframe_provider": keyframe_provider,
        "video_provider": video_provider,
        "voice_provider": voice_provider,
        "ffmpeg": ffmpeg,
        "storyboard": str(storyboard_path),
        "subtitles": str(run_dir / "subtitles.srt"),
        "keyframes": [str(item["keyframe"]) for item in assets],
        "voices": [str(item["voice"]) for item in assets],
        "clips": [str(clip) for clip in clips],
        "final_video": str(final_video),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[5/5] Done: {final_video}")


# Enhanced script recognition overrides.
#
# The original implementation stays in place as a fallback reference, but the
# definitions below take precedence at runtime and give the web MVP a steadier
# pasted-script parser plus richer preview metadata.
SCRIPT_SCENE_MARKERS = ("场景", "镜头", "Scene", "scene", "第", "#")
SCRIPT_ROLE_IGNORE = {"旁白", "解说", "播音", "字幕", "画外音"}
SCRIPT_DIALOGUE_SEPARATORS = (":", "：", "—", "–", "-", "－")
SCRIPT_HEADING_RE = re.compile(
    r"^\s*(?:(?:第\s*(?P<index>[\d一二三四五六七八九十百]{1,6})\s*(?:场|幕|节|镜头))|(?:scene\s*(?P<scene_index>\d{1,3}))|(?:场景\s*\d{1,3})|(?:镜头\s*\d{1,3})|(?:#{1,3}\s*.+))",
    re.IGNORECASE,
)
SCRIPT_SPEAKER_TOKEN_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9·•_]{1,16}$")
SCRIPT_HEADING_FALLBACK_RE = re.compile(
    r"^\s*(?:(?:\u7b2c\s*)?(?P<number>[0-9\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u4e24]{1,6})\s*(?:\u573a|\u5e55|\u8282|\u955c\u5934|\u955c)|(?P<label>\u573a\u666f|\u955c\u5934|\u5206\u955c|scene)\s*(?P<label_number>[0-9\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u4e24]{0,6})|(?P<hash>#{1,3}\s*.+))\s*(?P<trailing>.*)$",
    re.IGNORECASE,
)


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
    if any(token in candidate for token in ("剧本", "标题", "类型", "作者", "编剧", "提示", "提示词", "画面", "氛围", "音效", "说明", "备注", "简介", "梗概")):
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
        title = re.sub(r"^\s*第\s*[\d一二三四五六七八九十百]{1,6}\s*(?:场|幕|节|镜头)\s*[:：\-—]?\s*", "", raw).strip()
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
    return stripped.startswith(("(", "（", "[", "【", "「", "『", "*", "﹙", "《")) and stripped.endswith(
        (")", "）", "]", "】", "」", "』", "*", "﹚", "》")
    )


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

        if _looks_like_scene_heading(stripped) or _is_script_cue_line(stripped) or _split_script_dialogue(stripped)[0]:
            normalized.append(stripped)
            index += 1
            continue

        next_line = raw_lines[index + 1].strip() if index + 1 < len(raw_lines) else ""
        if _looks_like_speaker_label(stripped) and next_line and not _looks_like_scene_heading(next_line) and not _is_script_cue_line(next_line):
            normalized.append(f"{_clean_script_label(stripped)}：{next_line}")
            index += 2
            continue

        chunks = [chunk.strip() for chunk in re.split(r"(?<=[。！？!?；;…])\s*", stripped) if chunk.strip()]
        if len(chunks) > 1 and len(stripped) > 100:
            normalized.extend(chunks)
        else:
            normalized.append(stripped)
        index += 1
    return normalized


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
        key=lambda item: (-int(item.get("mentions", 0)), int(item.get("first_scene", 0)), str(item.get("name", ""))),
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
if __name__ == "__main__":
    main()
