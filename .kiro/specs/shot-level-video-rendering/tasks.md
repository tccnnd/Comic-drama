# Implementation Plan: shot-level-video-rendering

Status: draft; do not implement core rendering until this spec is accepted.
Codex leads implementation and validation. M3 may assist with creative
shot-language and prompt candidate work only.

## Task List

- [x] 1. Accept scope and configuration names
  - Accepted environment defaults: `VIDEO_RENDER_GRANULARITY=scene|shot`,
    `VIDEO_SHOT_MAX_CALLS`, `VIDEO_SHOT_MAX_SECONDS`,
    `VIDEO_SHOT_DRY_RUN`, and `VIDEO_SHOT_REUSE_CACHE`.
  - Accepted override order: CLI flag, API/runtime request, safe project
    setting, environment default, built-in default.
  - Confirmed default remains `scene`.
  - Confirmed `shot` mode must pass quota validation before the first provider
    submit.
  - _Requirements: FR-1, FR-7_

- [x] 2. Add `generation_meta` normalization for future schema versions
  - Added `normalize_generation_meta(...)` in `backend/video_generation.py`.
  - Version 1 metadata is preserved and sanitized; version 2 shot-level fields
    (`render_granularity`, `shot_outputs`, aggregate counts) are accepted and
    normalized.
  - Project load, project snapshot, scene metadata update, and canonical
    timeline generation now pass metadata through the normalizer.
  - Added tests for v1 metadata, v2 shot outputs, and project-load
    normalization.
  - Validation: `python -m py_compile backend\video_generation.py backend\project_runtime.py backend\scene_renderer.py scripts\run_workflow.py`;
    `python -m pytest -q tests\test_video_provider_mainline.py` -> 19 passed,
    2 existing FastAPI deprecation warnings.
  - _Requirements: FR-4, NFR-1_

- [x] 3. Define shot output and assembly manifest helpers
  - Added pure helpers in `backend/video_generation.py`:
    `build_shot_output(...)`, `generation_meta_from_shot_outputs(...)`, and
    `build_shot_assembly_manifest(...)`.
  - Helpers serialize/sanitize shot outputs, aggregate shot counts/attempts,
    and build a stable scene assembly manifest without provider calls or file
    I/O.
  - Secrets, signed URL query values, authorization headers, and token-like
    fields are sanitized before persistence.
  - Added pure-function tests for shot output sanitization, generation-meta
    aggregation, and manifest child timing.
  - Validation: `python -m py_compile backend\video_generation.py`;
    `python -m pytest -q tests\test_video_provider_mainline.py` -> 22 passed,
    2 existing FastAPI deprecation warnings.
  - _Requirements: FR-4, NFR-3_

- [x] 4. Resolve and validate render granularity
  - Added `normalize_video_render_granularity(...)` and
    `video_render_granularity(...)` in `backend/video_generation.py`.
  - Resolution supports CLI, request value, project setting, environment
    default, then built-in `scene`.
  - Added `video_render_granularity` to project/task creation and workflow CLI
    (`--video-render-granularity`), and persisted it in safe settings/output
    metadata.
  - Existing scene-level render paths remain unchanged by default; `shot` is
    parsed and persisted but not yet wired into provider orchestration.
  - Validation: `python -m py_compile backend\video_generation.py backend\project_runtime.py backend\app.py backend\task_store.py scripts\run_workflow.py backend\scene_renderer.py`;
    `python -m pytest -q tests\test_video_provider_mainline.py` -> 24 passed,
    2 existing FastAPI deprecation warnings.
  - _Requirements: FR-1, NFR-1_

