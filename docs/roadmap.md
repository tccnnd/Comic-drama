# Roadmap

This roadmap tracks the production workflow rather than individual model
experiments. The goal is to keep the project useful even as video models and
vendors change.

## Phase 0: Local Production Spine

Status: mostly complete.

- Project workspace layout
- Script import and storyboard planning
- Character, scene, prop, dialogue, and asset records
- Local 2.5D dynamic-comic rendering
- Subtitle, BGM, SFX, and final export path
- Canonical timeline object
- Storyboard review canvas

## Phase 1: Real Video Generation

Status: active priority.

- Treat generated video clips as first-class scene media.
- Route each scene through a pluggable `VIDEO_PROVIDER`.
- Keep local 2.5D rendering as a fallback, not the target quality ceiling.
- Add provider adapters for self-hosted ComfyUI video workflows.
- Add gateway adapters for Sora-style, Doubao, Seedance, and aggregator
  platforms.
- Persist provider request, response, cost, timing, and failure metadata.

## Phase 2: Global Consistency Governance

Status: planned.

- Generate a production bible for characters, locations, props, lighting, and
  camera grammar.
- Lock character identity before scene generation begins.
- Track continuity requirements across adjacent shots and scenes.
- Add consistency checks for:
  - character face and costume
  - lighting direction and color temperature
  - camera continuity
  - environment geometry
  - prop placement
- Surface consistency notes in the storyboard review canvas.

## Phase 3: Review And Editorial Workflow

Status: in progress.

- Expand the storyboard review canvas into a director review console.
- Add A/B comparison for regenerated scene versions.
- Add review filters, ratings, blocking reasons, and rerender queues.
- Export canonical timeline data for external editing tools.
- Support shot-level notes and acceptance criteria.

## Phase 4: Screenplay Import And Authoring

Status: planned.

- Add Fountain-like screenplay import.
- Preserve scene headings, action lines, dialogue, parentheticals, and cues.
- Support lightweight script edits that can regenerate affected scenes only.
- Add stronger role and speaker disambiguation.

## Phase 5: Release And Collaboration

Status: planned.

- Publish tagged pre-releases.
- Add issue templates and contribution labels.
- Add example projects that do not contain private assets.
- Add automated checks for frontend syntax and backend imports.
- Document provider setup recipes for common local and cloud environments.

## Non-Goals For Early Versions

- Hosting a public multi-user SaaS service.
- Bundling large model weights in the repository.
- Guaranteeing commercial rights for third-party model outputs.
- Replacing professional editing or animation tools end to end.
