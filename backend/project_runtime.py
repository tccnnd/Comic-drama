from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import base64
import binascii
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any

try:
    import imageio_ffmpeg
except ImportError:  # pragma: no cover - optional runtime dependency
    imageio_ffmpeg = None

from PIL import Image, ImageStat, UnidentifiedImageError

from backend.asset_retention import cleanup_project_versions
from backend.event_bus import project_event_bus
from backend.styles import get_default_style_id
from scripts.face_crop import preprocess_reference_image
from scripts.run_workflow import (
    coerce_scene,
    StoryScene,
    analyze_script_workflow,
    default_episode_pacing,
    build_storyboard,
    build_scene_graph,
    default_audio_style,
    default_subtitle_style,
    generate_keyframe,
    infer_episode_phase,
    load_env_file,
    normalize_episode_pacing,
    normalize_episode_phase,
    normalize_subtitle_style,
    normalize_audio_style,
    normalize_crop_box,
    render_clip,
    render_voice_track,
    stitch_scene_subtitles,
    wav_duration,
    is_script_text_garbled,
    validate_script_text,
)


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


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "workspace"
WORKSPACE.mkdir(parents=True, exist_ok=True)

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
SCENE_HISTORY_LIMIT = 6
SCENE_ACTION_LABELS = {
    "edit": "保存分镜",
    "rebuild": "整格重跑",
    "rerender-image": "重绘图",
    "rerender-audio": "重配音",
    "rerender-video": "重合成",
    "restore": "回滚版本",
    "build": "整集生成",
    "export": "导出成片",
}


class ExportAssetReadinessError(ValueError):
    def __init__(self, detail: dict[str, Any]) -> None:
        self.detail = detail
        super().__init__(str(detail.get("message") or "Export assets are not ready"))


def utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def project_dir(project_id: str) -> Path:
    return WORKSPACE / project_id


def project_file(project_id: str) -> Path:
    return project_dir(project_id) / "project.json"


def project_relative_path(project_id: str, relative_path: str) -> Path:
    base = project_dir(project_id).resolve()
    path = (base / Path(relative_path)).resolve()
    if path != base and base not in path.parents:
        raise ValueError(f"Path escapes project directory: {relative_path}")
    return path


def project_relative_file_exists(project_id: str, relative_path: str) -> bool:
    if not str(relative_path or "").strip():
        return False
    try:
        return project_relative_path(project_id, relative_path).is_file()
    except ValueError:
        return False


def project_lock(project_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        if project_id not in _LOCKS:
            _LOCKS[project_id] = threading.Lock()
        return _LOCKS[project_id]


def workspace_url(project_id: str, relative_path: str | Path) -> str:
    relative = Path(relative_path).as_posix().lstrip("/")
    return f"/workspace/{project_id}/{relative}"


def ffmpeg_concat_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", "\\:")


def ensure_project_dirs(project_id: str) -> None:
    base = project_dir(project_id)
    (base / "characters").mkdir(parents=True, exist_ok=True)
    (base / "scenes").mkdir(parents=True, exist_ok=True)
    (base / "output").mkdir(parents=True, exist_ok=True)


def character_dir(project_id: str) -> Path:
    return project_dir(project_id) / "characters"


def character_card_path(project_id: str, character: dict[str, Any] | str) -> Path:
    if isinstance(character, dict):
        char_id = str(character.get("char_id") or "").strip()
        if not char_id:
            char_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(character.get("name") or "character")).strip("_") or "character"
    else:
        char_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(character or "character")).strip("_") or "character"
    return character_dir(project_id) / f"{char_id}.json"


def default_character_meta() -> dict[str, str]:
    return {"age": "", "role": ""}


def normalize_character_meta(meta: object) -> dict[str, str]:
    normalized = default_character_meta()
    if isinstance(meta, dict):
        for key in normalized:
            value = meta.get(key)
            if value not in (None, ""):
                normalized[key] = str(value)
    return normalized


