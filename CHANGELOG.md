# Changelog

All notable changes to this project will be documented here.

The project currently uses pre-release versioning while the workflow structure
is still evolving.

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
