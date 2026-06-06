# Design: video-provider-mainline

## Overview

This design makes real video generation the primary scene rendering path while
keeping local 2.5D as an explicit, observable fallback. It does so without
rewriting the renderer: it formalizes a `shot_plan` artifact, threads a
structured generation result through `render_clip`, persists per-scene
generation metadata, and surfaces that metadata in the canonical timeline and
review console.

The core insight from the current code: `backend/video_generation.py` already
defines `VideoGenerationResult` (provider_id, is_real_video, attempts,
warnings) and the retry/fallback policy knobs, but `scripts/run_workflow.py`'s
`render_clip` does its own inline retry/fallback and returns only a `Path`. The
provenance is computed and then thrown away. This design captures and persists
it.

## Components and Interfaces

| Component | Location | Responsibility |
| --- | --- | --- |
| `build_shot_plan(scene)` | `scripts/run_workflow.py` | Derive/synthesize the §4.1 `shot_plan` from `temporal_spec.shots`. Shared with timeline derivation. |
| `render_clip` (+ meta wrapper) | `scripts/run_workflow.py` | Dispatch comfyui/remote/local, retry, and return a `VideoGenerationResult`. |
| `VideoGenerationResult` | `backend/video_generation.py` | Shared provenance type (provider, is_real_video, attempts, warnings). |
| `generation_meta_from_result(...)` | `backend/video_generation.py` | Map a result + requested provider + fallback mode → §4.2 dict (sanitized). |
| Scene renderers | `backend/scene_renderer.py` | Capture result, persist `scene["generation_meta"]` and `scene["shot_plan"]`. |
| Scene loader | `backend/project_models.py` | Normalize/default new fields for backward compatibility. |
| `build_canonical_timeline` | `scripts/run_workflow.py` | Attach `generation` metadata to clips; add real-vs-fallback summary counts. |
| Project API | `backend/app.py`, `backend/project_runtime.py` | Include new fields in snapshot/API responses. |
| Review console | `frontend/app.js` | Display per-scene provenance badge and project provider status. |

## Architecture

```text
shot_plan (per scene, persisted)
        │
        ▼
render_clip(scene, ..., video_provider)  ──► VideoGenerationResult
        │  (provider dispatch: comfyui / remote / local)          │
        │  retry + fallback policy                                │
        ▼                                                         ▼
clip.mp4 (real video OR 2.5D fallback)            scene["generation_meta"] (persisted)
        │                                                         │
        ▼                                                         ▼
canonical_timeline picture clip  ◄──── metadata (provider, is_real_video, fallback)
        │
        ▼
review console badges + project provider status
```

## Data Models

The two new persisted contracts (`shot_plan`, `generation_meta`) and the
canonical timeline additions are defined in the Data Contracts section below.

## Data Contracts

### 4.1 shot_plan (new, per-scene)

Stored at `scene["shot_plan"]`. Derived from `temporal_spec.shots` (the
existing producer) or synthesized when absent. Scene-relative timing.

```json
{
  "version": 1,
  "scene_id": "scene_001",
  "scene_order": 1,
  "duration_seconds": 4.2,
  "shot_count": 2,
  "source": "temporal_spec",        // "temporal_spec" | "synthesized"
  "shots": [
    {
      "shot_id": "scene_001_shot_01",
      "shot_order": 1,
      "label": "ESTABLISH",
      "beat_type": "establish",
      "start_seconds": 0.0,
      "duration_seconds": 2.1,
      "end_seconds": 2.1,
      "camera_movement": "slow_push",
      "camera_speed": 1.0,
      "zoom": 1.0,
      "center_x": 0.5,
      "center_y": 0.5,
      "speaker": "",
      "dialogue": "",
      "emotion": "tension",
      "scene_intent": "",
      "subject_focus": ""
    }
  ]
}
```

Notes:
- This is intentionally the same per-shot shape already built inside
  `build_canonical_timeline`'s `shot_timeline`. We extract that derivation into
  a shared helper `build_shot_plan(scene)` so the timeline and the persisted
  `shot_plan` stay identical.
- `shot_plan` is additive. Existing readers of `temporal_spec.shots` keep
  working; `temporal_spec` remains the upstream source.

### 4.2 generation_meta (new, per-scene)

