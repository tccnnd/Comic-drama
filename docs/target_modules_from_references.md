# Target Modules From References

This document captures the parts of OpenToonz and OmniVoice that are worth carrying into Comic Drama.

## OpenToonz: what to borrow

- Scene timeline model: project -> scene -> shot -> layer -> keyframe.
- Camera track as a first-class object instead of a derived render parameter.
- Xsheet / timeline editing for shot ordering and duration control.
- Onion-skin style frame adjacency review for continuity checks.
- Export-friendly scene graph that separates content from render backend.

## OmniVoice: what to borrow

- Voice preset registry per character or role.
- Voice design as a reusable preset, not a one-off TTS request.
- Voice clone / reference voice as a separate capability from plain TTS.
- Batch generation for many dialogue lines.
- Non-speech cues and emotion markers as part of the voice layer.

## Comic Drama: target module map

### 1. Scene graph

Keep the project data model explicit:

- project
- episode
- scene
- shot
- camera track
- visual layer
- audio layer
- subtitle layer

### 2. Voice layer

Add a voice preset system with:

- `character_id`
- `voice_engine`
- `voice_model`
- `reference_audio`
- `emotion_profile`
- `rate`, `pitch`, `volume`
- `non_speech_cues`

### 3. Provider layer

Keep provider routing separate from content logic:

- `video_provider`
- `voice_provider`
- `keyframe_provider`
- `provider_status`
- `provider_capabilities`

### 4. Editing layer

Add UI and API entry points for:

- shot order
- duration adjustment
- camera movement
- keyframe preview
- voice preset binding
- provider status inspection

## Suggested next build step

Implement the scene graph layer first:

1. formalize `shot` as a real data object
2. bind `camera` to each shot
3. store per-shot audio and subtitle references
4. expose the structure in the project snapshot API

That gives us the foundation for both the OpenToonz-style editor path and the OmniVoice-style voice path.
