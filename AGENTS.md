# Agent Collaboration Baseline

This repository is maintained with Codex, Kiro, and Cursor working together.
Use this file as the default instruction layer for AI coding agents.

## Project Objective

Comic Drama Workflow is an AI comic-drama production pipeline. The current
strategic priority is to move from keyframe-driven 2.5D clips toward real
video-provider scene generation while preserving a stable production spine:

```text
script -> roles/assets -> shot_plan -> production_bible
-> video provider -> canonical_timeline -> review/export
```

## Tool Roles

- **Kiro** owns specs: requirements, design, task breakdown, acceptance
  criteria, risks, and edge cases.
- **Codex** owns implementation integration: backend workflow, provider
  abstraction, tests, docs, Git hygiene, and release preparation.
- **Cursor** owns focused UI/local edits: frontend interaction, visual polish,
  CSS, small component edits, and manual UI debugging.

## Coordination Rules

1. Do not let multiple agents edit the same file family at the same time.
2. For large features, require a Kiro spec before implementation.
3. Codex should implement from the accepted spec and keep changes scoped.
4. Cursor should not change core backend architecture unless a task explicitly
   delegates that file to Cursor.
5. Any agent that changes behavior must update relevant docs or checklist
   notes.

## High-Risk Files

These files need extra care and should usually be edited by Codex only:

- `scripts/run_workflow.py`
- `backend/project_runtime.py`
- `video_providers.py`
- `scripts/video_provider_adapters.py`
- `backend/video_generation.py`
- `backend/scene_renderer.py`
- `frontend/app.js`

If Cursor edits `frontend/app.js`, Codex should run final syntax checks before
release.

## Required Checks

Run the checks that match the edited area:

```powershell
python -m py_compile scripts\run_workflow.py backend\project_runtime.py backend\app.py video_providers.py scripts\video_provider_adapters.py
node --check frontend\app.js
```

For provider or workflow changes, also run a short sample workflow when the
runtime dependencies are available:

```powershell
python scripts\run_workflow.py --input inputs\sample_story.txt
```

## Git Safety

- Do not commit `.env`, `workspace/`, `outputs/`, `tools/`, model weights,
  provider tokens, or private generated media.
- Keep external reference projects under `_external/` as references, not as
  copied source unless licensing and intent are explicit.
- Prefer small release-oriented commits after a feature has passed checks.

## Current Version Direction

The next planned feature line is:

```text
v0.2.0: video-provider-mainline
```

It should make real video generation the primary scene rendering path and keep
local 2.5D rendering as fallback.
