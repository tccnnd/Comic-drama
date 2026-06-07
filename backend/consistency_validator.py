"""Post-generation consistency validation for character identity and visual coherence.

This module provides automated quality checks after image/video generation:
1. Character identity drift detection (via reference image comparison)
2. Style consistency scoring across scenes
3. Lighting/color temperature continuity checks
4. Automated re-generation triggers when quality thresholds are not met

The validation pipeline:
  generate → validate → (pass: accept) | (fail: retry with stronger constraints)
"""
from __future__ import annotations

import json
import logging
import os
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Similarity thresholds (0.0 = completely different, 1.0 = identical)
CHARACTER_SIMILARITY_THRESHOLD = float(os.environ.get("CONSISTENCY_CHAR_THRESHOLD", "0.6"))
STYLE_SIMILARITY_THRESHOLD = float(os.environ.get("CONSISTENCY_STYLE_THRESHOLD", "0.7"))
PROP_SIMILARITY_THRESHOLD = float(os.environ.get("CONSISTENCY_PROP_THRESHOLD", "0.6"))
CAMERA_CONTINUITY_THRESHOLD = float(os.environ.get("CONSISTENCY_CAMERA_THRESHOLD", "0.6"))
MAX_VALIDATION_RETRIES = int(os.environ.get("CONSISTENCY_MAX_RETRIES", "1"))

