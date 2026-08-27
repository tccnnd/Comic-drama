"""Provider viability evaluation — deterministic, pure-function gate.

Companion to:
- ``docs/provider_rubric.md`` (rubric definition, 6 dims × 0–5)
- ``docs/provider_research.md`` (candidate providers, theoretical scores)
- ``scripts/provider_viability_gate.py`` (IO wrapper CLI, reads scorecard
  JSON and emits a decision JSON)

Design rule:
    This module is pure-functional — no I/O, no logging, no subprocess, no
    network. That keeps it trivially testable and lets the gate script
    compose it however it wants (CLI / server endpoint / library).

Scorecard JSON shape (manual fill, before any real API call):

    {
      "provider_id": "kling",
      "evaluated_at": "2026-06-24",
      "evaluator": "name",
      "samples": [
        {
          "scene": 1,
          "type": "character_closeup",
          "expected_style": "anime",
          "usable": true,
          "vlm_score": 0.85,
          "duration_seconds": 4,
          "cost_per_second_cny": 1.2,
          "latency_ms": 8000,
          "evidence_paths": {
            "image": "outputs/viability/kling/scene_01_keyframe.png",
            "video": "outputs/viability/kling/scene_01_video.mp4"
          }
        }
      ],
      "scores": {
        "api_stability": 4,
        "doc_quality": 4,
        "domestic_access": 5,
        "cost": 3,
        "output_quality": 4,
        "comic_fit": 5
      },
      "flags": {
        "license_clear": true,
        "compliance_blocked": false
      },
      "manual_notes": "optional free text"
    }

Decision output (``ViabilityDecision``):

    {
      "provider_id": "kling",
      "status": "pass" | "smoke_only" | "reject",
      "total_score": 26,
      "fail_reasons": [],
      "sample_pass_rate": 1.0,
      "avg_vlm_score": 0.85,
      "sample_count": 5
    }
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

DecisionStatus = Literal["pass", "smoke_only", "reject"]

DIM_KEYS: tuple[str, ...] = (
    "api_stability",
    "doc_quality",
    "domestic_access",
    "cost",
    "output_quality",
    "comic_fit",
)

# F1–F7 mirror ``docs/provider_rubric.md`` §3, plus F7 (evidence missing)
# which is enforced at the gate level because no scorecard can be valid
# without evidence paths.
FAIL_REASONS: dict[str, str] = {
    "F1": "API 不可用 (api_stability=0)",
    "F2": "实测全废 (>=5 sample 全 unusable)",
    "F3": "国内完全无法访问 (domestic_access=0)",
    "F4": "价格不可承受 (任意 sample cost_per_second_cny > 5)",
    "F5": "版权风险 (license_clear=false)",
    "F6": "已被监管下架 (compliance_blocked=true)",
    "F7": "evidence 缺失 (任意 sample 缺 image/video path)",
}


@dataclass(frozen=True)
class ViabilityDecision:
    provider_id: str
    status: DecisionStatus
    total_score: int
    fail_reasons: list[str] = field(default_factory=list)
    sample_pass_rate: float = 0.0
    avg_vlm_score: float = 0.0
    sample_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _check_scorecard_shape(scorecard: dict[str, Any]) -> None:
    if not isinstance(scorecard, dict):
        raise ValueError("scorecard must be a dict")
    if "provider_id" not in scorecard:
        raise ValueError("scorecard.provider_id is required")
    scores = scorecard.get("scores")
    if not isinstance(scores, dict):
        raise ValueError("scorecard.scores must be a dict")


def _validate_dim_scores(provider_id: str, scores: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in DIM_KEYS:
        raw = scores.get(key, 0)
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{provider_id}: scores[{key}] must be int, got {raw!r}") from exc
        if value < 0 or value > 5:
            raise ValueError(f"{provider_id}: scores[{key}]={value} must be in [0, 5]")
        out[key] = value
    return out


def _compute_sample_stats(samples: list[dict[str, Any]]) -> tuple[float, float, int]:
    sample_count = len(samples)
    if not sample_count:
        return 0.0, 0.0, 0
    usable_count = sum(1 for s in samples if s.get("usable"))
    pass_rate = usable_count / sample_count
    vlm_scores = [
        float(s["vlm_score"])
        for s in samples
        if isinstance(s, dict) and s.get("vlm_score") is not None
    ]
    avg_vlm = (sum(vlm_scores) / len(vlm_scores)) if vlm_scores else 0.0
    return pass_rate, avg_vlm, sample_count


def _detect_fails(
    dims: dict[str, int],
    samples: list[dict[str, Any]],
    flags: dict[str, Any],
) -> list[str]:
    fails: list[str] = []
    if dims["api_stability"] == 0:
        fails.append("F1")
    if len(samples) >= 5 and all(not s.get("usable") for s in samples):
        fails.append("F2")
    if dims["domestic_access"] == 0:
        fails.append("F3")
    if any(float(s.get("cost_per_second_cny", 0)) > 5.0 for s in samples):
        fails.append("F4")
    if not flags.get("license_clear", True):
        fails.append("F5")
    if flags.get("compliance_blocked", False):
        fails.append("F6")
    for s in samples:
        if not isinstance(s, dict):
            continue
        evidence = s.get("evidence_paths") or {}
        if not evidence.get("image") or not evidence.get("video"):
            fails.append("F7")
            break
    return fails


def _decide_status(total_score: int, fails: list[str]) -> DecisionStatus:
    if fails:
        return "reject"
    if total_score >= 25:
        return "pass"
    if total_score >= 15:
        return "smoke_only"
    return "reject"


def evaluate_provider_scorecard(scorecard: dict[str, Any]) -> ViabilityDecision:
    """Evaluate a single provider scorecard and return a decision.

    Pure function. Validates shape, aggregates dim + sample stats, applies
    F1–F7 fail rules from the rubric, then buckets into pass / smoke_only
    / reject based on total_score and fails.
    """
    _check_scorecard_shape(scorecard)
    provider_id = str(scorecard["provider_id"])
    dims = _validate_dim_scores(provider_id, scorecard["scores"])
    samples = scorecard.get("samples") or []
    flags = scorecard.get("flags") or {}
    pass_rate, avg_vlm, sample_count = _compute_sample_stats(samples)
    fails = _detect_fails(dims, samples, flags)
    total = sum(dims.values())
    status = _decide_status(total, fails)
    return ViabilityDecision(
        provider_id=provider_id,
        status=status,
        total_score=total,
        fail_reasons=[FAIL_REASONS[c] for c in fails],
        sample_pass_rate=pass_rate,
        avg_vlm_score=avg_vlm,
        sample_count=sample_count,
    )
