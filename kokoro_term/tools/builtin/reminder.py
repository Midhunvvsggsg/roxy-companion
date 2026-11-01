"""Timer and Reminder Tools for Roxy AI Companion."""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import subprocess
import time
import uuid
from typing import Any, Optional

from kokoro_term.tools.base import BaseTool, ToolResult
from kokoro_term.tools.tasks import TASK_REGISTRY


class SetReminderTool(BaseTool):
    name = "set_reminder"
    description = (
        "Set a non-blocking background reminder or timer for the user (e.g. 'remind me to check code in 10 minutes', "
        "'remind me to drink water in 30 seconds'). When the time arrives, Roxy alerts the user."
    )
    parameters = {
        "message": {
            "type": "string",
            "description": "What to remind the user about (e.g. 'stretch and drink water', 'check the oven')",
        },
        "minutes": {
            "type": "number",
            "description": "Delay in minutes before the reminder triggers (can be fractional, e.g. 0.5 for 30s)",
            "default": 0,
        },
        "seconds": {
            "type": "integer",
            "description": "Optional additional seconds delay",
            "default": 0,
        },
    }
    tier = "safe"

    async def execute(
        self,
        message: Optional[str] = None,
        minutes: Optional[float] = 0,
        seconds: Optional[int] = 0,
        **kwargs,
    ) -> ToolResult:
        remind_msg = (message or kwargs.get("text") or kwargs.get("task") or "Reminder from Roxy!").strip()
        min_val = float(minutes or kwargs.get("delay_minutes") or 0)
        sec_val = int(seconds or kwargs.get("delay_seconds") or 0)

        total_sec = max(1.0, min_val * 60.0 + float(sec_val))
        task_id = f"reminder_{uuid.uuid4().hex[:8]}"

        if total_sec >= 60:
            m = int(total_sec // 60)
            s = int(total_sec % 60)
            dur_str = f"{m} minute{'s' if m != 1 else ''}" + (f" {s}s" if s > 0 else "")
        else:
            dur_str = f"{int(total_sec)} seconds"

        async def _reminder_coro():
            try:
                await asyncio.sleep(total_sec)
                # Desktop notification
                if platform.system().lower() == "linux" and shutil.which("notify-send"):
                    try:
                        subprocess.run(
                            ["notify-send", "-a", "Roxy Migurdia", "Roxy Reminder", remind_msg],
                            timeout=5,
                            capture_output=True,
                        )
                    except Exception:
                        pass
            except asyncio.CancelledError:
                pass
            finally:
                TASK_REGISTRY.remove(task_id)

        # Launch non-blocking task
        loop = asyncio.get_event_loop()
        async_task = loop.create_task(_reminder_coro())

        # Register in TASK_REGISTRY
        TASK_REGISTRY.register(
            task_id=task_id,
            name=f"Reminder: {remind_msg[:30]}",
            task_type="reminder",
            cancel_fn=async_task.cancel,
            metadata={"message": remind_msg, "duration_sec": total_sec},
        )

        output_str = f"Reminder scheduled for {dur_str} from now: '{remind_msg}'."
        return ToolResult(
            success=True,
            output=output_str,
            detail=output_str,
            data={"task_id": task_id, "duration_seconds": total_sec, "message": remind_msg},
        )
