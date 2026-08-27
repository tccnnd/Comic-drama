# Implementation Plan: video-provider-mainline

Status: complete
Last updated: 2026-06-24

## Overview

This spec made real video generation the primary scene rendering path while
keeping local 2.5D as an explicit, observable fallback. It introduced the
`shot_plan` and `generation_meta` contracts, persisted provider provenance,
propagated it into `canonical_timeline`, and surfaced it in the Review Console.

The original implementation validated local workflow and live report-mode
fallback. A later controlled XL live run validated the scene-level real-video
success branch:

```text
outputs/live_xl_ac7_20260624_161004/live_validation_result.json
```

Observed live result:

```text
provider_id=xl
is_real_video=true
fallback_used=false
attempts=1
real_video_scene_count=1
fallback_scene_count=0
```

Shot-level real-video rendering is not part of this spec. It is tracked in
`.kiro/specs/shot-level-video-rendering/`.

## Completed Tasks

- [x] 1. Add `build_shot_plan` helper and shared shot derivation
  - Added a persisted per-scene `shot_plan` derived from
    `temporal_spec.shots`.
  - Synthesizes a single full-duration shot when no temporal shots exist.
  - Requirements: FR-1.1, FR-1.2, FR-1.4, NFR-1, NFR-3.

- [x] 2. Unit-test `build_shot_plan`
  - Covers temporal shots and synthesized fallback shot plans.
  - Requirements: FR-1.1, FR-1.4.

- [x] 3. Adopt `VideoGenerationResult` as the shared provenance type
  - Added `generation_meta_from_result(...)`.
  - Sanitizes/truncates persisted error text.
  - Requirements: FR-3.1.

- [x] 4. Make `render_clip` emit a structured generation result
  - Added `render_clip_with_meta(...)` returning `(Path, VideoGenerationResult)`.
  - Kept `render_clip(...)` as a compatibility wrapper.
  - Requirements: FR-2.1, FR-2.2, FR-2.3, FR-3.1, NFR-4.

- [x] 5. Unify fallback policy
  - Shared `video_fallback_mode()` handles `VIDEO_FALLBACK_MODE` and
    `VIDEO_STRICT`.
  - Modes: `report`, `strict`, `silent`; default is `report`.
  - Requirements: FR-4.1, FR-4.2, FR-4.3, FR-4.4.

- [x] 6. Persist `shot_plan` and `generation_meta` on the scene
  - `scene_renderer` captures render results and persists latest-wins metadata.
  - Per-scene history remains intact.
  - Requirements: FR-1.3, FR-3.2, FR-3.4.

- [x] 7. Normalize new scene fields on load
  - Legacy projects without `shot_plan` or `generation_meta` load safely.
  - Missing provenance is treated as unknown.
  - Requirements: NFR-1.

- [x] 8. Add generation metadata and summary to canonical timeline
  - Picture clips include `metadata.generation`.
  - Timeline summary includes `real_video_scene_count` and
    `fallback_scene_count`.
  - Requirements: FR-6.1, FR-6.2, FR-6.3.

- [x] 9. Unit-test timeline provenance and counts
  - Mixed real/fallback/unknown scenes produce correct summary counts.
  - Requirements: FR-6.2, FR-6.3.

- [x] 10. Surface `generation_meta` in backend snapshot/runtime
  - Scene snapshots expose `shot_plan` and `generation_meta`.
  - Requirements: FR-3.3, FR-5.1.

- [x] 11. Expose `generation_meta` in project/scene API responses
  - Review Console consumers receive the provider provenance fields.
  - Requirements: FR-5.1.

- [x] 12. Review Console provenance display
  - Per-scene badge shows real video, fallback, or unknown.
  - Provider readiness is surfaced at project level.
  - Requirements: FR-5.2, FR-5.3.

- [x] 13. Integration tests with a mock provider
  - Covers remote success, report fallback, strict failure, retries,
    persistence, and history recording.
  - Requirements: AC-1, AC-2, AC-3, FR-2, FR-4.

- [x] 14. Backward-compatibility test
  - Legacy load, timeline build, and rerender path work without a real provider.
  - Requirements: NFR-1, AC-4.

- [x] 15. Documentation update
  - `docs/canonical_timeline.md` documents generation metadata,
    `shot_plan_source`, and summary counts.
  - `docs/troubleshooting_video_providers.md` documents operator handling.
  - Requirements: FR-6 and project doc-update rule.

- [x] 16. Checkpoint and validation
  - Python compile checks passed on edited backend/script modules.
  - Frontend syntax/helper checks passed.
  - Full pytest evidence from the latest pass: `240 passed, 10 warnings`.
  - Targeted provider tests after live validation:
    `tests/test_video_provider_mainline.py` passed with 16 tests.
  - Live scene-level XL validation passed:
    `outputs/live_xl_ac7_20260624_161004`.
  - Requirements: AC-7.

## Acceptance Checklist

- [x] AC-1 Remote provider success persists real-video metadata.
- [x] AC-2 Report-mode provider failure persists fallback metadata.
- [x] AC-3 Strict-mode provider failure fails the scene and records history.
- [x] AC-4 `shot_plan` is present and persisted after render.
- [x] AC-5 `canonical_timeline` references video media and carries generation
  metadata.
- [x] AC-6 Review Console shows generation badge/provider/attempt/error data.
- [x] AC-7 Compile, frontend, pytest, sample workflow, and controlled live
  scene-level real-video validation passed.

## Notes

- Do not treat this spec as multi-shot real-video support. Current real provider
  calls remain scene-level.
- Do not edit `scripts/video_provider_adapters.py` under this spec; provider
  wire formats are owned by provider-specific specs.
- Live provider runs consume quota and should remain explicit.

