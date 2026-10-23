from pathlib import Path
from PIL import Image
import pytest

from kokoro_term.avatar.generator import generate_roxy_sprite_pack
from kokoro_term.avatar.renderer import image_to_half_block, render_to_rich_text
from kokoro_term.avatar.sprites import SpritePack
from kokoro_term.avatar.terminal import detect_render_protocol


def test_detect_render_protocol():
    proto = detect_render_protocol()
    assert proto in ("kitty", "sixel", "half_block", "ascii")


def test_image_to_half_block():
    img = Image.new("RGBA", (4, 4), (255, 0, 0, 255))
    result = image_to_half_block(img, width=4, height=4)
    assert "▀" in result
    assert "\033[38;2;255;0;0m" in result


def test_sprite_pack_generation_and_composition(tmp_path):
    pack_dir = generate_roxy_sprite_pack(output_dir=tmp_path / "avatar")
    assert (pack_dir / "manifest.yaml").exists()
    assert (pack_dir / "base.png").exists()
    assert (pack_dir / "eyes_open.png").exists()

    pack = SpritePack(pack_dir)
    assert pack.has_sprites() is True

    # Neutral frame
    neutral_frame = pack.get_composite_frame(emotion="neutral", is_speaking=False, time_sec=1.0)
    assert neutral_frame is not None
    assert neutral_frame.size == (24, 24)

    # Blush frame
    blush_frame = pack.get_composite_frame(emotion="blush", is_speaking=False, time_sec=1.0)
    assert blush_frame is not None

    # Blinking frame (time_sec triggers blink interval)
    blink_frame = pack.get_composite_frame(emotion="neutral", is_speaking=False, time_sec=0.05)
    assert blink_frame is not None

    # Speaking frame
    speaking_frame = pack.get_composite_frame(emotion="neutral", is_speaking=True, time_sec=0.1)
    assert speaking_frame is not None


def test_avatar_panel_rendering():
    from rich.text import Text
    from kokoro_term.character import load_character
    from kokoro_term.ui.app import AvatarPanel

    character = load_character("roxy", character_dir="characters")
    panel = AvatarPanel(character=character)
    assert panel.avatar_mode == "half_block"

    rendered = panel.render()
    assert isinstance(rendered, Text)
    assert len(rendered.plain) > 100
    assert "Roxy Migurdia" in rendered.plain
