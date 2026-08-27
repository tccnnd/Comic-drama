# Requirements Document

## Introduction

Comic Drama Workflow currently has scene-level real-video generation and
scene-to-scene final concatenation. It can also concatenate local/fallback
segments inside a scene, but real remote providers are still called once per
scene. That means a multi-shot scene is described in `shot_plan`, yet the
provider receives one scene-level request and the output provenance is one
scene-level `generation_meta` record.

`shot-level-video-rendering` makes each `shot_plan.shots[]` item a renderable
unit. The pipeline should be able to call a real video provider per shot,
assemble those shot clips into a scene clip, then continue through the existing
canonical timeline and final export path.

This is the next planned feature after `video-provider-mainline`. Because Kiro
is unavailable, this document is a Codex-authored Kiro-style draft and should
be accepted before implementation.

## Glossary

- **scene-level render**: Current behavior: one provider request produces one
  clip for the whole scene.
- **shot-level render**: New behavior: each shot in `shot_plan.shots[]` can be
  rendered as its own provider clip.
- **shot output**: Per-shot render artifact and provenance: shot id, provider,
  path, duration, status, attempts, fallback/error data.
- **scene assembly**: Concatenating shot outputs into the scene video asset
  consumed by the existing final timeline.
- **render granularity**: The requested render mode: `scene` or `shot`.
- **planning model**: LLM used for interpretation, spec reasoning, or prompt
  preparation. This is separate from the video-provider model.

## Problem Statement

1. `shot_plan` is first-class, but real providers do not consume it as
   independently renderable units.
2. Per-scene provider calls blur shot boundaries, making camera changes,
   reaction shots, and insert shots unreliable.
3. A failed real provider request currently affects the whole scene. There is
   no way to retry or fall back one shot while preserving the rest.
4. `generation_meta` cannot describe mixed outcomes such as "shot 1 real,
   shot 2 fallback, shot 3 retried twice".
5. Review and export tools cannot inspect or act on shot-level render status.
6. Shot-level live runs can multiply provider calls, so cost/quota controls are
   required before this becomes a default production path.

## User Value

- Creators can generate scenes with explicit cuts, reaction shots, close-ups,
  inserts, and camera changes that match the director plan.
- A failed shot can be retried or locally substituted without throwing away
  successful shots.
- Producers can review which shots are real video and which are fallback.
- The project gains a bridge from deterministic shot planning to real video
  assembly without replacing the existing scene/final export spine.

## Requirements

### FR-1 Render granularity control

1.1 The system SHALL support `scene` and `shot` render granularity.
1.2 The default SHALL remain `scene` until shot-level cost controls and review
    workflows are accepted.
1.3 Granularity SHALL be configurable through
    `VIDEO_RENDER_GRANULARITY=scene|shot`, with CLI/API/project settings allowed
    to override the environment default. This must not change provider adapter
    wire formats.
1.4 When a scene has no usable multi-shot `shot_plan`, `shot` mode SHALL
    degrade to a single full-scene render or an explicit fallback path.

### FR-2 Per-shot provider rendering

2.1 In `shot` mode, the renderer SHALL iterate over ordered
    `shot_plan.shots[]` and build one provider request per shot.
2.2 Each request SHALL use the shot's timing, camera fields, intent, and
    `visual_content` when available.
2.3 Each shot request SHALL preserve scene-level continuity context such as
    characters, location, production bible constraints, and previous-shot
    continuity hints.
2.4 Provider/model selection SHALL be resolved per shot from project defaults,
    scene overrides, then shot overrides, while keeping secrets outside
    persisted artifacts.
2.5 Planning-model selection SHALL be explicit and separate from video-provider
    model selection. Recommended routing while Kiro is unavailable:
    `deepseek v4pro` for engineering/spec tasks, `kimi k2.7` for long-context
    script and shot reasoning, `minimax m3` for creative variation, and
    `glm-5.2` as a general fallback.

### FR-3 Scene assembly

3.1 The system SHALL assemble shot outputs into the scene video asset consumed
    by the existing canonical timeline.
3.2 Assembly SHALL preserve shot order and target durations within documented
    tolerance.
3.3 The initial implementation MAY use hard cuts only; transition effects can
    be added after duration and provenance are stable.
3.4 Existing dialogue, music, subtitle, and final scene-to-scene concatenation
    behavior SHALL remain compatible.

### FR-4 Shot-level provenance

4.1 The scene's `generation_meta` SHALL record `render_granularity="shot"` when
    shot-level rendering is used.
4.2 The scene's `generation_meta` SHALL include aggregate counts:
    `real_video_shot_count`, `fallback_shot_count`, `failed_shot_count`, and
    `total_provider_attempts`.
4.3 The scene's `generation_meta` SHALL include a `shot_outputs` array with
    per-shot provider id, backend, model label when safe, status, attempts,
    duration, path, fallback flag, warnings, and sanitized error text.
4.4 `canonical_timeline` SHALL expose shot-level provenance without breaking
    existing readers of scene-level `metadata.generation`.

