# Production Pipeline

This document describes the end-to-end production spine of Comic Drama Workflow
and the maturity of each stage. It is a narrative overview; per-stage contracts
live in their own docs and specs.

## The Spine

```text
script
  → roles / assets
  → director interpretation        (v0.5.0 spec)
  → shot_plan + visual_content      (v0.2.0 shot_plan; visual_content is v0.5.0 spec)
  → production_bible
  → video provider / local 2.5D fallback   (v0.2.0)
  → canonical_timeline               (v0.2.0 provenance enrichment)
  → consistency governance           (v0.3.0)
  → director review console          (v0.4.0)
  → rerender / export
```

The system has progressed from "a workflow that runs" to an iterable
**AI comic-drama production workbench**: script-to-finished-video with a stable
production layer around the models (role continuity, timeline control, asset
review, provider routing, governance, and export).

## Stage Maturity

| Stage | Capability | Version | Status |
| --- | --- | --- | --- |
| Video generation mainline | Real video as primary renderer; local 2.5D as explicit, observable fallback; per-scene generation provenance; canonical-timeline metadata + real/fallback summary | v0.2.0 | Implemented (pushed) |
| Consistency governance | Five-dimension continuity (character/lighting/environment/prop/camera); per-scene verdict; project ledger; `report`/`block` policy | v0.3.0 | Implemented (local, pending merge) |
| Director review console | In-place review console: overview, triage filter/sort, unified review unit, per-scene + serial batch rerender | v0.4.0 | Implemented (local, pending merge) |
| Director interpretation | Structured `director_plan` (why) + per-shot `visual_content` (what); provider prompt consumes `visual_content` | v0.5.0 | Spec complete (local) |

## Branch / Merge State

Feature branches are pending merge in dependency order:

```text
main
 ├─ codex/video-provider-mainline        v0.2.0  (pushed)
 │   └─ codex/global-consistency-governance   v0.3.0  (local)
 │       └─ codex/director-review-console-impl   v0.4.0  (local)
 └─ codex/director-interpretation-mainline   v0.5.0 spec  (local, off main)
```

Planned merge order: `v0.2.0 → v0.3.0 → v0.4.0`. The v0.5.0 implementation,
when it starts, MUST be based on the v0.2.0 line (the
`shot_plan`/`canonical_timeline`/`build_scene_video_prompts` chain it modifies
was refactored by v0.2.0) — never on plain pre-v0.2.0 `main`.

## Minimal Demo Path

The canonical "show me it works" entrypoint uses the local keyframe provider to
bypass the environment-dependent ComfyUI tunnel:

```powershell
python -m scripts.run_workflow --input inputs\sample_story.txt --keyframe-provider local
```

This runs the full pipeline end-to-end and writes a final video plus
`canonical_timeline.json` to `outputs/<run_id>/`. With a video provider
configured, scenes attempt real video generation and fall back to local 2.5D
under the `report` policy, recording provenance either way.

Use the module form (`python -m scripts.run_workflow ...`); a direct-script
invocation currently has a `from scripts import tts_engines` import-resolution
issue tracked separately.

## Environment-Gated Verification

These are validated by tests and `node --check` / `py_compile`, but their live
runs depend on the environment and remain pending:

- **ComfyUI keyframe tunnel**: blocked here with
  `Error reading SSH protocol banner`; bypass with `--keyframe-provider local`.
- **Real-video success branch** (v0.2.0): the report-mode fallback path is
  validated live; a live real-video success run is quota/provider-dependent and
  covered by mock-provider tests.
- **Browser visual smoke** (v0.3.0, v0.4.0): the in-app browser blocks
  localhost (`ERR_BLOCKED_BY_CLIENT`); JS validated via `node --check` and
  helper tests.

## Future Lines (specced or deferred)

- `director-interpretation-mainline` (v0.5.0): spec complete; deterministic-first
  implementation pending, LLM tier deferred.
- `provider-cost-controls`: cost/timing/quota accounting — future spec.
- consistency-regeneration: the deferred `regenerate` policy mode from v0.3.0 —
  future spec, to add a render feedback loop only after verdicts prove stable.
- Long-form / multi-episode management and finer shot-language/prompt governance
  — not yet specced.
