from __future__ import annotations

import time
from pathlib import Path
from typing import Optional
from PIL import Image

from kokoro_term.avatar.animation import AnimationEngine
from kokoro_term.avatar.backends.base import AvatarBackend
from kokoro_term.avatar.compositor import AvatarCompositor
from kokoro_term.avatar.lipsync import LipSyncEngine
from kokoro_term.avatar.renderer import image_to_half_block
from kokoro_term.avatar.terminal import detect_render_protocol


class TerminalAvatarBackend(AvatarBackend):
    """Renders avatar frames in-terminal with Kitty/Sixel/Half-block fallback."""

    def __init__(self, avatar_dir: str | Path, target_size: tuple[int, int] = (24, 24)):
        self.avatar_dir = Path(avatar_dir)
        self.compositor = AvatarCompositor(self.avatar_dir, target_size=target_size)
        self.animation = AnimationEngine()
        self.protocol = detect_render_protocol()

    def start(self) -> None:
        pass

    def update_emotion(self, emotion: str) -> None:
        self.animation.set_emotion(emotion)

    def set_speaking(self, speaking: bool, lipsync: Optional[LipSyncEngine] = None) -> None:
        self.animation.set_speaking(speaking, lipsync)

    def set_mouth(self, mouth: str) -> None:
        self.animation.set_mouth_shape(mouth)

    def set_mouth_level(self, level: float) -> None:
        self.animation.set_mouth_level(level)

    def render_current_ansi_frame(self, width: int = 20, height: int = 20) -> str:
        """Render the current animated frame as an ANSI half-block string."""
        now = time.time()
        state = self.animation.update(now)
        self.compositor.set_target_size((width, height))
        frame = self.compositor.composite(state)
        return image_to_half_block(frame, width=width, height=height)

    def stop(self) -> None:
        pass
