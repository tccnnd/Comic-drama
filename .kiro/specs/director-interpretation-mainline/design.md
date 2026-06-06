# Design: director-interpretation-mainline

## Overview

This design makes the AI director's interpretation a first-class, structured
stage between scene classification and video-provider prompt construction. It
adds a per-scene `director_plan` (the "why" — dramatic intent, emotional target,
narrative focus, rationale) and a structured per-shot `visual_content` (the
"what is on screen" — shot description, fore/mid/background, composition,
motion, lighting, focus) plus `shot_size`, `camera_language`, and
`dramatic_intent` on each shot. The video-provider prompt builder then consumes
`visual_content` as the primary visual driver instead of raw dialogue.

The v0.5.0 scope is **deterministic-first**: the structures, pipeline placement,
persistence, and the prompt-consumption chain are the deliverable. An LLM
interpretation tier is a deferred enhancement that plugs into the same tiering
the existing classifier already uses (llm → rules → default).

Resolved open questions:
- OQ-1 → `director_plan` is a sibling scene key (`scene["director_plan"]`), not
  nested in `director_meta`.
- OQ-2 → `visual_content` lives on each shot in the shot plan.
- OQ-3 → reuse the existing classifier's `llm/rules/default` tiering.
- OQ-4 → deterministic synthesis ships in v0.5.0; LLM tier deferred.

Core acceptance chain:

```text
script → director_meta → director_plan → shot_plan + visual_content
       → video provider prompt
```

The goal is not a smarter AI director yet; it is that **every video-generation
prompt is driven by director interpretation and on-screen content**, with a
guaranteed deterministic fallback.

## Architecture

```text
scene (classified: director_meta = emotion/intent/pacing/subject_focus)
        │
        ▼
 director interpretation stage  (NEW; after classify, before prompt build)
   ├─ build_director_plan(scene)        → scene["director_plan"]      (why)
   └─ build_shot_visual_content(scene,  → shot["visual_content"] +    (what)
        shot)                              shot_size/camera_language/
                                           dramatic_intent
        │  tiering: llm (deferred) → rules → default  (deterministic floor)
        ▼
 shot_plan (v0.2.0) extended with per-shot visual fields
        │
        ▼
 build_scene_video_prompts  → consumes visual_content + shot_size +
                              camera_language (dialogue = context only)
        │
        ▼
 video provider prompt
```

The interpretation stage reuses the classifier's tiering pattern: try LLM (a
deferred enhancement, off by default in v0.5.0), fall back to rules, then to a
deterministic default — guaranteeing a usable `director_plan` and
`visual_content` with no provider/LLM dependency.

## Components and Interfaces

| Component | Location | Responsibility |
| --- | --- | --- |
| `build_director_plan(scene)` | `scripts/director_classifier.py` (or a sibling `director_interpreter.py`) | Produce the §director_plan dict from `director_meta` + scene fields; deterministic. |
| `build_shot_visual_content(scene, shot)` | same module | Produce per-shot `visual_content` + `shot_size` + `camera_language` + `dramatic_intent`; deterministic synthesis from visual prompt, subject_focus, camera fields. |
| interpretation tiering | same module | `llm` (deferred, optional) → `rules` → `default`, mirroring existing `apply_*_classification`; records `source`. |
| `shot_plan` builder | `scripts/run_workflow.py` (`build_shot_plan`) | Attach `visual_content` and new shot fields to each shot (additive). |
| `build_scene_video_prompts` | `scripts/run_workflow.py` | Consume `visual_content` / `shot_size` / `camera_language` as the primary visual source; dialogue becomes context only; legacy fallback retained. |
| snapshot/persistence | `backend/project_models.py`, `backend/project_runtime.py` | Default/normalize `director_plan` + shot `visual_content` on load; expose in snapshot. |

## Data Models

The two new contracts (`director_plan`, `visual_content`) are defined in Data
Contracts. Both are additive: existing `director_meta` and `shot_plan`
timing/camera shapes are unchanged.

