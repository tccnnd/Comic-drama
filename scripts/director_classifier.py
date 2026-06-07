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
VISUAL_PROTOTYPE_VERSION = 1
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
VISUAL_PROTOTYPE_IDS = {
    "danger_intro_extreme_closeup",
    "dialogue_pressure_two_shot",
    "reaction_hold_closeup",
    "power_dynamic_low_angle",
    "isolation_single_wide",
    "emotional_push_in",
    "lonely_establishing_wide",
    "impact_action_wide",
    "pursuit_forward_push",
    "transition_environment_insert",
}

EMPTY_PROTOTYPE_CONSTRAINTS = {"hard": [], "soft": [], "guidelines": []}
VISUAL_PROTOTYPE_CONSTRAINTS: dict[str, dict[str, list[str]]] = {
    "danger_intro_extreme_closeup": {
        "hard": ["object_dominates_frame", "shallow_background"],
        "soft": ["no_environment_pan", "minimal_handheld_motion"],
        "guidelines": ["color_contrast_between_object_and_background"],
    },
    "dialogue_pressure_two_shot": {
        "hard": ["preserve_eyelines", "keep_both_speakers_readable"],
        "soft": ["background_subordinate", "motivated_reframing_only"],
        "guidelines": ["separate_speakers_with_clear_screen_direction"],
    },
    "reaction_hold_closeup": {
        "hard": ["hold_performance_detail", "avoid_new_action"],
        "soft": ["background_subordinate", "minimal_camera_drift"],
        "guidelines": ["micro_expression_remains_readable"],
    },
    "power_dynamic_low_angle": {
        "hard": ["power_relation_visible", "dominant_subject_controls_frame"],
        "soft": ["avoid_flat_eye_level_staging", "background_reinforces_status"],
        "guidelines": ["subordinate_subject_has_less_frame_weight"],
    },
    "isolation_single_wide": {
        "hard": ["single_subject_visibly_isolated", "negative_space_readable"],
        "soft": ["environment_scale_supports_emotion", "avoid_crowded_background"],
        "guidelines": ["hold_long_enough_for_loneliness_to_register"],
    },
    "emotional_push_in": {
        "hard": ["push_in_motivated_by_emotional_turn", "face_or_decisive_prop_readable"],
        "soft": ["background_simplifies_during_push", "avoid_lateral_pan"],
        "guidelines": ["increase_pressure_without_overcutting"],
    },
    "lonely_establishing_wide": {
        "hard": ["environment_geography_readable"],
        "soft": ["character_scale_small_or_absent", "slow_reveal_only"],
        "guidelines": ["use_weather_or_light_to_support_mood"],
    },
    "impact_action_wide": {
        "hard": ["screen_direction_readable", "impact_context_visible"],
        "soft": ["avoid_abstract_motion", "keep_collision_or_contact_visible"],
        "guidelines": ["preserve_before_after_cause_effect"],
    },
    "pursuit_forward_push": {
        "hard": ["forward_vector_clear", "subject_leads_motion"],
        "soft": ["background_supports_speed", "avoid_confusing_axis_change"],
        "guidelines": ["motion_intensity_matches_stakes"],
    },
    "transition_environment_insert": {
        "hard": ["next_location_cue_clear"],
        "soft": ["no_new_character_business", "simple_composition"],
        "guidelines": ["use_insert_to_reset_rhythm"],
    },
}

DANGER_OBJECT_TERMS = (
    "雷管炸弹",
    "炸弹计时器",
    "雷管",
    "炸弹",
    "引信",
    "枪",
    "手枪",
    "刀",
    "匕首",
    "毒药",
    "detonator",
    "bomb timer",
    "bomb",
    "fuse",
    "gun",
    "knife",
    "weapon",
)

