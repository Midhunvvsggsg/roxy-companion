from __future__ import annotations

import os
import sys
from typing import Literal

RenderProtocol = Literal["kitty", "sixel", "half_block", "ascii"]


def detect_render_protocol() -> RenderProtocol:
    """
    Detect the highest quality image rendering protocol supported by the host terminal.
    Fallback chain: Kitty -> Sixel -> Half-Block Unicode (▀▄) -> Pure ASCII.
    """
    # Explicit environment override
    override = os.environ.get("KOKORO_RENDER_PROTOCOL", "").lower()
    if override in ("kitty", "sixel", "half_block", "ascii"):
        return override

    term = os.environ.get("TERM", "").lower()
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    colorterm = os.environ.get("COLORTERM", "").lower()

    # 1. Kitty Graphics Protocol
    if os.environ.get("KITTY_WINDOW_ID") or "kitty" in term or "kitty" in term_program or "ghostty" in term_program:
        return "kitty"

    # 2. Sixel Graphics (foot, mlterm, sixel, wezterm)
    if "foot" in term or "mlterm" in term or "sixel" in term or "wezterm" in term:
        return "sixel"

    # 3. Half-block Unicode (requires ANSI colors / truecolor / 256 color)
    if "truecolor" in colorterm or "24bit" in colorterm or "xterm-256color" in term or "linux" not in term:
        return "half_block"

    # 4. Pure ASCII fallback
    return "ascii"