def normalize_character_card(character: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(character)
    merged["char_id"] = str(merged.get("char_id") or "").strip()
    merged["name"] = str(merged.get("name") or "").strip()
    merged["meta"] = normalize_character_meta(merged.get("meta"))
    merged["appearance_core"] = str(merged.get("appearance_core") or "").strip()
    merged["clothing_style"] = str(merged.get("clothing_style") or "").strip()
    merged["negative_constraints"] = str(merged.get("negative_constraints") or "").strip()
    merged["immutable_features"] = str(merged.get("immutable_features") or "").strip()
    merged["description"] = str(merged.get("description") or "").strip()
    merged["summary"] = str(merged.get("summary") or "").strip()
    merged["voice_profile"] = str(merged.get("voice_profile") or "").strip()
    merged["voice_engine"] = str(merged.get("voice_engine") or "").strip()
    merged["voice_id"] = str(merged.get("voice_id") or "").strip()
    merged["reference_audio_path"] = str(merged.get("reference_audio_path") or "").strip()
    merged["reference_audio_url"] = str(merged.get("reference_audio_url") or "").strip()
    merged["reference_text"] = str(merged.get("reference_text") or "").strip()
    merged["emotion"] = str(merged.get("emotion") or "").strip()
    merged["suggested_voice_engine"] = str(merged.get("suggested_voice_engine") or "edge").strip() or "edge"
    merged["reference_image_path"] = str(merged.get("reference_image_path") or "").strip()
    merged["reference_image_url"] = str(merged.get("reference_image_url") or "").strip()
    merged["primary_reference_image_path"] = str(merged.get("primary_reference_image_path") or "").strip()
    merged["primary_reference_image_url"] = str(merged.get("primary_reference_image_url") or "").strip()
    merged["reference_original_path"] = str(merged.get("reference_original_path") or "").strip()
    merged["reference_original_url"] = str(merged.get("reference_original_url") or "").strip()
    merged["reference_meta"] = deepcopy(merged.get("reference_meta") if isinstance(merged.get("reference_meta"), dict) else {})
    return merged


def load_character_card_files(project_id: str) -> dict[str, dict[str, Any]]:
    cards: dict[str, dict[str, Any]] = {}
    base = character_dir(project_id)
    if not base.exists():
        return cards
    for path in sorted(base.glob("*.json")):
        try:
            payload = load_json(path)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        payload = normalize_character_card(payload)
        char_id = payload.get("char_id") or path.stem
        name = payload.get("name") or ""
        if char_id:
            cards[str(char_id)] = payload
        if name:
            cards[_normalized_name(name)] = payload
    return cards


def sync_character_card_files(project: dict[str, Any]) -> None:
    project_id = str(project.get("project_id") or "")
    if not project_id:
        return
    ensure_project_dirs(project_id)
    for character in project.get("characters", []):
        if not isinstance(character, dict):
            continue
        normalized = normalize_character_card(character)
        path = character_card_path(project_id, normalized)
        atomic_write_json(path, normalized)


def hydrate_character_cards(project: dict[str, Any]) -> dict[str, Any]:
    project_id = str(project.get("project_id") or "")
    if not project_id:
        return project
    cards = load_character_card_files(project_id)
    if not cards:
        return project
    for character in project.get("characters", []):
        if not isinstance(character, dict):
            continue
        card = cards.get(str(character.get("char_id") or "")) or cards.get(_normalized_name(character.get("name")))
        if not isinstance(card, dict):
            continue
        for key in (
            "meta",
            "appearance_core",
            "clothing_style",
            "negative_constraints",
            "description",
            "summary",
            "voice_profile",
            "voice_engine",
            "voice_id",
            "reference_audio_path",
            "reference_audio_url",
            "reference_text",
            "emotion",
            "voice_rate",
            "voice_pitch",
            "voice_volume",
            "suggested_voice_engine",
            "reference_image_path",
            "reference_image_url",
            "reference_original_path",
            "reference_original_url",
            "reference_meta",
        ):
            value = card.get(key)
            if value not in (None, ""):
                character[key] = deepcopy(value)
    return project


def scene_dir(project_id: str, scene_id: str) -> Path:
    return project_dir(project_id) / "scenes" / scene_id


def next_version_path(directory: Path, prefix: str, suffix: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    max_version = 0
    pattern = f"{prefix}_v*{suffix}"
    for path in directory.glob(pattern):
        stem = path.stem
        if "_v" not in stem:
            continue
        try:
            version = int(stem.rsplit("_v", 1)[1])
        except ValueError:
            continue
        max_version = max(max_version, version)
    return directory / f"{prefix}_v{max_version + 1}{suffix}"


def derive_project_title(story_text: str, fallback: str = "未命名漫剧") -> str:
    compact = " ".join(story_text.strip().split())
    if not compact:
        return fallback
    return compact[:18]


def _scene_subtitle_path(scene_order: int, scene_id: str) -> str:
    return f"scenes/{scene_id}/scene_{scene_order:02d}_dialogue.srt"


def _scene_audio_ref(scene: StoryScene | dict[str, Any], project_id: str, scene_order: int, scene_id: str) -> dict[str, Any]:
    payload = scene if isinstance(scene, dict) else {}
    assets = payload.get("assets", {}) if isinstance(payload, dict) else {}
    audio_path = ""
    audio_url = ""
    if isinstance(assets, dict):
        audio_path = str(assets.get("audio_path") or "").strip()
        audio_url = str(assets.get("audio_url") or "").strip()
    if not audio_path and isinstance(scene, StoryScene):
        audio_path = str(scene.reference_audio_path or "").strip()
    if not audio_path and isinstance(payload, dict):
        audio_path = str(payload.get("reference_audio_path") or "").strip()
    if not audio_url and project_id and audio_path and project_relative_file_exists(project_id, audio_path):
        audio_url = workspace_url(project_id, audio_path)
    return {
        "kind": "scene_audio",
        "scene_id": scene_id,
        "scene_order": scene_order,
        "path": audio_path,
        "url": audio_url,
        "reference_audio_path": str(getattr(scene, "reference_audio_path", "") or payload.get("reference_audio_path") or "").strip(),
        "voice_id": str(getattr(scene, "voice_id", "") or payload.get("voice_id") or "").strip(),
        "voice_profile": str(getattr(scene, "voice_profile", "") or payload.get("voice_profile") or "").strip(),
    }


def _scene_subtitle_ref(project_id: str, scene_order: int, scene_id: str) -> dict[str, Any]:
    path = _scene_subtitle_path(scene_order, scene_id)
    url = workspace_url(project_id, path) if project_id and project_relative_file_exists(project_id, path) else ""
    return {
        "kind": "scene_subtitle",
        "scene_id": scene_id,
        "scene_order": scene_order,
        "path": path,
        "url": url,
    }


def _scene_graph_payload(
    scene: StoryScene | dict[str, Any],
    order: int,
    *,
    project_id: str = "",
) -> dict[str, Any]:
    if isinstance(scene, dict):
        scene_obj = _scene_from_payload(scene)
        payload_scene: dict[str, Any] = scene
    else:
        scene_obj = scene
        payload_scene = {}
    scene_order = int(payload_scene.get("order") or order) if isinstance(payload_scene, dict) else order
    scene_id = str(payload_scene.get("scene_id") or f"scene_{scene_order:03d}") if isinstance(payload_scene, dict) else f"scene_{scene_order:03d}"
    graph = deepcopy(build_scene_graph(scene_obj))
    graph = _apply_shot_overrides_to_graph(graph, payload_scene.get("shot_overrides") if isinstance(payload_scene, dict) else [])
    audio_ref = _scene_audio_ref(scene_obj, project_id, scene_order, scene_id)
    subtitle_ref = _scene_subtitle_ref(project_id, scene_order, scene_id)
    shots: list[dict[str, Any]] = []
    for shot in graph.get("shots", []) or []:
        shot_payload = deepcopy(shot) if isinstance(shot, dict) else {}
        shot_payload["scene_id"] = scene_id
        shot_payload["scene_order"] = scene_order
        shot_payload["audio_ref"] = deepcopy(audio_ref)
        shot_payload["subtitle_ref"] = deepcopy(subtitle_ref)
        shots.append(shot_payload)
    graph["shots"] = shots
    graph["camera_track"] = {
        **deepcopy(graph.get("camera_track") or {}),
        "movement": str(scene_obj.camera_movement or scene_obj.camera or "").strip(),
        "speed": float(scene_obj.camera_speed or 1.0),
        "shot_count": len(shots),
    }
    graph["production_bible"] = deepcopy(payload_scene.get("production_bible") or {}) if isinstance(payload_scene, dict) else {}
    graph["temporal_spec"] = deepcopy(payload_scene.get("temporal_spec") or {}) if isinstance(payload_scene, dict) else {}
    if isinstance(payload_scene, dict) and payload_scene.get("shot_overrides"):
        total_duration = float(graph["camera_track"].get("duration_seconds") or sum(float(shot.get("duration_seconds") or 0.0) for shot in shots))
        payload_scene["duration_seconds"] = round(total_duration, 3)
    return graph


def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _shot_override_key(override: dict[str, Any]) -> str:
    shot_id = str(override.get("shot_id") or "").strip()
    if shot_id:
        return f"id:{shot_id}"
    try:
        return f"order:{int(override.get('shot_order') or 0)}"
    except (TypeError, ValueError):
        return "order:0"


def _normalize_shot_overrides(overrides: Any) -> list[dict[str, Any]]:
    if not isinstance(overrides, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in overrides:
        if not isinstance(item, dict):
            continue
        try:
            shot_order = int(item.get("shot_order") or 0)
        except (TypeError, ValueError):
            shot_order = 0
        shot_id = str(item.get("shot_id") or "").strip()
        if shot_order <= 0 and not shot_id:
            continue
        payload: dict[str, Any] = {}
        if shot_id:
            payload["shot_id"] = shot_id
        if shot_order > 0:
            payload["shot_order"] = shot_order
        for key in ("label", "caption", "bubble", "camera_movement"):
            value = str(item.get(key) or "").strip()
            if value:
                payload[key] = value
        numeric_bounds = {
            "duration_seconds": (0.25, 120.0),
            "camera_speed": (0.1, 5.0),
            "zoom": (1.0, 3.0),
            "hold_in_ratio": (0.0, 0.45),
            "hold_out_ratio": (0.0, 0.45),
            "center_x": (0.0, 1.0),
            "center_y": (0.0, 1.0),
        }
        for key, bounds in numeric_bounds.items():
            if key in item and item.get(key) not in (None, ""):
                payload[key] = _bounded_float(item.get(key), bounds[0], bounds[0], bounds[1])
        normalized.append(payload)
    return normalized


def _apply_shot_overrides_to_graph(graph: dict[str, Any], overrides: Any) -> dict[str, Any]:
    normalized = _normalize_shot_overrides(overrides)
    if not normalized:
        graph["shot_overrides"] = []
        return graph
    by_key = {_shot_override_key(item): item for item in normalized}
    shots = [deepcopy(shot) for shot in graph.get("shots", []) or [] if isinstance(shot, dict)]
    if not shots:
        graph["shot_overrides"] = normalized
        return graph
    for shot in shots:
        key = f"id:{str(shot.get('shot_id') or '').strip()}"
        override = by_key.get(key)
        if override is None:
            override = by_key.get(f"order:{int(shot.get('shot_order') or 0)}")
        if not override:
            continue
        for text_key in ("label", "caption", "bubble", "camera_movement"):
            if text_key in override:
                shot[text_key] = override[text_key]
        for number_key in (
            "duration_seconds",
            "camera_speed",
            "zoom",
            "hold_in_ratio",
            "hold_out_ratio",
            "center_x",
            "center_y",
        ):
            if number_key in override:
                shot[number_key] = override[number_key]
        shot["has_override"] = True
    cursor = 0.0
    for shot in shots:
        duration = max(0.25, float(shot.get("duration_seconds") or 0.25))
        shot["start_seconds"] = round(cursor, 3)
        shot["duration_seconds"] = round(duration, 3)
        cursor += duration
        shot["end_seconds"] = round(cursor, 3)
    graph["shots"] = shots
    graph["shot_overrides"] = normalized
    camera_track = deepcopy(graph.get("camera_track") or {})
    camera_track["shot_count"] = len(shots)
    camera_track["duration_seconds"] = round(cursor, 3)
    graph["camera_track"] = camera_track
    return graph


def _apply_scene_graph(scene: dict[str, Any], graph: dict[str, Any]) -> None:
    scene["camera_track"] = deepcopy(graph.get("camera_track") or {})
    scene["shots"] = deepcopy(graph.get("shots") or [])
    scene["shot_count"] = len(scene["shots"])
    scene["shot_overrides"] = deepcopy(graph.get("shot_overrides") or [])
    scene["production_bible"] = deepcopy(graph.get("production_bible") or {})
    scene["temporal_spec"] = deepcopy(graph.get("temporal_spec") or {})


def _refresh_project_scene_graph(project: dict[str, Any], *, project_id: str = "") -> None:
    scenes = project.get("scenes", [])
    if not isinstance(scenes, list):
        return
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            continue
        scene_order = int(scene.get("order") or index)
        scene_context = scene_with_character_context(project, scene)
        graph = _scene_graph_payload(scene_context, scene_order, project_id=project_id)
        _apply_scene_graph(scene, graph)


def scene_to_dict(scene: StoryScene, order: int) -> dict[str, Any]:
    scene_id = f"scene_{order:03d}"
    payload = {
        "scene_id": scene_id,
        "order": order,
        "title": scene.title,
        "visual_prompt": scene.visual,
        "dialogue": scene.dialogue,
        "speaker": scene.speaker or "",
        "voice_profile": scene.voice_profile or "",
        "camera_movement": scene.camera,
        "emotion": scene.emotion,
        "duration_seconds": scene.duration,
        "characters": list(scene.characters),
        "voice_engine": scene.voice_engine or "",
        "voice_id": scene.voice_id or "",
        "reference_audio_path": scene.reference_audio_path or "",
        "reference_audio_url": "",
        "reference_text": scene.reference_text or "",
        "voice_rate": scene.voice_rate,
        "voice_pitch": scene.voice_pitch,
        "voice_volume": scene.voice_volume,
        "crop_box": normalize_crop_box(scene.crop_box),
        **default_drama_config(),
        "audio_manifest": deepcopy(scene.audio_manifest) if isinstance(scene.audio_manifest, dict) else {},
        "camera_speed": float(scene.camera_speed or 1.0),
        "episode_rhythm": scene.episode_rhythm or "",
        "episode_phase": scene.episode_phase or "",
        "episode_phase_index": int(scene.episode_phase_index or order),
        "episode_phase_total": int(scene.episode_phase_total or 0),
        "primary_reference_meta": deepcopy(scene.primary_reference_meta) if isinstance(scene.primary_reference_meta, dict) else {},
        "consistency_meta": deepcopy(scene.consistency_meta) if isinstance(scene.consistency_meta, dict) else {},
        "camera_movement": scene.camera_movement or "",
        "emotion_tone": scene.emotion_tone or "",
        "scene_intent": scene.scene_intent or "",
        "pacing": scene.pacing or "",
        "subject_focus": scene.subject_focus or "",
        "director_meta": deepcopy(scene.director_meta) if isinstance(scene.director_meta, dict) else {},
        "character_prompt_compilation": scene.character_prompt_compilation or "",
        "negative_prompt_compilation": scene.negative_prompt_compilation or "",
        "shot_overrides": [],
        "validation_failed": bool(getattr(scene, "validation_failed", False)),
        "error_message": str(getattr(scene, "error_message", "") or ""),
        "raw_llm_output": deepcopy(getattr(scene, "raw_llm_output", {})) if getattr(scene, "raw_llm_output", {}) else {},
        **default_enhancement_config(),
        "history": [],
        "assets": {
            "status": "pending",
            "versions": {"image": 0, "audio": 0, "video": 0},
            "image_path": "",
            "image_url": "",
            "audio_path": "",
            "audio_url": "",
            "video_path": "",
            "video_url": "",
        },
    }
    if payload["validation_failed"]:
        payload["assets"]["status"] = "failed"
    if not isinstance(scene.director_meta, dict):
        apply_director_recommendation(payload)
    graph = _scene_graph_payload(payload, order)
    _apply_scene_graph(payload, graph)
    return payload


def _director_text(scene: dict[str, Any]) -> str:
    return " ".join(
        str(scene.get(key) or "")
        for key in ("title", "visual_prompt", "dialogue", "emotion", "camera_movement", "sfx_type")
    ).lower()


def _ensure_audio_manifest(scene: dict[str, Any]) -> dict[str, Any]:
    default_manifest = deepcopy(default_drama_config()["audio_manifest"])
    manifest = scene.get("audio_manifest")
    if not isinstance(manifest, dict):
        manifest = {}
    merged = {**default_manifest, **manifest}
    trigger = merged.get("sfx_trigger")
    if not isinstance(trigger, dict):
        trigger = {}
    merged["sfx_trigger"] = {**default_manifest["sfx_trigger"], **trigger}
    if not isinstance(merged.get("sfx_triggers"), list):
        merged["sfx_triggers"] = []
    scene["audio_manifest"] = merged
    return merged


def _normalize_audio_manifest(manifest: object) -> dict[str, Any]:
    default_manifest = deepcopy(default_drama_config()["audio_manifest"])
    if not isinstance(manifest, dict):
        return default_manifest
    merged = {**default_manifest, **manifest}
    trigger = merged.get("sfx_trigger")
    if isinstance(trigger, dict):
        merged["sfx_trigger"] = {**default_manifest["sfx_trigger"], **trigger}
    else:
        merged["sfx_trigger"] = deepcopy(default_manifest["sfx_trigger"])
    if not isinstance(merged.get("sfx_triggers"), list):
        merged["sfx_triggers"] = []
    return merged


def apply_director_recommendation(scene: dict[str, Any], *, preserve_explicit: bool = True) -> dict[str, Any]:
    text = _director_text(scene)
    manifest = _ensure_audio_manifest(scene)
    current_camera = str(scene.get("camera_movement") or "").strip()
    current_speed = scene.get("camera_speed")
    trigger = manifest.setdefault("sfx_trigger", {})

    impact_tokens = (
        "巴掌",
        "耳光",
        "掌掴",
        "拍",
        "拍桌",
        "办公桌",
        "巨响",
        "啪嗒",
        "掉",
        "掉落",
        "落地",
        "钢笔",
        "打脸",
        "打飞",
        "拳",
        "踢",
        "撞",
        "砸",
        "雷",
        "闪电",
        "惊雷",
        "爆炸",
        "刺入",
        "拔剑",
        "刀光",
        "震惊",
        "怎么可能",
        "不可能",
        "杀意",
        "背叛",
        "怒吼",
        "吐血",
        "跪下",
        "slap",
        "hit",
        "impact",
        "thunder",
        "boom",
    )
    melancholy_tokens = (
        "内心",
        "独白",
        "回忆",
        "悲伤",
        "沉默",
        "雨夜",
        "孤独",
        "低沉",
        "叹息",
        "绝望",
        "落泪",
        "眼泪",
        "苦笑",
        "melancholy",
        "sad",
        "memory",
    )
    establishing_tokens = (
        "全景",
        "远景",
        "会议室",
        "顶层",
        "宫殿",
        "大殿",
        "推开",
        "木门",
        "西装",
        "全场",
        "董事",
        "山门",
        "建筑",
        "第一次登场",
        "初次登场",
        "登场",
        "全身",
        "高大",
        "城门",
        "华山",
        "宗门",
        "山巅",
        "establishing",
        "wide shot",
        "full body",
    )

    recommendation = ""
    if any(token in text for token in impact_tokens):
        recommendation = "dramatic_push"
    elif any(token in text for token in melancholy_tokens):
        recommendation = "melancholy_pan"
    elif any(token in text for token in establishing_tokens):
        recommendation = "establishing_tilt"

    auto_cameras = {
        "",
        "auto",
        "static",
        "slow_push_in",
        "slow_zoom_out",
        "pan_left",
        "pan_right",
        "tilt_down",
        "tilt_up",
        "dramatic_reveal",
    }
    if recommendation and (not preserve_explicit or current_camera in auto_cameras):
        scene["camera_movement"] = recommendation

    try:
        speed_value = float(current_speed) if current_speed not in (None, "") else None
    except (TypeError, ValueError):
        speed_value = None

    camera = str(scene.get("camera_movement") or "")
    if camera == "dramatic_push":
        speed = max(1.35, speed_value or 1.35)
        if not trigger.get("file"):
            if any(token in text for token in ("雷", "闪电", "惊雷", "thunder")):
                trigger["file"] = "thunder"
            elif any(token in text for token in ("拍", "拍桌", "办公桌", "巨响", "撞门", "爆炸", "boom")):
                trigger["file"] = "boom"
            elif any(token in text for token in ("巴掌", "耳光", "掌掴", "扇耳光", "扇巴掌", "slap")):
                trigger["file"] = "slap"
            elif any(token in text for token in ("啪嗒", "掉", "掉落", "落地", "钢笔", "drop")):
                trigger["file"] = "drop"
            else:
                trigger["file"] = "hit"
        if not trigger.get("timestamp_ms"):
            if any(token in text for token in ("啪嗒", "掉", "掉落", "落地", "钢笔", "推开", "开门")):
                trigger["timestamp_ms"] = 350
            else:
                trigger["timestamp_ms"] = 1200
        if scene.get("sfx_type") in (None, "", "auto"):
            scene["sfx_type"] = str(trigger.get("file") or "hit")
    elif camera == "melancholy_pan":
        speed = min(0.8, speed_value or 0.7)
    elif camera == "establishing_tilt":
        speed = speed_value or 0.85
    else:
        speed = speed_value or 1.0
    scene["camera_speed"] = max(0.35, min(3.0, speed))
    if not trigger.get("volume"):
        trigger["volume"] = 0.65
    manifest["sfx_trigger"] = trigger
    scene["director_recommendation"] = {
        "camera_movement": scene.get("camera_movement"),
        "camera_speed": scene.get("camera_speed"),
        "sfx_type": scene.get("sfx_type", "auto"),
        "reason": "rule_heuristic",
    }
    return scene


def _role_lookup(roles: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for role in roles or []:
        if not isinstance(role, dict):
            continue
        name = str(role.get("name") or "").strip()
        if not name:
            continue
        lookup[_normalized_name(name)] = role
    return lookup


_PLACEHOLDER_CHARACTER_NAMES = {
    "主角",
    "主人公",
    "角色",
    "人物",
    "旁白",
    "解说",
    "男主",
    "女主",
    "反派",
}
_PLACEHOLDER_CHARACTER_NAMES_NORMALIZED = {str(item).strip().lower() for item in _PLACEHOLDER_CHARACTER_NAMES}


def _is_placeholder_character(name: str, role_map: dict[str, dict[str, Any]]) -> bool:
    normalized = _normalized_name(name)
    return normalized in _PLACEHOLDER_CHARACTER_NAMES_NORMALIZED and normalized not in role_map


def build_initial_characters(scenes: list[StoryScene], roles: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    role_map = _role_lookup(roles)
    index = 1
    for scene in scenes:
        for character in scene.characters:
            name = character.strip()
            if not name or name in seen:
                continue
            if _is_placeholder_character(name, role_map):
                continue
            role = role_map.get(_normalized_name(name), {})
            voice_rate = role.get("voice_rate") if role.get("voice_rate") not in (None, "") else scene.voice_rate
            voice_pitch = role.get("voice_pitch") if role.get("voice_pitch") not in (None, "") else scene.voice_pitch
            voice_volume = role.get("voice_volume") if role.get("voice_volume") not in (None, "") else scene.voice_volume
            seen[name] = {
                "char_id": f"c_{index:03d}",
                "name": name,
                **default_voice_config(),
                "meta": normalize_character_meta(role.get("meta") if isinstance(role.get("meta"), dict) else {}),
                "appearance_core": str(role.get("appearance_core") or ""),
                "clothing_style": str(role.get("clothing_style") or ""),
                "negative_constraints": str(role.get("negative_constraints") or ""),
                "immutable_features": str(role.get("immutable_features") or ""),
                "voice_profile": str(role.get("voice_profile") or scene.voice_profile or ""),
                "voice_engine": str(role.get("suggested_voice_engine") or scene.voice_engine or ""),
                "voice_id": str(role.get("voice_id") or scene.voice_id or ""),
                "reference_audio_path": str(role.get("reference_audio_path") or scene.reference_audio_path or ""),
                "reference_audio_url": "",
                "reference_text": str(role.get("reference_text") or scene.reference_text or ""),
                "emotion": str(role.get("emotion") or scene.emotion or ""),
                "voice_rate": float(voice_rate if voice_rate not in (None, "") else 1.0),
                "voice_pitch": float(voice_pitch if voice_pitch not in (None, "") else 0.0),
                "voice_volume": float(voice_volume if voice_volume not in (None, "") else 1.0),
                "description": str(role.get("summary") or ""),
                "first_scene": int(role.get("first_scene") or scene.scene),
                "importance": float(role.get("importance") or 0),
                "summary": str(role.get("summary") or ""),
                "suggested_voice_engine": str(role.get("suggested_voice_engine") or "edge"),
                "reference_image_path": "",
                "reference_image_url": "",
                "primary_reference_image_path": "",
                "primary_reference_image_url": "",
                "reference_original_path": "",
                "reference_original_url": "",
                "reference_meta": {},
            }
            index += 1
    return list(seen.values())


def remove_placeholder_scene_characters(scenes: list[StoryScene], roles: list[dict[str, Any]] | None = None) -> list[StoryScene]:
    role_map = _role_lookup(roles)
    if not role_map:
        return scenes
    for scene in scenes:
        scene.characters = [name for name in scene.characters if not _is_placeholder_character(name, role_map)]
        if scene.speaker and _is_placeholder_character(scene.speaker, role_map):
            scene.speaker = ""
    return scenes


def _normalized_name(value: object) -> str:
    return str(value or "").strip().lower()


def merge_character_configs(
    existing: list[dict[str, Any]],
    scenes: list[StoryScene],
    roles: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    fresh = build_initial_characters(scenes, roles=roles)
    if not fresh:
        return deepcopy(existing)

    existing_map: dict[str, dict[str, Any]] = {}
    for character in existing:
        key = _normalized_name(character.get("name"))
        if key and key not in existing_map:
            existing_map[key] = character

    merged: list[dict[str, Any]] = []
    preserved_keys = {
        "char_id",
        "meta",
        "appearance_core",
        "clothing_style",
        "negative_constraints",
        "description",
        "reference_image_path",
        "reference_image_url",
        "reference_original_path",
        "reference_original_url",
        "reference_meta",
        "voice_id",
        "reference_audio_path",
        "reference_audio_url",
        "reference_text",
        "voice_rate",
        "voice_pitch",
        "voice_volume",
    }
    for character in fresh:
        key = _normalized_name(character.get("name"))
        merged_character = deepcopy(character)
        source = existing_map.get(key)
        if source:
            for field in preserved_keys:
                value = source.get(field)
                if value not in (None, ""):
                    merged_character[field] = deepcopy(value)
        merged.append(merged_character)
    return merged


def create_project(
    title: str,
    story_text: str,
    planner: str,
    scene_count: int,
    keyframe_provider: str,
    video_provider: str,
    voice_provider: str,
) -> dict[str, Any]:
    load_env_file()
    project_id = f"proj_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    ensure_project_dirs(project_id)

    scenes, planner_used = build_storyboard(story_text, planner, scene_count)
    project = {
        "project_id": project_id,
        "title": title.strip() or derive_project_title(story_text),
        "story_text": story_text,
        "style_id": get_default_style_id(),
        "style_guide": "",
        "settings": {
            "aspect_ratio": "9:16",
            "global_style": "竖屏动态漫画",
            "planner": planner_used,
            "scene_count": scene_count,
            "keyframe_provider": keyframe_provider,
            "video_provider": video_provider,
            "voice_provider": voice_provider,
            "subtitle_style": default_subtitle_style(),
            "audio_style": default_audio_style(),
            "episode_pacing": default_episode_pacing_config(),
        },
        "characters": build_initial_characters(scenes),
        "scenes": [scene_to_dict(scene, order) for order, scene in enumerate(scenes, start=1)],
        "runtime": {
            "status": "idle",
            "progress": 0,
            "stage": "draft",
            "message": "Draft ready",
            "updated_at": utc_iso(),
        },
        "output": {
            "final_video_path": "",
            "final_video_url": "",
            "subtitles_path": "",
            "subtitles_url": "",
            "status": "idle",
        },
        "created_at": utc_iso(),
        "updated_at": utc_iso(),
    }
    apply_project_episode_pacing(project, force=True)
    return _save_project_with_project_event(project)


def reconstruct_story_text_from_scenes(project: dict[str, Any]) -> str:
    parts: list[str] = []
    for scene in sorted(project.get("scenes", []), key=lambda item: int(item.get("order", 0))):
        title = str(scene.get("title") or f"场景 {int(scene.get('order') or 0)}").strip()
        speaker = str(scene.get("speaker") or "").strip()
        visual = str(scene.get("visual_prompt") or "").strip()
        dialogue = str(scene.get("dialogue") or "").strip()
        lines = [f"{title}"]
        if visual:
            lines.append(f"【画面】{visual}")
        if dialogue:
            lines.append(dialogue)
        elif speaker:
            lines.append(f"{speaker}：")
        parts.append("\n".join(lines).strip())
    return "\n\n".join(parts).strip()


def replace_project_storyboard(
    project_id: str,
    story_text: str,
    planner: str,
    title: str = "",
    max_scenes: int = 12,
    script_hint: str = "",
) -> dict[str, Any]:
    load_env_file()
    analysis, scenes, planner_used = analyze_script_workflow(
        story_text,
        planner,
        max_scenes=max_scenes,
        script_hint=script_hint,
    )
    roles = analysis.get("roles") if isinstance(analysis, dict) else None
    scenes = remove_placeholder_scene_characters(scenes, roles=roles)
    with project_lock(project_id):
        project = load_project(project_id)
        existing_characters = list(project.get("characters", []))
        project["story_text"] = story_text
        project["script_analysis"] = analysis
        chosen_title = title.strip()
        if chosen_title:
            project["title"] = chosen_title
        elif not str(project.get("title") or "").strip():
            project["title"] = derive_project_title(story_text)
        settings = project.setdefault("settings", {})
        settings["planner"] = planner_used
        settings["scene_count"] = len(scenes)
        project["characters"] = merge_character_configs(existing_characters, scenes, roles=roles)
        project["scenes"] = [scene_to_dict(scene, order) for order, scene in enumerate(scenes, start=1)]
        apply_project_episode_pacing(project, force=True)
        _mark_output_stale(project)
        project["output"] = {
            "final_video_path": "",
            "final_video_url": "",
            "subtitles_path": "",
            "subtitles_url": "",
            "status": "idle",
        }
        _set_runtime(project, status="idle", progress=0, stage="draft", message="Script parsed")
    return _save_project_with_project_event(project)


def _preview_scene_characters(value: object) -> list[str]:
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        items = re.split(r"[,，;；\n]+", value)
    else:
        items = [value]
    return [str(item).strip() for item in items if str(item).strip()]


def _preview_scene_to_story_scene(raw: dict[str, Any], index: int) -> StoryScene:
    normalized = {
        "title": raw.get("title") or raw.get("scene_title") or f"分镜 {index}",
        "visual": raw.get("visual") or raw.get("visual_prompt") or "",
        "dialogue": raw.get("dialogue") or "",
        "camera": raw.get("camera") or raw.get("camera_movement") or "slow_push_in",
        "emotion": raw.get("emotion") or "",
        "characters": _preview_scene_characters(raw.get("characters")),
        "speaker": raw.get("speaker") or "",
        "voice_profile": raw.get("voice_profile") or "",
        "duration": raw.get("duration") or raw.get("duration_seconds") or 4.0,
        "sfx_type": raw.get("sfx_type") or "auto",
        "audio_manifest": raw.get("audio_manifest") if isinstance(raw.get("audio_manifest"), dict) else {},
        "camera_speed": raw.get("camera_speed") or 1.0,
        "crop_box": raw.get("crop_box"),
    }
    return coerce_scene(normalized, index)


def replace_project_storyboard_from_preview(
    project_id: str,
    draft: dict[str, Any],
) -> dict[str, Any]:
    load_env_file()
    story_text = str(draft.get("story_text") or "").strip()
    if not story_text:
        raise ValueError("Script text is required.")
    validate_script_text(story_text)

    raw_scenes = draft.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("Script preview must contain scenes.")

    planner_used = str(draft.get("planner_used") or draft.get("planner") or "rule").strip() or "rule"
    title = str(draft.get("title") or "").strip()
    analysis = draft.get("analysis") if isinstance(draft.get("analysis"), dict) else {}
    scenes = [_preview_scene_to_story_scene(raw if isinstance(raw, dict) else {}, index) for index, raw in enumerate(raw_scenes, start=1)]
    analysis = deepcopy(analysis) if isinstance(analysis, dict) else {}
    roles = analysis.get("roles") if isinstance(analysis, dict) else None
    scenes = remove_placeholder_scene_characters(scenes, roles=roles)
    analysis["planner_used"] = planner_used
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

    with project_lock(project_id):
        project = load_project(project_id)
        existing_characters = list(project.get("characters", []))
        project["story_text"] = story_text
        project["script_analysis"] = analysis
        chosen_title = title.strip()
        if chosen_title:
            project["title"] = chosen_title
        elif not str(project.get("title") or "").strip():
            project["title"] = derive_project_title(story_text)
        settings = project.setdefault("settings", {})
        settings["planner"] = planner_used
        settings["scene_count"] = len(scenes)
        project["characters"] = merge_character_configs(existing_characters, scenes, roles=roles)
        project["scenes"] = [scene_to_dict(scene, order) for order, scene in enumerate(scenes, start=1)]
        apply_project_episode_pacing(project, force=True)
        _mark_output_stale(project)
        project["output"] = {
            "final_video_path": "",
            "final_video_url": "",
            "subtitles_path": "",
            "subtitles_url": "",
            "status": "idle",
        }
        _set_runtime(project, status="idle", progress=0, stage="draft", message="Script parsed")
    return _save_project_with_project_event(project)


def load_project(project_id: str) -> dict[str, Any]:
    path = project_file(project_id)
    if not path.exists():
        raise FileNotFoundError(project_id)
    project = load_json(path)
    if isinstance(project, dict):
        hydrate_character_cards(project)
        project.setdefault("style_guide", "")
    return project


def save_project(project: dict[str, Any]) -> dict[str, Any]:
    project_id = project["project_id"]
    project["style_id"] = str(project.get("style_id") or get_default_style_id()).strip()
    project.setdefault("style_guide", "")
    _refresh_project_scene_graph(project, project_id=project_id)
    project["updated_at"] = utc_iso()
    sync_character_card_files(project)
    atomic_write_json(project_file(project_id), project)
    try:
        cleanup_project_versions(project_dir(project_id), project, keep=2)
    except Exception as exc:
        print(f"[cleanup] failed for {project_id}: {exc}")
    return project


def project_subtitle_style(project: dict[str, Any]) -> dict[str, Any]:
    settings = project.setdefault("settings", {})
    style = normalize_subtitle_style(settings.get("subtitle_style"))
    settings["subtitle_style"] = style
    return style


def project_audio_style(project: dict[str, Any]) -> dict[str, Any]:
    settings = project.setdefault("settings", {})
    style = normalize_audio_style(settings.get("audio_style"))
    settings["audio_style"] = style
    return style


def default_episode_pacing_config() -> dict[str, Any]:
    return normalize_episode_pacing(default_episode_pacing())


def project_episode_pacing(project: dict[str, Any]) -> dict[str, Any]:
    settings = project.setdefault("settings", {})
    pacing = normalize_episode_pacing(settings.get("episode_pacing"))
    settings["episode_pacing"] = pacing
    return pacing


def _coerce_int_field(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def apply_project_episode_pacing(project: dict[str, Any], force: bool = False) -> dict[str, Any]:
    pacing = project_episode_pacing(project)
    scenes = project.get("scenes", [])
    total = max(1, len(scenes))
    for index, scene in enumerate(scenes, start=1):
        phase = normalize_episode_phase(scene.get("episode_phase"), "")
        if force or not phase:
            phase = infer_episode_phase(index, total, pacing)
            phase_index = index
        else:
            phase_index = _coerce_int_field(scene.get("episode_phase_index"), index, 1, total)
        scene["episode_rhythm"] = str(pacing.get("preset") or "classic_four_act")
        scene["episode_phase"] = phase
        scene["episode_phase_index"] = phase_index
        scene["episode_phase_total"] = total
    return project


def normalize_scene_pacing_update(updates: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(updates)
    if "crop_box" in normalized and normalized["crop_box"] is not None:
        normalized["crop_box"] = normalize_crop_box(normalized["crop_box"])
    if "episode_phase" in normalized and normalized["episode_phase"] is not None:
        normalized["episode_phase"] = normalize_episode_phase(normalized["episode_phase"], "setup")
    if "episode_phase_index" in normalized and normalized["episode_phase_index"] is not None:
        normalized["episode_phase_index"] = _coerce_int_field(normalized["episode_phase_index"], 1, 1, 100)
    if "episode_phase_total" in normalized and normalized["episode_phase_total"] is not None:
        normalized["episode_phase_total"] = _coerce_int_field(normalized["episode_phase_total"], 1, 1, 100)
    if "episode_rhythm" in normalized and normalized["episode_rhythm"] is not None:
        pacing = normalize_episode_pacing({"preset": normalized["episode_rhythm"]})
        normalized["episode_rhythm"] = pacing["preset"]
    return normalized


def default_voice_config() -> dict[str, Any]:
    return {
        "voice_engine": "",
        "voice_id": "",
        "reference_audio_path": "",
        "reference_audio_url": "",
        "reference_text": "",
        "emotion": "",
        "voice_rate": 1.0,
        "voice_pitch": 0.0,
        "voice_volume": 1.0,
    }


def default_enhancement_config() -> dict[str, Any]:
    return {
        "enhancement_mode": "none",
        "enhancement_provider": "",
        "enhancement_prompt": "",
        "enhancement_workflow_path": "",
        "enhancement_status": "idle",
        "enhancement_result_path": "",
        "enhancement_result_url": "",
    }


def default_drama_config() -> dict[str, Any]:
    return {
        "rhythm_preset": "balanced",
        "sfx_type": "auto",
        "audio_manifest": {
            "bgm_style": "",
            "bgm_file": "",
            "bgm_gain_db": "",
            "sfx_trigger": {"file": "", "timestamp_ms": 0, "volume": 0.65},
            "sfx_triggers": [],
        },
        "subtitle_preset": "standard",
        "camera_intensity": 1.0,
        "camera_speed": 1.0,
    }


def list_projects() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(WORKSPACE.glob("proj_*/project.json"), reverse=True):
        try:
            items.append(load_json(path))
        except Exception:
            continue
    return items


def delete_project(project_id: str) -> dict[str, str]:
    base = project_dir(project_id).resolve()
    workspace = WORKSPACE.resolve()
    if base == workspace or workspace not in base.parents:
        raise ValueError(f"Invalid project path: {project_id}")
    lock = project_lock(project_id)
    with lock:
        if not project_file(project_id).exists():
            raise FileNotFoundError(project_id)
        shutil.rmtree(base)
    with _LOCKS_GUARD:
        _LOCKS.pop(project_id, None)
    return {"project_id": project_id, "status": "deleted"}


def project_snapshot(project: dict[str, Any]) -> dict[str, Any]:
    snapshot = deepcopy(project)
    project_id = snapshot["project_id"]
    snapshot["style_id"] = str(snapshot.get("style_id") or get_default_style_id()).strip()
    snapshot.setdefault("style_guide", "")
    project_subtitle_style(snapshot)
    project_audio_style(snapshot)
    apply_project_episode_pacing(snapshot)
    _refresh_project_scene_graph(snapshot, project_id=project_id)
    scenes = snapshot.get("scenes", [])
    characters = snapshot.get("characters", [])
    for character in snapshot.get("characters", []):
        if isinstance(character, dict):
            character.update(normalize_character_card(character))
        for key, value in list(character.items()):
            if key.endswith("_path") and value and project_relative_file_exists(project_id, value):
                character[key.replace("_path", "_url")] = workspace_url(project_id, value)
        if character.get("reference_audio_path"):
            character["reference_audio_url"] = (
                workspace_url(project_id, character["reference_audio_path"])
                if project_relative_file_exists(project_id, character["reference_audio_path"])
                else ""
            )
    for scene in snapshot.get("scenes", []):
        scene["crop_box"] = normalize_crop_box(scene.get("crop_box"))
        for key, value in default_drama_config().items():
            scene.setdefault(key, value)
        _ensure_audio_manifest(scene)
        for key, value in default_enhancement_config().items():
            scene.setdefault(key, value)
        assets = scene.get("assets", {})
        for key, value in list(assets.items()):
            if key.endswith("_path") and value:
                if project_relative_file_exists(project_id, value):
                    assets[key.replace("_path", "_url")] = workspace_url(project_id, value)
                else:
                    kind = key[: -len("_path")]
                    assets[key] = ""
                    assets[key.replace("_path", "_url")] = ""
                    versions = assets.setdefault("versions", {"image": 0, "audio": 0, "video": 0})
                    if isinstance(versions, dict) and kind in versions:
                        versions[kind] = 0
        if scene.get("reference_audio_path"):
            scene["reference_audio_url"] = (
                workspace_url(project_id, scene["reference_audio_path"])
                if project_relative_file_exists(project_id, scene["reference_audio_path"])
                else ""
            )
        if scene.get("enhancement_result_path"):
            scene["enhancement_result_url"] = (
                workspace_url(project_id, scene["enhancement_result_path"])
                if project_relative_file_exists(project_id, scene["enhancement_result_path"])
                else ""
            )
    output = snapshot.get("output", {})
    if output.get("final_video_path") and project_relative_file_exists(project_id, output["final_video_path"]):
        output["final_video_url"] = workspace_url(project_id, output["final_video_path"])
    else:
        output["final_video_path"] = ""
        output["final_video_url"] = ""
    if output.get("subtitles_path") and project_relative_file_exists(project_id, output["subtitles_path"]):
        output["subtitles_url"] = workspace_url(project_id, output["subtitles_path"])
    else:
        output["subtitles_path"] = ""
        output["subtitles_url"] = ""
    if output.get("subtitles_ass_path") and project_relative_file_exists(project_id, output["subtitles_ass_path"]):
        output["subtitles_ass_url"] = workspace_url(project_id, output["subtitles_ass_path"])
    else:
        output["subtitles_ass_path"] = ""
        output["subtitles_ass_url"] = ""
    asset_totals = {"image": 0, "audio": 0, "video": 0}
    completed_scenes = 0
    scene_graph_entries: list[dict[str, Any]] = []
    total_shots = 0
    for scene in scenes:
        assets = scene.get("assets", {}) or {}
        if assets.get("status") == "completed":
            completed_scenes += 1
        for kind in asset_totals:
            if assets.get(f"{kind}_url"):
                asset_totals[kind] += 1
        shots = scene.get("shots", []) if isinstance(scene, dict) else []
        shot_count = len(shots) if isinstance(shots, list) else 0
        total_shots += shot_count
        scene_graph_entries.append(
            {
                "scene_id": str(scene.get("scene_id") or ""),
                "order": int(scene.get("order") or 0),
                "title": str(scene.get("title") or ""),
                "shot_count": shot_count,
                "camera_track": deepcopy(scene.get("camera_track") or {}),
            }
        )
    snapshot["summary"] = {
        "total_scenes": len(scenes),
        "completed_scenes": completed_scenes,
        "total_characters": len(characters),
        "asset_totals": asset_totals,
        "has_final_video": bool(output.get("final_video_url")),
        "total_shots": total_shots,
    }
    snapshot["scene_graph"] = {
        "version": 1,
        "scene_count": len(scenes),
        "shot_count": total_shots,
        "scenes": scene_graph_entries,
    }
    snapshot["production_bible"] = build_production_bible(snapshot)
    return snapshot


def _event_project(project: dict[str, Any]) -> dict[str, Any]:
    try:
        return project_snapshot(project)
    except Exception:
        return deepcopy(project)


def _event_scene(project: dict[str, Any], scene_order: int) -> dict[str, Any] | None:
    snapshot = _event_project(project)
    for scene in snapshot.get("scenes", []):
        try:
            if int(scene.get("order") or 0) == int(scene_order):
                return scene
        except (TypeError, ValueError):
            continue
    return None


def _publish_project_updated(project: dict[str, Any]) -> None:
    project_id = str(project.get("project_id") or "")
    if project_id:
        project_event_bus.publish_project_updated(project_id, _event_project(project))


def _publish_scene_updated(project: dict[str, Any], scene_order: int) -> None:
    project_id = str(project.get("project_id") or "")
    scene = _event_scene(project, scene_order)
    if project_id and scene:
        project_event_bus.publish_scene_updated(project_id, scene)


def _save_project_with_project_event(project: dict[str, Any]) -> dict[str, Any]:
    saved = save_project(project)
    _publish_project_updated(saved)
    return saved


def _save_project_with_scene_event(project: dict[str, Any], scene_order: int) -> dict[str, Any]:
    saved = save_project(project)
    _publish_scene_updated(saved, scene_order)
    _publish_project_updated(saved)
    return saved


def _save_project_with_structure_event(project: dict[str, Any], event_type: str, scene_order: int) -> dict[str, Any]:
    saved = save_project(project)
    project_id = str(saved.get("project_id") or "")
    snapshot = _event_project(saved)
    if not project_id:
        return saved
    if event_type == "split":
        project_event_bus.publish_scene_split(project_id, scene_order, snapshot)
    elif event_type == "merge":
        project_event_bus.publish_scene_merged(project_id, scene_order, snapshot)
    elif event_type == "restore":
        project_event_bus.publish_scene_restored(project_id, scene_order, snapshot)
    return saved


def _scene_from_payload(scene: dict[str, Any]) -> StoryScene:
    def _float_field(name: str, default: float) -> float:
        value = scene.get(name)
        return float(default if value is None or value == "" else value)

    return StoryScene(
        scene=int(scene.get("order") or 1),
        duration=float(scene.get("duration_seconds") or 4.0),
        title=str(scene.get("title") or "分镜"),
        visual=str(scene.get("visual_prompt") or ""),
        dialogue=str(scene.get("dialogue") or ""),
        camera=str(scene.get("camera_movement") or "slow_push_in"),
        emotion=str(scene.get("emotion") or ""),
        characters=[str(item) for item in scene.get("characters") or [] if str(item).strip()],
        bg_color="0x182033",
        accent_color="0x4ea3ff",
        speaker=str(scene.get("speaker") or ""),
        voice_profile=str(scene.get("voice_profile") or ""),
        voice_engine=str(scene.get("voice_engine") or ""),
        voice_id=str(scene.get("voice_id") or ""),
        reference_audio_path=str(scene.get("reference_audio_path") or ""),
        reference_text=str(scene.get("reference_text") or ""),
        voice_emotion=str(scene.get("voice_emotion") or scene.get("emotion") or ""),
        voice_rate=_float_field("voice_rate", 1.0),
        voice_pitch=_float_field("voice_pitch", 0.0),
        voice_volume=_float_field("voice_volume", 1.0),
        rhythm_preset=str(scene.get("rhythm_preset") or "balanced"),
        sfx_type=str(scene.get("sfx_type") or "auto"),
        audio_manifest=_normalize_audio_manifest(scene.get("audio_manifest")),
        subtitle_preset=str(scene.get("subtitle_preset") or "standard"),
        camera_intensity=_float_field("camera_intensity", 1.0),
        camera_speed=_float_field("camera_speed", 1.0),
        episode_rhythm=str(scene.get("episode_rhythm") or "classic_four_act"),
        episode_phase=normalize_episode_phase(scene.get("episode_phase"), "setup"),
        episode_phase_index=_coerce_int_field(scene.get("episode_phase_index"), 1, 1, 100),
        episode_phase_total=_coerce_int_field(scene.get("episode_phase_total"), 1, 1, 100),
        crop_box=normalize_crop_box(scene.get("crop_box")),
        character_descriptions=str(scene.get("character_descriptions") or ""),
        character_references=scene.get("character_references") if isinstance(scene.get("character_references"), list) else [],
        primary_reference_image_path=str(scene.get("primary_reference_image_path") or ""),
        primary_reference_image_abs_path=str(scene.get("primary_reference_image_abs_path") or ""),
        primary_reference_meta=deepcopy(scene.get("primary_reference_meta")) if isinstance(scene.get("primary_reference_meta"), dict) else None,
        consistency_meta=deepcopy(scene.get("consistency_meta")) if isinstance(scene.get("consistency_meta"), dict) else None,
        camera_movement=str(scene.get("camera_movement") or ""),
        emotion_tone=str(scene.get("emotion_tone") or ""),
        scene_intent=str(scene.get("scene_intent") or ""),
        pacing=str(scene.get("pacing") or ""),
        subject_focus=str(scene.get("subject_focus") or ""),
        director_meta=deepcopy(scene.get("director_meta")) if isinstance(scene.get("director_meta"), dict) else None,
        production_bible=deepcopy(scene.get("production_bible")) if isinstance(scene.get("production_bible"), dict) else {},
        temporal_spec=deepcopy(scene.get("temporal_spec")) if isinstance(scene.get("temporal_spec"), dict) else {},
        character_prompt_compilation=str(scene.get("character_prompt_compilation") or ""),
        negative_prompt_compilation=str(scene.get("negative_prompt_compilation") or ""),
        validation_failed=bool(scene.get("validation_failed")),
        error_message=str(scene.get("error_message") or ""),
        raw_llm_output=deepcopy(scene.get("raw_llm_output")) if isinstance(scene.get("raw_llm_output"), dict) else {},
    )


def _normalized_key(value: object) -> str:
    return str(value or "").strip().lower()


def _voice_source_for_scene(project: dict[str, Any], scene: dict[str, Any]) -> dict[str, Any] | None:
    names = [
        scene.get("speaker"),
        *list(scene.get("characters") or []),
    ]
    characters = project.get("characters", [])
    character_map = {
        _normalized_key(character.get("name")): character
        for character in characters
        if _normalized_key(character.get("name"))
    }
    for name in names:
        match = character_map.get(_normalized_key(name))
        if match:
            return match
    return None


def scene_character_refs(project: dict[str, Any], scene: dict[str, Any]) -> list[dict[str, Any]]:
    project_id = str(project.get("project_id") or "")
    character_map = {
        _normalized_key(character.get("name")): character
        for character in project.get("characters", [])
        if _normalized_key(character.get("name"))
    }
    ordered_names: list[object] = []
    speaker = scene.get("speaker")
    if speaker:
        ordered_names.append(speaker)
    ordered_names.extend(list(scene.get("characters") or []))

    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, name in enumerate(ordered_names):
        key = _normalized_key(name)
        if not key or key in seen:
            continue
        character = character_map.get(key)
        if not character:
            continue
        seen.add(key)
        relative_path = str(character.get("reference_image_path") or "").strip()
        abs_path = ""
        url = str(character.get("reference_image_url") or "").strip()
        if relative_path:
            candidate = project_dir(project_id) / relative_path
            if candidate.is_file():
                abs_path = str(candidate.resolve())
                url = workspace_url(project_id, relative_path)
        refs.append(
            {
                "name": str(character.get("name") or name),
                "char_id": str(character.get("char_id") or ""),
                "description": str(character.get("description") or ""),
                "summary": str(character.get("summary") or ""),
                "meta": deepcopy(character.get("meta") if isinstance(character.get("meta"), dict) else default_character_meta()),
                "appearance_core": str(character.get("appearance_core") or ""),
                "clothing_style": str(character.get("clothing_style") or ""),
                "negative_constraints": str(character.get("negative_constraints") or ""),
                "reference_meta": deepcopy(character.get("reference_meta") if isinstance(character.get("reference_meta"), dict) else {}),
                "reference_image_path": relative_path,
                "reference_image_abs_path": abs_path,
                "reference_image_url": url,
                "role": "primary" if not refs else "supporting",
            }
        )
    return refs


def _character_prompt_feature_lines(ref: dict[str, Any]) -> tuple[list[str], list[str]]:
    name = str(ref.get("name") or "").strip()
    meta = ref.get("meta") if isinstance(ref.get("meta"), dict) else {}
    positive: list[str] = []
    negative: list[str] = []

    age = str(meta.get("age") or "").strip()
    role = str(meta.get("role") or "").strip()
    appearance = str(ref.get("appearance_core") or "").strip()
    clothing = str(ref.get("clothing_style") or "").strip()
    description = str(ref.get("description") or ref.get("summary") or "").strip()
    negative_constraints = str(ref.get("negative_constraints") or "").strip()

    if name:
        identity_bits = [name]
        if age:
            identity_bits.append(f"{age}岁")
        if role:
            identity_bits.append(role)
        positive.append("角色设定：" + "，".join(identity_bits))
    if appearance:
        positive.append(f"{name}外貌锚点：{appearance}")
    if clothing:
        positive.append(f"{name}服装锚点：{clothing}")
    if description:
        positive.append(f"{name}补充设定：{description}")
    if negative_constraints:
        negative.append(negative_constraints)
    if name:
        negative.append(f"不要改变{name}的脸型、发型、服装与整体辨识度")
    return positive, negative


def compile_character_prompt(scene: dict[str, Any], refs: list[dict[str, Any]]) -> tuple[str, str]:
    positive_lines: list[str] = []
    negative_lines: list[str] = []
    seen: set[str] = set()
    for ref in refs[:4]:
        key = str(ref.get("char_id") or ref.get("name") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        positive, negative = _character_prompt_feature_lines(ref)
        positive_lines.extend(positive)
        negative_lines.extend(negative)

    scene_descriptions = str(scene.get("character_descriptions") or "").strip()
    if scene_descriptions:
        positive_lines.append(f"场景角色说明：{scene_descriptions}")
    scene_title = str(scene.get("title") or "").strip()
    if scene_title:
        positive_lines.append(f"镜头标题：{scene_title}")

    return "；".join(line for line in positive_lines if line), "；".join(line for line in negative_lines if line)


def build_production_bible(project: dict[str, Any]) -> dict[str, Any]:
    characters: list[dict[str, Any]] = []
    for character in project.get("characters", []) or []:
        if not isinstance(character, dict):
            continue
        characters.append(
            {
                "name": str(character.get("name") or "").strip(),
                "char_id": str(character.get("char_id") or "").strip(),
                "description": str(character.get("description") or character.get("summary") or "").strip(),
                "appearance_core": str(character.get("appearance_core") or "").strip(),
                "clothing_style": str(character.get("clothing_style") or "").strip(),
                "negative_constraints": str(character.get("negative_constraints") or "").strip(),
                "reference_image_path": str(character.get("reference_image_path") or "").strip(),
                "reference_meta": deepcopy(character.get("reference_meta")) if isinstance(character.get("reference_meta"), dict) else {},
            }
        )
    scenes: list[dict[str, Any]] = []
    for scene in project.get("scenes", []) or []:
        if not isinstance(scene, dict):
            continue
        scenes.append(
            {
                "scene_id": str(scene.get("scene_id") or "").strip(),
                "order": int(scene.get("order") or len(scenes) + 1),
                "title": str(scene.get("title") or "").strip(),
                "emotion_tone": str(scene.get("emotion_tone") or scene.get("emotion") or "").strip(),
                "pacing": str(scene.get("pacing") or "").strip(),
                "scene_intent": str(scene.get("scene_intent") or "").strip(),
                "subject_focus": str(scene.get("subject_focus") or "").strip(),
                "characters": [str(name).strip() for name in scene.get("characters") or [] if str(name).strip()],
            }
        )
    settings = project.get("settings") if isinstance(project.get("settings"), dict) else {}
    return {
        "version": 1,
        "project_id": str(project.get("project_id") or "").strip(),
        "title": str(project.get("title") or "").strip(),
        "style_id": str(project.get("style_id") or "").strip(),
        "style_guide": str(project.get("style_guide") or "").strip(),
        "global_style": str(settings.get("global_style") or "").strip(),
        "characters": characters,
        "scene_continuity": scenes,
        "rules": {
            "preserve_character_identity": True,
            "preserve_costume_per_scene": True,
            "keep_lighting_continuous_within_scene": True,
            "keep_environment_geometry_stable": True,
            "avoid_identity_drift": True,
            "avoid_unmotivated_camera_jumps": True,
        },
    }


def scene_production_bible(project: dict[str, Any], scene: dict[str, Any], refs: list[dict[str, Any]]) -> dict[str, Any]:
    bible = build_production_bible(project)
    scene_order = int(scene.get("order") or 0)
    bible["current_scene"] = {
        "scene_id": str(scene.get("scene_id") or f"scene_{scene_order:03d}"),
        "order": scene_order,
        "title": str(scene.get("title") or "").strip(),
        "visual_prompt": str(scene.get("visual_prompt") or "").strip(),
        "emotion_tone": str(scene.get("emotion_tone") or scene.get("emotion") or "").strip(),
        "pacing": str(scene.get("pacing") or "").strip(),
        "scene_intent": str(scene.get("scene_intent") or "").strip(),
        "subject_focus": str(scene.get("subject_focus") or "").strip(),
        "camera_movement": str(scene.get("camera_movement") or "").strip(),
        "active_characters": [
            {
                "name": str(ref.get("name") or "").strip(),
                "role": str(ref.get("role") or "").strip(),
                "appearance_core": str(ref.get("appearance_core") or "").strip(),
                "clothing_style": str(ref.get("clothing_style") or "").strip(),
                "negative_constraints": str(ref.get("negative_constraints") or "").strip(),
                "reference_image_path": str(ref.get("reference_image_path") or "").strip(),
            }
            for ref in refs
        ],
    }
    return bible


def scene_with_character_context(project: dict[str, Any], scene: dict[str, Any]) -> dict[str, Any]:
    merged = scene_with_inherited_voice(project, scene)
    refs = scene_character_refs(project, merged)
    descriptions = [
        f"{ref['name']}：{ref['description']}"
        for ref in refs
        if str(ref.get("description") or "").strip()
    ]
    primary = next((ref for ref in refs if ref.get("reference_image_abs_path") or ref.get("reference_image_path")), refs[0] if refs else None)
    merged["character_references"] = refs
    merged["character_descriptions"] = "；".join(descriptions)
    positive_prompt, negative_prompt = compile_character_prompt(merged, refs)
    merged["character_prompt_compilation"] = positive_prompt
    merged["negative_prompt_compilation"] = negative_prompt
    merged["visual_prompt_compiled"] = "；".join(
        part for part in [str(merged.get("visual_prompt") or "").strip(), positive_prompt] if part
    )
    if primary:
        merged["primary_reference_image_path"] = str(primary.get("reference_image_path") or "")
        merged["primary_reference_image_abs_path"] = str(primary.get("reference_image_abs_path") or "")
        primary_meta = primary.get("reference_meta") if isinstance(primary.get("reference_meta"), dict) else {}
        merged["primary_reference_meta"] = {
            "crop_method": primary_meta.get("crop_method"),
            "output_size": deepcopy(primary_meta.get("output_size")) if isinstance(primary_meta.get("output_size"), list) else primary_meta.get("output_size"),
            "warnings": list(primary_meta.get("warnings") or []),
        }
    merged["production_bible"] = scene_production_bible(project, merged, refs)
    scene_order = int(merged.get("order") or 1)
    scene_graph = _scene_graph_payload(merged, scene_order, project_id=str(project.get("project_id") or ""))
    merged["temporal_spec"] = {
        "version": 1,
        "kind": "scene_temporal_video_spec",
        "scene": scene_order,
        "title": str(merged.get("title") or "").strip(),
        "duration_seconds": float(merged.get("duration_seconds") or 0.0),
        "camera_track": deepcopy(scene_graph.get("camera_track") or {}),
        "shots": deepcopy(scene_graph.get("shots") or []),
        "continuity_rules": {
            "generate_continuous_video": True,
            "avoid_static_pan_only_motion": True,
            "preserve_character_environment_contact": True,
            "preserve_lighting_direction": True,
            "preserve_scene_geometry": True,
        },
    }
    return merged


def scene_with_inherited_voice(project: dict[str, Any], scene: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(scene)
    source = _voice_source_for_scene(project, scene)
    if not source:
        return merged
    for key in {
        "voice_profile",
        "voice_engine",
        "voice_id",
        "reference_audio_path",
        "reference_text",
        "emotion",
        "voice_rate",
        "voice_pitch",
        "voice_volume",
    }:
        if merged.get(key) in (None, "") and source.get(key) not in (None, ""):
            merged[key] = deepcopy(source[key])
    return merged


def _scene_assets(scene: dict[str, Any]) -> dict[str, Any]:
    return scene.setdefault(
        "assets",
        {
            "status": "pending",
            "versions": {"image": 0, "audio": 0, "video": 0},
            "image_path": "",
            "image_url": "",
            "audio_path": "",
            "audio_url": "",
            "video_path": "",
            "video_url": "",
        },
    )


def _scene_validation_blocked(scene: dict[str, Any]) -> str | None:
    if bool(scene.get("validation_failed")):
        return str(scene.get("error_message") or "Scene validation failed").strip()
    assets = scene.get("assets", {})
    if isinstance(assets, dict) and str(assets.get("status") or "").lower() == "failed":
        return str(scene.get("error_message") or "Scene validation failed").strip()
    return None


def _scene_validation_resolved(scene: dict[str, Any]) -> bool:
    visual = str(scene.get("visual_prompt") or "").strip()
    if not visual:
        return False
    try:
        duration = float(scene.get("duration_seconds") or 0)
    except (TypeError, ValueError):
        return False
    if duration <= 0:
        return False
    if not isinstance(scene.get("characters"), list):
        return False
    try:
        camera_speed = float(scene.get("camera_speed") or 0)
    except (TypeError, ValueError):
        return False
    if not 0.35 <= camera_speed <= 3.0:
        return False
    audio_manifest = scene.get("audio_manifest")
    if not isinstance(audio_manifest, dict):
        return False
    if not isinstance(audio_manifest.get("sfx_trigger"), dict):
        return False
    camera = str(scene.get("camera_movement") or "").strip()
    if not camera:
        return False
    return True


def _ensure_scene_renderable(scene: dict[str, Any], scene_order: int) -> None:
    reason = _scene_validation_blocked(scene)
    if reason:
        raise ValueError(f"Scene {scene_order} is invalid and cannot be rendered: {reason}")


def _scene_history(scene: dict[str, Any]) -> list[dict[str, Any]]:
    return scene.setdefault("history", [])


def _scene_snapshot_dir(project_id: str, scene_id: str) -> Path:
    return scene_dir(project_id, scene_id) / "snapshots"


def _scene_snapshot_payload(
    project_id: str,
    scene_order: int,
    action: str,
    scene: dict[str, Any],
    project: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scene_payload = deepcopy(scene)
    _apply_scene_graph(scene_payload, _scene_graph_payload(scene_payload, scene_order, project_id=project_id))
    payload = {
        "project_id": project_id,
        "scene_order": scene_order,
        "action": action,
        "captured_at": utc_iso(),
        "scene": scene_payload,
    }
    if project is not None:
        payload["scenes"] = deepcopy(project.get("scenes", []))
    return payload


def _capture_scene_snapshot_locked(project_id: str, scene_order: int, action: str, project: dict[str, Any]) -> Path:
    scene = next((item for item in project.get("scenes", []) if int(item.get("order", 0)) == scene_order), None)
    if scene is None:
        raise KeyError(f"Scene {scene_order} not found")
    directory = _scene_snapshot_dir(project_id, scene["scene_id"])
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}_{uuid.uuid4().hex[:8]}_{action}.json"
    path = directory / filename
    atomic_write_json(path, _scene_snapshot_payload(project_id, scene_order, action, scene, project))
    return path


def capture_scene_snapshot(project_id: str, scene_order: int, action: str) -> Path:
    with project_lock(project_id):
        project = load_project(project_id)
        return _capture_scene_snapshot_locked(project_id, scene_order, action, project)


def _latest_scene_snapshot_locked(
    project_id: str,
    scene_order: int,
    skip_actions: set[str] | None,
    project: dict[str, Any],
) -> dict[str, Any] | None:
    scene = next((item for item in project.get("scenes", []) if int(item.get("order", 0)) == scene_order), None)
    if scene is None:
        raise KeyError(f"Scene {scene_order} not found")
    directory = _scene_snapshot_dir(project_id, scene["scene_id"])
    if not directory.exists():
        return None
    skip_actions = skip_actions or set()
    paths = sorted(directory.glob("*.json"), key=lambda item: item.stat().st_mtime_ns, reverse=True)
    for path in paths:
        try:
            snapshot = load_json(path)
        except Exception:
            continue
        if snapshot.get("action") in skip_actions:
            continue
        return snapshot
    return None


def latest_scene_snapshot(project_id: str, scene_order: int, skip_actions: set[str] | None = None) -> dict[str, Any] | None:
    with project_lock(project_id):
        project = load_project(project_id)
        return _latest_scene_snapshot_locked(project_id, scene_order, skip_actions, project)


def restore_scene_snapshot(project_id: str, scene_order: int) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        scene = next((item for item in project.get("scenes", []) if int(item.get("order", 0)) == scene_order), None)
        if scene is None:
            raise KeyError(f"Scene {scene_order} not found")
        _capture_scene_snapshot_locked(project_id, scene_order, "restore-backup", project)
        snapshot = _latest_scene_snapshot_locked(project_id, scene_order, {"restore-backup"}, project)
        if snapshot is None:
            raise FileNotFoundError("No snapshot available")
        if snapshot.get("action") in {"split", "merge"} and isinstance(snapshot.get("scenes"), list):
            project["scenes"] = deepcopy(snapshot["scenes"])
            _renumber_scenes(project)
            apply_project_episode_pacing(project, force=True)
            _mark_output_stale(project)
            _append_scene_history(
                project,
                scene_order,
                "restore",
                "done",
                f"鍥炴粴鍒颁笂涓€涓増鏈細{snapshot.get('captured_at', '')}",
            )
            return _save_project_with_structure_event(project, "restore", scene_order)
        restored = snapshot.get("scene") or {}
        for key, value in restored.items():
            if key in {"scene_id", "order", "history"}:
                continue
            scene[key] = deepcopy(value)
        _append_scene_history(
            project,
            scene_order,
            "restore",
            "done",
            f"回滚到上一个版本：{snapshot.get('captured_at', '')}",
        )
        return _save_project_with_structure_event(project, "restore", scene_order)


def _append_scene_history(
    project: dict[str, Any],
    scene_order: int,
    action: str,
    status: str,
    message: str,
) -> dict[str, Any]:
    scene = next((item for item in project.get("scenes", []) if int(item.get("order", 0)) == scene_order), None)
    if scene is None:
        raise KeyError(f"Scene {scene_order} not found")
    history = _scene_history(scene)
    history.insert(
        0,
        {
            "ts": utc_iso(),
            "action": action,
            "label": SCENE_ACTION_LABELS.get(action, action),
            "status": status,
            "message": message,
        },
    )
    del history[SCENE_HISTORY_LIMIT:]
    return project


def append_scene_history(project_id: str, scene_order: int, action: str, status: str, message: str) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        _append_scene_history(project, scene_order, action, status, message)
        return _save_project_with_scene_event(project, scene_order)


def scene_latest_path(project_id: str, scene: dict[str, Any], kind: str) -> Path | None:
    assets = _scene_assets(scene)
    relative = assets.get(f"{kind}_path") or ""
    if not relative:
        return None
    return project_relative_path(project_id, relative)


def scene_asset_file_exists(project_id: str, scene: dict[str, Any], kind: str) -> bool:
    try:
        path = scene_latest_path(project_id, scene, kind)
    except ValueError:
        return False
    return bool(path and path.is_file())


def fallback_scene_clip_path(project_id: str, scene: dict[str, Any]) -> Path:
    return scene_dir(project_id, scene["scene_id"]) / "clip.mp4"


def _export_issue_item(scene: dict[str, Any], missing: list[str]) -> dict[str, Any]:
    return {
        "order": int(scene.get("order") or 0),
        "scene_id": str(scene.get("scene_id") or ""),
        "title": str(scene.get("title") or ""),
        "missing": missing,
    }


def validate_export_assets(project_id: str, scenes: list[dict[str, Any]]) -> None:
    items: list[dict[str, Any]] = []
    totals = {"image": 0, "audio": 0, "video": 0}
    if not scenes:
        raise ExportAssetReadinessError(
            {
                "code": "EXPORT_ASSET_NOT_READY",
                "message": "导出前素材未就绪",
                "items": [],
                "totals": totals,
            }
        )
    for scene in scenes:
        missing: list[str] = []
        if not scene_asset_file_exists(project_id, scene, "image"):
            missing.append("image")
        try:
            clip_path = scene_latest_path(project_id, scene, "video")
        except ValueError:
            clip_path = None
        has_video = bool(clip_path and clip_path.is_file()) or fallback_scene_clip_path(project_id, scene).is_file()
        if not has_video:
            missing.append("video")
        if str(scene.get("dialogue") or "").strip():
            if not scene_asset_file_exists(project_id, scene, "audio"):
                missing.append("audio")
        if missing:
            for kind in missing:
                totals[kind] += 1
            items.append(_export_issue_item(scene, missing))
    if items:
        raise ExportAssetReadinessError(
            {
                "code": "EXPORT_ASSET_NOT_READY",
                "message": "导出前素材未就绪",
                "items": items,
                "totals": totals,
            }
        )


def _set_runtime(project: dict[str, Any], **updates: Any) -> dict[str, Any]:
    runtime = project.setdefault("runtime", {})
    runtime.update(updates)
    runtime["updated_at"] = utc_iso()
    return project


def update_runtime(project_id: str, **updates: Any) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        _set_runtime(project, **updates)
        return _save_project_with_project_event(project)


def _update_scene(project: dict[str, Any], scene_order: int, updates: dict[str, Any]) -> dict[str, Any]:
    for scene in project.get("scenes", []):
        if int(scene.get("order", 0)) != scene_order:
            continue
        scene.update({key: value for key, value in updates.items() if value is not None})
        apply_director_recommendation(scene)
        break
    return project


IMAGE_STALE_FIELDS = {"title", "visual_prompt", "emotion", "characters"}
AUDIO_STALE_FIELDS = {
    "dialogue",
    "speaker",
    "voice_profile",
    "voice_engine",
    "voice_id",
    "reference_audio_path",
    "reference_text",
    "voice_rate",
    "voice_pitch",
    "voice_volume",
}
VIDEO_STALE_FIELDS = {
    "camera_movement",
    "duration_seconds",
    "rhythm_preset",
    "sfx_type",
    "audio_manifest",
    "subtitle_preset",
    "camera_intensity",
    "camera_speed",
    "shot_overrides",
    "episode_rhythm",
    "episode_phase",
    "episode_phase_index",
    "episode_phase_total",
    "crop_box",
}


def _changed_scene_fields(scene: dict[str, Any], updates: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    for key, value in updates.items():
        if value is None:
            continue
        if scene.get(key) != value:
            changed.append(key)
    return changed


def _invalidate_scene_assets(scene: dict[str, Any], changed_fields: list[str]) -> None:
    changed = set(changed_fields)
    stale: set[str] = set()
    if changed & IMAGE_STALE_FIELDS:
        stale.update({"image", "video"})
    if changed & AUDIO_STALE_FIELDS:
        stale.update({"audio", "video"})
    if changed & VIDEO_STALE_FIELDS:
        stale.add("video")
    if not stale:
        return

    assets = _scene_assets(scene)
    versions = assets.setdefault("versions", {"image": 0, "audio": 0, "video": 0})
    for kind in stale:
        assets[f"{kind}_path"] = ""
        assets[f"{kind}_url"] = ""
        if isinstance(versions, dict):
            versions[kind] = 0
    assets["status"] = "pending"


def _scene_uses_character(scene: dict[str, Any], *names: object) -> bool:
    wanted = {_normalized_key(name) for name in names if _normalized_key(name)}
    if not wanted:
        return False
    scene_names = {
        _normalized_key(scene.get("speaker")),
        *{_normalized_key(name) for name in scene.get("characters") or []},
    }
    return bool(wanted & scene_names)


def _invalidate_character_scenes(project: dict[str, Any], character: dict[str, Any], changed_fields: list[str], *extra_names: object) -> None:
    names = [character.get("name"), *extra_names]
    changed_any = False
    for scene in project.get("scenes", []):
        if not _scene_uses_character(scene, *names):
            continue
        _invalidate_scene_assets(scene, changed_fields)
        changed_any = True
    if changed_any:
        _mark_output_stale(project)


def _blank_assets() -> dict[str, Any]:
    return {
        "status": "pending",
        "versions": {"image": 0, "audio": 0, "video": 0},
        "image_path": "",
        "image_url": "",
        "audio_path": "",
        "audio_url": "",
        "video_path": "",
        "video_url": "",
    }


def _mark_output_stale(project: dict[str, Any]) -> None:
    output = project.setdefault("output", {})
    for key in {"final_video_path", "final_video_url", "subtitles_path", "subtitles_url", "subtitles_ass_path", "subtitles_ass_url"}:
        output[key] = ""
    output["status"] = "stale"


def update_project_fields(project_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        for key, value in updates.items():
            if value is None:
                continue
            if key in {"title", "story_text"}:
                if key == "story_text" and isinstance(value, str):
                    current_story = str(project.get("story_text") or "")
                    if value != current_story and is_script_text_garbled(value):
                        raise ValueError("剧本文本疑似编码损坏：请重新从原始来源粘贴，不要使用已经变成 ? 的内容。")
                project[key] = value
            elif key == "style_id":
                project["style_id"] = str(value).strip()
            elif key == "settings" and isinstance(value, dict):
                settings = project.setdefault("settings", {})
                for setting_key, setting_value in value.items():
                    if setting_key == "subtitle_style" and isinstance(setting_value, dict):
                        current_style = settings.get("subtitle_style") if isinstance(settings.get("subtitle_style"), dict) else {}
                        settings["subtitle_style"] = normalize_subtitle_style({**current_style, **setting_value})
                    elif setting_key == "audio_style" and isinstance(setting_value, dict):
                        current_style = settings.get("audio_style") if isinstance(settings.get("audio_style"), dict) else {}
                        settings["audio_style"] = normalize_audio_style({**current_style, **setting_value})
                    elif setting_key == "episode_pacing" and isinstance(setting_value, dict):
                        current_pacing = settings.get("episode_pacing") if isinstance(settings.get("episode_pacing"), dict) else {}
                        settings["episode_pacing"] = normalize_episode_pacing({**current_pacing, **setting_value})
                    else:
                        settings[setting_key] = setting_value
            elif key == "characters" and isinstance(value, list):
                project["characters"] = value
        apply_project_episode_pacing(project, force=True)
        return _save_project_with_project_event(project)


def update_character_fields(project_id: str, char_index: int, updates: dict[str, Any]) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        characters = project.get("characters", [])
        if char_index < 1 or char_index > len(characters):
            raise KeyError(f"Character {char_index} not found")
        character = characters[char_index - 1]
        previous_name = character.get("name")
        changed_fields: list[str] = []
        for key, value in updates.items():
            if value is None:
                continue
            if key in {
                "name",
                "description",
                "meta",
                "appearance_core",
                "clothing_style",
                "negative_constraints",
                "voice_profile",
                "voice_engine",
                "voice_id",
                "reference_audio_path",
                "reference_text",
                "emotion",
                "voice_rate",
                "voice_pitch",
                "voice_volume",
            }:
                if character.get(key) != value:
                    changed_fields.append(key)
                character[key] = value
        visual_fields = {"name", "description", "meta", "appearance_core", "clothing_style", "negative_constraints"}
        voice_fields = AUDIO_STALE_FIELDS & set(changed_fields)
        invalidate_fields: list[str] = []
        if visual_fields & set(changed_fields):
            invalidate_fields.append("characters")
        if voice_fields:
            invalidate_fields.append("voice_id")
        if invalidate_fields:
            _invalidate_character_scenes(project, character, invalidate_fields, previous_name)
        return _save_project_with_project_event(project)


def update_scene_fields(project_id: str, scene_order: int, updates: dict[str, Any]) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        updates = normalize_scene_pacing_update(updates)
        scene = next((item for item in project.get("scenes", []) if int(item.get("order", 0)) == scene_order), None)
        if scene is None:
            raise KeyError(f"Scene {scene_order} not found")
        before_scene = deepcopy(scene)
        _capture_scene_snapshot_locked(project_id, scene_order, "edit", project)
        _update_scene(project, scene_order, updates)
        tracked_fields = set(updates) | {
            "camera_movement",
            "camera_speed",
            "audio_manifest",
            "sfx_type",
            "director_recommendation",
        }
        changed = [
            key
            for key in sorted(tracked_fields)
            if (key not in updates or updates.get(key) is not None) and before_scene.get(key) != scene.get(key)
        ]
        _invalidate_scene_assets(scene, changed)
        if scene.get("validation_failed") and _scene_validation_resolved(scene):
            scene["validation_failed"] = False
            scene["error_message"] = ""
            scene["raw_llm_output"] = {}
            assets = _scene_assets(scene)
            if assets.get("status") == "failed":
                assets["status"] = "pending"
            changed.append("validation_failed")
        if set(changed) & (IMAGE_STALE_FIELDS | AUDIO_STALE_FIELDS | VIDEO_STALE_FIELDS):
            _mark_output_stale(project)
        if changed:
            _append_scene_history(project, scene_order, "edit", "saved", f"已保存字段：{', '.join(changed)}")
        return _save_project_with_scene_event(project, scene_order)


def _renumber_scenes(project: dict[str, Any]) -> None:
    used_scene_ids: set[str] = set()
    project_id = str(project.get("project_id") or "")
    existing_dir_ids = set()
    if project_id:
        scene_root = project_dir(project_id) / "scenes"
        if scene_root.exists():
            existing_dir_ids = {path.name for path in scene_root.iterdir() if path.is_dir()}
    existing_scene_ids = {
        str(scene.get("scene_id") or "")
        for scene in project.get("scenes", [])
        if str(scene.get("scene_id") or "").strip()
    }
    max_number = 0
    for value in existing_scene_ids | existing_dir_ids:
        if value.startswith("scene_"):
            try:
                max_number = max(max_number, int(value.split("_", 1)[1]))
            except (IndexError, ValueError):
                continue
    next_scene_number = max_number + 1

    def _next_scene_id() -> str:
        nonlocal next_scene_number
        while True:
            candidate = f"scene_{next_scene_number:03d}"
            next_scene_number += 1
            if candidate not in existing_scene_ids and candidate not in existing_dir_ids and candidate not in used_scene_ids:
                return candidate

    for index, scene in enumerate(project.get("scenes", []), start=1):
        scene["order"] = index
        scene_id = str(scene.get("scene_id") or "").strip()
        if not scene_id or scene_id in used_scene_ids:
            scene_id = _next_scene_id()
        scene["scene_id"] = scene_id
        used_scene_ids.add(scene_id)
    project.setdefault("settings", {})["scene_count"] = len(project.get("scenes", []))


def split_scene(project_id: str, scene_order: int) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        scenes = project.get("scenes", [])
        index = next((i for i, item in enumerate(scenes) if int(item.get("order", 0)) == scene_order), None)
        if index is None:
            raise KeyError(f"Scene {scene_order} not found")
        source = scenes[index]
        _capture_scene_snapshot_locked(project_id, scene_order, "split", project)

        duplicate = deepcopy(source)
        duplicate["title"] = f"{source.get('title') or '分镜'} B"
        duplicate["visual_prompt"] = str(source.get("visual_prompt") or "").strip()
        duplicate["dialogue"] = ""
        duplicate["assets"] = _blank_assets()
        duplicate["history"] = []
        try:
            original_duration = float(source.get("duration_seconds") or 4.0)
        except (TypeError, ValueError):
            original_duration = 4.0
        half_duration = max(1.0, round(original_duration / 2, 1))
        source["duration_seconds"] = half_duration
        duplicate["duration_seconds"] = half_duration
        _invalidate_scene_assets(source, ["duration_seconds"])
        scenes.insert(index + 1, duplicate)
        _renumber_scenes(project)
        apply_project_episode_pacing(project, force=True)
        _mark_output_stale(project)
        _append_scene_history(project, scene_order, "split", "saved", "已拆成两个分镜")
        _set_runtime(project, status="idle", progress=0, stage="draft", message="Scene split")
        return _save_project_with_structure_event(project, "split", scene_order)


def merge_scene_with_next(project_id: str, scene_order: int) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        scenes = project.get("scenes", [])
        index = next((i for i, item in enumerate(scenes) if int(item.get("order", 0)) == scene_order), None)
        if index is None or index >= len(scenes) - 1:
            raise KeyError(f"Scene {scene_order} has no next scene")
        current = scenes[index]
        following = scenes[index + 1]
        _capture_scene_snapshot_locked(project_id, scene_order, "merge", project)

        current["title"] = " / ".join(
            part for part in [str(current.get("title") or "").strip(), str(following.get("title") or "").strip()] if part
        )[:80]
        current["visual_prompt"] = "\n".join(
            part
            for part in [str(current.get("visual_prompt") or "").strip(), str(following.get("visual_prompt") or "").strip()]
            if part
        )
        current["dialogue"] = "\n".join(
            part for part in [str(current.get("dialogue") or "").strip(), str(following.get("dialogue") or "").strip()] if part
        )
        current["characters"] = list(dict.fromkeys([*(current.get("characters") or []), *(following.get("characters") or [])]))
        try:
            current["duration_seconds"] = round(float(current.get("duration_seconds") or 0) + float(following.get("duration_seconds") or 0), 1)
        except (TypeError, ValueError):
            current["duration_seconds"] = 6.0
        current["assets"] = _blank_assets()
        current.setdefault("history", [])
        scenes.pop(index + 1)
        _renumber_scenes(project)
        apply_project_episode_pacing(project, force=True)
        _mark_output_stale(project)
        _append_scene_history(project, scene_order, "merge", "saved", "已合并下一个分镜")
        _set_runtime(project, status="idle", progress=0, stage="draft", message="Scene merged")
        return _save_project_with_structure_event(project, "merge", scene_order)


def update_scene_asset(project_id: str, scene_order: int, kind: str, source_path: Path) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        scene = next((item for item in project.get("scenes", []) if int(item.get("order", 0)) == scene_order), None)
        if scene is None:
            raise KeyError(f"Scene {scene_order} not found")

        assets = _scene_assets(scene)
        scene_id = scene["scene_id"]
        directory = scene_dir(project_id, scene_id)
        suffix = {"image": ".png", "audio": ".wav", "video": ".mp4"}[kind]
        prefix = {"image": "image", "audio": "audio", "video": "video"}[kind]
        target = next_version_path(directory, prefix, suffix)
        shutil.copy2(source_path, target)
        relative = str(target.relative_to(project_dir(project_id))).replace("\\", "/")
        assets[f"{kind}_path"] = relative
        assets[f"{kind}_url"] = workspace_url(project_id, relative)
        versions = assets.setdefault("versions", {"image": 0, "audio": 0, "video": 0})
        if isinstance(versions, dict):
            versions[kind] = int(versions.get(kind, 0)) + 1
        has_dialogue = bool(str(scene.get("dialogue") or "").strip())
        has_required_audio = (not has_dialogue) or scene_asset_file_exists(project_id, scene, "audio")
        assets["status"] = (
            "completed"
        if scene_asset_file_exists(project_id, scene, "image")
        and scene_asset_file_exists(project_id, scene, "video")
        and has_required_audio
        else "pending"
        )
        return _save_project_with_scene_event(project, scene_order)


def update_scene_consistency_meta(
    project_id: str,
    scene_order: int,
    consistency_meta: dict[str, Any] | None,
    primary_reference_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        scene = next((item for item in project.get("scenes", []) if int(item.get("order", 0)) == scene_order), None)
        if scene is None:
            raise KeyError(f"Scene {scene_order} not found")
        scene["consistency_meta"] = deepcopy(consistency_meta) if isinstance(consistency_meta, dict) else {}
        if isinstance(primary_reference_meta, dict):
            scene["primary_reference_meta"] = deepcopy(primary_reference_meta)
        return _save_project_with_scene_event(project, scene_order)


def sync_scene_duration(project_id: str, scene_order: int, duration_seconds: float) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        scene = next((item for item in project.get("scenes", []) if int(item.get("order", 0)) == scene_order), None)
        if scene is None:
            raise KeyError(f"Scene {scene_order} not found")
        normalized = max(0.25, round(float(duration_seconds), 1))
        current = float(scene.get("duration_seconds") or 0.0)
        if abs(current - normalized) < 0.05:
            return project
        scene["duration_seconds"] = normalized
        _invalidate_scene_assets(scene, ["duration_seconds"])
        return _save_project_with_scene_event(project, scene_order)


def update_character_reference_image(project_id: str, char_index: int, source_path: Path) -> dict[str, Any]:
    validate_reference_image(source_path)
    with project_lock(project_id):
        project = load_project(project_id)
        characters = project.get("characters", [])
        if char_index < 1 or char_index > len(characters):
            raise KeyError(f"Character {char_index} not found")
        character = characters[char_index - 1]
        directory = project_dir(project_id) / "characters" / character["char_id"]
        directory.mkdir(parents=True, exist_ok=True)
        original = directory / "reference_original.png"
        processed = directory / "reference_processed.png"
        if processed.exists():
            processed.unlink()
        if source_path.resolve() != original.resolve():
            shutil.copy2(source_path, original)
        else:
            original = source_path
        result = preprocess_reference_image(original, processed)
        original_relative = str(original.relative_to(project_dir(project_id))).replace("\\", "/")
        character["reference_original_path"] = original_relative
        character["reference_original_url"] = workspace_url(project_id, original_relative)
        if result.get("ok"):
            relative = str(processed.relative_to(project_dir(project_id))).replace("\\", "/")
            character["reference_image_path"] = relative
            character["reference_image_url"] = workspace_url(project_id, relative)
            character["reference_meta"] = {
                "crop_method": result.get("crop_method") or "center_fallback",
                "face_box": result.get("face_box"),
                "crop_box": result.get("crop_box"),
                "output_size": result.get("output_size") or [512, 512],
                "warnings": list(result.get("warnings") or []),
            }
        else:
            character["reference_image_path"] = ""
            character["reference_image_url"] = ""
            character["reference_meta"] = {
                "crop_method": "failed",
                "face_box": None,
                "crop_box": None,
                "output_size": result.get("output_size") or [0, 0],
                "warnings": list(result.get("warnings") or []),
            }
        _invalidate_character_scenes(project, character, ["characters"])
        return _save_project_with_project_event(project)


def validate_reference_image(path: Path) -> None:
    try:
        with Image.open(path) as image:
            width, height = image.size
            if width < 128 or height < 128:
                raise ValueError("Reference image is too small. Use an image at least 128x128.")
            thumb = image.convert("RGB")
            thumb.thumbnail((96, 96))
            pixels = list(thumb.getdata())
            color_bins = {(r // 32, g // 32, b // 32) for r, g, b in pixels}
            channel_ranges = [max(channel) - min(channel) for channel in zip(*pixels)]
            max_stddev = max(ImageStat.Stat(thumb).stddev)
    except UnidentifiedImageError as exc:
        raise ValueError("Uploaded file is not a readable image.") from exc

    if len(color_bins) < 8 or max(channel_ranges) < 24 or max_stddev < 10:
        raise ValueError("Reference image has too little visual detail. Upload a real character image, not a flat placeholder.")


def write_data_url_image(project_id: str, filename: str, data_url: str) -> Path:
    if "," not in data_url:
        raise ValueError("Invalid data URL")
    header, encoded = data_url.split(",", 1)
    if "base64" not in header:
        raise ValueError("Only base64 data URLs are supported")
    try:
        raw = base64.b64decode(encoded)
    except binascii.Error as exc:
        raise ValueError("Invalid base64 payload") from exc
    suffix = Path(filename or "upload.png").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    out = project_dir(project_id) / "characters" / f"upload_{uuid.uuid4().hex[:8]}{suffix}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    try:
        validate_reference_image(out)
    except ValueError:
        out.unlink(missing_ok=True)
        raise
    return out


def rerender_scene_image(project_id: str, scene_order: int) -> dict[str, Any]:
    load_env_file()
    try:
        with project_lock(project_id):
            project = load_project(project_id)
            scene = next((item for item in project.get("scenes", []) if int(item.get("order", 0)) == scene_order), None)
            if scene is None:
                raise KeyError(f"Scene {scene_order} not found")
            _ensure_scene_renderable(scene, scene_order)
            settings = project.get("settings", {})
            keyframe_provider = str(settings.get("keyframe_provider") or "auto")
            apply_project_episode_pacing(project)
            scene_obj = _scene_from_payload(scene_with_character_context(project, scene))
            directory = scene_dir(project_id, scene["scene_id"])
            directory.mkdir(parents=True, exist_ok=True)
            _capture_scene_snapshot_locked(project_id, scene_order, "rerender-image", project)
            _append_scene_history(project, scene_order, "rerender-image", "running", "开始重绘图")
            _save_project_with_scene_event(project, scene_order)
        image_path = generate_keyframe(scene_obj, directory, keyframe_provider)
        if getattr(scene_obj, "consistency_meta", None):
            update_scene_consistency_meta(project_id, scene_order, scene_obj.consistency_meta, scene_obj.primary_reference_meta)
        result = update_scene_asset(project_id, scene_order, "image", image_path)
        with project_lock(project_id):
            project = load_project(project_id)
            _append_scene_history(project, scene_order, "rerender-image", "done", "重绘图完成")
            _save_project_with_scene_event(project, scene_order)
        return result
    except Exception as exc:
        if "scene_obj" in locals() and getattr(scene_obj, "consistency_meta", None):
            try:
                update_scene_consistency_meta(project_id, scene_order, scene_obj.consistency_meta, scene_obj.primary_reference_meta)
            except Exception as meta_exc:
                print(f"[consistency] failed to persist scene meta for {project_id}#{scene_order}: {meta_exc}")
        with project_lock(project_id):
            project = load_project(project_id)
            _append_scene_history(project, scene_order, "rerender-image", "failed", f"重绘图失败：{exc}")
            _save_project_with_scene_event(project, scene_order)
        raise


def rerender_scene_audio(project_id: str, scene_order: int) -> dict[str, Any]:
    load_env_file()
    ffmpeg = get_ffmpeg_exe()
    try:
        with project_lock(project_id):
            project = load_project(project_id)
            scene = next((item for item in project.get("scenes", []) if int(item.get("order", 0)) == scene_order), None)
            if scene is None:
                raise KeyError(f"Scene {scene_order} not found")
            _ensure_scene_renderable(scene, scene_order)
            settings = project.get("settings", {})
            voice_provider = str(settings.get("voice_provider") or "auto")
            subtitle_style = project_subtitle_style(project)
            audio_style = project_audio_style(project)
            apply_project_episode_pacing(project)
            scene_obj = _scene_from_payload(scene_with_character_context(project, scene))
            directory = scene_dir(project_id, scene["scene_id"])
            directory.mkdir(parents=True, exist_ok=True)
            _capture_scene_snapshot_locked(project_id, scene_order, "rerender-audio", project)
            _append_scene_history(project, scene_order, "rerender-audio", "running", "开始重配音")
            _save_project_with_scene_event(project, scene_order)
        voice_path, _ = render_voice_track(
            ffmpeg,
            scene_obj,
            directory,
            voice_provider,
            subtitle_style=subtitle_style,
            audio_style=audio_style,
        )
        result = update_scene_asset(project_id, scene_order, "audio", voice_path)
        with project_lock(project_id):
            project = load_project(project_id)
            _append_scene_history(project, scene_order, "rerender-audio", "done", "重配音完成")
            _save_project_with_scene_event(project, scene_order)
        return result
    except Exception as exc:
        with project_lock(project_id):
            project = load_project(project_id)
            _append_scene_history(project, scene_order, "rerender-audio", "failed", f"重配音失败：{exc}")
            _save_project_with_scene_event(project, scene_order)
        raise


def rerender_scene_video(project_id: str, scene_order: int) -> dict[str, Any]:
    load_env_file()
    ffmpeg = get_ffmpeg_exe()
    try:
        with project_lock(project_id):
            project = load_project(project_id)
            scene = next((item for item in project.get("scenes", []) if int(item.get("order", 0)) == scene_order), None)
            if scene is None:
                raise KeyError(f"Scene {scene_order} not found")
            _ensure_scene_renderable(scene, scene_order)
            settings = project.get("settings", {})
            keyframe_provider = str(settings.get("keyframe_provider") or "auto")
            video_provider = str(settings.get("video_provider") or "auto")
            voice_provider = str(settings.get("voice_provider") or "auto")
            subtitle_style = project_subtitle_style(project)
            audio_style = project_audio_style(project)
            apply_project_episode_pacing(project)
            scene_obj = _scene_from_payload(scene_with_character_context(project, scene))
            directory = scene_dir(project_id, scene["scene_id"])
            directory.mkdir(parents=True, exist_ok=True)
            _capture_scene_snapshot_locked(project_id, scene_order, "rerender-video", project)
            _append_scene_history(project, scene_order, "rerender-video", "running", "开始重合成")
            _save_project_with_scene_event(project, scene_order)
        image_path = scene_latest_path(project_id, scene, "image")
        if image_path is None or not image_path.exists():
            image_path = generate_keyframe(scene_obj, directory, keyframe_provider)
            if getattr(scene_obj, "consistency_meta", None):
                update_scene_consistency_meta(project_id, scene_order, scene_obj.consistency_meta, scene_obj.primary_reference_meta)
            update_scene_asset(project_id, scene_order, "image", image_path)
        audio_path, _ = render_voice_track(
            ffmpeg,
            scene_obj,
            directory,
            voice_provider,
            subtitle_style=subtitle_style,
            audio_style=audio_style,
        )
        update_scene_asset(project_id, scene_order, "audio", audio_path)
        synced_duration = max(0.25, round(wav_duration(audio_path) if audio_path.exists() else scene_obj.duration, 1))
        sync_scene_duration(project_id, scene_order, synced_duration)
        scene_obj.duration = synced_duration
        clip_duration = max(scene_obj.duration, wav_duration(audio_path) if audio_path.exists() else scene_obj.duration)
        clip_path = render_clip(
            ffmpeg,
            scene_obj,
            directory,
            keyframe_provider,
            voice_provider,
            clip_duration,
            audio_path,
            subtitle_style,
            audio_style,
            project_dir(project_id),
            keyframe_path=image_path,
            video_provider=video_provider,
        )
        result = update_scene_asset(project_id, scene_order, "video", clip_path)
        with project_lock(project_id):
            project = load_project(project_id)
            _append_scene_history(project, scene_order, "rerender-video", "done", "重合成完成")
            _save_project_with_scene_event(project, scene_order)
        return result
    except Exception as exc:
        if "scene_obj" in locals() and getattr(scene_obj, "consistency_meta", None):
            try:
                update_scene_consistency_meta(project_id, scene_order, scene_obj.consistency_meta, scene_obj.primary_reference_meta)
            except Exception as meta_exc:
                print(f"[consistency] failed to persist scene meta for {project_id}#{scene_order}: {meta_exc}")
        with project_lock(project_id):
            project = load_project(project_id)
            _append_scene_history(project, scene_order, "rerender-video", "failed", f"重合成失败：{exc}")
            _save_project_with_scene_event(project, scene_order)
        raise


def export_project(project_id: str) -> dict[str, Any]:
    load_env_file()
    ffmpeg = get_ffmpeg_exe()
    with project_lock(project_id):
        project = load_project(project_id)
        scenes = list(project.get("scenes", []))
        subtitle_style = project_subtitle_style(project)
        validate_export_assets(project_id, scenes)
    clips: list[Path] = []
    subtitle_files: list[Path] = []
    clip_durations: list[float] = []
    for scene in scenes:
        try:
            clip_path = scene_latest_path(project_id, scene, "video")
        except ValueError as exc:
            raise ExportAssetReadinessError(
                {
                    "code": "EXPORT_ASSET_NOT_READY",
                    "message": "导出前素材未就绪",
                    "items": [],
                    "totals": {},
                    "error": str(exc),
                }
            ) from exc
        if clip_path is None or not clip_path.exists():
            clip_path = scene_dir(project_id, scene["scene_id"]) / "clip.mp4"
        if not clip_path.exists():
            raise FileNotFoundError(f"Missing scene video: {scene.get('scene_id')}")
        clips.append(clip_path)
        try:
            audio_path = scene_latest_path(project_id, scene, "audio")
        except ValueError:
            audio_path = None
        audio_duration = wav_duration(audio_path) if audio_path and audio_path.exists() else float(scene.get("duration_seconds") or 0.0)
        clip_durations.append(max(float(scene.get("duration_seconds") or 0.0), audio_duration))
        subtitle_files.append(scene_dir(project_id, scene["scene_id"]) / f"scene_{int(scene.get('order') or 1):02d}_dialogue.srt")

    output_dir = project_dir(project_id) / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    final_video = output_dir / "final_episode.mp4"
    final_subtitles = output_dir / "subtitles.srt"
    final_subtitles_ass = output_dir / "subtitles.ass"
    concat_file = output_dir / "concat.txt"
    local_clips: list[Path] = []
    for scene, clip in zip(scenes, clips):
        local_clip = output_dir / f"{scene['scene_id']}.mp4"
        shutil.copy2(clip, local_clip)
        local_clips.append(local_clip)
    lines = [f"file '{clip.name}'" for clip in local_clips]
    concat_file.write_text("\n".join(lines), encoding="utf-8")
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
        str(final_video),
    ]
    result = subprocess.run(cmd, cwd=output_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed while concatenating clips:\n{result.stderr}")
    stitch_scene_subtitles(
        subtitle_files,
        clip_durations,
        final_subtitles,
        fallback_scenes=[_scene_from_payload(scene_with_character_context(project, scene)) for scene in scenes],
        ass_path=final_subtitles_ass,
        subtitle_style=subtitle_style,
    )
    with project_lock(project_id):
        project = load_project(project_id)
        project["output"]["final_video_path"] = str(final_video.relative_to(project_dir(project_id))).replace("\\", "/")
        project["output"]["subtitles_path"] = str(final_subtitles.relative_to(project_dir(project_id))).replace("\\", "/")
        project["output"]["subtitles_ass_path"] = str(final_subtitles_ass.relative_to(project_dir(project_id))).replace("\\", "/")
        project["output"]["status"] = "completed"
        _set_runtime(project, status="ready", progress=100, stage="done", message="Export completed")
        _save_project_with_project_event(project)
        return project_snapshot(project)


def set_scene_status(project_id: str, scene_order: int, status: str) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        scene = next((item for item in project.get("scenes", []) if int(item.get("order", 0)) == scene_order), None)
        if scene is None:
            raise KeyError(f"Scene {scene_order} not found")
        scene.setdefault("assets", {})["status"] = status
        return _save_project_with_scene_event(project, scene_order)


def generate_scene_assets(project_id: str, scene_order: int) -> dict[str, Any]:
    load_env_file()
    ffmpeg = get_ffmpeg_exe()
    try:
        with project_lock(project_id):
            project = load_project(project_id)
            scene = next((item for item in project.get("scenes", []) if int(item.get("order", 0)) == scene_order), None)
            if scene is None:
                raise KeyError(f"Scene {scene_order} not found")
            _ensure_scene_renderable(scene, scene_order)
            settings = project.get("settings", {})
            keyframe_provider = str(settings.get("keyframe_provider") or "auto")
            video_provider = str(settings.get("video_provider") or "auto")
            voice_provider = str(settings.get("voice_provider") or "auto")
            subtitle_style = project_subtitle_style(project)
            audio_style = project_audio_style(project)
            apply_project_episode_pacing(project)
            scene_obj = _scene_from_payload(scene_with_character_context(project, scene))
            directory = scene_dir(project_id, scene["scene_id"])
            directory.mkdir(parents=True, exist_ok=True)
            _capture_scene_snapshot_locked(project_id, scene_order, "rebuild", project)
            _append_scene_history(project, scene_order, "rebuild", "running", "开始整格重跑")
            _save_project_with_scene_event(project, scene_order)

        image_path = generate_keyframe(scene_obj, directory, keyframe_provider)
        if getattr(scene_obj, "consistency_meta", None):
            update_scene_consistency_meta(project_id, scene_order, scene_obj.consistency_meta, scene_obj.primary_reference_meta)
        update_scene_asset(project_id, scene_order, "image", image_path)

        voice_path, voice_duration = render_voice_track(
            ffmpeg,
            scene_obj,
            directory,
            voice_provider,
            subtitle_style=subtitle_style,
            audio_style=audio_style,
        )
        update_scene_asset(project_id, scene_order, "audio", voice_path)

        clip_duration = max(scene_obj.duration, voice_duration)
        clip_path = render_clip(
            ffmpeg,
            scene_obj,
            directory,
            keyframe_provider,
            voice_provider,
            clip_duration,
            voice_path,
            subtitle_style,
            audio_style,
            project_dir(project_id),
            keyframe_path=image_path,
            video_provider=video_provider,
        )
        update_scene_asset(project_id, scene_order, "video", clip_path)
        with project_lock(project_id):
            project = load_project(project_id)
            _append_scene_history(project, scene_order, "rebuild", "done", "整格重跑完成")
            _save_project_with_scene_event(project, scene_order)
        return load_project(project_id)
    except Exception as exc:
        if "scene_obj" in locals() and getattr(scene_obj, "consistency_meta", None):
            try:
                update_scene_consistency_meta(project_id, scene_order, scene_obj.consistency_meta, scene_obj.primary_reference_meta)
            except Exception as meta_exc:
                print(f"[consistency] failed to persist scene meta for {project_id}#{scene_order}: {meta_exc}")
        with project_lock(project_id):
            project = load_project(project_id)
            _append_scene_history(project, scene_order, "rebuild", "failed", f"整格重跑失败：{exc}")
            _save_project_with_scene_event(project, scene_order)
        raise


def build_project(project_id: str) -> dict[str, Any]:
    load_env_file()
    ffmpeg = get_ffmpeg_exe()
    current_scene_order: int | None = None
    try:
        with project_lock(project_id):
            project = load_project(project_id)
            settings = project.get("settings", {})
            keyframe_provider = str(settings.get("keyframe_provider") or "auto")
            video_provider = str(settings.get("video_provider") or "auto")
            voice_provider = str(settings.get("voice_provider") or "auto")
            subtitle_style = project_subtitle_style(project)
            audio_style = project_audio_style(project)
            apply_project_episode_pacing(project)
            scene_payloads = [deepcopy(scene) for scene in project.get("scenes", [])]
            for payload in scene_payloads:
                _ensure_scene_renderable(payload, int(payload.get("order") or 0))
            scenes = [_scene_from_payload(scene_with_character_context(project, scene)) for scene in scene_payloads]
            _set_runtime(project, status="running", progress=5, stage="rendering", message="Rendering calibrated scenes")
            _save_project_with_project_event(project)

        if not scenes:
            raise ValueError("Project has no scenes to render")

        built_clips: list[Path] = []
        subtitle_files: list[Path] = []
        clip_durations: list[float] = []
        total = max(1, len(scenes))
        for index, scene_obj in enumerate(scenes, start=1):
            current_scene_order = index
            with project_lock(project_id):
                project = load_project(project_id)
                _set_runtime(
                    project,
                    status="running",
                    progress=int(((index - 1) / total) * 85) + 5,
                    stage=f"scene_{index:03d}",
                    message=f"Rendering scene {index}/{total}",
                )
                _save_project_with_project_event(project)

            scene_dir_path = scene_dir(project_id, f"scene_{index:03d}")
            scene_dir_path.mkdir(parents=True, exist_ok=True)
            image_path = generate_keyframe(scene_obj, scene_dir_path, keyframe_provider)
            if getattr(scene_obj, "consistency_meta", None):
                update_scene_consistency_meta(project_id, current_scene_order, scene_obj.consistency_meta, scene_obj.primary_reference_meta)
            voice_path, voice_duration = render_voice_track(
                ffmpeg,
                scene_obj,
                scene_dir_path,
                voice_provider,
                subtitle_style=subtitle_style,
                audio_style=audio_style,
            )
            synced_duration = max(0.25, round(float(voice_duration), 1))
            sync_scene_duration(project_id, current_scene_order, synced_duration)
            scene_obj.duration = synced_duration
            clip_duration = max(scene_obj.duration, voice_duration)
            subtitle_path = scene_dir_path / f"scene_{index:02d}_dialogue.srt"
            clip_path = render_clip(
                ffmpeg,
                scene_obj,
                scene_dir_path,
                keyframe_provider,
                voice_provider,
                clip_duration,
                voice_path,
                subtitle_style,
                audio_style,
                project_dir(project_id),
                keyframe_path=image_path,
                video_provider=video_provider,
            )
            update_scene_asset(project_id, current_scene_order, "image", image_path)
            update_scene_asset(project_id, current_scene_order, "audio", voice_path)
            update_scene_asset(project_id, current_scene_order, "video", clip_path)
            subtitle_files.append(subtitle_path)
            clip_durations.append(clip_duration)
            with project_lock(project_id):
                project = load_project(project_id)
                _append_scene_history(project, current_scene_order, "build", "done", f"整集生成完成：{index}/{total}")
                _save_project_with_scene_event(project, current_scene_order)
            built_clips.append(clip_path)

        output_dir = project_dir(project_id) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        final_video = output_dir / "final_episode.mp4"
        final_subtitles = output_dir / "subtitles.srt"
        final_subtitles_ass = output_dir / "subtitles.ass"
        concat_file = output_dir / "concat.txt"
        local_clips: list[Path] = []
        for scene, clip in zip(scenes, built_clips):
            local_clip = output_dir / f"scene_{scene.scene:03d}.mp4"
            shutil.copy2(clip, local_clip)
            local_clips.append(local_clip)
        lines = [f"file '{clip.name}'" for clip in local_clips]
        concat_file.write_text("\n".join(lines), encoding="utf-8")
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
            str(final_video),
        ]
        result = subprocess.run(cmd, cwd=output_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed while concatenating clips:\n{result.stderr}")
        stitch_scene_subtitles(
            subtitle_files,
            clip_durations,
            final_subtitles,
            fallback_scenes=scenes,
            ass_path=final_subtitles_ass,
            subtitle_style=subtitle_style,
        )

        with project_lock(project_id):
            project = load_project(project_id)
            project["output"]["final_video_path"] = str(final_video.relative_to(project_dir(project_id))).replace("\\", "/")
            project["output"]["subtitles_path"] = str(final_subtitles.relative_to(project_dir(project_id))).replace("\\", "/")
            project["output"]["subtitles_ass_path"] = str(final_subtitles_ass.relative_to(project_dir(project_id))).replace("\\", "/")
            project["output"]["status"] = "completed"
            _set_runtime(project, status="ready", progress=100, stage="done", message="Completed")
            _save_project_with_project_event(project)
            return project_snapshot(project)
    except Exception as exc:
        if current_scene_order is not None and "scene_obj" in locals() and getattr(scene_obj, "consistency_meta", None):
            try:
                update_scene_consistency_meta(project_id, current_scene_order, scene_obj.consistency_meta, scene_obj.primary_reference_meta)
            except Exception as meta_exc:
                print(f"[consistency] failed to persist scene meta for {project_id}#{current_scene_order}: {meta_exc}")
        with project_lock(project_id):
            project = load_project(project_id)
            _set_runtime(project, status="failed", stage="failed", message="Build failed")
            if current_scene_order is not None:
                _append_scene_history(project, current_scene_order, "build", "failed", f"整集生成失败：{exc}")
            _save_project_with_project_event(project)
        raise
