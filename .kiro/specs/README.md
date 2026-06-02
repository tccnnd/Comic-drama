# Kiro Specs

This directory contains requirements-first specs used to coordinate Kiro,
Codex, Cursor, and human review.

## Expected Structure

```text
.kiro/specs/<feature-id>/
  .config.kiro
  requirements.md
  design.md
  tasks.md
```

## Current Planned Specs

- `video-provider-mainline`: make real video generation the primary scene
  rendering path.
- `global-consistency-governance`: manage character, lighting, environment,
  prop, and camera continuity.
- `director-review-console`: expand review canvas into a production review and
  rerender console.

## Handoff Rule

Kiro writes the spec. Codex implements from the accepted spec. Cursor handles
focused UI work after the backend contract is stable.
