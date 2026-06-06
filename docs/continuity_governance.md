# Continuity Governance

Continuity governance records scene-level consistency results without changing
the renderer's provider flow. It is additive: legacy projects without these
fields still load and render.

## Policy

`CONSISTENCY_POLICY_MODE` controls enforcement:

- `report` is the default. Verdicts are recorded and export deliverability is
  unchanged.
- `block` marks failing scenes as `deliverable=false`; export readiness then
  reports a `governance` gap for those scenes.

There is no governance-driven regeneration in this release.

## Props Registry

The production bible may include recurring props:

```json
{
  "props": [
    {
      "prop_id": "jade_pendant",
      "name": "Jade Pendant",
      "description": "Green jade pendant on a red cord",
      "owner_characters": ["Lin"],
      "scenes": ["scene_002", "scene_007"],
      "reference_image_path": "props/jade_pendant.png",
      "reference_meta": {}
    }
  ]
}
```

Scene continuity entries also carry a `props` string list. Missing props or
missing reference images produce an informational result, not a failure.

## Scene Verdict

Each rendered scene can persist a sibling `scene["governance"]` object:

```json
{
  "version": 1,
  "scene_id": "scene_002",
  "scene_order": 2,
  "status": "warn",
  "evaluated_at": "2026-06-06T12:00:00Z",
  "dimensions": {
    "character": { "status": "pass", "score": 0.82, "threshold": 0.6, "reason": "" },
    "lighting": { "status": "warn", "score": 0.54, "threshold": 0.5, "reason": "brightness shift" },
    "environment": { "status": "pass", "score": 0.78, "threshold": 0.49, "reason": "" },
    "prop": { "status": "info", "score": 0.0, "threshold": 0.6, "reason": "No tracked prop in scene" },
    "camera": { "status": "pass", "score": 1.0, "threshold": 0.6, "reason": "" }
  },
  "offending_dimensions": ["lighting"],
  "policy": { "mode": "report", "action": "recorded" },
  "deliverable": true
}
```

Overall status uses precedence: `fail` over `warn` over `pass`. `info` is
neutral and is used for missing references or skipped checks.

## Project Ledger

Project snapshots expose `continuity_ledger`:

```json
{
  "version": 1,
  "evaluated_scene_count": 6,
  "status_counts": { "pass": 4, "warn": 1, "fail": 1, "not_evaluated": 0 },
  "dimension_pass_rates": {
    "character": 1.0,
    "lighting": 0.83,
    "environment": 1.0,
    "prop": 1.0,
    "camera": 0.83
  },
  "offending_scenes": [
    { "scene_id": "scene_005", "scene_order": 5, "status": "fail", "offending_dimensions": ["character"] }
  ],
  "policy_mode": "report",
  "blocked_scene_count": 0
}
```

The review console reads the ledger for the project summary and each scene's
governance verdict for continuity badges and dimension details.
