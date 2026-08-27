from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.project_runtime import (
    derive_project_title,
    load_project,
    project_lock,
    project_snapshot,
    reconstruct_story_text_from_scenes,
    replace_project_storyboard,
    replace_project_storyboard_from_preview,
    save_project,
    scene_to_dict,
)
from backend.routers._common import project_or_404
from scripts.run_workflow import analyze_script_workflow

router = APIRouter(tags=["script"])


class ScriptRecognitionRequest(BaseModel):
    script_text: str = Field(default="", min_length=1)
    title: str | None = None
    script_hint: str | None = None
    planner: Literal["auto", "rule", "llm"] = "auto"
    max_scenes: int = Field(default=12, ge=1, le=24)


class ScriptPreviewApplyRequest(BaseModel):
    story_text: str = Field(default="", min_length=1)
    title: str | None = None
    planner: Literal["auto", "rule", "llm"] = "auto"
    planner_used: str | None = None
    max_scenes: int = Field(default=12, ge=1, le=24)
    analysis: dict | None = None
    scenes: list[dict] = Field(default_factory=list)


class ScriptPreviewResponse(BaseModel):
    title: str
    planner_used: str
    analysis: dict
    scenes: list[dict]


@router.post("/api/projects/{project_id}/recognize-script")
def recognize_script(project_id: str, payload: ScriptRecognitionRequest) -> dict:
    try:
        project = replace_project_storyboard(
            project_id=project_id,
            story_text=payload.script_text,
            planner=payload.planner,
            title=payload.title or "",
            max_scenes=payload.max_scenes,
            script_hint=payload.script_hint or "",
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return project_snapshot(project)


@router.post("/api/projects/{project_id}/recognize-script/preview")
def preview_recognize_script(project_id: str, payload: ScriptRecognitionRequest) -> dict:
    project_or_404(project_id)
    try:
        analysis, scenes, planner_used = analyze_script_workflow(
            payload.script_text,
            payload.planner,
            max_scenes=payload.max_scenes,
            script_hint=payload.script_hint or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    title = payload.title.strip() if payload.title else ""
    if not title:
        title = derive_project_title(payload.script_text)
    return {
        "title": title,
        "script_text": payload.script_text,
        "planner_used": planner_used,
        "analysis": analysis,
        "scenes": [scene_to_dict(scene, order) for order, scene in enumerate(scenes, start=1)],
    }


@router.post("/api/projects/{project_id}/apply-script-preview")
def apply_script_preview(project_id: str, payload: ScriptPreviewApplyRequest) -> dict:
    try:
        project = replace_project_storyboard_from_preview(
            project_id=project_id,
            draft=payload.model_dump(),
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return project_snapshot(project)


@router.post("/api/projects/{project_id}/repair-story-text")
def repair_story_text(project_id: str) -> dict:
    try:
        with project_lock(project_id):
            project = load_project(project_id)
            repaired = reconstruct_story_text_from_scenes(project)
            if not repaired:
                raise HTTPException(
                    status_code=409, detail="No scenes available to rebuild story text"
                )
            project["story_text"] = repaired
            save_project(project)
        return project_or_404(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
