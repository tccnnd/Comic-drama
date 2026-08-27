# Improvement Plan: video-provider-mainline

Status: v0.2.0 delivered, live real-video branch validated
Last updated: 2026-06-24

## Release Decision

Approve. The video-provider mainline is no longer only a qualified pass:
scene-level real-video generation has been validated against a live XL remote
provider, while local 2.5D remains the observable fallback path.

## Completed Since Initial Review

1. AC-7 live real-video success validation
   - Provider: `xl` (`XL Aggregator`)
   - Model/config observed in local environment: `happyhorse-1.0-i2v` through
     the Alibaba Bailian style route.
   - Evidence:
     `outputs/live_xl_ac7_20260624_161004/live_validation_result.json`
   - Output:
     `outputs/live_xl_ac7_20260624_161004/clip_01.mp4`
   - Result summary:
     `is_real_video=true`, `fallback_used=false`, `attempts=1`,
     `real_video_scene_count=1`, `fallback_scene_count=0`
   - Media validation from the live run: 1080x1920, 24 fps, H.264/AAC,
     duration about 5.04 seconds.

2. Operator troubleshooting runbook
   - Added `docs/troubleshooting_video_providers.md`.
   - Covers fallback policy, metadata interpretation, provider readiness,
     common failure modes, and safety notes for credentials/generated media.

3. Provider-mainline edge-case coverage
   - Added coverage for silent fallback, `VIDEO_STRICT` overriding
     `VIDEO_FALLBACK_MODE`, stronger error sanitization, provider readiness,
     and unchanged `shot_plan` persistence.
   - Latest targeted result: `tests/test_video_provider_mainline.py` passed
     with 16 tests.

4. Strict-mode diagnostics
   - Strict failures now include scene/provider context while keeping error text
     sanitized.

5. Review Console provider readiness
   - The Review Console now surfaces provider readiness at the project level in
     addition to per-scene generation provenance.

6. `shot_plan` persistence optimization
   - Scene generation metadata updates avoid replacing an unchanged
     `shot_plan`.

## Remaining Product Work

1. Shot-level real-video rendering and assembly
   - Current capability is scene-level real-video generation plus final
     scene-to-scene concatenation.
   - Real provider calls are still one call per scene.
   - Next feature line should render `shot_plan.shots[]` as individual provider
     clips, assemble them into a scene clip, and persist per-shot provenance.
   - Draft spec:
     `.kiro/specs/shot-level-video-rendering/`

2. Provider/model selector and configuration matrix
   - Separate LLM planning models from video-provider models.
   - Recommended LLM routing while Kiro is unavailable:
     `deepseek v4pro` for engineering/spec reasoning, `kimi k2.7` for long
     script and shot-context work, `minimax m3` for creative rewrite/variation,
     and `glm-5.2` as a general fallback.
   - Video-provider model selection should stay provider-registry driven and
     must not leak credentials into project artifacts.

3. Cost and usage controls
   - Add dry-run estimation, max provider calls, max generated seconds, and
     provider/model-level quota guards before enabling shot-level live runs by
     default.

4. `generation_meta` schema migration
   - Add a normalizer before introducing version 2 fields such as
     `render_granularity`, `shot_outputs`, usage, or cost.

5. Review Console shot detail
   - Surface `shot_plan`, per-shot render status, shot-level notes, and
     targeted shot rerender controls.

6. Export provenance sidecars
   - Include generation provenance and shot outputs in export sidecars for
     editor handoff.

7. Deferred feature lines
   - LLM director interpretation tier.
   - Consistency-driven regeneration.
   - Long-form / multi-episode management.
   - Stronger screenplay import and partial regeneration.

## Validation Baseline

Use this baseline before merging future provider-work changes:

```powershell
python scripts\check_text_hygiene.py
python -m py_compile scripts\run_workflow.py backend\project_runtime.py backend\app.py video_providers.py scripts\video_provider_adapters.py backend\scene_renderer.py backend\video_generation.py
node --check frontend\app.js
node --check frontend\render.js
node --check frontend\components\review\canvas.js
node tests\test_frontend_imports.mjs
node tests\test_review_console_helpers.mjs
python -m pytest -q tests\test_video_provider_mainline.py
```

Full-suite evidence from the latest implementation pass: `240 passed,
10 warnings`. The warnings are existing FastAPI/Pillow deprecations.

