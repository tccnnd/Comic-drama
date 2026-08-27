from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.logger import get_logger
from backend.project_runtime import validate_task_id
from backend.routers._common import (
    OUTPUTS,
    ROOT,
    WORKFLOW_SCRIPT,
    configured_cors_origins,
    default_story_text,
)
from backend.task_store import TaskRecord, TaskStore
from backend.video_generation import normalize_video_render_granularity

logger = get_logger(__name__)

router = APIRouter(tags=["tasks"])

store = TaskStore()


class CreateTaskRequest(BaseModel):
    story_text: str | None = None
    planner: Literal["auto", "rule", "llm"] = "auto"
    scene_count: int = Field(default=5, ge=1, le=12)
    keyframe_provider: Literal["auto", "local", "comfyui"] = "auto"
    video_provider: str = "auto"
    video_render_granularity: Literal["scene", "shot"] = "scene"
    voice_provider: Literal["auto", "edge", "local", "silent", "cosyvoice", "gpt_sovits", "fish", "indextts"] = "auto"


class CreateTaskResponse(BaseModel):
    task_id: str
    status: str
    progress: int
    output_dir: str
    detail_url: str


def task_output_dir(task_id: str) -> Path:
    return OUTPUTS / validate_task_id(task_id)


def parse_progress(line: str) -> tuple[int, int, str] | None:
    match = re.match(r"^\[(\d+)/(\d+)\]\s*(.*)$", line.strip())
    if not match:
        return None
    step = int(match.group(1))
    total = int(match.group(2))
    message = match.group(3).strip()
    return step, total, message


def derive_progress(step: int, total: int) -> int:
    if total <= 0:
        return 0
    return max(0, min(100, int(step * 100 / total)))


def read_manifest(task_id: str) -> dict:
    manifest_path = task_output_dir(task_id) / "manifest.json"
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def run_workflow_task(task: TaskRecord, story_text: str) -> None:
    task_dir = task_output_dir(task.id)
    task_dir.mkdir(parents=True, exist_ok=True)
    story_path = task_dir / "story.txt"
    story_path.write_text(story_text, encoding="utf-8")
    store.update(task.id, stage="starting", message="Preparing workflow")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    cmd = [
        sys.executable,
        str(WORKFLOW_SCRIPT),
        "--story",
        str(story_path),
        "--run-id",
        task.id,
        "--planner",
        task.planner,
        "--scene-count",
        str(task.scene_count),
        "--keyframe-provider",
        task.keyframe_provider,
        "--video-provider",
        task.video_provider,
        "--video-render-granularity",
        task.video_render_granularity,
        "--voice-provider",
        task.voice_provider,
    ]

    store.update(task.id, status="running", stage="running", progress=1, message="Workflow started")
    process = subprocess.Popen(
        cmd,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )

    assert process.stdout is not None
    try:
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            if not line:
                continue
            store.append_log(task.id, line)
            progress_info = parse_progress(line)
            if progress_info:
                step, total, message = progress_info
                store.update(
                    task.id,
                    progress=derive_progress(step, total),
                    stage=message or "running",
                    message=message or "running",
                )
            elif line.startswith("[planner]"):
                store.update(task.id, stage="planning", message=line)
            elif "Rendering scene" in line:
                store.update(task.id, stage="rendering", message=line)
            elif "Concatenating clips" in line:
                store.update(task.id, stage="assembling", message=line)

        code = process.wait()
        if code != 0:
            raise RuntimeError(f"Workflow exited with code {code}")

        manifest = read_manifest(task.id)
        final_video = manifest.get("final_video")
        store.update(
            task.id,
            status="succeeded",
            progress=100,
            stage="done",
            message="Completed",
            final_video=final_video,
        )
    except Exception as exc:
        store.update(task.id, status="failed", stage="failed", message="Failed", error=str(exc))


@router.post("/api/tasks", response_model=CreateTaskResponse)
def create_task(payload: CreateTaskRequest) -> CreateTaskResponse:
    story_text = payload.story_text or default_story_text()
    task_id = uuid.uuid4().hex[:12]
    task_output_dir(task_id).mkdir(parents=True, exist_ok=True)
    task = TaskRecord(
        id=task_id,
        status="queued",
        progress=0,
        stage="queued",
        message="Queued",
        planner=payload.planner,
        keyframe_provider=payload.keyframe_provider,
        video_provider=payload.video_provider,
        video_render_granularity=normalize_video_render_granularity(payload.video_render_granularity),
        voice_provider=payload.voice_provider,
        scene_count=payload.scene_count,
        output_dir=str(task_output_dir(task_id)),
        story_path=str(task_output_dir(task_id) / "story.txt"),
    )
    store.create(task)
    thread = threading.Thread(target=run_workflow_task, args=(task, story_text), daemon=True)
    thread.start()
    return CreateTaskResponse(
        task_id=task_id,
        status=task.status,
        progress=task.progress,
        output_dir=task.output_dir,
        detail_url=f"/api/tasks/{task_id}",
    )


@router.get("/api/tasks")
def list_tasks() -> list[dict]:
    return [task.snapshot() for task in store.list()]


@router.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    task = store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    snapshot = task.snapshot()
    if snapshot.get("final_video") and not snapshot["final_video"].startswith("/"):
        snapshot["final_video_url"] = f"/outputs/{task_id}/comic_drama_demo.mp4"
    return snapshot


@router.get("/api/tasks/{task_id}/files")
def task_files(task_id: str) -> dict:
    task_dir = task_output_dir(task_id)
    if not task_dir.exists():
        raise HTTPException(status_code=404, detail="Task not found")

    files = []
    for path in sorted(task_dir.iterdir()):
        if path.is_file():
            files.append(
                {
                    "name": path.name,
                    "size": path.stat().st_size,
                    "url": f"/outputs/{task_id}/{path.name}",
                }
            )
    return {"task_id": task_id, "files": files}


@router.get("/api/tasks/{task_id}/video")
def task_video(task_id: str):
    path = task_output_dir(task_id) / "comic_drama_demo.mp4"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Video not ready")
    return FileResponse(path)


@router.websocket("/api/tasks/{task_id}/stream")
async def task_stream(websocket: WebSocket, task_id: str) -> None:
    # Validate task_id format before accepting the connection
    try:
        validate_task_id(task_id)
    except ValueError:
        await websocket.close(code=1008, reason="Invalid task_id")
        return

    # Origin validation to prevent cross-site WebSocket hijacking
    origin = websocket.headers.get("origin", "")
    allowed_origins = configured_cors_origins()
    if "*" not in allowed_origins and origin and origin not in allowed_origins:
        await websocket.close(code=1008, reason="Origin not allowed")
        return

    await websocket.accept()
    try:
        while True:
            task = store.get(task_id)
            if task is None:
                await websocket.send_json({"error": "Task not found"})
                break
            snapshot = task.snapshot()
            await websocket.send_json(snapshot)
            if snapshot["status"] in {"succeeded", "failed"}:
                break
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json({"error": str(exc)})
