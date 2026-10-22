from __future__ import annotations

import os
import platform
import sys
from typing import Any
from kokoro_term.tools.base import BaseTool, ToolResult


class SystemInfoTool(BaseTool):
    name = "system_info"
    description = "Retrieve system hardware, OS version, CPU, memory, and runtime details."
    parameters = {}
    tier = "safe"

    async def execute(self, **kwargs) -> ToolResult:
        try:
            uname = platform.uname()
            info = {
                "os": uname.system,
                "release": uname.release,
                "version": uname.version,
                "machine": uname.machine,
                "python_version": sys.version.split()[0],
                "cpu_count": os.cpu_count() or 1,
            }

            # Try to get memory info without external heavy psutil
            mem_info = "N/A"
            if uname.system.lower() == "linux" and os.path.exists("/proc/meminfo"):
                try:
                    with open("/proc/meminfo", "r") as f:
                        lines = [line.strip() for line in f.readlines()[:3]]
                        mem_info = ", ".join(lines)
                except Exception:
                    pass
            info["memory"] = mem_info

            summary = (
                f"OS: {info['os']} {info['release']} ({info['machine']})\n"
                f"CPUs: {info['cpu_count']} | Python: {info['python_version']}\n"
                f"Memory: {info['memory']}"
            )
            return ToolResult(success=True, output=summary)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
