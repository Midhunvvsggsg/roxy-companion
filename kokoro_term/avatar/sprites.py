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
        self.compositor = None

        if self.manifest_path.exists():
            self._load()

    def _load(self) -> None:
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            self.manifest = yaml.safe_load(f) or {}

        # Check if this is the new AvatarManifest format
        if "canvas_size" in self.manifest and isinstance(self.manifest.get("layers"), dict):
            first_val = next(iter(self.manifest["layers"].values()), None)
            if isinstance(first_val, dict):
                try:
                    from kokoro_term.avatar.compositor import AvatarCompositor
                    self.compositor = AvatarCompositor(self.avatar_dir, target_size=(256, 256))
                except Exception:
                    self.compositor = None

        # Pre-load all referenced PNG layers for backward compatibility
        for section in ("layers", "eye_states", "brow_states", "mouth_states"):
            items = self.manifest.get(section, {})
            if isinstance(items, dict):
                for key, val in items.items():
                    rel_path = val.get("file", "") if isinstance(val, dict) else str(val)
                    if rel_path:
                        img_path = self.avatar_dir / rel_path
                        if img_path.exists():
                            try:
                                self.loaded_images[f"{section}:{key}"] = Image.open(img_path).convert("RGBA")
                            except Exception:
                                pass

    def has_sprites(self) -> bool:
        if self.compositor is not None:
            return True
        return "layers:base" in self.loaded_images

    def get_composite_frame(
        self,
        emotion: str = "neutral",
        is_speaking: bool = False,
        time_sec: float = 0.0,
    ) -> Optional[Image.Image]:
        if not self.has_sprites():
            return None

        if self.compositor is not None:
            from kokoro_term.avatar.compositor import AvatarState
            anim_cfg = self.manifest.get("animation", {})
            blink_interval = anim_cfg.get("blink_interval_seconds", 3.5)
            blink_duration = anim_cfg.get("blink_duration_seconds", 0.15)
            is_blinking = (time_sec % blink_interval) < blink_duration
            eye_key = "closed" if is_blinking else "open"

            mouth_key = "a" if is_speaking and int(time_sec * 8) % 2 == 0 else "closed"
            state = AvatarState(
                emotion=emotion,
                eye_state=eye_key,
                mouth_state=mouth_key,
                offset_y=math.sin(time_sec * 1.5) * 4.0,
            )
            return self.compositor.composite(state)

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