Stored at `scene["generation_meta"]`. Latest-wins per scene. Persisted by the
scene save path so it survives reload.

```json
{
  "version": 1,
  "provider_id": "doubao",
  "provider_label": "Doubao",
  "backend": "remote",              // local | comfyui | remote
  "requested_provider": "auto",
  "is_real_video": true,
  "fallback_used": false,
  "attempts": 1,
  "duration_seconds": 4.2,
  "error": "",
  "warnings": [],
  "fallback_mode": "report",        // report | strict | silent
  "generated_at": "2026-06-06T12:00:00Z"
}
```

### 4.3 canonical_timeline additions

In `build_canonical_timeline`, each picture clip's `metadata` gains a
`generation` block (the FR-3 fields) and a `shot_plan_source`. A new
project-level `summary` field is added:

```json
"summary": {
  "scene_count": 6,
  "shot_count": 14,
  "transition_count": 5,
  "real_video_scene_count": 5,
  "fallback_scene_count": 1
}
```

Media reference precedence is unchanged: video first, image fallback
(`_scene_media_reference`).

## Affected Files and Module Boundaries

Per the file ownership matrix in `docs/collaboration_baseline.md`, all of these
are Codex-owned (Kiro spec only). This design defines the contract; Codex
implements.

| File | Change | Risk |
| --- | --- | --- |
| `scripts/run_workflow.py` | Add `build_shot_plan(scene)`; make `render_clip` return/emit a `VideoGenerationResult`-compatible record; add `generation` + `summary` to `build_canonical_timeline`. | High |
| `backend/video_generation.py` | Make `VideoGenerationResult` the shared result type; add `generation_meta` serialization helper; align `render_clip` fallback policy with this module's modes. | High |
| `backend/scene_renderer.py` | Capture the generation result from `render_clip` and persist `scene["generation_meta"]` + `scene["shot_plan"]` via the scene save path. | High |
| `backend/project_models.py` | Default/normalize `shot_plan` and `generation_meta` on scene load (backward-compat). | Medium |
| `backend/project_runtime.py` | Include `shot_plan` / `generation_meta` in scene snapshot/timeline assembly. | High |
| `backend/app.py` | Ensure scene/project API responses include `generation_meta`. | Medium |
| `frontend/app.js` | Render per-scene provenance badge + provider label/attempts/error; project-level provider status. | High (Cursor-owned UI, Codex integration) |
| `docs/canonical_timeline.md` | Document the new `generation` metadata and `summary` counts. | Low |

### Files Codex SHOULD NOT edit for this spec
- `scripts/video_provider_adapters.py` (provider wire formats — owned by the
  `alibaba-video-provider` spec).
- `backend/consistency_validator.py` (consistency governance — separate spec).
- Provider registry semantics in `video_providers.py` beyond reading specs.

## Behavior: render path

`render_clip` keeps its current dispatch (comfyui / remote / local) and inline
retry, but is refactored to construct a `VideoGenerationResult`:

- comfyui success → `is_real_video=true, backend=comfyui, attempts=n`.
- remote success → `is_real_video=true, backend=remote, attempts=n`.
- local provider → `is_real_video=false, backend=local, fallback_used=false`
  (local is a deliberate choice, not a fallback).
- non-local exhausted retries:
  - `strict` / `VIDEO_STRICT` → raise (scene render fails, history `failed`).
  - `report` → render 2.5D, `is_real_video=false, fallback_used=true`,
    populate `error` + `warnings`.
  - `silent` → render 2.5D, `is_real_video=false, fallback_used=true`, no
    warning surfaced (legacy).

The single source of truth for fallback mode is reused from
`backend/video_generation.py` (`VIDEO_FALLBACK_MODE`, `VIDEO_STRICT`) so
`render_clip` and `generate_scene_video_with_retry` agree.

## Failure and Fallback Behavior

- Transient remote errors (429/quota/timeout) retry with existing backoff.
- After retries: policy decides raise vs 2.5D fallback (see above).
- Fallback scenes are first-class renderable outputs in `report` mode; they are
  flagged, not hidden.
- A scene that fails in `strict` mode records a `failed` history entry via the
  existing `_append_scene_history` path; the project remains loadable.
