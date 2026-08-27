# Video Provider Troubleshooting

Use this runbook when a scene is expected to use a real video provider but the
workflow falls back to the local 2.5D renderer, fails in strict mode, or records
unexpected generation metadata.

## Fast Checks

Run the focused checks first:

```powershell
python scripts\check_text_hygiene.py frontend backend tests scripts docs README.md
python -m pytest -q tests\test_video_provider_mainline.py
```

For workflow-level validation:

```powershell
python scripts\run_workflow.py --input inputs\sample_story.txt --keyframe-provider local --video-provider local
```

When provider quota and credentials are available, validate the selected live
provider separately:

```powershell
python scripts\run_workflow.py --input inputs\sample_story.txt --keyframe-provider local --video-provider doubao
```

Replace `doubao` with `seedance`, `sora`, `xl`, or `comfyui` as needed.

## Fallback Policy

The video path uses one policy surface for every provider:

| Setting | Behavior |
| --- | --- |
| `VIDEO_FALLBACK_MODE=report` | Default. Retry the provider, fall back to local 2.5D on failure, and persist visible fallback metadata and warnings. |
| `VIDEO_FALLBACK_MODE=strict` | Retry the provider, then raise instead of creating a local fallback clip. |
| `VIDEO_FALLBACK_MODE=silent` | Retry the provider, fall back to local 2.5D, and suppress fallback warnings. This is only for compatibility checks. |
| `VIDEO_STRICT=1` | Global strict override. Takes precedence over `VIDEO_FALLBACK_MODE`. |
| `<PROVIDER>_VIDEO_STRICT=1` | Provider-specific strict override, for example `DOUBAO_VIDEO_STRICT=1`. |

Use `report` during normal development because it preserves the workflow while
making provider failures auditable. Use `strict` for release validation and live
provider acceptance checks.

## Reading Generation Metadata

Each rendered scene should persist `generation_meta`:

- `provider_id`: resolved provider id such as `doubao`, `seedance`, `comfyui`,
  or `local`.
- `backend`: `remote`, `comfyui`, or `local`.
- `is_real_video`: `true` when the selected provider produced the clip.
- `fallback_used`: `true` when a non-local provider failed and the local 2.5D
  renderer supplied the clip.
- `attempts`: number of provider attempts before success or fallback.
- `fallback_mode`: effective policy after strict overrides.
- `error`: sanitized failure summary. Tokens, API keys, authorization headers,
  bearer secrets, and URL query parameters must not be persisted.
- `warnings`: visible fallback messages unless silent mode suppressed them.

The canonical timeline also copies this metadata into each picture item and
summarizes known `real_video_scene_count` and `fallback_scene_count`.

### Shot-Level Render Metadata (v0.6.0-pre)

When `VIDEO_RENDER_GRANULARITY=shot` is active, `generation_meta` is version 2
and carries per-shot provenance:

- `version`: `2`
- `render_granularity`: `"shot"`
- `shot_outputs`: per-shot records, each with `shot_id`, `status`
  (`real_video` / `fallback` / `failed` / `skipped`), `provider_id`, `backend`,
  `path`, `attempts`, `cache_key`, and sanitized `error`/`warnings`.
- `real_video_shot_count`, `fallback_shot_count`, `failed_shot_count`,
  `skipped_shot_count`: aggregate counts.
- `total_provider_attempts`: sum of per-shot attempts.
- `shot_assembly_manifest`: hard-cut concat manifest with `children[]` timing.
- Legacy scene-level fields (`provider_id`, `backend`, `is_real_video`,
  `fallback_used`, `attempts`, `fallback_mode`, `error`, `warnings`) remain
  for backward compatibility.

The canonical timeline enriches `shot_timeline[]` items with compact per-shot
`generation` copied from `shot_outputs[]`.

## Common Failures

### Quota Or Rate Limit

Symptoms include HTTP 429, quota, billing, or rate-limit messages. In `report`
mode the workflow should still produce a local clip, set `fallback_used=true`,
and preserve the sanitized error for review.

