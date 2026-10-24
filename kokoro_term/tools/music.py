"""Background Music Player for Roxy Agent using yt-dlp and mpv IPC."""

from __future__ import annotations

import atexit
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import time
from typing import Any, Optional

from kokoro_term.tools.base import BaseTool, ToolResult
from kokoro_term.tools.env_detect import detect_environment
from kokoro_term.tools.gui_env import capture_gui_environment
from kokoro_term.tools.injection_defense import wrap_untrusted_data
from kokoro_term.tools.tasks import TASK_REGISTRY


class MusicManager:
    """Manages audio streaming via headless mpv with IPC control and ducking."""

    def __init__(self):
        self.system = platform.system().lower()
        uid = os.getuid() if hasattr(os, "getuid") else 1000
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"

        if self.system == "windows":
            self.ipc_path = r"\\.\pipe\roxy_mpv_pipe"
        else:
            if os.path.exists(runtime_dir):
                self.ipc_path = os.path.join(runtime_dir, "roxy_mpv.sock")
            else:
                self.ipc_path = "/tmp/roxy_mpv.sock"

        self.proc: Optional[subprocess.Popen] = None
        self.current_track: Optional[dict[str, Any]] = None
        self.queue: list[dict[str, Any]] = []
        self.normal_volume: int = 100
        self.duck_volume: int = 30
        self.duck_enabled: bool = True
        self.is_ducked: bool = False
        self.is_paused: bool = False
        self.last_search_results: list[dict[str, Any]] = []

        try:
            from kokoro_term.config import load_config
            cfg = load_config()
            if hasattr(cfg, "music"):
                self.duck_enabled = (str(cfg.music.duck).lower() in ("on", "true", "1"))
                self.duck_volume = int(cfg.music.duck_volume)
                self.normal_volume = int(cfg.music.default_volume)
        except Exception:
            pass

        # Cleanup any stale socket or orphaned process from previous runs
        self._cleanup_stale_resources()
        atexit.register(self.shutdown)

        try:
            for sig in (signal.SIGTERM, signal.SIGINT):
                prev_h = signal.getsignal(sig)
                def _make_handler(ph):
                    def _handler(signum, frame):
                        self.shutdown()
                        if callable(ph):
                            ph(signum, frame)
                        else:
                            os._exit(0)
                    return _handler
                signal.signal(sig, _make_handler(prev_h))
        except Exception:
            pass

    def _cleanup_stale_resources(self) -> None:
        """Remove leftover socket files and kill orphaned mpv instances."""
        if self.system != "windows" and os.path.exists(self.ipc_path):
            try:
                os.remove(self.ipc_path)
            except Exception:
                pass

        if self.system == "linux":
            try:
                # Terminate any orphaned mpv running on our socket
                subprocess.run(["pkill", "-f", f"input-ipc-server={self.ipc_path}"], capture_output=True, timeout=1)
            except Exception:
                pass

    def check_dependencies(self) -> Optional[dict[str, str]]:
        """Verify mpv and yt-dlp are installed. If missing, return detected install command."""
        env_info = detect_environment()
        pm = env_info.get("package_manager", "pacman")

        if self.system == "linux":
            install_cmds = {
                "pacman": ("sudo pacman -S mpv", "sudo pacman -S yt-dlp"),
                "apt": ("sudo apt update && sudo apt install -y mpv", "sudo apt install -y yt-dlp"),
                "dnf": ("sudo dnf install -y mpv", "sudo dnf install -y yt-dlp"),
                "brew": ("brew install mpv", "brew install yt-dlp"),
            }
            mpv_cmd, ytdlp_cmd = install_cmds.get(pm, ("sudo pacman -S mpv", "sudo pacman -S yt-dlp"))
        elif self.system == "windows":
            mpv_cmd = "winget install mpv.net"
            ytdlp_cmd = "winget install yt-dlp"
        else:
            mpv_cmd = "brew install mpv"
            ytdlp_cmd = "brew install yt-dlp"

        # Check mpv
        if not shutil.which("mpv"):
            return {
                "missing": "mpv",
                "install_cmd": mpv_cmd,
                "detail": f"Headless music player requires 'mpv'. Install with: {mpv_cmd}",
            }

        # Check yt-dlp
        has_ytdlp_bin = bool(shutil.which("yt-dlp"))
        has_ytdlp_mod = False
        try:
            import yt_dlp
            has_ytdlp_mod = True
        except ImportError:
            pass

        if not has_ytdlp_bin and not has_ytdlp_mod:
            return {
                "missing": "yt-dlp",
                "install_cmd": ytdlp_cmd,
                "detail": f"YouTube audio resolution requires 'yt-dlp'. Install with: {ytdlp_cmd} or pip install yt-dlp",
            }

        return None

    def _ensure_mpv_running(self) -> bool:
        """Start mpv in idle background mode with IPC socket if not already active."""
        if self.proc and self.proc.poll() is None:
            return True

        self._cleanup_stale_resources()
        gui_env = capture_gui_environment()

        cmd = [
            "mpv",
            "--no-video",
            "--no-terminal",
            "--idle=yes",
            f"--input-ipc-server={self.ipc_path}",
            "--ytdl-format=bestaudio/best",
            f"--volume={self.normal_volume}",
        ]

        try:
            kwargs: dict[str, Any] = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "env": gui_env,
            }
            if self.system == "windows":
                kwargs["creationflags"] = 0x00000008 | 0x00000200
            else:
                kwargs["start_new_session"] = True

            self.proc = subprocess.Popen(cmd, **kwargs)

            # Wait up to 1.5s for IPC socket to become ready
            start_t = time.monotonic()
            while time.monotonic() - start_t < 1.5:
                if self.system != "windows" and os.path.exists(self.ipc_path):
                    break
                time.sleep(0.05)

            return True
        except Exception as e:
            print(f"[MusicPlayer Error] Failed to start mpv: {e}")
            return False

    def send_ipc(self, command: list[Any]) -> Optional[dict[str, Any]]:
        """Send a JSON command over mpv's IPC socket and return response."""
        if self.system == "windows":
            # Windows named pipe
            try:
                with open(self.ipc_path, "r+b", buffering=0) as pipe:
                    req = json.dumps({"command": command}).encode("utf-8") + b"\n"
                    pipe.write(req)
                    res_line = pipe.readline().decode("utf-8", errors="replace")
                    return json.loads(res_line) if res_line else None
            except Exception:
                return None

        # Unix Domain Socket
        if not os.path.exists(self.ipc_path):
            return None

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1.2)
                client.connect(self.ipc_path)
                req = json.dumps({"command": command}).encode("utf-8") + b"\n"
                client.sendall(req)
                data = client.recv(4096).decode("utf-8", errors="replace")
                lines = [ln.strip() for ln in data.splitlines() if ln.strip()]
                for ln in lines:
                    try:
                        parsed = json.loads(ln)
                        if "error" in parsed or "data" in parsed:
                            return parsed
                    except Exception:
                        pass
                return None
        except Exception:
            return None

    def search_tracks(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search YouTube for tracks using yt-dlp."""
        clean_q = query.strip()
        low = clean_q.lower()
        allow_live = any(k in low for k in ("live", "radio", "stream"))
        allow_long = any(k in low for k in ("mix", "radio", "live", "compilation", "stream", "hour", "playlist", "album"))

        try:
            import yt_dlp

            ydl_opts = {
                "quiet": True,
                "extract_flat": True,
                "skip_download": True,
                "noplaylist": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch{limit * 2}:{clean_q}", download=False)

            results: list[dict[str, Any]] = []
            for entry in info.get("entries", []):
                dur = entry.get("duration") or 0
                is_live = bool(entry.get("is_live"))

                if is_live and not allow_live:
                    continue
                if dur > 720 and not allow_long:  # Skip videos over ~12 minutes unless mix/long requested
                    continue

                results.append({
                    "title": entry.get("title", "Unknown Title"),
                    "channel": entry.get("uploader", "Unknown Artist"),
                    "duration": dur,
                    "url": entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                    "id": entry.get("id", ""),
                })
                if len(results) >= limit:
                    break

            self.last_search_results = results
            return results
        except Exception as e:
            err_str = str(e)
            if "HTTP Error 429" in err_str or "Sign in to confirm" in err_str:
                raise RuntimeError(f"YouTube extraction error: {err_str}. Suggest running: pip install -U yt-dlp")
            raise RuntimeError(f"yt-dlp search failed: {err_str}")

    def play(self, query: str, queue_mode: bool = False) -> dict[str, Any]:
        """Resolve query and stream audio via mpv."""
        missing = self.check_dependencies()
        if missing:
            return {
                "ok": False,
                "detail": missing["detail"],
                "missing": missing["missing"],
                "install_cmd": missing["install_cmd"],
            }

        # Check for numeric selection from previous search (e.g. 'play the second one')
        track_to_play: Optional[dict[str, Any]] = None
        m_num = re.search(r'\b(second|third|fourth|fifth|[1-5])\b', query.lower())
        if self.last_search_results and m_num:
            word = m_num.group(1)
            idx_map = {"1": 0, "first": 0, "2": 1, "second": 1, "3": 2, "third": 2, "4": 3, "fourth": 3, "5": 4, "fifth": 4}
            idx = idx_map.get(word, 0)
            if idx < len(self.last_search_results):
                track_to_play = self.last_search_results[idx]

        if not track_to_play:
            tracks = self.search_tracks(query, limit=5)
            if not tracks:
                return {
                    "ok": False,
                    "detail": f"No suitable music tracks found for query: '{query}'. Try adding artist name.",
                }
            track_to_play = tracks[0]

        if not self._ensure_mpv_running():
            return {
                "ok": False,
                "detail": "Failed to initialize background mpv audio player process.",
            }

        url = track_to_play["url"]
        mode = "append" if queue_mode else "replace"
        res = self.send_ipc(["loadfile", url, mode])

        # Verify playback started
        time.sleep(0.3)
        self.is_paused = False
        self.current_track = track_to_play

        # Register in Task Registry
        title = track_to_play["title"]
        channel = track_to_play["channel"]
        TASK_REGISTRY.register(
            task_id="task_music_player",
            name=f"Background Music: {title} by {channel}",
            task_type="music",
            pid=self.proc.pid if self.proc else None,
            cancel_fn=self.stop,
            metadata={
                "title": title,
                "channel": channel,
                "url": url,
                "duration": track_to_play["duration"],
            },
        )

        return {
            "ok": True,
            "track": track_to_play,
            "mode": mode,
            "detail": f"Playing '{title}' by {channel}.",
        }

    def pause(self) -> dict[str, Any]:
        self.send_ipc(["set_property", "pause", True])
        self.is_paused = True
        return {"ok": True, "detail": "Music playback paused."}

    def resume(self) -> dict[str, Any]:
        self.send_ipc(["set_property", "pause", False])
        self.is_paused = False
        return {"ok": True, "detail": "Music playback resumed."}

    def toggle(self) -> dict[str, Any]:
        if self.is_paused:
            return self.resume()
        return self.pause()

    def stop(self) -> dict[str, Any]:
        self.send_ipc(["stop"])
        self.current_track = None
        self.is_paused = False
        TASK_REGISTRY.remove("task_music_player")
        return {"ok": True, "detail": "Music stopped."}

    def next_track(self) -> dict[str, Any]:
        self.send_ipc(["playlist-next"])
        return {"ok": True, "detail": "Skipped to next track."}

    def prev_track(self) -> dict[str, Any]:
        self.send_ipc(["playlist-prev"])
        return {"ok": True, "detail": "Returned to previous track."}

    def set_volume(self, vol: int) -> dict[str, Any]:
        vol = max(0, min(100, int(vol)))
        self.normal_volume = vol
        if not self.is_ducked:
            self.send_ipc(["set_property", "volume", vol])
        return {"ok": True, "volume": vol, "detail": f"Music volume set to {vol}%."}

    def mute(self, is_mute: bool = True) -> dict[str, Any]:
        self.send_ipc(["set_property", "mute", is_mute])
        return {"ok": True, "detail": f"Music {'muted' if is_mute else 'unmuted'}."}

    def duck(self) -> None:
        """Lower volume while Roxy speaks or microphone records."""
        if not self.duck_enabled or self.is_ducked or not self.current_track:
            return
        self.is_ducked = True
        self.send_ipc(["set_property", "volume", self.duck_volume])

    def unduck(self) -> None:
        """Restore volume after speech/recording ends."""
        if not self.is_ducked:
            return
        self.is_ducked = False
        self.send_ipc(["set_property", "volume", self.normal_volume])

    def get_status(self) -> dict[str, Any]:
        running = self.proc is not None and self.proc.poll() is None
        if not running:
            if self.current_track:
                self.current_track = None
                TASK_REGISTRY.remove("task_music_player")
            return {
                "playing": False,
                "paused": False,
                "track": None,
                "volume": self.normal_volume,
                "ducked": False,
                "duck_enabled": self.duck_enabled,
            }

        # Check if mpv has finished track/queue (idle-active is true)
        res = self.send_ipc(["get_property", "idle-active"])
        if res and res.get("data") is True:
            if self.current_track:
                self.current_track = None
                TASK_REGISTRY.remove("task_music_player")

        return {
            "playing": self.current_track is not None and not self.is_paused,
            "paused": self.is_paused,
            "track": self.current_track,
            "volume": self.duck_volume if self.is_ducked else self.normal_volume,
            "ducked": self.is_ducked,
            "duck_enabled": self.duck_enabled,
        }

    def shutdown(self) -> None:
        """Terminate mpv and process group on Roxy exit."""
        TASK_REGISTRY.remove("task_music_player")
        if self.proc and self.proc.poll() is None:
            try:
                if self.system != "windows":
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
                else:
                    self.proc.terminate()
            except Exception:
                pass
        self._cleanup_stale_resources()


# Global Singleton Music Manager
MUSIC_MANAGER = MusicManager()


class MusicPlayTool(BaseTool):
    name = "music_play"
    description = (
        "Search and stream background music directly with mpv without opening browser tabs. "
        "Usage: music_play(query='song name', queue=false)"
    )
    parameters = {
        "query": {
            "type": "string",
            "description": "Song title or artist query (e.g. 'yoasobi idol' or 'lofi hip hop')",
        },
        "queue": {
            "type": "boolean",
            "description": "If true, appends track to queue instead of replacing active song",
        },
    }
    tier = "moderate"

    async def execute(self, query: str, queue: bool = False, **kwargs) -> ToolResult:
        res = MUSIC_MANAGER.play(query, queue_mode=queue)
        track = res.get("track")
        if res["ok"] and track:
            title = track["title"]
            channel = track["channel"]
            detail = f"Playing {title} by {channel}."
            return ToolResult(
                success=True,
                output=detail,
                detail=detail,
            )
        err = res.get("detail", "Playback failed.")
        return ToolResult(success=False, output="", error=err, detail=err)


class MusicControlTool(BaseTool):
    name = "music_control"
    description = (
        "Control background music playback: pause | resume | stop | next | prev | volume | mute | status"
    )
    parameters = {
        "action": {
            "type": "string",
            "description": "Action: pause | resume | stop | next | prev | volume | mute | status",
        },
        "value": {
            "type": "string",
            "description": "Optional value for volume (0-100) or mute (true/false)",
        },
    }
    tier = "moderate"

    async def execute(self, action: str, value: Optional[str] = None, **kwargs) -> ToolResult:
        act = action.strip().lower()
        if act in ("pause", "hold"):
            res = MUSIC_MANAGER.pause()
        elif act in ("resume", "unpause", "play"):
            res = MUSIC_MANAGER.resume()
        elif act in ("stop", "turn off", "kill", "cancel"):
            res = MUSIC_MANAGER.stop()
        elif act in ("next", "skip"):
            res = MUSIC_MANAGER.next_track()
        elif act in ("prev", "previous", "back"):
            res = MUSIC_MANAGER.prev_track()
        elif act in ("volume", "set_volume", "louder", "quieter"):
            vol = int(value) if value and value.isdigit() else (MUSIC_MANAGER.normal_volume + 15 if "louder" in act else MUSIC_MANAGER.normal_volume - 15)
            res = MUSIC_MANAGER.set_volume(vol)
        elif act in ("mute", "unmute"):
            res = MUSIC_MANAGER.mute(act == "mute")
        elif act in ("status", "what's playing", "now_playing"):
            st = MUSIC_MANAGER.get_status()
            track = st.get("track")
            if track:
                detail = f"Currently playing: '{track['title']}' by {track['channel']} (Volume: {st['volume']}%)."
            else:
                detail = "No music is currently playing."
            return ToolResult(success=True, output=detail, detail=detail)
        else:
            return ToolResult(success=False, output="", error=f"Unknown music action: {act}")

        return ToolResult(success=res["ok"], output=res.get("detail", ""), detail=res.get("detail", ""))


class MusicSearchTool(BaseTool):
    name = "music_search"
    description = "Search YouTube for the top 5 music matches without immediately playing."
    parameters = {
        "query": {"type": "string", "description": "Search query"},
    }
    tier = "safe"

    async def execute(self, query: str, **kwargs) -> ToolResult:
        try:
            tracks = MUSIC_MANAGER.search_tracks(query, limit=5)
            if not tracks:
                return ToolResult(success=True, output="No search results found.")
            lines = [f"Found {len(tracks)} tracks:"]
            for i, t in enumerate(tracks, 1):
                dur_m = t['duration'] // 60
                dur_s = t['duration'] % 60
                lines.append(f"{i}. '{t['title']}' by {t['channel']} ({dur_m}:{dur_s:02d})")
            out = "\n".join(lines)
            # Wrap in untrusted data to treat video titles strictly as DATA
            return ToolResult(success=True, output=wrap_untrusted_data(out, source="youtube_search"), detail=out)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
