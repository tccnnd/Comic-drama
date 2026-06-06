"""Continuity governance aggregation and policy helpers.

The validator remains the stateless scoring engine. This module owns verdict
aggregation, report/block policy decisions, and project-level ledger rollups.
"""
from __future__ import annotations

import logging
import os
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from backend.consistency_validator import (
    CAMERA_CONTINUITY_THRESHOLD,
    CHARACTER_SIMILARITY_THRESHOLD,
    PROP_SIMILARITY_THRESHOLD,
    STYLE_SIMILARITY_THRESHOLD,
    ValidationCheck,
    evaluate_camera_continuity,
    validate_character_identity,
    validate_lighting_continuity,
    validate_prop_continuity,
    validate_style_consistency,
)

logger = logging.getLogger(__name__)

DIMENSIONS = ("character", "lighting", "environment", "prop", "camera")
STATUS_ORDER = {"fail": 3, "warn": 2, "pass": 1, "info": 0, "not_evaluated": 0}
DEFAULT_THRESHOLDS = {
    "character": CHARACTER_SIMILARITY_THRESHOLD,
    "lighting": 0.5,
    "environment": STYLE_SIMILARITY_THRESHOLD * 0.7,
    "prop": PROP_SIMILARITY_THRESHOLD,
    "camera": CAMERA_CONTINUITY_THRESHOLD,
}


def governance_policy_mode(value: str | None = None) -> str:
    mode = (value or os.environ.get("CONSISTENCY_POLICY_MODE", "report")).strip().lower()
    return mode if mode in {"report", "block"} else "report"


def utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _as_path(value: object) -> Path | None:
    if isinstance(value, Path):
        return value
    text = str(value or "").strip()
    return Path(text) if text else None


def _image_path(images: dict[str, Any] | None, *keys: str) -> Path | None:
    if not isinstance(images, dict):
        return None
    for key in keys:
        path = _as_path(images.get(key))
        if path is not None:
            return path
    return None


def _info_check(name: str, details: str, score: float = 0.0) -> ValidationCheck:
    return ValidationCheck(name=name, passed=True, score=score, details=details, severity="info")


def _exception_check(name: str, exc: Exception) -> ValidationCheck:
    return _info_check(name, f"Validation skipped: {exc}", score=0.0)


def _check_status(dimension: str, check: ValidationCheck) -> str:
    if str(check.severity or "").lower() == "info":
        return "info"
    if check.passed:
        return "pass"
    if str(check.severity or "").lower() == "error" or dimension == "character":
        return "fail"
    return "warn"


def _dimension_from_checks(dimension: str, checks: list[ValidationCheck]) -> dict[str, Any]:
    if not checks:
        checks = [_info_check(f"{dimension}_continuity", "No check performed")]
    statuses = [_check_status(dimension, check) for check in checks]
    meaningful = [status for status in statuses if status != "info"]
    status = "info"
    if any(status == "fail" for status in meaningful):
        status = "fail"
    elif any(status == "warn" for status in meaningful):
        status = "warn"
    elif meaningful:
        status = "pass"

    scores = [float(check.score or 0.0) for check in checks]
    score = min(scores) if scores else 0.0
    reasons = [str(check.details or "").strip() for check in checks if str(check.details or "").strip()]
    threshold = DEFAULT_THRESHOLDS.get(dimension, 0.0)
    return {
        "status": status,
        "score": round(score, 3),
        "threshold": round(float(threshold or 0.0), 3),
        "reason": "; ".join(reasons),
        "checks": [
            {
                "name": check.name,
                "status": _check_status(dimension, check),
                "score": round(float(check.score or 0.0), 3),
                "reason": str(check.details or ""),
                "severity": str(check.severity or "warning"),
            }
            for check in checks
        ],
    }


def _overall_status(dimensions: dict[str, dict[str, Any]]) -> str:
    statuses = [str(item.get("status") or "not_evaluated") for item in dimensions.values()]
    meaningful = [status for status in statuses if status != "info"]
    if not meaningful:
        return "not_evaluated"
    if "fail" in meaningful:
        return "fail"
    if "warn" in meaningful:
        return "warn"
    return "pass"