- [x] 5. Add quota dry-run estimation
  - Estimate shot count, provider calls, and generated seconds before live
    submission.
  - Enforce configured max calls/max seconds.
  - Added `video_shot_quota_config(...)`,
    `estimate_shot_render_quota(...)`, and
    `validate_shot_render_quota(...)` in `backend/video_generation.py`.
  - Quota validation raises `VideoShotQuotaError` before provider submission
    when max calls or max generated seconds are exceeded.
  - Cache reuse is accounted for when `VIDEO_SHOT_REUSE_CACHE=1`.
  - Validation: `python -m py_compile backend\video_generation.py`;
    `python -m pytest -q tests\test_video_provider_mainline.py` -> 27
    passed, 2 existing FastAPI deprecation warnings.
  - _Requirements: FR-7_

- [x] 6. Build per-shot provider request inputs
  - Use shot timing, camera fields, intent, `visual_content`, and scene
    continuity context.
  - Keep video-provider model routing separate from LLM/planning model routing.
  - Added pure `build_shot_provider_request_inputs(...)` in
    `backend/video_generation.py`.
  - Request inputs carry per-shot prompt, negative prompt, timing,
    `temporal_spec`, `consistency_spec`, camera payload, intent payload,
    visual content, continuity hints, and resolved provider/model metadata.
  - Video model resolution uses project/scene/shot/provider environment
    fields and explicitly avoids `LLM_MODEL` planning-model leakage.
  - Provider adapter wire formats are unchanged; no provider submission is
    performed by this helper.
  - Validation: `python -m py_compile backend\video_generation.py`;
    `python -m pytest -q tests\test_video_provider_mainline.py` -> 29
    passed, 2 existing FastAPI deprecation warnings.
  - _Requirements: FR-2_

- [x] 7. Render one shot with existing provider policy
  - Reuse the current retry/fallback semantics.
  - Return a structured shot output result without changing provider adapter
    wire formats.
  - Added `render_shot_with_provider_policy(...)` in
    `backend/video_generation.py`.
  - The helper converts one shot request input into the existing
    `VideoRenderRequest` adapter contract, applies retry/backoff, honors
    `report`/`strict`/`silent` fallback modes, and returns sanitized
    `shot_outputs[]` metadata.
  - No live provider calls are made by tests; provider submission is covered by
    mock adapter calls.
  - Validation: `python -m py_compile backend\video_generation.py`;
    `python -m pytest -q tests\test_video_provider_mainline.py` -> 32
    passed, 2 existing FastAPI deprecation warnings.
  - _Requirements: FR-2, FR-5_

- [x] 8. Assemble shot clips into a scene clip
  - Use existing ffmpeg/local concat patterns where possible.
  - Start with hard cuts and stable duration handling.
  - Write an assembly manifest.
  - Added `assemble_shot_clips(...)` in `backend/video_generation.py`.
  - The helper filters usable real/fallback/skipped shot outputs, assembles
    them with ffmpeg concat hard cuts, and writes a stable assembly manifest
    when requested.
  - Failed shot outputs are excluded from assembly and remain visible in
    provenance for fallback/strict policy handling.
  - Validation: `python -m py_compile backend\video_generation.py`;
    `python -m pytest -q tests\test_video_provider_mainline.py` -> 34
    passed, 2 existing FastAPI deprecation warnings.
  - _Requirements: FR-3_

- [x] 9. Implement scene-level shot render orchestration
  - Iterate ordered `shot_plan.shots[]`.
  - Render/reuse each shot.
  - Assemble the scene clip.
  - Persist aggregate `generation_meta`.
  - Added `render_scene_shots_with_provider_policy(...)` in
    `backend/video_generation.py` and wired `backend/scene_renderer.py` to use
    it only when effective `video_render_granularity` is `shot`.
  - The orchestration performs quota validation before provider submission,
    builds per-shot requests, renders each shot through the existing provider
    policy, assembles the scene clip, writes a shot assembly manifest, and
    persists version-2 aggregate `generation_meta`.
  - Existing scene-level rendering remains the default path.
  - Validation: `python -m py_compile backend\video_generation.py
    backend\scene_renderer.py`; `python -m pytest -q
    tests\test_video_provider_mainline.py` -> 35 passed, 2 existing FastAPI
    deprecation warnings.
  - _Requirements: FR-1, FR-2, FR-3, FR-4_

