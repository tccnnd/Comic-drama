"""
Project runtime – core project CRUD, coordination, and re-exports.

This module was split into focused sub-modules:
  - backend.project_models   : data models, constants, conversion utilities
  - backend.character_manager : character cards, prompts, voice inheritance
  - backend.scene_graph       : scene graph, timeline, production bible, director logic
  - backend.scene_renderer    : scene rendering and asset generation
  - backend.project_export    : export and build logic

All public names are re-exported here so existing importers (e.g. backend.app)
continue to work unchanged.
"""
from __future__ import annotations

import re
import time
import uuid
from copy import deepcopy
from typing import Any

from scripts.run_workflow import (
    StoryScene,
    analyze_script_workflow,
    build_canonical_timeline,
    build_shot_plan,
    build_storyboard,
    coerce_scene,
    default_audio_style,
    default_episode_pacing,
    default_subtitle_style,
    is_script_text_garbled,
    load_env_file,
    normalize_audio_style,
    normalize_crop_box,
    normalize_episode_pacing,
    normalize_episode_phase,
    normalize_subtitle_style,
    validate_script_text,
)

from backend.asset_retention import cleanup_project_versions
from backend.event_bus import project_event_bus
from backend.styles import get_default_style_id
from backend.consistency_governance import _normalized_governance, build_continuity_ledger

# ─── Re-exports from project_models ───────────────────────────────────────────
from backend.project_models import (  # noqa: F401
    ExportAssetReadinessError,
    ROOT,
    WORKSPACE,
    SCENE_HISTORY_LIMIT,
    SCENE_ACTION_LABELS,
    _LOCKS,
    _LOCKS_GUARD,
    _coerce_int_field,
    _normalize_audio_manifest,
    _scene_from_payload,
    atomic_write_json,
    default_character_meta,
    default_drama_config,
    default_enhancement_config,
    default_episode_pacing_config,
    default_voice_config,
    derive_project_title,
    ensure_project_dirs,
    ffmpeg_concat_path,
    get_ffmpeg_exe,
    load_json,
    next_version_path,
    normalize_character_meta,
    project_dir,
    project_file,
    project_lock,
    project_relative_file_exists,
    project_relative_path,
    scene_dir,
    scene_to_dict,
    utc_iso,
    workspace_url,
)

# ─── Re-exports from character_manager ────────────────────────────────────────
from backend.character_manager import (  # noqa: F401
    build_initial_characters,
    character_card_path,
    character_dir,
    compile_character_prompt,
    hydrate_character_cards,
    load_character_card_files,
    merge_character_configs,
    normalize_character_card,
    remove_placeholder_scene_characters,
    scene_character_refs,
    scene_with_character_context,
    scene_with_inherited_voice,
    sync_character_card_files,
    update_character_reference_image,
    validate_reference_image,
    write_data_url_image,
    _character_prompt_feature_lines,
)

# ─── Re-exports from scene_graph ──────────────────────────────────────────────
from backend.scene_graph import (  # noqa: F401
    _apply_scene_graph,
    _apply_shot_overrides_to_graph,
    _bounded_float,
    _normalize_shot_overrides,
    _refresh_project_scene_graph,
    _scene_graph_payload,
    _shot_override_key,
    apply_director_recommendation,
    build_production_bible,
    scene_production_bible,
)

# ─── Re-exports from scene_renderer ──────────────────────────────────────────
from backend.scene_renderer import (  # noqa: F401
    AUDIO_STALE_FIELDS,
    IMAGE_STALE_FIELDS,
    VIDEO_STALE_FIELDS,
    _blank_assets,
    _ensure_scene_renderable,
    _invalidate_character_scenes,
    _invalidate_scene_assets,
    _mark_output_stale,
    _scene_assets,
    _scene_validation_blocked,
    _scene_validation_resolved,
    fallback_scene_clip_path,
    generate_scene_assets,
    rerender_scene_audio,
    rerender_scene_image,
    rerender_scene_video,
    scene_asset_file_exists,
    scene_latest_path,
    sync_scene_duration,
    update_scene_asset,
    update_scene_consistency_meta,
    update_scene_governance,
)