def _character_refs(project: dict[str, Any], scene: dict[str, Any]) -> list[dict[str, Any]]:
    scene_names = {str(name).strip() for name in scene.get("characters") or [] if str(name).strip()}
    refs: list[dict[str, Any]] = []
    for character in project.get("characters", []) or []:
        if not isinstance(character, dict):
            continue
        name = str(character.get("name") or "").strip()
        if scene_names and name not in scene_names:
            continue
        ref_path = str(character.get("reference_image_path") or character.get("reference_image_abs_path") or "").strip()
        if not ref_path:
            continue
        refs.append({"name": name, "reference_image_path": ref_path})
    return refs


def _production_bible(project: dict[str, Any]) -> dict[str, Any]:
    bible = project.get("production_bible")
    if isinstance(bible, dict):
        return bible
    return {}


def _scene_prop_tokens(scene: dict[str, Any]) -> set[str]:
    tokens = {str(item).strip() for item in scene.get("props") or [] if str(item).strip()}
    return tokens


def _props_for_scene(project: dict[str, Any], scene: dict[str, Any]) -> list[dict[str, Any]]:
    bible = _production_bible(project)
    props = bible.get("props") if isinstance(bible.get("props"), list) else project.get("props", [])
    scene_id = str(scene.get("scene_id") or "").strip()
    scene_order = str(scene.get("order") or "").strip()
    scene_tokens = _scene_prop_tokens(scene)
    matches: list[dict[str, Any]] = []
    for prop in props or []:
        if not isinstance(prop, dict):
            continue
        prop_id = str(prop.get("prop_id") or prop.get("id") or "").strip()
        prop_name = str(prop.get("name") or "").strip()
        prop_scenes = {str(item).strip() for item in prop.get("scenes") or [] if str(item).strip()}
        listed_for_scene = scene_id in prop_scenes or scene_order in prop_scenes
        named_in_scene = bool(scene_tokens & {prop_id, prop_name})
        if listed_for_scene or named_in_scene:
            matches.append(prop)
    return matches


def evaluate_scene_governance(
    project: dict[str, Any],
    scene: dict[str, Any],
    images: dict[str, Any] | None = None,
    prev_image: Path | str | None = None,
    prev_scene: dict[str, Any] | None = None,
    policy_mode: str | None = None,
) -> dict[str, Any]:
    current_image = _image_path(images, "current_image", "current", "image")
    previous_image = _as_path(prev_image) or _image_path(images, "previous_image", "previous", "prev")

    dimension_checks: dict[str, list[ValidationCheck]] = {dimension: [] for dimension in DIMENSIONS}
    if current_image is None:
        for dimension in DIMENSIONS:
            dimension_checks[dimension].append(_info_check(f"{dimension}_continuity", "No current image available"))
    else:
        character_refs = _character_refs(project, scene)
        if character_refs:
            for ref in character_refs:
                try:
                    dimension_checks["character"].append(
                        validate_character_identity(
                            current_image,
                            Path(str(ref.get("reference_image_path") or "")),
                            character_name=str(ref.get("name") or ""),
                        )
                    )
                except Exception as exc:
                    dimension_checks["character"].append(_exception_check("character_identity", exc))
        else:
            dimension_checks["character"].append(_info_check("character_identity", "No character reference image available"))

        try:
            dimension_checks["environment"].append(validate_style_consistency(current_image, previous_image))
        except Exception as exc:
            dimension_checks["environment"].append(_exception_check("style_consistency", exc))
        try:
            dimension_checks["lighting"].append(validate_lighting_continuity(current_image, previous_image))
        except Exception as exc:
            dimension_checks["lighting"].append(_exception_check("lighting_continuity", exc))

        scene_props = _props_for_scene(project, scene)
        if scene_props:
            for prop in scene_props:
                try:
                    dimension_checks["prop"].append(validate_prop_continuity(current_image, prop))
                except Exception as exc:
                    dimension_checks["prop"].append(_exception_check("prop_continuity", exc))
        else:
            dimension_checks["prop"].append(_info_check("prop_continuity", "No tracked prop in scene"))

        try:
            dimension_checks["camera"].append(evaluate_camera_continuity(scene, prev_scene))
        except Exception as exc:
            dimension_checks["camera"].append(_exception_check("camera_continuity", exc))

    dimensions = {
        dimension: _dimension_from_checks(dimension, checks)
        for dimension, checks in dimension_checks.items()
    }
    status = _overall_status(dimensions)
    offending = [
        dimension
        for dimension, data in dimensions.items()
        if str(data.get("status") or "") in {"warn", "fail"}
    ]
    verdict = {
        "version": 1,
        "scene_id": str(scene.get("scene_id") or "").strip(),
        "scene_order": int(scene.get("order") or 0),
        "status": status,
        "evaluated_at": utc_iso(),
        "dimensions": dimensions,
        "offending_dimensions": offending,
        "policy": {"mode": governance_policy_mode(policy_mode), "action": "recorded"},
        "deliverable": True,
    }
    return apply_governance_policy(verdict, policy_mode)