## Data Contracts

### scene["director_plan"] (new, per-scene, sibling key)

```json
{
  "version": 1,
  "dramatic_intent": "制造爆炸前的压迫感和危险预告",
  "emotional_target": "紧张、窒息、危险逼近",
  "narrative_focus": "雷管炸弹是当前场景的核心危险源",
  "rationale": "用极致特写和固定机位让观众无法逃离危险物，强化倒计时前的紧张感",
  "source": "rules"
}
```

`source` ∈ `llm | rules | default | fallback` (mirrors `director_meta.source`).

### shot["visual_content"] + new shot fields (additive to shot_plan shots)

```json
{
  "shot_id": "scene_01_shot_01",
  "shot_order": 1,
  "shot_size": "extreme_close_up",
  "dramatic_intent": "制造爆炸前的压迫感和危险预告",
  "camera_language": {
    "lens": "telephoto",
    "depth_of_field": "shallow",
    "movement": "locked_off",
    "framing": "center_composition"
  },
  "visual_content": {
    "shot_description": "极致特写，浅景深，长焦压缩空间；雷管炸弹位于画面中心，背景虚化",
    "foreground": "雷管炸弹的金属、导线、引信细节",
    "midground": "",
    "background": "高度虚化的环境，弱化信息",
    "composition": "中心构图，危险物占据视觉焦点",
    "motion": "固定机位，画面静止但压迫感强",
    "lighting": "低调冷光，强调金属质感",
    "focus": "雷管炸弹"
  }
}
```

`shot_size` ∈ a small controlled set (e.g. `extreme_close_up | close_up |
medium | wide | extreme_wide`); unknown → synthesized from `subject_focus`.

## Behavior: deterministic synthesis (v0.5.0 floor)

- `build_director_plan`: maps `director_meta` (emotion_tone, scene_intent,
  subject_focus, pacing) + title/visual prompt into the four `director_plan`
  fields via deterministic rules; `source="rules"` (or `default` when fields are
  sparse). No LLM required.
- `build_shot_visual_content`: derives `shot_size` from `subject_focus`
  (environment→wide, single_character→close_up, group→wide, etc.),
  `camera_language` from existing camera movement/speed, and fills
  `visual_content` from the scene visual prompt + subject focus + emotion.
- LLM tier (deferred): when enabled, replaces the rules output and sets
  `source="llm"`, then falls through to rules/default on any error — same
  pattern as `apply_llm_classification`.

## Provider prompt consumption (FR-3, the key acceptance)

- `build_scene_video_prompts` builds the positive prompt primarily from the
  shot's `visual_content` (shot_description + composition + lighting + focus) and
  `shot_size`/`camera_language`, layered with style/quality tags.
- Dialogue is demoted to optional context (e.g. for lip/voice alignment), not
  the visual source of truth.
- Legacy scenes without `visual_content` use the current builder path unchanged
  (FR-3.3 / AC-4).

## Failure and Fallback Behavior

- No interpretation available → synthesized `director_plan` (`source` rules or
  default) and synthesized `visual_content`; never fails a render (FR-1.3,
  FR-2.3).
- LLM tier error (when enabled later) → fall through to rules/default.
- Legacy scene without the new fields → prompt builder falls back to current
  behavior (FR-3.3); load normalization defaults the new keys.
- Interpretation adds no video-provider calls (NFR-3); deterministic path has no
  network dependency.

## Security and Credential Considerations

- The deterministic v0.5.0 path makes no network calls and needs no
  credentials.
- A future LLM tier would reuse the existing LLM client/credentials of the
  classifier; no new secret storage. `director_plan`/`visual_content` store only
  descriptive text — no credentials.

## Correctness Properties

Property 1: Director plan completeness — every scene has a `director_plan` with
`dramatic_intent`, `emotional_target`, `narrative_focus`, and `rationale`;
absent interpretation yields a synthesized plan, never a failure.
**Validates: Requirements 1.1, 1.3**