- Backward compat: a project with no `generation_meta` shows an "unknown"
  provenance badge rather than erroring.

## Correctness Properties

Property 1: Provenance fidelity — for every scene render, `generation_meta`
reflects the actual backend used and whether the output is real video
(`is_real_video`) or a fallback (`fallback_used`).
**Validates: Requirements 3.1, 3.2**

Property 2: Shot plan equivalence — `build_shot_plan(scene).shots` equals the
`shot_timeline` derivation used by `build_canonical_timeline` for the same
scene (single source of truth).
**Validates: Requirements 1.1, 1.3**

Property 3: Shot timing integrity — shots are contiguous, ordered, and their
summed durations cover the scene duration (a synthesized plan covers full
duration).
**Validates: Requirements 1.1, 1.4**

Property 4: Policy soundness — in `strict` mode (or `VIDEO_STRICT=true`) a
provider failure never yields a silent 2.5D success; it raises and records
`failed`.
**Validates: Requirements 4.2, 4.4**

Property 5: Backward compatibility — loading a project without `shot_plan` /
`generation_meta` never errors; missing provenance renders as "unknown".
**Validates: Requirements 1.2**

Property 6: Timeline accuracy — `real_video_scene_count + fallback_scene_count`
accounts for all scenes with known provenance.
**Validates: Requirements 6.3**

## Error Handling

- Transient remote errors (429 / quota / timeout) are retried with the existing
  backoff; retry exhaustion is what triggers policy evaluation.
- `report` mode: render 2.5D, set `fallback_used=true`, populate truncated
  `error` and human-readable `warnings`; scene still renders.
- `strict` mode / `VIDEO_STRICT`: raise; the scene renderer records a `failed`
  history entry through the existing `_append_scene_history` path; the project
  remains loadable.
- `silent` mode: legacy quiet fallback (no surfaced warning) retained as an
  escape hatch.
- Missing/partial `generation_meta` on load is treated as unknown provenance,
  not an error.
- Persisted error text is truncated and stripped of credentials and query-param
  URLs.

## Security and Credential Considerations

- No new secrets. Provider credentials continue to come from environment
  variables enumerated in `video_providers.py` `config_env`.
- `generation_meta` MUST NOT store API keys, tokens, or full request bodies —
  only provider id/label/backend, counts, timings, and sanitized error text.
- Error strings persisted in `generation_meta.error` SHOULD be truncated and
  SHOULD NOT echo credentials or full URLs with query params.

## Testing Strategy

- Unit: `build_shot_plan` from a scene with `temporal_spec.shots`; synthesized
  single-shot plan when shots absent; shot timing is contiguous and matches
  scene duration.
- Unit: result-to-`generation_meta` mapping for each backend and each fallback
  mode (report/strict/silent, VIDEO_STRICT override).
- Unit: `build_canonical_timeline` emits `generation` metadata and correct
  `real_video_scene_count` / `fallback_scene_count`.
- Integration (mock provider): remote success path sets `is_real_video=true`;
  forced-failure in `report` mode persists fallback metadata and still produces
  a clip; `strict` mode raises and records a `failed` history entry.
- Backward-compat: load a legacy project JSON (no shot_plan/generation_meta)
  and confirm normalization defaults without error.
- Checks: `python -m py_compile` on edited modules; `node --check
  frontend\app.js`; sample workflow run when dependencies available.

## Rollback Plan

- All scene additions (`shot_plan`, `generation_meta`) are additive keys;
  removing the feature means ignoring them.
- `VIDEO_FALLBACK_MODE=silent` reproduces legacy behavior (quiet fallback) as
  an escape hatch without code changes.
- Timeline `generation` metadata and `summary` counts are additive; older
  consumers ignore unknown keys.

## Design Decisions

- DD-1 `shot_plan` mirrors `temporal_spec.shots` rather than replacing it, to
  avoid breaking existing readers (resolves OQ-1).
- DD-2 Reuse `VideoGenerationResult` from `backend/video_generation.py` as the
  shared provenance type instead of inventing a new one in `run_workflow.py`.
- DD-3 Default `VIDEO_FALLBACK_MODE=report` for the mainline release so real
  video is primary but a single bad scene does not abort a batch (resolves
  OQ-2). `strict` is opt-in for final delivery passes.
