# Roadmap

This roadmap tracks the production workflow rather than individual model
experiments. The goal is to keep the project useful even as video models and
vendors change.

## Phase 0: Local Production Spine

Status: **complete**.

- Project workspace layout
- Script import and storyboard planning
- Character, scene, prop, dialogue, and asset records
- Local 2.5D dynamic-comic rendering
- Subtitle, BGM, SFX, and final export path
- Canonical timeline object
- Storyboard review canvas

## Phase 1: Real Video Generation

Status: **scene-level mainline delivered (v0.2.0)**; shot-level rendering is
the active next step.

- Treat generated video clips as first-class scene media. ✅
- Route each scene through a pluggable `VIDEO_PROVIDER`. ✅
- Keep local 2.5D rendering as a fallback, not the target quality ceiling. ✅
- Add provider adapters for self-hosted ComfyUI video workflows. ✅
- Add gateway adapters for Sora-style, Doubao, Seedance, and aggregator
  platforms. ✅
- Persist provider request, response, cost, timing, and failure metadata. ✅
- Render `shot_plan.shots[]` as provider clips, assemble them into the scene
  video, and persist per-shot provenance. *(next — draft spec in
  `.kiro/specs/shot-level-video-rendering/`)*
- Add dry-run quota guards before enabling shot-level live calls by default.
  *(next)*

## Phase 2: Global Consistency Governance

Status: **delivered (v0.3.0)**.

- Five-dimension continuity (character/lighting/environment/prop/camera) ✅
- Per-scene verdict (`pass`/`warn`/`fail`/`not_evaluated`) ✅
- Project-level continuity ledger ✅
- `report`/`block` policy via `CONSISTENCY_POLICY_MODE` ✅
- Governance-driven automatic regeneration (`regenerate` policy) — deferred to
  a future spec after verdicts prove stable.

## Phase 3: Review And Editorial Workflow

Status: **director review console delivered (v0.4.0)**; shot-level review
pending.

- Director review console with overview, triage filter/sort, and review units. ✅
- Per-scene rerender controls (image / audio / video / full rebuild). ✅
- Serial batch rerender over the filtered set with progress and outcomes. ✅
- Export canonical timeline data for external editing tools. ✅
- A/B comparison for regenerated scene versions — deferred.
- Shot-level render status, notes, targeted rerender, and acceptance
  criteria — pending shot-level-video-rendering spec.

## Phase 4: Director Interpretation

Status: **deterministic floor delivered (v0.5.0)**; LLM tier deferred.

- Structured `director_plan` synthesized deterministically per scene. ✅
- Per-shot `visual_content` and `visual_prototype` constraint layer. ✅
- Provider prompts consume `visual_content` + prototype hard/soft/guideline
  constraints. ✅
- LLM-based interpretation tier — deferred to a later spec.
- Prototype-to-output A/B automation and CLIP scoring — deferred.

## Phase 5: Screenplay Import And Authoring

Status: planned.

- Add Fountain-like screenplay import.
- Preserve scene headings, action lines, dialogue, parentheticals, and cues.
- Support lightweight script edits that can regenerate affected scenes only.
- Add stronger role and speaker disambiguation.

## Phase 6: Release And Collaboration

Status: partially delivered; in progress.

- Publish tagged pre-releases. *(v0.1.0 – v0.5.0 released)*
- Add issue templates and contribution labels. ✅
- Add example projects that do not contain private assets. *(planned)*
- Add automated checks for frontend syntax and backend imports. ✅
- Document provider setup recipes for common local and cloud environments.
  ✅ *(troubleshooting_video_providers.md)*

## Non-Goals For Early Versions

- Hosting a public multi-user SaaS service.
- Bundling large model weights in the repository.
- Guaranteeing commercial rights for third-party model outputs.
- Replacing professional editing or animation tools end to end.
