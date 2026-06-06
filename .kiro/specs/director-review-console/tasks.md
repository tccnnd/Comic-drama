# Implementation Plan: director-review-console

## Overview

Evolve the existing storyboard review canvas, in place, into a production
review-and-rerender console. No new generation/governance/provider logic, no new
persisted schema; consume existing snapshot data (review state, v0.2.0
provenance, v0.3.0 governance, continuity ledger) and the existing rerender
endpoints.

Work is split into two slices to isolate risk:
- **Slice A (read-only console)**: overview, triage filter/sort, unified review
  unit, in-place review-state edits. No rerender actions.
- **Slice B (rerender actions)**: per-scene + serial batch rerender over the
  filtered set, with confirmation, progress, per-scene outcomes, and
  fail-isolation. Reuses existing endpoints only.

## Implementation Base / Branching Constraint (hard prerequisite)

- Spec branch may be based on `main`.
- Implementation branch MUST be based on `codex/global-consistency-governance`
  (v0.3.0) OR `main` after v0.2.0 + v0.3.0 merge.
- Do NOT implement on plain current `main` — it lacks the provenance badge/detail
  (v0.2.0), governance badge/detail (v0.3.0), and continuity-ledger UI (v0.3.0)
  this spec evolves.

## Tasks

### Slice A — Read-only console

- [x] 1. Triage + overview pure helpers (`frontend/`)
  - Add `deriveReviewOverview(project)` (live-derived: ledger counts,
    real/fallback counts, review-progress counts) and `applyReviewTriage(scenes,
    triage)` (pure filter+sort, empty-state aware). No persistence, no DOM.
  - _Requirements: 2.1, 2.2, 3.1, 3.2, 3.3, NFR-3, Property 3, Property 4_

- [x] 2. Unit-test the pure helpers
  - `applyReviewTriage`: each filter (review status, governance, provenance,
    deliverability, rating), combined filters, sort orders, empty result.
  - `deriveReviewOverview`: counts match a snapshot incl. unknown/not_evaluated.
  - _Requirements: 3.1, 3.2, 3.3, 2.1, 2.2_

- [x] 3. Triage state in `frontend/state.js`
  - Add `reviewTriageState` (filters + sort) to the existing state model,
    reflected in the existing URL/state pattern (FR-3.4).
  - _Requirements: 3.4_

- [x] 4. Overview header (`frontend/render.js`)
  - `renderReviewOverviewHeader(project)` from `deriveReviewOverview`; metrics
    are clickable to set the triage filter.
  - _Requirements: 2.1, 2.2, 2.3, Property 4_

- [x] 5. Triage bar (`frontend/render.js` + `events.js`)
  - `renderReviewTriageBar` (filter controls + sort selector); wire changes to
    `reviewTriageState` and re-render the list client-side.
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 6. Unified review unit (`frontend/render.js`)
  - `renderReviewUnit(scene, project)` composing existing
    `renderGenerationBadge/Detail` (v0.2.0) + `renderGovernanceBadge/Detail`
    (v0.3.0) + review state + asset readiness. Graceful unknown/not_evaluated.
  - _Requirements: 1.1, 1.2, 1.3, 6.1, Property 1, Property 2_

- [x] 7. In-place review-state actions (`frontend/render.js` + `events.js`)
  - Status / rating / notes editable in the review unit via the existing
    review-state save path; overview updates without a full reload.
  - _Requirements: 4.1, 4.2, Property 4_

- [x] 8. Console layout/styles (`frontend/styles.css`)
  - Overview + triage + review-unit list layout, including empty/loading states.
  - _Requirements: 3.3, 1.2_

- [x] 9. Slice A checks
  - `node --check` on edited frontend modules; run helper unit tests; backward-
    compat pass with a legacy project (unknown/not_evaluated, no errors).
  - _Requirements: AC-1, AC-2, AC-3, AC-4, AC-7, AC-8, NFR-1_

## Slice B — Rerender actions

- [x] 10. Per-scene rerender controls (`frontend/render.js` + `events.js` + `api.js`)
  - Buttons for image / audio / video / full rebuild mapping 1:1 to existing
    endpoints (`rerender_scene_image/audio/video`, `generate_scene_assets`).
    Dispatch via the existing async task/event path; non-blocking.
  - _Requirements: 5.1, 5.3, NFR-4, Property 5_

- [x] 11. Post-rerender refresh
  - On a scene's rerender completion, refresh that scene's provenance +
    governance in its review unit from the updated snapshot.
  - _Requirements: 5.4, AC-6, Property 6_

- [x] 12. Batch rerender over filtered set (`frontend/render.js` + `events.js`)
  - `renderBatchRerenderBar`: act on the current filtered set, run **serially**,
    show progress (n/total), report per-scene outcomes, and continue on failure
    (fail-isolated). Explicit confirmation stating scene count and cost/duration.
    No new provider/scheduling logic — only existing endpoints, called in
    sequence.
  - _Requirements: 5.2, 5.3, NFR-4, NFR-5, Property 5_