- [x] 10. Implement fallback-mode behavior
  - `report`: assemble mixed real/fallback shot outputs.
  - `strict`: fail scene if a required shot fails.
  - `silent`: record fallback metadata while suppressing visible warnings.
  - Shot-level report mode now renders local fallback clips for failed shots,
    assembles mixed real/fallback scene clips, and records per-shot warnings.
  - Shot-level strict mode raises before publishing an assembled scene clip or
    persisted generation metadata.
  - Shot-level silent mode records fallback shot outputs and aggregate metadata
    while suppressing warning text.
  - Validation: `python -m py_compile backend\video_generation.py
    backend\scene_renderer.py tests\test_video_provider_mainline.py`;
    `python -m pytest -q tests\test_video_provider_mainline.py` -> 38
    passed, 2 existing FastAPI deprecation warnings.
  - _Requirements: FR-5_

- [x] 11. Implement resume and targeted shot rerender
  - Add cache keys and reuse unchanged successful shot outputs.
  - Add backend path for rerendering one shot and reassembling the scene.
  - Added deterministic `build_shot_cache_key(...)` and cache-key checked
    shot-output reuse in `backend/video_generation.py`.
  - Shot-level orchestration now validates quota against actually reusable
    cached outputs, skips unchanged matching shots, and supports
    `force_shot_id` for targeted rerender.
  - Added `rerender_scene_shot_video(...)` plus
    `POST /api/projects/{project_id}/scenes/{scene_order}/shots/{shot_id}/rerender-video`.
  - Targeted rerender reuses unchanged shots, resubmits the requested shot,
    reassembles the scene clip, and persists refreshed aggregate
    `generation_meta`.
  - Validation: `python -m py_compile backend\video_generation.py
    backend\scene_renderer.py backend\project_runtime.py backend\app.py`;
    `python -m pytest -q tests\test_video_provider_mainline.py` -> 40
    passed, 2 existing FastAPI deprecation warnings.
  - _Requirements: FR-6_

- [x] 12. Update canonical timeline and snapshots
  - Preserve existing scene-level `metadata.generation`.
  - Add shot-level provenance for new consumers.
  - `build_canonical_timeline(...)` still writes scene-level
    `metadata.generation` and now enriches `shot_timeline[]` items with compact
    per-shot `generation` copied from `generation_meta.shot_outputs[]`.
  - `project_snapshot(...)` now exposes compact `shot_render_status` in
    `scene_graph.scenes[]` while keeping full `generation_meta` on each scene.
  - Updated `docs/canonical_timeline.md`.
  - Validation: `python -m py_compile scripts\run_workflow.py
    backend\project_runtime.py`; `python -m pytest -q
    tests\test_video_provider_mainline.py` -> 41 passed, 2 existing FastAPI
    deprecation warnings.
  - _Requirements: FR-4, AC-5_

- [x] 13. Add Review Console read-only shot status
  - Show real/fallback/failed/skipped shot states.
  - Keep legacy scene-level projects readable.
  - Added frontend helpers for `sceneShotRenderEntries(...)`,
    `shotRenderStatusLabel(...)`, and `shotRenderStatusClass(...)`.
  - Review Console cards/details now show read-only shot render summaries and
    per-shot rows from `generation_meta.shot_outputs[]` or canonical
    `shot_timeline[].generation`.
  - Legacy scene-level projects fall back to planned shot rows without requiring
    shot render metadata.
  - Updated `docs/director_review_console.md`.
  - Validation: `node --check frontend\utils.js`;
    `node --check frontend\components\review\canvas.js`;
    `node tests\test_frontend_imports.mjs`;
    `node tests\test_review_console_helpers.mjs`;
    `python -m pytest -q tests\test_video_provider_mainline.py` -> 41
    passed, 2 existing FastAPI deprecation warnings.
  - _Requirements: FR-8, AC-6_

