from __future__ import annotations

import asyncio
import threading
import time
import uuid
from copy import deepcopy
from typing import Any

from backend.logger import get_logger

logger = get_logger(__name__)


class EventType:
    SCENE_UPDATED = "scene_updated"
    SCENE_SPLIT = "scene_split"
    SCENE_MERGED = "scene_merged"
    SCENE_RESTORED = "scene_restored"
    PROJECT_UPDATED = "project_updated"
    FINAL_STALE_CHANGED = "final_stale_changed"
    EXPORT_PROGRESS = "export_progress"


class ProjectEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def subscribe(self, project_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        with self._lock:
            self._subscribers.setdefault(project_id, set()).add(queue)
        return queue

    async def unsubscribe(self, project_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            subscribers = self._subscribers.get(project_id)
            if not subscribers:
                return
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(project_id, None)

    def publish(self, project_id: str, event_type: str, payload: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        with self._lock:
            queues = list(self._subscribers.get(project_id, set()))
        if not queues:
            return

        event = {
            "id": str(uuid.uuid4()),
            "ts": time.time(),
            "project_id": project_id,
            "type": event_type,
            "payload": deepcopy(payload),
        }
        for queue in queues:
            loop.call_soon_threadsafe(self._enqueue, queue, event)

    def _enqueue(self, queue: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("subscriber queue full, dropped %s for %s", event.get('type'), event.get('project_id'))

    def publish_scene_updated(self, project_id: str, scene: dict[str, Any]) -> None:
        self.publish(
            project_id,
            EventType.SCENE_UPDATED,
            {"scene_order": scene.get("order"), "scene": scene},
        )

    def publish_scene_split(self, project_id: str, original_order: int, project: dict[str, Any]) -> None:
        self.publish(
            project_id,
            EventType.SCENE_SPLIT,
            {"original_order": original_order, "project": project},
        )

    def publish_scene_merged(self, project_id: str, merged_order: int, project: dict[str, Any]) -> None:
        self.publish(
            project_id,
            EventType.SCENE_MERGED,
            {"merged_order": merged_order, "project": project},
        )

    def publish_scene_restored(self, project_id: str, scene_order: int, project: dict[str, Any]) -> None:
        self.publish(
            project_id,
            EventType.SCENE_RESTORED,
            {"scene_order": scene_order, "project": project},
        )

    def publish_project_updated(self, project_id: str, project: dict[str, Any]) -> None:
        self.publish(project_id, EventType.PROJECT_UPDATED, {"project": project})

    def publish_final_stale_changed(self, project_id: str, stale: bool) -> None:
        self.publish(project_id, EventType.FINAL_STALE_CHANGED, {"stale": stale})

    def publish_export_progress(self, project_id: str, progress: float, message: str = "") -> None:
        self.publish(
            project_id,
            EventType.EXPORT_PROGRESS,
            {"progress": progress, "message": message},
        )

    def subscriber_count(self, project_id: str) -> int:
        with self._lock:
            return len(self._subscribers.get(project_id, set()))


project_event_bus = ProjectEventBus()
