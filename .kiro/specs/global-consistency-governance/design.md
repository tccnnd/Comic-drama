# Design: global-consistency-governance

## Overview

This design adds a governance layer over the existing continuity machinery
without rewriting it. The core architectural rule (per the maintainer
constraint): `consistency_validator.py` remains the **scoring engine** — pure,
stateless, image-in / score-out — and a new **governance orchestrator**
(`backend/consistency_governance.py`) owns policy, aggregation, persistence, and
enforcement. The validator never learns about policy modes, deliverability, or
project state.

It governs five continuity dimensions (character, lighting, environment, prop,
camera). Character/style/lighting scoring already exists in the validator; this
spec adds prop and camera scoring functions to the same engine, then aggregates
all five into a per-scene **governance verdict** (sibling `scene["governance"]`
key), rolls verdicts into a **project continuity ledger**, and applies a
configurable **policy** (`report` default; `block` opt-in). Automatic
regeneration is explicitly out of scope for v0.3.0 (see Non-Goals / Future
Hooks in requirements) to avoid a render feedback loop before the verdict model
is proven.

Resolved open questions:
- OQ-1 → verdict lives at `scene["governance"]`; `consistency_meta` stays as-is.
- OQ-2 → default policy `report`; `block` opt-in.
- OQ-3 → rules-based camera heuristic for v0.3.0; motion embeddings deferred.

## Architecture

```text
                  consistency_validator.py  (SCORING ENGINE — stateless)
                  ┌───────────────────────────────────────────────┐
                  │ validate_character_identity()  [exists]        │
                  │ validate_style_consistency()   [exists]        │
                  │ validate_lighting_continuity() [exists]        │
                  │ validate_prop_continuity()     [NEW]           │
                  │ evaluate_camera_continuity()   [NEW]           │
                  └───────────────────────────────────────────────┘
                                     ▲ scores (ValidationCheck)
                                     │
   backend/consistency_governance.py │  (ORCHESTRATOR — policy + state)
   ┌─────────────────────────────────┴───────────────────────────┐
   │ evaluate_scene_governance(project, scene, images) -> verdict │
   │ apply_governance_policy(verdict, mode) -> action             │
   │ build_continuity_ledger(project) -> ledger                   │
   └──────────────────────────────────────────────────────────────┘
        │ persist                         │ enforce
        ▼                                 ▼
   scene["governance"]            policy action: report | block
        │                                 │
        ▼                                 ▼
   project ledger (snapshot/API)   export readiness (block-mode only)
        │
        ▼
   review console badges + summary
```

Call site: `backend/scene_renderer.py` already runs post-generation validation
inside `rerender_scene_video` / `generate_scene_assets`. That block is replaced
by a single call to the orchestrator's `evaluate_scene_governance`, keeping the
render functions thin.

## Components and Interfaces

| Component | Location | Responsibility |
| --- | --- | --- |
| `validate_prop_continuity(image, prop_ref)` | `backend/consistency_validator.py` | NEW scoring fn; reuse histogram/structural-hash utilities. Returns `ValidationCheck`. |
| `evaluate_camera_continuity(scene, prev_scene)` | `backend/consistency_validator.py` | NEW rules-based scoring fn (movement/speed deltas vs emotion/intent change). Returns `ValidationCheck`. |
| `evaluate_scene_governance(...)` | `backend/consistency_governance.py` (NEW) | Gather all five `ValidationCheck`s, aggregate into a verdict, persist `scene["governance"]`. |
| `apply_governance_policy(verdict, mode, ...)` | `backend/consistency_governance.py` (NEW) | Decide action for a failing verdict: `report` (record) or `block` (set undeliverable). No re-render in v0.3.0. |
| `build_continuity_ledger(project)` | `backend/consistency_governance.py` (NEW) | Aggregate verdicts into the project ledger. |
| `props` registry | `backend/scene_graph.py` (`build_production_bible`) | Add `props` list mirroring character entry shape. |
| Scene loader | `backend/project_models.py` or `backend/project_runtime.py` | Default/normalize `governance` + scene `props` on load at the existing normalization site (recent normalization landed in `project_runtime.py`). |
| Snapshot/API | `backend/project_runtime.py`, `backend/app.py` | Expose `governance` per scene and the ledger at project level. |
| Export readiness | `backend/project_export.py` | Honor `block`-mode undeliverable scenes. |
| Review console | `frontend/*.js`, `frontend/styles.css` | Verdict badges + project continuity summary. |

