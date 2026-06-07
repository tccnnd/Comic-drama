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
| v0.2.0 | `video-provider-mainline` | Delivered on `main`; AC-7 qualified pass | merged from `codex/video-provider-mainline` |
| v0.3.0 | `global-consistency-governance` | Delivered on `main`; browser visual smoke pending | merged from `codex/global-consistency-governance` |
| v0.4.0 | `director-review-console` | Delivered on `main`; browser visual smoke pending | merged from `codex/director-review-console-impl` |
| v0.5.0 | `director-interpretation-mainline` | Spec complete, local commit; implementation not started | `codex/director-interpretation-mainline` |

## Delivered Stack

The implementation branches were merged in dependency order:

```text
main
+-- v0.2.0 video-provider-mainline
    +-- v0.3.0 global-consistency-governance
        +-- v0.4.0 director-review-console
```

The v0.5.0 spec branch is intentionally separate and off an earlier `main`.
Its implementation should now be created on a new branch based on current
`main`, which already contains v0.2.0 through v0.4.0.

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

- Rebase and merge this docs consolidation branch after v0.4.0.
- Keep v0.5.0 implementation on a new branch based on current `main`.
- Keep `_external/Toonflow-app` untouched unless explicitly investigating that
  nested reference project.
