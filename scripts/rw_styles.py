from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from backend.config_utils import coerce_bool as _coerce_bool
from backend.config_utils import coerce_float as _coerce_float
from backend.config_utils import coerce_int as _coerce_int
from scripts.rw_config import (
    DEFAULT_AUDIO_MANIFEST,
    DEFAULT_AUDIO_STYLE,
    DEFAULT_CROP_BOX,
    DEFAULT_EPISODE_PACING,
    DEFAULT_SUBTITLE_STYLE,
    EPISODE_PHASES,
    MIN_CROP_BOX_SIZE,
)
from scripts.rw_models import StoryScene
from scripts.rw_utils import clamp


def default_subtitle_style() -> dict:
    return dict(DEFAULT_SUBTITLE_STYLE)


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
    preset = (
        str(merged.get("preset") or DEFAULT_EPISODE_PACING["preset"])
        .strip()
        .lower()
        .replace("-", "_")
    )
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
        "auto_assign": _coerce_bool(
            merged.get("auto_assign"), DEFAULT_EPISODE_PACING["auto_assign"]
        ),
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


def apply_episode_pacing_to_scenes(
    scenes: list[StoryScene], pacing: dict | None = None
) -> list[StoryScene]:
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
    merged["font_name"] = str(
        merged.get("font_name") or DEFAULT_SUBTITLE_STYLE["font_name"]
    ).strip()
    merged["font_size"] = _coerce_int(
        merged.get("font_size"), DEFAULT_SUBTITLE_STYLE["font_size"], 12, 96
    )
    merged["margin_v"] = _coerce_int(
        merged.get("margin_v"), DEFAULT_SUBTITLE_STYLE["margin_v"], 0, 600
    )
    merged["outline"] = _coerce_int(merged.get("outline"), DEFAULT_SUBTITLE_STYLE["outline"], 0, 8)
    merged["shadow"] = _coerce_int(merged.get("shadow"), DEFAULT_SUBTITLE_STYLE["shadow"], 0, 8)
    merged["alignment"] = _coerce_int(
        merged.get("alignment"), DEFAULT_SUBTITLE_STYLE["alignment"], 1, 9
    )
    merged["show_speaker"] = _coerce_bool(
        merged.get("show_speaker"), DEFAULT_SUBTITLE_STYLE["show_speaker"]
    )
    merged["burn_in"] = _coerce_bool(merged.get("burn_in"), DEFAULT_SUBTITLE_STYLE["burn_in"])
    return merged


def default_audio_style() -> dict:
    return dict(DEFAULT_AUDIO_STYLE)


def normalize_audio_style(style: dict | None = None) -> dict:
    merged = default_audio_style()
    if isinstance(style, dict):
        merged.update({key: value for key, value in style.items() if value is not None})
    merged["master_lufs"] = _coerce_float(
        merged.get("master_lufs"), DEFAULT_AUDIO_STYLE["master_lufs"], -30.0, -6.0
    )
    merged["true_peak"] = _coerce_float(
        merged.get("true_peak"), DEFAULT_AUDIO_STYLE["true_peak"], -6.0, 0.0
    )
    merged["loudness_range"] = _coerce_float(
        merged.get("loudness_range"), DEFAULT_AUDIO_STYLE["loudness_range"], 5.0, 20.0
    )
    merged["limiter_level"] = _coerce_float(
        merged.get("limiter_level"), DEFAULT_AUDIO_STYLE["limiter_level"], 0.5, 0.999
    )
    merged["bgm_path"] = str(merged.get("bgm_path") or "").strip()
    merged["bgm_gain_db"] = _coerce_float(
        merged.get("bgm_gain_db"), DEFAULT_AUDIO_STYLE["bgm_gain_db"], -60.0, 0.0
    )
    merged["duck_threshold"] = _coerce_float(
        merged.get("duck_threshold"), DEFAULT_AUDIO_STYLE["duck_threshold"], 0.01, 1.0
    )
    merged["duck_ratio"] = _coerce_float(
        merged.get("duck_ratio"), DEFAULT_AUDIO_STYLE["duck_ratio"], 1.0, 20.0
    )
    merged["duck_attack_ms"] = _coerce_int(
        merged.get("duck_attack_ms"), DEFAULT_AUDIO_STYLE["duck_attack_ms"], 1, 1000
    )
    merged["duck_release_ms"] = _coerce_int(
        merged.get("duck_release_ms"), DEFAULT_AUDIO_STYLE["duck_release_ms"], 10, 5000
    )
    return merged


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
