# Director Review Console

The director review console evolves the storyboard review canvas into a
production review and rerender surface. It is a frontend view over existing
project snapshot fields; it does not add generation, governance, provider, or
review persistence schemas.

## Overview

The console derives its summary at render time:

- Review progress from each scene's existing `review_meta`.
- Provenance counts from `generation_meta` (`real`, `fallback`, `local`,
  `unknown`).
- Continuity counts from `continuity_ledger`.
- Readiness counts from asset gaps and governance block-mode deliverability.
- Director prototype counts from `shot_plan.shots[].visual_prototype`
  (`prototype_lock`, `freeform`, and gap reasons).

For offline prototype coverage tracking across one project or a workspace, run
`python scripts\prototype_gap_report.py workspace --pretty`.

For manual prototype-to-output quality tracking, generate a scorecard template:

```powershell
python scripts\prototype_quality_scorecard.py workspace --pretty
```

Fill the `scores` fields on a 0-5 scale and summarize the completed file with:

```powershell
python scripts\prototype_quality_scorecard.py path\to\scorecard.json --summary --pretty
```

Scores must be based on visual inspection of the generated image/video, not on
the prompt text alone. For each scored entry, fill `review.reviewer`,
`review.reviewed_at`, `review.evidence`, and `review.rationale` so the rating is
traceable to the actual output.

Overview metrics are clickable and update the current triage filter in client
state.

## Triage

The visible scene list is derived by `applyReviewTriage` from the current
snapshot. Filters can be combined:

- Review status: `unreviewed`, `approved`, `needs_work`, `blocked`.
- Continuity status: `pass`, `warn`, `fail`, `not_evaluated`.
- Provenance: `real`, `fallback`, `local`, `unknown`.
- Deliverability: deliverable, blocked, or missing assets.
- Prototype mode: `prototype_lock`, `freeform`, or `unknown`.
- Prototype gaps: all scenes, gap-only scenes, or scenes without prototype gaps.
- Minimum rating.

Sort modes are scene order, rating high first, continuity risk, and fallback
first. Legacy projects without provenance or governance render as
`unknown`/`not_evaluated`.

## Review Unit

Each scene is rendered as a review unit that combines:

- Thumbnail or clip preview.
- Existing generation provenance badge/detail.
- Shot-level render status when `generation_meta.render_granularity="shot"`:
  real, fallback, failed, skipped, or planned rows are displayed from
  `generation_meta.shot_outputs[]` or canonical `shot_timeline[].generation`;
  selected-scene detail rows expose per-shot video rerender controls.
- Existing governance badge/detail.
- Director prototype badge/detail: prototype id, lock/freeform mode,
  hard/soft/guideline constraints, and gap reason when no prototype matched.
- Review status and rating.
- Asset readiness and export-block marker.
- Existing status/rating/notes save form for the selected scene.

Review-state edits continue through the existing save path.

## Rerender Actions

Per-scene buttons call existing scene operations:

- Image -> `rerender-image`
- Audio -> `rerender-audio`
- Video -> `rerender-video`
- Full -> `rebuild`

When a scene was rendered with `video_render_granularity=shot`, each selected
shot-status row can submit a targeted video rerender through
`/api/projects/{project_id}/scenes/{scene_order}/shots/{shot_id}/rerender-video`.
The action requires confirmation because it can consume provider quota, reuses
unchanged cached shot outputs on the backend, and then refreshes the project
snapshot through the same frontend state path as scene-level actions.

Batch rerender acts on the current filtered set, requires explicit confirmation,
runs serially, and records per-scene outcomes. Failures are isolated: one failed
scene does not stop the remaining scenes.

After each action, the project snapshot returned by the existing endpoint is
loaded into frontend state, so updated provenance and governance are reflected
from the latest snapshot.

## Boundaries

The console does not:

- Add new provider or scheduling logic.
- Add governance-driven automatic regeneration.
- Change backend generation logic.
- Change review/provenance/governance data schemas.
- Score prototype quality in the UI or automatically compare prototype-lock vs
  freeform output quality. The offline scorecard script is the current manual
  scoring path.
- Track provider costs or quotas.

## Checks

Frontend changes should pass:

```powershell
node --check frontend\app.js
node --check frontend\api.js
node --check frontend\events.js
node --check frontend\render.js
node --check frontend\state.js
node --check frontend\utils.js
node tests\test_review_console_helpers.mjs
```


Scorecard entries include URL and local path evidence (image_url, image_path, ideo_url, ideo_path, inal_video_path, and provider_output_path) plus scoreable_entries / missing_visual_evidence in the summary.

