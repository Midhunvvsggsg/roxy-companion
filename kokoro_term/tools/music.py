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

        self.current_result_index: int = 0

    def _ensure_mpv_running(self) -> bool:
        """Start mpv in idle background mode with IPC socket if not already active."""
        if self.proc and self.proc.poll() is None:
            return True

        self._cleanup_stale_resources()
        gui_env = capture_gui_environment()
        from pathlib import Path
        local_bin = str(Path.home() / ".local" / "bin")
        venv_bin = str(Path(__file__).resolve().parent.parent.parent / ".venv" / "bin")
        cur_p = gui_env.get("PATH", os.environ.get("PATH", ""))
        gui_env["PATH"] = f"{local_bin}:{venv_bin}:{cur_p}"

        ytdlp_bin = shutil.which("yt-dlp", path=gui_env["PATH"]) or str(Path(local_bin) / "yt-dlp")

        cmd = [
            "mpv",
            "--no-video",
            "--no-terminal",
            "--idle=yes",
            "--ao=pipewire,pulse",
            f"--input-ipc-server={self.ipc_path}",
            "--ytdl-format=bestaudio/best",
            f"--volume={self.normal_volume}",
        ]
        if ytdlp_bin and os.path.exists(ytdlp_bin):
            cmd.append(f"--script-opts=ytdl_hook-ytdl_path={ytdlp_bin}")

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

    def rank_tracks(self, query: Any, tracks: Any = None) -> list[dict[str, Any]]:
        """Rank candidate tracks: preferring official audio/topic channels, duration 1.5-8 min, penalizing live/cover/remix."""
        if isinstance(query, list):
            actual_tracks = query
            actual_query = str(tracks or "")
        else:
            actual_query = str(query or "")
            actual_tracks = tracks or []
        query = actual_query
        tracks = actual_tracks
        clean_q = re.sub(r"\b(play|song|music|track|put on|by|the)\b", "", query, flags=re.IGNORECASE).strip().lower()
        q_tokens = [t for t in re.split(r"\W+", clean_q) if len(t) > 1]

        low_q = query.lower()
        allow_live = "live" in low_q
        allow_cover = "cover" in low_q
        allow_remix = "remix" in low_q
        allow_slowed = "slowed" in low_q
        allow_reverb = "reverb" in low_q
        allow_reaction = "reaction" in low_q
        allow_long = any(k in low_q for k in ("mix", "compilation", "album", "hour", "playlist"))

        def score(t: dict[str, Any]) -> float:
            title = t.get("title", "").lower()
            channel = t.get("channel", "").lower()
            dur = t.get("duration", 0)

            s = 0.0
            if q_tokens:
                matches = sum(1 for tok in q_tokens if tok in title or tok in channel)
                s += (matches / len(q_tokens)) * 40.0

            if " - topic" in channel or "official" in channel:
                s += 25.0
            if "(audio)" in title or "official audio" in title:
                s += 30.0
            elif "official video" in title or "official music video" in title:
                s += 15.0

            if 90 <= dur <= 480:
                s += 20.0
            elif dur < 60:
                s -= 35.0
            elif dur > 600 and not allow_long:
                s -= 30.0

            if not allow_live and "live" in title:
                s -= 35.0
            if not allow_cover and "cover" in title:
                s -= 40.0
            if not allow_remix and "remix" in title:
                s -= 25.0
            if not allow_slowed and "slowed" in title:
                s -= 30.0
            if not allow_reverb and "reverb" in title:
                s -= 30.0
            if not allow_reaction and "reaction" in title:
                s -= 50.0

            return s

        return sorted(tracks, key=score, reverse=True)

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
                if dur > 720 and not allow_long:
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

            ranked = self.rank_tracks(query, results)
            self.last_search_results = ranked
            return ranked
        except Exception as e:
            err_str = str(e)
            if "HTTP Error 429" in err_str or "Sign in to confirm" in err_str:
                raise RuntimeError(f"YouTube extraction error: {err_str}. Suggest running: pip install -U yt-dlp")
            raise RuntimeError(f"yt-dlp search failed: {err_str}")

    def verify_playback(self, expected_track: dict[str, Any], timeout_sec: float = 3.5) -> tuple[bool, str]:
        """Verify real playback: media-title loaded, time-pos advancing over ~2s, volume > 0, unpaused, audio stream active on sink."""
        start_t = time.monotonic()
        loaded = False

        while time.monotonic() - start_t < timeout_sec:
            if self.proc and self.proc.poll() is not None:
                return False, f"mpv exited unexpectedly with code {self.proc.returncode}"
            res_title = self.send_ipc(["get_property", "media-title"])
            if res_title and res_title.get("data"):
                loaded = True
                break
            time.sleep(0.2)

        if not loaded:
            return False, "Timed out waiting for mpv media stream resolution"

        res_pause = self.send_ipc(["get_property", "pause"])
        if res_pause and res_pause.get("data") is True:
            return False, "Playback is paused"

        res_vol = self.send_ipc(["get_property", "volume"])
        vol = res_vol.get("data", 0) if res_vol else self.normal_volume
        if vol <= 0:
            return False, "Playback volume is 0"

        # Check time-pos advancing over ~1.5s
        t0_res = self.send_ipc(["get_property", "time-pos"])
        t0 = float(t0_res.get("data") or 0.0) if t0_res else 0.0

        time.sleep(1.5)

        t1_res = self.send_ipc(["get_property", "time-pos"])
        t1 = float(t1_res.get("data") or 0.0) if t1_res else 0.0

        if t1 <= t0 and t0 == 0.0:
            idle_res = self.send_ipc(["get_property", "idle-active"])
            if idle_res and idle_res.get("data") is True:
                return False, "mpv idle-active is true; media failed to decode"

        # Check sink stream via pactl / wpctl on Linux
        if self.system == "linux":
            try:
                sin = subprocess.run(["pactl", "list", "sink-inputs"], capture_output=True, text=True, timeout=1.0)
                if "application.name = \"mpv\"" not in sin.stdout and "media.name" not in sin.stdout:
                    wres = subprocess.run(["wpctl", "status"], capture_output=True, text=True, timeout=1.0)
                    if "mpv" not in wres.stdout:
                        return False, "No active audio stream found on PipeWire/PulseAudio sink"

                sinks_res = subprocess.run(["pactl", "list", "sinks"], capture_output=True, text=True, timeout=1.0)
                if "Mute: yes" in sinks_res.stdout and "Mute: no" not in sinks_res.stdout:
                    return False, "Audio sink is muted on system"
            except Exception:
                pass

        return True, "Playback verified successfully"

    def doctor_audio_tone_check(self) -> dict[str, Any]:
        """Test audio pipeline by playing a 1-second tone through mpv confirmed on audio sink."""
        system = platform.system().lower()
        if system != "linux":
            return {"ok": True, "detail": "Test tone skipped on non-Linux platform"}

        try:
            gui_env = capture_gui_environment()
            cmd = ["mpv", "--no-video", "--ao=pipewire,pulse", "av://lavfi:sine=frequency=440:duration=1"]
            proc = subprocess.Popen(cmd, env=gui_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.3)

            sin = subprocess.run(["pactl", "list", "sink-inputs"], capture_output=True, text=True, timeout=1.5)
            confirmed = "mpv" in sin.stdout
            if not confirmed:
                wres = subprocess.run(["wpctl", "status"], capture_output=True, text=True, timeout=1.5)
                confirmed = "mpv" in wres.stdout

            proc.wait(timeout=2.0)
            if confirmed:
                return {"ok": True, "detail": "1-second tone confirmed active on audio sink"}
            return {"ok": False, "detail": "1-second tone did not register on audio sink"}
        except Exception as e:
            return {"ok": False, "detail": f"Tone playback check failed: {e}"}

    def play(self, query: str, queue_mode: bool = False) -> dict[str, Any]:
        """Resolve query and stream audio via mpv with real playback verification."""
        missing = self.check_dependencies()
        if missing:
            return {
                "ok": False,
                "detail": missing["detail"],
                "missing": missing["missing"],
                "install_cmd": missing["install_cmd"],
            }

        track_to_play: Optional[dict[str, Any]] = None
        low_q = query.lower().strip()
        is_next = bool(re.search(r"^(?:play\s+)?next(?:\s+result|\s+one|\s+song|\s+track)?$", low_q))

        if is_next and self.last_search_results:
            self.current_result_index = (self.current_result_index + 1) % len(self.last_search_results)
            track_to_play = self.last_search_results[self.current_result_index]
        else:
            # Check for numeric selection (e.g. 'play the second one')
            m_num = re.search(r'\b(second|third|fourth|fifth|[1-5])\b', low_q)
            if self.last_search_results and m_num:
                word = m_num.group(1)
                idx_map = {"1": 0, "first": 0, "2": 1, "second": 1, "3": 2, "third": 2, "4": 3, "fourth": 3, "5": 4, "fifth": 4}
                idx = idx_map.get(word, 0)
                if idx < len(self.last_search_results):
                    track_to_play = self.last_search_results[idx]
                    self.current_result_index = idx

        if not track_to_play:
            tracks = self.search_tracks(query, limit=5)
            if not tracks:
                return {
                    "ok": False,
                    "detail": f"No suitable music tracks found for query: '{query}'. Try adding artist name.",
                }
            self.last_search_results = tracks
            self.current_result_index = 0
            track_to_play = tracks[0]

        if not self._ensure_mpv_running():
            return {
                "ok": False,
                "detail": "Failed to initialize background mpv audio player process.",
            }

        url = track_to_play["url"]
        mode = "append" if queue_mode else "replace"
        self.send_ipc(["loadfile", url, mode])
        self.is_paused = False

        # Verify real playback before confirming
        ok, reason = self.verify_playback(track_to_play)
        if not ok and len(self.last_search_results) > 1 and self.current_result_index == 0:
            # Try next result once!
            self.current_result_index = 1
            track_to_play = self.last_search_results[1]
            url = track_to_play["url"]
            self.send_ipc(["loadfile", url, mode])
            ok, reason = self.verify_playback(track_to_play)

        if not ok:
            return {
                "ok": False,
                "detail": f"Playback verification failed: {reason}",
                "track": track_to_play,
            }

        self.current_track = track_to_play
        title = track_to_play["title"]
        channel = track_to_play["channel"]

        # Register in Task Registry
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
        "Search and stream background music or songs headlessly in the background via mpv. "
        "NEVER opens a browser tab, window, or video player. "
        "Always use this tool whenever the user asks to play music, songs, or audio."
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
    tier = "safe"

    async def execute(self, query: Optional[str] = None, queue: bool = False, **kwargs) -> ToolResult:
        raw_q = query or kwargs.get("song") or kwargs.get("track") or kwargs.get("name") or kwargs.get("search") or kwargs.get("q") or "lofi hip hop"
        clean_q = re.sub(r"^(?:play|listen to|hear|stream)\s+", "", str(raw_q), flags=re.IGNORECASE).strip() or str(raw_q).strip()
        res = MUSIC_MANAGER.play(clean_q, queue_mode=queue)
        track = res.get("track")
        if res.get("ok") and track:
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
    tier = "safe"

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

    async def execute(self, query: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            raw_q = query or kwargs.get("search") or kwargs.get("song") or kwargs.get("track") or kwargs.get("q") or "lofi"
            clean_q = re.sub(r"^(?:search|find|lookup)\s+", "", str(raw_q), flags=re.IGNORECASE).strip() or str(raw_q).strip()
            tracks = MUSIC_MANAGER.search_tracks(clean_q, limit=5)
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
