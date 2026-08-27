# CI Coverage Threshold — Upgrade Plan

## What changed
`COVERAGE_THRESHOLD` in `.github/workflows/ci.yml` raised from `"0"` → `"30"`.

Frontend `node --check` expanded to cover all JS modules:
- `frontend/api.js`
- `frontend/events.js`
- `frontend/utils.js`
- `frontend/state.js`
- `frontend/timeline.js`

## Recommended threshold ramp-up schedule

| Quarter | Threshold | Action |
|---------|-----------|--------|
| Now     | 30 %      | Applied in this fix |
| +4 wks  | 50 %      | Add tests for `video_providers.py` and `project_runtime.py` core |
| +8 wks  | 65 %      | Add tests for `app.py` routes and `video_generation.py` |
| +12 wks | 75 %      | Steady-state target |

Bump `COVERAGE_THRESHOLD` in `ci.yml` as each milestone is reached.
Do **not** skip thresholds — the jump from 0 → 75 in one step will
block CI until enough tests are written.
