"""Scene graph, timeline, production bible, and director recommendation logic."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from scripts.run_workflow import (
    StoryScene,
    build_scene_graph,
    build_canonical_timeline,
)

from backend.project_models import (
    _scene_from_payload,
    project_relative_file_exists,
    workspace_url,
)


def _scene_subtitle_path(scene_order: int, scene_id: str) -> str:
    return f"scenes/{scene_id}/scene_{scene_order:02d}_dialogue.srt"


def _scene_audio_ref(scene: StoryScene | dict[str, Any], project_id: str, scene_order: int, scene_id: str) -> dict[str, Any]:
    payload = scene if isinstance(scene, dict) else {}
    assets = payload.get("assets", {}) if isinstance(payload, dict) else {}
    audio_path = ""
    audio_url = ""
    if isinstance(assets, dict):
        audio_path = str(assets.get("audio_path") or "").strip()
        audio_url = str(assets.get("audio_url") or "").strip()
    if not audio_path and isinstance(scene, StoryScene):
        audio_path = str(scene.reference_audio_path or "").strip()
    if not audio_path and isinstance(payload, dict):
        audio_path = str(payload.get("reference_audio_path") or "").strip()
    if not audio_url and project_id and audio_path and project_relative_file_exists(project_id, audio_path):
        audio_url = workspace_url(project_id, audio_path)
    return {
        "kind": "scene_audio",
        "scene_id": scene_id,
        "scene_order": scene_order,
        "path": audio_path,
        "url": audio_url,
        "reference_audio_path": str(getattr(scene, "reference_audio_path", "") or payload.get("reference_audio_path") or "").strip(),
        "voice_id": str(getattr(scene, "voice_id", "") or payload.get("voice_id") or "").strip(),
        "voice_profile": str(getattr(scene, "voice_profile", "") or payload.get("voice_profile") or "").strip(),
    }


def _scene_subtitle_ref(project_id: str, scene_order: int, scene_id: str) -> dict[str, Any]:
    path = _scene_subtitle_path(scene_order, scene_id)
    url = workspace_url(project_id, path) if project_id and project_relative_file_exists(project_id, path) else ""
    return {
        "kind": "scene_subtitle",
        "scene_id": scene_id,
        "scene_order": scene_order,
        "path": path,
        "url": url,
    }


def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _shot_override_key(override: dict[str, Any]) -> str:
    shot_id = str(override.get("shot_id") or "").strip()
    if shot_id:
        return f"id:{shot_id}"
    try:
        return f"order:{int(override.get('shot_order') or 0)}"
    except (TypeError, ValueError):
        return "order:0"


def _normalize_shot_overrides(overrides: Any) -> list[dict[str, Any]]:
    if not isinstance(overrides, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in overrides:
        if not isinstance(item, dict):
            continue
        try:
            shot_order = int(item.get("shot_order") or 0)
        except (TypeError, ValueError):
            shot_order = 0
        shot_id = str(item.get("shot_id") or "").strip()
        if shot_order <= 0 and not shot_id:
            continue
        payload: dict[str, Any] = {}
        if shot_id:
            payload["shot_id"] = shot_id
        if shot_order > 0:
            payload["shot_order"] = shot_order
        for key in ("label", "caption", "bubble", "camera_movement"):
            value = str(item.get(key) or "").strip()
            if value:
                payload[key] = value
        numeric_bounds = {
            "duration_seconds": (0.25, 120.0),
            "camera_speed": (0.1, 5.0),
            "zoom": (1.0, 3.0),
            "hold_in_ratio": (0.0, 0.45),
            "hold_out_ratio": (0.0, 0.45),
            "center_x": (0.0, 1.0),
            "center_y": (0.0, 1.0),
        }
        for key, bounds in numeric_bounds.items():
            if key in item and item.get(key) not in (None, ""):
                payload[key] = _bounded_float(item.get(key), bounds[0], bounds[0], bounds[1])
        normalized.append(payload)
    return normalized


def _apply_shot_overrides_to_graph(graph: dict[str, Any], overrides: Any) -> dict[str, Any]:
    normalized = _normalize_shot_overrides(overrides)
    if not normalized:
        graph["shot_overrides"] = []
        return graph
    by_key = {_shot_override_key(item): item for item in normalized}
    shots = [deepcopy(shot) for shot in graph.get("shots", []) or [] if isinstance(shot, dict)]
    if not shots:
        graph["shot_overrides"] = normalized
        return graph
    for shot in shots:
        key = f"id:{str(shot.get('shot_id') or '').strip()}"
        override = by_key.get(key)
        if override is None:
            override = by_key.get(f"order:{int(shot.get('shot_order') or 0)}")
        if not override:
            continue
        for text_key in ("label", "caption", "bubble", "camera_movement"):
            if text_key in override:
                shot[text_key] = override[text_key]
        for number_key in (
            "duration_seconds",
            "camera_speed",
            "zoom",
            "hold_in_ratio",
            "hold_out_ratio",
            "center_x",
            "center_y",
        ):
            if number_key in override:
                shot[number_key] = override[number_key]
        shot["has_override"] = True
    cursor = 0.0
    for shot in shots:
        duration = max(0.25, float(shot.get("duration_seconds") or 0.25))
        shot["start_seconds"] = round(cursor, 3)
        shot["duration_seconds"] = round(duration, 3)
        cursor += duration
        shot["end_seconds"] = round(cursor, 3)
    graph["shots"] = shots
    graph["shot_overrides"] = normalized
    camera_track = deepcopy(graph.get("camera_track") or {})
    camera_track["shot_count"] = len(shots)
    camera_track["duration_seconds"] = round(cursor, 3)
    graph["camera_track"] = camera_track
    return graph


def _scene_graph_payload(
    scene: StoryScene | dict[str, Any],
    order: int,
    *,
    project_id: str = "",
) -> dict[str, Any]:
    if isinstance(scene, dict):
        scene_obj = _scene_from_payload(scene)
        payload_scene: dict[str, Any] = scene
    else:
        scene_obj = scene
        payload_scene = {}
    scene_order = int(payload_scene.get("order") or order) if isinstance(payload_scene, dict) else order
    scene_id = str(payload_scene.get("scene_id") or f"scene_{scene_order:03d}") if isinstance(payload_scene, dict) else f"scene_{scene_order:03d}"
    graph = deepcopy(build_scene_graph(scene_obj))
    graph = _apply_shot_overrides_to_graph(graph, payload_scene.get("shot_overrides") if isinstance(payload_scene, dict) else [])
    audio_ref = _scene_audio_ref(scene_obj, project_id, scene_order, scene_id)
    subtitle_ref = _scene_subtitle_ref(project_id, scene_order, scene_id)
    shots: list[dict[str, Any]] = []
    for shot in graph.get("shots", []) or []:
        shot_payload = deepcopy(shot) if isinstance(shot, dict) else {}
        shot_payload["scene_id"] = scene_id
        shot_payload["scene_order"] = scene_order
        shot_payload["audio_ref"] = deepcopy(audio_ref)
        shot_payload["subtitle_ref"] = deepcopy(subtitle_ref)
        shots.append(shot_payload)
    graph["shots"] = shots
    graph["camera_track"] = {
        **deepcopy(graph.get("camera_track") or {}),
        "movement": str(scene_obj.camera_movement or scene_obj.camera or "").strip(),
        "speed": float(scene_obj.camera_speed or 1.0),
        "shot_count": len(shots),
    }
    graph["production_bible"] = deepcopy(payload_scene.get("production_bible") or {}) if isinstance(payload_scene, dict) else {}
    graph["temporal_spec"] = deepcopy(payload_scene.get("temporal_spec") or {}) if isinstance(payload_scene, dict) else {}
    if isinstance(payload_scene, dict) and payload_scene.get("shot_overrides"):
        total_duration = float(graph["camera_track"].get("duration_seconds") or sum(float(shot.get("duration_seconds") or 0.0) for shot in shots))
        payload_scene["duration_seconds"] = round(total_duration, 3)
    return graph


def _apply_scene_graph(scene: dict[str, Any], graph: dict[str, Any]) -> None:
    scene["camera_track"] = deepcopy(graph.get("camera_track") or {})
    scene["shots"] = deepcopy(graph.get("shots") or [])
    scene["shot_count"] = len(scene["shots"])
    scene["shot_overrides"] = deepcopy(graph.get("shot_overrides") or [])
    scene["production_bible"] = deepcopy(graph.get("production_bible") or {})
    scene["temporal_spec"] = deepcopy(graph.get("temporal_spec") or {})


def _refresh_project_scene_graph(project: dict[str, Any], *, project_id: str = "") -> None:
    from backend.character_manager import scene_with_character_context

    scenes = project.get("scenes", [])
    if not isinstance(scenes, list):
        return
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            continue
        scene_order = int(scene.get("order") or index)
        scene_context = scene_with_character_context(project, scene)
        graph = _scene_graph_payload(scene_context, scene_order, project_id=project_id)
        _apply_scene_graph(scene, graph)
    project["production_bible"] = build_production_bible(project)
    project["canonical_timeline"] = build_canonical_timeline(project)


def build_production_bible(project: dict[str, Any]) -> dict[str, Any]:
    characters: list[dict[str, Any]] = []
    for character in project.get("characters", []) or []:
        if not isinstance(character, dict):
            continue
        characters.append(
            {
                "name": str(character.get("name") or "").strip(),
                "char_id": str(character.get("char_id") or "").strip(),
                "description": str(character.get("description") or character.get("summary") or "").strip(),
                "appearance_core": str(character.get("appearance_core") or "").strip(),
                "clothing_style": str(character.get("clothing_style") or "").strip(),
                "negative_constraints": str(character.get("negative_constraints") or "").strip(),
                "reference_image_path": str(character.get("reference_image_path") or "").strip(),
                "reference_meta": deepcopy(character.get("reference_meta")) if isinstance(character.get("reference_meta"), dict) else {},
            }
        )
    scenes: list[dict[str, Any]] = []
    for scene in project.get("scenes", []) or []:
        if not isinstance(scene, dict):
            continue
        scenes.append(
            {
                "scene_id": str(scene.get("scene_id") or "").strip(),
                "order": int(scene.get("order") or len(scenes) + 1),
                "title": str(scene.get("title") or "").strip(),
                "emotion_tone": str(scene.get("emotion_tone") or scene.get("emotion") or "").strip(),
                "pacing": str(scene.get("pacing") or "").strip(),
                "scene_intent": str(scene.get("scene_intent") or "").strip(),
                "subject_focus": str(scene.get("subject_focus") or "").strip(),
                "characters": [str(name).strip() for name in scene.get("characters") or [] if str(name).strip()],
            }
        )
    settings = project.get("settings") if isinstance(project.get("settings"), dict) else {}
    return {
        "version": 1,
        "project_id": str(project.get("project_id") or "").strip(),
        "title": str(project.get("title") or "").strip(),
        "style_id": str(project.get("style_id") or "").strip(),
        "style_guide": str(project.get("style_guide") or "").strip(),
        "global_style": str(settings.get("global_style") or "").strip(),
        "characters": characters,
        "scene_continuity": scenes,
        "rules": {
            "preserve_character_identity": True,
            "preserve_costume_per_scene": True,
            "keep_lighting_continuous_within_scene": True,
            "keep_environment_geometry_stable": True,
            "avoid_identity_drift": True,
            "avoid_unmotivated_camera_jumps": True,
        },
    }


def scene_production_bible(project: dict[str, Any], scene: dict[str, Any], refs: list[dict[str, Any]]) -> dict[str, Any]:
    bible = build_production_bible(project)
    scene_order = int(scene.get("order") or 0)
    bible["current_scene"] = {
        "scene_id": str(scene.get("scene_id") or f"scene_{scene_order:03d}"),
        "order": scene_order,
        "title": str(scene.get("title") or "").strip(),
        "visual_prompt": str(scene.get("visual_prompt") or "").strip(),
        "emotion_tone": str(scene.get("emotion_tone") or scene.get("emotion") or "").strip(),
        "pacing": str(scene.get("pacing") or "").strip(),
        "scene_intent": str(scene.get("scene_intent") or "").strip(),
        "subject_focus": str(scene.get("subject_focus") or "").strip(),
        "camera_movement": str(scene.get("camera_movement") or "").strip(),
        "active_characters": [
            {
                "name": str(ref.get("name") or "").strip(),
                "role": str(ref.get("role") or "").strip(),
                "appearance_core": str(ref.get("appearance_core") or "").strip(),
                "clothing_style": str(ref.get("clothing_style") or "").strip(),
                "negative_constraints": str(ref.get("negative_constraints") or "").strip(),
                "reference_image_path": str(ref.get("reference_image_path") or "").strip(),
            }
            for ref in refs
        ],
    }
    return bible


def _director_text(scene: dict[str, Any]) -> str:
    return " ".join(
        str(scene.get(key) or "")
        for key in ("title", "visual_prompt", "dialogue", "emotion", "camera_movement", "sfx_type")
    ).lower()


def _ensure_audio_manifest(scene: dict[str, Any]) -> dict[str, Any]:
    from backend.project_models import default_drama_config
    default_manifest = deepcopy(default_drama_config()["audio_manifest"])
    manifest = scene.get("audio_manifest")
    if not isinstance(manifest, dict):
        manifest = {}
    merged = {**default_manifest, **manifest}
    trigger = merged.get("sfx_trigger")
    if not isinstance(trigger, dict):
        trigger = {}
    merged["sfx_trigger"] = {**default_manifest["sfx_trigger"], **trigger}
    if not isinstance(merged.get("sfx_triggers"), list):
        merged["sfx_triggers"] = []
    scene["audio_manifest"] = merged
    return merged


def apply_director_recommendation(scene: dict[str, Any], *, preserve_explicit: bool = True) -> dict[str, Any]:
    text = _director_text(scene)
    manifest = _ensure_audio_manifest(scene)
    current_camera = str(scene.get("camera_movement") or "").strip()
    current_speed = scene.get("camera_speed")
    trigger = manifest.setdefault("sfx_trigger", {})

    impact_tokens = (
        "巴掌", "耳光", "掌掴", "拍", "拍桌", "办公桌", "巨响", "啪嗒", "掉", "掉落",
        "落地", "钢笔", "打脸", "打飞", "拳", "踢", "撞", "砸", "雷", "闪电",
        "惊雷", "爆炸", "刺入", "拔剑", "刀光", "震惊", "怎么可能", "不可能", "杀意", "背叛",
        "怒吼", "吐血", "跪下", "slap", "hit", "impact", "thunder", "boom",
    )
    melancholy_tokens = (
        "内心", "独白", "回忆", "悲伤", "沉默", "雨夜", "孤独", "低沉", "叹息", "绝望",
        "落泪", "眼泪", "苦笑", "melancholy", "sad", "memory",
    )
    establishing_tokens = (
        "全景", "远景", "会议室", "顶层", "宫殿", "大殿", "推开", "木门", "西装", "全场",
        "董事", "山门", "建筑", "第一次登场", "初次登场", "登场", "全身", "高大", "城门", "华山",
        "宗门", "山巅", "establishing", "wide shot", "full body",
    )

    recommendation = ""
    if any(token in text for token in impact_tokens):
        recommendation = "dramatic_push"
    elif any(token in text for token in melancholy_tokens):
        recommendation = "melancholy_pan"
    elif any(token in text for token in establishing_tokens):
        recommendation = "establishing_tilt"

    auto_cameras = {
        "", "auto", "static", "slow_push_in", "slow_zoom_out",
        "pan_left", "pan_right", "tilt_down", "tilt_up", "dramatic_reveal",
    }
    if recommendation and (not preserve_explicit or current_camera in auto_cameras):
        scene["camera_movement"] = recommendation

    try:
        speed_value = float(current_speed) if current_speed not in (None, "") else None
    except (TypeError, ValueError):
        speed_value = None

    camera = str(scene.get("camera_movement") or "")
    if camera == "dramatic_push":
        speed = max(1.35, speed_value or 1.35)
        if not trigger.get("file"):
            if any(token in text for token in ("雷", "闪电", "惊雷", "thunder")):
                trigger["file"] = "thunder"
            elif any(token in text for token in ("拍", "拍桌", "办公桌", "巨响", "撞门", "爆炸", "boom")):
                trigger["file"] = "boom"
            elif any(token in text for token in ("巴掌", "耳光", "掌掴", "扇耳光", "扇巴掌", "slap")):
                trigger["file"] = "slap"
            elif any(token in text for token in ("啪嗒", "掉", "掉落", "落地", "钢笔", "drop")):
                trigger["file"] = "drop"
            else:
                trigger["file"] = "hit"
        if not trigger.get("timestamp_ms"):
            if any(token in text for token in ("啪嗒", "掉", "掉落", "落地", "钢笔", "推开", "开门")):
                trigger["timestamp_ms"] = 350
            else:
                trigger["timestamp_ms"] = 1200
        if scene.get("sfx_type") in (None, "", "auto"):
            scene["sfx_type"] = str(trigger.get("file") or "hit")
    elif camera == "melancholy_pan":
        speed = min(0.8, speed_value or 0.7)
    elif camera == "establishing_tilt":
        speed = speed_value or 0.85
    else:
        speed = speed_value or 1.0
    scene["camera_speed"] = max(0.35, min(3.0, speed))
    if not trigger.get("volume"):
        trigger["volume"] = 0.65
    manifest["sfx_trigger"] = trigger
    scene["director_recommendation"] = {
        "camera_movement": scene.get("camera_movement"),
        "camera_speed": scene.get("camera_speed"),
        "sfx_type": scene.get("sfx_type", "auto"),
        "reason": "rule_heuristic",
    }
    return scene
