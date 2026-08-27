from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.comfyui_health import check_character_consistency
from backend.consistency_validator import generate_consistency_report
from backend.project_runtime import (
    WORKSPACE,
    load_project,
    project_snapshot,
    update_character_fields,
    update_character_reference_image,
    write_data_url_image,
)
from backend.routers._common import project_or_404

router = APIRouter(tags=["characters"])


class CharacterPatchRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    meta: dict | None = None
    appearance_core: str | None = None
    clothing_style: str | None = None
    negative_constraints: str | None = None
    voice_profile: str | None = None
    voice_engine: str | None = None
    voice_id: str | None = None
    reference_audio_path: str | None = None
    reference_text: str | None = None
    emotion: str | None = None
    voice_rate: float | None = None
    voice_pitch: float | None = None
    voice_volume: float | None = None


class CharacterImageUploadRequest(BaseModel):
    filename: str = "reference.png"
    data_url: str


@router.get("/api/projects/{project_id}/characters/{char_name}/consistency-status")
def character_consistency_status(project_id: str, char_name: str) -> dict:
    try:
        project = load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return check_character_consistency(project, WORKSPACE / project_id, char_name)


@router.get("/api/projects/{project_id}/consistency-report")
def project_consistency_report(project_id: str) -> dict:
    """Generate a consistency validation report for all scenes in a project."""
    try:
        load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return generate_consistency_report(project_id)


@router.patch("/api/projects/{project_id}/characters/{char_index}")
def patch_character(project_id: str, char_index: int, payload: CharacterPatchRequest) -> dict:
    updates = payload.model_dump(exclude_none=True)
    project = update_character_fields(project_id, char_index, updates)
    return project_snapshot(project)


@router.post("/api/projects/{project_id}/characters/{char_index}/reference-image")
def upload_character_reference_image(project_id: str, char_index: int, payload: CharacterImageUploadRequest) -> dict:
    try:
        source_path = write_data_url_image(project_id, payload.filename, payload.data_url)
        project = update_character_reference_image(project_id, char_index, source_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return project_snapshot(project)
