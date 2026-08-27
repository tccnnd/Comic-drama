from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend.video_generation import normalize_generation_meta
from scripts.director_classifier import VISUAL_CONTENT_FIELDS, build_shot_visual_content
from scripts.rw_image import emotion_stamp, split_text_chunks
from scripts.rw_models import StoryScene
from scripts.rw_styles import normalize_episode_phase
from scripts.rw_utils import clamp
from scripts.rw_voice import split_dialogue_speaker


def build_scene_beats(
    scene: StoryScene, total_duration: float, spoken_text: str
) -> list[dict[str, object]]:
    speaker = scene.speaker or split_dialogue_speaker(scene.dialogue)[0] or "narrator"
    visual_chunks = split_text_chunks(scene.visual, 2)
    dialogue_chunks = split_text_chunks(spoken_text or scene.dialogue, 3)

    rhythm = (scene.rhythm_preset or "balanced").strip().lower()
    episode_rhythm = (scene.episode_rhythm or "classic_four_act").strip().lower().replace("-", "_")
    phase = normalize_episode_phase(scene.episode_phase, "setup")
    phase_weights = {
        "opening": (0.34, 0.26, 0.18, 0.22),
        "setup": (0.18, 0.42, 0.22, 0.18),
        "reversal": (0.14, 0.22, 0.42, 0.22),
        "finale": (0.16, 0.20, 0.22, 0.42),
    }
    weights = list(phase_weights.get(phase, phase_weights["setup"]))
    if episode_rhythm == "fast_hook" or rhythm == "fast":
        weights = [
            weights[0] + 0.06,
            max(0.12, weights[1] - 0.05),
            weights[2] + 0.04,
            max(0.12, weights[3] - 0.05),
        ]
    elif episode_rhythm == "slow_burn" or rhythm == "slow":
        weights = [
            max(0.12, weights[0] - 0.04),
            weights[1] + 0.08,
            max(0.12, weights[2] - 0.02),
            max(0.12, weights[3] - 0.02),
        ]
    elif rhythm == "dialogue":
        weights = [0.14, 0.54, 0.18, 0.14]
    elif rhythm == "suspense":
        weights = [0.16, 0.24, 0.38, 0.22]

    weight_total = sum(weights) or 1.0
    weights = [weight / weight_total for weight in weights]
    minimum = 0.45 if total_duration < 3.0 else 0.65
    durations = [max(minimum, float(total_duration) * weight) for weight in weights]
    if sum(durations) > total_duration:
        scale = max(0.25, float(total_duration)) / sum(durations)
        durations = [max(0.25, duration * scale) for duration in durations]
    durations[-1] = max(0.25, float(total_duration) - sum(durations[:-1]))
    intensity = clamp(float(scene.camera_intensity or 1.0), 0.5, 1.8)
    pacing = str(getattr(scene, "pacing", "") or "").strip().lower()
    emotion_tone = str(getattr(scene, "emotion_tone", "") or "").strip().lower()
    motion_boost = 1.0
    if pacing == "fast" or emotion_tone in {"anger", "fear", "tension", "surprise"}:
        motion_boost = 1.10
    elif pacing == "slow" or emotion_tone in {"sadness", "calm"}:
        motion_boost = 0.96

    def _zoom(value: float) -> float:
        return 1.0 + (value - 1.0) * intensity * motion_boost

    def _hold_ratios(label: str) -> tuple[float, float]:
        if label == "OPENING":
            hold_in, hold_out = 0.18, 0.18
        elif label == "SETUP":
            hold_in, hold_out = 0.12, 0.12
        elif label == "REVERSAL":
            hold_in, hold_out = 0.08, 0.10
        else:
            hold_in, hold_out = 0.10, 0.20
        if scene.camera == "dramatic_push":
            hold_in = min(hold_in, 0.08)
            hold_out = max(hold_out, 0.15)
        elif scene.camera in {"slow_push", "slow_push_in"}:
            hold_in = max(hold_in, 0.15)
            hold_out = max(hold_out, 0.15)
        elif scene.camera in {"melancholy_pan", "establishing_tilt"}:
            hold_in = max(hold_in, 0.10)
            hold_out = max(hold_out, 0.14)
        return hold_in, hold_out

    first_dialogue = dialogue_chunks[0] if dialogue_chunks else spoken_text
    middle_dialogue = dialogue_chunks[1] if len(dialogue_chunks) > 1 else first_dialogue
    final_dialogue = dialogue_chunks[-1] if dialogue_chunks else spoken_text
    visual_open = visual_chunks[0] if visual_chunks else scene.visual
    visual_setup = visual_chunks[-1] if visual_chunks else scene.visual
    phase_caption = f"{phase.upper()} {scene.episode_phase_index}/{scene.episode_phase_total}"
    opening_hold = _hold_ratios("OPENING")
    setup_hold = _hold_ratios("SETUP")
    reversal_hold = _hold_ratios("REVERSAL")
    finale_hold = _hold_ratios("FINALE")

    return [
        {
            "label": "OPENING",
            "beat_type": "OPENING",
            "caption": scene.title,
            "bubble": visual_open,
            "zoom": _zoom(1.05 if phase == "opening" else 1.07),
            "hold_in_ratio": opening_hold[0],
            "hold_out_ratio": opening_hold[1],
            "center_x": 0.50,
            "center_y": 0.42,
            "duration": durations[0],
        },
        {
            "label": "SETUP",
            "beat_type": "SETUP",
            "caption": speaker,
            "bubble": first_dialogue or visual_setup,
            "zoom": _zoom(1.15 if phase == "setup" else 1.12),
            "hold_in_ratio": setup_hold[0],
            "hold_out_ratio": setup_hold[1],
            "center_x": 0.52,
            "center_y": 0.50,
            "duration": durations[1],
        },
        {
            "label": "REVERSAL",
            "beat_type": "REVERSAL",
            "caption": emotion_stamp(scene.emotion) or "TURN",
            "bubble": middle_dialogue or final_dialogue or visual_setup,
            "zoom": _zoom(1.30 if phase == "reversal" else 1.23),
            "hold_in_ratio": reversal_hold[0],
            "hold_out_ratio": reversal_hold[1],
            "center_x": 0.56,
            "center_y": 0.60,
            "duration": durations[2],
        },
        {
            "label": "FINALE",
            "beat_type": "FINALE",
            "caption": phase_caption,
            "bubble": final_dialogue or visual_setup,
            "zoom": _zoom(1.36 if phase == "finale" else 1.27),
            "hold_in_ratio": finale_hold[0],
            "hold_out_ratio": finale_hold[1],
            "center_x": 0.54,
            "center_y": 0.56,
            "duration": durations[3],
        },
    ]


