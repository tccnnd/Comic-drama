# Self-hosted video provider

This project now supports two scene video providers:

- `local`: keyframe PNG -> 2.5D motion clip -> concat.
- `comfyui`: self-hosted ComfyUI video workflow. If it fails, rendering falls back to `local` unless `VIDEO_STRICT=1`.

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
