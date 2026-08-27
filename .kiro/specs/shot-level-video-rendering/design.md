# Design: shot-level-video-rendering

## Overview

The design extends the current scene renderer with an optional shot-level
render path. Scene-level rendering remains the default and compatibility path.
Shot-level rendering splits a scene into `shot_plan.shots[]`, renders each shot
through the selected video provider or local fallback, then assembles the shot
clips into the scene clip used by the existing canonical timeline and export
pipeline.

```text
scene
  -> shot_plan.shots[]
  -> build shot render requests
  -> render shot clips with provider/fallback policy
  -> assemble shot clips into scene clip
  -> persist generation_meta + shot_outputs
  -> canonical_timeline
  -> Review Console / export
```

## Current Baseline

Existing behavior already provides:

- `shot_plan` persisted per scene.
- Scene-level `generation_meta`.
- Scene-level real-video provider path with local 2.5D fallback.
- Final scene-to-scene concatenation with cut/transition handling.
- Local/fallback segment concatenation for non-provider generated scene
  segments.

The missing part is official real-provider rendering per shot.

## Data Contracts

### Scene generation metadata

Shot-level rendering should keep existing `generation_meta` fields and add
versioned optional fields:

```json
{
  "version": 2,
  "provider_id": "xl",
  "provider_label": "XL Aggregator",
  "backend": "remote",
  "requested_provider": "xl",
  "is_real_video": true,
  "fallback_used": true,
  "attempts": 4,
  "duration_seconds": 8.0,
  "fallback_mode": "report",
  "generated_at": "2026-06-24T09:00:00Z",
  "render_granularity": "shot",
  "real_video_shot_count": 2,
  "fallback_shot_count": 1,
  "failed_shot_count": 0,
  "total_provider_attempts": 4,
  "shot_outputs": []
}
```

Version 1 readers must continue to work by ignoring unknown fields. A
`normalize_generation_meta` helper should be introduced before writing version
2 metadata.

### Shot output

Each `shot_outputs[]` entry should be stable and sanitized:

```json
{
  "shot_id": "scene_001_shot_002",
  "index": 2,
  "status": "real_video",
  "provider_id": "xl",
  "provider_label": "XL Aggregator",
  "backend": "remote",
  "model": "happyhorse-1.0-i2v",
  "path": "scenes/scene_001/shots/shot_002.mp4",
  "duration_seconds": 2.0,
  "target_duration_seconds": 2.0,
  "attempts": 1,
  "fallback_used": false,
  "warnings": [],
  "error": "",
  "cache_key": "sha256:..."
}
```

`model` is allowed only when it is a public model identifier. Secrets, signed
URLs, request bodies, and query tokens must not be persisted.

### Assembly manifest

The renderer should write a lightweight manifest next to the assembled scene
clip for debugging and resume:

```json
{
  "version": 1,
  "scene_id": "scene_001",
  "render_granularity": "shot",
  "output_path": "scenes/scene_001/video_v3.mp4",
  "children": [
    {
      "shot_id": "scene_001_shot_001",
      "path": "scenes/scene_001/shots/shot_001.mp4",
      "start_seconds": 0.0,
      "duration_seconds": 2.0
    }
  ]
}
```

## Runtime Flow

1. Resolve render granularity.
2. Load or synthesize `shot_plan`.
3. Estimate call count/generated seconds and enforce configured limits.
4. For each shot:
   - Build a shot prompt from `visual_content`, camera fields, timing, and
     scene continuity context.
   - Resolve provider/model configuration.
   - Compute a cache key.
   - Reuse valid existing shot output when resuming.
   - Render through the provider with existing retry/fallback policy.
   - Persist sanitized shot output metadata.
5. Assemble valid shot clips into a scene clip.
6. Persist scene `generation_meta`, scene history, and assembly manifest.
7. Rebuild or update canonical timeline references.

## Module Responsibilities

| Module | Responsibility |
| --- | --- |
| `scripts/run_workflow.py` | Add shot-level orchestration helpers, shot request building, assembly, workflow flags, and canonical timeline metadata. |
| `backend/video_generation.py` | Add versioned normalization and helpers for aggregating shot outputs into scene `generation_meta`. |
| `backend/scene_renderer.py` | Invoke shot-level render path for scene generation/rerender, persist metadata/history, support targeted shot rerender. |
| `backend/project_runtime.py` | Expose shot outputs and render granularity in project snapshots. |
| `backend/app.py` | Add API surface for granularity config and targeted shot rerender after backend support lands. |
| `frontend/components/review/canvas.js` | Display shot-level status and later targeted shot rerender controls. |
| `frontend/utils.js` | Add pure helper functions for generation/shot status labels and classes. |