## Data Models

The governed contracts (`props` registry, scene `governance` verdict, project
`continuity_ledger`) are defined in Data Contracts below.

## Data Contracts

### 4.1 props registry (additive, in production_bible)

```json
"props": [
  {
    "prop_id": "jade_pendant",
    "name": "Jade Pendant",
    "description": "Green jade pendant on a red cord",
    "owner_characters": ["Lin"],
    "scenes": ["scene_002", "scene_007"],
    "reference_image_path": "props/jade_pendant.png",
    "reference_meta": {}
  }
]
```

### 4.2 scene["governance"] verdict (sibling key; consistency_meta unchanged)

```json
{
  "version": 1,
  "scene_id": "scene_002",
  "scene_order": 2,
  "status": "warn",                 // pass | warn | fail | not_evaluated
  "evaluated_at": "2026-06-06T12:00:00Z",
  "dimensions": {
    "character": { "status": "pass", "score": 0.82, "threshold": 0.6, "reason": "" },
    "lighting":  { "status": "warn", "score": 0.54, "threshold": 0.5, "reason": "brightness shift vs prev scene" },
    "environment": { "status": "pass", "score": 0.78, "threshold": 0.6, "reason": "" },
    "prop":      { "status": "info", "score": 0.0,  "threshold": 0.6, "reason": "no prop reference" },
    "camera":    { "status": "pass", "score": 1.0,  "threshold": 0.5, "reason": "" }
  },
  "offending_dimensions": ["lighting"],
  "policy": { "mode": "report", "action": "recorded" },
  "deliverable": true
}
```

Status precedence for the overall verdict: any `fail` → `fail`; else any `warn`
→ `warn`; else `pass`. `info` (missing reference) never worsens the verdict.

### 4.3 project continuity_ledger (project-level)

```json
{
  "version": 1,
  "evaluated_scene_count": 6,
  "status_counts": { "pass": 4, "warn": 1, "fail": 1, "not_evaluated": 0 },
  "dimension_pass_rates": {
    "character": 1.0, "lighting": 0.83, "environment": 1.0,
    "prop": 1.0, "camera": 0.83
  },
  "offending_scenes": [
    { "scene_id": "scene_005", "status": "fail", "offending_dimensions": ["character"] }
  ],
  "policy_mode": "report",
  "blocked_scene_count": 0
}
```

## Failure and Fallback Behavior

- Missing reference (prop without reference image, first scene with no previous
  image) → dimension `status="info"`, does not fail the verdict (FR-4.3).
- Scoring exception in the validator → that dimension scores `info` with the
  reason captured; governance never crashes a render (mirrors the validator's
  existing try/except-to-neutral pattern).
- `report` (default): verdict recorded, `deliverable` unchanged.
- `block`: failing verdict sets `deliverable=false`; export readiness reflects
  it (FR-5.3, AC-4).
- Automatic regeneration is NOT performed in v0.3.0 (FR-5.4, NG-7);
  `CONSISTENCY_MAX_RETRIES` remains validator/runtime config and is non-operative
  for governance policy.
- Not evaluated / legacy: `governance` absent → treated as `not_evaluated`;
  load/render/export proceed (NFR-1, AC-8).

## Security and Credential Considerations

- No new secrets or network calls; governance only scores existing images and
  records verdicts.
- Reference image paths are project-relative; governance stores paths and
  scores only — no image bytes, no credentials.
- Persisted reasons are short human-readable strings; no sensitive data.

## Correctness Properties

Property 1: Verdict completeness — for every evaluated scene, `scene["governance"]`
contains all five dimensions, each with status/score/threshold/reason, and an
overall status derived by the precedence rule.
**Validates: Requirements 2.1, 2.3**

Property 2: Engine purity — `consistency_validator` functions return scores
without reading or writing project/scene state or policy; all persistence and
policy live in the orchestrator.
**Validates: Requirements 2.2**

