"""Media, Volume, Brightness, and YouTube Tools for Roxy Agent."""

from __future__ import annotations

import asyncio
import shutil
import urllib.parse
from typing import Any, Optional
from kokoro_term.tools.base import BaseTool, ToolResult
from kokoro_term.tools.gui_env import open_url_or_site, spawn_gui_process


class MediaControlTool(BaseTool):
    name = "media_control"
    description = "Control media playback (play, pause, play-pause, next, previous, stop)."
    parameters = {
        "action": {
            "type": "string",
            "description": "Media action: play | pause | play-pause | next | previous | stop",
        }
    }
    tier = "moderate"

    async def execute(self, action: str, **kwargs) -> ToolResult:
        act = action.strip().lower()
        if not shutil.which("playerctl"):
            return ToolResult(
                success=False,
                output="",
                error="Helper 'playerctl' is not installed. To install on Arch: sudo pacman -S playerctl",
            )

        cmd = ["playerctl", act]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                err = stderr.decode(errors="replace").strip() or "No active media players found."
                return ToolResult(success=False, output="", error=err)
            return ToolResult(success=True, output=f"Media action '{act}' executed successfully.")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class VolumeControlTool(BaseTool):
    name = "volume_control"
    description = "Get or set audio volume (0-100), or toggle mute."
    parameters = {
        "action": {
            "type": "string",
            "description": "Action: get | set | mute | unmute | toggle-mute",
        },
        "level": {
            "type": "integer",
            "description": "Volume percentage from 0 to 100 (for 'set')",
        },
    }
    tier = "safe"

    async def execute(self, action: str, level: Optional[int] = None, **kwargs) -> ToolResult:
        act = action.strip().lower()

        # Try wpctl (PipeWire) first, then pactl (PulseAudio)
        if shutil.which("wpctl"):
            try:
                if act == "get":
                    proc = await asyncio.create_subprocess_exec(
                        "wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    out, _ = await proc.communicate()
                    txt = out.decode().strip()
                    # Example output: Volume: 0.65 [MUTED]
                    return ToolResult(success=True, output=f"Current volume: {txt}")

                elif act == "set":
                    if level is None:
                        return ToolResult(success=False, output="", error="Must provide 'level' (0-100) for set action")
                    lvl_float = max(0, min(100, int(level))) / 100.0
                    proc = await asyncio.create_subprocess_exec(
                        "wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{lvl_float:.2f}",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await proc.communicate()
                    return ToolResult(success=True, output=f"Volume set to {level}%")

                elif act in ("mute", "unmute", "toggle-mute"):
                    arg = "1" if act == "mute" else ("0" if act == "unmute" else "toggle")
                    proc = await asyncio.create_subprocess_exec(
                        "wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", arg,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await proc.communicate()
                    return ToolResult(success=True, output=f"Audio mute state updated: {act}")

            except Exception as e:
                return ToolResult(success=False, output="", error=f"wpctl failed: {e}")

        elif shutil.which("pactl"):
            try:
                if act == "get":
                    proc = await asyncio.create_subprocess_exec(
                        "pactl", "get-sink-volume", "@DEFAULT_SINK@",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    out, _ = await proc.communicate()
                    return ToolResult(success=True, output=out.decode().strip())
                elif act == "set":
                    lvl = max(0, min(100, int(level or 50)))
                    proc = await asyncio.create_subprocess_exec(
                        "pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{lvl}%",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await proc.communicate()
                    return ToolResult(success=True, output=f"Volume set to {lvl}%")
                elif act in ("mute", "unmute", "toggle-mute"):
                    arg = "1" if act == "mute" else ("0" if act == "unmute" else "toggle")
                    proc = await asyncio.create_subprocess_exec(
                        "pactl", "set-sink-mute", "@DEFAULT_SINK@", arg,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await proc.communicate()
                    return ToolResult(success=True, output=f"Sink mute updated: {act}")
            except Exception as e:
                return ToolResult(success=False, output="", error=f"pactl failed: {e}")

        return ToolResult(success=False, output="", error="Neither wpctl nor pactl is installed.")


class BrightnessControlTool(BaseTool):
    name = "brightness_control"
    description = "Get or set display brightness (0-100%)."
    parameters = {
        "action": {"type": "string", "description": "Action: get | set"},
        "level": {"type": "integer", "description": "Brightness percentage from 0 to 100"},
    }
    tier = "safe"

    async def execute(self, action: str, level: Optional[int] = None, **kwargs) -> ToolResult:
        if not shutil.which("brightnessctl"):
            return ToolResult(
                success=False,
                output="",
                error="Helper 'brightnessctl' is not installed. To install on Arch: sudo pacman -S brightnessctl",
            )

        act = action.strip().lower()
        try:
            if act == "get":
                proc = await asyncio.create_subprocess_exec(
                    "brightnessctl", "info",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                out, _ = await proc.communicate()
                return ToolResult(success=True, output=out.decode().strip())
            elif act == "set":
                if level is None:
                    return ToolResult(success=False, output="", error="Must provide level (0-100)")
                lvl = max(1, min(100, int(level)))
                proc = await asyncio.create_subprocess_exec(
                    "brightnessctl", "set", f"{lvl}%",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                out, _ = await proc.communicate()
                return ToolResult(success=True, output=f"Brightness set to {lvl}%")
            return ToolResult(success=False, output="", error=f"Unknown action: {act}")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class NowPlayingTool(BaseTool):
    name = "now_playing"
    description = "Check what music or video is currently playing."
    parameters = {}
    tier = "safe"

    async def execute(self, **kwargs) -> ToolResult:
        if not shutil.which("playerctl"):
            return ToolResult(
                success=False,
                output="",
                error="playerctl is not installed. Install with: sudo pacman -S playerctl",
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                "playerctl", "metadata", "--format", "Status: {{status}}\nTitle: {{title}}\nArtist: {{artist}}\nAlbum: {{album}}\nPlayer: {{playerName}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await proc.communicate()
            if proc.returncode != 0:
                return ToolResult(success=True, output="No media is currently playing.")
            return ToolResult(success=True, output=out.decode().strip())
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class YouTubePlayTool(BaseTool):
    name = "youtube_play"
    description = "Search YouTube and play the video or music in the browser or media player."
    parameters = {
        "query": {
            "type": "string",
            "description": "Search query or video URL to play on YouTube",
        },
        "player": {
            "type": "string",
            "description": "Playback target: 'browser' (default) or 'mpv'",
        },
    }
    tier = "moderate"

    async def execute(self, query: str, player: str = "browser", **kwargs) -> ToolResult:
        q = query.strip()
        if not q:
            return ToolResult(success=False, output="", error="Missing YouTube search query")

        # Determine target URL
        if q.startswith("http://") or q.startswith("https://"):
            url = q
        else:
            encoded = urllib.parse.quote_plus(q)
            url = f"https://www.youtube.com/results?search_query={encoded}"

        if player == "mpv":
            if not shutil.which("mpv"):
                return ToolResult(
                    success=False,
                    output="",
                    error="mpv is not installed. To install on Arch: sudo pacman -S mpv",
                    detail="mpv binary not found in PATH.",
                )
            res = spawn_gui_process(["mpv", "--no-terminal", url], wait_sec=2.0)
            return ToolResult(
                success=res["ok"],
                output=res["detail"],
                error=res["stderr"] or (None if res["ok"] else res["detail"]),
                pid=res["pid"],
                exit_code=res["exit_code"],
                stderr=res["stderr"],
                detail=res["detail"],
            )

        # Default: open in browser
        res = open_url_or_site(url, wait_sec=2.0)
        return ToolResult(
            success=res["ok"],
            output=res["detail"],
            error=res["stderr"] or (None if res["ok"] else res["detail"]),
            pid=res["pid"],
            exit_code=res["exit_code"],
            stderr=res["stderr"],
            detail=res["detail"],
        )
