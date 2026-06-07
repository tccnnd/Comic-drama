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
VALID_SHOT_SIZE = {
    "extreme_close_up",
    "close_up",
    "medium",
    "wide",
    "extreme_wide",
}

DIRECTOR_PLAN_VERSION = 1
VISUAL_CONTENT_FIELDS = (
    "shot_description",
    "foreground",
    "midground",
    "background",
    "composition",
    "motion",
    "lighting",
    "focus",
)

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


def build_director_plan(scene: Any) -> dict[str, Any]:
    """Build a deterministic director interpretation for a scene."""
    scene_intent = _validated_scene_value(scene, "scene_intent", VALID_SCENE_INTENT, "dialogue")
    emotion_tone = _validated_scene_value(scene, "emotion_tone", VALID_EMOTION_TONE, "neutral")
    pacing = _validated_scene_value(scene, "pacing", VALID_PACING, "medium")
    subject_focus = _validated_scene_value(scene, "subject_focus", VALID_SUBJECT_FOCUS, "single_character")
    title = _first_text(
        _scene_get(scene, "title", ""),
        _scene_get(scene, "scene_title", ""),
        f"scene {_scene_get(scene, 'scene', '')}".strip(),
    )
    visual = _first_text(_scene_get(scene, "visual_prompt", ""), _scene_get(scene, "visual", ""))
    has_classification = any(
        _scene_get(scene, key, "") in FIELD_VALIDATORS[key]
        for key in ("scene_intent", "emotion_tone", "pacing", "subject_focus", "camera_movement")
    )
    source = "rules" if has_classification else "default"

    dramatic_intent = _dramatic_intent(scene_intent, pacing)
    emotional_target = _emotional_target(emotion_tone)
    narrative_focus = _narrative_focus(subject_focus, scene_intent)
    rationale_bits = [
        f"{scene_intent} scene",
        f"{emotion_tone} tone",
        f"{pacing} pacing",
        f"{subject_focus} focus",
    ]
    if title:
        rationale_bits.insert(0, title)
    if visual:
        rationale_bits.append(f"visual basis: {_shorten(visual)}")

    return {
        "version": DIRECTOR_PLAN_VERSION,
        "dramatic_intent": dramatic_intent,
        "emotional_target": emotional_target,
        "narrative_focus": narrative_focus,
        "rationale": "; ".join(rationale_bits),
        "source": source,
    }


def build_shot_visual_content(scene: Any, shot: Any | None = None) -> dict[str, Any]:
    """Build deterministic visual-content fields for one shot."""
    shot = shot or {}
    plan = build_director_plan(scene)
    subject_focus = _validated_scene_value(scene, "subject_focus", VALID_SUBJECT_FOCUS, "single_character")
    scene_intent = _validated_scene_value(scene, "scene_intent", VALID_SCENE_INTENT, "dialogue")
    emotion_tone = _validated_scene_value(scene, "emotion_tone", VALID_EMOTION_TONE, "neutral")
    camera_movement = _validated_shot_or_scene_value(
        scene,
        shot,
        ("camera_movement", "movement", "camera"),
        VALID_CAMERA_MOVEMENT,
        "static",
    )
    shot_size = _validated_shot_or_scene_value(
        scene,
        shot,
        ("shot_size", "size", "framing"),
        VALID_SHOT_SIZE,
        _shot_size_for(subject_focus, scene_intent),
    )
    visual_basis = _first_text(
        _shot_get(shot, "visual_content", ""),
        _shot_get(shot, "description", ""),
        _shot_get(shot, "prompt", ""),
        _scene_get(scene, "visual_prompt", ""),
        _scene_get(scene, "visual", ""),
        _scene_get(scene, "dialogue", ""),
        "the scene's central dramatic beat",
    )
    camera_language = _camera_language(camera_movement, shot_size, emotion_tone)
    visual_content = _visual_content(
        visual_basis=visual_basis,
        subject_focus=subject_focus,
        scene_intent=scene_intent,
        emotion_tone=emotion_tone,
        camera_language=camera_language,
    )

    return {
        "shot_size": shot_size,
        "camera_language": camera_language,
        "dramatic_intent": plan["dramatic_intent"],
        "visual_content": visual_content,
    }


def _scene_meta(scene: Any) -> dict[str, Any]:
    meta = _scene_get(scene, "director_meta", {})
    return meta if isinstance(meta, dict) else {}


def _shot_get(shot: Any, key: str, default: Any = "") -> Any:
    if isinstance(shot, dict):
        return shot.get(key, default)
    return getattr(shot, key, default)


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, dict):
            continue
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value if item)
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _shorten(text: str, limit: int = 120) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _validated_scene_value(scene: Any, key: str, valid_values: set[str], default: str) -> str:
    value = _scene_get(scene, key, "")
    if not value:
        value = _scene_meta(scene).get(key, "")
    value = str(value or "").strip()
    return value if value in valid_values else default


def _validated_shot_or_scene_value(
    scene: Any,
    shot: Any,
    keys: tuple[str, ...],
    valid_values: set[str],
    default: str,
) -> str:
    for key in keys:
        value = str(_shot_get(shot, key, "") or "").strip()
        if value in valid_values:
            return value
    for key in keys:
        value = str(_scene_get(scene, key, "") or "").strip()
        if value in valid_values:
            return value
    return default


