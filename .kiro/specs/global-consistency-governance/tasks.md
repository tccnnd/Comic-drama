# Implementation Plan: global-consistency-governance

## Overview

Add a governance layer over the existing continuity machinery for v0.3.0,
scoped to `report` + `block` policy only (no automatic regeneration). Work
proceeds bottom-up: extend the stateless scoring engine with prop and camera
checks, add the props registry, build the governance orchestrator (verdict +
policy + ledger), wire persistence and a single render-site call, surface
through API and review console, then docs and checks.

Architectural rule (DD-1): `backend/consistency_validator.py` stays a stateless
scoring engine; all policy, aggregation, persistence, and enforcement live in
the new `backend/consistency_governance.py`. Do NOT edit the validator's
existing similarity algorithms (NG-1). No governance-driven re-render (NG-7).

Files Codex edits: `backend/consistency_validator.py` (additive checks only),
`backend/consistency_governance.py` (new), `backend/scene_graph.py`,
`backend/scene_renderer.py`, `backend/project_models.py`,
`backend/project_runtime.py`, `backend/app.py`, `backend/project_export.py`,
`frontend/*.js`, `frontend/styles.css`, `docs/`.

## Tasks

- [ ] 1. Add prop continuity scoring to the validator
  - In `backend/consistency_validator.py`, add `validate_prop_continuity(image,
    prop_ref)` returning a `ValidationCheck`; reuse existing histogram /
    structural-hash utilities. Missing reference → `info` (non-failing).
  - No project/scene state access; pure scoring (Property 2).
  - _Requirements: 4.1, 4.2, 4.3, NFR-2_

- [ ] 2. Add camera continuity scoring to the validator
  - Add `evaluate_camera_continuity(scene, prev_scene)` — rules-based heuristic
    over `camera_movement` / `camera_speed` / shot plan vs emotion/intent
    change. Returns a `ValidationCheck`; unmotivated change lowers score.
  - _Requirements: 3.1, 3.2, OQ-3_

- [ ] 3. Unit-test the two new validator checks
  - Prop: match / mismatch / missing-ref (info). Camera: motivated vs
    unmotivated transition.
  - _Requirements: 3.2, 4.2, 4.3_

- [ ] 4. Add the props registry to the production bible
  - In `backend/scene_graph.py` `build_production_bible`, add a `props` list
    mirroring the character entry shape (§4.1). Backward-compatible when absent.
  - _Requirements: 1.1, 1.2, 1.3_

- [ ] 5. Create the governance orchestrator — verdict
  - New `backend/consistency_governance.py`:
    `evaluate_scene_governance(project, scene, images, prev_image)` gathers all
    five `ValidationCheck`s (character/style/lighting from existing validator +
    prop/camera), aggregates per §4.2 with precedence fail>warn>pass, info
    neutral, and returns the verdict dict.
  - _Requirements: 2.1, 2.2, 2.3, Property 1, Property 3_

- [ ] 6. Governance orchestrator — policy (report | block)
  - Add `apply_governance_policy(verdict, mode)`: `report` records only;
    `block` sets `deliverable=false` on `fail`. No re-render. Log scene id +
    offending dimensions. Default mode `report` from `CONSISTENCY_POLICY_MODE`.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, Property 4_

- [ ] 7. Governance orchestrator — project continuity ledger
  - Add `build_continuity_ledger(project)` per §4.3: status counts (summing to
    evaluated scene count), per-dimension pass rates, offending scenes,
    blocked-scene count.
  - _Requirements: 6.1, Property 5_

- [ ] 8. Unit-test orchestrator (verdict, policy, ledger)
  - Verdict precedence + info neutrality; policy report/block deliverability;
    ledger counts/pass-rates/offending list.
  - _Requirements: 2.1, 2.3, 5.2, 5.3, 6.1_

- [ ] 9. Persist the verdict and wire the render site
  - Add an `update_scene_governance` save helper (mirror
    `update_scene_consistency_meta`: project lock + scene event) writing
    `scene["governance"]`.
  - In `backend/scene_renderer.py`, replace the inline post-generation
    validation block with one `evaluate_scene_governance` + persist call; keep
    render functions thin. `consistency_meta` behavior unchanged.
  - _Requirements: 2.4, NFR-2_