Recommended action: wait for quota recovery, lower concurrency outside this
workflow if applicable, then rerun the affected scene in `strict` mode to verify
the provider path.

### Missing Credentials Or Endpoint

Remote providers usually require provider-specific environment values:

```env
DOUBAO_API_KEY=
DOUBAO_BASE_URL=
DOUBAO_MODEL=
SEEDANCE_API_KEY=
SEEDANCE_BASE_URL=
SEEDANCE_MODEL=
XL_API_KEY=
XL_BASE_URL=
XL_MODEL=
OPENAI_API_KEY=
OPENAI_VIDEO_MODEL=
```

Exact names depend on the provider route in
`scripts/video_provider_adapters.py`. Keep secrets in `.env` or the shell
environment; never commit them.

### ComfyUI Unreachable

Typical causes are a stopped ComfyUI process, a stale SSH tunnel, the wrong
host in `COMFYUI_BASE_URL`, or an HTTP response that is actually an SSH banner.

Recommended action: open the ComfyUI URL in a browser or run a simple health
request, then retry with `VIDEO_FALLBACK_MODE=strict` once the service responds.

### Workflow, Model, Or Node Missing

ComfyUI failures often mention missing checkpoints, LoRAs, node classes, or
unresolved placeholders. Confirm:

- `COMFYUI_VIDEO_WORKFLOW_PATH` points to an API-format workflow JSON.
- `COMFYUI_VIDEO_CHECKPOINT_NAME` matches an installed checkpoint.
- Optional LoRA and custom node names exist on the ComfyUI host.
- The workflow contains supported placeholders listed in
  [self_hosted_video_provider.md](self_hosted_video_provider.md).

### Unknown Provenance In Review

Old projects may have clips without `generation_meta`. This is expected for
legacy data. Rerender the scene to populate current provenance fields.

### Shot-Level Render Issues

Shot-level rendering (`VIDEO_RENDER_GRANULARITY=shot`) introduces additional
environment variables and failure modes:

| Setting | Purpose |
| --- | --- |
| `VIDEO_RENDER_GRANULARITY` | `scene` (default) or `shot`. |
| `VIDEO_SHOT_MAX_CALLS` | Max provider calls per scene; quota validation runs before the first submit. |
| `VIDEO_SHOT_MAX_SECONDS` | Max total generated seconds per scene. |
| `VIDEO_SHOT_DRY_RUN` | When truthy, estimate quota and block if over limit without submitting. |
| `VIDEO_SHOT_REUSE_CACHE` | When truthy, reuse unchanged successful shot outputs on rerender. |

Common issues:

- **`VideoShotQuotaError` before any provider call**: quota validation blocked
  the render. Raise `VIDEO_SHOT_MAX_CALLS` / `VIDEO_SHOT_MAX_SECONDS`, or reduce
  shot count in `temporal_spec.shots[]`.
- **Shot marked `fallback` in `report` mode**: the provider failed for that
  shot; the local 2.5D renderer supplied a fallback clip. Check the sanitized
  `error` field in `shot_outputs[]`.
- **Strict mode raises without a video asset**: expected behavior. In `strict`
  mode, any shot failure aborts the scene; no fallback clip is produced and
  `generation_meta` is not persisted.
- **Targeted rerender not reusing cache**: confirm `VIDEO_SHOT_REUSE_CACHE=1`
  and that the shot's `cache_key` matches. A shot will be re-rendered if its
  request inputs (prompt, timing, camera, visual content) changed.
- **`shot_assembly_manifest.json` missing**: the manifest is written only when
  `render_granularity=shot` and the scene has at least one usable shot output.

## Security Notes

Do not commit `.env`, provider tokens, `workspace/`, `outputs/`, `tools/`,
model weights, or private generated media. Provider errors persisted into
project JSON are sanitized, but logs and gateway-side records may still contain
sensitive data.