- [x] 13. Slice B checks
  - `node --check` on edited modules; verify per-scene + batch dispatch use
    existing endpoints only; confirm batch confirmation, serial progress, and
    fail-isolation behavior.
  - _Requirements: AC-5, AC-6, AC-8_

- [x] 14. (Optional) backend read aggregation
  - ONLY if an overview count is not client-derivable: add a read-only
    aggregation over existing snapshot fields in `backend/project_runtime.py`;
    `py_compile` + a targeted test. Skip if unnecessary.
  - Skipped: all counts are derivable from the existing snapshot; no backend
    read aggregation was needed.
  - _Requirements: 6.2, NFR-2, NFR-6_

- [x] 15. Docs update
  - Document the review console (overview, triage, review unit, rerender
    actions) in `docs/`.
  - _Requirements: project doc-update rule_

- [x] 16. Checkpoint — run required checks
  - `node --check` on all edited frontend modules; helper unit tests; any
    backend read-aggregation `py_compile` + test. Visual smoke is expected to be
    environment-gated (in-app browser blocks localhost) — record as pending.
  - Completed locally: `node --check` passed for `frontend/app.js`, `api.js`,
    `events.js`, `render.js`, `state.js`, and `utils.js`; helper tests passed.
    Browser visual smoke remains environment-gated.
  - _Requirements: AC-8_

## Task Dependency Graph

```json
{
  "waves": [
    ["1", "3"],
    ["2", "4", "5", "8"],
    ["6"],
    ["7", "9"],
    ["10", "12", "14"],
    ["11", "13"],
    ["15"],
    ["16"]
  ]
}
```

## Implementation Slices

- Slice A (DONE — local, uncommitted): tasks 1–9. Pure helpers
  `deriveReviewOverview` / `applyReviewTriage` in `frontend/utils.js` (live-derived,
  no persistence); triage state in `state.js`; overview header, triage bar, and
  unified `review-unit` in `render.js` (reusing existing generation/governance
  detail); event wiring in `events.js` (client-state only); layout in
  `styles.css`; helper tests in `tests/test_review_console_helpers.mjs`.
  Verification: `node --check` on render/events/state/utils/app/api pass; helper
  test suite passes. No Slice B / rerender logic; no backend/provider/governance/
  workflow changes; `_external/Toonflow-app` untouched; legacy review
  filter/summary preserved as compatibility entry while triage drives results.
  Note: implemented field names use the codebase's real review vocabulary
  (`unreviewed/approved/needs_work/blocked`; provenance `real/fallback/local/
  unknown`); design.md §Data Contracts used illustrative names — reconcile the
  design example to these if it is ever treated as authoritative.
- Slice B (DONE — local, uncommitted): tasks 10–14. `runSceneAction` in
  `frontend/api.js` maps to existing scene endpoints only; per-scene rerender
  buttons (image/audio/video/full) in the review unit; serial batch rerender
  over the current filtered set in `events.js` (`window.confirm` gate, n/total
  progress, per-scene ok/failed outcomes, fail-isolated continue);
  non-persisted `reviewBatchRerender` run-state in `state.js`; batch bar +
  styles. Task 14 (backend read aggregation) intentionally skipped — all counts
  client-derivable. No backend/provider/scheduler/governance/workflow changes;
  no new endpoints; `_external/Toonflow-app` untouched.
- Wrap-up (DONE — local, uncommitted): tasks 15–16. `docs/director_review_console.md`
  added; `node --check` on app/api/events/render/state/utils pass; helper tests
  pass. Browser visual smoke remains environment-gated (in-app browser blocks
  localhost).

## Notes

- Read-only console (Slice A) ships first and is independently reviewable; batch
  operations are deliberately deferred to Slice B.
- Batch rerender is serial, confirmation-gated, progress-reporting, and
  fail-isolated; it adds NO provider/scheduling logic — it calls existing
  endpoints in sequence.
- No new persisted schema; overview and triage are live-derived/client-side.
- Reuse v0.2.0/v0.3.0 provenance and governance components; do not reimplement
  their data.
- Do not edit generation, governance-scoring, or provider code.

## Handoff to Codex

- Base the implementation branch per the Branching Constraint above (NOT plain
  `main`).
- Files to edit: `frontend/render.js`, `frontend/events.js`, `frontend/state.js`,
  `frontend/api.js`, `frontend/styles.css`; optionally
  `backend/project_runtime.py` (read aggregation only); `docs/`.
- Files NOT to edit: `scripts/run_workflow.py`, `backend/video_generation.py`,
  `backend/consistency_validator.py`, `backend/consistency_governance.py`,
  provider code, and any review/provenance/governance data schema.
- Validation: `node --check` + helper unit tests (+ `py_compile`/test if a
  backend read helper is added).
- Acceptance checklist: AC-1 through AC-8 in `requirements.md`.
- Known risks: `render.js` is the high-traffic file; Slice A must preserve the
  existing review workflow while reorganizing it. Visual smoke is
  environment-gated.
