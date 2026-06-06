# Requirements Document

## Introduction

Comic Drama Workflow already has the seeds of continuity management: a
`production_bible` (global rules + per-character appearance/clothing/negative
constraints/reference images), a `consistency_validator` that scores character
identity, style, and lighting after generation, and per-scene `consistency_meta`
persistence. But these pieces are advisory and siloed: validation results are
logged as warnings and stored on the scene, regeneration is not actually driven
by them, prop and camera continuity are declared as rules but never tracked or
checked, and there is no project-level view of where continuity is breaking.

`global-consistency-governance` turns these scattered signals into a managed
system: a single continuity model spanning character, lighting, environment,
prop, and camera dimensions; a per-scene governance check that produces a
structured verdict; a project-level continuity ledger and report; and explicit,
configurable policy for what a failing verdict does (warn, block, or trigger
regeneration). It does not replace the existing validator or production bible —
it elevates and connects them.

This is the planned spec `global-consistency-governance` from
`.kiro/specs/README.md` (manage character, lighting, environment, prop, and
camera continuity). It targets release line `v0.3.0`.

## Glossary

- **continuity dimension**: One of the governed axes — character, lighting,
  environment, prop, camera.
- **production_bible**: The existing global continuity contract produced by
  `build_production_bible` (rules + characters + scene continuity).
- **consistency_meta**: The existing per-scene record where validation scores
  and warnings are stored.
- **governance verdict**: A structured per-scene result aggregating dimension
  scores into pass / warn / fail with reasons and offending dimensions.
- **continuity ledger**: A project-level rollup of per-scene verdicts used for
  review and gating.
- **governance policy**: Configurable behavior on a failing verdict —
  `report` (record + warn) or `block` (mark scene not deliverable).
- **prop**: A named recurring object tied to characters/scenes that must stay
  visually stable when it reappears.

## Problem Statement

1. Validation is advisory only — `validate_scene_generation` logs warnings and
   writes scores into `consistency_meta`, but nothing consumes them to gate or
   regenerate. The documented loop "fail: retry with stronger constraints" is
   not wired.
2. Coverage is partial — character/style/lighting checks exist; prop and camera
   continuity are declared in `production_bible.rules` but never measured.
3. No project-level visibility — there is no aggregated continuity report a
   reviewer can read to find which scenes/dimensions are drifting.
4. No policy model — there is no single place that decides what a failing scene
   should do, so behavior is inconsistent across render paths.
5. No prop model — recurring objects have no representation in the bible or the
   scene schema.

## User Value

- A producer gets a single continuity contract covering all five dimensions and
  a clear per-scene verdict instead of scattered log warnings.
- A reviewer can open a continuity report/ledger and jump straight to the
  scenes and dimensions that are drifting.
- The pipeline can enforce continuity: block undeliverable scenes or trigger a
  bounded regeneration, under explicit configurable policy.
- Prop and camera continuity become first-class, so recurring objects and shot
  grammar stay stable across an episode.

## Requirements

### FR-1 Unified continuity model

**User Story:** As a producer, I want one continuity model spanning all five
dimensions, so that governance is consistent and complete.

1.1 The system SHALL define a continuity model covering character, lighting,
    environment, prop, and camera dimensions, building on the existing
    `production_bible`.
1.2 The model SHALL add a `props` registry to the production bible: named
    recurring objects with description, owning characters/scenes, and optional
    reference image — mirroring the existing character entry shape.
1.3 The model SHALL be additive and backward-compatible: projects without a
    `props` registry or governance fields SHALL load and render unchanged.

### FR-2 Per-scene governance verdict

**User Story:** As a reviewer, I want a structured per-scene verdict, so that I
can see exactly which continuity dimensions passed, warned, or failed.

2.1 After scene generation, the system SHALL produce a governance verdict per
    scene aggregating per-dimension scores into an overall status of `pass`,
    `warn`, or `fail`.
2.2 The verdict SHALL reuse existing checks where present (character identity,
    style, lighting from `consistency_validator`) and add prop and camera
    continuity checks.
2.3 The verdict SHALL record, per dimension: score, status, threshold used, and
    a human-readable reason.
2.4 The verdict SHALL be persisted on the scene (within or alongside
    `consistency_meta`) and survive project reload.

### FR-3 Camera continuity check

**User Story:** As a director, I want unmotivated camera jumps flagged, so that
shot grammar stays coherent.

3.1 The system SHALL evaluate camera continuity using existing scene/shot
    fields (`camera_movement`, `camera_speed`, shot plan) against the
    `production_bible` rule `avoid_unmotivated_camera_jumps`.
3.2 The check SHALL flag transitions that violate configured camera-continuity
    constraints (e.g. abrupt movement/speed changes without an emotional or
    intent change) and contribute a dimension score to the verdict.

### FR-4 Prop continuity check

**User Story:** As a producer, I want recurring props to stay visually stable,
so that objects don't change between appearances.

4.1 The system SHALL track which props appear in which scenes via the FR-1.2
    registry.
