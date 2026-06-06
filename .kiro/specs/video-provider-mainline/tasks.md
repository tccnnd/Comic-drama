
# Implementation Plan: video-provider-mainline

## Overview

Make real video generation the primary scene rendering path with local 2.5D as
an explicit, observable fallback. Work proceeds bottom-up: define the
`shot_plan` and `generation_meta` contracts first, thread the structured
generation result through `render_clip`, persist provenance, surface it in the
canonical timeline, then expose it in the API and review console. Each task is
scoped, references requirements, and is implementable by Codex from this spec.

Handoff note: all backend/script files here are Codex-owned per
`docs/collaboration_baseline.md`. Do NOT edit `scripts/video_provider_adapters.py`
(owned by the `alibaba-video-provider` spec).

## Status (current)

- Complete: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16.
- AC-7: qualified pass — sample workflow ran end-to-end with
  `--keyframe-provider local`, producing a final video and validating shot_plan
  + generation provenance + live report-mode fallback. Real-video branch not
  exercised end-to-end (remote provider 429); ComfyUI keyframe tunnel remains
  separately environment-blocked.
- Release blockers: none. Optional: re-validate the real-video branch when a
  remote provider has quota or the ComfyUI path is reachable.

## Tasks

- [x] 1. Add `build_shot_plan` helper and shared shot derivation
  - In `scripts/run_workflow.py`, add `build_shot_plan(scene) -> dict`
    producing the §4.1 schema.
  - Extract the per-shot derivation currently inlined in
    `build_canonical_timeline` into a shared helper so timeline `shot_timeline`
    and `shot_plan` are identical.
  - Synthesize a single full-duration shot when `temporal_spec.shots` is empty.
  - _Requirements: FR-1.1, FR-1.2, FR-1.4, NFR-1, NFR-3_

- [x] 2. Unit-test `build_shot_plan`
  - Scene with `temporal_spec.shots` → contiguous shots summing to scene
    duration; ids/labels/camera fields mapped.
  - Scene without shots → `source="synthesized"`, one shot, full duration.
  - _Requirements: FR-1.1, FR-1.4_

- [x] 3. Adopt `VideoGenerationResult` as the shared provenance type
  - In `backend/video_generation.py`, add a helper
    `generation_meta_from_result(result, requested_provider, fallback_mode) -> dict`
    producing the §4.2 schema (sanitized error, ISO timestamp).
  - Ensure error text is truncated and free of credentials/URLs with query
    params.
  - _Requirements: FR-3.1, Security considerations_

- [x] 4. Make `render_clip` emit a structured generation result
  - Done: `render_clip_with_meta` returns `(Path, VideoGenerationResult)`;
    `render_clip` remains a compatibility wrapper. Evidence:
    `scripts/run_workflow.py:5091` (`render_clip_with_meta`),
    `scripts/run_workflow.py:5299` (`render_clip` wrapper).
  - Refactor `render_clip` in `scripts/run_workflow.py` to build a
    `VideoGenerationResult` for the chosen backend (comfyui/remote/local),
    capturing `attempts`, `is_real_video`, `fallback_used`, `error`,
    `warnings`.
  - Keep existing dispatch and retry/backoff; do not change provider wire
    calls.
  - Return the result alongside the clip path (e.g. via an out-param object or
    a new `render_clip_with_meta` wrapper) without breaking current callers.
  - _Requirements: FR-2.1, FR-2.2, FR-2.3, FR-3.1, NFR-4_

- [x] 5. Unify fallback policy
  - Done: shared `video_fallback_mode()` sources `VIDEO_FALLBACK_MODE` /
    `VIDEO_STRICT` for both `render_clip` and `generate_scene_video_with_retry`.
  - Source `VIDEO_FALLBACK_MODE` and `VIDEO_STRICT` from one place shared by
    `render_clip` and `generate_scene_video_with_retry`.
  - `strict`/`VIDEO_STRICT` → raise on exhausted retries; `report` → flagged
    2.5D fallback; `silent` → legacy quiet fallback.
  - Default mode is `report`.
  - _Requirements: FR-4.1, FR-4.2, FR-4.3, FR-4.4, DD-3_

