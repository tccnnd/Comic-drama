from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Callable

from fastapi import HTTPException

from backend.logger import get_logger
from backend.project_runtime import load_project, project_snapshot, update_runtime

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs"
FRONTEND = ROOT / "frontend"
DEFAULT_STORY = ROOT / "inputs" / "sample_story.txt"
WORKFLOW_SCRIPT = ROOT / "scripts" / "run_workflow.py"


def configured_cors_origins() -> list[str]:
    raw = os.environ.get("APP_CORS_ORIGINS", "").strip()
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]


def _format_sse(event: str, data: object, event_id: str | None = None) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    for line in payload.splitlines() or [""]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


def default_story_text() -> str:
    return DEFAULT_STORY.read_text(encoding="utf-8")


def spawn_background_job(target, *args) -> None:
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()


def run_background_job(
    project_id: str,
    stage: str,
    message: str,
    action: Callable[[], None],
    fail_message: str,
    error_log: str,
    error_args: tuple = (),
    *,
    update_on_success: bool = True,
) -> None:
    """Schedule a background job with standard runtime status updates."""
    update_runtime(project_id, status="running", stage=stage, message=message, progress=1)

    def _run() -> None:
        try:
            action()
            if update_on_success:
                update_runtime(project_id, status="ready", stage="done", message="Completed", progress=100)
        except Exception as exc:
            update_runtime(project_id, status="failed", stage="failed", message=fail_message)
            logger.error(error_log, *error_args, exc)

    spawn_background_job(_run)


def project_or_404(project_id: str) -> dict:
    try:
        return project_snapshot(load_project(project_id))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
