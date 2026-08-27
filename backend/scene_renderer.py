"""Scene rendering and asset generation: image, audio, video rerender and asset management."""

from __future__ import annotations

import logging
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

from backend.project_models import (
    _scene_from_payload,
    get_ffmpeg_exe,
    next_version_path,
    project_dir,
    project_lock,
    project_relative_file_exists,
    project_relative_path,
    scene_dir,
    utc_iso,
    workspace_url,
)
from backend.video_generation import (
    generation_meta_from_result,
    normalize_generation_meta,
    render_scene_shots_with_provider_policy,
    sanitize_generation_error,
    video_fallback_mode,
    video_render_granularity,
)
from scripts.run_workflow import (
    build_shot_plan,
    generate_keyframe,
    load_env_file,
    render_clip_with_meta,
    render_silent_visual_segment,
    render_voice_track,
    run_guarded,
    wav_duration,
)

logger = logging.getLogger(__name__)


def _scene_assets(scene: dict[str, Any]) -> dict[str, Any]:
    return scene.setdefault(
        "assets",
        {
            "status": "pending",
            "versions": {"image": 0, "audio": 0, "video": 0},
            "image_path": "",
            "image_url": "",
            "audio_path": "",
            "audio_url": "",
            "video_path": "",
            "video_url": "",
        },
    )


def scene_latest_path(project_id: str, scene: dict[str, Any], kind: str) -> Path | None:
    assets = _scene_assets(scene)
    relative = assets.get(f"{kind}_path") or ""
    if not relative:
        return None
    return project_relative_path(project_id, relative)


def scene_asset_file_exists(project_id: str, scene: dict[str, Any], kind: str) -> bool:
    try:
        path = scene_latest_path(project_id, scene, kind)
    except ValueError:
        return False
    return bool(path and path.is_file())


def fallback_scene_clip_path(project_id: str, scene: dict[str, Any]) -> Path:
    return scene_dir(project_id, scene["scene_id"]) / "clip.mp4"


def _blank_assets() -> dict[str, Any]:
    return {
        "status": "pending",
        "versions": {"image": 0, "audio": 0, "video": 0},
        "image_path": "",
        "image_url": "",
        "audio_path": "",
        "audio_url": "",
        "video_path": "",
        "video_url": "",
    }


IMAGE_STALE_FIELDS = {"title", "visual_prompt", "emotion", "characters"}
AUDIO_STALE_FIELDS = {
    "dialogue",
    "speaker",
    "voice_profile",
    "voice_engine",
    "voice_id",
    "reference_audio_path",
    "reference_text",
    "voice_rate",
    "voice_pitch",
    "voice_volume",
}
VIDEO_STALE_FIELDS = {
    "camera_movement",
    "duration_seconds",
    "rhythm_preset",
    "sfx_type",
    "audio_manifest",
    "subtitle_preset",
    "camera_intensity",
    "camera_speed",
    "shot_overrides",
    "episode_rhythm",
    "episode_phase",
    "episode_phase_index",
    "episode_phase_total",
    "crop_box",
}


def _normalized_key(value: object) -> str:
    return str(value or "").strip().lower()


def _invalidate_scene_assets(scene: dict[str, Any], changed_fields: list[str]) -> None:
    changed = set(changed_fields)
    stale: set[str] = set()
    if changed & IMAGE_STALE_FIELDS:
        stale.update({"image", "video"})
    if changed & AUDIO_STALE_FIELDS:
        stale.update({"audio", "video"})
    if changed & VIDEO_STALE_FIELDS:
        stale.add("video")
    if not stale:
        return

    assets = _scene_assets(scene)
    versions = assets.setdefault("versions", {"image": 0, "audio": 0, "video": 0})
    for kind in stale:
        assets[f"{kind}_path"] = ""
        assets[f"{kind}_url"] = ""
        if isinstance(versions, dict):
            versions[kind] = 0
    assets["status"] = "pending"


def _scene_uses_character(scene: dict[str, Any], *names: object) -> bool:
    wanted = {_normalized_key(name) for name in names if _normalized_key(name)}
    if not wanted:
        return False
    scene_names = {
        _normalized_key(scene.get("speaker")),
        *{_normalized_key(name) for name in scene.get("characters") or []},
    }
    return bool(wanted & scene_names)


def _invalidate_character_scenes(
    project: dict[str, Any],
    character: dict[str, Any],
    changed_fields: list[str],
    *extra_names: object,
) -> None:
    names = [character.get("name"), *extra_names]
    changed_any = False
    for scene in project.get("scenes", []):
        if not _scene_uses_character(scene, *names):
            continue
        _invalidate_scene_assets(scene, changed_fields)
        changed_any = True
    if changed_any:
        _mark_output_stale(project)


