from __future__ import annotations

import asyncio
import platform
from typing import Any
from kokoro_term.tools.base import BaseTool, ToolResult


class ShellCommandTool(BaseTool):
    name = "run_command"
    description = "Execute a shell command (Bash on Linux/macOS, PowerShell on Windows)."
    parameters = {
        "command": {"type": "string", "description": "The exact shell command line string to execute"},
        "timeout": {"type": "integer", "description": "Maximum seconds to wait before timeout", "default": 30},
    }
    tier = "moderate"

    async def dry_run(self, command: str, **kwargs) -> str:
        return f"Would run shell command: {command}"

    async def execute(self, command: str, timeout: int = 30, **kwargs) -> ToolResult:
        is_windows = (platform.system().lower() == "windows")

        if is_windows:
            shell_cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            shell_cmd = ["bash", "-c", command]

        try:
            process = await asyncio.create_subprocess_exec(
                *shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=float(timeout),
                )
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except Exception:
                    pass
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Command timed out after {timeout} seconds.",
                )

            stdout = stdout_bytes.decode(errors="replace").strip()
            stderr = stderr_bytes.decode(errors="replace").strip()

            combined = []
            if stdout:
                combined.append(stdout)
            if stderr:
                combined.append(f"[stderr]:\n{stderr}")

            out_text = "\n".join(combined) if combined else "(Command executed with no output)"
            success = (process.returncode == 0)

            return ToolResult(
                success=success,
                output=out_text,
                error=f"Exited with code {process.returncode}" if not success else None,
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Execution failed: {e}")
