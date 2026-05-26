from __future__ import annotations

import json
import time
from typing import Any, Callable


VALID_CAMERA_MOVEMENT = {
    "dramatic_push",
    "melancholy_pan",
    "establishing_tilt",
    "static",
    "slow_push",
    "pull_back",
}
VALID_EMOTION_TONE = {
    "anger",
    "sadness",
    "joy",
    "tension",
    "calm",
    "fear",
    "surprise",
    "neutral",
}
VALID_SFX_TYPE = {
    "boom",
    "drop",
    "whoosh",
    "thunder",
    "hit",
    "none",
}
VALID_SCENE_INTENT = {
    "establishing",
    "dialogue",
    "action",
    "reaction",
    "transition",
}
VALID_PACING = {"slow", "medium", "fast"}
VALID_SUBJECT_FOCUS = {
    "single_character",
    "two_shot",
    "group",
    "environment",
}

FIELD_VALIDATORS: dict[str, set[str]] = {
    "camera_movement": VALID_CAMERA_MOVEMENT,
    "emotion_tone": VALID_EMOTION_TONE,
    "sfx_type": VALID_SFX_TYPE,
    "scene_intent": VALID_SCENE_INTENT,
    "pacing": VALID_PACING,
    "subject_focus": VALID_SUBJECT_FOCUS,
}

SYSTEM_PROMPT = """You are a storyboard classification assistant.
Return only valid JSON. Do not add markdown or explanations.

Classify each scene into exactly these fields:
- scene_index
- camera_movement
- emotion_tone
- sfx_type
- scene_intent
- pacing
- subject_focus

Allowed values:
camera_movement: dramatic_push, melancholy_pan, establishing_tilt, static, slow_push, pull_back
emotion_tone: anger, sadness, joy, tension, calm, fear, surprise, neutral
sfx_type: boom, drop, whoosh, thunder, hit, none
scene_intent: establishing, dialogue, action, reaction, transition
pacing: slow, medium, fast
subject_focus: single_character, two_shot, group, environment

Rules:
- scene_index must match the 0-based position in the input array.
- Do not invent values outside the allowed enums.
- Return a JSON array only.
"""

USER_PROMPT_TEMPLATE = """Classify the following {count} scenes.

{scenes_json}
"""


class DirectorClassificationError(Exception):
    pass


def _scene_get(scene: Any, key: str, default: Any = "") -> Any:
    if isinstance(scene, dict):
        return scene.get(key, default)
    return getattr(scene, key, default)


def _scene_set(scene: Any, key: str, value: Any) -> None:
    if isinstance(scene, dict):
        scene[key] = value
    else:
        setattr(scene, key, value)


def _build_scene_input(scene: Any, index: int) -> dict[str, Any]:
    return {
        "scene_index": index,
        "order": _scene_get(scene, "scene", index + 1),
        "title": str(_scene_get(scene, "title", "")),
        "visual": str(_scene_get(scene, "visual", "")),
        "visual_prompt": str(_scene_get(scene, "visual_prompt", _scene_get(scene, "visual", ""))),
        "dialogue": str(_scene_get(scene, "dialogue", "")),
        "emotion": str(_scene_get(scene, "emotion", "")),
        "speaker": str(_scene_get(scene, "speaker", "")),
        "characters": list(_scene_get(scene, "characters", [])) if isinstance(_scene_get(scene, "characters", []), list) else [],
        "camera": str(_scene_get(scene, "camera", "")),
        "sfx_type": str(_scene_get(scene, "sfx_type", "")),
        "duration": _scene_get(scene, "duration", None),
    }