def _mark_output_stale(project: dict[str, Any]) -> None:
    output = project.setdefault("output", {})
    for key in {
        "final_video_path",
        "final_video_url",
        "subtitles_path",
        "subtitles_url",
        "subtitles_ass_path",
        "subtitles_ass_url",
    }:
        output[key] = ""
    output["status"] = "stale"


def update_scene_asset(
    project_id: str, scene_order: int, kind: str, source_path: Path
) -> dict[str, Any]:
    with project_lock(project_id):
        from backend.project_runtime import _save_project_with_scene_event, load_project

        project = load_project(project_id)
        scene = next(
            (
                item
                for item in project.get("scenes", [])
                if int(item.get("order", 0)) == scene_order
            ),
            None,
        )
        if scene is None:
            raise KeyError(f"Scene {scene_order} not found")

        assets = _scene_assets(scene)
        scene_id = scene["scene_id"]
        directory = scene_dir(project_id, scene_id)
        suffix = {"image": ".png", "audio": ".wav", "video": ".mp4"}[kind]
        prefix = {"image": "image", "audio": "audio", "video": "video"}[kind]
        target = next_version_path(directory, prefix, suffix)
        shutil.copy2(source_path, target)
        relative = str(target.relative_to(project_dir(project_id))).replace("\\", "/")
        assets[f"{kind}_path"] = relative
        assets[f"{kind}_url"] = workspace_url(project_id, relative)
        versions = assets.setdefault("versions", {"image": 0, "audio": 0, "video": 0})
        if isinstance(versions, dict):
            versions[kind] = int(versions.get(kind, 0)) + 1
        has_dialogue = bool(str(scene.get("dialogue") or "").strip())
        has_required_audio = (not has_dialogue) or scene_asset_file_exists(
            project_id, scene, "audio"
        )
        assets["status"] = (
            "completed"
            if scene_asset_file_exists(project_id, scene, "image")
            and scene_asset_file_exists(project_id, scene, "video")
            and has_required_audio
            else "pending"
        )
        return _save_project_with_scene_event(project, scene_order)