4.2 When a prop reappears, the system SHALL compare the current scene image
    against the prop reference (reusing the existing histogram/structural
    similarity utilities) and contribute a dimension score to the verdict.
4.3 Absence of a prop reference SHALL degrade gracefully to an informational
    (non-failing) result.

### FR-5 Governance policy and enforcement

**User Story:** As a producer, I want to choose what a failing verdict does, so
that I can warn during drafting and enforce at delivery.

5.1 The system SHALL support a configurable governance policy via
    `CONSISTENCY_POLICY_MODE` with modes `report` and `block`, defaulting to
    `report`.
5.2 In `report` mode, a failing verdict SHALL be recorded and surfaced but SHALL
    NOT change deliverability.
5.3 In `block` mode, a failing verdict SHALL mark the scene as not deliverable
    and SHALL be reflected in export readiness.
5.4 Governance SHALL NOT trigger automatic re-rendering in v0.3.0. The existing
    `CONSISTENCY_MAX_RETRIES` remains validator/runtime config and is
    explicitly non-operative for governance policy in this release.
5.5 Policy decisions SHALL be logged with scene id and offending dimensions.

### FR-6 Project continuity ledger and report

**User Story:** As a reviewer, I want a project-level continuity report, so that
I can find drift across the whole episode quickly.

6.1 The system SHALL build a project-level continuity ledger aggregating
    per-scene verdicts: counts by status, per-dimension pass rates, and a list
    of offending scenes.
6.2 The ledger SHALL be exposed through the project snapshot/API consumed by the
    review console.
6.3 The review console SHALL display per-scene verdict badges and a
    project-level continuity summary, with empty/loading/error states.

## Non-Functional Requirements

- NFR-1 Backward compatibility: existing projects load, render, and export
  without governance fields; missing data defaults to "not evaluated".
- NFR-2 Reuse, not rewrite: build on `consistency_validator`,
  `production_bible`, and `consistency_meta`; do not duplicate similarity math.
- NFR-3 No new heavy dependencies; reuse PIL-based utilities already present.
- NFR-4 Bounded cost: governance SHALL NOT add any provider calls in v0.3.0
  (no automatic regeneration).
- NFR-5 Deterministic, versioned JSON contracts for verdict and ledger.
- NFR-6 Observability: per-dimension scores, thresholds, and policy actions are
  logged with scene identifiers.

## Non-Goals

- NG-1 Replacing the existing `consistency_validator` similarity algorithms.
- NG-2 ML/embedding-based identity models (current histogram/hash approach is
  retained; upgrades are a future spec).
- NG-3 Video-provider mainline changes (owned by `video-provider-mainline`).
- NG-4 Cost accounting (owned by the future `provider-cost-controls` spec).
- NG-5 A full review-console redesign (owned by `director-review-console`);
  this spec only adds verdict/ledger display.
- NG-6 Cross-project or cross-episode continuity.
- NG-7 Automatic regeneration / remediation loops. v0.3.0 is non-actuating
  beyond `block`-mode deliverability. A `regenerate` policy mode may be added in
  a later spec once project-level verdicts prove stable (see Future Hooks).

## Future Hooks

- A `regenerate` policy mode (failing verdict triggers a bounded re-render with
  stronger constraints) is intentionally deferred. It introduces a render
  feedback loop between governance and the renderer and should get its own spec
  after the verdict model and ledger are proven in production.

## Acceptance Criteria

- AC-1 A project can define props in the production bible; a project without
  props loads and renders unchanged.
- AC-2 After rendering a scene, a governance verdict is persisted with
  per-dimension scores/status/reasons for all five dimensions and an overall
  status.
- AC-3 Camera and prop continuity checks produce dimension scores; missing
  references degrade to non-failing informational results.
- AC-4 In `block` mode, a failing scene is marked not deliverable and export
  readiness reflects it; in `report` mode deliverability is unchanged.
- AC-5 Governance performs no automatic re-rendering in v0.3.0; only `report`
  and `block` modes are operative.
- AC-6 The project continuity ledger aggregates verdicts (status counts,
  per-dimension pass rates, offending scenes) and is exposed via the API.
- AC-7 The review console shows per-scene verdict badges and a project-level
  continuity summary.
- AC-8 Backward compat: a legacy project (no governance fields) loads, renders,
  and exports; verdicts default to "not evaluated".
- AC-9 Checks pass: `python -m py_compile` on edited backend modules and
  `node --check` on edited frontend modules; targeted tests for the verdict,
  camera/prop checks, policy modes, and ledger pass.

## Open Questions

- OQ-1 Should the governance verdict live inside `consistency_meta` or as a
  sibling `governance` key on the scene? (Design to decide; sibling key likely
  cleaner for backward-compat.)
- OQ-2 Default policy mode for v0.3.0: `report` (recommended) vs `block`.
- OQ-3 Camera-continuity heuristic: rules-based (movement/speed deltas vs
  emotion/intent change) for v0.3.0, with embedding-based motion analysis
  deferred — confirm scope.