def classify_scenes_batch(
    scenes: list[Any],
    call_llm_fn: Callable[[str, str, str], str],
    model: str = "",
) -> list[dict[str, Any]]:
    if not scenes:
        return []
    if len(scenes) > 10:
        raise ValueError(f"Single batch is limited to 10 scenes, got {len(scenes)}")

    scenes_input = [_build_scene_input(scene, index) for index, scene in enumerate(scenes)]
    user_prompt = USER_PROMPT_TEMPLATE.format(
        count=len(scenes_input),
        scenes_json=json.dumps(scenes_input, ensure_ascii=False, indent=2),
    )

    try:
        raw_response = call_llm_fn(SYSTEM_PROMPT, user_prompt, model)
    except TypeError:
        raw_response = call_llm_fn(SYSTEM_PROMPT, user_prompt)
    except Exception as exc:
        raise DirectorClassificationError(f"LLM call failed: {exc}") from exc

    classifications = _parse_llm_response(raw_response)
    aligned = _align_by_index(classifications, expected_count=len(scenes))
    _validate_batch(aligned)
    return aligned


def apply_llm_classification(scene: Any, classification: dict[str, Any], model_name: str) -> None:
    for field in FIELD_VALIDATORS:
        if field in classification:
            _scene_set(scene, field, classification[field])

    _scene_set(
        scene,
        "director_meta",
        {
            "source": "llm",
            "model": model_name or None,
            "classified_at": time.time(),
            "warnings": [],
        },
    )


def apply_rules_classification(scene: Any, apply_director_fn: Callable[[Any], None], reason: str = "") -> None:
    apply_director_fn(scene)
    _scene_set(
        scene,
        "director_meta",
        {
            "source": "rules",
            "model": None,
            "classified_at": time.time(),
            "warnings": [reason] if reason else [],
        },
    )


def apply_default_classification(scene: Any, reason: str = "") -> None:
    defaults = {
        "camera_movement": "static",
        "emotion_tone": "neutral",
        "sfx_type": "none",
        "scene_intent": "dialogue",
        "pacing": "medium",
        "subject_focus": "single_character",
    }
    for field, value in defaults.items():
        current = _scene_get(scene, field, "")
        if not current:
            _scene_set(scene, field, value)

    _scene_set(
        scene,
        "director_meta",
        {
            "source": "default",
            "model": None,
            "classified_at": time.time(),
            "warnings": [reason] if reason else ["director classification fell back to defaults"],
        },
    )


def _parse_llm_response(raw: str) -> list[dict[str, Any]]:
    text = raw.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise DirectorClassificationError("LLM output did not contain a JSON array.")
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise DirectorClassificationError(f"Failed to parse JSON array: {exc}") from exc

    if isinstance(parsed, dict) and isinstance(parsed.get("scenes"), list):
        parsed = parsed["scenes"]
    if not isinstance(parsed, list):
        raise DirectorClassificationError(f"LLM output must be a JSON array, got {type(parsed).__name__}")
    return parsed


def _align_by_index(
    classifications: list[dict[str, Any]],
    expected_count: int,
) -> list[dict[str, Any]]:
    index_map: dict[int, dict[str, Any]] = {}

    for item in classifications:
        if not isinstance(item, dict):
            raise DirectorClassificationError(f"Classification item must be an object, got {type(item).__name__}")
        idx = item.get("scene_index")
        if idx is None:
            raise DirectorClassificationError(f"Missing scene_index in classification item: {item}")
        try:
            idx = int(idx)
        except (TypeError, ValueError) as exc:
            raise DirectorClassificationError(f"scene_index must be an integer: {idx!r}") from exc
        if idx < 0 or idx >= expected_count:
            raise DirectorClassificationError(f"scene_index={idx} out of range (expected 0-{expected_count - 1})")
        if idx in index_map:
            raise DirectorClassificationError(f"scene_index={idx} appears more than once")
        index_map[idx] = item

    missing = [i for i in range(expected_count) if i not in index_map]
    if missing:
        raise DirectorClassificationError(f"Missing classifications for scene_index values: {missing}")

    return [index_map[i] for i in range(expected_count)]


def _validate_batch(classifications: list[dict[str, Any]]) -> None:
    for item in classifications:
        idx = item.get("scene_index", "?")
        for field, valid_values in FIELD_VALIDATORS.items():
            value = item.get(field)
            if value is None:
                raise DirectorClassificationError(f"scene_index={idx} is missing field {field}")
            if value not in valid_values:
                raise DirectorClassificationError(
                    f"scene_index={idx} field {field}={value!r} is not in {sorted(valid_values)}"
                )
