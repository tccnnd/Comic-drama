"""Multi-candidate generation and selection for keyframes and videos.

Generates N candidates for each asset, stores them, and lets the user pick the best one.
Supports both automatic scoring (via consistency_validator) and manual selection.

Data model:
  scene.assets.candidates = {
    "image": [
      {"id": "img_001", "path": "...", "url": "...", "score": 0.85, "selected": true, "created_at": "..."},
      {"id": "img_002", "path": "...", "url": "...", "score": 0.72, "selected": false, "created_at": "..."},
    ],
    "video": [...],
  }
"""
from __future__ import annotations

import logging
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_CANDIDATE_COUNT = 2
MAX_CANDIDATE_COUNT = 5


def generate_candidates(
    generate_fn: Callable[[int], Path],
    *,
    count: int = DEFAULT_CANDIDATE_COUNT,
    score_fn: Callable[[Path], float] | None = None,
    output_dir: Path | None = None,
    kind: str = "image",
) -> list[dict[str, Any]]:
    """Generate multiple candidates and optionally score them.

    Args:
        generate_fn: Callable that takes attempt index (0-based) and returns output Path
        count: Number of candidates to generate
        score_fn: Optional scoring function (0.0 to 1.0)
        output_dir: Directory to store candidates
        kind: Asset type ("image" or "video")

    Returns:
        List of candidate dicts sorted by score (best first)
    """
    count = max(1, min(MAX_CANDIDATE_COUNT, count))
    candidates: list[dict[str, Any]] = []

    for i in range(count):
        candidate_id = f"{kind}_{uuid.uuid4().hex[:6]}"
        try:
            path = generate_fn(i)
            if not path or not path.exists():
                logger.warning("[candidates] Attempt %d produced no output", i + 1)
                continue

            score = 0.5
            if score_fn:
                try:
                    score = score_fn(path)
                except Exception as exc:
                    logger.warning("[candidates] Scoring failed for attempt %d: %s", i + 1, exc)

            candidates.append({
                "id": candidate_id,
                "path": str(path),
                "filename": path.name,
                "score": round(score, 3),
                "selected": False,
                "attempt": i + 1,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "size_bytes": path.stat().st_size,
            })
            logger.info(
                "[candidates] %s attempt %d/%d: score=%.3f, size=%d KB",
                kind, i + 1, count, score, path.stat().st_size // 1024,
            )
        except Exception as exc:
            logger.error("[candidates] %s attempt %d/%d failed: %s", kind, i + 1, count, exc)
            candidates.append({
                "id": candidate_id,
                "path": "",
                "filename": "",
                "score": 0.0,
                "selected": False,
                "attempt": i + 1,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "error": str(exc),
            })

    # Sort by score descending, auto-select best
    valid = [c for c in candidates if c.get("path")]
    valid.sort(key=lambda c: c["score"], reverse=True)
    if valid:
        valid[0]["selected"] = True

    return candidates


def select_candidate(
    candidates: list[dict[str, Any]],
    candidate_id: str,
) -> dict[str, Any] | None:
    """Mark a specific candidate as selected (user choice).

    Returns the selected candidate dict, or None if not found.
    """
    selected = None
    for c in candidates:
        if c["id"] == candidate_id:
            c["selected"] = True
            selected = c
        else:
            c["selected"] = False
    return selected


def get_selected_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Get the currently selected candidate."""
    for c in candidates:
        if c.get("selected") and c.get("path"):
            return c
    # Fallback: return highest scored
    valid = [c for c in candidates if c.get("path")]
    if valid:
        valid.sort(key=lambda c: c.get("score", 0), reverse=True)
        return valid[0]
    return None


def store_candidates_on_scene(
    scene: dict[str, Any],
    kind: str,
    candidates: list[dict[str, Any]],
) -> None:
    """Store candidate list on a scene's assets."""
    assets = scene.setdefault("assets", {})
    asset_candidates = assets.setdefault("candidates", {})
    asset_candidates[kind] = candidates


def get_scene_candidates(scene: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """Get stored candidates for a scene."""
    assets = scene.get("assets", {})
    candidates = assets.get("candidates", {})
    return candidates.get(kind, [])
