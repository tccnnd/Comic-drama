from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.asset_retention import cleanup_project_versions
from backend.event_bus import project_event_bus
from backend.project_runtime import (
    WORKSPACE,
    create_project,
    delete_project,
    fallback_scene_clip_path,
)
from backend.project_runtime import list_projects as load_projects
from backend.project_runtime import (
    load_project,
    project_lock,
    project_snapshot,
    rerender_scene_audio,
    rerender_scene_image,
    rerender_scene_video,
    scene_asset_file_exists,
    scene_latest_path,
    update_project_fields,
)
from backend.routers._common import (
    _format_sse,
    default_story_text,
    project_or_404,
    run_background_job,
)
from backend.styles import get_default_style_id, get_style

router = APIRouter(tags=["projects"])


class CreateProjectRequest(BaseModel):
    title: str = ""
    story_text: str | None = None
    planner: Literal["auto", "rule", "llm"] = "auto"
    scene_count: int = Field(default=5, ge=1, le=12)
    keyframe_provider: Literal["auto", "local", "comfyui"] = "auto"
    video_provider: str = "auto"
    video_render_granularity: Literal["scene", "shot"] = "scene"
    voice_provider: Literal[
        "auto", "edge", "local", "silent", "cosyvoice", "gpt_sovits", "fish", "indextts"
    ] = "auto"


class UpdateProjectRequest(BaseModel):
    title: str | None = None
    story_text: str | None = None
    settings: dict | None = None
    characters: list | None = None


class UpdateProjectStyleRequest(BaseModel):
    style_id: str = Field(min_length=1)


class FillMissingAssetsRequest(BaseModel):
    kinds: list[Literal["image", "audio", "video"]] | None = None


def scene_missing_asset_kinds(project_id: str, scene: dict) -> list[str]:
    missing: list[str] = []
    if not scene_asset_file_exists(project_id, scene, "image"):
        missing.append("image")
    if str(scene.get("dialogue") or "").strip() and not scene_asset_file_exists(
        project_id, scene, "audio"
    ):
        missing.append("audio")
    try:
        video_path = scene_latest_path(project_id, scene, "video")
    except ValueError:
        video_path = None
    if (
        not (video_path and video_path.is_file())
        and not fallback_scene_clip_path(project_id, scene).is_file()
    ):
        missing.append("video")
    return missing


def fill_missing_assets(project_id: str, requested_kinds: set[str] | None = None) -> dict:
    requested = requested_kinds or {"image", "audio", "video"}
    with project_lock(project_id):
        project = load_project(project_id)
        scenes = sorted(project.get("scenes", []), key=lambda item: int(item.get("order", 0)))
    for scene in scenes:
        missing = scene_missing_asset_kinds(project_id, scene)
        order = int(scene.get("order") or 0)
        if "video" in requested and "video" in missing:
            rerender_scene_video(project_id, order)
            continue
        if "image" in requested and "image" in missing:
            rerender_scene_image(project_id, order)
        if "audio" in requested and "audio" in missing:
            rerender_scene_audio(project_id, order)
    return project_or_404(project_id)


@router.get("/api/projects")
def list_projects() -> list[dict]:
    return [project_snapshot(project) for project in load_projects()]


@router.post("/api/projects")
def create_project_endpoint(payload: CreateProjectRequest) -> dict:
    story_text = payload.story_text or default_story_text()
    project = create_project(
        title=payload.title,
        story_text=story_text,
        planner=payload.planner,
        scene_count=payload.scene_count,
        keyframe_provider=payload.keyframe_provider,
        video_provider=payload.video_provider,
        voice_provider=payload.voice_provider,
        video_render_granularity_value=payload.video_render_granularity,
    )
    return project_snapshot(project)


@router.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict:
    return project_or_404(project_id)


@router.get("/api/projects/{project_id}/style")
def get_project_style(project_id: str) -> dict:
    project = project_or_404(project_id)
    style_id = str(project.get("style_id") or get_default_style_id()).strip()
    try:
        style = get_style(style_id)
    except KeyError:
        style_id = get_default_style_id()
        style = get_style(style_id)
    return {"project_id": project_id, "style_id": style_id, "style": style.model_dump()}


@router.post("/api/projects/{project_id}/style")
def set_project_style(project_id: str, payload: UpdateProjectStyleRequest) -> dict:
    style_id = str(payload.style_id or "").strip()
    try:
        style = get_style(style_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Style not found")
    try:
        project = update_project_fields(project_id, {"style_id": style.id})
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "project_id": project_id,
        "style_id": style.id,
        "style": style.model_dump(),
        "project": project_snapshot(project),
    }


@router.get("/api/projects/{project_id}/events")
async def project_events(project_id: str, request: Request):
    project_or_404(project_id)
    queue = await project_event_bus.subscribe(project_id)

    async def event_generator():
        try:
            yield _format_sse("connected", {"project_id": project_id, "message": "SSE connected"})
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield _format_sse(event["type"], event, event["id"])
        finally:
            await project_event_bus.unsubscribe(project_id, queue)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)


@router.delete("/api/projects/{project_id}")
def delete_project_endpoint(project_id: str) -> dict:
    try:
        return delete_project(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/api/projects/{project_id}")
def patch_project(project_id: str, payload: UpdateProjectRequest) -> dict:
    updates = payload.model_dump(exclude_none=True)
    try:
        project = update_project_fields(project_id, updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return project_snapshot(project)


@router.post("/api/projects/{project_id}/fill-missing-assets")
def fill_missing_assets_endpoint(
    project_id: str, payload: FillMissingAssetsRequest | None = None
) -> dict:
    project_or_404(project_id)
    requested = set(payload.kinds) if payload and payload.kinds else {"image", "audio", "video"}
    run_background_job(
        project_id,
        stage="repairing",
        message="Filling missing assets",
        action=lambda: fill_missing_assets(project_id, requested),
        fail_message="Asset repair failed",
        error_log="asset repair failed for %s: %s",
        error_args=(project_id,),
    )
    return project_or_404(project_id)


@router.post("/api/projects/{project_id}/cleanup")
def cleanup_project_endpoint(project_id: str, keep: int = 1) -> dict:
    if keep < 1 or keep > 10:
        raise HTTPException(status_code=400, detail="keep must be between 1 and 10")
    try:
        with project_lock(project_id):
            project = load_project(project_id)
            result = cleanup_project_versions(WORKSPACE / project_id, project, keep=keep)
            snapshot = project_snapshot(load_project(project_id))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"ok": True, **result, "project": snapshot}
