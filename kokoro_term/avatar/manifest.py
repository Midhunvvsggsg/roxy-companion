from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field
import yaml


class LayerDefinition(BaseModel):
    file: str
    z_index: int = 10
    offset: list[int] = Field(default_factory=lambda: [0, 0])
    size: list[int] = Field(default_factory=lambda: [1024, 1024])
    group: str = "base"


class EmotionLayerConfig(BaseModel):
    eyes: str = "open"
    brows: str = "neutral"
    mouth: str = "closed"
    blush: bool = False
    overlays: list[str] = Field(default_factory=list)


class AnimationConfig(BaseModel):
    breathing_frequency: float = 0.25
    breathing_amplitude_px: float = 8.0
    blink_interval_min: float = 3.0
    blink_interval_max: float = 6.0
    blink_duration: float = 0.12
    head_sway_amplitude_px: float = 4.0


class AvatarManifest(BaseModel):
    character: str = "roxy"
    canvas_size: list[int] = Field(default_factory=lambda: [1024, 1024])
    framing: Optional[list[int]] = None
    layers: dict[str, LayerDefinition] = Field(default_factory=dict)
    eye_states: dict[str, LayerDefinition] = Field(default_factory=dict)
    brow_states: dict[str, LayerDefinition] = Field(default_factory=dict)
    mouth_states: dict[str, LayerDefinition] = Field(default_factory=dict)
    emotions: dict[str, EmotionLayerConfig] = Field(default_factory=dict)
    animation: AnimationConfig = Field(default_factory=AnimationConfig)

    @classmethod
    def load(cls, manifest_path: str | Path) -> AvatarManifest:
        p = Path(manifest_path)
        if not p.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")

        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(**data)
