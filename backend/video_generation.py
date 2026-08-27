"""Video generation orchestration with retry, fallback reporting, and cross-scene continuity.

This module wraps the existing render_clip pipeline to add:
1. Explicit retry logic for remote video providers (Kling, Sora, etc.)
2. Clear failure reporting instead of silent 2.5D fallback
3. Cross-scene frame continuity constraints (last-frame → first-frame bridging)
4. Generation metadata tracking for quality governance
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from backend.config_utils import env_bool as _env_bool, coerce_bool as _coerce_bool

try:
    from scripts.video_provider_adapters import render_remote_video_provider as _default_render_remote_video_provider
except Exception:  # pragma: no cover - adapter import is optional for pure helper tests
    _default_render_remote_video_provider = None

render_remote_video_provider = _default_render_remote_video_provider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_VIDEO_RETRIES = int(os.environ.get("VIDEO_MAX_RETRIES", "2"))
VIDEO_RETRY_DELAY_SECONDS = float(os.environ.get("VIDEO_RETRY_DELAY_SECONDS", "5.0"))
VIDEO_FALLBACK_MODE = os.environ.get("VIDEO_FALLBACK_MODE", "report").strip().lower()
# "report" = fall back to 2.5D but mark the scene with a warning
# "strict" = raise on failure, no fallback
# "silent" = original behavior, silent fallback (not recommended)
VIDEO_RENDER_GRANULARITY = os.environ.get("VIDEO_RENDER_GRANULARITY", "scene").strip().lower()
VIDEO_RENDER_GRANULARITIES = {"scene", "shot"}


@dataclass
class VideoGenerationResult:
    """Result of a single scene video generation attempt."""
    scene_order: int
    provider_id: str
    provider_label: str
    success: bool
    is_real_video: bool  # True if actual video generation, False if 2.5D fallback
    attempts: int
    duration_seconds: float
    output_path: str
    error: str = ""
    warnings: list[str] | None = None
    last_frame_path: str = ""  # For cross-scene continuity
    backend: str = ""
    fallback_used: bool = False


class VideoShotQuotaError(ValueError):
    """Raised when a planned shot-level render exceeds configured quota limits."""

    def __init__(self, detail: dict[str, Any]) -> None:
        self.detail = detail
        message = "; ".join(str(item) for item in detail.get("errors") or []) or "Shot-level render quota exceeded"
        super().__init__(message)


class VideoShotDryRun(RuntimeError):
    """Raised after a shot-level dry run is estimated and validated."""

    def __init__(self, detail: dict[str, Any]) -> None:
        self.detail = detail
        estimate = detail.get("estimate") if isinstance(detail, dict) else {}
        calls = estimate.get("provider_call_count") if isinstance(estimate, dict) else 0
        seconds = estimate.get("generated_seconds") if isinstance(estimate, dict) else 0
        super().__init__(f"Shot-level dry run completed: {calls} provider calls, {seconds} generated seconds.")


# ---------------------------------------------------------------------------
# Cross-scene continuity
# ---------------------------------------------------------------------------

def video_provider_strict_env_name(provider_id: str) -> str:
    """Return the provider-specific strict-mode environment variable name."""
    normalized = str(provider_id or "").strip().upper().replace("-", "_")
    return f"{normalized}_VIDEO_STRICT" if normalized else ""


def video_fallback_mode(provider_id: str = "") -> str:
    """Return the effective fallback policy for video generation."""
    if _env_bool("VIDEO_STRICT", default=False):
        return "strict"
    provider_strict_name = video_provider_strict_env_name(provider_id)
    if provider_strict_name and _env_bool(provider_strict_name, default=False):
        return "strict"
    mode = os.environ.get("VIDEO_FALLBACK_MODE", VIDEO_FALLBACK_MODE).strip().lower()
    if mode not in {"report", "strict", "silent"}:
        return "report"
    return mode


def normalize_video_render_granularity(value: object, *, default: str = "scene") -> str:
    """Normalize render granularity to ``scene`` or ``shot``."""
    normalized_default = str(default or "scene").strip().lower()
    if normalized_default not in VIDEO_RENDER_GRANULARITIES:
        normalized_default = "scene"
    normalized = str(value or "").strip().lower()
    if normalized in VIDEO_RENDER_GRANULARITIES:
        return normalized
    return normalized_default


def video_render_granularity(
    *,
    cli_value: object = None,
    request_value: object = None,
    project_settings: dict[str, Any] | None = None,
) -> str:
    """Resolve render granularity using CLI -> request -> project -> env -> scene."""
    for value in (
        cli_value,
        request_value,
        project_settings.get("video_render_granularity") if isinstance(project_settings, dict) else None,
        os.environ.get("VIDEO_RENDER_GRANULARITY", VIDEO_RENDER_GRANULARITY),
    ):
        normalized = str(value or "").strip().lower()
        if normalized:
            return normalize_video_render_granularity(normalized)
    return "scene"


def _first_config_value(
    key: str,
    env_name: str,
    *,
    request_values: dict[str, Any] | None = None,
    project_settings: dict[str, Any] | None = None,
) -> object:
    if isinstance(request_values, dict) and key in request_values:
        return request_values.get(key)
    if isinstance(project_settings, dict) and key in project_settings:
        return project_settings.get(key)
    return os.environ.get(env_name)


def _optional_positive_int(value: object) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _optional_positive_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0.0 else None


def video_shot_quota_config(
    *,
    request_values: dict[str, Any] | None = None,
    project_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve shot-level dry-run/quota settings without submitting jobs."""
    return {
        "max_calls": _optional_positive_int(
            _first_config_value(
                "video_shot_max_calls",
                "VIDEO_SHOT_MAX_CALLS",
                request_values=request_values,
                project_settings=project_settings,
            )
        ),
        "max_seconds": _optional_positive_float(
            _first_config_value(
                "video_shot_max_seconds",
                "VIDEO_SHOT_MAX_SECONDS",
                request_values=request_values,
                project_settings=project_settings,
            )
        ),
        "dry_run": _coerce_bool(
            _first_config_value(
                "video_shot_dry_run",
                "VIDEO_SHOT_DRY_RUN",
                request_values=request_values,
                project_settings=project_settings,
            ),
            default=False,
        ),
        "reuse_cache": _coerce_bool(
            _first_config_value(
                "video_shot_reuse_cache",
                "VIDEO_SHOT_REUSE_CACHE",
                request_values=request_values,
                project_settings=project_settings,
            ),
            default=False,
        ),
    }


def _shot_duration_seconds(shot: dict[str, Any]) -> float:
    return _coerce_non_negative_float(
        shot.get("duration_seconds") if isinstance(shot, dict) else 0.0
    )


def _shot_output_reusable(output: dict[str, Any]) -> bool:
    status = str(output.get("status") or "").strip().lower()
    if status not in {"real_video", "fallback", "skipped"}:
        return False
    return bool(str(output.get("path") or "").strip())


def _path_fingerprint(path: Path | str | None) -> dict[str, Any]:
    if path is None:
        return {}
    text = str(path or "")
    if not text:
        return {}
    payload: dict[str, Any] = {"path": text}
    try:
        path_obj = Path(text)
        stat = path_obj.stat()
        payload["size"] = int(stat.st_size)
        payload["mtime_ns"] = int(stat.st_mtime_ns)
    except (OSError, ValueError):
        pass
    return payload


