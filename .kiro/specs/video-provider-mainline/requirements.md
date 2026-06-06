# Requirements Document

## Introduction

This feature makes real video generation the primary scene rendering path for
Comic Drama Workflow, with local 2.5D keyframe motion kept as an explicit,
observable fallback. Today 2.5D behaves as the silent default and real video as
an opportunistic upgrade; provenance (which provider ran, how many attempts,
real video vs fallback) is computed inside `render_clip` and then discarded.
This spec formalizes a `shot_plan` artifact, threads a structured generation
result through the renderer, persists per-scene generation metadata, and
surfaces it in the canonical timeline and review console. It targets release
`v0.2.0: video-provider-mainline`.

## Glossary

- **shot_plan**: A persisted, scene-relative, ordered list of shots (timing,
  camera, intent) that is the input contract for the video provider request
  builder. Mirrors `temporal_spec.shots`.
- **generation_meta**: Per-scene provenance record of the last render
  (provider id/label/backend, is_real_video, attempts, fallback_used, error,
  warnings, timing, timestamp).
- **real video**: Output from a comfyui or remote video provider backend.
- **2.5D fallback**: Output from the local Ken Burns keyframe renderer used when
  a non-local provider is unavailable or fails under a permissive policy.
- **fallback mode**: Policy (`report` | `strict` | `silent`) controlling what
  happens when a non-local provider exhausts retries.
- **canonical_timeline**: The OTIO-inspired project interchange object produced
  by `build_canonical_timeline`.

## Problem Statement

Comic Drama Workflow currently treats keyframe-driven 2.5D motion (Ken Burns
style pans over a single PNG) as the de facto primary scene renderer. Real
video providers (ComfyUI, Sora, Doubao, Seedance, XL aggregator) exist and are
wired into `render_clip`, but the pipeline behaves as if 2.5D is the default
and real video is an opportunistic upgrade:

- When a remote/ComfyUI provider fails, `render_clip` silently falls back to a
  2.5D clip and returns only a file path. Nothing records which provider ran,
  how many attempts happened, or whether the output is real video or a
  fallback.
- `backend/video_generation.py` already models a richer result
  (`VideoGenerationResult` with `provider_id`, `is_real_video`, `attempts`,
  `warnings`), but `render_clip` and the scene renderers do not use it and
  never persist it onto the scene.
- The `canonical_timeline` picture clips carry no provider/generation
  provenance, so review and export tools cannot tell real video from fallback.
- `shot_plan` is named as a pipeline stage in `AGENTS.md`
  (`script -> roles/assets -> shot_plan -> production_bible -> video provider
  -> canonical_timeline -> review/export`) but it is not a first-class,
  persisted artifact. Shot data lives implicitly inside `temporal_spec.shots`
  and `scene_graph`.
- The review console (`frontend/app.js`) and backend endpoints expose provider
  configuration status but not per-scene generation outcomes.

The result: producers cannot trust that a delivered episode was rendered with
real video, cannot see why a scene fell back, and cannot drive the pipeline
from a stable shot plan.

## 2. User Value

- A producer can configure a video provider and have it be the real primary
  renderer, with 2.5D as an explicit, visible fallback rather than a silent
  substitute.
- A reviewer can open the review console and immediately see, per scene,
  whether the clip is real video or a 2.5D fallback, which provider produced
  it, how many attempts it took, and the failure reason if it fell back.
- A downstream tool (export, future editor) can read `shot_plan` and
  `canonical_timeline` to know the intended shot structure and the actual
  render provenance without re-deriving it.
- The team gets a stable contract (`shot_plan`, provider metadata, fallback
  rules) that Codex can implement against without reinterpreting intent.

## Requirements

### FR-1 shot_plan as a first-class artifact

**User Story:** As a producer, I want a stable shot plan per scene, so that the
video provider request builder and downstream tools work from one explicit
contract.

1.1 The system SHALL produce a persisted `shot_plan` object per scene that
    enumerates ordered shots with timing, camera, and intent fields.
1.2 The `shot_plan` SHALL be derivable from existing `temporal_spec.shots` /
    `scene_graph` data so existing projects can be upgraded without re-running
    the LLM planner.
1.3 The `shot_plan` SHALL be the input contract consumed by the video provider
    request builder (prompt, duration, camera, continuity).
1.4 When `temporal_spec.shots` is absent, the system SHALL synthesize a
    single-shot `shot_plan` covering the full scene duration.

### FR-2 Real video as the primary path
2.1 When a non-local video provider is configured (auto-resolved or explicit),
    the system SHALL attempt real video generation as the primary renderer for
    each scene.
2.2 The system SHALL retry remote provider failures using the existing
    retry/backoff configuration (`VIDEO_MAX_RETRIES`,
    `VIDEO_RETRY_DELAY_SECONDS`) before considering fallback.
2.3 The system SHALL only use the local 2.5D renderer when (a) the configured
    provider is `local`, or (b) a non-local provider has exhausted retries and
    fallback is permitted by policy.

