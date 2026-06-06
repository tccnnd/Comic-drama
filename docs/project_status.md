# Project Status And Consolidation Plan

This document summarizes the current feature-line state for the Comic Drama
Workflow repository. It is a consolidation note, not a replacement for the
individual Kiro specs or release notes.

## Current Production Spine

The implemented workflow is now organized around this production spine:

```text
script
-> roles/assets
-> shot_plan
-> production_bible
-> video provider / local fallback
-> canonical_timeline
-> consistency governance
-> director review console
-> rerender / export
```

The next planned spine extension is the director interpretation layer:

```text
script
-> director interpretation
-> shot_plan + visual_content
-> video provider prompt
```

## Feature-Line Status

| Version | Feature line | Status | Branch |
| --- | --- | --- | --- |
| v0.2.0 | `video-provider-mainline` | Implemented, pushed; AC-7 qualified pass | `codex/video-provider-mainline` |
| v0.3.0 | `global-consistency-governance` | Implemented, local commits; browser visual smoke pending | `codex/global-consistency-governance` |
| v0.4.0 | `director-review-console` | Implemented, local commits; browser visual smoke pending | `codex/director-review-console-impl` |
| v0.5.0 | `director-interpretation-mainline` | Spec complete, local commit; implementation not started | `codex/director-interpretation-mainline` |

## Branch Stack

The implementation branches form a dependency stack:

```text
main
+-- codex/video-provider-mainline          v0.2.0
    +-- codex/global-consistency-governance v0.3.0
        +-- codex/director-review-console-impl v0.4.0
```

The v0.5.0 spec branch is intentionally separate and off `main`. Its
implementation must be created on a new branch based on
`codex/video-provider-mainline` or on `main` after v0.2.0 has merged.

## Recommended Merge Order

Merge the implementation stack in dependency order:

1. `codex/video-provider-mainline` -> `main`
2. `codex/global-consistency-governance` -> `main`
3. `codex/director-review-console-impl` -> `main`

After v0.2.0 merges, rebase v0.3.0 onto the updated `main` before opening its
PR. After v0.3.0 merges, rebase v0.4.0 onto the updated `main`.

## Known Pending Verification

- Live real-video success path is provider quota / tunnel dependent. The
  report-mode fallback path was validated end-to-end.
- ComfyUI keyframe tunnel can block the full ComfyUI sample path. The local
  keyframe path is the current reliable demo route.
- Browser visual smoke for the governance and director-review UI remains
  environment-gated.

## Canonical Demo Path

Use the local keyframe provider to avoid the ComfyUI tunnel gate:

```powershell
python -m scripts.run_workflow --input inputs\sample_story.txt --keyframe-provider local
```

Expected result: an output run directory under `outputs/`, per-scene media, a
`canonical_timeline.json`, and a final `comic_drama_demo.mp4`.

## Immediate Consolidation Tasks

- Open and merge the v0.2.0 PR first.
- Keep v0.3.0 and v0.4.0 local until their baselines are updated.
- Do not rewrite the pushed v0.2.0 branch only to remove spec-only docs.
- Keep `_external/Toonflow-app` untouched unless explicitly investigating that
  nested reference project.