def build_scene_graph(scene: StoryScene) -> dict[str, object]:
    spoken_text = split_dialogue_speaker(scene.dialogue)[1] or scene.dialogue
    beat_specs = build_scene_beats(scene, float(scene.duration or 0.0), spoken_text)
    camera_track = {
        "movement": str(scene.camera_movement or scene.camera or "").strip(),
        "speed": float(scene.camera_speed or 1.0),
        "shot_count": len(beat_specs),
        "beat_labels": [str(beat.get("label") or "") for beat in beat_specs],
        "beat_types": [str(beat.get("beat_type") or "") for beat in beat_specs],
    }
    cursor = 0.0
    shots: list[dict[str, object]] = []
    for index, beat in enumerate(beat_specs, start=1):
        duration = max(0.25, float(beat.get("duration") or 0.0))
        shots.append(
            {
                "shot_id": f"scene_{scene.scene:03d}_shot_{index:02d}",
                "shot_order": index,
                "label": str(beat.get("label") or beat.get("beat_type") or f"SHOT {index}").strip(),
                "beat_type": str(beat.get("beat_type") or "").strip(),
                "title": str(scene.title or "").strip(),
                "caption": str(beat.get("caption") or "").strip(),
                "bubble": str(beat.get("bubble") or "").strip(),
                "start_seconds": round(cursor, 3),
                "duration_seconds": round(duration, 3),
                "end_seconds": round(min(float(scene.duration or 0.0), cursor + duration), 3),
                "camera_movement": str(scene.camera_movement or scene.camera or "").strip(),
                "camera_speed": float(scene.camera_speed or 1.0),
                "zoom": float(beat.get("zoom") or 1.0),
                "hold_in_ratio": float(beat.get("hold_in_ratio") or 0.0),
                "hold_out_ratio": float(beat.get("hold_out_ratio") or 0.0),
                "center_x": float(beat.get("center_x") or 0.5),
                "center_y": float(beat.get("center_y") or 0.5),
                "speaker": str(
                    scene.speaker or split_dialogue_speaker(scene.dialogue)[0] or ""
                ).strip(),
                "dialogue": spoken_text.strip(),
                "emotion": str(scene.emotion_tone or scene.emotion or "").strip(),
                "scene_intent": str(scene.scene_intent or "").strip(),
                "subject_focus": str(scene.subject_focus or "").strip(),
            }
        )
        cursor += duration
    return {"camera_track": camera_track, "shots": shots}