def apply_governance_policy(verdict: dict[str, Any], mode: str | None = None) -> dict[str, Any]:
    result = deepcopy(verdict) if isinstance(verdict, dict) else {}
    policy_mode = governance_policy_mode(mode or result.get("policy", {}).get("mode"))
    status = str(result.get("status") or "not_evaluated")
    action = "recorded"
    deliverable = bool(result.get("deliverable", True))
    if policy_mode == "block" and status == "fail":
        deliverable = False
        action = "blocked"
    result["deliverable"] = deliverable
    result["policy"] = {"mode": policy_mode, "action": action}
    if status in {"warn", "fail"}:
        logger.warning(
            "[governance] scene=%s status=%s mode=%s action=%s offending=%s",
            result.get("scene_id") or result.get("scene_order") or "",
            status,
            policy_mode,
            action,
            ",".join(result.get("offending_dimensions") or []),
        )
    return result


def _normalized_governance(scene: dict[str, Any]) -> dict[str, Any]:
    governance = scene.get("governance")
    if isinstance(governance, dict) and governance:
        return governance
    return {
        "version": 1,
        "scene_id": str(scene.get("scene_id") or "").strip(),
        "scene_order": int(scene.get("order") or 0),
        "status": "not_evaluated",
        "dimensions": {},
        "offending_dimensions": [],
        "policy": {"mode": governance_policy_mode(), "action": "none"},
        "deliverable": True,
    }


def build_continuity_ledger(project: dict[str, Any]) -> dict[str, Any]:
    scenes = [scene for scene in project.get("scenes", []) or [] if isinstance(scene, dict)]
    status_counts = {status: 0 for status in ("pass", "warn", "fail", "not_evaluated")}
    dimension_passes = {dimension: 0 for dimension in DIMENSIONS}
    dimension_totals = {dimension: 0 for dimension in DIMENSIONS}
    offending_scenes: list[dict[str, Any]] = []
    blocked_count = 0

    for scene in scenes:
        governance = _normalized_governance(scene)
        status = str(governance.get("status") or "not_evaluated")
        if status == "info":
            status = "not_evaluated"
        if status not in status_counts:
            status = "not_evaluated"
        status_counts[status] += 1
        if status in {"warn", "fail"}:
            offending_scenes.append(
                {
                    "scene_id": str(governance.get("scene_id") or scene.get("scene_id") or "").strip(),
                    "scene_order": int(governance.get("scene_order") or scene.get("order") or 0),
                    "status": status,
                    "offending_dimensions": list(governance.get("offending_dimensions") or []),
                }
            )
        if governance.get("deliverable") is False:
            blocked_count += 1
        dimensions = governance.get("dimensions") if isinstance(governance.get("dimensions"), dict) else {}
        for dimension in DIMENSIONS:
            data = dimensions.get(dimension) if isinstance(dimensions.get(dimension), dict) else {}
            dim_status = str(data.get("status") or "")
            if dim_status in {"pass", "warn", "fail"}:
                dimension_totals[dimension] += 1
                if dim_status == "pass":
                    dimension_passes[dimension] += 1

    pass_rates = {
        dimension: round(dimension_passes[dimension] / dimension_totals[dimension], 3)
        if dimension_totals[dimension]
        else 0.0
        for dimension in DIMENSIONS
    }
    return {
        "version": 1,
        "evaluated_scene_count": len(scenes),
        "status_counts": status_counts,
        "dimension_pass_rates": pass_rates,
        "offending_scenes": offending_scenes,
        "policy_mode": governance_policy_mode(),
        "blocked_scene_count": blocked_count,
    }
