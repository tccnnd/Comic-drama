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

## Current Specs

Delivered / specced (see `docs/production_pipeline.md` for stage maturity and
branch/merge state):

- `video-provider-mainline` (v0.2.0): real video as the primary scene renderer
  with local 2.5D fallback. **Delivered on main.**
- `global-consistency-governance` (v0.3.0): character, lighting, environment,
  prop, and camera continuity governance. **Delivered on main.**
- `director-review-console` (v0.4.0): production review + rerender console.
  **Delivered on main.**
- `director-interpretation-mainline` (v0.5.0): structured `director_plan` +
  per-shot `visual_content`, consumed by the video-provider prompt.
  **Spec complete (local); implementation pending.**

Future / deferred specs (not yet written):

- `provider-cost-controls`: cost/timing/quota accounting across video providers.
- consistency-regeneration: the deferred `regenerate` policy mode from v0.3.0
  (governance-driven re-render), only after verdicts prove stable.
- Long-form / multi-episode management and finer shot-language/prompt governance.

## Handoff Rule

Kiro writes the spec. Codex implements from the accepted spec. Cursor handles
focused UI work after the backend contract is stable.
