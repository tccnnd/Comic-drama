from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()


@dataclass
class TaskRecord:
    id: str
    status: str
    progress: int = 0
    stage: str = "queued"
    message: str = "Waiting"
    planner: str = "auto"
    keyframe_provider: str = "auto"
    video_provider: str = "auto"
    voice_provider: str = "auto"
    scene_count: int = 5
    created_at: str = field(default_factory=isoformat)
    updated_at: str = field(default_factory=isoformat)
    output_dir: str = ""
    story_path: str = ""
    final_video: str | None = None
    error: str | None = None
    logs: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "stage": self.stage,
            "message": self.message,
            "planner": self.planner,
            "keyframe_provider": self.keyframe_provider,
            "video_provider": self.video_provider,
            "voice_provider": self.voice_provider,
            "scene_count": self.scene_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "output_dir": self.output_dir,
            "story_path": self.story_path,
            "final_video": self.final_video,
            "error": self.error,
            "logs": list(self.logs[-80:]),
        }


class TaskStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._tasks: dict[str, TaskRecord] = {}

    def create(self, task: TaskRecord) -> TaskRecord:
        with self._lock:
            self._tasks[task.id] = task
            return task

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list(self) -> list[TaskRecord]:
        with self._lock:
            return list(self._tasks.values())

    def update(self, task_id: str, **updates: Any) -> TaskRecord:
        with self._lock:
            task = self._tasks[task_id]
            for key, value in updates.items():
                setattr(task, key, value)
            task.updated_at = isoformat()
            return task

    def append_log(self, task_id: str, line: str, limit: int = 120) -> TaskRecord:
        with self._lock:
            task = self._tasks[task_id]
            task.logs.append(line)
            if len(task.logs) > limit:
                task.logs = task.logs[-limit:]
            task.updated_at = isoformat()
            return task