- [ ] 10. Normalize new fields on load (backward-compat)
  - At the existing project load-normalization site (`project_models.py` or
    `project_runtime.py` — Codex chooses the site already used for scene
    normalization; recent normalization landed in `project_runtime.py`),
    default/normalize `scene["governance"]` (absent → `not_evaluated`) and
    scene/bible `props` so legacy projects load and render unchanged.
  - _Requirements: 1.3, NFR-1, Property 6_

- [ ] 11. Honor block-mode deliverability in export
  - In `backend/project_export.py`, treat `block`-mode undeliverable scenes
    (`governance.deliverable == false`) in export readiness.
  - _Requirements: 5.3, AC-4_

- [ ] 12. Surface verdict + ledger in snapshot/API
  - In `backend/project_runtime.py`, include `scene["governance"]` and the
    project ledger in the snapshot; ensure `backend/app.py` responses expose
    them to the review console.
  - _Requirements: 6.2_

- [ ] 13. Review console continuity display (frontend)
  - In the active frontend modules, render per-scene verdict badges (pass /
    warn / fail / not_evaluated) and a project-level continuity summary; define
    empty/loading/error states.
  - _Requirements: 6.3, AC-7_

- [ ] 14. Integration + backward-compat tests
  - Scene render persists `scene["governance"]` with all five dimensions;
    `block` mode flips export readiness; `report` leaves it unchanged; legacy
    project (no governance/props) loads, renders, exports → `not_evaluated`.
  - _Requirements: AC-2, AC-4, AC-8_

- [ ] 15. Docs update
  - Document the governance verdict (`scene["governance"]`), props registry, and
    continuity ledger contracts in `docs/`.
  - _Requirements: NFR-5, project doc-update rule_

- [ ] 16. Checkpoint — run required checks
  - `python -m py_compile` on edited backend modules
    (`backend\consistency_validator.py`, `backend\consistency_governance.py`,
    `backend\scene_graph.py`, `backend\scene_renderer.py`,
    `backend\project_models.py`, `backend\project_runtime.py`, `backend\app.py`,
    `backend\project_export.py`).
  - `node --check` on edited frontend modules.
  - Targeted pytest for the new validator checks, orchestrator, and ledger.
  - _Requirements: AC-9_

## Implementation Slices

- Slice 1 (proposed first): tasks 1–8 only — validator additions (prop +
  camera scoring), props registry, the new governance orchestrator (verdict,
  policy, ledger), and their unit tests. No render/export/frontend wiring. This
  proves the verdict model in isolation before any high-blast-radius
  integration.
- Slice 2: tasks 9–12 — persistence, render-site wiring, backward-compat
  normalization, block-mode export, API/snapshot exposure.
- Slice 3: tasks 13–16 — review console display, integration/backward-compat
  tests, docs, checks.

## Task Dependency Graph

```json
{
  "waves": [
    ["1", "2", "4"],
    ["3", "5"],
    ["6", "7"],
    ["8", "9", "10"],
    ["11", "12"],
    ["13", "14"],
    ["15"],
    ["16"]
  ]
}
```

## Notes

- v0.3.0 is `report` + `block` only. No governance-driven re-render; the
  `regenerate` policy mode is deferred (NG-7 / Future Hooks).
- Keep `consistency_validator.py` a stateless scoring engine (DD-1). Do not edit
  its existing similarity algorithms (NG-1); only add the two new check
  functions.
- All new fields (`props`, `scene["governance"]`, ledger) are additive; legacy
  projects must load, render, and export unchanged.
- Verdict lives at sibling `scene["governance"]`; `consistency_meta` is left
  backward-compatible (DD-2).
- `CONSISTENCY_MAX_RETRIES` stays validator/runtime config and is non-operative
  for governance policy in this release.

## Handoff to Codex

- Files to edit: see Overview. New module: `backend/consistency_governance.py`.
- Files NOT to edit: `consistency_validator` similarity algorithms,
  `video_providers.py` / provider adapters, `scripts/run_workflow.py` render
  dispatch.
- Validation commands: see task 16.
- Acceptance checklist: AC-1 through AC-9 in `requirements.md`.
- Known risks: the render-site wiring in `scene_renderer.py` (task 9) is the
  highest-blast-radius change — it must preserve existing `consistency_meta`
  behavior and add governance without altering render flow.