Property 3: Graceful degradation — missing prop reference or missing previous
image yields an `info` dimension that never changes a `pass`/`warn` into `fail`.
**Validates: Requirements 4.3, 3.2**

Property 4: Policy soundness — `report` never changes deliverability; `block`
sets `deliverable=false` on `fail`. Governance performs no re-rendering in
v0.3.0.
**Validates: Requirements 5.2, 5.3, 5.4**

Property 5: Ledger accuracy — ledger `status_counts` sum to
`evaluated_scene_count`, and `offending_scenes` lists exactly the scenes whose
verdict is `warn` or `fail`.
**Validates: Requirements 6.1**

Property 6: Backward compatibility — a project without `props` or `governance`
loads, renders, and exports; verdicts default to `not_evaluated`.
**Validates: Requirements 1.3**

## Error Handling

- Validator scoring errors are caught per-dimension and converted to `info`
  with the exception text in `reason`; the verdict still completes.
- Orchestrator persistence reuses the existing `update_scene_consistency_meta`
  save path pattern (project lock + scene event) for `scene["governance"]`.
- Ledger build tolerates partial/legacy verdicts by classifying them as
  `not_evaluated`.

## Affected Files and Module Boundaries

| File | Change | Risk |
| --- | --- | --- |
| `backend/consistency_validator.py` | Add `validate_prop_continuity`, `evaluate_camera_continuity`; no policy/state. | Medium |
| `backend/consistency_governance.py` | NEW orchestrator: verdict, policy, ledger. | High |
| `backend/scene_graph.py` | Add `props` registry to `build_production_bible`. | Medium |
| `backend/scene_renderer.py` | Replace inline validation block with one orchestrator call. | High |
| `backend/project_models.py` | Normalize `governance` + scene `props` on load. | Medium |
| `backend/project_runtime.py` | Expose `governance` + ledger in snapshot. | Medium |
| `backend/app.py` | Surface ledger/verdict in API responses. | Low |
| `backend/project_export.py` | Honor `block`-mode deliverability. | Medium |
| `frontend/*.js`, `frontend/styles.css` | Verdict badges + continuity summary. | Medium |
| `docs/` | Document governance verdict + ledger contracts. | Low |

Out of scope (do not edit): `consistency_validator` similarity algorithms
(NG-1), `video_providers.py` / provider adapters (other specs),
`scripts/run_workflow.py` render dispatch (no governance-driven re-render in
v0.3.0).

## Testing Strategy

- Unit: `validate_prop_continuity` (match/mismatch/missing-ref → info);
  `evaluate_camera_continuity` (motivated vs unmotivated change).
- Unit: verdict aggregation precedence (fail>warn>pass; info neutral).
- Unit: `apply_governance_policy` for `report` and `block` modes (deliverability
  flip on `block`+`fail`; unchanged on `report`).
- Unit: `build_continuity_ledger` counts/pass-rates/offending list.
- Integration: scene render persists `scene["governance"]`; `block` mode flips
  export readiness; legacy project → `not_evaluated`, no errors.
- Checks: `python -m py_compile` on edited backend modules; `node --check` on
  edited frontend modules.

## Rollback Plan

- All additions are additive keys (`props`, `scene["governance"]`, ledger);
  removing the feature means ignoring them.
- Default `report` mode is non-enforcing, so enabling governance cannot block a
  pipeline; `block` is opt-in.
- Setting `CONSISTENCY_VALIDATION_ENABLED=0` disables scoring; governance then
  records `not_evaluated` and changes nothing.

## Design Decisions

- DD-1 Validator stays a stateless scoring engine; orchestrator owns policy and
  state (maintainer constraint; limits blast radius, keeps validator reusable).
- DD-2 Verdict at sibling `scene["governance"]`, not inside `consistency_meta`
  (OQ-1; cleaner backward-compat and separation).
- DD-3 Default policy `report`; `block` opt-in (OQ-2). `regenerate` deferred to
  a later spec to avoid a render feedback loop (NG-7).
- DD-4 Rules-based camera heuristic for v0.3.0; motion embeddings deferred
  (OQ-3).
- DD-5 Reuse existing histogram/structural-hash utilities for prop scoring
  rather than introducing new similarity math (NFR-2).
