# Design: director-review-console

## Overview

This design evolves the existing storyboard review canvas, in place, into a
production review-and-rerender console. It introduces no new generation,
governance, or provider logic and no new persistence schema. It consumes data
that already exists in the project snapshot — review state (status/rating/notes),
v0.2.0 provenance (`generation_meta`), v0.3.0 governance (`scene["governance"]`),
and the `continuity_ledger` — and makes it unified, triageable, and actionable
(including triggering the rerender endpoints that already exist).

Resolved open questions:
- OQ-1 → **in-place** evolution of the current review canvas; no new tab.
- OQ-2 → **serial** batch rerender with progress; no concurrency.
- OQ-3 → overview is **live-derived** from the snapshot; no persisted
  review-session summary.

## Implementation Base / Branching Constraint

This is a hard constraint for implementation, not optional guidance:

- The **spec branch** may be based on `main`
  (`codex/director-review-console` currently is).
- The **implementation branch** MUST be based on either:
  - `codex/global-consistency-governance` (the v0.3.0 branch), or
  - `main` **after** v0.2.0 and v0.3.0 have merged.
- Do NOT implement `director-review-console` on plain current `main`, because
  that tree lacks the surfaces this spec evolves:
  - video provenance badge/detail (`renderGenerationBadge` / detail) — v0.2.0
  - governance badge/detail (`renderGovernanceBadge` / `renderGovernanceDetail`)
    — v0.3.0
  - continuity ledger snapshot + UI (`continuity_ledger`,
    `renderContinuitySummaryChip`) — v0.3.0
- Rationale: this spec is a refactor/extension of existing UI; without those
  components present, there is nothing to evolve and the work would diverge.

## Architecture

```text
project snapshot (existing)
  ├─ scenes[].review state (status/rating/notes)   [exists]
  ├─ scenes[].generation_meta (provenance)         [v0.2.0]
  ├─ scenes[].governance (verdict)                 [v0.3.0]
  └─ continuity_ledger / timeline summary          [v0.3.0 / v0.2.0]
            │  (live-derived, client-side)
            ▼
   review console (frontend, in-place evolution of the review canvas)
   ┌─────────────────────────────────────────────────────────────┐
   │ Overview header  → ledger + provenance + review-progress     │
   │   (clickable metrics drive the triage filter)                │
   │ Triage bar       → filter + sort (client-side, state-backed) │
   │ Review units[]   → per-scene: state + provenance + governance│
   │                    + readiness + review actions + rerender   │
   └─────────────────────────────────────────────────────────────┘
            │ review actions            │ rerender actions
            ▼                           ▼
   existing review-state save     existing async render endpoints
   path (status/rating/notes)     (rerender_scene_*, generate_scene_assets)
                                          │ task/event mechanism (existing)
                                          ▼
                                   progress + per-scene outcome;
                                   on completion → provenance/governance refresh
```

## Components and Interfaces

Frontend (primary surface; `frontend/render.js`, `frontend/events.js`,
`frontend/state.js`, `frontend/api.js`, `frontend/styles.css`):

| Component | Responsibility |
| --- | --- |
| `deriveReviewOverview(project)` | Live-derive overview metrics from snapshot: ledger status counts, real/fallback counts, review-progress counts. No persistence. |
| `renderReviewOverviewHeader(project)` | Render overview metrics; each metric is a clickable filter trigger. |
| `reviewTriageState` (in `state.js`) | Active filter + sort, reflected in existing URL/state pattern. |
| `applyReviewTriage(scenes, triage)` | Pure client-side filter+sort producing the visible scene list; empty-state aware. |
| `renderReviewTriageBar(project)` | Filter controls (status/governance/provenance/deliverability/rating) + sort selector. |
| `renderReviewUnit(scene, project)` | Unified per-scene unit; composes existing `renderGenerationBadge/Detail` (v0.2.0) and `renderGovernanceBadge/Detail` (v0.3.0) + review state + readiness + actions. |
| `renderReviewActions(scene)` | In-place status/rating/notes controls (existing save path) + per-scene rerender buttons. |
| `renderBatchRerenderBar(project, triage)` | Batch rerender over the filtered set, with confirmation + progress. |

Backend (read aggregation only, if needed):

| Component | Responsibility |
| --- | --- |
| snapshot (existing `project_snapshot`) | Already exposes review state, `generation_meta`, `governance`, `continuity_ledger`. Preferred: no change. |
| optional read helper | Only if the overview needs a count not derivable client-side; must be read-only aggregation over existing fields. |
| existing rerender endpoints | `rerender_scene_image/audio/video`, `generate_scene_assets` — invoked, not modified. |

## Data Models

No new persisted data models. The console is a live view over existing snapshot
fields. The only new *client-side* (non-persisted) structures are the triage
state and the derived overview, defined in Data Contracts.

## Data Contracts

### Triage state (client-side, non-persisted)

```json
{
  "filters": {
    "review_status": ["pending", "approved", "rejected"],
    "governance_status": ["fail", "warn"],
    "provenance": ["fallback"],
    "deliverable": "blocked",
    "min_rating": 0
  },
  "sort": "governance_severity"
}
```

`sort` ∈ `scene_order | rating | governance_severity | provenance_fallback_first`.

### Derived overview (client-side, non-persisted)

```json
{
  "continuity": { "pass": 4, "warn": 1, "fail": 1, "not_evaluated": 0, "blocked": 1 },
  "provenance": { "real_video": 0, "fallback": 5, "unknown": 0 },
  "review": { "approved": 2, "pending": 3, "rejected": 0, "unrated": 1, "total": 5 }
}
```