- [x] 6. Persist `shot_plan` and `generation_meta` on the scene
  - Done: `scene_renderer` captures `render_result`, maps it via
    `generation_meta_from_result`, and persists `generation_meta` + `shot_plan`
    through `update_scene_generation_meta`. Evidence:
    `backend/scene_renderer.py:390`, `backend/scene_renderer.py:505`.
  - In `backend/scene_renderer.py` (`generate_scene_assets`,
    `rerender_scene_video`), capture the generation result from the refactored
    `render_clip` and write `scene["generation_meta"]` (latest-wins) and
    `scene["shot_plan"]` through the existing scene save path.
  - Keep the existing per-scene history log behavior.
  - _Requirements: FR-1.3, FR-3.2, FR-3.4_

- [x] 7. Normalize new scene fields on load (backward-compat)
  - In `backend/project_models.py`, default/normalize `shot_plan` and
    `generation_meta` when loading scenes that lack them (no error;
    `generation_meta` absent → treated as unknown provenance).
  - _Requirements: NFR-1, FR-4 (unknown state)_

- [x] 8. Add generation metadata + summary to canonical timeline
  - In `build_canonical_timeline`, add a `generation` block to each picture
    clip's `metadata` and `shot_plan_source`.
  - Add project-level `real_video_scene_count` and `fallback_scene_count` to
    `summary`.
  - Preserve existing media-reference precedence (video then image).
  - _Requirements: FR-6.1, FR-6.2, FR-6.3_

- [x] 9. Unit-test timeline provenance and counts
  - Mixed scenes (some real video, some fallback, some unknown) produce correct
    `summary` counts and per-clip `generation` metadata.
  - _Requirements: FR-6.2, FR-6.3_

- [x] 10. Surface `generation_meta` in backend snapshot/runtime
  - In `backend/project_runtime.py`, include `shot_plan` / `generation_meta`
    in scene snapshot and timeline assembly.
  - _Requirements: FR-3.3, FR-5.1_

- [x] 11. Expose `generation_meta` in the project/scene API
  - In `backend/app.py`, ensure scene/project API responses consumed by the
    review console include `generation_meta`.
  - _Requirements: FR-5.1_

- [x] 12. Review console provenance display (frontend)
  - Done in active frontend modules: `frontend/api.js`, `frontend/events.js`,
    `frontend/render.js`, `frontend/state.js`, `frontend/styles.css` (provider
    status + per-scene provenance display).
  - In `frontend/app.js`, render per-scene: real-video vs fallback badge,
    provider label, attempts, and failure reason when present; show "unknown"
    when metadata absent.
  - Surface active video provider + readiness at project level using existing
    `/api/video-providers` and `/api/video-providers/status`.
  - Define empty/loading/error states for the badge area.
  - _Requirements: FR-5.2, FR-5.3_

- [x] 13. Integration tests with a mock provider  **(DONE)**
  - Provider-boundary coverage added (no `render_clip_with_meta` stub), so
    retries, fallback-mode branching, metadata serialization, persistence, and
    strict-mode history are all exercised:
    `test_mock_remote_success_persists_real_video_metadata`,
    `test_mock_remote_report_failure_persists_fallback_metadata`,
    `test_mock_remote_strict_failure_records_failed_history_without_video_asset`.
  - Remote success → `is_real_video=true`, `fallback_used=false`, persisted.
  - Report-mode failure → fallback clip written, `fallback_used=true`,
    attempts/error/warnings persisted.
  - Strict-mode failure → exception propagates, `failed` history recorded by
    `scene_renderer`, no video asset written. No runtime defect surfaced.
  - _Requirements: AC-1, AC-2, AC-3, FR-2, FR-4_

