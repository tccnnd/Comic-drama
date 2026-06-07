# Requirements Document

## Introduction

The review canvas today is a storyboard viewer with status, rating, notes,
filters, and version comparison, onto which two recent feature lines bolted
read-only signals: v0.2.0 added per-scene generation provenance (real-video vs
2.5D fallback, provider, attempts, errors) and v0.3.0 added continuity
governance (per-scene verdict badge, five-dimension detail, project continuity
ledger, block-mode deliverability). The data is now rich, but the surface was
designed as a storyboard review, not as a production review-and-rerender
console: the new signals are displayed but not actionable, not filterable, and
not organized for a director triaging an episode.

`director-review-console` elevates the existing review canvas into a purpose-built
production review console. It does not invent new generation or governance data;
it makes the data that v0.2.0 and v0.3.0 already produce reviewable, filterable,
and actionable from one place — including triggering the rerender actions that
already exist in the backend (`rerender_scene_image/audio/video`,
`generate_scene_assets`).

This is the planned spec `director-review-console` from `.kiro/specs/README.md`
("expand review canvas into a production review and rerender console"). It
targets release line `v0.4.0`.

## Glossary

- **review console**: The production review surface this spec defines, evolving
  the current storyboard review canvas in `frontend/render.js`.
- **provenance**: Per-scene generation metadata from v0.2.0
  (`scene["generation_meta"]`): provider, backend, `is_real_video`,
  `fallback_used`, attempts, error.
- **governance verdict**: Per-scene continuity result from v0.3.0
  (`scene["governance"]`): overall status + five dimension scores +
  deliverability.
- **continuity ledger**: Project-level governance rollup from v0.3.0
  (`continuity_ledger` in the snapshot).
- **rerender action**: An existing backend scene operation
  (`rerender_scene_image`, `rerender_scene_audio`, `rerender_scene_video`,
  `generate_scene_assets`) the console can trigger.
- **triage**: Filtering/sorting scenes by review-relevant signals (status,
  fallback, governance, rating) to find what needs attention.
- **review state**: Existing per-scene review fields (status, rating, notes)
  already in the project model.

## Problem Statement

1. The new provenance and governance signals are read-only badges; a reviewer
   cannot act on them (e.g. "rerender every scene that fell back to 2.5D")
   without manually hunting scene by scene.
2. There is no triage: scenes cannot be filtered or sorted by fallback,
   governance status, deliverability, or rating, so finding the scenes that need
   attention in a long episode is manual.
3. Review signals are scattered: provenance, governance, asset readiness, and
   review state (status/rating/notes) appear in different places rather than a
   single per-scene review unit.
4. Rerender actions exist in the backend but are not surfaced as review-driven
   batch/contextual actions from the console.
5. No console-level overview ties the project continuity ledger and provenance
   summary to the work queue.

## User Value

- A director can open one console and immediately see episode health: how many
  scenes are real-video vs fallback, how many pass/warn/fail governance, how
  many are blocked or unrated.
- A reviewer can triage by filtering/sorting to the scenes that need attention
  (fallbacks, governance failures, undeliverable, low rating) instead of
  scrolling the whole storyboard.
- A reviewer can act in place: approve/rate/note and trigger the appropriate
  rerender directly from the scene's review unit, including a batch rerender of a
  filtered set.
- The console gives a single source of truth for review decisions, reducing the
  manual cross-referencing the current canvas requires.

## Requirements

### FR-1 Unified per-scene review unit

**User Story:** As a reviewer, I want all review-relevant signals for a scene in
one unit, so that I can judge and act without hunting across the UI.

1.1 The console SHALL present each scene as a single review unit combining:
    thumbnail/clip, review state (status, rating, notes), provenance
    (`generation_meta`), governance verdict (`governance`), and asset readiness.
1.2 The review unit SHALL degrade gracefully when any signal is absent
    (provenance/governance `not_evaluated`, no rating) without errors.
1.3 The review unit SHALL reuse the existing provenance and governance display
    components from v0.2.0 / v0.3.0 rather than redefining their data shapes.

### FR-2 Console overview header

**User Story:** As a director, I want an episode-health overview, so that I can
see where the work is before drilling in.

2.1 The console SHALL show a project-level overview combining the continuity
    ledger (status counts, blocked count) and the timeline provenance summary
    (real-video vs fallback counts).
2.2 The overview SHALL show review progress: counts by review status and how
    many scenes are unrated/unreviewed.
2.3 The overview metrics SHALL be clickable to drive the triage filter (e.g.
    clicking "fallback 5" filters the list to fallback scenes).

### FR-3 Triage: filter and sort

**User Story:** As a reviewer, I want to filter and sort scenes by review
signals, so that I can focus on what needs attention.

3.1 The console SHALL filter scenes by: review status, governance status
    (pass/warn/fail/not_evaluated), provenance (real-video / fallback),
    deliverability (blocked), and rating threshold.
