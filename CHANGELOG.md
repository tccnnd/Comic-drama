# Changelog

All notable changes to this project will be documented here.

The project currently uses pre-release versioning while the workflow structure
is still evolving.

## [0.5.0] - 2026-06-07

Feature line: **director-interpretation-mainline** — make the AI director's
interpretation a first-class, structured stage between scene classification and
video-provider prompt construction. Deterministic-first; no LLM dependency.

### Added

- Per-scene `director_plan` (`dramatic_intent`, `emotional_target`,
  `narrative_focus`, `rationale`, `source`) synthesized deterministically from
  the existing `director_meta` and scene text (`build_director_plan`).
- Per-shot `visual_content` (shot_description, foreground, midground,
  background, composition, motion, lighting, focus) plus `shot_size`,
  `camera_language`, and `dramatic_intent` (`build_shot_visual_content`).
- Deterministic `visual_prototype` shot-language constraint layer: each shot
  gets a `mode` (`prototype_lock` | `freeform`), an `id` from a fixed prototype
  set, and hard/soft/guideline `constraints`; `freeform` records a
  `gap.reason`.
- `build_shot_plan` enriches every shot with the above via the shared,
  additive `normalize_shot_plan_visual_content`; the workflow persists
  `director_plan` and the enriched `shot_plan`.
- Legacy projects are normalized on load/snapshot
  (`_normalize_director_interpretation`) so older projects gain synthesized
  interpretation without failing.
- Tests in `tests/test_director_interpretation.py` (planner, shot enrichment,
  legacy load, AC-3 prompt consumption, AC-4 legacy fallback).

### Changed

- `build_scene_video_prompts` now builds the positive prompt primarily from
  shot `visual_content` (+ `shot_size` / `camera_language` / prototype
  constraints), demoting dialogue to context. The `PromptCompiler` path uses the
  same visual source. The legacy `clean_comfyui_visual_prompt(scene.visual)`
  path is retained as a fallback when `visual_content` is absent.

### Known Limitations

- LLM-based interpretation is deferred; v0.5.0 ships the deterministic floor
  that reuses the classifier's `llm/rules/default` tiering pattern.
- The implementation extends Slice C beyond the original "consume
  visual_content" wording with the `visual_prototype` constraint layer; the spec
  tasks.md records this scope note.
- Sample-workflow live verification remains environment-gated (ComfyUI tunnel);
  use `--keyframe-provider local`.

## [0.4.0] - 2026-06-06

Feature line: **director-review-console** — evolve the storyboard review canvas,
in place, into a production review-and-rerender console that triages and acts on
the provenance (v0.2.0) and governance (v0.3.0) data already in the snapshot.

### Added

- Live-derived review overview (`deriveReviewOverview`) and pure triage helper
  (`applyReviewTriage`) in `frontend/utils.js` — no new persisted schema.
- Console overview header: continuity ledger counts, real-vs-fallback
  provenance counts, and review progress; metrics drive the triage filter.
- Triage bar: filter by review status, governance status, provenance,
  deliverability, and rating; sort by scene order, rating, governance severity,
  or fallback-first. Client-side, state-backed.
- Unified per-scene review unit composing the existing v0.2.0 generation and
  v0.3.0 governance badges/detail with review state and asset readiness;
  graceful unknown/not_evaluated for legacy projects.
- Per-scene rerender controls (image / audio / video / full rebuild) mapping to
  existing scene endpoints via `runSceneAction`.
- Serial batch rerender over the current filtered set: explicit confirmation,
  n/total progress, per-scene outcomes, and fail-isolated continuation.
- Console documentation (`docs/director_review_console.md`) and frontend helper
  tests (`tests/test_review_console_helpers.mjs`).

### Changed

- The review canvas is reorganized in place into the console; the prior review
  filter/summary is preserved as a compatibility entry while triage drives the
  visible results.

### Known Limitations

- Browser visual smoke of the console is unverified in this environment (the
  in-app browser blocks localhost with `ERR_BLOCKED_BY_CLIENT`); JS syntax is
  validated via `node --check` and helper logic via tests.
- Batch rerender is serial by design (no concurrency) and reviewer-initiated;
  governance-driven automatic rerender (`regenerate`) remains deferred.
- The console depends on v0.2.0 provenance and v0.3.0 governance data; on a
  baseline without them, scenes display unknown/not_evaluated states.

## [0.3.0] - 2026-06-06

Feature line: **global-consistency-governance** — manage continuity across
character, lighting, environment, prop, and camera dimensions, with a per-scene
verdict, a project-level ledger, and `report`/`block` policy. No automatic
regeneration in this release.

### Added

- Two stateless validator checks in `consistency_validator.py`:
  `validate_prop_continuity` (recurring-prop similarity vs a reference; missing
  reference degrades to a non-failing `info`) and `evaluate_camera_continuity`
  (rules-based heuristic flagging unmotivated camera-family / speed changes).
- `props` registry in the production bible (`build_production_bible`): recurring
  objects with description, owning characters/scenes, and optional reference
  image.
- New governance orchestrator `backend/consistency_governance.py`:
  - `evaluate_scene_governance` — aggregates all five dimension checks into a
    per-scene verdict (`pass`/`warn`/`fail`/`not_evaluated`) with per-dimension
    score, threshold, and reason; persisted at `scene["governance"]`.
  - `apply_governance_policy` — `report` (record only) or `block` (mark
    `deliverable=false` on `fail`); default `report` via
    `CONSISTENCY_POLICY_MODE`.
  - `build_continuity_ledger` — project rollup: status counts, per-dimension
    pass rates, offending scenes, blocked-scene count.
