"""Background Task Lifecycle and Registry for Roxy Agent."""

from __future__ import annotations

import atexit
import os
import signal
from typing import Any, Callable, Optional


class BackgroundTask:
    def __init__(
        self,
        task_id: str,
        name: str,
        task_type: str,
        pid: Optional[int] = None,
        cancel_fn: Optional[Callable[[], Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ):
        self.task_id = task_id
        self.name = name
        self.task_type = task_type
        self.pid = pid
        self.cancel_fn = cancel_fn
        self.metadata = metadata or {}
        self.status = "running"

    def cancel(self) -> None:
        if self.cancel_fn:
            try:
                self.cancel_fn()
            except Exception:
                pass
        if self.pid:
            try:
                os.kill(self.pid, signal.SIGTERM)
            except Exception:
                pass
        self.status = "stopped"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "type": self.task_type,
            "status": self.status,
            "pid": self.pid,
            "metadata": self.metadata,
        }


class TaskRegistry:
    """Registry maintaining active background tasks (e.g. Music Player, Downloads)."""

    def __init__(self):
        self._tasks: dict[str, BackgroundTask] = {}
        atexit.register(self.cleanup_all)

    def register(
        self,
        task_id: str,
        name: str,
        task_type: str,
        pid: Optional[int] = None,
        cancel_fn: Optional[Callable[[], Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> BackgroundTask:
        # Cancel any existing task with the same task_id
        if task_id in self._tasks:
            self._tasks[task_id].cancel()

        task = BackgroundTask(
            task_id=task_id,
            name=name,
            task_type=task_type,
            pid=pid,
            cancel_fn=cancel_fn,
            metadata=metadata,
        )
        self._tasks[task_id] = task
        return task

    def remove(self, task_id: str) -> None:
        task = self._tasks.pop(task_id, None)
        if task:
            task.status = "stopped"

    def get(self, task_id: str) -> Optional[BackgroundTask]:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[dict[str, Any]]:
        active: list[dict[str, Any]] = []
        for task_id, task in list(self._tasks.items()):
            if task.pid:
                # Check if process is still running
                try:
                    os.kill(task.pid, 0)
                except OSError:
                    task.status = "stopped"
                    self._tasks.pop(task_id, None)
                    continue
            if task.status == "running":
                active.append(task.to_dict())
        return active

    def cleanup_all(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        self._tasks.clear()


# Global Singleton Task Registry
TASK_REGISTRY = TaskRegistry()
