from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
import yaml
from pydantic import BaseModel, Field


class SpeakingStyle(BaseModel):
    summary: str = ""
    rules: list[str] = Field(default_factory=list)


class VoiceConfig(BaseModel):
    engine: str = "kokoro"
    voice_id: str = "af_sarah"
    speed: float = 1.0
    pitch: float = 1.0
    lang: str = "en-us"
    speech_style: dict[str, Any] = Field(default_factory=dict)


class Character(BaseModel):
    id: str
    name: str
    display_name: str
    title: str = ""
    bio: str
    personality_traits: list[str] = Field(default_factory=list)
    speaking_style: SpeakingStyle = Field(default_factory=SpeakingStyle)
    emotions: list[str] = Field(default_factory=lambda: ["neutral", "happy", "blush", "pout", "sad", "surprised", "thinking"])
    default_emotion: str = "neutral"
    voice: Optional[VoiceConfig] = None

    def build_system_prompt(self, user_name: str = "Master") -> str:
        traits_bulleted = "\n".join(f"- {trait.replace('_', ' ')}" for trait in self.personality_traits)
        rules_bulleted = "\n".join(f"- {rule}" for rule in self.speaking_style.rules)
        emotions_str = ", ".join(f"[emotion:{e}]" for e in self.emotions)

        return (
            f"You are {self.name} ({self.title}).\n\n"
            f"Background & Persona:\n{self.bio}\n\n"
            f"Personality Traits:\n{traits_bulleted}\n\n"
            f"Speaking Style & Mannerisms:\n{self.speaking_style.summary}\n"
            f"Rules to adhere to:\n{rules_bulleted}\n\n"
            f"Emotion Formatting Requirement:\n"
            f"Every single reply MUST start with exactly one emotion tag indicating your current facial expression or mood.\n"
            f"Choose from: {emotions_str}.\n"
            f"Example: '[emotion:blush] A-ano... I wasn't waiting for you or anything! But... I am glad you returned safely.'\n"
            f"User's name/handle: {user_name}."
        )


def load_character(character_id: str, character_dir: str | Path = "characters") -> Character:
    """Load character definition and optional voice config from the characters directory."""
    base_path = Path(character_dir) / character_id
    char_file = base_path / "character.yaml"
    voice_file = base_path / "voice.yaml"

    if not char_file.exists():
        raise FileNotFoundError(f"Character configuration not found at {char_file}")

    with open(char_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    voice_conf = None
    if voice_file.exists():
        try:
            with open(voice_file, "r", encoding="utf-8") as vf:
                vdata = yaml.safe_load(vf) or {}
                voice_conf = VoiceConfig(**vdata)
        except Exception:
            pass

    return Character(id=character_id, voice=voice_conf, **data)
