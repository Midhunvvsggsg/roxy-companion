from __future__ import annotations

import time
from pathlib import Path
from typing import Optional
import numpy as np
from PIL import Image

from kokoro_term.avatar.manifest import AvatarManifest, LayerDefinition


class AvatarState:
    def __init__(
        self,
        emotion: str = "neutral",
        eye_state: str = "open",
        brow_state: str = "neutral",
        mouth_state: str = "closed",
        blush: bool = False,
        overlays: Optional[list[str]] = None,
        offset_y: float = 0.0,
        offset_x: float = 0.0,
        hair_offset_x: float = 0.0,
        pose: str = "normal",
    ):
        self.emotion = emotion
        self.eye_state = eye_state
        self.brow_state = brow_state
        self.mouth_state = mouth_state
        self.blush = blush
        self.overlays = tuple(sorted(overlays or []))
        self.offset_y = round(offset_y, 1)
        self.offset_x = round(offset_x, 1)
        self.hair_offset_x = round(hair_offset_x, 1)
        self.pose = pose

    def key(self) -> tuple:
        return (
            self.emotion,
            self.eye_state,
            self.brow_state,
            self.mouth_state,
            self.blush,
            self.overlays,
            self.offset_y,
            self.offset_x,
            self.hair_offset_x,
            self.pose,
        )


