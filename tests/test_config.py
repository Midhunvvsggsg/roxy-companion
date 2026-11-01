from pathlib import Path
import os
import pytest
from kokoro_term.config import load_config, AppConfig, LLMConfig


def test_load_default_config():
    config = load_config()
    assert config.active_character == "roxy"
    assert config.llm.provider in ("gemini", "mock", "openai", "ollama")
    assert config.llm.temperature == 0.7
    assert config.llm.max_tokens == 1024


def test_llm_config_env_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key-12345")
    llm_conf = LLMConfig(provider="gemini", api_key_env="GEMINI_API_KEY")
    assert llm_conf.get_effective_api_key() == "test-gemini-key-12345"


def test_config_env_overrides(monkeypatch):
    monkeypatch.setenv("KOKORO_LLM_PROVIDER", "mock")
    monkeypatch.setenv("KOKORO_LLM_MODEL", "mock-custom")
    config = load_config()
    assert config.llm.provider == "mock"
    assert config.llm.model == "mock-custom"
