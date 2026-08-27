from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.project_runtime import (
    generate_scene_assets,
    load_project,
    merge_scene_with_next,
    project_snapshot,
    rerender_scene_audio,
    rerender_scene_image,
    rerender_scene_shot_video,
    rerender_scene_video,
    restore_scene_snapshot,
    save_project,
    split_scene,
    update_scene_fields,
)
from backend.routers._common import project_or_404, run_background_job

router = APIRouter(tags=["scenes"])


class UpdateSceneRequest(BaseModel):
    title: str | None = None
    visual_prompt: str | None = None
    dialogue: str | None = None
    speaker: str | None = None
    voice_profile: str | None = None
    voice_engine: str | None = None
    voice_id: str | None = None
    reference_audio_path: str | None = None
    reference_text: str | None = None
    emotion: str | None = None
    voice_rate: float | None = None
    voice_pitch: float | None = None
    voice_volume: float | None = None
    camera_movement: str | None = None
    duration_seconds: float | None = None
    characters: list[str] | None = None
    crop_box: dict | None = None
    rhythm_preset: str | None = None
    sfx_type: str | None = None
    audio_manifest: dict | None = None
    subtitle_preset: str | None = None
    camera_intensity: float | None = None
    camera_speed: float | None = None
    shot_overrides: list[dict] | None = None
    episode_rhythm: Literal["classic_four_act", "fast_hook", "slow_burn"] | None = None
    episode_phase: Literal["opening", "setup", "reversal", "finale"] | None = None
    episode_phase_index: int | None = Field(default=None, ge=1, le=100)
    episode_phase_total: int | None = Field(default=None, ge=1, le=100)
    enhancement_mode: str | None = None
    enhancement_provider: str | None = None
    enhancement_prompt: str | None = None
    enhancement_workflow_path: str | None = None


@router.post("/api/projects/{project_id}/scenes/{scene_order}/candidates/{kind}/select")
def select_scene_candidate(project_id: str, scene_order: int, kind: str, candidate_id: str) -> dict:
    """Select a specific candidate for a scene asset."""
    try:
        project = load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    scene = next(
        (s for s in project.get("scenes", []) if int(s.get("order", 0)) == scene_order), None
    )
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    from backend.candidate_manager import get_scene_candidates, select_candidate

    candidates = get_scene_candidates(scene, kind)
    if not candidates:
        raise HTTPException(status_code=404, detail="No candidates found")
    selected = select_candidate(candidates, candidate_id)
    if not selected:
        raise HTTPException(status_code=404, detail="Candidate not found")
    # Save project with updated selection
    save_project(project)
    return {"selected": selected, "candidates": candidates}


@router.patch("/api/projects/{project_id}/scenes/{scene_order}")
def patch_scene(project_id: str, scene_order: int, payload: UpdateSceneRequest) -> dict:
    updates = payload.model_dump(exclude_none=True)
    project = update_scene_fields(project_id, scene_order, updates)
    return project_snapshot(project)


@router.post("/api/projects/{project_id}/scenes/{scene_order}/split")
def split_scene_endpoint(project_id: str, scene_order: int) -> dict:
    try:
        project = split_scene(project_id, scene_order)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except KeyError:
        raise HTTPException(status_code=404, detail="Scene not found")
    return project_snapshot(project)


@router.post("/api/projects/{project_id}/scenes/{scene_order}/merge-next")
def merge_scene_endpoint(project_id: str, scene_order: int) -> dict:
    try:
        project = merge_scene_with_next(project_id, scene_order)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except KeyError:
        raise HTTPException(status_code=404, detail="Next scene not found")
    return project_snapshot(project)


@router.post("/api/projects/{project_id}/scenes/{scene_order}/rerender-image")
def rerender_scene_image_endpoint(project_id: str, scene_order: int) -> dict:
    project_or_404(project_id)
    run_background_job(
        project_id,
        stage=f"scene_{scene_order:03d}_image",
        message="Rerendering image",
        action=lambda: rerender_scene_image(project_id, scene_order),
        fail_message="Image rerender failed",
        error_log="image rerender failed for %s scene %s: %s",
        error_args=(project_id, scene_order),
    )
    return project_or_404(project_id)


@router.post("/api/projects/{project_id}/scenes/{scene_order}/rerender-audio")
def rerender_scene_audio_endpoint(project_id: str, scene_order: int) -> dict:
    project_or_404(project_id)
    run_background_job(
        project_id,
        stage=f"scene_{scene_order:03d}_audio",
        message="Rerendering audio",
        action=lambda: rerender_scene_audio(project_id, scene_order),
        fail_message="Audio rerender failed",
        error_log="audio rerender failed for %s scene %s: %s",
        error_args=(project_id, scene_order),
    )
    return project_or_404(project_id)


@router.post("/api/projects/{project_id}/scenes/{scene_order}/rerender-video")
def rerender_scene_video_endpoint(project_id: str, scene_order: int) -> dict:
    project_or_404(project_id)
    run_background_job(
        project_id,
        stage=f"scene_{scene_order:03d}_video",
        message="Rerendering video",
        action=lambda: rerender_scene_video(project_id, scene_order),
        fail_message="Video rerender failed",
        error_log="video rerender failed for %s scene %s: %s",
        error_args=(project_id, scene_order),
    )
    return project_or_404(project_id)


@router.post("/api/projects/{project_id}/scenes/{scene_order}/shots/{shot_id}/rerender-video")
def rerender_scene_shot_video_endpoint(project_id: str, scene_order: int, shot_id: str) -> dict:
    project_or_404(project_id)
    run_background_job(
        project_id,
        stage=f"scene_{scene_order:03d}_shot_video",
        message="Rerendering shot video",
        action=lambda: rerender_scene_shot_video(project_id, scene_order, shot_id),
        fail_message="Shot video rerender failed",
        error_log="shot video rerender failed for %s scene %s shot %s: %s",
        error_args=(project_id, scene_order, shot_id),
    )
    return project_or_404(project_id)


@router.post("/api/projects/{project_id}/scenes/{scene_order}/rebuild")
def rebuild_scene_endpoint(project_id: str, scene_order: int) -> dict:
    project_or_404(project_id)
    run_background_job(
        project_id,
        stage=f"scene_{scene_order:03d}_rebuild",
        message="Rebuilding scene",
        action=lambda: generate_scene_assets(project_id, scene_order),
        fail_message="Scene rebuild failed",
        error_log="rebuild failed for %s scene %s: %s",
        error_args=(project_id, scene_order),
    )
    return project_or_404(project_id)


@router.post("/api/projects/{project_id}/scenes/{scene_order}/restore")
def restore_scene_endpoint(project_id: str, scene_order: int) -> dict:
    try:
        project = restore_scene_snapshot(project_id, scene_order)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="No snapshot available")
    except KeyError:
        raise HTTPException(status_code=404, detail="Scene not found")
    return project_snapshot(project)
