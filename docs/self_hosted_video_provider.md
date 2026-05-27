# Self-hosted video provider

This project now supports a pluggable scene video provider registry:

- `local`: keyframe PNG -> 2.5D motion clip -> concat.
- `comfyui`: self-hosted ComfyUI video workflow. If it fails, rendering falls back to `local` unless `VIDEO_STRICT=1`.
- `sora`, `xl`, `doubao`, and `seedance`: remote video model providers through a submit/poll/download gateway. If they fail, rendering falls back to `local` unless `VIDEO_STRICT=1`.

Provider ids are now resolved through `video_providers.py`. Unknown ids still fall back to `local` for backward compatibility.

## Required environment

```env
VIDEO_PROVIDER=comfyui
VIDEO_STRICT=0
COMFYUI_VIDEO_WORKFLOW_PATH=workflows/comfyui_video_template.json
COMFYUI_VIDEO_CHECKPOINT_NAME=
COMFYUI_VIDEO_LORA_NAME=
VIDEO_WIDTH=1080
VIDEO_HEIGHT=1920
VIDEO_FPS=24
VIDEO_STEPS=18
VIDEO_CFG=6.5
```

`COMFYUI_VIDEO_WORKFLOW_PATH` must point to an exported ComfyUI API-format workflow. The workflow should accept a first-frame image and return downloadable video media in ComfyUI history under `videos` or `gifs`.

## Supported placeholders

The video workflow can use these placeholders:

- `__PROMPT__`
- `__NEGATIVE__`
- `__SEED__`
- `__WIDTH__`
- `__HEIGHT__`
- `__STEPS__`
- `__CFG__`
- `__DURATION__`
- `__DURATION_SECONDS__`
- `__FPS__`
- `__PRIMARY_REFERENCE_IMAGE__`
- `__REFERENCE_IMAGE__`
- `__KEYFRAME_IMAGE__`

## Temporal and consistency contract

The renderer now builds two structured objects for every scene before calling a video provider:

- `temporal_spec`: shot order, shot timing, camera movement, zoom, hold ratios, focus point, dialogue, emotion, and continuity rules.
- `consistency_spec`: active characters, compiled character prompt, negative constraints, primary reference metadata, and identity/lighting/environment rules.

These specs are always appended to the text prompt as compact continuity instructions. Remote providers also write them to:

```text
outputs/<run_id>/debug/scene_<NN>_remote_video_<provider>_structured_spec.json
```

For gateway/self-hosted providers that accept structured metadata, set:

```env
VIDEO_SEND_STRUCTURED_SPEC=1
```

or provider-specific:

```env
XL_SEND_STRUCTURED_SPEC=1
SEEDANCE_SEND_STRUCTURED_SPEC=1
SORA_SEND_STRUCTURED_SPEC=1
```

When enabled for the unified route, the submit payload includes `metadata.temporal_spec`, `metadata.consistency_spec`, and top-level `temporal_spec` / `consistency_spec` for simpler gateway mapping. Official provider routes keep the structured data in debug files and rely on the prompt text, because many official APIs reject unknown fields.
- `__SCENE_TITLE__`
- `__SCENE_DIALOGUE__`
- `__SCENE_CAMERA__`
- `__SCENE_EMOTION__`
- `__CHARACTER_DESCRIPTIONS__`
- `__VIDEO_CHECKPOINT_NAME__`
- `__VIDEO_LORA_NAME__`
- `__VIDEO_LORA_STRENGTH_MODEL__`
- `__VIDEO_LORA_STRENGTH_CLIP__`
- `__VIDEO_IP_ADAPTER_WEIGHT__`

## CLI

```powershell
$env:PYTHONPATH="."
python scripts/run_workflow.py --story inputs/sample_story.txt --keyframe-provider comfyui --video-provider comfyui
```

Use `--video-provider local` to force the existing 2.5D renderer.

## Remote provider gateway

Remote providers use the same scene prompt, first-frame image, duration, size, and fps fields as the ComfyUI video path. The built-in adapter expects a small gateway-shaped protocol so the main workflow does not need to know each vendor's private API format.

Example Seedance-style config:

```env
VIDEO_PROVIDER=seedance
VIDEO_STRICT=0
VIDEO_STRUCTURED_SPEC_MODE=auto
VIDEO_SEND_STRUCTURED_SPEC=0
SEEDANCE_API_KEY=
SEEDANCE_MODEL=
SEEDANCE_BASE_URL=
# Or provide explicit endpoints instead of BASE_URL:
# SEEDANCE_SUBMIT_URL=
# SEEDANCE_POLL_URL=
SEEDANCE_TIMEOUT_SECONDS=900
SEEDANCE_POLL_INTERVAL_SECONDS=5
VIDEO_WIDTH=1080
VIDEO_HEIGHT=1920
VIDEO_FPS=24
```

The adapter submits JSON to `{BASE_URL}/videos` or `{PROVIDER}_SUBMIT_URL`:

```json
{
  "model": "provider-model-id",
  "prompt": "...",
  "negative_prompt": "...",
  "duration": 4.0,
  "width": 1080,
  "height": 1920,
  "fps": 24,
  "reference_image_base64": "...",
  "metadata": {
    "temporal_spec": { "...": "..." },
    "consistency_spec": { "...": "..." }
  },
  "scene": {
    "scene": 1,
    "title": "...",
    "camera": "...",
    "emotion": "...",
    "dialogue": "...",
    "characters": []
  }
}
```

If the gateway understands structured payloads, it can also accept top-level `temporal_spec` and `consistency_spec`. The adapter only sends those fields when `*_STRUCTURED_SPEC_MODE=fields` or `both`.

The submit response can return `video_url` / `video_base64` immediately, or return `task_id`. Task polling uses `{BASE_URL}/tasks/{task_id}` or `{PROVIDER}_POLL_URL` with a `{task_id}` placeholder. Polling succeeds on `completed`, `success`, `succeeded`, or `done`; it fails on `failed`, `failure`, `error`, `cancelled`, or `canceled`.

If an official Sora / Doubao / Seedance API uses different field names, keep this workflow-facing protocol stable and add a thin gateway or provider-specific mapper behind it.

## Provider presets

### OpenAI Sora

```env
VIDEO_PROVIDER=sora
OPENAI_API_KEY=
OPENAI_VIDEO_MODEL=sora-2
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_REFERENCE_FIELD=input_reference
```

### XL / Moyin-compatible aggregator

```env
VIDEO_PROVIDER=xl
XL_API_KEY=
XL_MODEL=
XL_BASE_URL=
XL_ROUTE=unified
XL_SUBMIT_URL=
XL_POLL_URL=
XL_CONTENT_URL=
XL_IMAGE_UPLOAD_URL=
XL_REFERENCE_IMAGE_URL=
XL_TIMEOUT_SECONDS=900
XL_POLL_INTERVAL_SECONDS=5
```

`XL_ROUTE` can be set to `openai_official`, `unified`, `volc`, or `kling` to force a route. If omitted, the adapter infers the route from the model name and provider id.
