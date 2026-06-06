# Requirements Document

## Introduction

Today the AI director's output is thin and flat. `director_classifier.py`
produces a `director_meta` of enum tags (emotion_tone, sfx_type, scene_intent,
pacing, subject_focus), `shot_plan` (v0.2.0) holds shot timing and camera
fields, and `build_scene_video_prompts` builds the video-provider prompt largely
from the visual prompt, dialogue, camera, and emotion. There is no structured
notion of **what is actually on screen** per shot, and no captured directorial
reasoning ("why shot this way"). The provider prompt leans on raw dialogue and
generic tags rather than a deliberate visual description.

`director-interpretation-mainline` makes the director's interpretation a
first-class, structured stage of the pipeline. It introduces a per-scene
`director_plan` ("why this is shot this way" — dramatic intent, emotional
target, narrative focus, rationale) and a structured per-shot `visual_content`
(what is on screen — shot description, fore/mid/background, composition, motion,
lighting, focus), then requires the video-provider prompt builder to consume
`visual_content` rather than only raw dialogue.

Pipeline placement:

```text
script
  → AI director interpretation
  → director_plan        (why: intent, emotion, narrative focus, rationale)
  → shot_plan            (how: timing, camera, shot size) [extends v0.2.0]
  → video provider prompt (consumes visual_content)
```

`director_plan` owns "why this shot"; `shot_plan` owns "how it is generated".
This is a new feature line; proposed release `v0.5.0`.

## Glossary

- **director_plan**: Per-scene structured directorial reasoning — dramatic
  intent, emotional target, narrative focus, and rationale — that motivates the
  shots. New.
- **visual_content**: Per-shot structured description of what is on screen —
  shot description, foreground/midground/background, composition, motion,
  lighting, focus. New, attached to each shot.
- **shot_plan**: The existing v0.2.0 per-scene shot list (timing, camera,
  intent). Extended here with `shot_size`, `camera_language`, `dramatic_intent`,
  and `visual_content` per shot.
- **director_meta**: The existing flat enum classification from
  `director_classifier.py` (emotion_tone, scene_intent, pacing, subject_focus).
  Retained; `director_plan` is the richer layer above it.
- **camera_language**: Structured camera fields per shot — lens, depth_of_field,
  movement, framing.
- **video-provider prompt**: The text built by `build_scene_video_prompts`
  and sent to the video provider.

## Problem Statement

1. No on-screen description: there is no structured field saying what the frame
   contains per shot; the provider infers it from prose + dialogue.
2. No captured reasoning: directorial intent ("why this framing") is not stored,
   so it cannot drive prompts, review, or regeneration.
3. Prompt relies on dialogue: `build_scene_video_prompts` leans on raw dialogue
   and generic tags rather than a deliberate visual description, weakening
   shot-accurate generation.
4. `director_meta` is flat enums: useful for routing (BGM, pacing) but not
   expressive enough to direct a shot's visual content.
5. Shots lack shot-size / camera-language structure: `shot_plan` carries camera
   movement/speed but not shot size, lens, or depth-of-field as structured
   fields.

## User Value

- A creator gets shots that render what the director intends to be on screen,
  not a loose interpretation of dialogue.
- The director's reasoning is captured and reusable — for the provider prompt,
  the review console, and any future regeneration.
- The pipeline gains a clear separation: `director_plan` (why) vs `shot_plan`
  (how), making each stage inspectable and improvable.
- Downstream specs (review console, future regeneration) can surface and act on
  structured intent rather than opaque prompts.

## Requirements

### FR-1 Per-scene director_plan

**User Story:** As a creator, I want the director's reasoning captured per
scene, so that intent drives generation and review instead of being lost.

1.1 The system SHALL produce a `director_plan` per scene containing at least:
    `dramatic_intent`, `emotional_target`, `narrative_focus`, and `rationale`.
1.2 `director_plan` SHALL build on the existing `director_meta` (reuse its
    emotion/intent/pacing classification) rather than replace it.
1.3 Every scene SHALL have a `director_plan`; when interpretation is
    unavailable, a deterministic fallback `director_plan` SHALL be synthesized
    from existing scene fields (no failure).

### FR-2 Structured per-shot visual_content

**User Story:** As a director, I want a structured description of what is on
screen per shot, so that the generator renders the intended frame.

2.1 Each shot SHALL carry a structured `visual_content` with at least:
    `shot_description`, `foreground`, `midground`, `background`, `composition`,
    `motion`, `lighting`, and `focus`.
2.2 Each shot SHALL carry `shot_size` (e.g. extreme_close_up / close_up /
    medium / wide) and a structured `camera_language` (`lens`,
    `depth_of_field`, `movement`, `framing`) and `dramatic_intent`.
2.3 When per-shot visual fields are not produced by interpretation, the system
    SHALL synthesize a deterministic `visual_content` from the scene's visual
    prompt, subject focus, and camera fields (graceful, non-failing).
2.4 `visual_content` and the new shot fields SHALL be additive to the existing
    `shot_plan` shot shape; existing shot readers SHALL continue to work.

### FR-3 Provider prompt consumes visual_content