def build_scene_temporal_spec(
    scene: StoryScene, duration: float, *, width: int = 1080, height: int = 1920, fps: int = 24
) -> dict[str, Any]:
    graph = deepcopy(build_scene_graph(scene))
    shots: list[dict[str, Any]] = []
    for raw in graph.get("shots", []) or []:
        if not isinstance(raw, dict):
            continue
        shots.append(
            {
                "shot_id": raw.get("shot_id"),
                "shot_order": raw.get("shot_order"),
                "label": raw.get("label"),
                "beat_type": raw.get("beat_type"),
                "start_seconds": raw.get("start_seconds"),
                "duration_seconds": raw.get("duration_seconds"),
                "end_seconds": raw.get("end_seconds"),
                "camera_movement": raw.get("camera_movement"),
                "camera_speed": raw.get("camera_speed"),
                "zoom": raw.get("zoom"),
                "hold_in_ratio": raw.get("hold_in_ratio"),
                "hold_out_ratio": raw.get("hold_out_ratio"),
                "center_x": raw.get("center_x"),
                "center_y": raw.get("center_y"),
                "caption": raw.get("caption"),
                "bubble": raw.get("bubble"),
                "speaker": raw.get("speaker"),
                "dialogue": raw.get("dialogue"),
                "emotion": raw.get("emotion"),
                "scene_intent": raw.get("scene_intent"),
                "subject_focus": raw.get("subject_focus"),
            }
        )
    return {
        "version": 1,
        "kind": "scene_temporal_video_spec",
        "scene": scene.scene,
        "title": scene.title,
        "duration_seconds": round(float(duration or scene.duration or 0.0), 3),
        "size": {"width": int(width), "height": int(height), "fps": int(fps)},
        "camera_track": graph.get("camera_track") or {},
        "shots": shots,
        "continuity_rules": {
            "generate_continuous_video": True,
            "avoid_static_pan_only_motion": True,
            "preserve_character_environment_contact": True,
            "preserve_lighting_direction": True,
            "preserve_scene_geometry": True,
        },
    }


def _timeline_scene_field(scene: dict[str, Any], key: str, default: Any = "") -> Any:
    if isinstance(scene, dict) and key in scene:
        value = scene.get(key)
        if value not in (None, ""):
            return value
    assets = (
        scene.get("assets")
        if isinstance(scene, dict) and isinstance(scene.get("assets"), dict)
        else {}
    )
    if isinstance(assets, dict) and key in assets:
        value = assets.get(key)
        if value not in (None, ""):
            return value
    return default


def _scene_media_reference(scene: dict[str, Any], kind: str) -> dict[str, str]:
    if kind == "image":
        path = str(
            _timeline_scene_field(scene, "keyframe", "")
            or _timeline_scene_field(scene, "image_path", "")
            or _timeline_scene_field(scene, "primary_reference_image_path", "")
        ).strip()
        url = str(
            _timeline_scene_field(scene, "keyframe_url", "")
            or _timeline_scene_field(scene, "image_url", "")
            or _timeline_scene_field(scene, "primary_reference_image_url", "")
        ).strip()
    elif kind == "audio":
        path = str(
            _timeline_scene_field(scene, "voice", "")
            or _timeline_scene_field(scene, "audio_path", "")
            or _timeline_scene_field(scene, "reference_audio_path", "")
        ).strip()
        url = str(
            _timeline_scene_field(scene, "voice_url", "")
            or _timeline_scene_field(scene, "audio_url", "")
            or _timeline_scene_field(scene, "reference_audio_url", "")
        ).strip()
    elif kind == "video":
        path = str(
            _timeline_scene_field(scene, "video", "")
            or _timeline_scene_field(scene, "video_path", "")
            or _timeline_scene_field(scene, "final_video_path", "")
        ).strip()
        url = str(
            _timeline_scene_field(scene, "video_url", "")
            or _timeline_scene_field(scene, "final_video_url", "")
        ).strip()
    else:
        path = str(
            _timeline_scene_field(scene, "subtitle_path", "")
            or _timeline_scene_field(scene, "subtitles_path", "")
        ).strip()
        url = str(
            _timeline_scene_field(scene, "subtitle_url", "")
            or _timeline_scene_field(scene, "subtitles_url", "")
        ).strip()
    return {"path": path, "url": url}


