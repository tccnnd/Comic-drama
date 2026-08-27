from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.project_models import project_dir
from backend.project_runtime import (
    ExportAssetReadinessError,
    build_project,
    export_project,
    load_project,
    project_snapshot,
)
from backend.routers._common import project_or_404, run_background_job

router = APIRouter(tags=["production"])


@router.post("/api/projects/{project_id}/build")
def build_project_endpoint(project_id: str) -> dict:
    project_or_404(project_id)
    run_background_job(
        project_id,
        stage="queued",
        message="Queued",
        action=lambda: build_project(project_id),
        fail_message="Failed",
        error_log="build failed for %s: %s",
        error_args=(project_id,),
        update_on_success=False,
    )
    return project_or_404(project_id)


@router.post("/api/projects/{project_id}/export")
def export_project_endpoint(project_id: str) -> dict:
    try:
        project = export_project(project_id)
    except FileNotFoundError as exc:
        message = str(exc)
        if message == "Project not found":
            raise HTTPException(status_code=404, detail="Project not found")
        raise HTTPException(status_code=409, detail={"code": "EXPORT_ASSET_NOT_READY", "message": message})
    except ExportAssetReadinessError as exc:
        raise HTTPException(status_code=409, detail=exc.detail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return project_snapshot(project)


@router.get("/api/projects/{project_id}/export-otio")
def export_otio(project_id: str) -> dict:
    """Export project timeline in OpenTimelineIO format."""
    try:
        project = load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    from backend.timeline_export import export_project_to_otio, save_otio_file
    proj_dir = project_dir(project_id)
    timeline = export_project_to_otio(project, proj_dir)
    output_path = proj_dir / "export" / f"{project_id}.otio"
    save_otio_file(timeline, output_path)
    return {
        "timeline": timeline,
        "file_path": str(output_path),
        "url": f"/workspace/{project_id}/export/{project_id}.otio",
    }


@router.get("/api/projects/{project_id}/cost-estimate")
def project_cost_estimate(project_id: str, provider: str = "") -> dict:
    """Estimate rendering cost for a project."""
    try:
        project = load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    from backend.provider_router import estimate_project_cost
    return estimate_project_cost(project, provider)
