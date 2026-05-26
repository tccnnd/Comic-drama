from __future__ import annotations

import re
from pathlib import Path
from typing import Any


PRIMARY_ASSET_PATTERN = re.compile(r"^(image|audio|video)_v(\d+)\.(png|wav|mp4)$")
SUBTITLE_ASSET_PATTERN = re.compile(r"^subtitle_v(\d+)\.(ass|srt)$")
TEMP_ASSET_PATTERN = re.compile(r"^.+_v(\d+)\.(tmp|log)$")


def _retained_versions(current_version: object, keep: int) -> set[int]:
    try:
        current = int(current_version)
    except (TypeError, ValueError):
        return set()
    if current < 1:
        return set()
    keep = max(1, int(keep))
    return {version for version in range(max(1, current - keep + 1), current + 1)}


def _extract_version(filename: str) -> tuple[str, int] | None:
    match = PRIMARY_ASSET_PATTERN.match(filename)
    if match:
        return match.group(1), int(match.group(2))
    match = SUBTITLE_ASSET_PATTERN.match(filename)
    if match:
        return "subtitle", int(match.group(1))
    match = TEMP_ASSET_PATTERN.match(filename)
    if match:
        return "temp", int(match.group(1))
    return None


def cleanup_scene_versions(scene_dir: Path, current_versions: dict[str, Any], keep: int = 2) -> list[Path]:
    if keep < 1 or not scene_dir.is_dir():
        return []

    retained_by_kind = {
        kind: _retained_versions(current_versions.get(kind), keep)
        for kind in ("image", "audio", "video")
    }
    retained_union = set().union(*retained_by_kind.values())
    retained_union.discard(0)
    retained_derivatives = retained_by_kind["video"] or retained_union

    deleted: list[Path] = []
    for entry in scene_dir.iterdir():
        if not entry.is_file():
            continue
        extracted = _extract_version(entry.name)
        if extracted is None:
            continue
        kind, version = extracted
        if kind in retained_by_kind:
            if version in retained_by_kind[kind]:
                continue
        elif version in retained_derivatives:
            continue
        try:
            entry.unlink()
            deleted.append(entry)
        except OSError:
            continue
    return deleted


def cleanup_project_versions(project_dir: Path, project_data: dict[str, Any], keep: int = 2) -> dict[str, int]:
    scenes_dir = project_dir / "scenes"
    if not scenes_dir.is_dir():
        return {"deleted_files": 0, "scenes_cleaned": 0}

    deleted_files = 0
    cleaned_scenes = 0
    for scene in project_data.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("scene_id") or "").strip()
        if not scene_id:
            continue
        versions = scene.get("assets", {}).get("versions", {})
        if not isinstance(versions, dict):
            continue
        deleted = cleanup_scene_versions(scenes_dir / scene_id, versions, keep=keep)
        if deleted:
            cleaned_scenes += 1
            deleted_files += len(deleted)

    return {"deleted_files": deleted_files, "scenes_cleaned": cleaned_scenes}
