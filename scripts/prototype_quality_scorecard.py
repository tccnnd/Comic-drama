"""Build a manual quality scorecard for visual prototype outputs.

The scorecard is intentionally offline: it reads project snapshots and emits a
stable JSON template that humans or later automation can score without spending
provider quota.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prototype_gap_report import discover_project_files


SCORE_FIELDS = [
    "composition_intent",
    "subject_clarity",
    "constraint_adherence",
    "emotional_fit",
    "overall_usable",
]


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _scene_identifier(scene: dict[str, Any], fallback_order: int) -> str:
    return _text(scene.get("scene_id") or scene.get("id") or scene.get("scene")) or f"scene_{fallback_order:03d}"


def _shot_identifier(scene_id: str, shot: dict[str, Any], fallback_order: int) -> str:
    return _text(shot.get("shot_id")) or f"{scene_id}_shot_{fallback_order:02d}"


def _constraints(visual_prototype: dict[str, Any]) -> dict[str, list[str]]:
    source = _as_dict(visual_prototype.get("constraints"))
    return {
        "hard": [_text(item) for item in _as_list(source.get("hard")) if _text(item)],
        "soft": [_text(item) for item in _as_list(source.get("soft")) if _text(item)],
        "guidelines": [_text(item) for item in _as_list(source.get("guidelines")) if _text(item)],
    }


def _score_template() -> dict[str, Any]:
    return {field: None for field in SCORE_FIELDS}


def _review_template() -> dict[str, Any]:
    return {
        "reviewer": "",
        "reviewed_at": "",
        "evidence": "",
        "rationale": "",
    }


def _output_evidence(scene: dict[str, Any], assets: dict[str, Any], generation_meta: dict[str, Any]) -> dict[str, str]:
    return {
        "image_url": _text(assets.get("image_url") or scene.get("image_url") or scene.get("keyframe_url")),
        "image_path": _text(assets.get("image_path") or scene.get("image_path") or scene.get("keyframe")),
        "video_url": _text(assets.get("video_url") or scene.get("video_url") or scene.get("final_video_url")),
        "video_path": _text(assets.get("video_path") or scene.get("video_path") or scene.get("video") or scene.get("final_video_path")),
        "final_video_path": _text(assets.get("final_video_path") or scene.get("final_video_path")),
        "provider_output_path": _text(
            generation_meta.get("output_path")
            or generation_meta.get("video_path")
            or generation_meta.get("download_path")
        ),
    }


def _has_visual_evidence(entry: dict[str, Any]) -> bool:
    output = _as_dict(entry.get("output"))
    return any(_text(output.get(key)) for key in ("image_url", "image_path", "video_url", "video_path", "final_video_path", "provider_output_path"))


def _score_values(entry: dict[str, Any]) -> list[float]:
    scores = _as_dict(entry.get("scores"))
    values: list[float] = []
    for field in SCORE_FIELDS:
        value = scores.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(max(0.0, min(5.0, float(value))))
    return values


def entry_score_average(entry: dict[str, Any]) -> float | None:
    values = _score_values(entry)
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def build_project_entries(project: dict[str, Any], source_path: str | None = None) -> list[dict[str, Any]]:
    """Extract scoreable shot entries from one project snapshot."""
    project_id = _text(project.get("project_id"))
    entries: list[dict[str, Any]] = []

    for scene_index, scene in enumerate(_as_list(project.get("scenes")), start=1):
        if not isinstance(scene, dict):
            continue
        scene_id = _scene_identifier(scene, scene_index)
        scene_order = scene.get("order") or scene.get("scene") or scene_index
        shot_plan = _as_dict(scene.get("shot_plan"))
        shots = _as_list(shot_plan.get("shots"))
        assets = _as_dict(scene.get("assets"))
        generation_meta = _as_dict(scene.get("generation_meta"))

        for shot_index, shot in enumerate(shots, start=1):
            if not isinstance(shot, dict):
                continue
            shot_id = _shot_identifier(scene_id, shot, shot_index)
            visual_prototype = _as_dict(shot.get("visual_prototype"))
            visual_content = _as_dict(shot.get("visual_content"))
            prototype_id = _text(visual_prototype.get("id"))
            mode = _text(visual_prototype.get("mode")) or ("prototype_lock" if prototype_id else "unknown")
            gap = _as_dict(visual_prototype.get("gap"))
            entry_id = ":".join(
                [
                    project_id or "project",
                    scene_id,
                    shot_id,
                    mode,
                    prototype_id or "none",
                ]
            )
            entries.append(
                {
                    "entry_id": entry_id,
                    "project_id": project_id,
                    "source_path": source_path or "",
                    "scene_id": scene_id,
                    "scene_order": scene_order,
                    "scene_title": _text(scene.get("title")),
                    "shot_id": shot_id,
                    "shot_order": shot.get("shot_order") or shot_index,
                    "variant": mode,
                    "prototype_id": prototype_id,
                    "gap_reason": _text(gap.get("reason")),
                    "constraints": _constraints(visual_prototype),
                    "visual_content_source": _text(visual_content.get("_source")),
                    "visual_content": {
                        "shot_description": _text(visual_content.get("shot_description")),
                        "foreground": _text(visual_content.get("foreground")),
                        "background": _text(visual_content.get("background")),
                        "composition": _text(visual_content.get("composition")),
                        "motion": _text(visual_content.get("motion")),
                        "focus": _text(visual_content.get("focus")),
                    },
                    "output": _output_evidence(scene, assets, generation_meta),
                    "generation": {
                        "provider_id": _text(generation_meta.get("provider_id")),
                        "provider_label": _text(generation_meta.get("provider_label")),
                        "backend": _text(generation_meta.get("backend")),
                        "is_real_video": bool(generation_meta.get("is_real_video")),
                        "fallback_used": bool(generation_meta.get("fallback_used")),
                        "attempts": generation_meta.get("attempts") or 0,
                    },
                    "scores": _score_template(),
                    "review": _review_template(),
                    "decision": "unscored",
                    "notes": "",
                }
            )
    return entries


def summarize_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    variant_counts: Counter[str] = Counter()
    prototype_counts: Counter[str] = Counter()
    scored = 0
    scoreable = 0
    score_total = 0.0
    by_variant: dict[str, list[float]] = {}
    by_prototype: dict[str, list[float]] = {}

    for entry in entries:
        variant = _text(entry.get("variant")) or "unknown"
        prototype_id = _text(entry.get("prototype_id"))
        variant_counts[variant] += 1
        if prototype_id:
            prototype_counts[prototype_id] += 1
        if _has_visual_evidence(entry):
            scoreable += 1
        average = entry_score_average(entry)
        if average is None:
            continue
        scored += 1
        score_total += average
        by_variant.setdefault(variant, []).append(average)
        if prototype_id:
            by_prototype.setdefault(prototype_id, []).append(average)

    def _averages(source: dict[str, list[float]]) -> dict[str, float]:
        return {key: round(sum(values) / len(values), 3) for key, values in sorted(source.items()) if values}

    return {
        "total_entries": len(entries),
        "scoreable_entries": scoreable,
        "missing_visual_evidence": len(entries) - scoreable,
        "scored_entries": scored,
        "average_score": round(score_total / scored, 3) if scored else None,
        "variant_counts": dict(sorted(variant_counts.items())),
        "prototype_counts": dict(sorted(prototype_counts.items())),
        "average_by_variant": _averages(by_variant),
        "average_by_prototype": _averages(by_prototype),
    }


def build_scorecard(path: Path) -> dict[str, Any]:
    project_files = discover_project_files(path)
    entries: list[dict[str, Any]] = []
    for project_file in project_files:
        entries.extend(build_project_entries(_load_json(project_file), str(project_file)))
    return {
        "version": 1,
        "score_scale": "0-5; null means unscored",
        "score_fields": SCORE_FIELDS,
        "summary": summarize_entries(entries),
        "entries": entries,
    }


def summarize_scorecard(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    entries = _as_list(payload.get("entries"))
    normalized_entries = [entry for entry in entries if isinstance(entry, dict)]
    return {
        "version": 1,
        "score_fields": SCORE_FIELDS,
        "summary": summarize_entries(normalized_entries),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or summarize a visual prototype quality scorecard.")
    parser.add_argument("path", type=Path, help="project.json, project directory, workspace directory, or scorecard JSON with --summary")
    parser.add_argument("--summary", action="store_true", help="summarize a previously filled scorecard JSON")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    args = parser.parse_args(argv)

    payload = summarize_scorecard(args.path) if args.summary else build_scorecard(args.path)
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

