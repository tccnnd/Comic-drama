# Agent Collaboration Baseline

This repository is maintained with Codex, Kiro, and Cursor working together.
Use this file as the default instruction layer for AI coding agents.

## Project Objective

Comic Drama Workflow is an AI comic-drama production pipeline. The current
strategic priority is to complete the director-interpretation layer and move
toward shot-level video rendering while preserving a stable production spine:

```text
script -> roles/assets -> director_plan + shot_plan + visual_prototype
-> production_bible -> video provider -> canonical_timeline
-> consistency governance -> director review console -> review/export
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
python -m py_compile backend\video_generation.py backend\scene_renderer.py
node --check frontend\app.js
```

For provider or workflow changes, also run a short sample workflow when the
runtime dependencies are available:

```powershell
# --story（不是 --input）；PYTHONPATH=. 必需，否则报
# ModuleNotFoundError: No module named 'backend'
$env:PYTHONPATH = "."
python -m scripts.run_workflow --story inputs\sample_story.txt
# 指定 provider / 渲染粒度时可追加：
python -m scripts.run_workflow --story inputs\sample_story.txt --keyframe-provider local --video-provider local --video-render-granularity scene|shot
```

Verification environment note: if the sandbox wraps `python` and reports
`Warning: Python was not found but appears to be installed`, call the project
virtualenv interpreter directly:

```powershell
.venv\Scripts\python.exe -m scripts.run_workflow --story inputs\sample_story.txt
```

## Git Safety

- Do not commit `.env`, `workspace/`, `outputs/`, `tools/`, model weights,
  provider tokens, or private generated media.
- Keep external reference projects under `_external/` as references, not as
  copied source unless licensing and intent are explicit.
- Prefer small release-oriented commits after a feature has passed checks.

## CI Gate (established 2026-08-29)

Changes to any of the following MUST go through a PR so the full Linux CI
pipeline runs before they land on `main`:

- `requirements*.in/.txt` (dependencies, platform markers, version pins)
- `.github/workflows/*` (CI jobs, commands, runners)
- Python entry points relied on by CI (`python -m <pkg>` usage — verify the
  package actually supports `-m` on Linux, e.g. isort 9 does not)
- Files listed under High-Risk Files

Rationale: the 2026-08-28 main CI failures were all "validated locally on
Windows but broken on Linux CI" (missing `sys_platform` markers for
pywin32/pypiwin32, `python -m isort` removed in isort 9, backend job missing
pytest). Local Windows checks do not cover the Linux runner environment.

After merging dependency changes, confirm the run is green
(`gh run list --limit 1`) before starting dependent work.

## Current Version Direction

The project is currently moving through **v0.5.0**
(`director-interpretation-mainline`). Delivered feature lines:

```text
v0.2.0: video-provider-mainline
v0.3.0: global-consistency-governance
v0.4.0: director-review-console
v0.5.0: director-interpretation
```

The next planned feature line is:

```text
next: shot-level-video-rendering
```

It should render each `shot_plan.shots[]` item through the video provider,
assemble shot clips into scene clips, and persist per-shot provenance while
keeping scene-level rendering as the default until live quota validation is
stable.