ENVIRONMENT_TERMS = (
    "废墟",
    "小巷",
    "街道",
    "车站",
    "屋顶",
    "雨夜",
    "ruins",
    "alley",
    "street",
    "station",
    "rooftop",
    "rain",
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
    dramatic_weight = _dramatic_weight(scene_intent, emotion_tone, pacing, visual)
    emotional_curve = _emotional_curve(scene_intent, emotion_tone, pacing)
    shot_archetypes = _director_shot_archetypes(
        scene_intent=scene_intent,
        emotion_tone=emotion_tone,
        pacing=pacing,
        subject_focus=subject_focus,
        visual_basis=visual,
        dramatic_weight=dramatic_weight,
    )
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
        "emotional_curve": emotional_curve,
        "dramatic_weight": dramatic_weight,
        "shot_archetypes": shot_archetypes,
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
    visual_prototype = build_visual_prototype(
        scene=scene,
        shot=shot,
        visual_basis=visual_basis,
        subject_focus=subject_focus,
        scene_intent=scene_intent,
        emotion_tone=emotion_tone,
        pacing=_validated_scene_value(scene, "pacing", VALID_PACING, "medium"),
        shot_size=shot_size,
        camera_movement=camera_movement,
        plan=plan,
    )
    if visual_prototype.get("mode") == "prototype_lock":
        visual_content = _prototype_visual_content(
            visual_basis=visual_basis,
            visual_prototype=visual_prototype,
            subject_focus=subject_focus,
            scene_intent=scene_intent,
            emotion_tone=emotion_tone,
            camera_language=camera_language,
        )
    else:
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
        "visual_prototype": visual_prototype,
        "visual_content": visual_content,
    }