# Feature: enable/disable consistency validation
CONSISTENCY_VALIDATION_ENABLED = os.environ.get(
    "CONSISTENCY_VALIDATION_ENABLED", "1"
).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class ValidationResult:
    """Result of a consistency validation check."""
    passed: bool
    score: float  # 0.0 to 1.0
    checks: list[ValidationCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationCheck:
    """Individual validation check result."""
    name: str
    passed: bool
    score: float
    details: str = ""
    severity: str = "warning"  # "warning" or "error"


# ---------------------------------------------------------------------------
# Image-based validation (histogram / structural comparison)
# ---------------------------------------------------------------------------

def _compute_color_histogram(image_path: Path) -> list[float] | None:
    """Compute a normalized color histogram for an image."""
    try:
        from PIL import Image
        img = Image.open(image_path).convert("RGB").resize((128, 128))
        pixels = list(img.getdata())
        # Simple 8-bin histogram per channel (24 bins total)
        bins = [0.0] * 24
        total = len(pixels)
        for r, g, b in pixels:
            bins[r // 32] += 1
            bins[8 + g // 32] += 1
            bins[16 + b // 32] += 1
        # Normalize
        return [v / total for v in bins]
    except Exception as exc:
        logger.warning("Failed to compute histogram for %s: %s", image_path, exc)
        return None


def _histogram_similarity(hist_a: list[float], hist_b: list[float]) -> float:
    """Compute histogram intersection similarity (0.0 to 1.0)."""
    if not hist_a or not hist_b or len(hist_a) != len(hist_b):
        return 0.0
    intersection = sum(min(a, b) for a, b in zip(hist_a, hist_b))
    return min(1.0, intersection)


def _compute_structural_hash(image_path: Path, hash_size: int = 16) -> str | None:
    """Compute a perceptual hash (average hash) for structural comparison."""
    try:
        from PIL import Image
        img = Image.open(image_path).convert("L").resize((hash_size, hash_size))
        pixels = list(img.getdata())
        avg = sum(pixels) / len(pixels)
        bits = "".join("1" if p > avg else "0" for p in pixels)
        return bits
    except Exception as exc:
        logger.warning("Failed to compute structural hash for %s: %s", image_path, exc)
        return None


def _hamming_similarity(hash_a: str, hash_b: str) -> float:
    """Compute similarity from hamming distance of two binary hash strings."""
    if not hash_a or not hash_b or len(hash_a) != len(hash_b):
        return 0.0
    matches = sum(a == b for a, b in zip(hash_a, hash_b))
    return matches / len(hash_a)


# ---------------------------------------------------------------------------
# Character identity validation
# ---------------------------------------------------------------------------

def validate_character_identity(
    generated_image: Path,
    reference_image: Path,
    character_name: str = "",
) -> ValidationCheck:
    """Validate that a generated image maintains character identity vs reference.

    Uses a combination of:
    - Color histogram similarity (clothing/hair color consistency)
    - Structural hash similarity (overall composition/pose)
    """
    if not generated_image.exists():
        return ValidationCheck(
            name=f"character_identity:{character_name}",
            passed=False,
            score=0.0,
            details="Generated image not found",
            severity="error",
        )
    if not reference_image.exists():
        return ValidationCheck(
            name=f"character_identity:{character_name}",
            passed=True,
            score=1.0,
            details="No reference image available, skipping validation",
            severity="warning",
        )

    # Color histogram comparison
    hist_gen = _compute_color_histogram(generated_image)
    hist_ref = _compute_color_histogram(reference_image)
    color_score = _histogram_similarity(hist_gen, hist_ref) if hist_gen and hist_ref else 0.5

    # Structural comparison
    hash_gen = _compute_structural_hash(generated_image)
    hash_ref = _compute_structural_hash(reference_image)
    struct_score = _hamming_similarity(hash_gen, hash_ref) if hash_gen and hash_ref else 0.5

    # Weighted combination (color is more important for character identity)
    combined_score = color_score * 0.6 + struct_score * 0.4
    passed = combined_score >= CHARACTER_SIMILARITY_THRESHOLD

    return ValidationCheck(
        name=f"character_identity:{character_name}",
        passed=passed,
        score=round(combined_score, 3),
        details=(
            f"Color similarity: {color_score:.3f}, "
            f"Structure similarity: {struct_score:.3f}, "
            f"Combined: {combined_score:.3f} "
            f"(threshold: {CHARACTER_SIMILARITY_THRESHOLD})"
        ),
        severity="warning" if not passed else "warning",
    )


# ---------------------------------------------------------------------------
# Style consistency validation (across scenes)
# ---------------------------------------------------------------------------

def validate_style_consistency(
    current_image: Path,
    previous_image: Path | None,
    style_reference: dict[str, str] | None = None,
) -> ValidationCheck:
    """Validate that the current scene maintains style consistency with previous scenes."""
    if previous_image is None or not previous_image.exists():
        return ValidationCheck(
            name="style_consistency",
            passed=True,
            score=1.0,
            details="No previous scene image for comparison",
        )
    if not current_image.exists():
        return ValidationCheck(
            name="style_consistency",
            passed=False,
            score=0.0,
            details="Current image not found",
            severity="error",
        )

    # Compare color palettes between scenes
    hist_curr = _compute_color_histogram(current_image)
    hist_prev = _compute_color_histogram(previous_image)
    color_score = _histogram_similarity(hist_curr, hist_prev) if hist_curr and hist_prev else 0.5

    # For style, we care more about overall color temperature than exact match
    # A score of 0.5+ is usually acceptable for different scenes in same style
    adjusted_threshold = STYLE_SIMILARITY_THRESHOLD * 0.7  # More lenient for cross-scene
    passed = color_score >= adjusted_threshold

    return ValidationCheck(
        name="style_consistency",
        passed=passed,
        score=round(color_score, 3),
        details=(
            f"Color palette similarity with previous scene: {color_score:.3f} "
            f"(threshold: {adjusted_threshold:.3f})"
        ),
        severity="warning",
    )


# ---------------------------------------------------------------------------
# Lighting continuity validation
# ---------------------------------------------------------------------------

def validate_lighting_continuity(
    current_image: Path,
    previous_image: Path | None,
) -> ValidationCheck:
    """Check if lighting direction and intensity are consistent between adjacent scenes."""
    if previous_image is None or not previous_image.exists():
        return ValidationCheck(
            name="lighting_continuity",
            passed=True,
            score=1.0,
            details="No previous scene for lighting comparison",
        )
    if not current_image.exists():
        return ValidationCheck(
            name="lighting_continuity",
            passed=False,
            score=0.0,
            details="Current image not found",
            severity="error",
        )

    try:
        from PIL import Image
        import statistics

        # Compare brightness distribution (proxy for lighting)
        curr_img = Image.open(current_image).convert("L").resize((64, 64))
        prev_img = Image.open(previous_image).convert("L").resize((64, 64))

        curr_pixels = list(curr_img.getdata())
        prev_pixels = list(prev_img.getdata())

        curr_mean = statistics.mean(curr_pixels)
        prev_mean = statistics.mean(prev_pixels)
        curr_std = statistics.stdev(curr_pixels) if len(curr_pixels) > 1 else 0
        prev_std = statistics.stdev(prev_pixels) if len(prev_pixels) > 1 else 0

        # Brightness difference (normalized)
        brightness_diff = abs(curr_mean - prev_mean) / 255.0
        contrast_diff = abs(curr_std - prev_std) / 128.0

        # Score: lower difference = higher score
        score = max(0.0, 1.0 - (brightness_diff * 0.6 + contrast_diff * 0.4))
        passed = score >= 0.5  # Lenient threshold for lighting

        return ValidationCheck(
            name="lighting_continuity",
            passed=passed,
            score=round(score, 3),
            details=(
                f"Brightness diff: {brightness_diff:.3f}, "
                f"Contrast diff: {contrast_diff:.3f}, "
                f"Score: {score:.3f}"
            ),
            severity="warning",
        )
    except Exception as exc:
        return ValidationCheck(
            name="lighting_continuity",
            passed=True,
            score=0.5,
            details=f"Validation skipped: {exc}",
        )


# ---------------------------------------------------------------------------
# Prop and camera continuity validation
# ---------------------------------------------------------------------------

def _prop_reference_path(prop_ref: dict[str, Any] | None) -> Path | None:
    if not isinstance(prop_ref, dict):
        return None
    value = (
        prop_ref.get("reference_image_path")
        or prop_ref.get("reference_image_abs_path")
        or prop_ref.get("image_path")
        or ""
    )
    text = str(value or "").strip()
    return Path(text) if text else None


def validate_prop_continuity(
    image: Path,
    prop_ref: dict[str, Any] | None,
) -> ValidationCheck:
    """Validate visual continuity for a recurring prop against its reference."""
    prop_id = ""
    if isinstance(prop_ref, dict):
        prop_id = str(prop_ref.get("prop_id") or prop_ref.get("name") or "").strip()
    name = f"prop_continuity:{prop_id}" if prop_id else "prop_continuity"
    reference = _prop_reference_path(prop_ref)
    if reference is None:
        return ValidationCheck(
            name=name,
            passed=True,
            score=0.0,
            details="No prop reference image available, skipping validation",
            severity="info",
        )
    if not reference.exists():
        return ValidationCheck(
            name=name,
            passed=True,
            score=0.0,
            details=f"Prop reference image not found: {reference}",
            severity="info",
        )
    if not image.exists():
        return ValidationCheck(
            name=name,
            passed=False,
            score=0.0,
            details="Current image not found",
            severity="error",
        )

    hist_image = _compute_color_histogram(image)
    hist_ref = _compute_color_histogram(reference)
    color_score = _histogram_similarity(hist_image, hist_ref) if hist_image and hist_ref else 0.5
    hash_image = _compute_structural_hash(image)
    hash_ref = _compute_structural_hash(reference)
    structural_score = _hamming_similarity(hash_image, hash_ref) if hash_image and hash_ref else 0.5
    combined_score = color_score * 0.55 + structural_score * 0.45
    passed = combined_score >= PROP_SIMILARITY_THRESHOLD
    return ValidationCheck(
        name=name,
        passed=passed,
        score=round(combined_score, 3),
        details=(
            f"Prop color similarity: {color_score:.3f}, "
            f"structure similarity: {structural_score:.3f}, "
            f"combined: {combined_score:.3f} "
            f"(threshold: {PROP_SIMILARITY_THRESHOLD})"
        ),
        severity="warning",
    )


def _scene_text_field(scene: dict[str, Any] | None, key: str) -> str:
    if not isinstance(scene, dict):
        return ""
    return str(scene.get(key) or "").strip().lower()


def _scene_float_field(scene: dict[str, Any] | None, key: str, default: float = 1.0) -> float:
    if not isinstance(scene, dict):
        return default
    try:
        return float(scene.get(key) or default)
    except (TypeError, ValueError):
        return default


def _camera_family(value: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if not text:
        return "unknown"
    if "push" in text or "zoom" in text or "dolly" in text:
        return "push"
    if "pan" in text or "tilt" in text or "truck" in text:
        return "pan"
    if "shake" in text or "handheld" in text:
        return "shake"
    if "static" in text or "locked" in text or "hold" in text:
        return "static"
    return text.split("_", 1)[0]


def evaluate_camera_continuity(
    scene: dict[str, Any],
    prev_scene: dict[str, Any] | None,
) -> ValidationCheck:
    """Rules-based camera continuity heuristic between adjacent scenes."""
    if not isinstance(prev_scene, dict) or not prev_scene:
        return ValidationCheck(
            name="camera_continuity",
            passed=True,
            score=1.0,
            details="No previous scene for camera comparison",
            severity="info",
        )

    current_camera = _scene_text_field(scene, "camera_movement") or _scene_text_field(scene, "camera")
    previous_camera = _scene_text_field(prev_scene, "camera_movement") or _scene_text_field(prev_scene, "camera")
    current_family = _camera_family(current_camera)
    previous_family = _camera_family(previous_camera)
    current_speed = _scene_float_field(scene, "camera_speed", 1.0)
    previous_speed = _scene_float_field(prev_scene, "camera_speed", 1.0)
    speed_delta = abs(current_speed - previous_speed)

    emotional_change = (
        _scene_text_field(scene, "emotion_tone") or _scene_text_field(scene, "emotion")
    ) != (
        _scene_text_field(prev_scene, "emotion_tone") or _scene_text_field(prev_scene, "emotion")
    )
    intent_change = _scene_text_field(scene, "scene_intent") != _scene_text_field(prev_scene, "scene_intent")
    focus_change = _scene_text_field(scene, "subject_focus") != _scene_text_field(prev_scene, "subject_focus")
    motivated_change = emotional_change or intent_change or focus_change
    family_changed = current_family != previous_family and current_family != "unknown" and previous_family != "unknown"
    abrupt_speed = speed_delta >= 0.65

    penalty = 0.0
    reasons: list[str] = []
    if family_changed:
        penalty += 0.28
        reasons.append(f"camera family changed {previous_family}->{current_family}")
    if abrupt_speed:
        penalty += min(0.35, speed_delta / 3.0)
        reasons.append(f"camera speed delta {speed_delta:.2f}")
    if (family_changed or abrupt_speed) and not motivated_change:
        penalty += 0.25
        reasons.append("no emotion/intent/focus change to motivate jump")
    if motivated_change and penalty:
        penalty = max(0.0, penalty - 0.25)
        reasons.append("change is motivated by scene context")

    score = max(0.0, min(1.0, 1.0 - penalty))
    passed = score >= CAMERA_CONTINUITY_THRESHOLD
    return ValidationCheck(
        name="camera_continuity",
        passed=passed,
        score=round(score, 3),
        details=(
            "; ".join(reasons)
            if reasons
            else "Camera movement and speed are continuous"
        ),
        severity="warning",
    )


# ---------------------------------------------------------------------------
# Composite validation
# ---------------------------------------------------------------------------

def validate_scene_generation(
    generated_image: Path,
    *,
    character_references: list[dict[str, Any]] | None = None,
    previous_scene_image: Path | None = None,
    style_config: dict[str, str] | None = None,
    scene_order: int = 0,
    enforce_hard_constraints: bool = True,
) -> ValidationResult:
    """Run all consistency checks on a generated scene image.

    Args:
        generated_image: Path to the newly generated image
        character_references: List of dicts with 'name' and 'reference_image_path'
        previous_scene_image: Path to the previous scene's keyframe for continuity
        style_config: Style configuration for style consistency check
        scene_order: Scene order number for logging
        enforce_hard_constraints: If True, character identity failures block acceptance

    Returns:
        ValidationResult with all check results
    """
    if not CONSISTENCY_VALIDATION_ENABLED:
        return ValidationResult(
            passed=True,
            score=1.0,
            warnings=["Consistency validation is disabled"],
        )

    checks: list[ValidationCheck] = []
    warnings: list[str] = []

    # 1. Character identity checks (HARD constraint when enforced)
    character_passed = True
    if character_references:
        for char_ref in character_references:
            ref_path_str = str(char_ref.get("reference_image_path") or char_ref.get("reference_image_abs_path") or "").strip()
            if not ref_path_str:
                continue
            ref_path = Path(ref_path_str)
            if not ref_path.exists():
                warnings.append(f"Character reference not found: {char_ref.get('name')}")
                continue
            check = validate_character_identity(
                generated_image,
                ref_path,
                character_name=str(char_ref.get("name", "")),
            )
            checks.append(check)
            if not check.passed and enforce_hard_constraints:
                check.severity = "error"
                character_passed = False

    # 2. Style consistency (soft constraint)
    style_check = validate_style_consistency(
        generated_image,
        previous_scene_image,
        style_config,
    )
    checks.append(style_check)

    # 3. Lighting continuity (soft constraint)
    lighting_check = validate_lighting_continuity(
        generated_image,
        previous_scene_image,
    )
    checks.append(lighting_check)

    # Compute overall result
    if not checks:
        return ValidationResult(passed=True, score=1.0, warnings=["No checks performed"])

    # Hard constraint: character identity must pass
    if enforce_hard_constraints and not character_passed:
        all_passed = False
    else:
        all_passed = all(c.passed for c in checks)

    avg_score = sum(c.score for c in checks) / len(checks)
    errors = [c.details for c in checks if not c.passed and c.severity == "error"]

    return ValidationResult(
        passed=all_passed,
        score=round(avg_score, 3),
        checks=checks,
        warnings=warnings + [c.details for c in checks if not c.passed and c.severity == "warning"],
        errors=errors,
        metadata={
            "scene_order": scene_order,
            "validated_at": time.time(),
            "checks_count": len(checks),
            "passed_count": sum(1 for c in checks if c.passed),
            "hard_constraints_enforced": enforce_hard_constraints,
            "character_identity_passed": character_passed,
        },
    )


# ---------------------------------------------------------------------------
# Validation-aware generation wrapper
# ---------------------------------------------------------------------------

def generate_with_validation(
    generate_fn,
    validate_fn,
    *,
    max_retries: int | None = None,
    strengthen_on_retry: bool = True,
) -> tuple[Any, ValidationResult]:
    """Generate content and validate it, retrying with stronger constraints if needed.

    Args:
        generate_fn: Callable that generates content and returns the output path
        validate_fn: Callable that takes the output path and returns ValidationResult
        max_retries: Maximum validation retries (default from config)
        strengthen_on_retry: Whether to strengthen constraints on retry

    Returns:
        Tuple of (generation result, final validation result)
    """
    if max_retries is None:
        max_retries = MAX_VALIDATION_RETRIES

    if not CONSISTENCY_VALIDATION_ENABLED:
        result = generate_fn(retry_attempt=0)
        return result, ValidationResult(passed=True, score=1.0, warnings=["Validation disabled"])

    best_result = None
    best_validation = None

    for attempt in range(max_retries + 1):
        result = generate_fn(retry_attempt=attempt)
        validation = validate_fn(result)

        if best_validation is None or validation.score > best_validation.score:
            best_result = result
            best_validation = validation

        if validation.passed:
            logger.info(
                "[consistency] Validation passed on attempt %d (score: %.3f)",
                attempt + 1, validation.score,
            )
            return result, validation

        logger.warning(
            "[consistency] Validation failed on attempt %d (score: %.3f): %s",
            attempt + 1, validation.score, validation.warnings[:2],
        )

        if attempt < max_retries:
            logger.info("[consistency] Retrying with strengthened constraints...")

    # Return best result even if validation didn't pass
    logger.warning(
        "[consistency] All %d attempts failed validation. Using best result (score: %.3f)",
        max_retries + 1, best_validation.score if best_validation else 0.0,
    )
    return best_result, best_validation or ValidationResult(passed=False, score=0.0)


# ---------------------------------------------------------------------------
# Project-level consistency report
# ---------------------------------------------------------------------------

def generate_consistency_report(project_id: str) -> dict[str, Any]:
    """Generate a consistency report for all scenes in a project.

    Checks:
    - Character identity consistency across all scenes
    - Style drift detection
    - Lighting continuity between adjacent scenes
    """
    from backend.project_runtime import load_project
    from backend.scene_renderer import project_dir, scene_dir, scene_latest_path

    project = load_project(project_id)
    scenes = sorted(
        [s for s in project.get("scenes", []) if isinstance(s, dict)],
        key=lambda s: int(s.get("order", 0)),
    )
    characters = project.get("characters", [])

    report: dict[str, Any] = {
        "project_id": project_id,
        "generated_at": time.time(),
        "scene_count": len(scenes),
        "character_count": len(characters),
        "overall_score": 0.0,
        "scenes": [],
        "character_drift": [],
        "recommendations": [],
    }

    prev_image: Path | None = None
    scene_scores: list[float] = []

    for scene in scenes:
        scene_order = int(scene.get("order", 0))
        scene_id_str = str(scene.get("scene_id") or f"scene_{scene_order:03d}")

        # Get the scene's keyframe image
        current_image = scene_latest_path(project_id, scene, "image")
        if not current_image or not current_image.exists():
            report["scenes"].append({
                "order": scene_order,
                "status": "no_image",
                "score": None,
            })
            continue

        # Build character references for this scene
        scene_chars = scene.get("characters") or []
        char_refs = []
        for char in characters:
            if str(char.get("name", "")) in [str(c) for c in scene_chars]:
                ref_path = str(char.get("reference_image_path") or "").strip()
                if ref_path:
                    abs_path = project_dir(project_id) / ref_path
                    if abs_path.exists():
                        char_refs.append({
                            "name": char.get("name"),
                            "reference_image_path": str(abs_path),
                        })

        # Validate
        validation = validate_scene_generation(
            current_image,
            character_references=char_refs,
            previous_scene_image=prev_image,
            scene_order=scene_order,
        )

        scene_scores.append(validation.score)
        report["scenes"].append({
            "order": scene_order,
            "status": "passed" if validation.passed else "failed",
            "score": validation.score,
            "checks": [
                {"name": c.name, "passed": c.passed, "score": c.score, "details": c.details}
                for c in validation.checks
            ],
            "warnings": validation.warnings,
        })

        prev_image = current_image

    # Overall score
    if scene_scores:
        report["overall_score"] = round(sum(scene_scores) / len(scene_scores), 3)

    # Generate recommendations
    failed_scenes = [s for s in report["scenes"] if s.get("status") == "failed"]
    if failed_scenes:
        report["recommendations"].append(
            f"{len(failed_scenes)} 个场景未通过一致性检查，建议重新生成"
        )

    no_image_scenes = [s for s in report["scenes"] if s.get("status") == "no_image"]
    if no_image_scenes:
        report["recommendations"].append(
            f"{len(no_image_scenes)} 个场景缺少关键帧图片"
        )

    if report["overall_score"] < STYLE_SIMILARITY_THRESHOLD:
        report["recommendations"].append(
            "整体风格一致性偏低，建议检查风格设置或使用更强的角色参考约束"
        )

    return report
