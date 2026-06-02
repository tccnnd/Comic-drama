"""Data models, constants, and conversion utilities for the project runtime."""
from __future__ import annotations

import json
import shutil
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

try:
    import imageio_ffmpeg
except ImportError:  # pragma: no cover - optional runtime dependency
    imageio_ffmpeg = None

from scripts.run_workflow import (
    StoryScene,
    normalize_crop_box,
    normalize_episode_phase,
    normalize_episode_pacing,
    default_episode_pacing,
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


def _coerce_int_field(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


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


def scene_to_dict(scene: StoryScene, order: int) -> dict[str, Any]:
    """Convert a StoryScene to a project scene dict. Imports scene_graph functions lazily."""
    from backend.scene_graph import _scene_graph_payload, _apply_scene_graph

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
        from backend.scene_graph import apply_director_recommendation
        apply_director_recommendation(payload)
    graph = _scene_graph_payload(payload, order)
    _apply_scene_graph(payload, graph)
    return payload


def default_episode_pacing_config() -> dict[str, Any]:
    return normalize_episode_pacing(default_episode_pacing())