Property 2: Visual content completeness — every shot has a structured
`visual_content` (all eight fields) plus `shot_size`, `camera_language`, and
`dramatic_intent`, synthesized deterministically when not provided.
**Validates: Requirements 2.1, 2.2, 2.3**

Property 3: Additivity — new fields are additive; `director_meta` and the
existing `shot_plan` timing/camera shapes are unchanged, and existing shot
readers keep working.
**Validates: Requirements 2.4, 5.2**

Property 4: Prompt consumption — `build_scene_video_prompts` incorporates
`visual_content`/`shot_size`/`camera_language` and does not use raw dialogue as
the primary visual driver when `visual_content` is present.
**Validates: Requirements 3.1, 3.2**

Property 5: Legacy prompt fallback — a scene without `visual_content` still
produces a prompt via the existing path and renders.
**Validates: Requirements 3.3, 5.1**

Property 6: Deterministic floor — interpretation produces usable output with no
LLM and no provider calls; `source` records the tier used.
**Validates: Requirements 1.2, 1.3**

## Error Handling

- Synthesis helpers are pure over scene/shot fields; missing/malformed inputs
  default rather than throw.
- Persistence reuses existing scene save/normalization paths; new keys default
  on load (`director_plan` synthesized, `visual_content` synthesized).
- The prompt builder guards on presence of `visual_content` and falls back to
  the current behavior otherwise.

## Affected Files and Module Boundaries

| File | Change | Risk |
| --- | --- | --- |
| `scripts/director_classifier.py` (or new `scripts/director_interpreter.py`) | Add `build_director_plan` + `build_shot_visual_content` + tiering. | Medium |
| `scripts/run_workflow.py` | Run interpretation after classify; attach visual fields in `build_shot_plan`; make `build_scene_video_prompts` consume `visual_content`. | High |
| `backend/project_models.py` | Normalize/default `director_plan` + shot `visual_content` on load. | Medium |
| `backend/project_runtime.py` | Ensure new fields appear in snapshot. | Low |
| `docs/` | Document the interpretation stage + contracts. | Low |
| tests | Synthesis, prompt consumption, backward compat. | Low |

Out of scope (do not edit): video provider adapters / wire formats, governance
scoring, the review-console UI (surfacing is a follow-up), and the enum
classifier's existing outputs (extended around, not changed).

## Testing Strategy

- Unit: `build_director_plan` produces all four fields from representative
  `director_meta`; sparse input → default source.
- Unit: `build_shot_visual_content` produces all eight `visual_content` fields +
  shot_size/camera_language for each `subject_focus`/camera case.
- Unit: `build_scene_video_prompts` includes visual_content tokens and does not
  treat dialogue as the primary visual driver when visual_content present;
  legacy scene falls back.
- Backward-compat: load a legacy project (no director_plan/visual_content) →
  synthesized defaults, renders, snapshot exposes fields.
- Checks: `python -m py_compile` on edited modules; targeted pytest.

## Rollback Plan

- All additions are additive keys (`director_plan`, shot `visual_content` +
  fields); removing the feature means ignoring them.
- The prompt builder's legacy fallback means reverting interpretation restores
  prior prompt behavior with no data migration.
- LLM tier is deferred/optional, so v0.5.0 carries no network/credential
  dependency to roll back.

## Design Decisions

- DD-1 `director_plan` as a sibling scene key, separate from the flat
  `director_meta` (OQ-1).
- DD-2 `visual_content` on each shot in the shot plan (OQ-2).
- DD-3 Reuse the classifier's `llm/rules/default` tiering with a deterministic
  floor (OQ-3).
- DD-4 Deterministic-first for v0.5.0; LLM interpretation tier deferred as an
  enhancement (OQ-4) — prioritize wiring the structure + prompt-consumption
  chain over director "intelligence".
- DD-5 The provider prompt's visual source of truth becomes `visual_content`;
  dialogue is demoted to context (FR-3) — the central behavioral change.
