# Changelog

All notable changes to this project will be documented here.

The project currently uses pre-release versioning while the workflow structure
is still evolving.

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