**User Story:** As a creator, I want the video prompt driven by the intended
on-screen content, so that generation is shot-accurate.

3.1 `build_scene_video_prompts` SHALL incorporate the shot's `visual_content`
    (and `shot_size` / `camera_language`) into the positive prompt.
3.2 The prompt SHALL NOT be built from raw dialogue as the primary visual
    driver; dialogue MAY remain as context but `visual_content` is the visual
    source of truth.
3.3 When `visual_content` is absent (legacy scene), the builder SHALL fall back
    to current behavior so older projects still render.

### FR-4 Persistence and pipeline placement

**User Story:** As a maintainer, I want the interpretation stage to slot cleanly
into the existing pipeline, so that it is inspectable and reusable.

4.1 `director_plan` SHALL be persisted per scene; per-shot `visual_content` and
    new shot fields SHALL be persisted within the shot plan / temporal spec.
4.2 The interpretation stage SHALL run after scene classification and before
    video-provider prompt construction, consistent with the documented pipeline
    placement.
4.3 The new fields SHALL appear in the project snapshot so downstream consumers
    (review console, exports) can read them.

### FR-5 Backward compatibility

**User Story:** As a maintainer, I want existing projects to keep working, so
that adding interpretation is non-breaking.

5.1 Projects without `director_plan` / `visual_content` SHALL load and render
    unchanged, using synthesized fallbacks.
5.2 The new fields SHALL be additive; no existing field shape (director_meta,
    shot_plan timing/camera) is removed or repurposed.

## Non-Functional Requirements

- NFR-1 Backward compatibility: legacy projects load, render, and export;
  missing interpretation is synthesized deterministically.
- NFR-2 Reuse, not replace: build on `director_classifier`/`director_meta`,
  `shot_plan`, and `build_scene_video_prompts`; do not duplicate classification.
- NFR-3 Bounded cost: interpretation SHALL NOT add video-provider calls; if it
  uses an LLM it MUST have a deterministic non-LLM fallback (mirroring the
  existing rules/default classification path).
- NFR-4 Deterministic, versioned JSON contracts for `director_plan` and
  `visual_content`.
- NFR-5 Observability: interpretation source (llm / rules / default / fallback)
  recorded per scene, like `director_meta.source`.
- NFR-6 Checks: `python -m py_compile` on edited modules and targeted tests for
  synthesis, prompt consumption, and backward compatibility.

## Non-Goals

- NG-1 Replacing the existing enum classifier (`director_meta` stays as the
  routing layer).
- NG-2 New video providers or changes to provider wire formats (owned by other
  specs).
- NG-3 Automatic regeneration based on interpretation (regeneration remains
  deferred per the governance spec).
- NG-4 Cost accounting (owned by the future `provider-cost-controls` spec).
- NG-5 Review-console redesign; surfacing `director_plan`/`visual_content` in
  the console beyond what already reads the snapshot is a follow-up.
- NG-6 Multi-shot choreography/transitions beyond per-shot `visual_content`
  (transitions already exist in the timeline).

## Acceptance Criteria

- AC-1 Every scene has a `director_plan` with `dramatic_intent`,
  `emotional_target`, `narrative_focus`, and `rationale`; a scene with no
  interpretation gets a synthesized plan (no failure).
- AC-2 Every shot has a structured `visual_content` (shot_description,
  foreground, midground, background, composition, motion, lighting, focus) plus
  `shot_size`, `camera_language`, and `dramatic_intent`.
- AC-3 `build_scene_video_prompts` incorporates `visual_content` /
  `shot_size` / `camera_language` into the positive prompt and no longer uses
  raw dialogue as the primary visual driver.
- AC-4 A legacy scene without `visual_content` still builds a prompt via the
  existing fallback and renders.
- AC-5 `director_plan` and `visual_content` are persisted and present in the
  project snapshot.
- AC-6 Interpretation degrades deterministically without an LLM (rules/default
  fallback), adding no provider calls.
- AC-7 Backward compat: a legacy project loads, renders, and exports with
  synthesized interpretation and no errors.
- AC-8 Checks pass: `python -m py_compile` on edited modules and targeted tests
  for synthesis, prompt consumption, and backward compatibility.

## Open Questions

- OQ-1 Should `director_plan` live as a sibling scene key (`scene["director_plan"]`)
  or nested under the existing `director_meta`? (Design to decide; sibling key
  likely cleaner, mirroring how governance chose a sibling key.)
- OQ-2 Should `visual_content` live on each shot inside the shot plan, or as a
  parallel per-scene list keyed by shot_id? (Design to decide; on-shot is
  simplest and matches the example.)
- OQ-3 Is the interpretation produced by extending the existing
  `director_classifier` LLM path, or a separate interpreter module? (Design to
  decide; reuse the classifier's llm/rules/default tiering for consistency and a
  guaranteed deterministic fallback.)
- OQ-4 For v0.5.0, is LLM-based interpretation in scope, or ship the
  deterministic synthesis first and add the LLM tier later? (Design/scope to
  decide; deterministic-first reduces risk and satisfies NFR-3.)
