from __future__ import annotations

import math
from PIL import Image
from rich.text import Text


def get_starfield_pixel(x: int, y: int, time_sec: float = 0.0) -> tuple[int, int, int]:
    """
    Generate deep cosmic black background with subtle, elegant twinkling stars.
    x, y: coordinate in avatar grid
    time_sec: animation timestamp for smooth twinkling
    """
    h = ((x * 127 + y * 311) ^ 0x5DEECE66D) % 1000
    if h < 8:
        # Bright golden-white twinkle star
        twinkle = 0.75 + 0.25 * math.sin(time_sec * 3.2 + h * 0.1)
        return (int(255 * twinkle), int(250 * twinkle), int(220 * twinkle))
    elif h < 20:
        # Diamond cyan starlight
        twinkle = 0.70 + 0.30 * math.sin(time_sec * 2.4 + h * 0.1)
        return (int(150 * twinkle), int(210 * twinkle), int(255 * twinkle))
    return (5, 6, 12)  # Deep cosmic black (#05060d)


def image_to_half_block(
    img: Image.Image,
    width: int = 24,
    height: int = 24,
    bg_stars: bool = True,
    time_sec: float = 0.0,
) -> str:
    """
    Convert a PIL Image into 24-bit ANSI half-block characters (▀).
    Each character cell represents two vertical pixels (top = foreground, bottom = background).
    When bg_stars=True, transparent areas render deep cosmic black with twinkling little stars.
    """
    # Ensure height is even for half-block pairing
    if height % 2 != 0:
        height += 1

    resized = img.convert("RGBA").resize((width, height), Image.Resampling.LANCZOS)
    pixels = resized.load()

    lines = []
    for y in range(0, height, 2):
        line_parts = []
        for x in range(width):
            r1, g1, b1, a1 = pixels[x, y]
            r2, g2, b2, a2 = pixels[x, y + 1]

            if bg_stars:
                # Top pixel starfield blend
                bg1 = get_starfield_pixel(x, y, time_sec)
                a1_f = a1 / 255.0
                fr1 = int(r1 * a1_f + bg1[0] * (1.0 - a1_f))
                fg1 = int(g1 * a1_f + bg1[1] * (1.0 - a1_f))
                fb1 = int(b1 * a1_f + bg1[2] * (1.0 - a1_f))

                # Bottom pixel starfield blend
                bg2 = get_starfield_pixel(x, y + 1, time_sec)
                a2_f = a2 / 255.0
                fr2 = int(r2 * a2_f + bg2[0] * (1.0 - a2_f))
                fg2 = int(g2 * a2_f + bg2[1] * (1.0 - a2_f))
                fb2 = int(b2 * a2_f + bg2[2] * (1.0 - a2_f))

                line_parts.append(f"\033[38;2;{fr1};{fg1};{fb1}m\033[48;2;{fr2};{fg2};{fb2}m▀\033[0m")
            else:
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


def render_to_rich_text(
    img: Image.Image,
    width: int = 24,
    height: int = 24,
    bg_stars: bool = True,
    time_sec: float = 0.0,
) -> Text:
    """Produce a Rich Text object from half-block ANSI string for Textual widgets."""
    ansi_str = image_to_half_block(img, width=width, height=height, bg_stars=bg_stars, time_sec=time_sec)
    return Text.from_ansi(ansi_str)