def _dramatic_intent(scene_intent: str, pacing: str) -> str:
    base = {
        "establishing": "orient the audience in the scene's space and stakes",
        "dialogue": "make the spoken conflict and relationship tension readable",
        "action": "prioritize kinetic cause and effect with clear screen direction",
        "reaction": "hold on emotional consequence before the next beat",
        "transition": "carry the audience cleanly into the next story beat",
    }[scene_intent]
    pacing_clause = {
        "slow": "using held beats and controlled tempo",
        "medium": "with balanced scene rhythm",
        "fast": "with urgent rhythm and compressed decision time",
    }[pacing]
    return f"{base}, {pacing_clause}"


def _emotional_target(emotion_tone: str) -> str:
    return {
        "anger": "keep the performance sharp, confrontational, and unstable",
        "sadness": "let loss and hesitation sit visibly in the frame",
        "joy": "make warmth and release feel immediate",
        "tension": "sustain pressure and unresolved danger",
        "calm": "keep the moment composed, legible, and unhurried",
        "fear": "make the threat feel close and unavoidable",
        "surprise": "create a clean reveal and visible reaction beat",
        "neutral": "keep the emotional read clear without overstatement",
    }[emotion_tone]


def _narrative_focus(subject_focus: str, scene_intent: str) -> str:
    focus = {
        "single_character": "the lead character's immediate decision",
        "two_shot": "the relationship pressure between two characters",
        "group": "group dynamics and changing alignment",
        "environment": "environmental context and spatial stakes",
    }[subject_focus]
    if scene_intent == "establishing":
        return f"{focus}, with clear orientation for the audience"
    if scene_intent == "reaction":
        return f"{focus}, emphasizing consequence over action"
    return focus


def _shot_size_for(subject_focus: str, scene_intent: str) -> str:
    if scene_intent == "establishing" and subject_focus == "environment":
        return "extreme_wide"
    return {
        "single_character": "close_up",
        "two_shot": "medium",
        "group": "wide",
        "environment": "wide",
    }[subject_focus]


def _camera_language(camera_movement: str, shot_size: str, emotion_tone: str) -> dict[str, str]:
    movement = {
        "dramatic_push": "push in to compress attention on the decisive beat",
        "slow_push": "slow push in to increase emotional pressure",
        "pull_back": "pull back to reveal context and consequence",
        "melancholy_pan": "slow pan across the scene to carry reflective mood",
        "establishing_tilt": "tilt to introduce scale and spatial hierarchy",
        "static": "locked-off frame that lets performance and blocking carry the beat",
    }[camera_movement]
    lens = {
        "extreme_close_up": "telephoto macro compression",
        "close_up": "short telephoto portrait compression",
        "medium": "normal lens with natural perspective",
        "wide": "wide lens for spatial readability",
        "extreme_wide": "wide lens emphasizing geography and scale",
    }[shot_size]
    depth = "shallow depth of field" if shot_size in {"extreme_close_up", "close_up"} else "deep readable focus"
    if emotion_tone in {"tension", "fear", "sadness"} and shot_size in {"medium", "wide", "extreme_wide"}:
        depth = "selective focus with controlled background separation"
    return {
        "movement": movement,
        "lens": lens,
        "depth_of_field": depth,
        "framing": _framing_for(shot_size),
    }


def _framing_for(shot_size: str) -> str:
    return {
        "extreme_close_up": "detail dominates the frame with minimal environment",
        "close_up": "face or decisive prop carries the composition",
        "medium": "upper body and immediate relationship space stay visible",
        "wide": "characters and environment share the frame",
        "extreme_wide": "environment establishes the scene before performance detail",
    }[shot_size]


def _visual_content(
    visual_basis: str,
    subject_focus: str,
    scene_intent: str,
    emotion_tone: str,
    camera_language: dict[str, str],
) -> dict[str, str]:
    basis = _shorten(visual_basis, 180)
    focus_label = subject_focus.replace("_", " ")
    return {
        "shot_description": f"{basis}; directed as a {scene_intent} beat with {emotion_tone} tone",
        "foreground": _foreground_for(subject_focus),
        "midground": _midground_for(subject_focus, basis),
        "background": _background_for(scene_intent),
        "composition": camera_language["framing"],
        "motion": camera_language["movement"],
        "lighting": _lighting_for(emotion_tone),
        "focus": f"audience attention stays on {focus_label} and the scene's dramatic turn",
    }


def _foreground_for(subject_focus: str) -> str:
    return {
        "single_character": "the principal character or decisive prop anchors the foreground",
        "two_shot": "both characters share foreground weight without losing eyeline clarity",
        "group": "the nearest character cluster establishes the group's immediate pressure",
        "environment": "foreground objects frame the location and lead into the space",
    }[subject_focus]


def _midground_for(subject_focus: str, basis: str) -> str:
    if subject_focus == "environment":
        return f"the main action sits inside the location: {basis}"
    return f"performance and blocking express the beat: {basis}"


def _background_for(scene_intent: str) -> str:
    return {
        "establishing": "background geography stays readable for orientation",
        "dialogue": "background stays quiet so relationship tension remains dominant",
        "action": "background preserves screen direction and impact context",
        "reaction": "background is restrained to protect the emotional pause",
        "transition": "background cues the next location or story movement",
    }[scene_intent]


def _lighting_for(emotion_tone: str) -> str:
    return {
        "anger": "hard contrast with controlled highlights",
        "sadness": "soft, low-key light with muted contrast",
        "joy": "open, warm light with clean facial readability",
        "tension": "narrow contrast and motivated shadow",
        "calm": "balanced natural light with low visual noise",
        "fear": "low-key light with threatening negative space",
        "surprise": "clear reveal light that isolates the reaction",
        "neutral": "clean motivated light with readable faces and space",
    }[emotion_tone]
