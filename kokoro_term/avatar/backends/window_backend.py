from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from kokoro_term.avatar.backends.base import AvatarBackend
from kokoro_term.avatar.lipsync import LipSyncEngine


class WindowAvatarBackend(AvatarBackend):
    """
    Spawns and controls a separate PySide6 transparent avatar window.
    Resilient: Closing the window never crashes the main chat.
    """

    def __init__(self, avatar_dir: str | Path, port: int = 18492):
        self.avatar_dir = Path(avatar_dir)
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self._sock: Optional[socket.socket] = None

    def start(self) -> None:
        cmd = [
            sys.executable,
            "-m",
            "kokoro_term.avatar.backends.window_process",
            "--port",
            str(self.port),
            "--avatar-dir",
            str(self.avatar_dir),
        ]
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Short wait for server socket to open
            time.sleep(0.3)
            self._connect()
        except Exception as e:
            print(f"[Warning] Failed to launch AvatarWindow: {e}", file=sys.stderr)

    def _connect(self) -> bool:
        try:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(0.2)
            self._sock.connect(("127.0.0.1", self.port))
            return True
        except Exception:
            self._sock = None
            return False

    def _send_event(self, event_type: str, value: object) -> None:
        if not self._sock:
            if not self._connect():
                return
        try:
            payload = json.dumps({"type": event_type, "value": value}) + "\n"
            self._sock.sendall(payload.encode("utf-8"))
        except Exception:
            # Reconnect attempt
            self._sock = None

    def update_emotion(self, emotion: str) -> None:
        self._send_event("emotion", emotion)

    def set_speaking(self, speaking: bool, lipsync: Optional[LipSyncEngine] = None) -> None:
        self._send_event("speaking", speaking)

    def set_mouth(self, mouth: str) -> None:
        self._send_event("mouth", mouth)

    def set_mouth_level(self, level: float) -> None:
        self._send_event("mouth_level", level)

    def update_character(self, character_name: str) -> None:
        self._send_event("character", character_name)

    def stop(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=1.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
