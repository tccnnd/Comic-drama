# Spec Review: video-provider-mainline

Review date: 2026-06-24
Reviewer: Codex acting from the accepted Kiro spec because Kiro is currently
unavailable
Spec version: v0.2.0
Status: ready for production; live scene-level real-video branch validated

## Executive Summary

The v0.2.0 video-provider-mainline feature is complete. The original qualified
pass has been upgraded with a live XL provider success run. The system can now
produce a real scene-level video clip, persist generation provenance, propagate
it into the canonical timeline, and surface provider readiness/provenance in
the Review Console. Local 2.5D remains the explicit fallback path.

## Acceptance Status

| Criterion | Status | Evidence |
| --- | --- | --- |
| AC-1 remote success | Pass | Live XL validation plus mock-provider success tests |
| AC-2 report fallback | Pass | Mock-provider failure tests and prior live 429 fallback run |
| AC-3 strict failure | Pass | Strict-mode tests and sanitized scene/provider error context |
| AC-4 `shot_plan` persistence | Pass | Unit and integration coverage; unchanged plans are not rewritten |
| AC-5 timeline provenance | Pass | Canonical timeline summary includes real/fallback counts |
| AC-6 Review Console visibility | Pass | Per-scene provenance plus provider readiness banner |
| AC-7 checks/sample workflow | Pass | Pytest, py_compile, node checks, local workflow, live XL validation |

Live AC-7 evidence:

```text
outputs/live_xl_ac7_20260624_161004/live_validation_result.json
outputs/live_xl_ac7_20260624_161004/clip_01.mp4
```

Observed live metadata:

```json
{
  "provider_id": "xl",
  "provider_label": "XL Aggregator",
  "is_real_video": true,
  "fallback_used": false,
  "attempts": 1,
  "timeline_summary": {
    "real_video_scene_count": 1,
    "fallback_scene_count": 0
  }
}
```

## Remaining Risks

- ComfyUI keyframe tunnel remains environment-blocked in this workspace. This
  is upstream of the video-provider mainline and does not invalidate the XL
  remote success branch.
- The successful live validation covers scene-level real-video rendering, not
  shot-level provider rendering.
- A later `generation_meta` schema migration is needed before adding
  shot-level output arrays, cost data, or provider usage fields.
- Live provider checks consume quota and should stay explicit and controlled.

## Recommended Next Feature

Implement shot-level real-video rendering only after accepting a dedicated spec.
Current behavior is:

```text
scene -> one provider call -> scene clip -> final concat
```

The next feature should become:

```text
scene -> shot_plan.shots[] -> per-shot provider calls
      -> shot concat -> scene clip -> final concat
```

Draft spec location:

```text
.kiro/specs/shot-level-video-rendering/
```

## Sign-off

No release blocker remains for v0.2.0. Future work should focus on shot-level
rendering, cost controls, provider/model selection, schema migration, and
Review Console shot-detail workflows.

