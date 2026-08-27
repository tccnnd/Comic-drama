"""Tests for ``scripts.provider_viability_eval``.

Mirrors ``docs/provider_rubric.md`` §2–§3:

- 6 dimensions × 0–5 = 30 max
- F1–F7 hard fails override total score
- Status: ``pass`` (≥25, no fail) / ``smoke_only`` (15–24, no fail) /
  ``reject`` (any fail OR <15)

Each test loads a JSON fixture under ``tests/fixtures/viability/`` and
asserts both the structural decision (status, fail codes) and the
aggregated stats (sample_pass_rate, avg_vlm_score, total_score).

When ``scripts/provider_viability_gate.py`` is implemented, it should
import :func:`evaluate_provider_scorecard` from this module unchanged —
if you find yourself rewriting the eval logic in the gate, surface that
as a refactor candidate first.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.provider_viability_eval import (
    DIM_KEYS,
    FAIL_REASONS,
    ViabilityDecision,
    evaluate_provider_scorecard,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "viability"


def _load(name: str) -> dict:
    path = FIXTURES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def _fail_codes_from_reasons(reasons: list[str]) -> set[str]:
    """Extract F-codes from decision.fail_reasons by reverse-mapping."""
    return {code for code, msg in FAIL_REASONS.items() if msg in reasons}


# ---------------------------------------------------------------------------
# Scenario 1 — happy path: Kling (theoretical 25/30, no fails)
# ---------------------------------------------------------------------------


def test_pass_kling_returns_pass_with_no_fails() -> None:
    scorecard = _load("pass_kling.json")
    expected = scorecard.pop("expected_decision")

    decision = evaluate_provider_scorecard(scorecard)

    assert isinstance(decision, ViabilityDecision)
    assert decision.provider_id == "kling"
    assert decision.status == expected["status"], (
        f"expected {expected['status']}, got {decision.status}" f" (fails={decision.fail_reasons})"
    )
    assert decision.fail_reasons == expected["fail_reasons"]
    assert decision.total_score == expected["total_score"]
    # Aggregate stats from samples
    assert decision.sample_count == 5
    assert decision.sample_pass_rate == 1.0
    assert 0.7 < decision.avg_vlm_score < 0.9
    # 4+5+5+3+4+5 = 26? Check arithmetic
    expected_total = sum(scorecard["scores"][k] for k in DIM_KEYS)
    assert decision.total_score == expected_total


# ---------------------------------------------------------------------------
# Scenario 2 — domestic access fail: Runway (quality 5/5 but F3)
# ---------------------------------------------------------------------------


def test_domestic_fail_runway_rejected_by_f3() -> None:
    scorecard = _load("domestic_fail_runway.json")
    expected = scorecard.pop("expected_decision")

    decision = evaluate_provider_scorecard(scorecard)

    assert decision.provider_id == "runway"
    assert decision.status == "reject"
    assert decision.sample_pass_rate == 1.0  # quality was perfect
    fail_codes = _fail_codes_from_reasons(decision.fail_reasons)
    assert fail_codes == set(
        expected["fail_codes"]
    ), f"expected fail codes {expected['fail_codes']}, got {fail_codes}"
    # Verify the F3 message is exactly the rubric text
    assert FAIL_REASONS["F3"] in decision.fail_reasons


# ---------------------------------------------------------------------------
# Scenario 3 — output quality fail: Vidu (5 unusable → F2)
# ---------------------------------------------------------------------------


def test_quality_fail_vidu_rejected_by_f2() -> None:
    scorecard = _load("quality_fail_vidu.json")
    expected = scorecard.pop("expected_decision")

    decision = evaluate_provider_scorecard(scorecard)

    assert decision.provider_id == "vidu_low_quality"
    assert decision.status == "reject"
    assert decision.sample_pass_rate == 0.0
    assert decision.avg_vlm_score < 0.3
    fail_codes = _fail_codes_from_reasons(decision.fail_reasons)
    assert "F2" in fail_codes
    assert fail_codes == set(expected["fail_codes"])


# ---------------------------------------------------------------------------
# Scenario 4 — cost fail: premium provider (8.5 元/秒 → F4)
# ---------------------------------------------------------------------------


def test_cost_fail_premium_rejected_by_f4() -> None:
    scorecard = _load("cost_fail_premium.json")
    expected = scorecard.pop("expected_decision")

    decision = evaluate_provider_scorecard(scorecard)

    assert decision.provider_id == "premium_tier_provider"
    assert decision.status == "reject"
    assert decision.sample_pass_rate == 1.0  # quality was fine
    fail_codes = _fail_codes_from_reasons(decision.fail_reasons)
    assert "F4" in fail_codes
    assert fail_codes == set(expected["fail_codes"])


# ---------------------------------------------------------------------------
# Scenario 5 — missing evidence: Seedance (sample 4 empty paths → F7)
# ---------------------------------------------------------------------------


def test_missing_evidence_seedance_rejected_by_f7() -> None:
    scorecard = _load("missing_evidence_seedance.json")
    expected = scorecard.pop("expected_decision")

    decision = evaluate_provider_scorecard(scorecard)

    assert decision.provider_id == "seedance_incomplete_run"
    assert decision.status == "reject"
    fail_codes = _fail_codes_from_reasons(decision.fail_reasons)
    assert "F7" in fail_codes
    assert fail_codes == set(expected["fail_codes"])


# ---------------------------------------------------------------------------
# Schema & invariant guards — independent of any fixture
# ---------------------------------------------------------------------------


def test_dim_keys_match_rubric_six_dimensions() -> None:
    """The eval must score exactly the 6 dims from provider_rubric §2."""
    assert DIM_KEYS == (
        "api_stability",
        "doc_quality",
        "domestic_access",
        "cost",
        "output_quality",
        "comic_fit",
    )


def test_evaluate_rejects_out_of_range_dim_scores() -> None:
    bad = {
        "provider_id": "bogus",
        "scores": {
            "api_stability": 7,
            "doc_quality": 3,
            "domestic_access": 5,
            "cost": 3,
            "output_quality": 3,
            "comic_fit": 3,
        },
        "samples": [],
    }
    with pytest.raises(ValueError, match="must be in"):
        evaluate_provider_scorecard(bad)


def test_evaluate_requires_provider_id() -> None:
    with pytest.raises(ValueError, match="provider_id is required"):
        evaluate_provider_scorecard({"scores": {}, "samples": []})


def test_evaluate_rejects_no_scores_dict() -> None:
    with pytest.raises(ValueError, match="scores must be a dict"):
        evaluate_provider_scorecard({"provider_id": "x", "samples": []})


def test_empty_samples_yields_zero_stats_but_still_evaluates_dims() -> None:
    """A provider with no real samples yet can still be scored on dims
    alone — useful for the desktop-research theoretical pass."""
    scorecard = {
        "provider_id": "theoretical_only",
        "scores": {
            "api_stability": 4,
            "doc_quality": 4,
            "domestic_access": 5,
            "cost": 3,
            "output_quality": 4,
            "comic_fit": 5,
        },
        "samples": [],
    }
    decision = evaluate_provider_scorecard(scorecard)
    assert decision.sample_count == 0
    assert decision.sample_pass_rate == 0.0
    assert decision.avg_vlm_score == 0.0
    assert decision.total_score == 25
    assert decision.status == "pass"
    assert decision.fail_reasons == []


def test_total_score_under_15_is_rejected_even_without_fails() -> None:
    """Score 14 with no fails → still reject (below smoke_only threshold)."""
    scorecard = {
        "provider_id": "marginal",
        "scores": {
            "api_stability": 2,
            "doc_quality": 2,
            "domestic_access": 3,
            "cost": 3,
            "output_quality": 2,
            "comic_fit": 2,
        },
        "samples": [],
    }
    decision = evaluate_provider_scorecard(scorecard)
    assert decision.total_score == 14
    assert decision.status == "reject"
    assert decision.fail_reasons == []


def test_smoke_only_bucket_for_15_to_24_with_no_fails() -> None:
    scorecard = {
        "provider_id": "backup",
        "scores": {
            "api_stability": 4,
            "doc_quality": 3,
            "domestic_access": 5,
            "cost": 4,
            "output_quality": 3,
            "comic_fit": 3,
        },
        "samples": [],
    }
    decision = evaluate_provider_scorecard(scorecard)
    assert decision.total_score == 22
    assert decision.status == "smoke_only"
    assert decision.fail_reasons == []
