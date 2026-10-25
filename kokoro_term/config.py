from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    provider: str = Field(default="gemini", description="LLM provider: gemini, openai, ollama, mock")
    model: str = Field(default="gemini-2.5-flash", description="Model identifier")
    api_key_env: str = Field(default="GEMINI_API_KEY", description="Environment variable name for the API key")
    api_key: Optional[str] = Field(default=None, description="Direct API key if specified")
    base_url: Optional[str] = Field(default=None, description="Custom base URL for OpenAI or Ollama endpoints")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1)

    def get_effective_api_key(self) -> Optional[str]:
        if self.api_key:
            return self.api_key
        return os.environ.get(self.api_key_env) or os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY")


class UIConfig(BaseModel):
    theme: str = "dark"
    show_avatar_panel: bool = True
    mode: str = "companion"  # "companion" (full terminal avatar + starry sky + voice) or "chat" (split GUI)


class MemoryConfig(BaseModel):
    enabled: bool = True
    db_path: str = "data/memory.db"
    short_term_window: int = 15
    auto_consolidate_interval: int = 10
    user_id: str = "default_user"


class ToolsConfig(BaseModel):
    enabled: bool = True
    sandbox_dir: Optional[str] = None
    auto_approve_moderate: bool = False
    audit_log_path: str = "data/audit.log"
    max_agent_steps: int = 5


class AvatarConfig(BaseModel):
    backend: str = "auto"  # "window", "terminal", "auto"
    enable_animation: bool = True
    fps: int = 24
    lipsync_offset_ms: int = 0


class VoiceSettingsConfig(BaseModel):
    provider: str = Field(default="edge", description="TTS provider: 'edge' (cloud)")
    preset: str = "anime_american_girl"
    voice: str = "en-US-JennyNeural"
    speed: float = Field(default=1.15, ge=0.9, le=1.5)
    base_pitch: int = -4
    base_rate: int = 20
    pause_comma_ms: int = 120
    pause_sentence_ms: int = 250
    trim_silence: bool = True
    custom_model_path: str = ""
    fallback_enabled: bool = True


class MusicConfig(BaseModel):
    duck: str = "on"  # "on" | "off"
    duck_volume: int = Field(default=30, ge=0, le=100)
    default_volume: int = Field(default=100, ge=0, le=100)


class AppConfig(BaseModel):
    active_character: str = "roxy"
    character_dir: str = "characters"
    llm: LLMConfig = Field(default_factory=LLMConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    avatar: AvatarConfig = Field(default_factory=AvatarConfig)
    voice: VoiceSettingsConfig = Field(default_factory=VoiceSettingsConfig)
    music: MusicConfig = Field(default_factory=MusicConfig)
    ui: UIConfig = Field(default_factory=UIConfig)


def load_config(config_path: Optional[str | Path] = None) -> AppConfig:
    """Load configuration from YAML file and .env, falling back to sensible defaults."""
    load_dotenv()

    candidate_paths: list[Path] = []
    if config_path:
        candidate_paths.append(Path(config_path))
    
    # Project default
    candidate_paths.append(Path("config/default_config.yaml"))
    
    # User config directory fallback
    user_conf = Path.home() / ".config" / "kokoro-term" / "config.yaml"
    candidate_paths.append(user_conf)

    data: dict = {}
    for p in candidate_paths:
        if p.exists() and p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    content = yaml.safe_load(f)
                    if isinstance(content, dict):
                        data = content
                        break
            except Exception:
                pass

    config = AppConfig(**data)

    # Allow environment variable overrides
    if env_provider := os.environ.get("KOKORO_LLM_PROVIDER"):
        config.llm.provider = env_provider
    if env_model := os.environ.get("KOKORO_LLM_MODEL"):
        config.llm.model = env_model

    return config
