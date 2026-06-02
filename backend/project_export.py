"""Export and build logic for final video assembly."""
from __future__ import annotations

import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.run_workflow import (
    generate_keyframe,
    load_env_file,
    render_clip,
    render_voice_track,
    stitch_scene_subtitles,
    wav_duration,
)

from backend.project_models import (
    ExportAssetReadinessError,
    _scene_from_payload,
    get_ffmpeg_exe,
    project_dir,
    project_lock,
    scene_dir,
    utc_iso,
)
from backend.scene_renderer import (
    _scene_assets,
    fallback_scene_clip_path,
    scene_asset_file_exists,
    scene_latest_path,
    update_scene_asset,
    update_scene_consistency_meta,
    sync_scene_duration,
)


def _export_issue_item(scene: dict[str, Any], missing: list[str]) -> dict[str, Any]:
    return {
        "order": int(scene.get("order") or 0),
        "scene_id": str(scene.get("scene_id") or ""),
        "title": str(scene.get("title") or ""),
        "missing": missing,
    }


def validate_export_assets(project_id: str, scenes: list[dict[str, Any]]) -> None:
    items: list[dict[str, Any]] = []
    totals = {"image": 0, "audio": 0, "video": 0}
    if not scenes:
        raise ExportAssetReadinessError(
            {
                "code": "EXPORT_ASSET_NOT_READY",
                "message": "导出前素材未就绪",
                "items": [],
                "totals": totals,
            }
        )
    for scene in scenes:
        missing: list[str] = []
        if not scene_asset_file_exists(project_id, scene, "image"):
            missing.append("image")
        try:
            clip_path = scene_latest_path(project_id, scene, "video")
        except ValueError:
            clip_path = None
        has_video = bool(clip_path and clip_path.is_file()) or fallback_scene_clip_path(project_id, scene).is_file()
        if not has_video:
            missing.append("video")
        if str(scene.get("dialogue") or "").strip():
            if not scene_asset_file_exists(project_id, scene, "audio"):
                missing.append("audio")
        if missing:
            for kind in missing:
                totals[kind] += 1
            items.append(_export_issue_item(scene, missing))
    if items:
        raise ExportAssetReadinessError(
            {
                "code": "EXPORT_ASSET_NOT_READY",
                "message": "导出前素材未就绪",
                "items": items,
                "totals": totals,
            }
        )


