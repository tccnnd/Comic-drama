# Audio Assets

Local audio assets used by the render pipeline.

## `bgm/`

Use one of these layouts:

- `bgm/<emotion>/<file>` for automatic matching, such as `bgm/tension/bridge_loop.mp3`
- `bgm/<file>` for uncategorized fallback beds
- `bgm/_meta.json` for optional tags

Example `_meta.json`:

```json
{
  "files": {
    "dramatic_loop.mp3": { "tags": ["tension", "action"] },
    "sadness/piano_bed.mp3": { "tags": ["sadness", "calm"] }
  }
}
```

Matching order:

1. `audio_manifest.bgm_file` or `audio_manifest.bgm_path`
2. `audio_manifest.bgm_style`
3. director-derived style from `emotion_tone`, `scene_intent`, `pacing`
4. `neutral` or uncategorized fallback

## `sfx/`

Short sound effects. Use `audio_manifest.sfx_trigger.file` or `audio_manifest.sfx_triggers[].file`.

Supported extensions: `.wav`, `.mp3`, `.m4a`, `.aac`, `.flac`, `.ogg`.