3.2 The console SHALL sort scenes by scene order, rating, governance severity,
    and provenance (fallback-first).
3.3 Filters SHALL be combinable and reflect an empty state when no scene
    matches.
3.4 The active filter/sort SHALL be reflected in the URL/state so a view can be
    returned to (reuse existing frontend state patterns).

### FR-4 In-console review actions

**User Story:** As a reviewer, I want to set status/rating/notes from the review
unit, so that I can record decisions without leaving the console.

4.1 The console SHALL let a reviewer set per-scene review status, rating, and
    notes in place, persisting through the existing review-state save path.
4.2 Review-state changes SHALL update the overview metrics without a full
    reload (reuse existing event/refresh patterns).

### FR-5 Rerender actions from the console

**User Story:** As a reviewer, I want to trigger rerenders from the console, so
that I can fix flagged scenes immediately.

5.1 The console SHALL expose per-scene rerender actions that call the existing
    backend operations (`rerender_scene_image`, `rerender_scene_audio`,
    `rerender_scene_video`, `generate_scene_assets`) — no new render logic.
5.2 The console SHALL support a batch rerender over the current filtered set
    (e.g. "rerender all fallback scenes"), with an explicit confirmation step
    given the cost/duration.
5.3 Rerender actions SHALL show progress/queued state and surface failures using
    existing task/event mechanisms; the console SHALL NOT block on long renders.
5.4 After a rerender completes, the scene's provenance and governance verdict
    SHALL refresh in the review unit.

### FR-6 Non-destructive, additive UI

**User Story:** As a maintainer, I want the console to build on existing review
data and endpoints, so that risk stays contained to the frontend.

6.1 The console SHALL be implemented primarily in the frontend, consuming the
    existing project snapshot/API (provenance, governance, ledger, review
    state) and existing rerender/review endpoints.
6.2 Any backend change SHALL be limited to read aggregation or exposing existing
    data already present in the snapshot; no changes to generation, governance
    scoring, or provider logic.

## Non-Functional Requirements

- NFR-1 Backward compatibility: projects without provenance/governance render in
  the console with `not_evaluated`/unknown states; no errors.
- NFR-2 Reuse, not rewrite: build on existing review-state, provenance, and
  governance components and endpoints; do not duplicate their data models.
- NFR-3 Responsiveness: filtering/sorting/overview update client-side without a
  full project reload.
- NFR-4 Non-blocking actions: rerenders run via the existing async task/event
  path; the console stays responsive.
- NFR-5 Safety: batch rerender requires explicit confirmation and reports
  per-scene outcomes.
- NFR-6 Frontend syntax validated via `node --check`; backend (if touched) via
  `py_compile` and targeted tests.

## Non-Goals

- NG-1 New generation, governance-scoring, or provider logic (owned by the
  respective specs).
- NG-2 Automatic/AI-driven rerender decisions — all rerenders are reviewer-
  initiated (governance `regenerate` remains deferred per the governance spec).
- NG-3 Cost accounting/quotas (owned by the future `provider-cost-controls`
  spec); the console may *display* attempts/fallback but does not meter cost.
- NG-4 Multi-user/concurrent review workflows or role-based permissions.
- NG-5 A new persistence model for review data; reuse existing review-state
  fields.
- NG-6 Export pipeline changes beyond reflecting existing block-mode
  deliverability already implemented in v0.3.0.

## Acceptance Criteria

- AC-1 Each scene appears as a unified review unit showing review state,
  provenance, governance verdict, and asset readiness; missing signals show
  graceful unknown/not_evaluated states.
- AC-2 The overview header shows continuity ledger counts, real-vs-fallback
  provenance counts, and review progress; overview metrics are clickable to
  filter.
- AC-3 Scenes can be filtered by review status, governance status, provenance,
  deliverability, and rating, and sorted by order/rating/governance/provenance;
  combined filters and empty state work.
- AC-4 A reviewer can set status/rating/notes from the review unit and see the
  overview update without a full reload.
- AC-5 Per-scene rerender actions invoke the existing backend operations; a
  batch rerender over the filtered set runs after explicit confirmation and
  reports per-scene outcomes.
- AC-6 After a rerender, the affected scene's provenance and governance refresh
  in the console.
- AC-7 Backward compat: a legacy project (no provenance/governance) loads in the
  console with unknown/not_evaluated states and no errors.
- AC-8 Checks pass: `node --check` on edited frontend modules; `py_compile` +
  targeted tests for any backend read-aggregation change.

## Open Questions

- OQ-1 Should the console replace the current storyboard review view in place,
  or be a new tab alongside it? (Design to decide; in-place evolution likely
  matches "expand the review canvas".)
- OQ-2 Batch rerender concurrency: serial (safer, slower) vs limited parallel —
  and whether to cap it. (Design to decide; serial with progress is the safer
  default.)
- OQ-3 Does the overview need a persisted "review session" summary, or is it
  always derived live from the snapshot? (Live-derived is simpler and matches
  NFR-2.)
