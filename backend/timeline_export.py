"""OpenTimelineIO (OTIO) compatible timeline export.

Exports the project's canonical timeline to OTIO JSON format,
enabling import into DaVinci Resolve, Premiere Pro, and other NLEs.

OTIO schema: https://opentimelineio.readthedocs.io/
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

OTIO_SCHEMA_VERSION = "0.15.0"


def _rational_time(seconds: float, rate: float = 24.0) -> dict[str, Any]:
    """Create an OTIO RationalTime object."""
    return {
        "OTIO_SCHEMA": "RationalTime.1",
        "value": round(seconds * rate),
        "rate": rate,
    }


def _time_range(start_seconds: float, duration_seconds: float, rate: float = 24.0) -> dict[str, Any]:
    """Create an OTIO TimeRange object."""
    return {
        "OTIO_SCHEMA": "TimeRange.1",
        "start_time": _rational_time(start_seconds, rate),
        "duration": _rational_time(duration_seconds, rate),
    }


def _media_reference(path: str, duration_seconds: float, rate: float = 24.0) -> dict[str, Any]:
    """Create an OTIO ExternalReference for a media file."""
    if not path:
        return {
            "OTIO_SCHEMA": "MissingReference.1",
            "name": "",
            "available_range": None,
            "metadata": {},
        }
    return {
        "OTIO_SCHEMA": "ExternalReference.1",
        "target_url": path.replace("\\", "/"),
        "available_range": _time_range(0, duration_seconds, rate),
        "metadata": {},
    }


def _clip(
    name: str,
    duration_seconds: float,
    media_path: str = "",
    rate: float = 24.0,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an OTIO Clip object."""
    return {
        "OTIO_SCHEMA": "Clip.2",
        "name": name,
        "source_range": _time_range(0, duration_seconds, rate),
        "media_reference": _media_reference(media_path, duration_seconds, rate),
        "metadata": metadata or {},
    }


def _gap(duration_seconds: float, rate: float = 24.0) -> dict[str, Any]:
    """Create an OTIO Gap (empty space on timeline)."""
    return {
        "OTIO_SCHEMA": "Gap.1",
        "name": "",
        "source_range": _time_range(0, duration_seconds, rate),
    }


def export_project_to_otio(project: dict[str, Any], project_dir: Path) -> dict[str, Any]:
    """Export a project's timeline to OTIO JSON format.

    Creates a timeline with:
    - Video track: scene clips in order
    - Audio track: voice/audio clips aligned to scenes
    - Markers: scene boundaries with metadata
    """
    title = str(project.get("title") or "Untitled").strip()
    scenes = sorted(
        [s for s in project.get("scenes", []) if isinstance(s, dict)],
        key=lambda s: int(s.get("order", 0)),
    )
    fps = 24.0

    # Build video track
    video_children: list[dict[str, Any]] = []
    audio_children: list[dict[str, Any]] = []
    markers: list[dict[str, Any]] = []
    cursor = 0.0

    for scene in scenes:
        order = int(scene.get("order", 0))
        scene_title = str(scene.get("title") or f"Scene {order}").strip()
        duration = float(scene.get("duration_seconds") or scene.get("clip_duration") or 5.0)
        duration = max(0.5, duration)

        # Video clip
        assets = scene.get("assets", {}) if isinstance(scene.get("assets"), dict) else {}
        video_path = str(assets.get("video_path") or "").strip()
        if video_path:
            video_path = str(project_dir / video_path)

        video_children.append(_clip(
            name=f"#{order} {scene_title}",
            duration_seconds=duration,
            media_path=video_path,
            rate=fps,
            metadata={
                "comic_drama": {
                    "scene_order": order,
                    "scene_id": scene.get("scene_id", ""),
                    "title": scene_title,
                    "emotion": str(scene.get("emotion") or scene.get("emotion_tone") or "").strip(),
                    "camera": str(scene.get("camera_movement") or "").strip(),
                    "characters": scene.get("characters", []),
                }
            },
        ))

        # Audio clip
        audio_path = str(assets.get("audio_path") or "").strip()
        if audio_path:
            audio_path = str(project_dir / audio_path)
            audio_children.append(_clip(
                name=f"#{order} Voice",
                duration_seconds=duration,
                media_path=audio_path,
                rate=fps,
            ))
        else:
            audio_children.append(_gap(duration, fps))

        # Scene boundary marker
        markers.append({
            "OTIO_SCHEMA": "Marker.2",
            "name": f"Scene {order}: {scene_title}",
            "marked_range": _time_range(cursor, 0, fps),
            "color": "RED" if scene.get("emotion") in ("anger", "tension") else "GREEN",
            "metadata": {"scene_order": order},
        })

        cursor += duration

    # Assemble timeline
    timeline = {
        "OTIO_SCHEMA": "Timeline.1",
        "name": title,
        "global_start_time": _rational_time(0, fps),
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "name": "Tracks",
            "children": [
                {
                    "OTIO_SCHEMA": "Track.1",
                    "name": "Video",
                    "kind": "Video",
                    "children": video_children,
                    "markers": markers,
                },
                {
                    "OTIO_SCHEMA": "Track.1",
                    "name": "Audio",
                    "kind": "Audio",
                    "children": audio_children,
                },
            ],
        },
        "metadata": {
            "comic_drama": {
                "project_id": str(project.get("project_id") or ""),
                "scene_count": len(scenes),
                "total_duration": round(cursor, 3),
                "exported_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
            }
        },
    }

    return timeline


def save_otio_file(timeline: dict[str, Any], output_path: Path) -> Path:
    """Save OTIO timeline to a .otio JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("[otio] Exported timeline to %s", output_path)
    return output_path
