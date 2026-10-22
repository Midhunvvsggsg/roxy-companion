from __future__ import annotations

from PIL import Image
from rich.text import Text


def image_to_half_block(img: Image.Image, width: int = 24, height: int = 24) -> str:
    """
    Convert a PIL Image into 24-bit ANSI half-block characters (▀).
    Each character cell represents two vertical pixels (top = foreground, bottom = background).
    """
    # Ensure height is even for half-block pairing
    if height % 2 != 0:
        height += 1

    resized = img.convert("RGBA").resize((width, height), Image.Resampling.NEAREST)
    pixels = resized.load()

    lines = []
    for y in range(0, height, 2):
        line_parts = []
        for x in range(width):
            r1, g1, b1, a1 = pixels[x, y]
            r2, g2, b2, a2 = pixels[x, y + 1]

            # If both pixels are completely transparent, output empty space
            if a1 < 30 and a2 < 30:
                line_parts.append("\033[0m ")
            elif a1 < 30:
                # Top transparent, bottom colored -> lower block ▄ or swap
                line_parts.append(f"\033[38;2;{r2};{g2};{b2}m\033[49m▄\033[0m")
            elif a2 < 30:
                # Bottom transparent, top colored -> upper block ▀
                line_parts.append(f"\033[38;2;{r1};{g1};{b1}m\033[49m▀\033[0m")
            else:
                # Both colored: top = foreground ▀, bottom = background
                line_parts.append(f"\033[38;2;{r1};{g1};{b1}m\033[48;2;{r2};{g2};{b2}m▀\033[0m")

        lines.append("".join(line_parts) + "\033[0m")

    return "\n".join(lines)


def render_to_rich_text(img: Image.Image, width: int = 24, height: int = 24) -> Text:
    """Produce a Rich Text object from half-block ANSI string for Textual widgets."""
    ansi_str = image_to_half_block(img, width=width, height=height)
    return Text.from_ansi(ansi_str)
