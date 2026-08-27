"""Offline visual prototype coverage and gap report.

This script intentionally reads raw project JSON instead of importing backend
runtime modules, so it can be used against archived workspace snapshots.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def discover_project_files(path: Path) -> list[Path]:
    """Return project.json files for a file, project directory, or workspace."""
    path = path.resolve()
    if path.is_file():
        if path.name != "project.json":
            raise ValueError(f"Expected a project.json file, got {path}")
        return [path]

    if not path.is_dir():
        raise FileNotFoundError(path)

    project_file = path / "project.json"
    if project_file.exists():
        return [project_file]

    project_files = sorted(
        candidate / "project.json"
        for candidate in path.iterdir()
        if candidate.is_dir() and (candidate / "project.json").exists()
    )
    if not project_files:
        raise FileNotFoundError(f"No project.json files found under {path}")
    return project_files


def _scene_identifier(scene: dict[str, Any], fallback_order: int) -> str:
    value = scene.get("scene_id") or scene.get("id") or scene.get("scene")
    if value is None:
        return f"scene_{fallback_order:03d}"
    return str(value)


def _shot_gap_reason(visual_prototype: dict[str, Any]) -> str:
    gap = visual_prototype.get("gap")
    if isinstance(gap, dict):
        reason = gap.get("reason")
        if reason:
            return str(reason)
    return "unspecified"


def summarize_project(project: dict[str, Any], source_path: str | None = None) -> dict[str, Any]:
    """Summarize visual_prototype usage for one project payload."""
    prototype_ids: Counter[str] = Counter()
    gap_reasons: Counter[str] = Counter()
    scenes_with_gaps: list[dict[str, Any]] = []
    total_shots = 0
    prototype_lock = 0
    freeform = 0
    unknown = 0

    scenes = project.get("scenes")
    if not isinstance(scenes, list):
        scenes = []

    for scene_index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            continue
        shot_plan = scene.get("shot_plan")
        if not isinstance(shot_plan, dict):
            continue
        shots = shot_plan.get("shots")
        if not isinstance(shots, list):
            continue

        scene_gap_reasons: Counter[str] = Counter()
        freeform_shots: list[str] = []
        scene_id = _scene_identifier(scene, scene_index)

        for shot_index, shot in enumerate(shots, start=1):
            if not isinstance(shot, dict):
                unknown += 1
                total_shots += 1
                continue

            total_shots += 1
            shot_id = str(shot.get("shot_id") or f"{scene_id}_shot_{shot_index:02d}")
            visual_prototype = shot.get("visual_prototype")
            if not isinstance(visual_prototype, dict):
                unknown += 1
                continue

            mode = str(visual_prototype.get("mode") or "").strip()
            prototype_id = str(visual_prototype.get("id") or "").strip()
            if prototype_id:
                prototype_ids[prototype_id] += 1

            if mode == "prototype_lock":
                prototype_lock += 1
            elif mode == "freeform":
                freeform += 1
                reason = _shot_gap_reason(visual_prototype)
                gap_reasons[reason] += 1
                scene_gap_reasons[reason] += 1
                freeform_shots.append(shot_id)
            else:
                unknown += 1

        if scene_gap_reasons:
            scenes_with_gaps.append(
                {
                    "project_id": str(project.get("project_id") or ""),
                    "scene_id": scene_id,
                    "scene_order": scene.get("order") or scene.get("scene") or scene_index,
                    "freeform_shots": freeform_shots,
                    "gap_reasons": dict(sorted(scene_gap_reasons.items())),
                }
            )

    return {
        "project_id": str(project.get("project_id") or ""),
        "source_path": source_path or "",
        "total_shots": total_shots,
        "prototype_lock": prototype_lock,
        "freeform": freeform,
        "unknown": unknown,
        "prototype_ids": dict(sorted(prototype_ids.items())),
        "gap_reasons": dict(sorted(gap_reasons.items())),
        "scenes_with_gaps": scenes_with_gaps,
    }


def merge_reports(project_reports: list[dict[str, Any]]) -> dict[str, Any]:
    prototype_ids: Counter[str] = Counter()
    gap_reasons: Counter[str] = Counter()
    scenes_with_gaps: list[dict[str, Any]] = []

    merged = {
        "total_shots": 0,
        "prototype_lock": 0,
        "freeform": 0,
        "unknown": 0,
    }
    for report in project_reports:
        for key in merged:
            merged[key] += int(report.get(key) or 0)
        prototype_ids.update(report.get("prototype_ids") or {})
        gap_reasons.update(report.get("gap_reasons") or {})
        scenes_with_gaps.extend(report.get("scenes_with_gaps") or [])

    return {
        **merged,
        "prototype_ids": dict(sorted(prototype_ids.items())),
        "gap_reasons": dict(sorted(gap_reasons.items())),
        "scenes_with_gaps": scenes_with_gaps,
        "projects": project_reports,
    }


def build_report(path: Path) -> dict[str, Any]:
    project_files = discover_project_files(path)
    reports = [
        summarize_project(_load_json(project_file), str(project_file))
        for project_file in project_files
    ]
    return merge_reports(reports)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report visual prototype coverage and freeform gaps."
    )
    parser.add_argument(
        "path", type=Path, help="project.json, project directory, or workspace directory"
    )
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    args = parser.parse_args(argv)

    report = build_report(args.path)
    indent = 2 if args.pretty else None
    print(json.dumps(report, ensure_ascii=False, indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
