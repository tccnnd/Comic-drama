# Collaboration Baseline

This document defines how Codex, Kiro, Cursor, and the human maintainer should
coordinate on Comic Drama Workflow.

## Why This Exists

The project now has multiple AI tools involved. Without a shared baseline, they
can overwrite each other, duplicate work, or change architecture without a
stable spec. This baseline keeps work staged:

```text
Kiro specifies -> Codex implements -> Cursor polishes -> Codex integrates
```

## Tool Responsibilities

| Tool | Primary Role | Should Avoid |
| --- | --- | --- |
| Kiro | Requirements, design, tasks, risks, acceptance criteria | Large unsupervised code edits |
| Codex | Backend, workflow, provider abstraction, tests, Git, docs | Styling-only churn |
| Cursor | UI, CSS, local frontend interaction, visual debugging | Core provider/runtime architecture |
| Human maintainer | Product direction, model/vendor decisions, final acceptance | Letting tools edit overlapping files concurrently |

## Feature Lifecycle

### 1. Intake

The maintainer states the goal and target version.

Example:

```text
v0.2.0: Make real video generation the primary scene rendering path.
```

### 2. Kiro Spec

Kiro creates:

```text
.kiro/specs/<feature-id>/
  .config.kiro
  requirements.md
  design.md
  tasks.md
```

The spec must include:

- user-facing goal
- non-goals
- data schema changes
- affected files
- failure/fallback behavior
- acceptance tests
- rollback plan

### 3. Codex Implementation

Codex reads the accepted spec and implements in scoped slices:

- backend/runtime changes
- provider or pipeline changes
- tests/checks
- documentation
- changelog/release notes when relevant

Codex should report:

- changed files
- validation commands
- known risks
- follow-up tasks

### 4. Cursor UI Pass

Cursor works from explicit UI tasks:

- add or refine frontend controls
- expose metadata
- improve review canvas ergonomics
- fix layout and interaction bugs

Cursor should avoid changing backend contracts unless the contract is already
specified.

### 5. Codex Integration

Codex performs final checks:

- frontend syntax
- backend compile/import checks
- sample workflow if possible
- docs/changelog consistency
- release readiness

## File Ownership Matrix

| Area | Primary Owner | Secondary |
| --- | --- | --- |
| `.kiro/specs/**` | Kiro | Codex review |
| `scripts/run_workflow.py` | Codex | Kiro spec only |
| `video_providers.py` | Codex | Kiro spec only |
| `scripts/video_provider_adapters.py` | Codex | Kiro spec only |
| `backend/project_runtime.py` | Codex | Cursor read-only |
| `backend/video_generation.py` | Codex | Kiro spec only |
| `frontend/app.js` | Cursor for UI, Codex for integration | shared with caution |
| `frontend/styles.css` | Cursor | Codex review |
| `docs/**` | Codex | Kiro/Cursor may draft |
| `.github/**` | Codex | maintainer review |

## Spec Naming

Use lowercase kebab-case:

```text
.kiro/specs/video-provider-mainline/
.kiro/specs/global-consistency-governance/
.kiro/specs/director-review-console/
```

## Branch And Commit Guidance

Recommended branch naming:

```text
codex/video-provider-mainline
codex/global-consistency-governance
cursor/review-console-ui
```

Commit messages should describe the production behavior:

```text
Make video provider the primary scene renderer
Add shot-level camera metadata to canonical timeline
Expose provider metadata in review console
```

## Required Checks

Backend-oriented changes:

```powershell
python -m py_compile scripts\run_workflow.py backend\project_runtime.py backend\app.py video_providers.py scripts\video_provider_adapters.py
```

Frontend-oriented changes:

```powershell
node --check frontend\app.js
```

Workflow-oriented changes:

```powershell
python scripts\run_workflow.py --input inputs\sample_story.txt
```

## v0.2.0 Collaboration Contract

The next major implementation should start with:

```text
.kiro/specs/video-provider-mainline/
```

The spec should settle:

- `shot_plan` schema
- provider request/response metadata
- fallback rules
- canonical timeline media references
- review console metadata display
- cost/timing/failure logging
- minimal acceptance scenario

No implementation should begin until these contracts are clear.