### FR-3 Provider/generation metadata (provenance)
3.1 For every scene render, the system SHALL record generation metadata:
    `provider_id`, `provider_label`, `backend`, `is_real_video`, `attempts`,
    `fallback_used`, `error` (if any), `warnings`, `duration_seconds`, and a
    timestamp.
3.2 The metadata SHALL be persisted on the scene (alongside `assets`) and
    survive project reload.
3.3 The metadata SHALL be propagated into `canonical_timeline` picture-clip
    metadata.
3.4 Generating or re-rendering a scene SHALL overwrite that scene's prior
    generation metadata (latest-wins), preserving the per-scene history log
    that already exists.

### FR-4 Fallback policy and visibility
4.1 The system SHALL support three fallback modes via `VIDEO_FALLBACK_MODE`:
    `report` (fall back but flag the scene), `strict` (fail the scene, no
    fallback), and `silent` (legacy quiet fallback).
4.2 `VIDEO_STRICT=true` SHALL force `strict` mode regardless of
    `VIDEO_FALLBACK_MODE`.
4.3 In `report` mode, a fallback scene SHALL be marked with a warning and its
    metadata `fallback_used=true`, and the scene SHALL still be renderable into
    the timeline.
4.4 In `strict` mode, a provider failure SHALL surface as a scene render
    failure (recorded in scene history) rather than a silent success.

### FR-5 Review console visibility
5.1 The backend SHALL expose per-scene generation metadata through the existing
    project/scene API responses consumed by the review console.
5.2 The review console SHALL display, per scene: real-video vs fallback badge,
    provider label, attempts, and failure reason when present.
5.3 The review console SHALL surface the active video provider and its
    configuration/readiness status at the project level (reusing the existing
    `/api/video-providers/status` data).

### FR-6 Canonical timeline references
6.1 `canonical_timeline` picture clips SHALL reference the real video media
    when present, falling back to image reference only when no video exists
    (preserving current `_scene_media_reference` precedence).
6.2 Each picture clip SHALL carry the FR-3 generation metadata under its
    `metadata` block.
6.3 The timeline SHALL include a project-level summary count of real-video
    scenes vs fallback scenes.

## 4. Non-Functional Requirements

- NFR-1 Backward compatibility: existing projects without `shot_plan` or
  generation metadata SHALL load and render without error; missing fields are
  synthesized or defaulted.
- NFR-2 No new hard runtime dependencies; reuse existing ffmpeg, provider
  adapters, and dataclasses.
- NFR-3 Determinism of contracts: `shot_plan` and timeline schemas SHALL be
  stable, versioned JSON suitable for diffing and export.
- NFR-4 Performance: metadata capture SHALL not add provider calls; it records
  what already happens.
- NFR-5 Observability: provider attempts, failures, and fallbacks SHALL be
  logged with scene identifiers.

## 5. Non-Goals

- NG-1 Adding new video providers or changing provider adapter wire formats
  (covered by the separate `alibaba-video-provider` spec).
- NG-2 Cost accounting / billing systems (future spec).
- NG-3 Global consistency governance across characters/lighting (separate
  `global-consistency-governance` spec).
- NG-4 A full review-console redesign (separate `director-review-console`
  spec); this spec only adds provenance display.
- NG-5 Replacing or removing the 2.5D renderer; it remains the fallback.
- NG-6 Long-form / multi-episode scaling.

## 6. Acceptance Criteria

- AC-1 With a remote provider configured and reachable, running a scene render
  produces a real video clip and scene metadata with `is_real_video=true`,
  `fallback_used=false`, and the correct `provider_id`.
- AC-2 With a remote provider configured but failing, in `report` mode the
  scene still renders (2.5D) and metadata shows `is_real_video=false`,
  `fallback_used=true`, `attempts>=VIDEO_MAX_RETRIES+1`, and a non-empty
  `error`/`warnings`.
- AC-3 With the same failing provider in `strict` mode (or `VIDEO_STRICT=true`),
  the scene render fails and a `failed` entry is recorded in scene history; no
  silent 2.5D substitution occurs.
- AC-4 `shot_plan` is present and persisted for every scene after a render, and
  a legacy project (no `temporal_spec.shots`) gets a synthesized single-shot
  plan.
- AC-5 `canonical_timeline` picture clips reference video media when available
  and carry generation metadata; the timeline summary reports real-vs-fallback
  counts.
- AC-6 The review console shows a real-video/fallback badge, provider label,
  attempts, and failure reason per scene.
- AC-7 `python -m py_compile` passes for all edited backend/script modules and
  `node --check frontend\app.js` passes; the sample workflow
  (`python scripts\run_workflow.py --input inputs\sample_story.txt`) completes
  when runtime dependencies are available.

## 7. Open Questions

- OQ-1 Should `shot_plan` be a new top-level scene key, or nested under
  `temporal_spec`? (Design proposes a dedicated `scene["shot_plan"]` mirrored
  from `temporal_spec.shots` to avoid breaking existing readers.)
- OQ-2 Default `VIDEO_FALLBACK_MODE` for the mainline release: keep `report` as
  default (recommended) vs `strict`.