- `update_scene_governance` persistence helper and render-site wiring that
  records a verdict after video rerender/rebuild.
- Project snapshot now includes `continuity_ledger`; the review console shows a
  project continuity chip, per-scene verdict badges (with a blocked marker), and
  a five-dimension detail view.
- Export readiness blocks scenes that are `block`-mode and not deliverable.
- Governance contract docs (`docs/continuity_governance.md`) and tests in
  `tests/test_consistency_governance.py` / `tests/test_scene_graph.py`.

### Changed

- Continuity validation moves from advisory-only logging to a structured,
  persisted verdict plus a project-level ledger; the validator remains a
  stateless scoring engine, with policy and state owned by the new orchestrator.
- Legacy projects without `props` / `governance` are normalized on load and via
  snapshot (`not_evaluated`), and continue to load, render, and export
  unchanged.

### Known Limitations

- Browser visual smoke of the review-console continuity display is unverified
  in this environment (the in-app browser blocks localhost with
  `ERR_BLOCKED_BY_CLIENT`); JS syntax is validated via `node --check` and
  backend logic via tests.
- A `regenerate` policy mode (governance-driven re-render) is intentionally
  deferred to a later spec to avoid a render feedback loop;
  `CONSISTENCY_MAX_RETRIES` remains validator/runtime config and is non-operative
  for governance policy.
- Continuity scoring uses histogram/structural-hash similarity; embedding-based
  identity/motion analysis is a future upgrade.

## [0.2.0] - 2026-06-06

Feature line: **video-provider-mainline** — make real video generation the
primary scene rendering path, with local 2.5D as an explicit, observable
fallback.

### Added

- `shot_plan` per scene: derived from `temporal_spec.shots`, or a synthesized
  single full-duration shot when none exist; contiguous and covering the scene
  duration.
- Generation provenance per scene (`generation_meta`): provider id/label,
  backend, `is_real_video`, `fallback_used`, attempts, duration, fallback mode,
  sanitized error, and timestamp. Persisted on the scene and exposed via the
  project snapshot/API.
- `canonical_timeline` enrichment: each picture clip carries
  `metadata.generation` and `shot_plan_source`; the timeline `summary` adds
  `real_video_scene_count` and `fallback_scene_count`.
- `render_clip_with_meta(...)` returning `(Path, VideoGenerationResult)`, with
  `VideoGenerationResult` as the shared provenance type and
  `generation_meta_from_result(...)` mapping it to persisted metadata (error
  strings are stripped of credentials and query-param URLs).
- Review console provenance display: per-scene real-video / fallback / unknown
  badge with provider label, attempts, and failure reason, plus project-level
  provider status.
- Test coverage in `tests/test_video_provider_mainline.py`: shot_plan
  derivation/synthesis, metadata sanitization, timeline counts, legacy load
  normalization, and mock-provider success / report / strict paths.

### Changed

- Real video generation is now the primary scene renderer when a non-local
  provider is configured; local 2.5D is an explicit fallback rather than a
  silent substitute.
- Unified fallback policy: `VIDEO_FALLBACK_MODE=report|strict|silent` with
  `VIDEO_STRICT` override, defaulting to `report`, shared across the render
  paths.
- Legacy projects without `shot_plan` / `generation_meta` are normalized on
  load (synthesized shot plan, empty provenance) and render unchanged.

### Known Limitations

- AC-7 acceptance is a qualified pass: the sample workflow was validated
  end-to-end with `--keyframe-provider local`, exercising the report-mode
  fallback live (remote provider returned HTTP 429 → retries → 2.5D fallback
  with provenance recorded). The real-video success branch is covered by mock
  tests; a live real-video run is still quota-dependent.
- The ComfyUI keyframe tunnel remains environment-dependent
  (`Error reading SSH protocol banner`) and is upstream of the video-provider
  path. Use the module form for runs
  (`python -m scripts.run_workflow ...`); the direct script form has an
  unresolved `from scripts import tts_engines` import issue.
- Global visual consistency governance (character, lighting, environment, prop,
  camera) is specified for the next line (`global-consistency-governance`) but
  not yet implemented.

## [0.1.0] - 2026-06-02

### Added

- Local project workspace layout for script, storyboard, scene assets, clips,
  and final exports.
- Script-to-storyboard workflow with deterministic fallback planning.
- Character extraction foundations and character library management.
- Scene-level keyframe generation with local and ComfyUI provider paths.
- TTS provider configuration and per-scene audio generation.
- Dynamic-comic rendering with enhanced zoom/pan easing, subtitle timing,
  transition handling, and SFX hooks.
- Pluggable video provider registry for local, ComfyUI, Sora-style, Doubao,
  Seedance, and aggregator-style providers.
- ComfyUI workflow injection with configurable checkpoint, optional LoRA, and
  style preset fallback.
- Canonical timeline export for downstream editing and provider routing.
- Storyboard review canvas with status, rating, notes, filters, and version
  comparison.
- Documentation for self-hosted video providers, cloud GPU restoration, target
  modules, and canonical timeline.

### Changed

- Promoted the timeline object to the canonical project interchange layer.
- Moved video generation toward provider-agnostic scene rendering.
- Improved encoded output settings for higher-quality MP4 export.

### Known Limitations

- True continuous video generation is still provider-dependent and not yet the
  default local path.
- Global visual consistency still requires stronger governance across character
  identity, lighting, camera, and environment.
- Some local workflows depend on external model runtimes such as ComfyUI.
- Public GitHub usage metrics are still early because the repository is newly
  prepared for open-source publication.
