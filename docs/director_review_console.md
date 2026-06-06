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

Overview metrics are clickable and update the current triage filter in client
state.

## Triage

The visible scene list is derived by `applyReviewTriage` from the current
snapshot. Filters can be combined:

- Review status: `unreviewed`, `approved`, `needs_work`, `blocked`.
- Continuity status: `pass`, `warn`, `fail`, `not_evaluated`.
- Provenance: `real`, `fallback`, `local`, `unknown`.
- Deliverability: deliverable, blocked, or missing assets.
- Minimum rating.

Sort modes are scene order, rating high first, continuity risk, and fallback
first. Legacy projects without provenance or governance render as
`unknown`/`not_evaluated`.

## Review Unit

Each scene is rendered as a review unit that combines:

- Thumbnail or clip preview.
- Existing generation provenance badge/detail.
- Existing governance badge/detail.
- Review status and rating.
- Asset readiness and export-block marker.
- Existing status/rating/notes save form for the selected scene.

Review-state edits continue through the existing save path.

## Rerender Actions

Per-scene buttons call existing scene operations only:

- Image -> `rerender-image`
- Audio -> `rerender-audio`
- Video -> `rerender-video`
- Full -> `rebuild`

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