Provider adapter wire formats should not change in the first implementation.

## Execution Ownership

Codex leads this feature line: implementation sequencing, high-risk backend
changes, provider integration, tests, docs, and final acceptance. M3 may assist
with creative shot-language alternatives, prompt wording candidates, and
non-core documentation drafts, but it must not be the deciding authority for
renderer architecture, provider policy, schema changes, or release validation.

## Configuration

Accepted keys for the first implementation:

```text
VIDEO_RENDER_GRANULARITY=scene|shot
VIDEO_SHOT_MAX_CALLS=<int>
VIDEO_SHOT_MAX_SECONDS=<float>
VIDEO_SHOT_REUSE_CACHE=1|0
VIDEO_SHOT_DRY_RUN=1|0
```

Resolution order:

1. Explicit CLI flag for standalone workflow runs.
2. API/runtime request value for backend rerender calls.
3. Safe persisted project setting, if present.
4. Environment default.
5. Built-in default: `scene`.

The accepted CLI/API names should mirror the environment keys:

```text
--video-render-granularity scene|shot
--video-shot-max-calls <int>
--video-shot-max-seconds <float>
--video-shot-dry-run
--video-shot-reuse-cache
```

`scene` remains the default until shot-level cost controls, Review Console
read-only status, and mock-provider integration tests are all implemented.
`shot` mode must pass quota validation before the first provider submit. A
missing or unusable multi-shot `shot_plan` degrades to the existing scene-level
path unless strict validation is explicitly requested in a later task.

Persisted project state should store only safe public configuration and actual
provenance. It must not store provider tokens, signed URLs, raw request bodies,
or private gateway parameters.

## Provider And Model Routing

Video-provider model routing remains provider-registry driven. The code should
distinguish:

- LLM/planning models: `deepseek v4pro`, `kimi k2.7`, `minimax m3`,
  `glm-5.2`.
- Video-provider models: provider-specific model ids such as the XL/Alibaba
  model validated in AC-7.

Recommended planning model usage while Kiro is unavailable:

| Need | Preferred model |
| --- | --- |
| Engineering/spec reasoning | `deepseek v4pro` |
| Long script and shot-context reasoning | `kimi k2.7` |
| Creative rewrite or variation | `minimax m3` |
| General fallback | `glm-5.2` |

Implementation tests should mock model selection; they should not call live LLM
or video providers.

## Fallback Semantics

| Mode | Shot failure behavior |
| --- | --- |
| `report` | Retry provider, render local fallback for failed shot, assemble mixed scene, record warnings. |
| `strict` | Retry provider, fail scene if a required shot fails, record failed history. |
| `silent` | Retry provider, render local fallback, record metadata, suppress visible warnings. |

Scene-level `fallback_used` is true when any shot falls back. Scene-level
`is_real_video` is true when at least one shot is real video and no required
shot failed; consumers needing precision should read `shot_outputs`.

## Resume And Cache

The cache key should include:

- Shot id/index and target duration.
- Shot prompt inputs, including `visual_content` and camera fields.
- Provider id and public model/config.
- Source reference image or first-frame fingerprint.
- Production bible fields used in the prompt.
- Fallback mode only when it affects output.

Targeted shot rerender should invalidate one shot output, rerender it, and
reassemble the scene clip without resubmitting unchanged valid shots.

## Canonical Timeline

Existing scene-level `metadata.generation` remains present. New readers may
inspect:

```json
{
  "metadata": {
    "generation": {
      "render_granularity": "shot",
      "shot_outputs": []
    }
  },
  "shot_timeline": [
    {
      "shot_id": "scene_001_shot_001",
      "generation": {}
    }
  ]
}
```

If duplicating full `shot_outputs` into every timeline clip becomes too heavy,
the implementation may store compact shot status in `shot_timeline` and keep
the full list in the scene/project snapshot.

## Testing Strategy

- Unit tests for granularity resolution, shot cache keys, metadata aggregation,
  sanitization, and quota dry-run calculations.
- Mock-provider integration tests for all-real, mixed fallback, strict failure,
  and targeted rerender.
- Assembly tests using generated tiny clips or existing local helpers.
- Snapshot/API tests for legacy scene-level projects and shot-level projects.
- Frontend helper tests for shot status labels/classes.
- Optional live XL validation only when explicitly requested and quota is
  available.

## Rollout Plan

1. Land accepted configuration resolution and schema normalizers.
2. Add shot assembly behind `VIDEO_RENDER_GRANULARITY=shot`.
3. Add fallback and resume behavior with tests.
4. Surface read-only shot status in the Review Console.
5. Add targeted shot rerender after the read-only flow is stable.
6. Run one controlled live short two-shot validation if provider quota is
   explicitly approved.
