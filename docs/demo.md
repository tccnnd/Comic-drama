# Demo Guide

This guide gives reviewers and contributors a fast way to understand the current
workflow without needing private project assets.

## Minimal Local Run

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\run_workflow.py --input inputs\sample_story.txt
```

Expected result:

- a new folder under `outputs/<run_id>/`
- scene keyframes
- scene audio
- scene video clips
- final MP4 export
- `canonical_timeline.json`

## Web Workbench

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/
```

The workbench is used for:

- project creation
- script recognition
- character asset review
- scene editing
- storyboard review
- scene rerendering
- final export

## What To Inspect

For a quick architecture review, inspect:

- `scripts/run_workflow.py`
- `video_providers.py`
- `backend/project_runtime.py`
- `frontend/app.js`
- `docs/canonical_timeline.md`
- `docs/self_hosted_video_provider.md`

## Current Quality Target

The local fallback renderer is not the final visual target. It exists to keep
the production chain testable when external video models are unavailable.

The intended high-quality path is:

```text
script -> role/scene extraction -> production bible -> canonical timeline
-> video provider -> review console -> export
```

## Known Demo Limitations

- Local fallback video is dynamic-comic style, not true model-generated motion.
- Sora, Seedance, Doubao, and aggregator providers require external gateways.
- ComfyUI quality depends on installed checkpoints, LoRA, IPAdapter, and custom
  nodes.
- Some generated assets are intentionally ignored from Git.
