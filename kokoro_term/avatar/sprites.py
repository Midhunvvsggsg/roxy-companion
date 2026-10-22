from __future__ import annotations

import math
from pathlib import Path
from typing import Optional
from PIL import Image
import yaml


class SpritePack:
    """Loads and composites layered sprite frames according to character manifest."""

    def __init__(self, avatar_dir: str | Path):
        self.avatar_dir = Path(avatar_dir)
        self.manifest_path = self.avatar_dir / "manifest.yaml"
        self.manifest: dict = {}
        self.loaded_images: dict[str, Image.Image] = {}

        if self.manifest_path.exists():
            self._load()

    def _load(self) -> None:
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            self.manifest = yaml.safe_load(f) or {}

        # Pre-load all referenced PNG layers
        for section in ("layers", "eye_states", "mouth_states"):
            items = self.manifest.get(section, {})
            for key, filename in items.items():
                img_path = self.avatar_dir / filename
                if img_path.exists():
                    self.loaded_images[f"{section}:{key}"] = Image.open(img_path).convert("RGBA")

    def has_sprites(self) -> bool:
        return "layers:base" in self.loaded_images

    def get_composite_frame(
        self,
        emotion: str = "neutral",
        is_speaking: bool = False,
        time_sec: float = 0.0,
    ) -> Optional[Image.Image]:
        if not self.has_sprites():
            return None

        emotions_map = self.manifest.get("emotions", {})
        emo_config = emotions_map.get(emotion, emotions_map.get("neutral", {}))

        # Determine eye state (check blink cycle)
        anim_cfg = self.manifest.get("animation", {})
        blink_interval = anim_cfg.get("blink_interval_seconds", 3.5)
        blink_duration = anim_cfg.get("blink_duration_seconds", 0.2)

        is_blinking = (time_sec % blink_interval) < blink_duration
        eye_key = "blink" if is_blinking else emo_config.get("eyes", "open")

        # Determine mouth state (check speaking cycle)
        if is_speaking:
            # Flap mouth ~4 times per second
            mouth_key = "open" if int(time_sec * 8) % 2 == 0 else emo_config.get("mouth", "neutral")
        else:
            mouth_key = emo_config.get("mouth", "neutral")

        # Composite layers
        base = self.loaded_images["layers:base"].copy()

        # Optional blush
        if emo_config.get("blush") and "layers:blush" in self.loaded_images:
            blush_layer = self.loaded_images["layers:blush"]
            base.paste(blush_layer, (0, 0), blush_layer)

        # Eyes layer
        eye_img = self.loaded_images.get(f"eye_states:{eye_key}")
        if eye_img:
            base.paste(eye_img, (0, 0), eye_img)

        # Mouth layer
        mouth_img = self.loaded_images.get(f"mouth_states:{mouth_key}")
        if mouth_img:
            base.paste(mouth_img, (0, 0), mouth_img)

        return base
