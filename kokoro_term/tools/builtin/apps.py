"""Desktop Application, Binary Launch, and Process Tools for Roxy Agent."""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import subprocess
from typing import Any, Optional
from kokoro_term.tools.base import BaseTool, ToolResult


class OpenAppTool(BaseTool):
    name = "open_app"
    description = "Launch a desktop application or binary in the background (e.g. 'brave', 'mpv', 'foot', 'code', 'discord')."
    parameters = {
        "app_name": {
            "type": "string",
            "description": "Application executable name or binary (e.g. 'brave', 'mpv', 'code', 'foot')",
        },
        "args": {
            "type": "string",
            "description": "Optional command-line arguments to pass to the application",
        },
    }
    tier = "moderate"

    async def execute(self, app_name: str, args: Optional[str] = None, **kwargs) -> ToolResult:
        app = app_name.strip()
        system = platform.system().lower()

        # Check if binary is in PATH
        bin_path = shutil.which(app)

        try:
            if bin_path:
                cmd = [bin_path]
                if args:
                    import shlex
                    cmd.extend(shlex.split(args))
            else:
                if system == "linux":
                    cmd = ["xdg-open", app]
                elif system == "darwin":
                    cmd = ["open", "-a", app]
                elif system == "windows":
                    cmd = ["cmd.exe", "/c", "start", "", app]
                else:
                    cmd = [app]

            # Launch detached so the Python agent doesn't hang
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return ToolResult(
                success=True,
                output=f"Successfully launched '{app}' in background (PID {proc.pid}).",
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to launch '{app}': {e}")


class KillProcessTool(BaseTool):
    name = "kill_process"
    description = "Terminate a running process by name or PID."
    parameters = {
        "target": {
            "type": "string",
            "description": "Process name (e.g. 'mpv') or integer PID",
        },
        "force": {
            "type": "boolean",
            "description": "Send SIGKILL (-9) if true, SIGTERM if false (default false)",
        },
    }
    tier = "dangerous"

    async def execute(self, target: str, force: bool = False, **kwargs) -> ToolResult:
        t = target.strip()
        sig = "-9" if force else "-15"

        try:
            if t.isdigit():
                cmd = ["kill", sig, t]
            else:
                cmd = ["pkill", sig, "-f", t]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                err = stderr.decode(errors="replace").strip() or f"No matching process found for '{t}'."
                return ToolResult(success=False, output="", error=err)
            return ToolResult(success=True, output=f"Terminated process matching '{t}'.")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Kill process error: {e}")


class CheckAppRunningTool(BaseTool):
    name = "check_app_running"
    description = "Check if an application or process is currently running."
    parameters = {
        "app_name": {
            "type": "string",
            "description": "Executable or process name to check",
        }
    }
    tier = "safe"

    async def execute(self, app_name: str, **kwargs) -> ToolResult:
        app = app_name.strip()
        try:
            proc = await asyncio.create_subprocess_exec(
                "pgrep", "-f", app,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            pids = stdout.decode().strip().split()
            if pids and proc.returncode == 0:
                return ToolResult(
                    success=True,
                    output=f"Application '{app}' is RUNNING (PIDs: {', '.join(pids[:5])}).",
                )
            return ToolResult(success=True, output=f"Application '{app}' is NOT running.")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Process check failed: {e}")


class OpenUrlTool(BaseTool):
    name = "open_url"
    description = "Open a webpage URL in the user's web browser."
    parameters = {
        "url": {"type": "string", "description": "The web URL to open (must start with http:// or https://)"},
    }
    tier = "moderate"

    async def execute(self, url: str, **kwargs) -> ToolResult:
        if not (url.startswith("http://") or url.startswith("https://")):
            return ToolResult(success=False, output="", error="URL must begin with http:// or https://")

        browser = shutil.which("brave") or shutil.which("chromium") or shutil.which("firefox")
        try:
            if browser:
                subprocess.Popen(
                    [browser, url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            else:
                import webbrowser
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, webbrowser.open, url)
            return ToolResult(success=True, output=f"Opened URL: {url}")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