- [x] 14. Add targeted Review Console controls
  - Add shot-level rerender controls only after backend targeted rerender is
    stable.
  - Review Console selected-scene detail rows now expose `Rerender shot`
    controls for `video_render_granularity=shot` scenes with concrete
    `shot_id`s.
  - The controls call the backend targeted rerender endpoint through the
    existing frontend API/event path, require confirmation, and refresh the
    project snapshot after submission.
  - Scene list cards remain status-only to avoid nested interactive controls.
  - Updated `docs/director_review_console.md`.
  - Validation: `node --check frontend\components\review\canvas.js`;
    `node --check frontend\api.js`; `node --check frontend\events.js`;
    `node tests\test_frontend_imports.mjs`; `node
    tests\test_review_console_helpers.mjs`.
  - _Requirements: FR-6, FR-8_

- [x] 15. Add mock-provider integration tests
  - All-real two-shot scene.
  - Mixed report fallback.
  - Strict failure.
  - Targeted rerender reuses unchanged shots.
  - Quota dry-run blocks before submit.
  - Tests implemented in `tests/test_video_provider_mainline.py`:
    - `test_shot_granularity_rerender_orchestrates_shots_and_persists_metadata`
      (all-real two-shot scene)
    - `test_shot_granularity_report_mode_assembles_mixed_real_and_fallback`
      (mixed report fallback)
    - `test_shot_granularity_strict_mode_fails_without_video_asset` (strict
      failure)
    - `test_targeted_shot_rerender_reuses_unchanged_shots_and_reassembles`
      (targeted rerender reuses unchanged shots)
    - `test_validate_shot_render_quota_blocks_over_limit_before_submit` (quota
      dry-run blocks before submit)
  - Validation: `python -m pytest -q tests\test_video_provider_mainline.py -k
    "test_shot_granularity_rerender_orchestrates_shots_and_persists_metadata or
    test_shot_granularity_report_mode_assembles_mixed_real_and_fallback or
    test_shot_granularity_strict_mode_fails_without_video_asset or
    test_targeted_shot_rerender_reuses_unchanged_shots_and_reassembles or
    test_validate_shot_render_quota_blocks_over_limit_before_submit"` -> 5
    passed.
  - _Requirements: AC-1, AC-2, AC-3, AC-4, AC-7_

- [x] 16. Documentation update
  - Update `docs/production_pipeline.md`, `docs/canonical_timeline.md`,
    provider troubleshooting, and release notes.
  - Updated `docs/production_pipeline.md`: Stage Maturity table and spine
    diagram now reflect v0.5.0 delivered and shot-level implementation status.
  - `docs/canonical_timeline.md` already documents `shot_timeline[]` per-shot
    `generation` provenance (L118-122); no further changes needed.
  - Updated `docs/troubleshooting_video_providers.md`: added "Shot-Level Render
    Metadata (v0.6.0-pre)" section and "Shot-Level Render Issues" common
    failures with environment variable reference and diagnostic guidance.
  - Created `docs/releases/v0.6.0-pre.md` documenting the shot-level render
    feature, configuration, validation, and known limitations.
  - _Requirements: NFR-2, NFR-3_

- [ ] 17. Optional controlled live validation
  - Only run after explicit approval because it consumes provider quota.
  - Use a short two-shot sample and verify `shot_outputs` plus assembled scene
    media.
  - _Requirements: AC-8_

## Validation Commands

Run the subset matching edited areas. Expected baseline:

```powershell
python -m py_compile scripts\run_workflow.py backend\project_runtime.py backend\app.py video_providers.py scripts\video_provider_adapters.py backend\scene_renderer.py backend\video_generation.py
python -m pytest -q tests\test_video_provider_mainline.py
node --check frontend\app.js
node --check frontend\render.js
node --check frontend\components\review\canvas.js
node tests\test_frontend_imports.mjs
node tests\test_review_console_helpers.mjs
```

Live provider validation is not part of normal CI.