# ─── Re-exports from project_export ──────────────────────────────────────────
from backend.project_export import (  # noqa: F401
    _export_issue_item,
    build_project,
    export_project,
    validate_export_assets,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Core project CRUD and coordination (kept in this module)
# ═══════════════════════════════════════════════════════════════════════════════


def create_project(
    title: str,
    story_text: str,
    planner: str,
    scene_count: int,
    keyframe_provider: str,
    video_provider: str,
    voice_provider: str,
) -> dict[str, Any]:
    load_env_file()
    project_id = f"proj_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    ensure_project_dirs(project_id)

    scenes, planner_used = build_storyboard(story_text, planner, scene_count)
    project = {
        "project_id": project_id,
        "title": title.strip() or derive_project_title(story_text),
        "story_text": story_text,
        "style_id": get_default_style_id(),
        "style_guide": "",
        "settings": {
            "aspect_ratio": "9:16",
            "global_style": "竖屏动态漫画",
            "planner": planner_used,
            "scene_count": scene_count,
            "keyframe_provider": keyframe_provider,
            "video_provider": video_provider,
            "voice_provider": voice_provider,
            "subtitle_style": default_subtitle_style(),
            "audio_style": default_audio_style(),
            "episode_pacing": default_episode_pacing_config(),
        },
        "characters": build_initial_characters(scenes),
        "scenes": [scene_to_dict(scene, order) for order, scene in enumerate(scenes, start=1)],
        "runtime": {
            "status": "idle",
            "progress": 0,
            "stage": "draft",
            "message": "Draft ready",
            "updated_at": utc_iso(),
        },
        "output": {
            "final_video_path": "",
            "final_video_url": "",
            "subtitles_path": "",
            "subtitles_url": "",
            "status": "idle",
        },
        "created_at": utc_iso(),
        "updated_at": utc_iso(),
    }
    apply_project_episode_pacing(project, force=True)
    return _save_project_with_project_event(project)


def reconstruct_story_text_from_scenes(project: dict[str, Any]) -> str:
    parts: list[str] = []
    for scene in sorted(project.get("scenes", []), key=lambda item: int(item.get("order", 0))):
        title = str(scene.get("title") or f"场景 {int(scene.get('order') or 0)}").strip()
        speaker = str(scene.get("speaker") or "").strip()
        visual = str(scene.get("visual_prompt") or "").strip()
        dialogue = str(scene.get("dialogue") or "").strip()
        lines = [f"{title}"]
        if visual:
            lines.append(f"【画面】{visual}")
        if dialogue:
            lines.append(dialogue)
        elif speaker:
            lines.append(f"{speaker}：")
        parts.append("\n".join(lines).strip())
    return "\n\n".join(parts).strip()


def replace_project_storyboard(
    project_id: str,
    story_text: str,
    planner: str,
    title: str = "",
    max_scenes: int = 12,
    script_hint: str = "",
) -> dict[str, Any]:
    load_env_file()
    analysis, scenes, planner_used = analyze_script_workflow(
        story_text,
        planner,
        max_scenes=max_scenes,
        script_hint=script_hint,
    )
    roles = analysis.get("roles") if isinstance(analysis, dict) else None
    scenes = remove_placeholder_scene_characters(scenes, roles=roles)
    with project_lock(project_id):
        project = load_project(project_id)
        existing_characters = list(project.get("characters", []))
        project["story_text"] = story_text
        project["script_analysis"] = analysis
        chosen_title = title.strip()
        if chosen_title:
            project["title"] = chosen_title
        elif not str(project.get("title") or "").strip():
            project["title"] = derive_project_title(story_text)
        settings = project.setdefault("settings", {})
        settings["planner"] = planner_used
        settings["scene_count"] = len(scenes)
        project["characters"] = merge_character_configs(existing_characters, scenes, roles=roles)
        project["scenes"] = [scene_to_dict(scene, order) for order, scene in enumerate(scenes, start=1)]
        apply_project_episode_pacing(project, force=True)
        _mark_output_stale(project)
        project["output"] = {
            "final_video_path": "",
            "final_video_url": "",
            "subtitles_path": "",
            "subtitles_url": "",
            "status": "idle",
        }
        _set_runtime(project, status="idle", progress=0, stage="draft", message="Script parsed")
    return _save_project_with_project_event(project)


def _preview_scene_characters(value: object) -> list[str]:
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        items = re.split(r"[,，;；\n]+", value)
    else:
        items = [value]
    return [str(item).strip() for item in items if str(item).strip()]


def _preview_scene_to_story_scene(raw: dict[str, Any], index: int) -> StoryScene:
    normalized = {
        "title": raw.get("title") or raw.get("scene_title") or f"分镜 {index}",
        "visual": raw.get("visual") or raw.get("visual_prompt") or "",
        "dialogue": raw.get("dialogue") or "",
        "camera": raw.get("camera") or raw.get("camera_movement") or "slow_push_in",
        "emotion": raw.get("emotion") or "",
        "characters": _preview_scene_characters(raw.get("characters")),
        "speaker": raw.get("speaker") or "",
        "voice_profile": raw.get("voice_profile") or "",
        "duration": raw.get("duration") or raw.get("duration_seconds") or 4.0,
        "sfx_type": raw.get("sfx_type") or "auto",
        "audio_manifest": raw.get("audio_manifest") if isinstance(raw.get("audio_manifest"), dict) else {},
        "camera_speed": raw.get("camera_speed") or 1.0,
        "crop_box": raw.get("crop_box"),
    }
    return coerce_scene(normalized, index)


def replace_project_storyboard_from_preview(
    project_id: str,
    draft: dict[str, Any],
) -> dict[str, Any]:
    load_env_file()
    story_text = str(draft.get("story_text") or "").strip()
    if not story_text:
        raise ValueError("Script text is required.")
    validate_script_text(story_text)

    raw_scenes = draft.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("Script preview must contain scenes.")

    planner_used = str(draft.get("planner_used") or draft.get("planner") or "rule").strip() or "rule"
    title = str(draft.get("title") or "").strip()
    analysis = draft.get("analysis") if isinstance(draft.get("analysis"), dict) else {}
    scenes = [_preview_scene_to_story_scene(raw if isinstance(raw, dict) else {}, index) for index, raw in enumerate(raw_scenes, start=1)]
    analysis = deepcopy(analysis) if isinstance(analysis, dict) else {}
    roles = analysis.get("roles") if isinstance(analysis, dict) else None
    scenes = remove_placeholder_scene_characters(scenes, roles=roles)
    analysis["planner_used"] = planner_used
    analysis["scenes"] = [
        {
            "scene_id": f"scene_{order:03d}",
            "index": order,
            "title": scene.title,
            "camera": scene.camera,
            "emotion": scene.emotion,
            "characters": list(scene.characters),
            "speaker": scene.speaker or "",
            "dialogue": scene.dialogue,
            "visual": scene.visual,
            "duration": scene.duration,
        }
        for order, scene in enumerate(scenes, start=1)
    ]

    with project_lock(project_id):
        project = load_project(project_id)
        existing_characters = list(project.get("characters", []))
        project["story_text"] = story_text
        project["script_analysis"] = analysis
        chosen_title = title.strip()
        if chosen_title:
            project["title"] = chosen_title
        elif not str(project.get("title") or "").strip():
            project["title"] = derive_project_title(story_text)
        settings = project.setdefault("settings", {})
        settings["planner"] = planner_used
        settings["scene_count"] = len(scenes)
        project["characters"] = merge_character_configs(existing_characters, scenes, roles=roles)
        project["scenes"] = [scene_to_dict(scene, order) for order, scene in enumerate(scenes, start=1)]
        apply_project_episode_pacing(project, force=True)
        _mark_output_stale(project)
        project["output"] = {
            "final_video_path": "",
            "final_video_url": "",
            "subtitles_path": "",
            "subtitles_url": "",
            "status": "idle",
        }
        _set_runtime(project, status="idle", progress=0, stage="draft", message="Script parsed")
    return _save_project_with_project_event(project)


def load_project(project_id: str) -> dict[str, Any]:
    path = project_file(project_id)
    if not path.exists():
        raise FileNotFoundError(project_id)
    project = load_json(path)
    if isinstance(project, dict):
        hydrate_character_cards(project)
        project.setdefault("style_guide", "")
        if not isinstance(project.get("props"), list):
            project["props"] = []
        bible = project.get("production_bible")
        if isinstance(bible, dict) and not isinstance(bible.get("props"), list):
            bible["props"] = []
        for scene in project.get("scenes", []):
            if not isinstance(scene, dict):
                continue
            if not isinstance(scene.get("props"), list):
                scene["props"] = []
            else:
                scene["props"] = [str(item).strip() for item in scene.get("props") or [] if str(item).strip()]
            if not isinstance(scene.get("generation_meta"), dict):
                scene["generation_meta"] = {}
            if not isinstance(scene.get("shot_plan"), dict):
                scene["shot_plan"] = build_shot_plan(scene)
            scene["governance"] = _normalized_governance(scene)
        # Sync visual data from AssetStore into project.characters
        from backend.character_sync import sync_characters_from_assets
        sync_characters_from_assets(project, project_id)
    return project


def save_project(project: dict[str, Any]) -> dict[str, Any]:
    project_id = project["project_id"]
    project["style_id"] = str(project.get("style_id") or get_default_style_id()).strip()
    project.setdefault("style_guide", "")
    _refresh_project_scene_graph(project, project_id=project_id)
    project["updated_at"] = utc_iso()
    sync_character_card_files(project)
    atomic_write_json(project_file(project_id), project)
    try:
        cleanup_project_versions(project_dir(project_id), project, keep=2)
    except Exception as exc:
        print(f"[cleanup] failed for {project_id}: {exc}")
    return project


def project_subtitle_style(project: dict[str, Any]) -> dict[str, Any]:
    settings = project.setdefault("settings", {})
    style = normalize_subtitle_style(settings.get("subtitle_style"))
    settings["subtitle_style"] = style
    return style


def project_audio_style(project: dict[str, Any]) -> dict[str, Any]:
    settings = project.setdefault("settings", {})
    style = normalize_audio_style(settings.get("audio_style"))
    settings["audio_style"] = style
    return style


def project_episode_pacing(project: dict[str, Any]) -> dict[str, Any]:
    settings = project.setdefault("settings", {})
    pacing = normalize_episode_pacing(settings.get("episode_pacing"))
    settings["episode_pacing"] = pacing
    return pacing


def apply_project_episode_pacing(project: dict[str, Any], force: bool = False) -> dict[str, Any]:
    from scripts.run_workflow import infer_episode_phase
    pacing = project_episode_pacing(project)
    scenes = project.get("scenes", [])
    total = max(1, len(scenes))
    for index, scene in enumerate(scenes, start=1):
        phase = normalize_episode_phase(scene.get("episode_phase"), "")
        if force or not phase:
            phase = infer_episode_phase(index, total, pacing)
            phase_index = index
        else:
            phase_index = _coerce_int_field(scene.get("episode_phase_index"), index, 1, total)
        scene["episode_rhythm"] = str(pacing.get("preset") or "classic_four_act")
        scene["episode_phase"] = phase
        scene["episode_phase_index"] = phase_index
        scene["episode_phase_total"] = total
    return project


def normalize_scene_pacing_update(updates: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(updates)
    if "crop_box" in normalized and normalized["crop_box"] is not None:
        normalized["crop_box"] = normalize_crop_box(normalized["crop_box"])
    if "episode_phase" in normalized and normalized["episode_phase"] is not None:
        normalized["episode_phase"] = normalize_episode_phase(normalized["episode_phase"], "setup")
    if "episode_phase_index" in normalized and normalized["episode_phase_index"] is not None:
        normalized["episode_phase_index"] = _coerce_int_field(normalized["episode_phase_index"], 1, 1, 100)
    if "episode_phase_total" in normalized and normalized["episode_phase_total"] is not None:
        normalized["episode_phase_total"] = _coerce_int_field(normalized["episode_phase_total"], 1, 1, 100)
    if "episode_rhythm" in normalized and normalized["episode_rhythm"] is not None:
        pacing = normalize_episode_pacing({"preset": normalized["episode_rhythm"]})
        normalized["episode_rhythm"] = pacing["preset"]
    return normalized


def list_projects() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(WORKSPACE.glob("proj_*/project.json"), reverse=True):
        try:
            items.append(load_json(path))
        except Exception:
            continue
    return items


def delete_project(project_id: str) -> dict[str, str]:
    import shutil
    base = project_dir(project_id).resolve()
    workspace = WORKSPACE.resolve()
    if base == workspace or workspace not in base.parents:
        raise ValueError(f"Invalid project path: {project_id}")
    lock = project_lock(project_id)
    with lock:
        if not project_file(project_id).exists():
            raise FileNotFoundError(project_id)
        shutil.rmtree(base)
    with _LOCKS_GUARD:
        _LOCKS.pop(project_id, None)
    return {"project_id": project_id, "status": "deleted"}


def project_snapshot(project: dict[str, Any]) -> dict[str, Any]:
    from backend.scene_graph import _ensure_audio_manifest

    snapshot = deepcopy(project)
    project_id = snapshot["project_id"]
    snapshot["style_id"] = str(snapshot.get("style_id") or get_default_style_id()).strip()
    snapshot.setdefault("style_guide", "")
    project_subtitle_style(snapshot)
    project_audio_style(snapshot)
    apply_project_episode_pacing(snapshot)
    _refresh_project_scene_graph(snapshot, project_id=project_id)
    scenes = snapshot.get("scenes", [])
    characters = snapshot.get("characters", [])
    for character in snapshot.get("characters", []):
        if isinstance(character, dict):
            character.update(normalize_character_card(character))
        for key, value in list(character.items()):
            if key.endswith("_path") and value and project_relative_file_exists(project_id, value):
                character[key.replace("_path", "_url")] = workspace_url(project_id, value)
        if character.get("reference_audio_path"):
            character["reference_audio_url"] = (
                workspace_url(project_id, character["reference_audio_path"])
                if project_relative_file_exists(project_id, character["reference_audio_path"])
                else ""
            )
    for scene in snapshot.get("scenes", []):
        scene["crop_box"] = normalize_crop_box(scene.get("crop_box"))
        if not isinstance(scene.get("props"), list):
            scene["props"] = []
        else:
            scene["props"] = [str(item).strip() for item in scene.get("props") or [] if str(item).strip()]
        if not isinstance(scene.get("generation_meta"), dict):
            scene["generation_meta"] = {}
        if not isinstance(scene.get("shot_plan"), dict):
            scene["shot_plan"] = build_shot_plan(scene)
        scene["governance"] = _normalized_governance(scene)
        for key, value in default_drama_config().items():
            scene.setdefault(key, value)
        _ensure_audio_manifest(scene)
        for key, value in default_enhancement_config().items():
            scene.setdefault(key, value)
        assets = scene.get("assets", {})
        for key, value in list(assets.items()):
            if key.endswith("_path") and value:
                if project_relative_file_exists(project_id, value):
                    assets[key.replace("_path", "_url")] = workspace_url(project_id, value)
                else:
                    kind = key[: -len("_path")]
                    assets[key] = ""
                    assets[key.replace("_path", "_url")] = ""
                    versions = assets.setdefault("versions", {"image": 0, "audio": 0, "video": 0})
                    if isinstance(versions, dict) and kind in versions:
                        versions[kind] = 0
        if scene.get("reference_audio_path"):
            scene["reference_audio_url"] = (
                workspace_url(project_id, scene["reference_audio_path"])
                if project_relative_file_exists(project_id, scene["reference_audio_path"])
                else ""
            )
        if scene.get("enhancement_result_path"):
            scene["enhancement_result_url"] = (
                workspace_url(project_id, scene["enhancement_result_path"])
                if project_relative_file_exists(project_id, scene["enhancement_result_path"])
                else ""
            )
    output = snapshot.get("output", {})
    if output.get("final_video_path") and project_relative_file_exists(project_id, output["final_video_path"]):
        output["final_video_url"] = workspace_url(project_id, output["final_video_path"])
    else:
        output["final_video_path"] = ""
        output["final_video_url"] = ""
    if output.get("subtitles_path") and project_relative_file_exists(project_id, output["subtitles_path"]):
        output["subtitles_url"] = workspace_url(project_id, output["subtitles_path"])
    else:
        output["subtitles_path"] = ""
        output["subtitles_url"] = ""
    if output.get("subtitles_ass_path") and project_relative_file_exists(project_id, output["subtitles_ass_path"]):
        output["subtitles_ass_url"] = workspace_url(project_id, output["subtitles_ass_path"])
    else:
        output["subtitles_ass_path"] = ""
        output["subtitles_ass_url"] = ""
    asset_totals = {"image": 0, "audio": 0, "video": 0}
    completed_scenes = 0
    scene_graph_entries: list[dict[str, Any]] = []
    total_shots = 0
    for scene in scenes:
        assets = scene.get("assets", {}) or {}
        if assets.get("status") == "completed":
            completed_scenes += 1
        for kind in asset_totals:
            if assets.get(f"{kind}_url"):
                asset_totals[kind] += 1
        shots = scene.get("shots", []) if isinstance(scene, dict) else []
        shot_count = len(shots) if isinstance(shots, list) else 0
        total_shots += shot_count
        scene_graph_entries.append(
            {
                "scene_id": str(scene.get("scene_id") or ""),
                "order": int(scene.get("order") or 0),
                "title": str(scene.get("title") or ""),
                "shot_count": shot_count,
                "camera_track": deepcopy(scene.get("camera_track") or {}),
            }
        )
    snapshot["summary"] = {
        "total_scenes": len(scenes),
        "completed_scenes": completed_scenes,
        "total_characters": len(characters),
        "asset_totals": asset_totals,
        "has_final_video": bool(output.get("final_video_url")),
        "total_shots": total_shots,
    }
    snapshot["scene_graph"] = {
        "version": 1,
        "scene_count": len(scenes),
        "shot_count": total_shots,
        "scenes": scene_graph_entries,
    }
    snapshot["production_bible"] = build_production_bible(snapshot)
    snapshot["continuity_ledger"] = build_continuity_ledger(snapshot)
    snapshot["canonical_timeline"] = build_canonical_timeline(snapshot)
    return snapshot


# ─── Event publishing helpers ─────────────────────────────────────────────────


def _event_project(project: dict[str, Any]) -> dict[str, Any]:
    try:
        return project_snapshot(project)
    except Exception:
        return deepcopy(project)


def _event_scene(project: dict[str, Any], scene_order: int) -> dict[str, Any] | None:
    snapshot = _event_project(project)
    for scene in snapshot.get("scenes", []):
        try:
            if int(scene.get("order") or 0) == int(scene_order):
                return scene
        except (TypeError, ValueError):
            continue
    return None


def _publish_project_updated(project: dict[str, Any]) -> None:
    project_id = str(project.get("project_id") or "")
    if project_id:
        project_event_bus.publish_project_updated(project_id, _event_project(project))


def _publish_scene_updated(project: dict[str, Any], scene_order: int) -> None:
    project_id = str(project.get("project_id") or "")
    scene = _event_scene(project, scene_order)
    if project_id and scene:
        project_event_bus.publish_scene_updated(project_id, scene)


def _save_project_with_project_event(project: dict[str, Any]) -> dict[str, Any]:
    saved = save_project(project)
    _publish_project_updated(saved)
    return saved


def _save_project_with_scene_event(project: dict[str, Any], scene_order: int) -> dict[str, Any]:
    saved = save_project(project)
    _publish_scene_updated(saved, scene_order)
    _publish_project_updated(saved)
    return saved


def _save_project_with_structure_event(project: dict[str, Any], event_type: str, scene_order: int) -> dict[str, Any]:
    saved = save_project(project)
    project_id = str(saved.get("project_id") or "")
    snapshot = _event_project(saved)
    if not project_id:
        return saved
    if event_type == "split":
        project_event_bus.publish_scene_split(project_id, scene_order, snapshot)
    elif event_type == "merge":
        project_event_bus.publish_scene_merged(project_id, scene_order, snapshot)
    elif event_type == "restore":
        project_event_bus.publish_scene_restored(project_id, scene_order, snapshot)
    return saved


# ─── Runtime update helpers ───────────────────────────────────────────────────


def _set_runtime(project: dict[str, Any], **updates: Any) -> dict[str, Any]:
    runtime = project.setdefault("runtime", {})
    runtime.update(updates)
    runtime["updated_at"] = utc_iso()
    return project


def update_runtime(project_id: str, **updates: Any) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        _set_runtime(project, **updates)
        return _save_project_with_project_event(project)


# ─── Scene update logic ──────────────────────────────────────────────────────


def _update_scene(project: dict[str, Any], scene_order: int, updates: dict[str, Any]) -> dict[str, Any]:
    for scene in project.get("scenes", []):
        if int(scene.get("order", 0)) != scene_order:
            continue
        scene.update({key: value for key, value in updates.items() if value is not None})
        apply_director_recommendation(scene)
        break
    return project


def _changed_scene_fields(scene: dict[str, Any], updates: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    for key, value in updates.items():
        if value is None:
            continue
        if scene.get(key) != value:
            changed.append(key)
    return changed


def update_project_fields(project_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        for key, value in updates.items():
            if value is None:
                continue
            if key in {"title", "story_text"}:
                if key == "story_text" and isinstance(value, str):
                    current_story = str(project.get("story_text") or "")
                    if value != current_story and is_script_text_garbled(value):
                        raise ValueError("剧本文本疑似编码损坏：请重新从原始来源粘贴，不要使用已经变成 ? 的内容。")
                project[key] = value
            elif key == "style_id":
                project["style_id"] = str(value).strip()
            elif key == "settings" and isinstance(value, dict):
                settings = project.setdefault("settings", {})
                for setting_key, setting_value in value.items():
                    if setting_key == "subtitle_style" and isinstance(setting_value, dict):
                        current_style = settings.get("subtitle_style") if isinstance(settings.get("subtitle_style"), dict) else {}
                        settings["subtitle_style"] = normalize_subtitle_style({**current_style, **setting_value})
                    elif setting_key == "audio_style" and isinstance(setting_value, dict):
                        current_style = settings.get("audio_style") if isinstance(settings.get("audio_style"), dict) else {}
                        settings["audio_style"] = normalize_audio_style({**current_style, **setting_value})
                    elif setting_key == "episode_pacing" and isinstance(setting_value, dict):
                        current_pacing = settings.get("episode_pacing") if isinstance(settings.get("episode_pacing"), dict) else {}
                        settings["episode_pacing"] = normalize_episode_pacing({**current_pacing, **setting_value})
                    else:
                        settings[setting_key] = setting_value
            elif key == "characters" and isinstance(value, list):
                project["characters"] = value
        apply_project_episode_pacing(project, force=True)
        return _save_project_with_project_event(project)


def update_character_fields(project_id: str, char_index: int, updates: dict[str, Any]) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        characters = project.get("characters", [])
        if char_index < 1 or char_index > len(characters):
            raise KeyError(f"Character {char_index} not found")
        character = characters[char_index - 1]
        previous_name = character.get("name")
        changed_fields: list[str] = []
        for key, value in updates.items():
            if value is None:
                continue
            if key in {
                "name",
                "description",
                "meta",
                "appearance_core",
                "clothing_style",
                "negative_constraints",
                "voice_profile",
                "voice_engine",
                "voice_id",
                "reference_audio_path",
                "reference_text",
                "emotion",
                "voice_rate",
                "voice_pitch",
                "voice_volume",
            }:
                if character.get(key) != value:
                    changed_fields.append(key)
                character[key] = value
        visual_fields = {"name", "description", "meta", "appearance_core", "clothing_style", "negative_constraints"}
        voice_fields = AUDIO_STALE_FIELDS & set(changed_fields)
        invalidate_fields: list[str] = []
        if visual_fields & set(changed_fields):
            invalidate_fields.append("characters")
        if voice_fields:
            invalidate_fields.append("voice_id")
        if invalidate_fields:
            _invalidate_character_scenes(project, character, invalidate_fields, previous_name)
        return _save_project_with_project_event(project)


def update_scene_fields(project_id: str, scene_order: int, updates: dict[str, Any]) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        updates = normalize_scene_pacing_update(updates)
        scene = next((item for item in project.get("scenes", []) if int(item.get("order", 0)) == scene_order), None)
        if scene is None:
            raise KeyError(f"Scene {scene_order} not found")
        before_scene = deepcopy(scene)
        _capture_scene_snapshot_locked(project_id, scene_order, "edit", project)
        _update_scene(project, scene_order, updates)
        tracked_fields = set(updates) | {
            "camera_movement",
            "camera_speed",
            "audio_manifest",
            "sfx_type",
            "director_recommendation",
        }
        changed = [
            key
            for key in sorted(tracked_fields)
            if (key not in updates or updates.get(key) is not None) and before_scene.get(key) != scene.get(key)
        ]
        _invalidate_scene_assets(scene, changed)
        if scene.get("validation_failed") and _scene_validation_resolved(scene):
            scene["validation_failed"] = False
            scene["error_message"] = ""
            scene["raw_llm_output"] = {}
            assets = _scene_assets(scene)
            if assets.get("status") == "failed":
                assets["status"] = "pending"
            changed.append("validation_failed")
        if set(changed) & (IMAGE_STALE_FIELDS | AUDIO_STALE_FIELDS | VIDEO_STALE_FIELDS):
            _mark_output_stale(project)
        if changed:
            _append_scene_history(project, scene_order, "edit", "saved", f"已保存字段：{', '.join(changed)}")
        return _save_project_with_scene_event(project, scene_order)


# ─── Scene renumbering ────────────────────────────────────────────────────────


def _renumber_scenes(project: dict[str, Any]) -> None:
    used_scene_ids: set[str] = set()
    project_id = str(project.get("project_id") or "")
    existing_dir_ids = set()
    if project_id:
        scene_root = project_dir(project_id) / "scenes"
        if scene_root.exists():
            existing_dir_ids = {path.name for path in scene_root.iterdir() if path.is_dir()}
    existing_scene_ids = {
        str(scene.get("scene_id") or "")
        for scene in project.get("scenes", [])
        if str(scene.get("scene_id") or "").strip()
    }
    max_number = 0
    for value in existing_scene_ids | existing_dir_ids:
        if value.startswith("scene_"):
            try:
                max_number = max(max_number, int(value.split("_", 1)[1]))
            except (IndexError, ValueError):
                continue
    next_scene_number = max_number + 1

    def _next_scene_id() -> str:
        nonlocal next_scene_number
        while True:
            candidate = f"scene_{next_scene_number:03d}"
            next_scene_number += 1
            if candidate not in existing_scene_ids and candidate not in existing_dir_ids and candidate not in used_scene_ids:
                return candidate

    for index, scene in enumerate(project.get("scenes", []), start=1):
        scene["order"] = index
        scene_id = str(scene.get("scene_id") or "").strip()
        if not scene_id or scene_id in used_scene_ids:
            scene_id = _next_scene_id()
        scene["scene_id"] = scene_id
        used_scene_ids.add(scene_id)
    project.setdefault("settings", {})["scene_count"] = len(project.get("scenes", []))


# ─── Split / Merge ────────────────────────────────────────────────────────────


def split_scene(project_id: str, scene_order: int) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        scenes = project.get("scenes", [])
        index = next((i for i, item in enumerate(scenes) if int(item.get("order", 0)) == scene_order), None)
        if index is None:
            raise KeyError(f"Scene {scene_order} not found")
        source = scenes[index]
        _capture_scene_snapshot_locked(project_id, scene_order, "split", project)

        duplicate = deepcopy(source)
        duplicate["title"] = f"{source.get('title') or '分镜'} B"
        duplicate["visual_prompt"] = str(source.get("visual_prompt") or "").strip()
        duplicate["dialogue"] = ""
        duplicate["assets"] = _blank_assets()
        duplicate["history"] = []
        try:
            original_duration = float(source.get("duration_seconds") or 4.0)
        except (TypeError, ValueError):
            original_duration = 4.0
        half_duration = max(1.0, round(original_duration / 2, 1))
        source["duration_seconds"] = half_duration
        duplicate["duration_seconds"] = half_duration
        _invalidate_scene_assets(source, ["duration_seconds"])
        scenes.insert(index + 1, duplicate)
        _renumber_scenes(project)
        apply_project_episode_pacing(project, force=True)
        _mark_output_stale(project)
        _append_scene_history(project, scene_order, "split", "saved", "已拆成两个分镜")
        _set_runtime(project, status="idle", progress=0, stage="draft", message="Scene split")
        return _save_project_with_structure_event(project, "split", scene_order)


def merge_scene_with_next(project_id: str, scene_order: int) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        scenes = project.get("scenes", [])
        index = next((i for i, item in enumerate(scenes) if int(item.get("order", 0)) == scene_order), None)
        if index is None or index >= len(scenes) - 1:
            raise KeyError(f"Scene {scene_order} has no next scene")
        current = scenes[index]
        following = scenes[index + 1]
        _capture_scene_snapshot_locked(project_id, scene_order, "merge", project)

        current["title"] = " / ".join(
            part for part in [str(current.get("title") or "").strip(), str(following.get("title") or "").strip()] if part
        )[:80]
        current["visual_prompt"] = "\n".join(
            part
            for part in [str(current.get("visual_prompt") or "").strip(), str(following.get("visual_prompt") or "").strip()]
            if part
        )
        current["dialogue"] = "\n".join(
            part for part in [str(current.get("dialogue") or "").strip(), str(following.get("dialogue") or "").strip()] if part
        )
        current["characters"] = list(dict.fromkeys([*(current.get("characters") or []), *(following.get("characters") or [])]))
        try:
            current["duration_seconds"] = round(float(current.get("duration_seconds") or 0) + float(following.get("duration_seconds") or 0), 1)
        except (TypeError, ValueError):
            current["duration_seconds"] = 6.0
        current["assets"] = _blank_assets()
        current.setdefault("history", [])
        scenes.pop(index + 1)
        _renumber_scenes(project)
        apply_project_episode_pacing(project, force=True)
        _mark_output_stale(project)
        _append_scene_history(project, scene_order, "merge", "saved", "已合并下一个分镜")
        _set_runtime(project, status="idle", progress=0, stage="draft", message="Scene merged")
        return _save_project_with_structure_event(project, "merge", scene_order)


# ─── Scene history and snapshots ──────────────────────────────────────────────


def _scene_history(scene: dict[str, Any]) -> list[dict[str, Any]]:
    return scene.setdefault("history", [])


def _scene_snapshot_dir(project_id: str, scene_id: str) -> "Path":
    from pathlib import Path
    return scene_dir(project_id, scene_id) / "snapshots"


def _scene_snapshot_payload(
    project_id: str,
    scene_order: int,
    action: str,
    scene: dict[str, Any],
    project: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scene_payload = deepcopy(scene)
    _apply_scene_graph(scene_payload, _scene_graph_payload(scene_payload, scene_order, project_id=project_id))
    payload = {
        "project_id": project_id,
        "scene_order": scene_order,
        "action": action,
        "captured_at": utc_iso(),
        "scene": scene_payload,
    }
    if project is not None:
        payload["scenes"] = deepcopy(project.get("scenes", []))
    return payload


def _capture_scene_snapshot_locked(project_id: str, scene_order: int, action: str, project: dict[str, Any]) -> "Path":
    import time as _time
    from pathlib import Path
    scene = next((item for item in project.get("scenes", []) if int(item.get("order", 0)) == scene_order), None)
    if scene is None:
        raise KeyError(f"Scene {scene_order} not found")
    directory = _scene_snapshot_dir(project_id, scene["scene_id"])
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{_time.strftime('%Y%m%d_%H%M%S', _time.gmtime())}_{uuid.uuid4().hex[:8]}_{action}.json"
    path = directory / filename
    atomic_write_json(path, _scene_snapshot_payload(project_id, scene_order, action, scene, project))
    return path


def capture_scene_snapshot(project_id: str, scene_order: int, action: str) -> "Path":
    with project_lock(project_id):
        project = load_project(project_id)
        return _capture_scene_snapshot_locked(project_id, scene_order, action, project)


def _latest_scene_snapshot_locked(
    project_id: str,
    scene_order: int,
    skip_actions: set[str] | None,
    project: dict[str, Any],
) -> dict[str, Any] | None:
    scene = next((item for item in project.get("scenes", []) if int(item.get("order", 0)) == scene_order), None)
    if scene is None:
        raise KeyError(f"Scene {scene_order} not found")
    directory = _scene_snapshot_dir(project_id, scene["scene_id"])
    if not directory.exists():
        return None
    skip_actions = skip_actions or set()
    paths = sorted(directory.glob("*.json"), key=lambda item: item.stat().st_mtime_ns, reverse=True)
    for path in paths:
        try:
            snapshot = load_json(path)
        except Exception:
            continue
        if snapshot.get("action") in skip_actions:
            continue
        return snapshot
    return None


def latest_scene_snapshot(project_id: str, scene_order: int, skip_actions: set[str] | None = None) -> dict[str, Any] | None:
    with project_lock(project_id):
        project = load_project(project_id)
        return _latest_scene_snapshot_locked(project_id, scene_order, skip_actions, project)


def restore_scene_snapshot(project_id: str, scene_order: int) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        scene = next((item for item in project.get("scenes", []) if int(item.get("order", 0)) == scene_order), None)
        if scene is None:
            raise KeyError(f"Scene {scene_order} not found")
        _capture_scene_snapshot_locked(project_id, scene_order, "restore-backup", project)
        snapshot = _latest_scene_snapshot_locked(project_id, scene_order, {"restore-backup"}, project)
        if snapshot is None:
            raise FileNotFoundError("No snapshot available")
        if snapshot.get("action") in {"split", "merge"} and isinstance(snapshot.get("scenes"), list):
            project["scenes"] = deepcopy(snapshot["scenes"])
            _renumber_scenes(project)
            apply_project_episode_pacing(project, force=True)
            _mark_output_stale(project)
            _append_scene_history(
                project,
                scene_order,
                "restore",
                "done",
                f"鍥炴粴鍒颁笂涓€涓増鏈細{snapshot.get('captured_at', '')}",
            )
            return _save_project_with_structure_event(project, "restore", scene_order)
        restored = snapshot.get("scene") or {}
        for key, value in restored.items():
            if key in {"scene_id", "order", "history"}:
                continue
            scene[key] = deepcopy(value)
        _append_scene_history(
            project,
            scene_order,
            "restore",
            "done",
            f"回滚到上一个版本：{snapshot.get('captured_at', '')}",
        )
        return _save_project_with_structure_event(project, "restore", scene_order)


def _append_scene_history(
    project: dict[str, Any],
    scene_order: int,
    action: str,
    status: str,
    message: str,
) -> dict[str, Any]:
    scene = next((item for item in project.get("scenes", []) if int(item.get("order", 0)) == scene_order), None)
    if scene is None:
        raise KeyError(f"Scene {scene_order} not found")
    history = _scene_history(scene)
    history.insert(
        0,
        {
            "ts": utc_iso(),
            "action": action,
            "label": SCENE_ACTION_LABELS.get(action, action),
            "status": status,
            "message": message,
        },
    )
    del history[SCENE_HISTORY_LIMIT:]
    return project


def append_scene_history(project_id: str, scene_order: int, action: str, status: str, message: str) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        _append_scene_history(project, scene_order, action, status, message)
        return _save_project_with_scene_event(project, scene_order)


def set_scene_status(project_id: str, scene_order: int, status: str) -> dict[str, Any]:
    with project_lock(project_id):
        project = load_project(project_id)
        scene = next((item for item in project.get("scenes", []) if int(item.get("order", 0)) == scene_order), None)
        if scene is None:
            raise KeyError(f"Scene {scene_order} not found")
        scene.setdefault("assets", {})["status"] = status
        return _save_project_with_scene_event(project, scene_order)