def _scene_duration_seconds(scene: dict[str, Any]) -> float:
    duration = (
        scene.get("duration_seconds")
        or scene.get("clip_duration")
        or scene.get("voice_duration")
        or 0.0
    )
    try:
        return round(max(0.25, float(duration)), 3)
    except (TypeError, ValueError):
        return 4.0


def normalize_shot_plan_visual_content(
    scene: dict[str, Any], shot_plan: dict[str, Any]
) -> dict[str, Any]:
    """Ensure each shot carries the additive director-interpretation fields."""
    if not isinstance(scene, dict):
        scene = {}
    if not isinstance(shot_plan, dict):
        return shot_plan
    shots = shot_plan.get("shots")
    if not isinstance(shots, list):
        return shot_plan

    for shot in shots:
        if not isinstance(shot, dict):
            continue
        generated = build_shot_visual_content(scene, shot)

        if not str(shot.get("shot_size") or "").strip():
            shot["shot_size"] = generated["shot_size"]
        if not str(shot.get("dramatic_intent") or "").strip():
            shot["dramatic_intent"] = generated["dramatic_intent"]

        visual_prototype = shot.get("visual_prototype")
        if not isinstance(visual_prototype, dict):
            visual_prototype = {}
        shot["visual_prototype"] = _merge_default_dict(
            generated["visual_prototype"], visual_prototype
        )

        camera_language = shot.get("camera_language")
        if not isinstance(camera_language, dict):
            camera_language = {}
        shot["camera_language"] = _merge_default_dict(generated["camera_language"], camera_language)

        visual_content = shot.get("visual_content")
        if not isinstance(visual_content, dict):
            visual_content = {}
        elif "_source" not in visual_content and any(
            str(visual_content.get(key) or "").strip() for key in VISUAL_CONTENT_FIELDS
        ):
            visual_content = {**visual_content, "_source": "legacy"}
        shot["visual_content"] = _merge_default_dict(generated["visual_content"], visual_content)

    return shot_plan


