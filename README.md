# Comic Drama Workflow MVP

This is a local project-based prototype for a comic-drama generation workflow.

The current version stores each project under `workspace/<project_id>/` and keeps the full asset chain visible on disk:

1. Story text input
2. Structured storyboard JSON
3. Scene-level keyframes
4. Scene-level TTS audio
5. Scene-level 2.5D clips
6. Final MP4 export

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run

```powershell
.\.venv\Scripts\python.exe scripts\run_workflow.py
```

Outputs are written to `outputs/<run_id>/`.

## Optional LLM Storyboard Planner

Copy `.env.example` to `.env`, then set your API key and OpenAI-compatible endpoint:

```powershell
Copy-Item .env.example .env
```

Run with the LLM planner:

```powershell
.\.venv\Scripts\python.exe scripts\run_workflow.py --planner llm
```

If no LLM configuration is present, `--planner auto` falls back to the deterministic rule planner.

The current visual layer renders a per-scene keyframe PNG locally and then turns it into a short animated clip. That gives you a stable replacement point for ComfyUI or any other image generator later.

To use ComfyUI as the keyframe provider, set `KEYFRAME_PROVIDER=comfyui` and point `COMFYUI_WORKFLOW_PATH` at an exported workflow JSON template. The script will fill placeholder strings like `__PROMPT__`, `__NEGATIVE__`, `__SEED__`, `__WIDTH__`, and `__HEIGHT__` before sending the prompt.

For audio, set `TTS_PROVIDER=edge` for online Chinese voices, `TTS_PROVIDER=local` for Windows SAPI/pyttsx3, or `TTS_PROVIDER=silent` as a fallback.

To give different characters different voices, add a `voice_presets.json` file at the project root or point `VOICE_PRESETS_PATH` at another JSON file. The workflow will use the scene speaker or inferred role to pick a voice, and `TTS_EDGE_VOICE` still works as a global override when you want one voice for the whole show.

For local external-provider testing, run:

```powershell
.\start_mock_tts_provider.bat
```

It serves `POST /tts` on `http://127.0.0.1:8010/tts` and can back all four external engine slots in `workspace/tts_provider_settings.json`.

## Backend API

Run the local API server:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

Open the workbench:

```text
http://127.0.0.1:8000/
```

Create a project:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/projects -ContentType 'application/json' -Body '{"title":"霸总的限时娇妻","planner":"rule","keyframe_provider":"local","voice_provider":"auto","scene_count":5}'
```

The workbench now centers on:

- project scaffold creation
- project-level editing
- character library maintenance
- character reference image upload
- scene card editing
- single-scene rerender
- full project build and export

Project artifacts are exposed under `/workspace/<project_id>/...`.

## Next Replacement Points

- Replace `build_storyboard()` with an LLM structured output call.
- Replace `render_keyframe()` with ComfyUI image generation.
- Replace the local 2.5D clip step with ComfyUI, AnimateDiff, or image-to-video generation.
- Replace placeholder audio with TTS.
- Replace placeholder audio with TTS.
- Wrap this script behind a FastAPI task endpoint and stream progress to the web UI.