- [x] 14. Backward-compatibility test  **(DONE)**
  - `test_legacy_project_builds_timeline_and_rerenders_without_real_provider`
    proves legacy load normalization, `build_canonical_timeline`, and the
    rerender path all succeed without a real provider.
  - _Requirements: NFR-1, AC-4_

- [x] 15. Docs update
  - Done: `docs/canonical_timeline.md` documents `metadata.generation`,
    `shot_plan_source`, and real/fallback summary counts.
  - _Requirements: FR-6, project doc-update rule_

- [x] 16. Checkpoint — run required checks  **(DONE — AC-7 qualified pass)**
  - Done: `python -m py_compile` on all listed modules; pytest
    (`tests/test_video_provider_mainline.py`) → 9 passed; Node checks on
    `frontend/app.js`, `render.js`, `api.js`, `events.js`, `state.js`.
  - AC-7 sample workflow: PASSED with local keyframe provider —
    `python -m scripts.run_workflow --input inputs\sample_story.txt --keyframe-provider local`
    ran end-to-end and produced a final video plus `canonical_timeline.json`.
    The run validated the mainline live: timeline `summary` reported accurate
    `real_video_scene_count` / `fallback_scene_count`, `shot_plan_source` was
    populated, and each clip carried full `generation` provenance
    (`provider_id`, `is_real_video`, `fallback_used`, `attempts`,
    `fallback_mode: report`, sanitized error). It also exercised the live
    report-mode fallback: the remote provider returned HTTP 429, retried per
    `VIDEO_MAX_RETRIES`, then fell back to 2.5D with provenance recorded.
  - Qualified pass notes: (a) no real-video scenes were produced in this run
    because the remote provider was rate-limited (429), so the real-video
    branch was not exercised end-to-end here; (b) the ComfyUI keyframe tunnel
    remains environment-blocked (`Error reading SSH protocol banner`) and is
    upstream of the video-provider path. Use the module form; avoid the direct
    script form until the `from scripts import tts_engines` import resolution is
    fixed. To validate the real-video branch end-to-end, re-run when a remote
    provider has quota or the ComfyUI path is reachable.
  - _Requirements: AC-7_

## Task Dependency Graph

```json
{
  "waves": [
    ["1", "3"],
    ["2", "4", "7"],
    ["5", "6"],
    ["8", "10"],
    ["9", "11"],
    ["12", "13", "14"],
    ["15"],
    ["16"]
  ]
}
```

## Handoff to Codex

- Files to edit: `scripts/run_workflow.py`, `backend/video_generation.py`,
  `backend/scene_renderer.py`, `backend/project_models.py`,
  `backend/project_runtime.py`, `backend/app.py`, `frontend/app.js`,
  `docs/canonical_timeline.md`.
- Files NOT to edit: `scripts/video_provider_adapters.py`,
  `backend/consistency_validator.py`, provider registry semantics in
  `video_providers.py`.
- Validation commands: see task 16.
- Acceptance checklist: AC-1 through AC-7 in `requirements.md`.
- Known risks: `render_clip` is high-risk and large; refactor to emit metadata
  must preserve existing dispatch/retry exactly. Fallback-mode unification must
  keep `silent` as a working legacy escape hatch.

## Notes

- Tasks are ordered bottom-up: contracts (1, 3) → renderer plumbing (4, 5, 6)
  → persistence/compat (7) → timeline (8, 9) → API/runtime (10, 11) → UI and
  validation (12-14) → docs and checks (15, 16).
- Do not edit `scripts/video_provider_adapters.py`; provider wire formats are
  owned by the `alibaba-video-provider` spec.
- All new scene fields (`shot_plan`, `generation_meta`) are additive; legacy
  projects must keep loading and rendering.
- Default `VIDEO_FALLBACK_MODE` for this release is `report`; `strict` is opt-in
  for final delivery passes.
