# Implementation Plan: director-interpretation-mainline

## Overview

Make the AI director's interpretation a first-class, structured stage between
scene classification and video-provider prompt construction. v0.5.0 scope is
deterministic-first: ship the structures, pipeline placement, persistence, and
the prompt-consumption chain, with the LLM tier deferred. The central
behavioral change is that `build_scene_video_prompts` consumes `visual_content`
as the primary visual source instead of raw dialogue.

Acceptance chain:

```text
script → director_meta → director_plan → shot_plan + visual_content
       → video provider prompt
```

## Implementation Base / Branching Constraint (hard prerequisite)

```text
Implementation branch MUST be based on:
- codex/video-provider-mainline, or
- main after v0.2.0 has merged.
Do NOT implement on plain current main.
```

Rationale: v0.5.0 modifies the `shot_plan` → `canonical_timeline` →
`build_scene_video_prompts` chain, which was refactored by v0.2.0. Basing on
old `main` would produce an incompatible implementation. (The spec branch may be
based on `main`; only the implementation branch carries this constraint.)

## Tasks

### Slice A — Data structures + deterministic planner

- [ ] 1. Define `director_plan` + `visual_content` structures and defaults
  - Add the §director_plan dict shape (`dramatic_intent`, `emotional_target`,
    `narrative_focus`, `rationale`, `source`) and the per-shot `visual_content`
    shape (8 fields) + `shot_size` + `camera_language` + `dramatic_intent`,
    with deterministic default builders.
  - _Requirements: 1.1, 2.1, 2.2, NFR-4_

- [ ] 2. Deterministic `build_director_plan(scene)`
  - In `scripts/director_classifier.py` (or new `scripts/director_interpreter.py`):
    synthesize `director_plan` from `director_meta` + scene text; `source`
    `rules`/`default`. No LLM, no network. Reuse the existing tiering pattern.
  - _Requirements: 1.1, 1.2, 1.3, NFR-2, NFR-3, NFR-5_

- [ ] 3. Deterministic `build_shot_visual_content(scene, shot)`
  - Derive `shot_size` from `subject_focus`, `camera_language` from camera
    movement/speed, and fill all 8 `visual_content` fields from visual prompt +
    subject focus + emotion. Deterministic.
  - _Requirements: 2.1, 2.2, 2.3_

- [ ] 4. Slice A unit tests
  - `build_director_plan`: all four fields from representative `director_meta`;
    sparse input → default source; no-LLM path. Legacy scene (no fields).
  - `build_shot_visual_content`: all 8 fields + shot_size/camera_language per
    subject_focus/camera case; empty shot_plan synthesizes one shot's content.
  - _Requirements: 1.3, 2.3, Property 1, Property 2, Property 6_

### Slice B — Pipeline integration

- [ ] 5. Wire interpretation into the workflow
  - In `scripts/run_workflow.py`, run interpretation after classification and
    before prompt build: `director_meta → director_plan → shot_plan +
    visual_content`. Attach `visual_content` + new shot fields in
    `build_shot_plan` (additive).
  - _Requirements: 4.1, 4.2, 2.4, Property 3_

- [ ] 6. Persist + snapshot the new fields
  - Persist `scene["director_plan"]` and per-shot `visual_content`; normalize/
    default on load in `backend/project_models.py`; expose in the snapshot via
    `backend/project_runtime.py`.
  - _Requirements: 4.1, 4.3, 5.1, 5.2_

- [ ] 7. Slice B backward-compat tests
  - Legacy project (no director_plan/visual_content) loads with synthesized
    defaults, renders, and the snapshot exposes the fields.
  - _Requirements: 5.1, 5.2, AC-5, AC-7, Property 3_

### Slice C — Prompt consumption (the key change)

- [ ] 8. Make `build_scene_video_prompts` consume `visual_content`
  - Build the positive prompt primarily from `visual_content`
    (shot_description + composition + lighting + focus) + `shot_size` +
    `camera_language`; demote dialogue to optional context. Retain the legacy
    fallback when `visual_content` is absent.
  - _Requirements: 3.1, 3.2, 3.3, Property 4, Property 5_

- [ ] 9. Slice C prompt tests
  - Prompt includes visual_content tokens (foreground/background/composition/
    motion/focus) and does not use raw dialogue as the primary visual driver
    when visual_content is present; legacy scene falls back and still builds.
  - _Requirements: 3.1, 3.2, 3.3, AC-3, AC-4_

### Slice D — Docs / checks

- [ ] 10. Docs update
  - Document the interpretation stage, `director_plan`, and `visual_content`
    contracts and the pipeline placement in `docs/`.
  - _Requirements: NFR-4, project doc-update rule_

- [ ] 11. Checkpoint — run required checks
  - `python -m py_compile` on edited modules
    (`scripts/run_workflow.py`, `scripts/director_classifier.py` /
    `director_interpreter.py`, `backend/project_models.py`,
    `backend/project_runtime.py`); targeted pytest for Slices A–C; sample
    workflow when the environment allows
    (`python -m scripts.run_workflow --input inputs\sample_story.txt
    --keyframe-provider local`), else record as environment-pending.
  - _Requirements: AC-8, NFR-6_

## Task Dependency Graph

```json
{
  "waves": [
    ["1"],
    ["2", "3"],
    ["4", "5"],
    ["6", "8"],
    ["7", "9"],
    ["10"],
    ["11"]
  ]
}
```

## Implementation Slices

- Slice A (tasks 1–4): data structures + deterministic planner (no LLM, no
  pipeline wiring). Proves the synthesis in isolation.
- Slice B (tasks 5–7): pipeline integration + persistence + backward compat.
- Slice C (tasks 8–9): the key change — prompt consumes `visual_content`,
  dialogue demoted to context.
- Slice D (tasks 10–11): docs + checks.

## Notes

- Deterministic-first: no LLM and no new provider calls in v0.5.0; the LLM
  interpretation tier is a deferred enhancement that reuses the same
  llm/rules/default tiering.
- The central behavioral change is Slice C (prompt consumption); Slices A–B set
  it up safely.
- All new fields are additive; `director_meta` and the existing shot_plan
  timing/camera shapes are unchanged.
- Do not edit provider adapters/wire formats, governance scoring, or the review
  console; surfacing interpretation in the console is a later follow-up.

## Handoff to Codex

- Base the implementation branch per the Branching Constraint above (NOT plain
  `main`).
- Files to edit: `scripts/run_workflow.py`, `scripts/director_classifier.py`
  (or new `scripts/director_interpreter.py`), `backend/project_models.py`,
  `backend/project_runtime.py`, `docs/`, tests.
- Files NOT to edit: `scripts/video_provider_adapters.py`, `video_providers.py`,
  `backend/consistency_validator.py`, `backend/consistency_governance.py`,
  review-console frontend.
- Validation: `python -m py_compile` + targeted pytest; sample workflow when
  available.
- Acceptance checklist: AC-1 through AC-8 in `requirements.md`.
- Known risks: `build_scene_video_prompts` and `build_shot_plan` in
  `run_workflow.py` are high-traffic and were touched by v0.2.0 — preserve the
  legacy fallback and additive shapes.
