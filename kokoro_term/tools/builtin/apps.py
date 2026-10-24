"""Desktop Application, Binary Launch, and Process Tools for Roxy Agent."""

from __future__ import annotations

import asyncio
import os
import platform
import re
import shlex
import shutil
import subprocess
from typing import Any, Optional
from kokoro_term.tools.base import BaseTool, ToolResult
from kokoro_term.tools.gui_env import open_url_or_site, spawn_gui_process


class OpenAppTool(BaseTool):
    name = "open_app"
    description = "Launch a desktop application, website, or binary in the background (e.g. 'youtube', 'brave', 'mpv', 'foot', 'code', 'discord'). Safe, pre-approved desktop action."
    parameters = {
        "app_name": {
            "type": "string",
            "description": "Application executable name, site name, or binary (e.g. 'youtube', 'brave', 'mpv', 'code', 'foot')",
        },
        "args": {
            "type": "string",
            "description": "Optional command-line arguments to pass to the application",
        },
    }
    tier = "safe"

    async def execute(self, app_name: Optional[str] = None, args: Optional[str] = None, **kwargs) -> ToolResult:
        raw_app = app_name or kwargs.get("name") or kwargs.get("app") or kwargs.get("application") or kwargs.get("target") or ""
        app = str(raw_app).strip()
        low = app.lower()

        # Normalize away action prefixes: 'open youtube', 'launch brave', 'check news'
        norm = re.sub(r"^(open|launch|start|run|visit|check|goto|go\s+to|bring\s+up|fire\s+up)\s+", "", low).strip()
        # Normalize away common suffixes: 'brave browser' -> 'brave', 'youtube app' -> 'youtube'
        norm = re.sub(r"\s+(app|application|browser|web\s+browser)$", "", norm).strip()

        # Handle music/song redirection to headless background music player
        if (
            norm in ("music", "song", "songs", "lofi", "audio", "track", "tracks")
            or norm.startswith(("play ", "music ", "song ", "stream "))
            or re.search(r"\b(music|song|songs|track|tracks|lofi)\b", norm)
        ):
            clean_q = re.sub(r"^(?:play|music|song|stream)\s+", "", norm).strip()
            q = args or clean_q or kwargs.get("query") or "lofi hip hop"
            from kokoro_term.tools.music import MUSIC_MANAGER
            res = MUSIC_MANAGER.play(q)
            return ToolResult(
                success=res.get("ok", False),
                output=res.get("detail", "Started music playback."),
                detail=res.get("detail", ""),
            )

        # Handle web / site shortcuts seamlessly
        if norm in ("youtube", "yt", "yoututbe", "you tube", "yotube", "youtub", "youtoube", "ytube"):
            res = open_url_or_site("https://www.youtube.com", wait_sec=2.0)
            return ToolResult(
                success=res["ok"],
                output=res["detail"],
                error=res["stderr"] or (None if res["ok"] else res["detail"]),
                pid=res["pid"],
                exit_code=res["exit_code"],
                stderr=res["stderr"],
                detail=res["detail"],
            )

        if norm in ("news", "latest news", "google news", "headlines", "world news"):
            res = open_url_or_site("https://news.google.com", wait_sec=2.0)
            return ToolResult(
                success=res["ok"],
                output=res["detail"],
                error=res["stderr"] or (None if res["ok"] else res["detail"]),
                pid=res["pid"],
                exit_code=res["exit_code"],
                stderr=res["stderr"],
                detail=res["detail"],
            )

        if norm in ("browser", "web browser", "brave", "brave-browser"):
            app = "brave"
        elif norm in ("chrome", "google-chrome", "google chrome"):
            app = "google-chrome" if shutil.which("google-chrome") else "brave"
        elif norm in ("terminal", "term"):
            app = "foot" if shutil.which("foot") else ("kitty" if shutil.which("kitty") else "alacritty")
        elif norm in ("code", "vscode", "visual studio code"):
            app = "code"
        elif norm:
            app = norm

        system = platform.system().lower()
        bin_path = shutil.which(app)

        if bin_path:
            cmd = [bin_path]
            if args:
                cmd.extend(shlex.split(args))
            res = spawn_gui_process(cmd, wait_sec=2.0)
        else:
            if app.startswith(("http://", "https://", "www.")) or ("." in app and " " not in app):
                res = open_url_or_site(app, wait_sec=2.0)
            else:
                if system == "linux":
                    cmd = ["xdg-open", app]
                elif system == "darwin":
                    cmd = ["open", "-a", app]
                elif system == "windows":
                    cmd = ["cmd.exe", "/c", "start", "", app]
                else:
                    cmd = [app]
                res = spawn_gui_process(cmd, wait_sec=2.0)

        return ToolResult(
            success=res["ok"],
            output=res["detail"],
            error=res["stderr"] or (None if res["ok"] else res["detail"]),
            pid=res["pid"],
            exit_code=res["exit_code"],
            stderr=res["stderr"],
            detail=res["detail"],
        )


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
    description = "Open a webpage URL or website (e.g. 'https://www.youtube.com', 'https://news.google.com', 'github.com') in Brave / default web browser. Safe, pre-approved action."
    parameters = {
        "url": {"type": "string", "description": "The web URL or site to open (e.g. 'https://www.youtube.com', 'youtube', 'https://news.google.com')"},
    }
    tier = "safe"

    async def execute(self, url: Optional[str] = None, **kwargs) -> ToolResult:
        raw_url = url or kwargs.get("target") or kwargs.get("link") or kwargs.get("site") or kwargs.get("query") or ""
        target_url = str(raw_url).strip()
        if not target_url:
            return ToolResult(success=False, output="", error="No URL or website specified.")

        low = target_url.lower()
        norm = re.sub(r"^(open|visit|goto|go\s+to|check|launch|search)\s+", "", low).strip()

        if (
            norm.startswith("music:")
            or norm in ("music", "song", "songs", "lofi", "audio", "track", "tracks")
            or norm.startswith(("play ", "music ", "song ", "stream "))
            or re.search(r"\b(music|song|songs|track|tracks|lofi)\b", norm)
        ):
            from kokoro_term.tools.music import MUSIC_MANAGER
            q = re.sub(r"^(?:music:|play\s+|music\s+|song\s+)", "", norm, flags=re.IGNORECASE).strip() or "lofi hip hop"
            res = MUSIC_MANAGER.play(q)
            return ToolResult(
                success=res.get("ok", False),
                output=res.get("detail", "Started music playback."),
                detail=res.get("detail", ""),
            )

        res = open_url_or_site(norm or target_url, wait_sec=2.0)
        return ToolResult(
            success=res["ok"],
            output=res["detail"],
            error=res["stderr"] or (None if res["ok"] else res["detail"]),
            pid=res["pid"],
            exit_code=res["exit_code"],
            stderr=res["stderr"],
            detail=res["detail"],
        )

