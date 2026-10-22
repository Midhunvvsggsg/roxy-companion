from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw
import yaml


def generate_roxy_sprite_pack(output_dir: str | Path = "characters/roxy/avatar") -> Path:
    """Generate original, charming pixel art layers and manifest for Roxy Migurdia."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    size = (24, 24)

    # 1. Base layer (Hat, Blue Hair, Face shape, Robe collar)
    base = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(base)

    # Dark blue/black pointed witch hat
    hat_color = (30, 32, 45, 255)
    hat_ribbon = (180, 80, 90, 255)
    d.polygon([(12, 1), (5, 8), (19, 8)], fill=hat_color)
    d.rectangle([3, 8, 20, 9], fill=hat_ribbon)  # ribbon band
    d.rectangle([1, 9, 22, 10], fill=hat_color)  # hat brim

    # Roxy's signature twin braided blue hair
    hair_color = (48, 88, 160, 255)
    hair_shadow = (32, 60, 120, 255)
    # Bangs / sides
    d.rectangle([4, 11, 7, 21], fill=hair_color)   # Left braid
    d.rectangle([16, 11, 19, 21], fill=hair_color) # Right braid
    d.rectangle([7, 10, 16, 12], fill=hair_color)  # Forehead fringe

    # Face skin
    skin_color = (255, 230, 210, 255)
    d.rectangle([8, 12, 15, 18], fill=skin_color)
    # Robe collar
    robe_color = (35, 40, 55, 255)
    white_collar = (240, 240, 245, 255)
    d.rectangle([7, 19, 16, 23], fill=robe_color)
    d.rectangle([10, 19, 13, 21], fill=white_collar)
    base.save(out / "base.png")

    # 2. Eyes Open
    eyes_open = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(eyes_open)
    eye_blue = (25, 60, 140, 255)
    eye_white = (255, 255, 255, 255)
    d.point([(9, 14), (14, 14)], fill=eye_white)
    d.point([(9, 15), (14, 15)], fill=eye_blue)
    eyes_open.save(out / "eyes_open.png")

    # 3. Eyes Blink (closed lines)
    eyes_blink = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(eyes_blink)
    d.line([(9, 15), (10, 15)], fill=hair_shadow)
    d.line([(13, 15), (14, 15)], fill=hair_shadow)
    eyes_blink.save(out / "eyes_blink.png")

    # 4. Eyes Half (shy / thinking)
    eyes_half = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(eyes_half)
    d.point([(9, 15), (14, 15)], fill=eye_blue)
    eyes_half.save(out / "eyes_half.png")

    # 5. Mouth Neutral
    m_neut = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(m_neut)
    d.point([(11, 17), (12, 17)], fill=(180, 100, 100, 255))
    m_neut.save(out / "mouth_neutral.png")

    # 6. Mouth Smile
    m_smile = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(m_smile)
    d.line([(11, 18), (12, 18)], fill=(200, 80, 90, 255))
    d.point([(10, 17), (13, 17)], fill=(200, 80, 90, 255))
    m_smile.save(out / "mouth_smile.png")

    # 7. Mouth Open (speaking / talking)
    m_open = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(m_open)
    d.rectangle([11, 17, 12, 18], fill=(160, 50, 60, 255))
    m_open.save(out / "mouth_open.png")

    # 8. Mouth Pout
    m_pout = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(m_pout)
    d.point([(11, 17)], fill=(190, 90, 100, 255))
    d.point([(12, 18)], fill=(190, 90, 100, 255))
    m_pout.save(out / "mouth_pout.png")

    # 9. Blush
    blush = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(blush)
    blush_pink = (255, 120, 140, 180)
    d.point([(8, 16), (9, 16)], fill=blush_pink)
    d.point([(14, 16), (15, 16)], fill=blush_pink)
    blush.save(out / "blush.png")

    # 10. Manifest YAML
    manifest = {
        "version": "1.0",
        "size": [24, 24],
        "layers": {
            "base": "base.png",
            "blush": "blush.png",
        },
        "eye_states": {
            "open": "eyes_open.png",
            "blink": "eyes_blink.png",
            "half": "eyes_half.png",
        },
        "mouth_states": {
            "neutral": "mouth_neutral.png",
            "smile": "mouth_smile.png",
            "open": "mouth_open.png",
            "pout": "mouth_pout.png",
        },
        "emotions": {
            "neutral": {"eyes": "open", "mouth": "neutral", "blush": False},
            "happy": {"eyes": "blink", "mouth": "smile", "blush": True},
            "blush": {"eyes": "half", "mouth": "pout", "blush": True},
            "pout": {"eyes": "open", "mouth": "pout", "blush": True},
            "sad": {"eyes": "half", "mouth": "neutral", "blush": False},
            "surprised": {"eyes": "open", "mouth": "open", "blush": True},
            "thinking": {"eyes": "half", "mouth": "neutral", "blush": False},
        },
        "animation": {
            "blink_interval_seconds": 3.5,
            "blink_duration_seconds": 0.2,
            "breathe_cycle_seconds": 3.0,
            "breathe_offset_y": 1,
        },
    }

    with open(out / "manifest.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)

    return out
