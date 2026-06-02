# Canonical Timeline

The canonical timeline is the project-level interchange object for editorial,
review, and render backends. It is OTIO-inspired, but does not require the
OpenTimelineIO Python package at runtime.

## Goals

- Keep cut order, durations, transitions, and media references in one object.
- Treat video/image/audio providers as render backends, not project structure.
- Preserve existing `scene_graph`, `temporal_spec`, and `production_bible` data
  as metadata for each timeline clip.
- Provide a stable JSON target for future import/export adapters.

## Shape

```json
{
  "version": 1,
  "kind": "canonical_timeline",
  "schema": "otio-inspired",
  "project_id": "proj_xxx",
  "title": "Episode title",
  "frame_rate": 24,
  "resolution": { "width": 1080, "height": 1920 },
  "duration_seconds": 43.1,
  "tracks": [
    {
      "track_id": "picture",
      "track_type": "video",
      "children": []
    },
    {
      "track_id": "dialogue",
      "track_type": "audio",
      "children": []
    }
  ],
  "transitions": [],
  "scene_index": []
}
```

## Clip Contract

Each picture clip represents one scene cut:

```json
{
  "item_type": "clip",
  "clip_id": "scene_001_picture",
  "scene_id": "scene_001",
  "scene_order": 1,
  "name": "Opening",
  "start_seconds": 0.0,
  "duration_seconds": 4.2,
  "end_seconds": 4.2,
  "source_range": { "start_seconds": 0.0, "duration_seconds": 4.2 },
  "media_reference": {
    "path": "scenes/scene_001/video_v1.mp4",
    "url": "/workspace/proj_xxx/scenes/scene_001/video_v1.mp4"
  },
  "metadata": {
    "emotion_tone": "tension",
    "pacing": "medium",
    "camera_movement": "slow_push",
    "production_bible": {},
    "temporal_spec": {}
  },
  "shot_timeline": []
}
```

The `shot_timeline` remains scene-relative. The clip start/end fields are
project-relative.

## Current Producers

- `scripts.run_workflow.build_canonical_timeline(project)`
- `backend.project_runtime.project_snapshot(project)`
- `scripts/run_workflow.py` writes `canonical_timeline.json` next to
  `storyboard.json` for standalone workflow runs.

## Compatibility

Existing fields remain valid:

- `scene_graph` is still emitted as a legacy summary.
- `scene.temporal_spec` is still used by renderer/provider requests.
- `project.production_bible` remains the global continuity source.

New systems should read `canonical_timeline` first and fall back to legacy
fields only when importing older projects.