All values are computed from the snapshot at render time (OQ-3: live-derived).

## Behavior: rerender actions

- Per-scene rerender buttons map 1:1 to existing operations: image / audio /
  video / full rebuild (`generate_scene_assets`).
- Batch rerender (FR-5.2): operates over the **current filtered set**, runs
  **serially** (OQ-2), shows progress (e.g. "3/7 done"), and reports a per-scene
  outcome list. A confirmation step states scene count and that renders are
  heavy/long.
- Actions dispatch through the **existing async task/event path**; the console
  never blocks (NFR-4). On each scene's completion, that scene's review unit
  refreshes provenance + governance from the updated snapshot (FR-5.4 / AC-6).

## Failure and Fallback Behavior

- Missing provenance/governance → review unit shows `unknown` / `not_evaluated`
  (NFR-1 / AC-7); overview counts them in the respective "unknown/not_evaluated"
  buckets.
- A rerender failure surfaces via the existing task/event error channel and is
  shown in the per-scene outcome; batch continues to the next scene (serial,
  fail-isolated) and reports failures at the end.
- Empty triage result → explicit empty state (FR-3.3).
- Backend unavailable for an action → existing error toast/notice path; console
  remains usable for review.

## Security and Credential Considerations

- No new endpoints handling secrets; rerenders reuse existing endpoints and
  their provider-credential handling.
- Batch rerender is gated by explicit confirmation (NFR-5) to avoid accidental
  cost/load.
- No provenance error text is newly exposed beyond what v0.2.0 already
  sanitizes and stores.

## Correctness Properties

Property 1: Single-source review unit — every visible scene renders one review
unit composing review state, provenance, governance, and readiness; absent
signals render as unknown/not_evaluated without error.
**Validates: Requirements 1.1, 1.2, 6.1**

Property 2: Component reuse — the console renders provenance and governance via
the existing v0.2.0/v0.3.0 components and reads existing snapshot fields; it
defines no new persisted data model.
**Validates: Requirements 1.3, 6.2**

Property 3: Triage soundness — the visible list equals the snapshot scenes
filtered and sorted by the active triage state; combined filters intersect and
an empty result yields the empty state.
**Validates: Requirements 3.1, 3.2, 3.3**

Property 4: Live overview accuracy — overview metrics equal a live derivation
over the snapshot, and review-state edits update them without a full reload.
**Validates: Requirements 2.1, 2.2, 4.2**

Property 5: Action passthrough — per-scene and batch rerenders invoke only the
existing render operations; batch runs serially with confirmation and reports
per-scene outcomes.
**Validates: Requirements 5.1, 5.2, 5.3**

Property 6: Post-rerender refresh — after a rerender completes, the affected
scene's provenance and governance reflect the updated snapshot.
**Validates: Requirements 5.4**

## Error Handling

- Client-side triage/overview are pure functions over the snapshot; malformed or
  missing fields default to unknown/not_evaluated rather than throwing.
- Review-state saves reuse the existing save/error path.
- Rerender dispatch reuses the existing async task/event mechanism; failures are
  reported per scene and never abort the whole batch.
- Overview recomputes on snapshot refresh; no stale persisted summary to
  invalidate (OQ-3).

## Affected Files and Module Boundaries

| File | Change | Risk |
| --- | --- | --- |
| `frontend/render.js` | In-place: overview header, triage bar, unified review unit, batch bar; reuse existing badge/detail renderers. | High |
| `frontend/events.js` | Wire filter/sort, review actions, per-scene + batch rerender dispatch. | Medium |
| `frontend/state.js` | Add triage state to existing state model. | Medium |
| `frontend/api.js` | Use existing review/rerender endpoints; add calls only if missing. | Low |
| `frontend/styles.css` | Console layout/styles. | Low |
| `backend/project_runtime.py` (optional) | Only if an overview count isn't client-derivable; read-only aggregation. | Low |

Out of scope (do not edit): generation logic (`scripts/run_workflow.py`,
`video_generation.py`), governance scoring (`consistency_validator.py`,
`consistency_governance.py`), provider code, and any data schema for review /
provenance / governance.

## Testing Strategy

- Frontend: `node --check` on edited modules. Where unit-testable, test the pure
  helpers `deriveReviewOverview` and `applyReviewTriage` (filter/sort/empty).
- Backend (only if a read helper is added): `py_compile` + a targeted test that
  the aggregation matches the snapshot.
- Manual/visual smoke of the console is expected to be environment-gated (the
  in-app browser blocks localhost); record it as pending like prior specs.

## Rollback Plan

- The console is an in-place frontend evolution consuming existing data; reverting
  the frontend changes restores the prior review canvas with no data migration.
- No schema or backend behavior change (or only a read helper), so rollback is
  frontend-local.

## Design Decisions

- DD-1 In-place evolution of the review canvas, not a new tab (OQ-1) — preserves
  existing navigation and review workflow.
- DD-2 Serial batch rerender with progress (OQ-2) — heavy render chain; serial is
  easier to recover, log, and reason about, and avoids resource contention.
- DD-3 Live-derived overview (OQ-3) — no new persisted review-session schema;
  matches reuse-not-rewrite.
- DD-4 Frontend-first, consuming existing snapshot/endpoints; backend change (if
  any) limited to read aggregation (FR-6) — contains blast radius.
- DD-5 Reuse v0.2.0/v0.3.0 display components rather than reimplementing
  provenance/governance rendering (NFR-2).