def build_visual_prototype(
    *,
    scene: Any,
    shot: Any,
    visual_basis: str,
    subject_focus: str,
    scene_intent: str,
    emotion_tone: str,
    pacing: str,
    shot_size: str,
    camera_movement: str,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select and parameterize a shot prototype, or record a freeform gap."""
    plan = plan if isinstance(plan, dict) else build_director_plan(scene)
    selected_id = _select_shot_archetype(plan, shot, visual_basis, scene_intent, emotion_tone, subject_focus)
    params = {
        "object": _focus_object(scene, shot, visual_basis),
        "environment": _environment(scene, shot, visual_basis),
        "subject": _subject(scene, shot),
        "emotional_tone": emotion_tone,
        "shot_size": shot_size,
        "camera_movement": camera_movement,
    }

    if selected_id:
        return {
            "version": VISUAL_PROTOTYPE_VERSION,
            "mode": "prototype_lock",
            "id": selected_id,
            "params": params,
            "constraints": _prototype_constraints(selected_id),
            "source": "director_plan",
        }

    gap_reason = _prototype_gap_reason(scene_intent, emotion_tone, subject_focus, visual_basis, pacing)
    return {
        "version": VISUAL_PROTOTYPE_VERSION,
        "mode": "freeform",
        "id": "",
        "params": params,
        "constraints": dict(EMPTY_PROTOTYPE_CONSTRAINTS),
        "gap": {
            "reason": gap_reason,
            "candidate_basis": _shorten(visual_basis, 120),
            "scene_intent": scene_intent,
            "emotion_tone": emotion_tone,
            "subject_focus": subject_focus,
        },
        "source": "prototype_gap",
    }


def _dramatic_weight(scene_intent: str, emotion_tone: str, pacing: str, visual_basis: str) -> float:
    weight = {
        "dialogue": 0.56,
        "reaction": 0.62,
        "action": 0.72,
        "establishing": 0.48,
        "transition": 0.34,
    }[scene_intent]
    if emotion_tone in {"tension", "fear", "anger", "sadness", "surprise"}:
        weight += 0.14
    if pacing == "fast":
        weight += 0.08
    if _contains_any(visual_basis, DANGER_OBJECT_TERMS):
        weight += 0.18
    return round(min(1.0, weight), 2)


def _emotional_curve(scene_intent: str, emotion_tone: str, pacing: str) -> str:
    if scene_intent == "reaction":
        return "hold_consequence"
    if scene_intent == "dialogue" and emotion_tone in {"tension", "anger", "fear"}:
        return "pressure_rise"
    if scene_intent == "action" or pacing == "fast":
        return "impact_spike"
    if scene_intent == "establishing":
        return "orientation_to_mood"
    return "steady_readability"


def _director_shot_archetypes(
    *,
    scene_intent: str,
    emotion_tone: str,
    pacing: str,
    subject_focus: str,
    visual_basis: str,
    dramatic_weight: float,
) -> list[dict[str, Any]]:
    prototypes: list[tuple[str, str]] = []
    if scene_intent == "dialogue":
        prototypes.append(("dialogue_pressure_two_shot", "primary_dialogue_coverage"))
        if emotion_tone in {"tension", "anger", "fear", "sadness"} or dramatic_weight >= 0.7:
            prototypes.append(("reaction_hold_closeup", "listener_consequence"))
        if emotion_tone in {"tension", "anger"}:
            prototypes.append(("power_dynamic_low_angle", "status_pressure"))
    elif scene_intent == "reaction":
        prototypes.append(("reaction_hold_closeup", "primary_reaction"))
        if emotion_tone in {"tension", "fear", "sadness", "surprise"}:
            prototypes.append(("emotional_push_in", "emotional_turn"))
    elif scene_intent == "establishing" and subject_focus == "environment":
        prototypes.append(("isolation_single_wide", "spatial_mood"))
    elif scene_intent == "action":
        if _contains_any(visual_basis, DANGER_OBJECT_TERMS):
            prototypes.append(("danger_intro_extreme_closeup", "danger_object_reveal"))
        prototypes.append(("pursuit_forward_push" if pacing == "fast" else "impact_action_wide", "action_readability"))
    elif scene_intent == "transition":
        if dramatic_weight >= 0.5 or _contains_any(visual_basis, ENVIRONMENT_TERMS):
            prototypes.append(("transition_environment_insert", "location_reset"))

    if not prototypes and dramatic_weight >= 0.72:
        prototypes.append(("emotional_push_in", "high_weight_emotional_turn"))

    return [
        {
            "prototype_id": prototype_id,
            "role": role,
            "priority": index,
            "constraints": _prototype_constraints(prototype_id),
        }
        for index, (prototype_id, role) in enumerate(prototypes, start=1)
        if prototype_id in VISUAL_PROTOTYPE_IDS
    ]


def _select_shot_archetype(
    plan: dict[str, Any],
    shot: Any,
    visual_basis: str,
    scene_intent: str,
    emotion_tone: str,
    subject_focus: str,
) -> str:
    shot_archetypes = plan.get("shot_archetypes") if isinstance(plan, dict) else []
    candidates = [
        item.get("prototype_id")
        for item in shot_archetypes
        if isinstance(item, dict) and item.get("prototype_id") in VISUAL_PROTOTYPE_IDS
    ]
    if not candidates:
        return ""

    beat_type = str(_shot_get(shot, "beat_type", "") or _shot_get(shot, "label", "")).lower()
    if "reaction" in beat_type and "reaction_hold_closeup" in candidates:
        return "reaction_hold_closeup"
    if any(token in beat_type for token in ("detail", "insert", "object")) and "danger_intro_extreme_closeup" in candidates:
        return "danger_intro_extreme_closeup"
    if "dialogue" in beat_type and "dialogue_pressure_two_shot" in candidates:
        return "dialogue_pressure_two_shot"
    if _contains_any(visual_basis, DANGER_OBJECT_TERMS) and "danger_intro_extreme_closeup" in candidates:
        return "danger_intro_extreme_closeup"
    if scene_intent == "reaction" and "reaction_hold_closeup" in candidates:
        return "reaction_hold_closeup"
    if scene_intent == "dialogue" and subject_focus == "two_shot" and "dialogue_pressure_two_shot" in candidates:
        return "dialogue_pressure_two_shot"
    if emotion_tone in {"tension", "fear", "sadness", "anger"} and "emotional_push_in" in candidates:
        return "emotional_push_in"
    return candidates[0]


def _prototype_constraints(prototype_id: str) -> dict[str, list[str]]:
    constraints = VISUAL_PROTOTYPE_CONSTRAINTS.get(prototype_id, EMPTY_PROTOTYPE_CONSTRAINTS)
    return {key: list(constraints.get(key, [])) for key in ("hard", "soft", "guidelines")}


def _prototype_gap_reason(
    scene_intent: str,
    emotion_tone: str,
    subject_focus: str,
    visual_basis: str,
    pacing: str,
) -> str:
    if scene_intent == "transition" and pacing != "fast":
        return "low dramatic weight transition can remain freeform"
    if not _contains_any(visual_basis, (*DANGER_OBJECT_TERMS, *ENVIRONMENT_TERMS)) and emotion_tone in {"calm", "neutral", "joy"}:
        return "no prototype trigger matched calm low-risk scene"
    return f"no prototype matched {scene_intent}/{emotion_tone}/{subject_focus}"


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lower = str(text or "").lower()
    return any(term.lower() in lower for term in terms)


def _focus_object(scene: Any, shot: Any, visual_basis: str) -> str:
    explicit = _first_text(
        _shot_get(shot, "focus_object", ""),
        _shot_get(shot, "object", ""),
        _shot_get(shot, "prop", ""),
        _scene_get(scene, "focus_object", ""),
        _scene_get(scene, "object", ""),
        _scene_get(scene, "prop", ""),
    )
    if explicit:
        return explicit
    lower = str(visual_basis or "").lower()
    for term in DANGER_OBJECT_TERMS:
        if term.lower() in lower:
            return term
    return "the decisive visual subject"


def _environment(scene: Any, shot: Any, visual_basis: str) -> str:
    explicit = _first_text(
        _shot_get(shot, "environment", ""),
        _shot_get(shot, "location", ""),
        _scene_get(scene, "environment", ""),
        _scene_get(scene, "location", ""),
    )
    if explicit:
        return explicit
    lower = str(visual_basis or "").lower()
    for term in ENVIRONMENT_TERMS:
        if term.lower() in lower:
            return term
    return "the surrounding location"


def _subject(scene: Any, shot: Any) -> str:
    return _first_text(
        _shot_get(shot, "speaker", ""),
        _scene_get(scene, "speaker", ""),
        _scene_get(scene, "characters", []),
        "the primary character",
    )


def _prototype_visual_content(
    *,
    visual_basis: str,
    visual_prototype: dict[str, Any],
    subject_focus: str,
    scene_intent: str,
    emotion_tone: str,
    camera_language: dict[str, str],
) -> dict[str, str]:
    prototype_id = str(visual_prototype.get("id") or "")
    params = visual_prototype.get("params") if isinstance(visual_prototype.get("params"), dict) else {}
    focus_object = str(params.get("object") or "the decisive visual subject")
    environment = str(params.get("environment") or "the surrounding location")
    subject = str(params.get("subject") or "the primary character")
    basis = _shorten(visual_basis, 160)

    if prototype_id == "danger_intro_extreme_closeup":
        return {
            "shot_description": f"{focus_object} dominates the center of frame in {environment}; {basis}",
            "foreground": f"{focus_object} fills the foreground with readable surface, wiring, trigger, or fuse detail",
            "midground": "only the nearest hand or contact point may enter frame to clarify immediate threat",
            "background": f"{environment} stays blurred and subordinate so danger does not drift into atmosphere",
            "composition": "extreme close-up with object weight locked to the center or lower third",
            "motion": "minimal tremor or pressure push; no environment pan",
            "lighting": _lighting_for(emotion_tone),
            "focus": f"audience attention stays on {focus_object} as the active source of danger",
        }
    if prototype_id == "dialogue_pressure_two_shot":
        return {
            "shot_description": f"{subject} and the opposing speaker share a pressured two-shot; {basis}",
            "foreground": "both speakers keep readable eyelines and frame weight",
            "midground": "blocking makes the relationship pressure visible without losing either face",
            "background": "background stays quiet and does not compete with the conversation",
            "composition": "medium two-shot with clear screen direction and motivated reframing only",
            "motion": camera_language["movement"],
            "lighting": _lighting_for(emotion_tone),
            "focus": "audience attention stays on the spoken conflict and power shift between the speakers",
        }
    if prototype_id == "reaction_hold_closeup":
        return {
            "shot_description": f"hold on {subject}'s reaction after the dramatic beat; {basis}",
            "foreground": "face, eyes, or decisive hand detail carries the frame",
            "midground": "performance detail stays still enough for the reaction to register",
            "background": "background is restrained and subordinate to the emotional consequence",
            "composition": "close-up or tight medium close-up with the reaction protected",
            "motion": "locked or slow push that does not introduce new action",
            "lighting": _lighting_for(emotion_tone),
            "focus": f"audience attention stays on {subject}'s emotional consequence",
        }
    if prototype_id == "power_dynamic_low_angle":
        return {
            "shot_description": f"stage the power imbalance around {subject}; {basis}",
            "foreground": "dominant subject takes stronger frame weight",
            "midground": "subordinate subject or response position remains readable",
            "background": "background height, doorway, desk, or architecture reinforces status",
            "composition": "low-angle or high-angle relationship framing that makes rank visible",
            "motion": camera_language["movement"],
            "lighting": _lighting_for(emotion_tone),
            "focus": "audience attention stays on the change in status between characters",
        }
    if prototype_id == "isolation_single_wide":
        return {
            "shot_description": f"{subject} is isolated inside {environment}; {basis}",
            "foreground": "foreground objects frame emptiness without blocking the subject",
            "midground": "single subject remains small but legible inside the space",
            "background": "background geography and negative space stay readable",
            "composition": "wide frame with deliberate negative space",
            "motion": "slow reveal or locked frame; no busy camera move",
            "lighting": _lighting_for(emotion_tone),
            "focus": "audience attention stays on isolation, scale, and emotional distance",
        }
    if prototype_id == "emotional_push_in":
        return {
            "shot_description": f"slowly push toward {subject} or {focus_object} at the emotional turn; {basis}",
            "foreground": "the face, hand, or decisive object becomes progressively dominant",
            "midground": "surrounding blocking simplifies as pressure rises",
            "background": "background separation increases without distracting motion",
            "composition": "controlled push-in that tightens from relationship context to emotional detail",
            "motion": "motivated slow push-in, no lateral pan",
            "lighting": _lighting_for(emotion_tone),
            "focus": "audience attention stays on the exact moment emotion changes",
        }
    if prototype_id == "impact_action_wide":
        return {
            "shot_description": f"show the action impact with readable cause and effect; {basis}",
            "foreground": "nearest action edge leads the eye into the impact",
            "midground": "impact, collision, or decisive movement remains visible",
            "background": "background preserves screen direction and spatial context",
            "composition": "wide action frame with before-and-after geography",
            "motion": camera_language["movement"],
            "lighting": _lighting_for(emotion_tone),
            "focus": "audience attention stays on clear action causality",
        }
    if prototype_id == "pursuit_forward_push":
        return {
            "shot_description": f"drive forward through {environment} with pursuit pressure; {basis}",
            "foreground": "moving subject or obstacle leads the frame",
            "midground": "forward vector stays clear and readable",
            "background": "background supports speed without confusing the axis",
            "composition": "forward-facing pursuit frame with strong directional line",
            "motion": "forward push or chase movement matched to stakes",
            "lighting": _lighting_for(emotion_tone),
            "focus": "audience attention stays on urgency and direction of travel",
        }
    if prototype_id == "transition_environment_insert":
        return {
            "shot_description": f"insert {environment} as a clean cue into the next story beat; {basis}",
            "foreground": "simple location marker or prop anchors the transition",
            "midground": "no new character business competes with the location cue",
            "background": "next space remains immediately identifiable",
            "composition": "simple insert frame that resets rhythm",
            "motion": "brief locked shot or restrained reveal",
            "lighting": _lighting_for(emotion_tone),
            "focus": "audience attention stays on where the story is moving next",
        }

    return _visual_content(
        visual_basis=visual_basis,
        subject_focus=subject_focus,
        scene_intent=scene_intent,
        emotion_tone=emotion_tone,
        camera_language=camera_language,
    )


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