### FR-5 Fallback policy at shot level

5.1 Existing fallback modes (`report`, `strict`, `silent`) SHALL apply at the
    shot level.
5.2 In `report` mode, a failed shot MAY fall back to local 2.5D while other
    shots keep their real-video outputs.
5.3 In `strict` mode, any failed required shot SHALL fail the scene render and
    record failed history; no silent scene clip may be assembled.
5.4 In `silent` mode, fallback metadata SHALL still be recorded, but visible
    warnings may be suppressed for compatibility.

### FR-6 Resume and targeted regeneration

6.1 The system SHALL be able to resume a partially completed shot-level scene
    render without resubmitting unchanged successful shots.
6.2 The system SHALL support targeted rerender of one shot in a scene.
6.3 A shot cache key SHALL account for prompt inputs, provider id, model/config,
    source image/reference inputs, duration, and relevant continuity context.
6.4 Reassembled scene clips SHALL update scene-level `generation_meta` and
    history using latest-wins semantics.

### FR-7 Cost and quota controls

7.1 Shot-level live provider runs SHALL support a dry-run estimate before
    submission.
7.2 The system SHALL support max provider calls and max generated seconds per
    workflow run through `VIDEO_SHOT_MAX_CALLS` and
    `VIDEO_SHOT_MAX_SECONDS`.
7.3 The system SHOULD support provider/model cost estimates when pricing data
    is configured.
7.4 Live provider tests SHALL remain opt-in and must not run in normal CI.
7.5 `VIDEO_SHOT_DRY_RUN=1` SHALL plan and validate a shot-level run without
    submitting provider jobs.
7.6 `VIDEO_SHOT_REUSE_CACHE=1` SHALL allow valid existing shot outputs to be
    reused during resume or targeted rerender flows.

### FR-8 Review Console visibility

8.1 The Review Console SHALL show shot-level render status when a scene was
    rendered in `shot` mode.
8.2 Reviewers SHALL be able to distinguish real, fallback, failed, and skipped
    shots.
8.3 The UI SHOULD expose shot-level notes and targeted shot rerender commands
    after the backend contract is stable.

## Non-Functional Requirements

- NFR-1 Backward compatibility: existing scene-level projects load, render, and
  export unchanged.
- NFR-2 Determinism: shot ordering, cache keys, and assembled clip manifests
  must be stable JSON suitable for diffing.
- NFR-3 Observability: every shot provider attempt is recorded without leaking
  API keys, signed URLs, or query tokens.
- NFR-4 Cost safety: shot-level live rendering cannot become the default until
  quota controls are in place.
- NFR-5 No new hard provider dependency: the feature reuses existing provider
  adapters and mock providers first.
- NFR-6 Testability: core behavior is covered with local/mock providers before
  any live provider validation.

## Non-Goals

- NG-1 Adding new video providers or changing provider adapter wire formats.
- NG-2 Replacing the existing scene-level render path.
- NG-3 Full nonlinear editor features or manual timeline editing.
- NG-4 Automatic visual consistency scoring or regeneration.
- NG-5 Multi-episode scheduling.
- NG-6 Guaranteeing provider support for seamless temporal continuity across
  independently rendered shots.

## Acceptance Criteria

- AC-1 With `shot` granularity and a mock remote provider, a two-shot scene
  produces two real shot clips, assembles one scene clip, and records
  `render_granularity="shot"`.
- AC-2 A mixed outcome in `report` mode assembles a scene from real and local
  fallback shot outputs and records accurate per-shot and aggregate metadata.
- AC-3 In `strict` mode, one failed required shot fails the scene render, writes
  failed history, and does not publish a silent assembled scene clip.
- AC-4 A targeted shot rerender reuses unchanged successful shots and updates
  only the changed shot output plus the reassembled scene clip.
- AC-5 `canonical_timeline` remains readable by existing consumers and exposes
  shot-level provenance for new consumers.
- AC-6 The Review Console can display shot-level status for a `shot`-rendered
  scene and still handles legacy scene-level projects.
- AC-7 Dry-run quota controls can predict provider call count/generated seconds
  and block a run that exceeds configured limits before the first live submit.
- AC-8 Required checks pass: Python compile checks for edited backend/script
  modules, targeted pytest coverage, frontend syntax/helper tests for UI
  changes, and no live provider calls in CI.

## Open Questions

- OQ-1 Resolved: render granularity is carried by
  `VIDEO_RENDER_GRANULARITY=scene|shot` as the environment default. CLI, API,
  and project settings may override it in that order when implemented. The
  default remains `scene`.
- OQ-2 Should `shot_outputs` live directly under `generation_meta`, under a
  versioned `generation_meta.details`, or as a separate scene sidecar?
- OQ-3 What duration tolerance is acceptable when provider outputs cannot match
  exact shot timing?
- OQ-4 Should a failed optional insert shot be droppable, or must every planned
  shot be represented in the assembled scene?
- OQ-5 Which Review Console controls are in the first implementation: display
  only, targeted rerender, or shot acceptance notes?