def export_project(project_id: str) -> dict[str, Any]:
    load_env_file()
    ffmpeg = get_ffmpeg_exe()
    with project_lock(project_id):
        from backend.project_runtime import load_project, project_subtitle_style, _set_runtime, _save_project_with_project_event, project_snapshot
        from backend.character_manager import scene_with_character_context
        project = load_project(project_id)
        scenes = list(project.get("scenes", []))
        subtitle_style = project_subtitle_style(project)
        validate_export_assets(project_id, scenes)
    clips: list[Path] = []
    subtitle_files: list[Path] = []
    clip_durations: list[float] = []
    for scene in scenes:
        try:
            clip_path = scene_latest_path(project_id, scene, "video")
        except ValueError as exc:
            raise ExportAssetReadinessError(
                {
                    "code": "EXPORT_ASSET_NOT_READY",
                    "message": "导出前素材未就绪",
                    "items": [],
                    "totals": {},
                    "error": str(exc),
                }
            ) from exc
        if clip_path is None or not clip_path.exists():
            clip_path = scene_dir(project_id, scene["scene_id"]) / "clip.mp4"
        if not clip_path.exists():
            raise FileNotFoundError(f"Missing scene video: {scene.get('scene_id')}")
        clips.append(clip_path)
        try:
            audio_path = scene_latest_path(project_id, scene, "audio")
        except ValueError:
            audio_path = None
        audio_duration = wav_duration(audio_path) if audio_path and audio_path.exists() else float(scene.get("duration_seconds") or 0.0)
        clip_durations.append(max(float(scene.get("duration_seconds") or 0.0), audio_duration))
        subtitle_files.append(scene_dir(project_id, scene["scene_id"]) / f"scene_{int(scene.get('order') or 1):02d}_dialogue.srt")

    output_dir = project_dir(project_id) / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    final_video = output_dir / "final_episode.mp4"
    final_subtitles = output_dir / "subtitles.srt"
    final_subtitles_ass = output_dir / "subtitles.ass"
    concat_file = output_dir / "concat.txt"
    local_clips: list[Path] = []
    for scene, clip in zip(scenes, clips):
        local_clip = output_dir / f"{scene['scene_id']}.mp4"
        shutil.copy2(clip, local_clip)
        local_clips.append(local_clip)
    lines = [f"file '{clip.name}'" for clip in local_clips]
    concat_file.write_text("\n".join(lines), encoding="utf-8")
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        str(final_video),
    ]
    result = subprocess.run(cmd, cwd=output_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed while concatenating clips:\n{result.stderr}")
    stitch_scene_subtitles(
        subtitle_files,
        clip_durations,
        final_subtitles,
        fallback_scenes=[_scene_from_payload(scene_with_character_context(project, scene)) for scene in scenes],
        ass_path=final_subtitles_ass,
        subtitle_style=subtitle_style,
    )
    with project_lock(project_id):
        project = load_project(project_id)
        project["output"]["final_video_path"] = str(final_video.relative_to(project_dir(project_id))).replace("\\", "/")
        project["output"]["subtitles_path"] = str(final_subtitles.relative_to(project_dir(project_id))).replace("\\", "/")
        project["output"]["subtitles_ass_path"] = str(final_subtitles_ass.relative_to(project_dir(project_id))).replace("\\", "/")
        project["output"]["status"] = "completed"
        _set_runtime(project, status="ready", progress=100, stage="done", message="Export completed")
        _save_project_with_project_event(project)
        return project_snapshot(project)


def build_project(project_id: str) -> dict[str, Any]:
    load_env_file()
    ffmpeg = get_ffmpeg_exe()
    current_scene_order: int | None = None
    try:
        with project_lock(project_id):
            from backend.project_runtime import load_project, _set_runtime, _save_project_with_project_event, _append_scene_history, _save_project_with_scene_event, apply_project_episode_pacing, project_subtitle_style, project_audio_style, project_snapshot
            from backend.character_manager import scene_with_character_context
            from backend.scene_renderer import _ensure_scene_renderable
            project = load_project(project_id)
            settings = project.get("settings", {})
            keyframe_provider = str(settings.get("keyframe_provider") or "auto")
            video_provider = str(settings.get("video_provider") or "auto")
            voice_provider = str(settings.get("voice_provider") or "auto")
            subtitle_style = project_subtitle_style(project)
            audio_style = project_audio_style(project)
            apply_project_episode_pacing(project)
            scene_payloads = [deepcopy(scene) for scene in project.get("scenes", [])]
            for payload in scene_payloads:
                _ensure_scene_renderable(payload, int(payload.get("order") or 0))
            scenes = [_scene_from_payload(scene_with_character_context(project, scene)) for scene in scene_payloads]
            _set_runtime(project, status="running", progress=5, stage="rendering", message="Rendering calibrated scenes")
            _save_project_with_project_event(project)

        if not scenes:
            raise ValueError("Project has no scenes to render")

        built_clips: list[Path] = []
        subtitle_files: list[Path] = []
        clip_durations: list[float] = []
        total = max(1, len(scenes))
        for index, scene_obj in enumerate(scenes, start=1):
            current_scene_order = index
            with project_lock(project_id):
                from backend.project_runtime import load_project, _set_runtime, _save_project_with_project_event
                project = load_project(project_id)
                _set_runtime(
                    project,
                    status="running",
                    progress=int(((index - 1) / total) * 85) + 5,
                    stage=f"scene_{index:03d}",
                    message=f"Rendering scene {index}/{total}",
                )
                _save_project_with_project_event(project)

            scene_dir_path = scene_dir(project_id, f"scene_{index:03d}")
            scene_dir_path.mkdir(parents=True, exist_ok=True)
            image_path = generate_keyframe(scene_obj, scene_dir_path, keyframe_provider)
            if getattr(scene_obj, "consistency_meta", None):
                update_scene_consistency_meta(project_id, current_scene_order, scene_obj.consistency_meta, scene_obj.primary_reference_meta)
            voice_path, voice_duration = render_voice_track(
                ffmpeg,
                scene_obj,
                scene_dir_path,
                voice_provider,
                subtitle_style=subtitle_style,
                audio_style=audio_style,
            )
            synced_duration = max(0.25, round(float(voice_duration), 1))
            sync_scene_duration(project_id, current_scene_order, synced_duration)
            scene_obj.duration = synced_duration
            clip_duration = max(scene_obj.duration, voice_duration)
            subtitle_path = scene_dir_path / f"scene_{index:02d}_dialogue.srt"
            clip_path = render_clip(
                ffmpeg,
                scene_obj,
                scene_dir_path,
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
            update_scene_asset(project_id, current_scene_order, "image", image_path)
            update_scene_asset(project_id, current_scene_order, "audio", voice_path)
            update_scene_asset(project_id, current_scene_order, "video", clip_path)
            subtitle_files.append(subtitle_path)
            clip_durations.append(clip_duration)
            with project_lock(project_id):
                from backend.project_runtime import load_project, _append_scene_history, _save_project_with_scene_event
                project = load_project(project_id)
                _append_scene_history(project, current_scene_order, "build", "done", f"整集生成完成：{index}/{total}")
                _save_project_with_scene_event(project, current_scene_order)
            built_clips.append(clip_path)

        output_dir = project_dir(project_id) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        final_video = output_dir / "final_episode.mp4"
        final_subtitles = output_dir / "subtitles.srt"
        final_subtitles_ass = output_dir / "subtitles.ass"
        concat_file = output_dir / "concat.txt"
        local_clips: list[Path] = []
        for scene, clip in zip(scenes, built_clips):
            local_clip = output_dir / f"scene_{scene.scene:03d}.mp4"
            shutil.copy2(clip, local_clip)
            local_clips.append(local_clip)
        lines = [f"file '{clip.name}'" for clip in local_clips]
        concat_file.write_text("\n".join(lines), encoding="utf-8")
        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(final_video),
        ]
        result = subprocess.run(cmd, cwd=output_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed while concatenating clips:\n{result.stderr}")
        stitch_scene_subtitles(
            subtitle_files,
            clip_durations,
            final_subtitles,
            fallback_scenes=scenes,
            ass_path=final_subtitles_ass,
            subtitle_style=subtitle_style,
        )

        with project_lock(project_id):
            from backend.project_runtime import load_project, _set_runtime, _save_project_with_project_event, project_snapshot
            project = load_project(project_id)
            project["output"]["final_video_path"] = str(final_video.relative_to(project_dir(project_id))).replace("\\", "/")
            project["output"]["subtitles_path"] = str(final_subtitles.relative_to(project_dir(project_id))).replace("\\", "/")
            project["output"]["subtitles_ass_path"] = str(final_subtitles_ass.relative_to(project_dir(project_id))).replace("\\", "/")
            project["output"]["status"] = "completed"
            _set_runtime(project, status="ready", progress=100, stage="done", message="Completed")
            _save_project_with_project_event(project)
            return project_snapshot(project)
    except Exception as exc:
        if current_scene_order is not None and "scene_obj" in locals() and getattr(scene_obj, "consistency_meta", None):
            try:
                update_scene_consistency_meta(project_id, current_scene_order, scene_obj.consistency_meta, scene_obj.primary_reference_meta)
            except Exception as meta_exc:
                print(f"[consistency] failed to persist scene meta for {project_id}#{current_scene_order}: {meta_exc}")
        with project_lock(project_id):
            from backend.project_runtime import load_project, _set_runtime, _append_scene_history, _save_project_with_project_event
            project = load_project(project_id)
            _set_runtime(project, status="failed", stage="failed", message="Build failed")
            if current_scene_order is not None:
                _append_scene_history(project, current_scene_order, "build", "failed", f"整集生成失败：{exc}")
            _save_project_with_project_event(project)
        raise
