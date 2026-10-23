from __future__ import annotations

import os
from pathlib import Path
from kokoro_term.avatar.backends.base import AvatarBackend
from kokoro_term.avatar.backends.terminal_backend import TerminalAvatarBackend
from kokoro_term.avatar.backends.window_backend import WindowAvatarBackend


def create_avatar_backend(
    mode: str = "auto",
    avatar_dir: str | Path = "characters/roxy/avatar",
) -> AvatarBackend:
    """Create avatar backend based on configuration ('window', 'terminal', or 'auto')."""
    clean_mode = (mode or "auto").lower()

    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

    if clean_mode == "window":
        try:
            return WindowAvatarBackend(avatar_dir=avatar_dir)
        except Exception:
            return TerminalAvatarBackend(avatar_dir=avatar_dir)

    return TerminalAvatarBackend(avatar_dir=avatar_dir)