def _merge_default_dict(defaults: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(defaults)
    for key, value in current.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        merged[key] = deepcopy(value)
    return merged


def build_shot_plan(scene: dict[str, Any]) -> dict[str, Any]:
    """Build the persisted, scene-relative shot plan contract for a scene."""
    if not isinstance(scene, dict):
        scene = {}
    order = int(scene.get("order") or scene.get("scene") or 1)
    scene_id = str(scene.get("scene_id") or f"scene_{order:03d}").strip()
    duration = _scene_duration_seconds(scene)
    temporal_spec = (
        scene.get("temporal_spec") if isinstance(scene.get("temporal_spec"), dict) else {}
    )
    shots_source = temporal_spec.get("shots") if isinstance(temporal_spec, dict) else None
    if not isinstance(shots_source, list) or not shots_source:
        shots_source = []
    source = "temporal_spec" if shots_source else "synthesized"

    shot_timeline: list[dict[str, Any]] = []
    cursor = 0.0
    for shot_index, raw_shot in enumerate(shots_source or [], start=1):
        if not isinstance(raw_shot, dict):
            continue
        try:
            raw_duration = float(
                raw_shot.get("duration_seconds") or raw_shot.get("duration") or 0.0
            )
        except (TypeError, ValueError):
            raw_duration = 0.0
        shot_duration = max(0.25, raw_duration)
        shot_start = round(cursor, 3)
        shot_end = round(shot_start + shot_duration, 3)
        shot_timeline.append(
            {
                "shot_id": str(raw_shot.get("shot_id") or f"{scene_id}_shot_{shot_index:02d}"),
                "shot_order": int(raw_shot.get("shot_order") or shot_index),
                "label": str(
                    raw_shot.get("label") or raw_shot.get("beat_type") or f"SHOT {shot_index}"
                ).strip(),
                "beat_type": str(raw_shot.get("beat_type") or "").strip(),
                "start_seconds": shot_start,
                "duration_seconds": round(shot_duration, 3),
                "end_seconds": shot_end,
                "camera_movement": str(
                    raw_shot.get("camera_movement")
                    or scene.get("camera_movement")
                    or scene.get("camera")
                    or ""
                ).strip(),
                "camera_speed": float(
                    raw_shot.get("camera_speed") or scene.get("camera_speed") or 1.0
                ),
                "zoom": float(raw_shot.get("zoom") or 1.0),
                "hold_in_ratio": float(raw_shot.get("hold_in_ratio") or 0.0),
                "hold_out_ratio": float(raw_shot.get("hold_out_ratio") or 0.0),
                "center_x": float(raw_shot.get("center_x") or 0.5),
                "center_y": float(raw_shot.get("center_y") or 0.5),
                "speaker": str(raw_shot.get("speaker") or scene.get("speaker") or "").strip(),
                "dialogue": str(raw_shot.get("dialogue") or scene.get("dialogue") or "").strip(),
                "emotion": str(
                    raw_shot.get("emotion")
                    or scene.get("emotion_tone")
                    or scene.get("emotion")
                    or ""
                ).strip(),
                "scene_intent": str(
                    raw_shot.get("scene_intent") or scene.get("scene_intent") or ""
                ).strip(),
                "subject_focus": str(
                    raw_shot.get("subject_focus") or scene.get("subject_focus") or ""
                ).strip(),
            }
        )
        cursor += shot_duration

    if shot_timeline:
        total_shot_duration = sum(
            float(shot.get("duration_seconds") or 0.0) for shot in shot_timeline
        )
        if total_shot_duration > 0.0 and abs(total_shot_duration - duration) > 0.001:
            scale = duration / total_shot_duration
            cursor = 0.0
            for shot_index, shot in enumerate(shot_timeline):
                shot_start = round(cursor, 3)
                if shot_index == len(shot_timeline) - 1:
                    shot_duration = max(0.001, round(duration - cursor, 3))
                else:
                    shot_duration = max(
                        0.001, round(float(shot.get("duration_seconds") or 0.0) * scale, 3)
                    )
                shot["start_seconds"] = shot_start
                shot["duration_seconds"] = shot_duration
                shot["end_seconds"] = round(shot_start + shot_duration, 3)
                cursor += shot_duration

    if not shot_timeline:
        shot_timeline.append(
            {
                "shot_id": f"{scene_id}_shot_01",
                "shot_order": 1,
                "label": "SHOT 1",
                "beat_type": "",
                "start_seconds": 0.0,
                "duration_seconds": duration,
                "end_seconds": duration,
                "camera_movement": str(
                    scene.get("camera_movement") or scene.get("camera") or ""
                ).strip(),
                "camera_speed": float(scene.get("camera_speed") or 1.0),
                "zoom": 1.0,
                "hold_in_ratio": 0.0,
                "hold_out_ratio": 0.0,
                "center_x": 0.5,
                "center_y": 0.5,
                "speaker": str(scene.get("speaker") or "").strip(),
                "dialogue": str(scene.get("dialogue") or "").strip(),
                "emotion": str(scene.get("emotion_tone") or scene.get("emotion") or "").strip(),
                "scene_intent": str(scene.get("scene_intent") or "").strip(),
                "subject_focus": str(scene.get("subject_focus") or "").strip(),
            }
        )
        source = "synthesized"

    shot_plan = {
        "version": 1,
        "scene_id": scene_id,
        "scene_order": order,
        "duration_seconds": duration,
        "shot_count": len(shot_timeline),
        "source": source,
        "shots": shot_timeline,
    }
    return normalize_shot_plan_visual_content(scene, shot_plan)


def _compact_shot_generation(output: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {}
    fields = (
        "shot_id",
        "index",
        "status",
        "provider_id",
        "provider_label",
        "backend",
        "model",
        "path",
        "duration_seconds",
        "target_duration_seconds",
        "attempts",
        "fallback_used",
        "warnings",
        "error",
        "cache_key",
    )
    compact = {key: deepcopy(output.get(key)) for key in fields if key in output}
    return {key: value for key, value in compact.items() if value not in ("", [], {}, None)}


def _shot_timeline_with_generation(
    shot_timeline: list[dict[str, Any]], generation_meta: dict[str, Any]
) -> list[dict[str, Any]]:
    shot_outputs = generation_meta.get("shot_outputs") if isinstance(generation_meta, dict) else []
    if not isinstance(shot_outputs, list) or not shot_outputs:
        return shot_timeline
    outputs_by_id: dict[str, dict[str, Any]] = {}
    outputs_by_index: dict[int, dict[str, Any]] = {}
    for fallback_index, output in enumerate(shot_outputs, start=1):
        if not isinstance(output, dict):
            continue
        shot_id = str(output.get("shot_id") or "").strip()
        if shot_id:
            outputs_by_id[shot_id] = output
        try:
            output_index = int(output.get("index") or fallback_index)
        except (TypeError, ValueError):
            output_index = fallback_index
        outputs_by_index[output_index] = output
    enriched: list[dict[str, Any]] = []
    for fallback_index, shot in enumerate(shot_timeline, start=1):
        if not isinstance(shot, dict):
            continue
        item = deepcopy(shot)
        shot_id = str(item.get("shot_id") or "").strip()
        output = outputs_by_id.get(shot_id) or outputs_by_index.get(fallback_index)
        if isinstance(output, dict):
            item["generation"] = _compact_shot_generation(output)
        enriched.append(item)
    return enriched


def build_canonical_timeline(project: dict[str, Any]) -> dict[str, Any]:
    scenes_raw = project.get("scenes", []) if isinstance(project, dict) else []
    scenes: list[dict[str, Any]] = [scene for scene in scenes_raw if isinstance(scene, dict)]
    scenes.sort(key=lambda scene: int(scene.get("order") or 0))

    project_id = str(project.get("project_id") or "").strip() if isinstance(project, dict) else ""
    title = str(project.get("title") or "").strip() if isinstance(project, dict) else ""
    settings = (
        project.get("settings")
        if isinstance(project, dict) and isinstance(project.get("settings"), dict)
        else {}
    )
    size = {"width": 1080, "height": 1920, "fps": 24}
    total_duration = 0.0
    picture_items: list[dict[str, Any]] = []
    audio_items: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    scene_index: list[dict[str, Any]] = []
    real_video_scene_count = 0
    fallback_scene_count = 0

    for index, scene in enumerate(scenes, start=1):
        order = int(scene.get("order") or index)
        scene_id = str(scene.get("scene_id") or f"scene_{order:03d}").strip()
        scene_title = str(scene.get("title") or f"Scene {order}").strip()
        duration = _scene_duration_seconds(scene)
        start_seconds = round(total_duration, 3)
        end_seconds = round(start_seconds + duration, 3)
        total_duration = end_seconds
        temporal_spec = (
            scene.get("temporal_spec") if isinstance(scene.get("temporal_spec"), dict) else {}
        )
        shot_plan = build_shot_plan(scene)
        video_ref = _scene_media_reference(scene, "video")
        image_ref = _scene_media_reference(scene, "image")
        picture_ref = video_ref if video_ref.get("path") or video_ref.get("url") else image_ref
        generation_meta = normalize_generation_meta(scene.get("generation_meta"))
        shot_timeline = _shot_timeline_with_generation(
            deepcopy(shot_plan.get("shots") or []), generation_meta
        )
        if generation_meta.get("is_real_video") is True:
            real_video_scene_count += 1
        if generation_meta.get("fallback_used") is True:
            fallback_scene_count += 1
        picture_item = {
            "item_type": "clip",
            "clip_id": f"{scene_id}_picture",
            "scene_id": scene_id,
            "scene_order": order,
            "name": scene_title,
            "start_seconds": start_seconds,
            "duration_seconds": duration,
            "end_seconds": end_seconds,
            "source_range": {"start_seconds": 0.0, "duration_seconds": duration},
            "media_reference": picture_ref,
            "metadata": {
                "emotion_tone": str(
                    scene.get("emotion_tone") or scene.get("emotion") or ""
                ).strip(),
                "pacing": str(scene.get("pacing") or "").strip(),
                "camera_movement": str(
                    scene.get("camera_movement") or scene.get("camera") or ""
                ).strip(),
                "scene_intent": str(scene.get("scene_intent") or "").strip(),
                "subject_focus": str(scene.get("subject_focus") or "").strip(),
                "production_bible": (
                    deepcopy(scene.get("production_bible") or {})
                    if isinstance(scene.get("production_bible"), dict)
                    else {}
                ),
                "temporal_spec": deepcopy(temporal_spec) if isinstance(temporal_spec, dict) else {},
                "shot_plan_source": str(shot_plan.get("source") or "").strip(),
                "generation": generation_meta,
            },
            "shot_timeline": shot_timeline,
        }
        audio_item = {
            "item_type": "clip",
            "clip_id": f"{scene_id}_audio",
            "scene_id": scene_id,
            "scene_order": order,
            "name": scene_title,
            "start_seconds": start_seconds,
            "duration_seconds": duration,
            "end_seconds": end_seconds,
            "source_range": {"start_seconds": 0.0, "duration_seconds": duration},
            "media_reference": _scene_media_reference(scene, "audio"),
            "metadata": {
                "speaker": str(scene.get("speaker") or "").strip(),
                "voice_profile": str(scene.get("voice_profile") or "").strip(),
                "voice_engine": str(scene.get("voice_engine") or "").strip(),
                "voice_id": str(scene.get("voice_id") or "").strip(),
                "emotion_tone": str(
                    scene.get("emotion_tone") or scene.get("emotion") or ""
                ).strip(),
            },
        }
        picture_items.append(picture_item)
        audio_items.append(audio_item)
        scene_index.append(
            {
                "scene_id": scene_id,
                "scene_order": order,
                "title": scene_title,
                "clip_id": picture_item["clip_id"],
                "shot_count": len(shot_timeline),
                "start_seconds": start_seconds,
                "duration_seconds": duration,
                "end_seconds": end_seconds,
            }
        )
        if index < len(scenes):
            next_scene = scenes[index]
            next_order = int(next_scene.get("order") or index + 1)
            next_scene_id = str(next_scene.get("scene_id") or f"scene_{next_order:03d}").strip()
            from scripts.run_workflow import _scene_transition

            transition_kind = _scene_transition(
                scene.get("emotion_tone") or scene.get("emotion") or "",
                next_scene.get("emotion_tone") or next_scene.get("emotion") or "",
            )
            transition_duration = (
                0.0 if transition_kind == "cut" else 0.2 if transition_kind == "xfade" else 0.3
            )
            transitions.append(
                {
                    "transition_id": f"{scene_id}_to_{next_scene_id}",
                    "from_scene_id": scene_id,
                    "to_scene_id": next_scene_id,
                    "from_order": order,
                    "to_order": next_order,
                    "kind": transition_kind,
                    "duration_seconds": transition_duration,
                }
            )

    return {
        "version": 1,
        "kind": "canonical_timeline",
        "schema": "otio-inspired",
        "project_id": project_id,
        "title": title or "Storyboard Timeline",
        "frame_rate": int(size["fps"]),
        "resolution": {"width": int(size["width"]), "height": int(size["height"])},
        "duration_seconds": round(total_duration, 3),
        "scene_count": len(scene_index),
        "shot_count": sum(len(item.get("shot_timeline") or []) for item in picture_items),
        "summary": {
            "scene_count": len(scene_index),
            "shot_count": sum(len(item.get("shot_timeline") or []) for item in picture_items),
            "transition_count": len(transitions),
            "real_video_scene_count": real_video_scene_count,
            "fallback_scene_count": fallback_scene_count,
        },
        "metadata": {
            "project_id": project_id,
            "title": title,
            "style_id": (
                str(project.get("style_id") or "").strip() if isinstance(project, dict) else ""
            ),
            "episode_pacing": (
                deepcopy(settings.get("episode_pacing"))
                if isinstance(settings.get("episode_pacing"), dict)
                else {}
            ),
            "production_bible": (
                deepcopy(project.get("production_bible") or {})
                if isinstance(project, dict) and isinstance(project.get("production_bible"), dict)
                else {}
            ),
        },
        "tracks": [
            {
                "track_id": "picture",
                "track_type": "video",
                "name": "Picture",
                "children": picture_items,
            },
            {
                "track_id": "dialogue",
                "track_type": "audio",
                "name": "Dialogue",
                "children": audio_items,
            },
        ],
        "transitions": transitions,
        "scene_index": scene_index,
    }