class AvatarCompositor:
    """Fast, cached 2D anime layer compositor with dirty-state checking (Pillow + numpy)."""

    def __init__(self, avatar_dir: str | Path, target_size: tuple[int, int] = (512, 512)):
        self.avatar_dir = Path(avatar_dir)
        self.manifest = AvatarManifest.load(self.avatar_dir / "manifest.yaml")
        self.target_size = target_size
        self._compute_scales()

        # Raw layer image cache and pre-scaled layer cache
        self._raw_layers: dict[str, Image.Image] = {}
        self._scaled_layers: dict[str, tuple[Image.Image, int, int]] = {}

        # Last composite cache
        self._last_state_key: Optional[tuple] = None
        self._last_frame: Optional[Image.Image] = None
        self._last_composite_time: float = 0.0

        # Performance telemetry
        self.composite_count: int = 0
        self.last_frame_duration_ms: float = 0.0

        self._preload_layers()

    def _compute_scales(self) -> None:
        if self.manifest.framing and len(self.manifest.framing) == 4:
            ref_w = float(self.manifest.framing[2] - self.manifest.framing[0])
            ref_h = float(self.manifest.framing[3] - self.manifest.framing[1])
        else:
            ref_w = float(self.manifest.canvas_size[0])
            ref_h = float(self.manifest.canvas_size[1])

        self.scale_x = self.target_size[0] / max(1.0, ref_w)
        self.scale_y = self.target_size[1] / max(1.0, ref_h)

    def set_target_size(self, size: tuple[int, int]) -> None:
        if size != self.target_size:
            self.target_size = size
            self._compute_scales()
            self._scaled_layers.clear()
            self._last_state_key = None

    def _preload_layers(self) -> None:
        all_layers = {}
        all_layers.update(self.manifest.layers)
        all_layers.update(self.manifest.eye_states)
        all_layers.update(self.manifest.brow_states)
        all_layers.update(self.manifest.mouth_states)

        for name, layer_def in all_layers.items():
            img_path = self.avatar_dir / layer_def.file
            if img_path.exists():
                try:
                    self._raw_layers[layer_def.file] = Image.open(img_path).convert("RGBA")
                except Exception:
                    pass

    def _get_scaled_layer(self, layer_def: LayerDefinition) -> Optional[tuple[Image.Image, int, int]]:
        cached = self._scaled_layers.get(layer_def.file)
        if cached is not None:
            return cached

        raw = self._raw_layers.get(layer_def.file)
        if raw is None:
            img_path = self.avatar_dir / layer_def.file
            if img_path.exists():
                raw = Image.open(img_path).convert("RGBA")
                self._raw_layers[layer_def.file] = raw
            else:
                return None

        # Pre-scale layer to target display resolution
        scaled_w = max(1, int(round(raw.width * self.scale_x)))
        scaled_h = max(1, int(round(raw.height * self.scale_y)))
        scaled_img = raw.resize((scaled_w, scaled_h), Image.Resampling.BILINEAR)

        origin_x = self.manifest.framing[0] if (self.manifest.framing and len(self.manifest.framing) == 4) else 0
        origin_y = self.manifest.framing[1] if (self.manifest.framing and len(self.manifest.framing) == 4) else 0

        scaled_ox = int(round((layer_def.offset[0] - origin_x) * self.scale_x))
        scaled_oy = int(round((layer_def.offset[1] - origin_y) * self.scale_y))

        entry = (scaled_img, scaled_ox, scaled_oy)
        self._scaled_layers[layer_def.file] = entry
        return entry

    def composite(self, state: AvatarState) -> Image.Image:
        """Composite all layers for the active state. Returns cached frame if state is clean."""
        state_key = state.key()
        if self._last_state_key == state_key and self._last_frame is not None:
            return self._last_frame

        start_t = time.perf_counter()
        canvas = Image.new("RGBA", self.target_size, (0, 0, 0, 0))

        # Collect active layers according to emotion config and state
        layers_to_draw: list[tuple[int, LayerDefinition, bool]] = [] # (z_index, LayerDefinition, is_head_feature)

        # 1. Base layer
        if "base" in self.manifest.layers:
            layers_to_draw.append((self.manifest.layers["base"].z_index, self.manifest.layers["base"], False))

        # 2. Overlays & blush from emotion
        emo_conf = self.manifest.emotions.get(state.emotion, self.manifest.emotions.get("neutral"))
        should_blush = state.blush or (emo_conf.blush if emo_conf else False)
        if should_blush and "blush" in self.manifest.layers:
            layers_to_draw.append((self.manifest.layers["blush"].z_index, self.manifest.layers["blush"], True))

        active_overlays = set(state.overlays)
        if emo_conf:
            active_overlays.update(emo_conf.overlays)
        for ov_name in active_overlays:
            if ov_name in self.manifest.layers:
                layers_to_draw.append((self.manifest.layers[ov_name].z_index, self.manifest.layers[ov_name], True))

        # 3. Eye state
        eye_def = self.manifest.eye_states.get(state.eye_state, self.manifest.eye_states.get("open"))
        if eye_def:
            layers_to_draw.append((eye_def.z_index, eye_def, True))

        # 4. Brow state
        brow_def = self.manifest.brow_states.get(state.brow_state, self.manifest.brow_states.get("neutral"))
        if brow_def:
            layers_to_draw.append((brow_def.z_index, brow_def, True))

        # 5. Mouth state
        mouth_def = self.manifest.mouth_states.get(state.mouth_state, self.manifest.mouth_states.get("closed"))
        if mouth_def:
            layers_to_draw.append((mouth_def.z_index, mouth_def, True))

        # 6. Hair front (draw on top of facial features)
        if "hair_front" in self.manifest.layers:
            layers_to_draw.append((self.manifest.layers["hair_front"].z_index, self.manifest.layers["hair_front"], True))

        # Sort layers strictly by z_index
        layers_to_draw.sort(key=lambda item: item[0])

        scaled_offset_x = int(round(state.offset_x * self.scale_x))
        scaled_offset_y = int(round(state.offset_y * self.scale_y))
        scaled_hair_x = int(round((state.offset_x + state.hair_offset_x) * self.scale_x))

        # Paste each layer onto master canvas
        for _, layer_def, is_facial in layers_to_draw:
            scaled = self._get_scaled_layer(layer_def)
            if not scaled:
                continue
            layer_img, ox, oy = scaled

            # Apply breathing / sway offset (hair has dynamic inertia lag)
            is_hair = "hair" in layer_def.file.lower() or layer_def.group == "overlay"
            if is_hair and "hair" in layer_def.file.lower():
                pos_x = ox + scaled_hair_x
            else:
                pos_x = ox + (scaled_offset_x if is_facial else 0)
            pos_y = oy + scaled_offset_y

            canvas.paste(layer_img, (pos_x, pos_y), layer_img)

        self._last_state_key = state_key
        self._last_frame = canvas
        self._last_composite_time = time.time()
        self.composite_count += 1
        self.last_frame_duration_ms = (time.perf_counter() - start_t) * 1000.0

        return canvas
