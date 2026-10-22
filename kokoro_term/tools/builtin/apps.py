from __future__ import annotations

import asyncio
import platform
import webbrowser
from typing import Any
from kokoro_term.tools.base import BaseTool, ToolResult


class OpenUrlTool(BaseTool):
    name = "open_url"
    description = "Open a webpage URL in the user's default web browser."
    parameters = {
        "url": {"type": "string", "description": "The web URL to open (must start with http:// or https://)"},
    }
    tier = "moderate"

    async def dry_run(self, url: str, **kwargs) -> str:
        return f"Would open browser to: {url}"

    async def execute(self, url: str, **kwargs) -> ToolResult:
        if not (url.startswith("http://") or url.startswith("https://")):
            return ToolResult(success=False, output="", error="URL must begin with http:// or https://")

        try:
            # Run in executor to prevent blocking async loop
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, webbrowser.open, url)
            return ToolResult(success=True, output=f"Opened URL: {url}")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class OpenAppTool(BaseTool):
    name = "open_app"
    description = "Launch a desktop application or open a file with its default handler."
    parameters = {
        "target": {"type": "string", "description": "Application name or file path to open"},
    }
    tier = "moderate"

    async def dry_run(self, target: str, **kwargs) -> str:
        return f"Would launch desktop target: {target}"

    async def execute(self, target: str, **kwargs) -> ToolResult:
        system = platform.system().lower()
        try:
            if system == "windows":
                cmd = ["cmd.exe", "/c", "start", "", target]
            elif system == "darwin":
                cmd = ["open", target]
            else:
                cmd = ["xdg-open", target]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()

            if proc.returncode != 0:
                return ToolResult(success=False, output="", error=stderr.decode(errors="replace"))
            return ToolResult(success=True, output=f"Launched: {target}")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
