# Production Pipeline

This document describes the end-to-end production spine of Comic Drama Workflow
and the maturity of each stage. It is a narrative overview; per-stage contracts
live in their own docs and specs.

## The Spine

```text
script
  -> roles / assets
  -> director interpretation        (v0.5.0 delivered)
  -> shot_plan + visual_prototype + visual_content
  -> production_bible
  -> scene-level video provider / local 2.5D fallback   (v0.2.0)
  -> shot-level provider assembly           (v0.6.0-pre delivered; Gate C EVALUATED 2026-09-01)
  -> canonical_timeline               (v0.2.0 provenance enrichment, shot-level in v0.6.0-pre)
  -> consistency governance           (v0.3.0)
  -> director review console          (v0.4.0)
  -> rerender / export
```

The system has progressed from "a workflow that runs" to an iterable
**AI comic-drama production workbench**: script-to-finished-video with a stable
production layer around the models (role continuity, timeline control, asset
review, provider routing, governance, and export).

## Stage Maturity

| Stage | Capability | Version | Status |
| --- | --- | --- | --- |
| Video generation mainline | Scene-level real video as primary renderer; local 2.5D as explicit, observable fallback; per-scene generation provenance; canonical-timeline metadata + real/fallback summary | v0.2.0 | Delivered on `main`; live XL success validated |
| Consistency governance | Five-dimension continuity (character/lighting/environment/prop/camera); per-scene verdict; project ledger; `report`/`block` policy | v0.3.0 | Delivered on `main` |
| Director review console | In-place review console: overview, triage filter/sort, unified review unit, per-scene + serial batch rerender | v0.4.0 | Delivered on `main` |
| Director interpretation | Structured `director_plan` (why) with scene-level `shot_archetypes`; per-shot `visual_prototype` (`id`, params, hard/soft/guideline constraints) renders deterministic `visual_content`; provider prompt consumes `visual_content` plus prototype constraints | v0.5.0 | Delivered on `main` (2026-06-07); deterministic-first, LLM tier deferred |
| Shot-level video rendering | Render each `shot_plan.shots[]` item through the video provider, assemble shot clips into a scene clip, and persist per-shot provenance | v0.6.0-pre | 17/17 tasks complete. Gate C EVALUATED 2026-09-01: two-shot XL live submit (HTTP 429 → report fallback) produced valid assembled 10s 1080x1920 media + `shot_outputs`. XL `real_video` success at shot-level still pending aggregator quota. |

## Merge State

The v0.2.0 through v0.4.0 implementation stack has been merged into `main` in
dependency order:

```text
main
  -> v0.2.0 video-provider-mainline
  -> v0.3.0 global-consistency-governance
  -> v0.4.0 director-review-console
```

The v0.5.0 implementation now extends the current `main`
`shot_plan`/`canonical_timeline`/`build_scene_video_prompts` path with a
deterministic director interpretation layer. The first pass is intentionally
small: high-frequency dialogue/reaction and high-weight danger/action beats can
lock to visual prototypes, while low-weight or uncovered beats remain freeform
and record a prototype gap for later library expansion.
Provider prompts preserve this layering without adapter-specific changes:
prototype hard constraints are emitted as `MUST PRESERVE`, soft constraints as
`SHOULD PRESERVE`, and guidelines as `GUIDE` quality hints.
The first quality loop is manual and offline: `scripts/prototype_quality_scorecard.py`
extracts prototype/freeform shots, output media paths, generation provenance,
constraints, and empty 0-5 scoring fields so real provider output can be
visually inspected and reviewed before expanding the prototype library further.
The scorecard requires reviewer/evidence/rationale metadata because prompt-only
scoring is not a valid quality signal.

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

These are validated by tests and `node --check` / `py_compile`, but some live
runs still depend on the environment:

- **ComfyUI keyframe tunnel**: blocked here with
  `Error reading SSH protocol banner`; bypass with `--keyframe-provider local`.
- **Scene-level real-video success branch** (v0.2.0): validated live with the
  XL provider in `outputs/live_xl_ac7_20260624_161004`
  (`is_real_video=true`, `fallback_used=false`, `attempts=1`).
- **Shot-level real-video branch**: not implemented yet; tracked by the
  `shot-level-video-rendering` draft spec.
- **Browser visual smoke** (v0.3.0, v0.4.0): the in-app browser blocks
  localhost (`ERR_BLOCKED_BY_CLIENT`); JS validated via `node --check` and
  helper tests.

## Future Lines (specced or deferred)

- `director-interpretation-mainline` (v0.5.0): deterministic-first
  implementation in progress; visual prototype library seeded; LLM tier
  deferred.
- `shot-level-video-rendering`: draft spec for per-shot provider calls,
  shot-output provenance, scene assembly, resume/targeted rerender, and quota
  guards.
- `provider-cost-controls`: cost/timing/quota accounting; future spec.
- consistency-regeneration: the deferred `regenerate` policy mode from v0.3.0;
  future spec, to add a render feedback loop only after verdicts prove stable.
- Long-form / multi-episode management and finer shot-language/prompt governance
  not yet specced.
- Prototype-to-output A/B automation: the manual scorecard exists, but automatic
  paired reruns, CLIP scoring, and cost-aware provider sampling remain deferred.