def build_shot_cache_key(shot_request: dict[str, Any], keyframe_path: Path | str | None = None) -> str:
    """Build a stable cache key for one shot render request.

    The digest covers public render inputs only. It intentionally excludes raw
    provider responses, credentials, signed URLs, and output paths.
    """
    request = shot_request if isinstance(shot_request, dict) else {}
    provider = request.get("provider") if isinstance(request.get("provider"), dict) else {}
    payload = {
        "version": 1,
        "render_granularity": "shot",
        "scene_id": _clean_short_text(request.get("scene_id"), limit=120),
        "shot_id": _clean_short_text(request.get("shot_id"), limit=120),
        "shot_order": _coerce_non_negative_int(request.get("shot_order") or request.get("index")),
        "start_seconds": _coerce_non_negative_float(request.get("start_seconds")),
        "duration_seconds": _coerce_non_negative_float(request.get("duration_seconds")),
        "end_seconds": _coerce_non_negative_float(request.get("end_seconds")),
        "width": _coerce_non_negative_int(request.get("width") or 1080),
        "height": _coerce_non_negative_int(request.get("height") or 1920),
        "fps": _coerce_non_negative_int(request.get("fps") or 24),
        "prompt": _clean_short_text(request.get("prompt"), limit=6000),
        "negative_prompt": _clean_short_text(request.get("negative_prompt"), limit=2000),
        "camera": _compact_mapping(request.get("camera"), max_items=16, text_limit=500),
        "intent": _compact_mapping(request.get("intent"), max_items=16, text_limit=500),
        "visual_content": _compact_mapping(request.get("visual_content"), max_items=16, text_limit=500),
        "continuity": _compact_mapping(request.get("continuity"), max_items=16, text_limit=500),
        "temporal_spec": _compact_mapping(request.get("temporal_spec"), max_items=16, text_limit=500),
        "consistency_spec": _compact_mapping(request.get("consistency_spec"), max_items=16, text_limit=500),
        "characters": _compact_string_list(request.get("characters")),
        "provider_id": _clean_short_text(provider.get("provider_id"), limit=120),
        "provider_backend": _clean_short_text(provider.get("backend"), limit=120),
        "provider_model": _clean_short_text(provider.get("model"), limit=240),
        "keyframe": _path_fingerprint(keyframe_path),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"


def _shot_output_matches_cache(output: dict[str, Any], shot_request: dict[str, Any], keyframe_path: Path | str | None = None) -> bool:
    if not _shot_output_reusable(output):
        return False
    existing_key = str(output.get("cache_key") or "").strip()
    return bool(existing_key and existing_key == build_shot_cache_key(shot_request, keyframe_path))


def estimate_shot_render_quota(
    shot_plan: object,
    *,
    existing_shot_outputs: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    reuse_cache: bool = False,
) -> dict[str, Any]:
    """Estimate provider calls and generated seconds for a shot-level render."""
    shots = shot_plan.get("shots") if isinstance(shot_plan, dict) else []
    if not isinstance(shots, list):
        shots = []
    normalized_outputs: dict[str, dict[str, Any]] = {}
    if reuse_cache and isinstance(existing_shot_outputs, (list, tuple)):
        for index, raw_output in enumerate(existing_shot_outputs, start=1):
            output = _normalize_shot_output(raw_output, index)
            if output is None or not _shot_output_reusable(output):
                continue
            shot_id = str(output.get("shot_id") or "").strip()
            if shot_id:
                normalized_outputs[shot_id] = output

    planned_shots: list[dict[str, Any]] = []
    reused_shots: list[dict[str, Any]] = []
    provider_call_count = 0
    generated_seconds = 0.0
    target_seconds = 0.0

    for index, shot in enumerate(shots, start=1):
        if not isinstance(shot, dict):
            continue
        shot_id = str(shot.get("shot_id") or f"shot_{index:03d}").strip()
        duration = _shot_duration_seconds(shot)
        target_seconds += duration
        entry = {
            "shot_id": shot_id,
            "index": index,
            "duration_seconds": round(duration, 3),
        }
        if reuse_cache and shot_id in normalized_outputs:
            reused_shots.append(entry)
            continue
        planned_shots.append(entry)
        provider_call_count += 1
        generated_seconds += duration

    return {
        "render_granularity": "shot",
        "shot_count": len(planned_shots) + len(reused_shots),
        "provider_call_count": provider_call_count,
        "generated_seconds": round(generated_seconds, 3),
        "target_seconds": round(target_seconds, 3),
        "reused_shot_count": len(reused_shots),
        "planned_shots": planned_shots,
        "reused_shots": reused_shots,
    }


def validate_shot_render_quota(
    estimate: dict[str, Any],
    *,
    max_calls: int | None = None,
    max_seconds: float | None = None,
    dry_run: bool = False,
    raise_on_error: bool = True,
) -> dict[str, Any]:
    """Validate a shot-level quota estimate and optionally block over-limit runs."""
    provider_call_count = _coerce_non_negative_int(estimate.get("provider_call_count") if isinstance(estimate, dict) else 0)
    generated_seconds = _coerce_non_negative_float(estimate.get("generated_seconds") if isinstance(estimate, dict) else 0.0)
    errors: list[str] = []
    if max_calls is not None and provider_call_count > max_calls:
        errors.append(f"provider calls {provider_call_count} exceed VIDEO_SHOT_MAX_CALLS={max_calls}")
    if max_seconds is not None and generated_seconds > max_seconds:
        errors.append(f"generated seconds {generated_seconds:g} exceed VIDEO_SHOT_MAX_SECONDS={max_seconds:g}")
    result = {
        "ok": not errors,
        "dry_run": bool(dry_run),
        "errors": errors,
        "estimate": deepcopy(estimate) if isinstance(estimate, dict) else {},
        "limits": {
            "max_calls": max_calls,
            "max_seconds": max_seconds,
        },
    }
    if errors and raise_on_error:
        raise VideoShotQuotaError(result)
    return result


def _clean_short_text(value: object, *, limit: int = 500) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _first_non_empty_text(*values: object, limit: int = 240) -> str:
    for value in values:
        text = _clean_short_text(value, limit=limit)
        if text:
            return text
    return ""


def _compact_string_list(value: object, *, limit: int = 12) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    items: list[str] = []
    for item in value:
        text = _clean_short_text(item, limit=160)
        if text:
            items.append(text)
        if len(items) >= limit:
            break
    return items


def _compact_mapping(value: object, *, max_items: int = 16, text_limit: int = 500) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    compact: dict[str, Any] = {}
    for key, item in value.items():
        key_text = _clean_short_text(key, limit=80)
        if not key_text:
            continue
        if isinstance(item, dict):
            nested = _compact_mapping(item, max_items=8, text_limit=text_limit)
            if nested:
                compact[key_text] = nested
        elif isinstance(item, (list, tuple)):
            list_items: list[Any] = []
            for child in item[:8]:
                if isinstance(child, dict):
                    nested_child = _compact_mapping(child, max_items=8, text_limit=text_limit)
                    if nested_child:
                        list_items.append(nested_child)
                else:
                    child_text = _clean_short_text(child, limit=160)
                    if child_text:
                        list_items.append(child_text)
            if list_items:
                compact[key_text] = list_items
        else:
            text = _clean_short_text(item, limit=text_limit)
            if text:
                compact[key_text] = text
        if len(compact) >= max_items:
            break
    return compact


def _shot_text_summary(shot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(shot, dict):
        return {}
    visual_content = shot.get("visual_content") if isinstance(shot.get("visual_content"), dict) else {}
    camera_language = shot.get("camera_language") if isinstance(shot.get("camera_language"), dict) else {}
    summary = {
        "shot_id": _clean_short_text(shot.get("shot_id"), limit=120),
        "shot_order": _coerce_non_negative_int(shot.get("shot_order") or shot.get("index")),
        "label": _first_non_empty_text(shot.get("label"), shot.get("beat_type"), limit=160),
        "visual": _first_non_empty_text(
            visual_content.get("shot_description") if isinstance(visual_content, dict) else "",
            shot.get("visual"),
            shot.get("visual_prompt"),
            limit=360,
        ),
        "camera_movement": _first_non_empty_text(
            shot.get("camera_movement"),
            camera_language.get("movement") if isinstance(camera_language, dict) else "",
            limit=180,
        ),
    }
    return {key: value for key, value in summary.items() if value not in ("", 0)}


def _video_provider_env_model(provider_id: str) -> tuple[str, str]:
    normalized = str(provider_id or "").strip().lower()
    prefix = normalized.upper().replace("-", "_")
    names = [f"{prefix}_MODEL"] if prefix else []
    if normalized == "sora":
        names.append("OPENAI_VIDEO_MODEL")
    for name in names:
        value = _clean_short_text(os.environ.get(name), limit=240)
        if value:
            return value, f"env:{name}"
    return "", ""


def _video_model_from_mapping(mapping: dict[str, Any] | None, provider_id: str) -> tuple[str, str]:
    if not isinstance(mapping, dict):
        return "", ""
    normalized_provider = str(provider_id or "").strip().lower()
    for collection_key in ("video_provider_models", "video_models"):
        collection = mapping.get(collection_key)
        if isinstance(collection, dict):
            value = _clean_short_text(collection.get(normalized_provider), limit=240)
            if value:
                return value, collection_key
    for key in (
        "video_provider_model",
        "video_model",
        f"{normalized_provider}_model" if normalized_provider else "",
        f"{normalized_provider}_video_model" if normalized_provider else "",
    ):
        if not key:
            continue
        value = _clean_short_text(mapping.get(key), limit=240)
        if value:
            return value, key
    return "", ""


def _resolve_shot_provider_config(
    *,
    default_provider: str = "auto",
    project_settings: dict[str, Any] | None = None,
    scene: dict[str, Any],
    shot: dict[str, Any],
) -> dict[str, Any]:
    provider_id = _clean_short_text(default_provider or "auto", limit=120) or "auto"
    provider_source = "default"
    for source, mapping in (
        ("project", project_settings),
        ("scene", scene),
        ("shot", shot),
    ):
        if not isinstance(mapping, dict):
            continue
        candidate = _clean_short_text(mapping.get("video_provider"), limit=120)
        if candidate:
            provider_id = candidate
            provider_source = source

    provider_label = ""
    backend = ""
    try:
        from video_providers import get_video_provider_spec

        provider_spec = get_video_provider_spec(provider_id)
        provider_id = provider_spec.id
        provider_label = provider_spec.label
        backend = provider_spec.backend
    except Exception:
        provider_id = provider_id.strip().lower() or "local"

    model = ""
    model_source = ""
    for source, mapping in (
        ("project", project_settings),
        ("scene", scene),
        ("shot", shot),
    ):
        candidate, key = _video_model_from_mapping(mapping, provider_id)
        if candidate:
            model = candidate
            model_source = f"{source}:{key}"
    if not model:
        model, model_source = _video_provider_env_model(provider_id)

    return {
        "provider_id": provider_id,
        "provider_label": provider_label,
        "backend": backend,
        "provider_source": provider_source,
        "model": model,
        "model_source": model_source,
    }


def _visual_content_lines(visual_content: dict[str, Any], shot: dict[str, Any], scene: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if isinstance(visual_content, dict) and visual_content:
        lines.append("visual_content is the primary visual source")
        for key in (
            "_source",
            "shot_description",
            "foreground",
            "midground",
            "background",
            "composition",
            "motion",
            "lighting",
            "focus",
        ):
            text = _clean_short_text(visual_content.get(key), limit=500)
            if text:
                lines.append(f"{key}: {text}")
    else:
        fallback_visual = _first_non_empty_text(
            shot.get("visual_prompt"),
            shot.get("visual"),
            scene.get("visual_prompt"),
            scene.get("visual"),
            limit=800,
        )
        if fallback_visual:
            lines.append(f"scene_visual: {fallback_visual}")
    return lines


def _shot_camera_payload(shot: dict[str, Any], scene: dict[str, Any]) -> dict[str, Any]:
    camera_language = shot.get("camera_language") if isinstance(shot.get("camera_language"), dict) else {}
    payload = {
        "camera_movement": _first_non_empty_text(
            shot.get("camera_movement"),
            camera_language.get("movement") if isinstance(camera_language, dict) else "",
            scene.get("camera_movement"),
            scene.get("camera"),
            limit=180,
        ),
        "camera_speed": _coerce_non_negative_float(shot.get("camera_speed") or scene.get("camera_speed") or 1.0),
        "zoom": _coerce_non_negative_float(shot.get("zoom") or 1.0),
        "center_x": _coerce_non_negative_float(shot.get("center_x") if shot.get("center_x") is not None else 0.5),
        "center_y": _coerce_non_negative_float(shot.get("center_y") if shot.get("center_y") is not None else 0.5),
        "shot_size": _clean_short_text(shot.get("shot_size"), limit=160),
        "language": _compact_mapping(camera_language, max_items=8, text_limit=240),
    }
    return {key: value for key, value in payload.items() if value not in ("", {}, [])}


def _shot_intent_payload(shot: dict[str, Any], scene: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "beat_type": _clean_short_text(shot.get("beat_type"), limit=160),
        "dramatic_intent": _first_non_empty_text(shot.get("dramatic_intent"), scene.get("dramatic_intent"), limit=360),
        "scene_intent": _first_non_empty_text(shot.get("scene_intent"), scene.get("scene_intent"), limit=240),
        "subject_focus": _first_non_empty_text(shot.get("subject_focus"), scene.get("subject_focus"), limit=160),
        "emotion": _first_non_empty_text(shot.get("emotion"), scene.get("emotion_tone"), scene.get("emotion"), limit=160),
        "dialogue": _first_non_empty_text(shot.get("dialogue"), scene.get("dialogue"), limit=500),
        "speaker": _first_non_empty_text(shot.get("speaker"), scene.get("speaker"), limit=160),
    }
    return {key: value for key, value in payload.items() if value}


def _scene_continuity_payload(
    scene: dict[str, Any],
    *,
    previous_shot: dict[str, Any] | None = None,
    next_shot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bible = scene.get("production_bible") if isinstance(scene.get("production_bible"), dict) else {}
    current_scene = bible.get("current_scene") if isinstance(bible.get("current_scene"), dict) else {}
    active_characters = current_scene.get("active_characters") if isinstance(current_scene, dict) else []
    if not isinstance(active_characters, list) or not active_characters:
        active_characters = scene.get("characters") if isinstance(scene.get("characters"), list) else []
    payload = {
        "characters": deepcopy(active_characters) if isinstance(active_characters, list) else [],
        "location": _first_non_empty_text(
            scene.get("location"),
            current_scene.get("location") if isinstance(current_scene, dict) else "",
            current_scene.get("setting") if isinstance(current_scene, dict) else "",
            limit=240,
        ),
        "production_rules": _compact_mapping(bible.get("rules"), max_items=12, text_limit=240),
        "style": _first_non_empty_text(
            scene.get("style"),
            bible.get("visual_style") if isinstance(bible, dict) else "",
            limit=240,
        ),
        "previous_shot": _shot_text_summary(previous_shot),
        "next_shot": _shot_text_summary(next_shot),
    }
    return {key: value for key, value in payload.items() if value not in ("", {}, [])}


def _shot_prompt_text(
    *,
    scene: dict[str, Any],
    shot: dict[str, Any],
    camera: dict[str, Any],
    intent: dict[str, Any],
    continuity: dict[str, Any],
) -> str:
    scene_title = _first_non_empty_text(scene.get("title"), scene.get("scene_id"), limit=180)
    visual_content = shot.get("visual_content") if isinstance(shot.get("visual_content"), dict) else {}
    parts = [
        "Generate this planned shot as one continuous real video clip.",
        "Preserve shot boundaries; do not summarize the whole scene.",
    ]
    if scene_title:
        parts.append(f"scene_title: {scene_title}")
    parts.append(f"shot_id: {_clean_short_text(shot.get('shot_id'), limit=120)}")
    parts.append(
        "timing: "
        f"start={_coerce_non_negative_float(shot.get('start_seconds')):.3f}s, "
        f"duration={_coerce_non_negative_float(shot.get('duration_seconds')):.3f}s"
    )
    parts.extend(_visual_content_lines(visual_content, shot, scene))
    if camera:
        parts.append("camera: " + json.dumps(camera, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if intent:
        parts.append("intent: " + json.dumps(intent, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if continuity:
        parts.append("scene_continuity: " + json.dumps(continuity, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return "\n".join(part for part in parts if str(part).strip())


def _shot_negative_prompt(scene: dict[str, Any], shot: dict[str, Any]) -> str:
    parts = [
        "worst quality, low quality, normal quality",
        "bad anatomy, extra limbs, deformed, disfigured, watermark, text, signature",
        _first_non_empty_text(shot.get("negative_prompt"), shot.get("negative_prompt_compilation"), limit=500),
        _first_non_empty_text(scene.get("negative_prompt"), scene.get("negative_prompt_compilation"), limit=500),
    ]
    return ", ".join(part for part in parts if str(part).strip())


def build_shot_provider_request_inputs(
    scene: dict[str, Any],
    shot_plan: dict[str, Any],
    *,
    provider_id: str = "auto",
    project_settings: dict[str, Any] | None = None,
    width: int = 1080,
    height: int = 1920,
    fps: int = 24,
) -> list[dict[str, Any]]:
    """Build pure per-shot provider inputs without submitting provider jobs.

    The returned dictionaries are intentionally close to the existing
    ``VideoRenderRequest`` fields while keeping provider/model routing as a
    separate safe metadata block. Adapter wire formats are not changed here.
    """
    if not isinstance(scene, dict):
        scene = {}
    shots = shot_plan.get("shots") if isinstance(shot_plan, dict) else []
    if not isinstance(shots, list):
        return []
    scene_order = _coerce_non_negative_int(scene.get("order") or scene.get("scene") or shot_plan.get("scene_order") if isinstance(shot_plan, dict) else 1, 1)
    scene_id = _first_non_empty_text(
        scene.get("scene_id"),
        shot_plan.get("scene_id") if isinstance(shot_plan, dict) else "",
        f"scene_{scene_order:03d}",
        limit=120,
    )
    scene_title = _first_non_empty_text(scene.get("title"), scene_id, limit=180)
    request_inputs: list[dict[str, Any]] = []
    valid_shots = [shot for shot in shots if isinstance(shot, dict)]
    for index, shot in enumerate(valid_shots, start=1):
        previous_shot = valid_shots[index - 2] if index > 1 else None
        next_shot = valid_shots[index] if index < len(valid_shots) else None
        shot_id = _first_non_empty_text(shot.get("shot_id"), f"{scene_id}_shot_{index:02d}", limit=120)
        shot_order = _coerce_non_negative_int(shot.get("shot_order") or index, index)
        start_seconds = _coerce_non_negative_float(shot.get("start_seconds"))
        duration_seconds = _coerce_non_negative_float(shot.get("duration_seconds") or scene.get("duration_seconds"))
        end_seconds = _coerce_non_negative_float(shot.get("end_seconds") or (start_seconds + duration_seconds))
        camera = _shot_camera_payload(shot, scene)
        intent = _shot_intent_payload(shot, scene)
        continuity = _scene_continuity_payload(scene, previous_shot=previous_shot, next_shot=next_shot)
        provider_config = _resolve_shot_provider_config(
            default_provider=provider_id,
            project_settings=project_settings,
            scene=scene,
            shot=shot,
        )
        prompt = _shot_prompt_text(
            scene=scene,
            shot={**shot, "shot_id": shot_id, "duration_seconds": duration_seconds, "start_seconds": start_seconds},
            camera=camera,
            intent=intent,
            continuity=continuity,
        )
        visual_content = shot.get("visual_content") if isinstance(shot.get("visual_content"), dict) else {}
        request_inputs.append(
            {
                "version": 1,
                "render_granularity": "shot",
                "scene_id": scene_id,
                "scene_order": scene_order,
                "scene_title": scene_title,
                "shot_id": shot_id,
                "shot_order": shot_order,
                "index": index,
                "start_seconds": round(start_seconds, 3),
                "duration_seconds": round(duration_seconds, 3),
                "end_seconds": round(end_seconds, 3),
                "width": int(width),
                "height": int(height),
                "fps": int(fps),
                "prompt": prompt,
                "negative_prompt": _shot_negative_prompt(scene, shot),
                "camera": camera,
                "intent": intent,
                "visual_content": _compact_mapping(visual_content, max_items=16, text_limit=500),
                "continuity": continuity,
                "provider": provider_config,
                "temporal_spec": {
                    "version": 1,
                    "kind": "shot_temporal_spec",
                    "scene_id": scene_id,
                    "shot_id": shot_id,
                    "shot_order": shot_order,
                    "start_seconds": round(start_seconds, 3),
                    "duration_seconds": round(duration_seconds, 3),
                    "end_seconds": round(end_seconds, 3),
                    "camera": deepcopy(camera),
                },
                "consistency_spec": {
                    "version": 1,
                    "kind": "shot_consistency_spec",
                    "scene_id": scene_id,
                    "shot_id": shot_id,
                    "continuity": deepcopy(continuity),
                },
                "characters": _compact_string_list(scene.get("characters")),
                "dialogue": intent.get("dialogue", ""),
                "emotion": intent.get("emotion", ""),
            }
        )
    return request_inputs


def render_shot_with_provider_policy(
    shot_request: dict[str, Any],
    keyframe_path: Path,
    output_path: Path,
    run_dir: Path,
    *,
    video_provider: str = "",
    fallback_renderer: Callable[[dict[str, Any], Path], Path | str | None] | None = None,
    max_retries: int | None = None,
    retry_delay: float | None = None,
    ffmpeg: str | None = None,
    run_guarded: Callable[..., Any] | None = None,
    timeout_s: int = 900,
) -> dict[str, Any]:
    """Render one shot through the existing provider retry/fallback policy."""
    from scripts.video_provider_adapters import VideoRenderRequest
    from video_providers import get_video_provider_spec

    request = shot_request if isinstance(shot_request, dict) else {}
    provider_payload = request.get("provider") if isinstance(request.get("provider"), dict) else {}
    requested_provider = _first_non_empty_text(video_provider, provider_payload.get("provider_id"), "auto", limit=120)
    provider_spec = get_video_provider_spec(requested_provider)
    if max_retries is None:
        max_retries = MAX_VIDEO_RETRIES
    if retry_delay is None:
        retry_delay = VIDEO_RETRY_DELAY_SECONDS

    shot_id = _first_non_empty_text(request.get("shot_id"), "shot_001", limit=120)
    index = _coerce_non_negative_int(request.get("index") or request.get("shot_order") or 1, 1) or 1
    scene_order = _coerce_non_negative_int(request.get("scene_order") or 1, 1) or 1
    duration = _coerce_non_negative_float(request.get("duration_seconds"), 0.0)
    width = _coerce_non_negative_int(request.get("width") or 1080, 1080) or 1080
    height = _coerce_non_negative_int(request.get("height") or 1920, 1920) or 1920
    fps = _coerce_non_negative_int(request.get("fps") or 24, 24) or 24
    prompt = _clean_short_text(request.get("prompt"), limit=6000)
    negative_prompt = _clean_short_text(request.get("negative_prompt"), limit=2000)
    temporal_spec = request.get("temporal_spec") if isinstance(request.get("temporal_spec"), dict) else {}
    consistency_spec = request.get("consistency_spec") if isinstance(request.get("consistency_spec"), dict) else {}
    camera_payload = request.get("camera") if isinstance(request.get("camera"), dict) else {}
    model = _clean_short_text(provider_payload.get("model"), limit=240)
    cache_key = build_shot_cache_key(request, keyframe_path)
    attempts = 0
    last_error = ""

    if provider_spec.backend == "remote":
        for attempt in range(1, max_retries + 2):
            attempts = attempt
            try:
                if render_remote_video_provider is None:
                    raise RuntimeError("remote video provider adapter is not available")
                render_remote_video_provider(
                    VideoRenderRequest(
                        scene=scene_order,
                        title=_first_non_empty_text(request.get("scene_title"), shot_id, limit=180),
                        prompt=prompt,
                        negative_prompt=negative_prompt,
                        keyframe_path=keyframe_path,
                        out_path=output_path,
                        run_dir=run_dir,
                        duration=duration,
                        width=width,
                        height=height,
                        fps=fps,
                        camera=_first_non_empty_text(camera_payload.get("camera_movement"), limit=180),
                        emotion=_first_non_empty_text(request.get("emotion"), limit=180),
                        dialogue=_first_non_empty_text(request.get("dialogue"), limit=1000),
                        characters=tuple(_compact_string_list(request.get("characters"))),
                        temporal_spec=temporal_spec,
                        consistency_spec=consistency_spec,
                    ),
                    provider_spec,
                    ffmpeg=ffmpeg,
                    run_guarded=run_guarded,
                    timeout_s=timeout_s,
                )
                return build_shot_output(
                    shot_id=shot_id,
                    index=index,
                    status="real_video",
                    provider_id=provider_spec.id,
                    provider_label=provider_spec.label,
                    backend=provider_spec.backend,
                    model=model,
                    path=str(output_path),
                    duration_seconds=duration,
                    target_duration_seconds=duration,
                    attempts=attempts,
                    fallback_used=False,
                    cache_key=cache_key,
                )
            except Exception as exc:
                last_error = str(exc)
                if attempt <= max_retries:
                    error_text = last_error.lower()
                    backoff = max(retry_delay, 30.0) if ("429" in error_text or "quota" in error_text or "饱和" in error_text) else retry_delay
                    if backoff > 0:
                        time.sleep(backoff)
                    retry_delay = min(retry_delay * 2.0, 120.0)
                    continue
                break
    elif provider_spec.backend in {"local", "comfyui"}:
        if fallback_renderer is None:
            return build_shot_output(
                shot_id=shot_id,
                index=index,
                status="failed",
                provider_id=provider_spec.id,
                provider_label=provider_spec.label,
                backend="local",
                model=model,
                path="",
                duration_seconds=duration,
                target_duration_seconds=duration,
                attempts=0,
                fallback_used=False,
                error="local shot fallback renderer is not configured",
                cache_key=cache_key,
            )
        try:
            fallback_path = fallback_renderer(request, output_path)
        except Exception as exc:
            return build_shot_output(
                shot_id=shot_id,
                index=index,
                status="failed",
                provider_id=provider_spec.id,
                provider_label=provider_spec.label,
                backend="local",
                model=model,
                path="",
                duration_seconds=duration,
                target_duration_seconds=duration,
                attempts=1,
                fallback_used=False,
                error=str(exc),
                cache_key=cache_key,
            )
        return build_shot_output(
            shot_id=shot_id,
            index=index,
            status="fallback",
            provider_id=provider_spec.id,
            provider_label=provider_spec.label,
            backend="local",
            model=model,
            path=str(fallback_path or output_path),
            duration_seconds=duration,
            target_duration_seconds=duration,
            attempts=1,
            fallback_used=provider_spec.backend != "local",
            cache_key=cache_key,
        )
    else:
        raise ValueError(f"Unsupported video provider backend: {provider_spec.backend}")

    fallback_mode = video_fallback_mode(provider_spec.id)
    if fallback_mode == "strict":
        raise RuntimeError(sanitize_generation_error(last_error) or f"{provider_spec.label} shot render failed")

    warnings = []
    if fallback_mode == "report":
        warnings.append(f"{provider_spec.label} shot render failed after {attempts} attempts; using local fallback.")
    fallback_path = output_path
    if fallback_renderer is not None:
        try:
            rendered = fallback_renderer(request, output_path)
            fallback_path = Path(str(rendered)) if rendered else output_path
        except Exception as exc:
            return build_shot_output(
                shot_id=shot_id,
                index=index,
                status="failed",
                provider_id=provider_spec.id,
                provider_label=provider_spec.label,
                backend="local",
                model=model,
                path="",
                duration_seconds=duration,
                target_duration_seconds=duration,
            attempts=attempts,
            fallback_used=False,
            warnings=warnings,
            error=str(exc),
            cache_key=cache_key,
        )
    else:
        return build_shot_output(
            shot_id=shot_id,
            index=index,
            status="failed",
            provider_id=provider_spec.id,
            provider_label=provider_spec.label,
            backend="local",
            model=model,
            path="",
            duration_seconds=duration,
            target_duration_seconds=duration,
            attempts=attempts,
            fallback_used=False,
            warnings=warnings,
            error=last_error or "local shot fallback renderer is not configured",
            cache_key=cache_key,
        )
    return build_shot_output(
        shot_id=shot_id,
        index=index,
        status="fallback",
        provider_id=provider_spec.id,
        provider_label=provider_spec.label,
        backend="local",
        model=model,
        path=str(fallback_path),
        duration_seconds=duration,
        target_duration_seconds=duration,
        attempts=attempts,
        fallback_used=True,
        warnings=warnings,
        error=last_error,
        cache_key=cache_key,
    )


def assemble_shot_clips(
    *,
    ffmpeg: str,
    shot_outputs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    output_path: Path,
    run_dir: Path,
    scene_id: str = "",
    run_guarded: Callable[..., Any] | None = None,
    manifest_path: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Assemble valid shot clips into one scene clip with hard cuts."""
    clips: list[Path] = []
    manifest_outputs: list[dict[str, Any]] = []
    for index, raw_output in enumerate(shot_outputs or [], start=1):
        output = _normalize_shot_output(raw_output, index)
        if output is None:
            continue
        status = str(output.get("status") or "").strip().lower()
        path_text = str(output.get("path") or "").strip()
        if status not in {"real_video", "fallback", "skipped"} or not path_text:
            continue
        clip_path = Path(path_text)
        clips.append(clip_path)
        manifest_outputs.append(output)

    if not clips:
        raise ValueError("No usable shot clips to assemble")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_shot_assembly_manifest(
        scene_id=scene_id,
        output_path=str(output_path),
        shot_outputs=manifest_outputs,
    )

    if len(clips) == 1:
        source = clips[0]
        if source != output_path:
            if run_guarded is None:
                import shutil

                shutil.copyfile(source, output_path)
            else:
                run_guarded(
                    [
                        ffmpeg,
                        "-y",
                        "-i",
                        str(source),
                        "-c",
                        "copy",
                        str(output_path),
                    ],
                    cwd=run_dir,
                    timeout=300,
                    stage="ffmpeg_copy_single_shot",
                )
    else:
        concat_file = run_dir / f"{output_path.stem}_shot_concat.txt"
        lines = []
        for clip in clips:
            safe_path = str(clip).replace("\\", "/").replace("'", "'\\''")
            lines.append(f"file '{safe_path}'")
        concat_file.write_text("\n".join(lines), encoding="utf-8")
        runner = run_guarded
        if runner is None:
            from scripts.run_workflow import run_guarded as runner

        runner(
            [
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
                str(output_path),
            ],
            cwd=run_dir,
            timeout=max(300, 300 + len(clips) * 10),
            stage="ffmpeg_assemble_shot_clips",
        )

    if manifest_path is not None:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path, manifest


def render_scene_shots_with_provider_policy(
    *,
    scene: dict[str, Any],
    shot_plan: dict[str, Any],
    keyframe_path: Path,
    output_path: Path,
    run_dir: Path,
    ffmpeg: str,
    video_provider: str = "auto",
    project_settings: dict[str, Any] | None = None,
    existing_shot_outputs: list[dict[str, Any]] | None = None,
    fallback_renderer: Callable[[dict[str, Any], Path], Path | str | None] | None = None,
    run_guarded: Callable[..., Any] | None = None,
    manifest_path: Path | None = None,
    max_retries: int | None = None,
    retry_delay: float | None = None,
    force_shot_id: str = "",
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Render/reuse all shots for one scene and assemble the scene clip."""
    quota_config = video_shot_quota_config(project_settings=project_settings)
    requests = build_shot_provider_request_inputs(
        scene,
        shot_plan,
        provider_id=video_provider,
        project_settings=project_settings,
    )
    reusable_by_id: dict[str, dict[str, Any]] = {}
    reusable_for_quota: list[dict[str, Any]] = []
    normalized_force_shot_id = str(force_shot_id or "").strip()
    if quota_config.get("reuse_cache") and isinstance(existing_shot_outputs, list):
        for index, raw_output in enumerate(existing_shot_outputs, start=1):
            output = _normalize_shot_output(raw_output, index)
            if output is None:
                continue
            shot_id = str(output.get("shot_id") or "").strip()
            if normalized_force_shot_id and shot_id == normalized_force_shot_id:
                continue
            matching_request = next((request for request in requests if str(request.get("shot_id") or "").strip() == shot_id), None)
            if shot_id and matching_request and _shot_output_matches_cache(output, matching_request, keyframe_path):
                reusable_by_id[shot_id] = output
                reusable_for_quota.append(output)

    estimate = estimate_shot_render_quota(
        shot_plan,
        existing_shot_outputs=reusable_for_quota,
        reuse_cache=bool(quota_config.get("reuse_cache")),
    )
    quota_result = validate_shot_render_quota(
        estimate,
        max_calls=quota_config.get("max_calls"),
        max_seconds=quota_config.get("max_seconds"),
        dry_run=bool(quota_config.get("dry_run")),
        raise_on_error=True,
    )
    if quota_config.get("dry_run"):
        raise VideoShotDryRun(quota_result)

    shot_outputs: list[dict[str, Any]] = []
    for request in requests:
        shot_id = str(request.get("shot_id") or "").strip()
        if shot_id and shot_id in reusable_by_id:
            shot_outputs.append(reusable_by_id[shot_id])
            continue
        shot_output_path = run_dir / "shots" / f"{shot_id or f'shot_{len(shot_outputs) + 1:03d}'}.mp4"
        shot_outputs.append(
            render_shot_with_provider_policy(
                request,
                keyframe_path,
                shot_output_path,
                run_dir,
                video_provider=str((request.get("provider") or {}).get("provider_id") if isinstance(request.get("provider"), dict) else video_provider),
                fallback_renderer=fallback_renderer,
                max_retries=max_retries,
                retry_delay=retry_delay,
                ffmpeg=ffmpeg,
                run_guarded=run_guarded,
            )
        )

    failed_required = [output for output in shot_outputs if output.get("status") == "failed"]
    if failed_required and video_fallback_mode(video_provider) == "strict":
        error = "; ".join(
            sanitize_generation_error(output.get("error"), limit=160)
            for output in failed_required
            if str(output.get("error") or "").strip()
        )
        raise RuntimeError(error or "Shot-level scene render failed in strict mode")

    assembled_path, assembly_manifest = assemble_shot_clips(
        ffmpeg=ffmpeg,
        shot_outputs=shot_outputs,
        output_path=output_path,
        run_dir=run_dir,
        scene_id=str(shot_plan.get("scene_id") or scene.get("scene_id") or ""),
        run_guarded=run_guarded,
        manifest_path=manifest_path,
    )
    generation_meta = generation_meta_from_shot_outputs(
        shot_outputs,
        requested_provider=video_provider,
        fallback_mode=video_fallback_mode(video_provider),
        duration_seconds=_coerce_non_negative_float(assembly_manifest.get("duration_seconds") or scene.get("duration_seconds")),
    )
    generation_meta["shot_assembly_manifest"] = assembly_manifest
    generation_meta = normalize_generation_meta(generation_meta)
    return assembled_path, generation_meta, assembly_manifest


def sanitize_generation_error(value: object, *, limit: int = 500) -> str:
    """Sanitize provider errors before persisting them in project JSON."""
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"(?i)(api[_-]?key|token|authorization|bearer|secret)=([^&\s]+)", r"\1=<redacted>", text)
    text = re.sub(r"(?i)(authorization:\s*bearer\s+)[^\s]+", r"\1<redacted>", text)
    text = re.sub(r"https?://[^\s?]+\?[^\s]*", lambda match: match.group(0).split("?", 1)[0], text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _coerce_non_negative_int(value: object, default: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, number)


def _coerce_non_negative_float(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, number)


def _clean_generation_text(value: object, *, limit: int = 500) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"https?://[^\s?]+\?[^\s]*", lambda match: match.group(0).split("?", 1)[0], text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _normalize_generation_warnings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    warnings: list[str] = []
    for item in value:
        text = sanitize_generation_error(item, limit=240)
        if text:
            warnings.append(text)
    return warnings


def _normalize_shot_output(value: object, fallback_index: int) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    output = deepcopy(value)
    output["shot_id"] = _clean_generation_text(output.get("shot_id"), limit=120)
    output["index"] = _coerce_non_negative_int(output.get("index"), fallback_index)
    status = str(output.get("status") or "unknown").strip().lower()
    if status not in {"real_video", "fallback", "failed", "skipped", "unknown"}:
        status = "unknown"
    output["status"] = status
    for key in ("provider_id", "provider_label", "backend", "model", "cache_key"):
        if key in output:
            output[key] = _clean_generation_text(output.get(key), limit=240)
    if "path" in output:
        output["path"] = sanitize_generation_error(output.get("path"))
    if "duration_seconds" in output:
        output["duration_seconds"] = _coerce_non_negative_float(output.get("duration_seconds"))
    if "target_duration_seconds" in output:
        output["target_duration_seconds"] = _coerce_non_negative_float(output.get("target_duration_seconds"))
    if "attempts" in output:
        output["attempts"] = _coerce_non_negative_int(output.get("attempts"))
    if "fallback_used" in output:
        output["fallback_used"] = bool(output.get("fallback_used"))
    if "error" in output:
        output["error"] = sanitize_generation_error(output.get("error"))
    if "warnings" in output:
        output["warnings"] = _normalize_generation_warnings(output.get("warnings"))
    return output


def build_shot_output(
    *,
    shot_id: str,
    index: int,
    status: str,
    provider_id: str = "",
    provider_label: str = "",
    backend: str = "",
    model: str = "",
    path: str = "",
    duration_seconds: float = 0.0,
    target_duration_seconds: float = 0.0,
    attempts: int = 0,
    fallback_used: bool = False,
    warnings: list[str] | None = None,
    error: str = "",
    cache_key: str = "",
) -> dict[str, Any]:
    """Build a sanitized shot-level render output record."""
    normalized = _normalize_shot_output(
        {
            "shot_id": shot_id,
            "index": index,
            "status": status,
            "provider_id": provider_id,
            "provider_label": provider_label,
            "backend": backend,
            "model": model,
            "path": path,
            "duration_seconds": duration_seconds,
            "target_duration_seconds": target_duration_seconds,
            "attempts": attempts,
            "fallback_used": fallback_used,
            "warnings": warnings or [],
            "error": error,
            "cache_key": cache_key,
        },
        fallback_index=index,
    )
    return normalized or {}


def generation_meta_from_shot_outputs(
    shot_outputs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    requested_provider: str = "",
    provider_id: str = "",
    provider_label: str = "",
    backend: str = "",
    fallback_mode: str = "",
    duration_seconds: float = 0.0,
) -> dict[str, Any]:
    """Aggregate shot output records into scene-level generation metadata."""
    normalized_outputs: list[dict[str, Any]] = []
    for index, output in enumerate(shot_outputs or [], start=1):
        normalized = _normalize_shot_output(output, index)
        if normalized is not None:
            normalized_outputs.append(normalized)
    real_count = sum(1 for item in normalized_outputs if item.get("status") == "real_video")
    fallback_count = sum(1 for item in normalized_outputs if item.get("status") == "fallback" or item.get("fallback_used") is True)
    failed_count = sum(1 for item in normalized_outputs if item.get("status") == "failed")
    total_attempts = sum(_coerce_non_negative_int(item.get("attempts")) for item in normalized_outputs)
    first_output = normalized_outputs[0] if normalized_outputs else {}
    resolved_provider_id = provider_id or str(first_output.get("provider_id") or "")
    resolved_provider_label = provider_label or str(first_output.get("provider_label") or "")
    resolved_backend = backend or str(first_output.get("backend") or "")
    if not resolved_backend:
        resolved_backend = "remote" if real_count else "local"
    warnings: list[str] = []
    errors: list[str] = []
    for output in normalized_outputs:
        warnings.extend(_normalize_generation_warnings(output.get("warnings")))
        error = sanitize_generation_error(output.get("error"))
        if error:
            errors.append(f"{output.get('shot_id') or output.get('index')}: {error}")
    return normalize_generation_meta(
        {
            "version": 2,
            "provider_id": resolved_provider_id,
            "provider_label": resolved_provider_label,
            "backend": resolved_backend,
            "requested_provider": requested_provider,
            "is_real_video": real_count > 0 and failed_count == 0,
            "fallback_used": fallback_count > 0,
            "attempts": total_attempts,
            "duration_seconds": duration_seconds,
            "error": "; ".join(errors),
            "warnings": warnings,
            "fallback_mode": fallback_mode or video_fallback_mode(resolved_provider_id),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "render_granularity": "shot",
            "real_video_shot_count": real_count,
            "fallback_shot_count": fallback_count,
            "failed_shot_count": failed_count,
            "total_provider_attempts": total_attempts,
            "shot_outputs": normalized_outputs,
        }
    )


def build_shot_assembly_manifest(
    *,
    scene_id: str,
    output_path: str,
    shot_outputs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    """Build a stable manifest for a scene assembled from shot clips."""
    children: list[dict[str, Any]] = []
    cursor = 0.0
    for index, output in enumerate(shot_outputs or [], start=1):
        normalized = _normalize_shot_output(output, index)
        if normalized is None:
            continue
        duration = _coerce_non_negative_float(
            normalized.get("duration_seconds") or normalized.get("target_duration_seconds")
        )
        child = {
            "shot_id": _clean_generation_text(normalized.get("shot_id") or f"shot_{index:03d}", limit=120),
            "path": sanitize_generation_error(normalized.get("path")),
            "start_seconds": round(cursor, 3),
            "duration_seconds": round(duration, 3),
            "status": str(normalized.get("status") or "unknown"),
        }
        cursor = round(cursor + duration, 3)
        children.append(child)
    return {
        "version": 1,
        "scene_id": _clean_generation_text(scene_id, limit=120),
        "render_granularity": "shot",
        "output_path": sanitize_generation_error(output_path),
        "duration_seconds": round(cursor, 3),
        "children": children,
    }


def normalize_generation_meta(meta: object) -> dict[str, Any]:
    """Normalize persisted generation metadata across schema versions.

    Empty or missing metadata remains ``{}`` so legacy projects keep their
    existing unknown-provenance behavior. Non-empty version-1 metadata gets a
    version field and sanitized common values. Version-2 metadata may carry
    shot-level fields such as ``render_granularity`` and ``shot_outputs``.
    """
    if not isinstance(meta, dict) or not meta:
        return {}
    normalized = deepcopy(meta)
    has_v2_fields = any(
        key in normalized
        for key in (
            "render_granularity",
            "shot_outputs",
            "real_video_shot_count",
            "fallback_shot_count",
            "failed_shot_count",
            "total_provider_attempts",
        )
    )
    version = _coerce_non_negative_int(normalized.get("version"), 2 if has_v2_fields else 1)
    if version < 1:
        version = 1
    if version < 2 and has_v2_fields:
        version = 2
    normalized["version"] = version

    for key in ("provider_id", "provider_label", "backend", "requested_provider", "fallback_mode", "generated_at"):
        if key in normalized:
            normalized[key] = _clean_generation_text(normalized.get(key), limit=240)
    for key in ("is_real_video", "fallback_used"):
        if key in normalized:
            normalized[key] = bool(normalized.get(key))
    if "attempts" in normalized:
        normalized["attempts"] = _coerce_non_negative_int(normalized.get("attempts"))
    if "duration_seconds" in normalized:
        normalized["duration_seconds"] = _coerce_non_negative_float(normalized.get("duration_seconds"))
    if "error" in normalized:
        normalized["error"] = sanitize_generation_error(normalized.get("error"))
    if "warnings" in normalized:
        normalized["warnings"] = _normalize_generation_warnings(normalized.get("warnings"))

    if version >= 2 or has_v2_fields:
        granularity = str(normalized.get("render_granularity") or "scene").strip().lower()
        if granularity not in {"scene", "shot"}:
            granularity = "scene"
        normalized["render_granularity"] = granularity

        shot_outputs: list[dict[str, Any]] = []
        if isinstance(normalized.get("shot_outputs"), list):
            for index, raw_output in enumerate(normalized.get("shot_outputs") or [], start=1):
                shot_output = _normalize_shot_output(raw_output, index)
                if shot_output is not None:
                    shot_outputs.append(shot_output)
        normalized["shot_outputs"] = shot_outputs

        computed_real = sum(1 for item in shot_outputs if item.get("status") == "real_video")
        computed_fallback = sum(1 for item in shot_outputs if item.get("status") == "fallback" or item.get("fallback_used") is True)
        computed_failed = sum(1 for item in shot_outputs if item.get("status") == "failed")
        computed_attempts = sum(_coerce_non_negative_int(item.get("attempts")) for item in shot_outputs)
        normalized["real_video_shot_count"] = _coerce_non_negative_int(
            normalized.get("real_video_shot_count"),
            computed_real,
        )
        normalized["fallback_shot_count"] = _coerce_non_negative_int(
            normalized.get("fallback_shot_count"),
            computed_fallback,
        )
        normalized["failed_shot_count"] = _coerce_non_negative_int(
            normalized.get("failed_shot_count"),
            computed_failed,
        )
        normalized["total_provider_attempts"] = _coerce_non_negative_int(
            normalized.get("total_provider_attempts"),
            computed_attempts,
        )

    return normalized


def generation_meta_from_result(
    result: VideoGenerationResult,
    requested_provider: str = "",
    fallback_mode: str = "",
) -> dict[str, Any]:
    """Serialize video generation provenance for scene persistence."""
    warnings = result.warnings if isinstance(result.warnings, list) else []
    backend = str(result.backend or "").strip()
    if not backend:
        backend = "local"
        if result.is_real_video:
            backend = "remote" if str(result.provider_id or "").lower() not in {"comfyui"} else "comfyui"
    fallback_used = bool(result.fallback_used or (not result.is_real_video and str(result.provider_id or "").lower() != "local"))
    return normalize_generation_meta({
        "version": 1,
        "provider_id": str(result.provider_id or "").strip(),
        "provider_label": str(result.provider_label or "").strip(),
        "backend": backend,
        "requested_provider": str(requested_provider or "").strip(),
        "is_real_video": bool(result.is_real_video),
        "fallback_used": fallback_used,
        "attempts": int(result.attempts or 0),
        "duration_seconds": float(result.duration_seconds or 0.0),
        "error": sanitize_generation_error(result.error),
        "warnings": [sanitize_generation_error(item, limit=240) for item in warnings if str(item or "").strip()],
        "fallback_mode": fallback_mode or video_fallback_mode(result.provider_id),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })

def extract_last_frame(video_path: Path, output_path: Path) -> Path | None:
    """Extract the last frame from a video for cross-scene continuity bridging."""
    try:
        from scripts.run_workflow import get_ffmpeg_exe, run_guarded
        ffmpeg = get_ffmpeg_exe()
        # Extract last frame using ffmpeg
        run_guarded(
            [
                ffmpeg, "-y",
                "-sseof", "-0.1",  # Seek to 0.1s before end
                "-i", str(video_path),
                "-frames:v", "1",
                "-q:v", "2",
                str(output_path),
            ],
            cwd=output_path.parent,
            timeout=15,
            stage="extract_last_frame",
        )
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path
    except Exception as exc:
        logger.warning("Failed to extract last frame from %s: %s", video_path, exc)
    return None


def build_continuity_bridge_prompt(
    prev_scene: dict[str, Any] | None,
    current_scene: dict[str, Any],
    prev_last_frame_path: str = "",
) -> dict[str, str]:
    """Build continuity bridging instructions for cross-scene transitions.

    Returns a dict with:
    - continuity_prefix: text to prepend to the video prompt
    - transition_type: cut/xfade/black
    - prev_ending_context: description of how the previous scene ended
    """
    if prev_scene is None:
        return {
            "continuity_prefix": "",
            "transition_type": "cut",
            "prev_ending_context": "",
        }

    prev_emotion = str(prev_scene.get("emotion_tone") or prev_scene.get("emotion") or "").strip()
    curr_emotion = str(current_scene.get("emotion_tone") or current_scene.get("emotion") or "").strip()
    prev_title = str(prev_scene.get("title") or "").strip()
    prev_characters = prev_scene.get("characters") or []
    curr_characters = current_scene.get("characters") or []

    # Determine transition type
    from scripts.run_workflow import _scene_transition
    transition = _scene_transition(prev_emotion, curr_emotion)

    # Build continuity prefix
    continuity_parts: list[str] = []

    # Shared characters should maintain appearance
    shared_chars = set(str(c) for c in prev_characters) & set(str(c) for c in curr_characters)
    if shared_chars:
        continuity_parts.append(
            f"Characters continuing from previous scene: {', '.join(shared_chars)}. "
            "Maintain exact same appearance, clothing, and proportions."
        )

    # Transition-specific instructions
    if transition == "cut":
        continuity_parts.append(
            "Hard cut from previous scene. Opening frame should establish the new scene clearly."
        )
    elif transition == "xfade":
        continuity_parts.append(
            f"Smooth transition from previous scene ('{prev_title}'). "
            "Opening frames should have visual continuity in lighting and color temperature."
        )
    elif transition == "black":
        continuity_parts.append(
            "Scene follows a dramatic pause. Opening should re-establish setting and characters."
        )

    # Emotional continuity
    if prev_emotion and curr_emotion and prev_emotion != curr_emotion:
        continuity_parts.append(
            f"Emotional shift from {prev_emotion} to {curr_emotion}. "
            "Reflect this transition in character expressions and lighting."
        )

    return {
        "continuity_prefix": " ".join(continuity_parts),
        "transition_type": transition,
        "prev_ending_context": f"Previous scene: '{prev_title}', emotion: {prev_emotion}",
    }


# ---------------------------------------------------------------------------
# Retry-aware video generation
# ---------------------------------------------------------------------------

def generate_scene_video_with_retry(
    scene_obj: Any,
    keyframe_path: Path,
    clip_duration: float,
    visual_output_path: Path,
    run_dir: Path,
    video_provider: str = "auto",
    *,
    prev_scene_data: dict[str, Any] | None = None,
    prev_last_frame: Path | None = None,
    max_retries: int | None = None,
    retry_delay: float | None = None,
) -> VideoGenerationResult:
    """Generate video for a scene with retry logic and continuity bridging.

    This wraps the existing provider dispatch (ComfyUI/remote/local) with:
    - Configurable retry on transient failures
    - Cross-scene continuity prompt injection
    - Clear result reporting (real video vs 2.5D fallback)
    """
    from scripts.run_workflow import (
        build_scene_video_prompts,
        build_scene_temporal_spec,
        env_float,
        render_scene_video_comfyui,
        scene_consistency_spec,
    )
    from scripts.video_provider_adapters import (
        VideoRenderRequest,
        render_remote_video_provider,
        VideoProviderError,
    )
    from video_providers import get_video_provider_spec

    if max_retries is None:
        max_retries = MAX_VIDEO_RETRIES
    if retry_delay is None:
        retry_delay = VIDEO_RETRY_DELAY_SECONDS

    provider_spec = get_video_provider_spec(video_provider)
    scene_id = f"{scene_obj.scene:02}"
    attempts = 0
    last_error = ""

    # Build continuity bridge if we have previous scene context
    continuity_bridge = build_continuity_bridge_prompt(
        prev_scene_data,
        {
            "emotion_tone": getattr(scene_obj, "emotion", ""),
            "emotion": getattr(scene_obj, "emotion", ""),
            "title": getattr(scene_obj, "title", ""),
            "characters": list(getattr(scene_obj, "characters", []) or []),
        },
        str(prev_last_frame or ""),
    )

    for attempt in range(1, max_retries + 2):  # +2 because range is exclusive and we start at 1
        attempts = attempt
        try:
            if provider_spec.backend == "comfyui":
                logger.info(
                    "[video] Scene %s attempt %d/%d via %s",
                    scene_id, attempt, max_retries + 1, provider_spec.label,
                )
                render_scene_video_comfyui(scene_obj, keyframe_path, clip_duration, visual_output_path, run_dir)
                return VideoGenerationResult(
                    scene_order=scene_obj.scene,
                    provider_id=provider_spec.id,
                    provider_label=provider_spec.label,
                    success=True,
                    is_real_video=True,
                    attempts=attempts,
                    duration_seconds=clip_duration,
                    output_path=str(visual_output_path),
                    backend=provider_spec.backend,
                    fallback_used=False,
                )

            elif provider_spec.backend == "remote":
                logger.info(
                    "[video] Scene %s attempt %d/%d via %s (remote)",
                    scene_id, attempt, max_retries + 1, provider_spec.label,
                )
                prompt_text, negative_text = build_scene_video_prompts(scene_obj, clip_duration, run_dir)

                # Inject continuity bridge into prompt
                if continuity_bridge["continuity_prefix"]:
                    prompt_text = f"{continuity_bridge['continuity_prefix']}\n\n{prompt_text}"

                temporal_spec = getattr(scene_obj, "temporal_spec", None) or build_scene_temporal_spec(
                    scene_obj,
                    clip_duration,
                    width=int(env_float("VIDEO_WIDTH", default=1080)),
                    height=int(env_float("VIDEO_HEIGHT", default=1920)),
                    fps=int(env_float("VIDEO_FPS", default=24)),
                )
                consistency_spec_data = scene_consistency_spec(scene_obj)

                # Add cross-scene continuity to consistency spec
                if continuity_bridge["prev_ending_context"]:
                    consistency_spec_data["cross_scene_continuity"] = {
                        "transition_type": continuity_bridge["transition_type"],
                        "prev_ending_context": continuity_bridge["prev_ending_context"],
                        "shared_characters_must_match": True,
                    }

                from scripts.run_workflow import get_ffmpeg_exe, run_guarded as _run_guarded
                ffmpeg = get_ffmpeg_exe()

                render_remote_video_provider(
                    VideoRenderRequest(
                        scene=scene_obj.scene,
                        title=scene_obj.title,
                        prompt=prompt_text,
                        negative_prompt=negative_text,
                        keyframe_path=keyframe_path,
                        out_path=visual_output_path,
                        run_dir=run_dir,
                        duration=clip_duration,
                        width=int(env_float("VIDEO_WIDTH", default=1080)),
                        height=int(env_float("VIDEO_HEIGHT", default=1920)),
                        fps=int(env_float("VIDEO_FPS", default=24)),
                        camera=scene_obj.camera,
                        emotion=scene_obj.emotion,
                        dialogue=scene_obj.dialogue,
                        characters=tuple(scene_obj.characters or []),
                        temporal_spec=temporal_spec,
                        consistency_spec=consistency_spec_data,
                    ),
                    provider_spec,
                    ffmpeg=ffmpeg,
                    run_guarded=_run_guarded,
                    timeout_s=int(env_float("VIDEO_TIMEOUT", default=600)),
                )
                return VideoGenerationResult(
                    scene_order=scene_obj.scene,
                    provider_id=provider_spec.id,
                    provider_label=provider_spec.label,
                    success=True,
                    is_real_video=True,
                    attempts=attempts,
                    duration_seconds=clip_duration,
                    output_path=str(visual_output_path),
                    backend=provider_spec.backend,
                    fallback_used=False,
                )

            else:
                # Local provider — no retry needed, always succeeds
                return VideoGenerationResult(
                    scene_order=scene_obj.scene,
                    provider_id=provider_spec.id,
                    provider_label=provider_spec.label,
                    success=True,
                    is_real_video=False,
                    attempts=1,
                    duration_seconds=clip_duration,
                    output_path=str(visual_output_path),
                    warnings=["Using 2.5D local renderer (no video generation provider configured)"],
                    backend="local",
                    fallback_used=False,
                )

        except Exception as exc:
            last_error = str(exc)
            logger.warning(
                "[video] Scene %s attempt %d failed: %s",
                scene_id, attempt, last_error,
            )
            if attempt <= max_retries:
                logger.info("[video] Retrying in %.1fs...", retry_delay)
                time.sleep(retry_delay)
                # Exponential backoff
                retry_delay = min(retry_delay * 1.5, 60.0)
            continue

    # All retries exhausted
    fallback_mode = video_fallback_mode(provider_spec.id)

    if fallback_mode == "strict":
        raise RuntimeError(
            f"视频生成失败（{provider_spec.label}），已重试 {attempts} 次: {last_error}"
        )

    # Fall back to 2.5D but report it
    warnings = [
        f"视频生成失败，已回退到 2.5D 动态漫画模式（{provider_spec.label} 重试 {attempts} 次后失败: {last_error}）",
    ]
    if fallback_mode == "silent":
        warnings = []
    logger.warning(
        "[video] Scene %s: all %d attempts failed, falling back to 2.5D. Last error: %s",
        scene_id, attempts, last_error,
    )
    return VideoGenerationResult(
        scene_order=scene_obj.scene,
        provider_id=provider_spec.id,
        provider_label=provider_spec.label,
        success=True,
        is_real_video=False,
        attempts=attempts,
        duration_seconds=clip_duration,
        output_path=str(visual_output_path),
        error=last_error,
        warnings=warnings,
        backend="local",
        fallback_used=True,
    )


# ---------------------------------------------------------------------------
# Batch video generation with cross-scene continuity
# ---------------------------------------------------------------------------

def generate_project_videos_with_continuity(
    project_id: str,
    scene_orders: list[int] | None = None,
) -> list[VideoGenerationResult]:
    """Generate videos for multiple scenes with cross-scene continuity enforcement.

    Processes scenes in order, passing the last frame of each completed scene
    to the next scene's generation for visual continuity.
    """
    from backend.project_runtime import load_project
    from backend.scene_renderer import (
        project_dir,
        scene_dir,
        scene_latest_path,
    )

    project = load_project(project_id)
    scenes = sorted(
        [s for s in project.get("scenes", []) if isinstance(s, dict)],
        key=lambda s: int(s.get("order", 0)),
    )

    if scene_orders:
        scenes = [s for s in scenes if int(s.get("order", 0)) in scene_orders]

    results: list[VideoGenerationResult] = []
    prev_scene_data: dict[str, Any] | None = None
    prev_last_frame: Path | None = None

    for scene in scenes:
        scene_order = int(scene.get("order", 0))
        scene_id_str = str(scene.get("scene_id") or f"scene_{scene_order:03d}")
        directory = scene_dir(project_id, scene_id_str)

        # Check if video already exists and extract last frame for continuity
        existing_video = scene_latest_path(project_id, scene, "video")
        if existing_video and existing_video.exists():
            # Extract last frame for next scene's continuity
            last_frame_out = directory / "last_frame.png"
            extracted = extract_last_frame(existing_video, last_frame_out)
            if extracted:
                prev_last_frame = extracted
            prev_scene_data = scene
            results.append(VideoGenerationResult(
                scene_order=scene_order,
                provider_id="cached",
                provider_label="Cached",
                success=True,
                is_real_video=True,
                attempts=0,
                duration_seconds=float(scene.get("duration_seconds", 0)),
                output_path=str(existing_video),
                last_frame_path=str(prev_last_frame or ""),
            ))
            continue

        # This scene needs generation — pass continuity context
        logger.info(
            "[video-continuity] Generating scene %d with %s continuity from scene %s",
            scene_order,
            "cross-scene" if prev_scene_data else "no",
            prev_scene_data.get("order") if prev_scene_data else "N/A",
        )

        # Store continuity bridge info on the scene for the renderer
        if prev_scene_data:
            bridge = build_continuity_bridge_prompt(prev_scene_data, scene)
            scene["_continuity_bridge"] = bridge
            if prev_last_frame and prev_last_frame.exists():
                scene["_prev_last_frame"] = str(prev_last_frame)

        # Update prev for next iteration
        prev_scene_data = scene

    return results