def update_scene_consistency_meta(
    project_id: str,
    scene_order: int,
    consistency_meta: dict[str, Any] | None,
    primary_reference_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with project_lock(project_id):
        from backend.project_runtime import _save_project_with_scene_event, load_project

        project = load_project(project_id)
        scene = next(
            (
                item
                for item in project.get("scenes", [])
                if int(item.get("order", 0)) == scene_order
            ),
            None,
        )
        if scene is None:
            raise KeyError(f"Scene {scene_order} not found")
        scene["consistency_meta"] = (
            deepcopy(consistency_meta) if isinstance(consistency_meta, dict) else {}
        )
        if isinstance(primary_reference_meta, dict):
            scene["primary_reference_meta"] = deepcopy(primary_reference_meta)
        return _save_project_with_scene_event(project, scene_order)


def update_scene_governance(
    project_id: str,
    scene_order: int,
    governance: dict[str, Any] | None,
) -> dict[str, Any]:
    with project_lock(project_id):
        from backend.consistency_governance import _normalized_governance
        from backend.project_runtime import _save_project_with_scene_event, load_project

        project = load_project(project_id)
        scene = next(
            (
                item
                for item in project.get("scenes", [])
                if int(item.get("order", 0)) == scene_order
            ),
            None,
        )
        if scene is None:
            raise KeyError(f"Scene {scene_order} not found")
        scene["governance"] = (
            deepcopy(governance) if isinstance(governance, dict) else _normalized_governance(scene)
        )
        return _save_project_with_scene_event(project, scene_order)


def update_scene_generation_meta(
    project_id: str,
    scene_order: int,
    generation_meta: dict[str, Any] | None,
    shot_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    with project_lock(project_id):
        from backend.project_runtime import _save_project_with_scene_event, load_project

        project = load_project(project_id)
        scene = next(
            (
                item
                for item in project.get("scenes", [])
                if int(item.get("order", 0)) == scene_order
            ),
            None,
        )
        if scene is None:
            raise KeyError(f"Scene {scene_order} not found")
        scene["generation_meta"] = normalize_generation_meta(generation_meta)
        current_shot_plan = (
            scene.get("shot_plan") if isinstance(scene.get("shot_plan"), dict) else {}
        )
        next_shot_plan = (
            deepcopy(shot_plan) if isinstance(shot_plan, dict) else build_shot_plan(scene)
        )
        if current_shot_plan != next_shot_plan:
            scene["shot_plan"] = next_shot_plan
        return _save_project_with_scene_event(project, scene_order)


def sync_scene_duration(
    project_id: str, scene_order: int, duration_seconds: float
) -> dict[str, Any]:
    with project_lock(project_id):
        from backend.project_runtime import _save_project_with_scene_event, load_project

        project = load_project(project_id)
        scene = next(
            (
                item
                for item in project.get("scenes", [])
                if int(item.get("order", 0)) == scene_order
            ),
            None,
        )
        if scene is None:
            raise KeyError(f"Scene {scene_order} not found")
        normalized = max(0.25, round(float(duration_seconds), 1))
        current = float(scene.get("duration_seconds") or 0.0)
        if abs(current - normalized) < 0.05:
            return project
        scene["duration_seconds"] = normalized
        _invalidate_scene_assets(scene, ["duration_seconds"])
        return _save_project_with_scene_event(project, scene_order)


def _evaluate_and_persist_scene_governance(
    project_id: str, scene_order: int, image_path: Path | None
) -> dict[str, Any] | None:
    try:
        with project_lock(project_id):
            from backend.project_runtime import load_project

            project = load_project(project_id)
            scene = next(
                (
                    item
                    for item in project.get("scenes", [])
                    if int(item.get("order", 0)) == scene_order
                ),
                None,
            )
            if scene is None:
                raise KeyError(f"Scene {scene_order} not found")
            prev_scene = next(
                (
                    item
                    for item in project.get("scenes", [])
                    if isinstance(item, dict) and int(item.get("order", 0)) == scene_order - 1
                ),
                None,
            )
            prev_image = scene_latest_path(project_id, prev_scene, "image") if prev_scene else None
            scene_copy = deepcopy(scene)
            project_copy = deepcopy(project)
            prev_scene_copy = deepcopy(prev_scene) if isinstance(prev_scene, dict) else None

        from backend.consistency_governance import _normalized_governance, evaluate_scene_governance
        from backend.consistency_validator import CONSISTENCY_VALIDATION_ENABLED

        if not CONSISTENCY_VALIDATION_ENABLED:
            verdict = _normalized_governance(scene_copy)
        else:
            verdict = evaluate_scene_governance(
                project_copy,
                scene_copy,
                images={"current_image": image_path} if image_path else {},
                prev_image=prev_image,
                prev_scene=prev_scene_copy,
            )
        return update_scene_governance(project_id, scene_order, verdict)
    except Exception as exc:
        logger.warning("[governance] failed to evaluate scene %d: %s", scene_order, exc)
        return None


def _strict_video_context_error(
    scene: dict[str, Any] | None, scene_order: int, video_provider: str, exc: Exception
) -> RuntimeError:
    scene_id = str((scene or {}).get("scene_id") or f"scene_{scene_order:03d}")
    provider = str(video_provider or "auto").strip() or "auto"
    error = sanitize_generation_error(exc, limit=240) or exc.__class__.__name__
    return RuntimeError(
        f"Scene {scene_id} video generation failed in strict mode. "
        f"Provider: {provider}. Error: {error}"
    )


def _scene_shot_plan(scene: dict[str, Any]) -> dict[str, Any]:
    existing = scene.get("shot_plan") if isinstance(scene.get("shot_plan"), dict) else {}
    if isinstance(existing.get("shots"), list) and existing.get("shots"):
        return deepcopy(existing)
    return build_shot_plan(scene)


def _render_shot_level_scene_clip(
    *,
    project_id: str,
    scene: dict[str, Any],
    shot_plan_source: dict[str, Any] | None = None,
    scene_order: int,
    scene_obj: Any,
    directory: Path,
    image_path: Path,
    clip_duration: float,
    ffmpeg: str,
    video_provider: str,
    settings: dict[str, Any],
    force_shot_id: str = "",
    reuse_cache: bool | None = None,
) -> dict[str, Any]:
    scene_for_plan = {**(shot_plan_source or {}), **scene, "duration_seconds": clip_duration}
    if isinstance(shot_plan_source, dict):
        for key in ("shot_plan", "temporal_spec"):
            if isinstance(shot_plan_source.get(key), dict):
                scene_for_plan[key] = deepcopy(shot_plan_source[key])
    shot_plan = _scene_shot_plan(scene_for_plan)
    generation_meta = normalize_generation_meta(scene.get("generation_meta"))
    existing_outputs = (
        generation_meta.get("shot_outputs")
        if isinstance(generation_meta.get("shot_outputs"), list)
        else []
    )

    def fallback_renderer(shot_request: dict[str, Any], fallback_output_path: Path) -> Path:
        camera = shot_request.get("camera") if isinstance(shot_request.get("camera"), dict) else {}
        render_silent_visual_segment(
            ffmpeg,
            image_path,
            float(shot_request.get("duration_seconds") or 0.25),
            fallback_output_path,
            1.08,
            str(camera.get("camera_movement") or scene.get("camera_movement") or "slow_push"),
            int(shot_request.get("index") or 1),
            camera_speed=float(camera.get("camera_speed") or scene.get("camera_speed") or 1.0),
            focus_x=float(camera.get("center_x") or 0.5),
            focus_y=float(camera.get("center_y") or 0.5),
        )
        return fallback_output_path

    effective_settings = dict(settings or {})
    if reuse_cache is not None:
        effective_settings["video_shot_reuse_cache"] = bool(reuse_cache)

    clip_path, shot_generation_meta, _ = render_scene_shots_with_provider_policy(
        scene=scene_for_plan,
        shot_plan=shot_plan,
        keyframe_path=image_path,
        output_path=directory / f"clip_{int(scene_obj.scene):02}_shot_assembled.mp4",
        run_dir=directory,
        ffmpeg=ffmpeg,
        video_provider=video_provider,
        project_settings=effective_settings,
        existing_shot_outputs=existing_outputs,
        fallback_renderer=fallback_renderer,
        run_guarded=run_guarded,
        manifest_path=directory / "shot_assembly_manifest.json",
        force_shot_id=force_shot_id,
    )
    update_scene_asset(project_id, scene_order, "video", clip_path)
    return update_scene_generation_meta(project_id, scene_order, shot_generation_meta, shot_plan)


def rerender_scene_image(project_id: str, scene_order: int) -> dict[str, Any]:
    load_env_file()
    try:
        with project_lock(project_id):
            from backend.character_manager import scene_with_character_context
            from backend.project_runtime import (
                _append_scene_history,
                _capture_scene_snapshot_locked,
                _save_project_with_scene_event,
                apply_project_episode_pacing,
                load_project,
            )

            project = load_project(project_id)
            scene = next(
                (
                    item
                    for item in project.get("scenes", [])
                    if int(item.get("order", 0)) == scene_order
                ),
                None,
            )
            if scene is None:
                raise KeyError(f"Scene {scene_order} not found")
            _ensure_scene_renderable(scene, scene_order)
            settings = project.get("settings", {})
            keyframe_provider = str(settings.get("keyframe_provider") or "auto")
            apply_project_episode_pacing(project)
            scene_obj = _scene_from_payload(scene_with_character_context(project, scene))
            directory = scene_dir(project_id, scene["scene_id"])
            directory.mkdir(parents=True, exist_ok=True)
            _capture_scene_snapshot_locked(project_id, scene_order, "rerender-image", project)
            _append_scene_history(project, scene_order, "rerender-image", "running", "开始重绘图")
            _save_project_with_scene_event(project, scene_order)
        image_path = generate_keyframe(scene_obj, directory, keyframe_provider)
        if getattr(scene_obj, "consistency_meta", None):
            update_scene_consistency_meta(
                project_id,
                scene_order,
                scene_obj.consistency_meta,
                scene_obj.primary_reference_meta,
            )
        result = update_scene_asset(project_id, scene_order, "image", image_path)
        with project_lock(project_id):
            project = load_project(project_id)
            _append_scene_history(project, scene_order, "rerender-image", "done", "重绘图完成")
            _save_project_with_scene_event(project, scene_order)
        return result
    except Exception as exc:
        if "scene_obj" in locals() and getattr(scene_obj, "consistency_meta", None):
            try:
                update_scene_consistency_meta(
                    project_id,
                    scene_order,
                    scene_obj.consistency_meta,
                    scene_obj.primary_reference_meta,
                )
            except Exception as meta_exc:
                print(
                    f"[consistency] failed to persist scene meta for {project_id}#{scene_order}: {meta_exc}"
                )
        with project_lock(project_id):
            from backend.project_runtime import (
                _append_scene_history,
                _save_project_with_scene_event,
                load_project,
            )

            project = load_project(project_id)
            _append_scene_history(
                project, scene_order, "rerender-image", "failed", f"重绘图失败：{exc}"
            )
            _save_project_with_scene_event(project, scene_order)
        raise


def rerender_scene_audio(project_id: str, scene_order: int) -> dict[str, Any]:
    load_env_file()
    ffmpeg = get_ffmpeg_exe()
    try:
        with project_lock(project_id):
            from backend.character_manager import scene_with_character_context
            from backend.project_runtime import (
                _append_scene_history,
                _capture_scene_snapshot_locked,
                _save_project_with_scene_event,
                apply_project_episode_pacing,
                load_project,
                project_audio_style,
                project_subtitle_style,
            )

            project = load_project(project_id)
            scene = next(
                (
                    item
                    for item in project.get("scenes", [])
                    if int(item.get("order", 0)) == scene_order
                ),
                None,
            )
            if scene is None:
                raise KeyError(f"Scene {scene_order} not found")
            _ensure_scene_renderable(scene, scene_order)
            settings = project.get("settings", {})
            voice_provider = str(settings.get("voice_provider") or "auto")
            subtitle_style = project_subtitle_style(project)
            audio_style = project_audio_style(project)
            apply_project_episode_pacing(project)
            scene_obj = _scene_from_payload(scene_with_character_context(project, scene))
            directory = scene_dir(project_id, scene["scene_id"])
            directory.mkdir(parents=True, exist_ok=True)
            _capture_scene_snapshot_locked(project_id, scene_order, "rerender-audio", project)
            _append_scene_history(project, scene_order, "rerender-audio", "running", "开始重配音")
            _save_project_with_scene_event(project, scene_order)
        voice_path, _ = render_voice_track(
            ffmpeg,
            scene_obj,
            directory,
            voice_provider,
            subtitle_style=subtitle_style,
            audio_style=audio_style,
        )
        result = update_scene_asset(project_id, scene_order, "audio", voice_path)
        with project_lock(project_id):
            from backend.project_runtime import (
                _append_scene_history,
                _save_project_with_scene_event,
                load_project,
            )

            project = load_project(project_id)
            _append_scene_history(project, scene_order, "rerender-audio", "done", "重配音完成")
            _save_project_with_scene_event(project, scene_order)
        return result
    except Exception as exc:
        with project_lock(project_id):
            from backend.project_runtime import (
                _append_scene_history,
                _save_project_with_scene_event,
                load_project,
            )

            project = load_project(project_id)
            _append_scene_history(
                project, scene_order, "rerender-audio", "failed", f"重配音失败：{exc}"
            )
            _save_project_with_scene_event(project, scene_order)
        raise


def rerender_scene_video(project_id: str, scene_order: int) -> dict[str, Any]:
    load_env_file()
    ffmpeg = get_ffmpeg_exe()
    try:
        with project_lock(project_id):
            from backend.character_manager import scene_with_character_context
            from backend.project_runtime import (
                _append_scene_history,
                _capture_scene_snapshot_locked,
                _save_project_with_scene_event,
                apply_project_episode_pacing,
                load_project,
                project_audio_style,
                project_subtitle_style,
            )

            project = load_project(project_id)
            scene = next(
                (
                    item
                    for item in project.get("scenes", [])
                    if int(item.get("order", 0)) == scene_order
                ),
                None,
            )
            if scene is None:
                raise KeyError(f"Scene {scene_order} not found")
            _ensure_scene_renderable(scene, scene_order)
            settings = project.get("settings", {})
            keyframe_provider = str(settings.get("keyframe_provider") or "auto")
            video_provider = str(settings.get("video_provider") or "auto")
            voice_provider = str(settings.get("voice_provider") or "auto")
            subtitle_style = project_subtitle_style(project)
            audio_style = project_audio_style(project)
            apply_project_episode_pacing(project)
            scene_obj = _scene_from_payload(scene_with_character_context(project, scene))
            render_scene_plan_source = deepcopy(scene)
            directory = scene_dir(project_id, scene["scene_id"])
            directory.mkdir(parents=True, exist_ok=True)
            _capture_scene_snapshot_locked(project_id, scene_order, "rerender-video", project)
            _append_scene_history(project, scene_order, "rerender-video", "running", "开始重合成")
            _save_project_with_scene_event(project, scene_order)
        image_path = scene_latest_path(project_id, scene, "image")
        if image_path is None or not image_path.exists():
            image_path = generate_keyframe(scene_obj, directory, keyframe_provider)
            if getattr(scene_obj, "consistency_meta", None):
                update_scene_consistency_meta(
                    project_id,
                    scene_order,
                    scene_obj.consistency_meta,
                    scene_obj.primary_reference_meta,
                )
            update_scene_asset(project_id, scene_order, "image", image_path)
        audio_path, _ = render_voice_track(
            ffmpeg,
            scene_obj,
            directory,
            voice_provider,
            subtitle_style=subtitle_style,
            audio_style=audio_style,
        )
        update_scene_asset(project_id, scene_order, "audio", audio_path)
        synced_duration = max(
            0.25, round(wav_duration(audio_path) if audio_path.exists() else scene_obj.duration, 1)
        )
        sync_scene_duration(project_id, scene_order, synced_duration)
        scene_obj.duration = synced_duration
        clip_duration = max(
            scene_obj.duration,
            wav_duration(audio_path) if audio_path.exists() else scene_obj.duration,
        )
        if video_render_granularity(project_settings=settings) == "shot":
            try:
                result = _render_shot_level_scene_clip(
                    project_id=project_id,
                    scene=scene,
                    shot_plan_source=render_scene_plan_source,
                    scene_order=scene_order,
                    scene_obj=scene_obj,
                    directory=directory,
                    image_path=image_path,
                    clip_duration=clip_duration,
                    ffmpeg=ffmpeg,
                    video_provider=video_provider,
                    settings=settings,
                )
            except Exception as exc:
                if video_fallback_mode(video_provider) == "strict":
                    raise _strict_video_context_error(
                        scene, scene_order, video_provider, exc
                    ) from exc
                raise
        else:
            try:
                clip_path, render_result = render_clip_with_meta(
                    ffmpeg,
                    scene_obj,
                    directory,
                    keyframe_provider,
                    voice_provider,
                    clip_duration,
                    audio_path,
                    subtitle_style,
                    audio_style,
                    project_dir(project_id),
                    keyframe_path=image_path,
                    video_provider=video_provider,
                )
            except Exception as exc:
                if video_fallback_mode(video_provider) == "strict":
                    raise _strict_video_context_error(
                        scene, scene_order, video_provider, exc
                    ) from exc
                raise
            update_scene_asset(project_id, scene_order, "video", clip_path)
            scene_for_plan = {**scene, "duration_seconds": clip_duration}
            generation_meta = generation_meta_from_result(
                render_result,
                requested_provider=video_provider,
                fallback_mode=video_fallback_mode(video_provider),
            )
            result = update_scene_generation_meta(
                project_id, scene_order, generation_meta, build_shot_plan(scene_for_plan)
            )
        _evaluate_and_persist_scene_governance(project_id, scene_order, image_path)
        with project_lock(project_id):
            from backend.project_runtime import (
                _append_scene_history,
                _save_project_with_scene_event,
                load_project,
            )

            project = load_project(project_id)
            _append_scene_history(project, scene_order, "rerender-video", "done", "重合成完成")
            result = _save_project_with_scene_event(project, scene_order)
        return result
    except Exception as exc:
        if "scene_obj" in locals() and getattr(scene_obj, "consistency_meta", None):
            try:
                update_scene_consistency_meta(
                    project_id,
                    scene_order,
                    scene_obj.consistency_meta,
                    scene_obj.primary_reference_meta,
                )
            except Exception as meta_exc:
                print(
                    f"[consistency] failed to persist scene meta for {project_id}#{scene_order}: {meta_exc}"
                )
        with project_lock(project_id):
            from backend.project_runtime import (
                _append_scene_history,
                _save_project_with_scene_event,
                load_project,
            )

            project = load_project(project_id)
            _append_scene_history(
                project, scene_order, "rerender-video", "failed", f"Video generation failed: {exc}"
            )
        _save_project_with_scene_event(project, scene_order)
        raise


def rerender_scene_shot_video(project_id: str, scene_order: int, shot_id: str) -> dict[str, Any]:
    """Rerender one shot and reassemble the scene clip, reusing unchanged shots."""
    normalized_shot_id = str(shot_id or "").strip()
    if not normalized_shot_id:
        raise ValueError("shot_id is required")
    load_env_file()
    ffmpeg = get_ffmpeg_exe()
    try:
        with project_lock(project_id):
            from backend.character_manager import scene_with_character_context
            from backend.project_runtime import (
                _append_scene_history,
                _capture_scene_snapshot_locked,
                _save_project_with_scene_event,
                apply_project_episode_pacing,
                load_project,
                project_audio_style,
                project_subtitle_style,
            )

            project = load_project(project_id)
            scene = next(
                (
                    item
                    for item in project.get("scenes", [])
                    if int(item.get("order", 0)) == scene_order
                ),
                None,
            )
            if scene is None:
                raise KeyError(f"Scene {scene_order} not found")
            _ensure_scene_renderable(scene, scene_order)
            settings = project.get("settings", {})
            if video_render_granularity(project_settings=settings) != "shot":
                raise ValueError("Targeted shot rerender requires video_render_granularity=shot")
            video_provider = str(settings.get("video_provider") or "auto")
            keyframe_provider = str(settings.get("keyframe_provider") or "auto")
            voice_provider = str(settings.get("voice_provider") or "auto")
            subtitle_style = project_subtitle_style(project)
            audio_style = project_audio_style(project)
            apply_project_episode_pacing(project)
            scene_obj = _scene_from_payload(scene_with_character_context(project, scene))
            render_scene_plan_source = deepcopy(scene)
            directory = scene_dir(project_id, scene["scene_id"])
            directory.mkdir(parents=True, exist_ok=True)
            shot_plan = _scene_shot_plan(render_scene_plan_source)
            known_shot_ids = {
                str(shot.get("shot_id") or "").strip()
                for shot in shot_plan.get("shots", [])
                if isinstance(shot, dict)
            }
            if normalized_shot_id not in known_shot_ids:
                raise KeyError(f"Shot {normalized_shot_id} not found")
            _capture_scene_snapshot_locked(project_id, scene_order, "rerender-shot-video", project)
            _append_scene_history(
                project,
                scene_order,
                "rerender-shot-video",
                "running",
                f"开始重合成镜头 {normalized_shot_id}",
            )
            _save_project_with_scene_event(project, scene_order)

        image_path = scene_latest_path(project_id, scene, "image")
        if image_path is None or not image_path.exists():
            image_path = generate_keyframe(scene_obj, directory, keyframe_provider)
            if getattr(scene_obj, "consistency_meta", None):
                update_scene_consistency_meta(
                    project_id,
                    scene_order,
                    scene_obj.consistency_meta,
                    scene_obj.primary_reference_meta,
                )
            update_scene_asset(project_id, scene_order, "image", image_path)

        audio_path = scene_latest_path(project_id, scene, "audio")
        has_dialogue = bool(str(scene.get("dialogue") or "").strip())
        if audio_path is None or not audio_path.exists():
            if has_dialogue:
                audio_path, _ = render_voice_track(
                    ffmpeg,
                    scene_obj,
                    directory,
                    voice_provider,
                    subtitle_style=subtitle_style,
                    audio_style=audio_style,
                )
                update_scene_asset(project_id, scene_order, "audio", audio_path)
            else:
                audio_path = None

        audio_duration = wav_duration(audio_path) if audio_path and audio_path.exists() else 0.0
        clip_duration = max(float(scene_obj.duration or 0.0), audio_duration, 0.25)
        sync_scene_duration(project_id, scene_order, clip_duration)
        scene_obj.duration = clip_duration
        try:
            result = _render_shot_level_scene_clip(
                project_id=project_id,
                scene=scene,
                shot_plan_source=render_scene_plan_source,
                scene_order=scene_order,
                scene_obj=scene_obj,
                directory=directory,
                image_path=image_path,
                clip_duration=clip_duration,
                ffmpeg=ffmpeg,
                video_provider=video_provider,
                settings=settings,
                force_shot_id=normalized_shot_id,
                reuse_cache=True,
            )
        except Exception as exc:
            if video_fallback_mode(video_provider) == "strict":
                raise _strict_video_context_error(scene, scene_order, video_provider, exc) from exc
            raise
        _evaluate_and_persist_scene_governance(project_id, scene_order, image_path)
        with project_lock(project_id):
            from backend.project_runtime import (
                _append_scene_history,
                _save_project_with_scene_event,
                load_project,
            )

            project = load_project(project_id)
            _append_scene_history(
                project,
                scene_order,
                "rerender-shot-video",
                "done",
                f"镜头 {normalized_shot_id} 重合成完成",
            )
            result = _save_project_with_scene_event(project, scene_order)
        return result
    except Exception as exc:
        if "scene_obj" in locals() and getattr(scene_obj, "consistency_meta", None):
            try:
                update_scene_consistency_meta(
                    project_id,
                    scene_order,
                    scene_obj.consistency_meta,
                    scene_obj.primary_reference_meta,
                )
            except Exception as meta_exc:
                print(
                    f"[consistency] failed to persist scene meta for {project_id}#{scene_order}: {meta_exc}"
                )
        with project_lock(project_id):
            from backend.project_runtime import (
                _append_scene_history,
                _save_project_with_scene_event,
                load_project,
            )

            project = load_project(project_id)
            _append_scene_history(
                project,
                scene_order,
                "rerender-shot-video",
                "failed",
                f"Shot video generation failed: {exc}",
            )
            _save_project_with_scene_event(project, scene_order)
        raise


def generate_scene_assets(project_id: str, scene_order: int) -> dict[str, Any]:
    load_env_file()
    ffmpeg = get_ffmpeg_exe()
    try:
        with project_lock(project_id):
            from backend.character_manager import scene_with_character_context
            from backend.project_runtime import (
                _append_scene_history,
                _capture_scene_snapshot_locked,
                _save_project_with_scene_event,
                apply_project_episode_pacing,
                load_project,
                project_audio_style,
                project_subtitle_style,
            )

            project = load_project(project_id)
            scene = next(
                (
                    item
                    for item in project.get("scenes", [])
                    if int(item.get("order", 0)) == scene_order
                ),
                None,
            )
            if scene is None:
                raise KeyError(f"Scene {scene_order} not found")
            _ensure_scene_renderable(scene, scene_order)
            settings = project.get("settings", {})
            keyframe_provider = str(settings.get("keyframe_provider") or "auto")
            video_provider = str(settings.get("video_provider") or "auto")
            voice_provider = str(settings.get("voice_provider") or "auto")
            subtitle_style = project_subtitle_style(project)
            audio_style = project_audio_style(project)
            apply_project_episode_pacing(project)
            scene_obj = _scene_from_payload(scene_with_character_context(project, scene))
            render_scene_plan_source = deepcopy(scene)
            directory = scene_dir(project_id, scene["scene_id"])
            directory.mkdir(parents=True, exist_ok=True)
            _capture_scene_snapshot_locked(project_id, scene_order, "rebuild", project)
            _append_scene_history(project, scene_order, "rebuild", "running", "开始整格重跑")
            _save_project_with_scene_event(project, scene_order)

        image_path = generate_keyframe(scene_obj, directory, keyframe_provider)
        if getattr(scene_obj, "consistency_meta", None):
            update_scene_consistency_meta(
                project_id,
                scene_order,
                scene_obj.consistency_meta,
                scene_obj.primary_reference_meta,
            )
        update_scene_asset(project_id, scene_order, "image", image_path)

        voice_path, voice_duration = render_voice_track(
            ffmpeg,
            scene_obj,
            directory,
            voice_provider,
            subtitle_style=subtitle_style,
            audio_style=audio_style,
        )
        update_scene_asset(project_id, scene_order, "audio", voice_path)

        clip_duration = max(scene_obj.duration, voice_duration)
        if video_render_granularity(project_settings=settings) == "shot":
            try:
                _render_shot_level_scene_clip(
                    project_id=project_id,
                    scene=scene,
                    shot_plan_source=render_scene_plan_source,
                    scene_order=scene_order,
                    scene_obj=scene_obj,
                    directory=directory,
                    image_path=image_path,
                    clip_duration=clip_duration,
                    ffmpeg=ffmpeg,
                    video_provider=video_provider,
                    settings=settings,
                )
            except Exception as exc:
                if video_fallback_mode(video_provider) == "strict":
                    raise _strict_video_context_error(
                        scene, scene_order, video_provider, exc
                    ) from exc
                raise
        else:
            try:
                clip_path, render_result = render_clip_with_meta(
                    ffmpeg,
                    scene_obj,
                    directory,
                    keyframe_provider,
                    voice_provider,
                    clip_duration,
                    voice_path,
                    subtitle_style,
                    audio_style,
                    project_dir(project_id),
                    keyframe_path=image_path,
                    video_provider=video_provider,
                )
            except Exception as exc:
                if video_fallback_mode(video_provider) == "strict":
                    raise _strict_video_context_error(
                        scene, scene_order, video_provider, exc
                    ) from exc
                raise
            update_scene_asset(project_id, scene_order, "video", clip_path)
            scene_for_plan = {**scene, "duration_seconds": clip_duration}
            generation_meta = generation_meta_from_result(
                render_result,
                requested_provider=video_provider,
                fallback_mode=video_fallback_mode(video_provider),
            )
            update_scene_generation_meta(
                project_id, scene_order, generation_meta, build_shot_plan(scene_for_plan)
            )
        _evaluate_and_persist_scene_governance(project_id, scene_order, image_path)
        with project_lock(project_id):
            from backend.project_runtime import (
                _append_scene_history,
                _save_project_with_scene_event,
                load_project,
            )

            project = load_project(project_id)
            _append_scene_history(project, scene_order, "rebuild", "done", "整格重跑完成")
            _save_project_with_scene_event(project, scene_order)
        from backend.project_runtime import load_project

        return load_project(project_id)
    except Exception as exc:
        if "scene_obj" in locals() and getattr(scene_obj, "consistency_meta", None):
            try:
                update_scene_consistency_meta(
                    project_id,
                    scene_order,
                    scene_obj.consistency_meta,
                    scene_obj.primary_reference_meta,
                )
            except Exception as meta_exc:
                print(
                    f"[consistency] failed to persist scene meta for {project_id}#{scene_order}: {meta_exc}"
                )
        with project_lock(project_id):
            from backend.project_runtime import (
                _append_scene_history,
                _save_project_with_scene_event,
                load_project,
            )

            project = load_project(project_id)
            _append_scene_history(
                project, scene_order, "rebuild", "failed", f"Video generation failed: {exc}"
            )
            _save_project_with_scene_event(project, scene_order)
        raise


def _scene_validation_blocked(scene: dict[str, Any]) -> str | None:
    if bool(scene.get("validation_failed")):
        return str(scene.get("error_message") or "Scene validation failed").strip()
    assets = scene.get("assets", {})
    if isinstance(assets, dict) and str(assets.get("status") or "").lower() == "failed":
        return str(scene.get("error_message") or "Scene validation failed").strip()
    return None


def _scene_validation_resolved(scene: dict[str, Any]) -> bool:
    visual = str(scene.get("visual_prompt") or "").strip()
    if not visual:
        return False
    try:
        duration = float(scene.get("duration_seconds") or 0)
    except (TypeError, ValueError):
        return False
    if duration <= 0:
        return False
    if not isinstance(scene.get("characters"), list):
        return False
    try:
        camera_speed = float(scene.get("camera_speed") or 0)
    except (TypeError, ValueError):
        return False
    if not 0.35 <= camera_speed <= 3.0:
        return False
    audio_manifest = scene.get("audio_manifest")
    if not isinstance(audio_manifest, dict):
        return False
    if not isinstance(audio_manifest.get("sfx_trigger"), dict):
        return False
    camera = str(scene.get("camera_movement") or "").strip()
    if not camera:
        return False
    return True


def _ensure_scene_renderable(scene: dict[str, Any], scene_order: int) -> None:
    reason = _scene_validation_blocked(scene)
    if reason:
        raise ValueError(f"Scene {scene_order} is invalid and cannot be rendered: {reason}")
