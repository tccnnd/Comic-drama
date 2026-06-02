# Comic Drama Workflow

An open-source AI comic-drama production workflow for turning a script into
structured scenes, character assets, dialogue audio, storyboard review data,
and an editorial timeline.

The project is currently an early local-first prototype. It is designed for
experiments around AI-assisted short drama, dynamic comics, and video-generation
pipelines rather than for production hosting.

## What It Does

- Imports story text and turns it into structured storyboard scenes.
- Extracts characters, speakers, dialogue, scene beats, props, and visual cues.
- Maintains project assets on disk under `workspace/<project_id>/`.
- Generates keyframes through local fallback rendering or ComfyUI.
- Generates dialogue audio through pluggable TTS providers.
- Builds 2.5D dynamic-comic clips and exports a final MP4.
- Supports pluggable video providers for local, ComfyUI, Sora-style, Doubao,
  Seedance, and aggregator-style gateways.
- Produces an OTIO-inspired `canonical_timeline` for downstream renderers,
  review tools, and future editing integrations.
- Provides a local web workbench for project editing, character management,
  scene review, rerendering, and export.

## Why This Matters

AI video generation is moving quickly, but creative workflows still need a
stable production layer around models: script parsing, role continuity,
timeline control, asset review, provider routing, and export management.

This repository explores that middle layer. The goal is to make the production
workflow reusable, auditable, and provider-agnostic so creators can swap models
without rewriting the whole project structure.

## Current Status

Implemented:

- Project scaffold and workspace artifact layout
- Script-to-storyboard workflow
- Role and dialogue extraction foundations
- Character library and reference image upload
- Scene-level keyframe, audio, and clip generation
- Subtitle timing, BGM/SFX hooks, and enhanced dynamic-comic rendering
- ComfyUI image workflow injection and validation
- Self-hosted and remote video provider abstraction
- Canonical timeline generation
- Storyboard review canvas with status, rating, notes, and version comparison

In progress:

- Real continuous video generation as the primary scene renderer
- Stronger global consistency governance across characters, light, camera, and
  environment
- Provider adapters for commercial and self-hosted video models
- More complete screenplay import and director review workflows

## Demo And Review Materials

- [Demo guide](docs/demo.md)
- [Roadmap](docs/roadmap.md)
- [Initial release notes](docs/releases/v0.1.0.md)
- [Codex open-source application notes](docs/open_source_application.md)

## Repository Layout

```text
backend/        FastAPI app, project runtime, local web API
frontend/       Browser workbench UI
scripts/        Main workflow runner and media pipeline
workflows/      ComfyUI workflow templates
docs/           Architecture notes and implementation plans
inputs/         Sample scripts
workspace/      Local project data, ignored for production use when needed
outputs/        Render outputs
video_providers.py
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Copy environment defaults when you need model or provider integrations:

```powershell
Copy-Item .env.example .env
```

## Run The Local Workflow

```powershell
.\.venv\Scripts\python.exe scripts\run_workflow.py --input inputs\sample_story.txt
```

Outputs are written to `outputs/<run_id>/`.

## Run The Web Workbench

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/
```

The workbench supports project creation, script recognition, character assets,
scene editing, review notes, rerendering, full build, and export.

## Model And Provider Integrations

### LLM Planner

Set an OpenAI-compatible endpoint and key in `.env`, then run:

```powershell
.\.venv\Scripts\python.exe scripts\run_workflow.py --planner llm
```

If no LLM configuration is present, `--planner auto` falls back to deterministic
rules.

### ComfyUI

Set:

```env
KEYFRAME_PROVIDER=comfyui
COMFYUI_WORKFLOW_PATH=workflows/comfyui_keyframe_template.json
COMFYUI_CHECKPOINT_NAME=v1-5-pruned-emaonly-fp16.safetensors
COMFYUI_LORA_NAME=
```

The workflow template is injected structurally at runtime. If `COMFYUI_LORA_NAME`
is empty, the LoRA node is skipped and the checkpoint model is connected
directly.

### Video Providers

The scene video provider registry is documented in
[docs/self_hosted_video_provider.md](docs/self_hosted_video_provider.md).

Supported provider shapes include:

- `local`: built-in 2.5D dynamic-comic clip renderer
- `comfyui`: self-hosted ComfyUI video workflow
- `sora`: Sora-style submit/poll/download gateway
- `doubao`: Doubao-style remote video gateway
- `seedance`: Seedance-style remote video gateway
- `aggregator`: Moyin/Happy Horse-style routing gateway

## Canonical Timeline

The workflow emits an OTIO-inspired canonical timeline object for downstream
editing, provider routing, review, and export tools.

See [docs/canonical_timeline.md](docs/canonical_timeline.md).

## Roadmap

See [docs/roadmap.md](docs/roadmap.md).

## Repository Health

The repository includes:

- MIT license
- Contribution guide
- Security policy
- Code of conduct
- Changelog
- Roadmap
- Collaboration baseline for Codex, Kiro, and Cursor
- Issue templates for bugs, features, and provider integrations
- Pull request template

Suggested GitHub topics:

```text
ai-video, generative-ai, comic, storyboard, comfyui, timeline, tts, video-generation, python, fastapi
```

## Contributing

Contributions are welcome while the project is still in early architecture
formation. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening issues
or pull requests.

For AI-assisted development, read
[docs/collaboration_baseline.md](docs/collaboration_baseline.md) and
[AGENTS.md](AGENTS.md).

## Security

Please read [SECURITY.md](SECURITY.md) before reporting vulnerabilities or
sharing logs that may contain credentials.

## License

MIT. See [LICENSE](LICENSE).
