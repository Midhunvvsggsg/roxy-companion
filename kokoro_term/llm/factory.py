from __future__ import annotations

from kokoro_term.config import LLMConfig
from kokoro_term.llm.base import LLMProvider
from kokoro_term.llm.gemini import GeminiProvider
from kokoro_term.llm.mock import MockProvider
from kokoro_term.llm.openai_compat import OpenAICompatProvider


def create_llm_provider(config: LLMConfig) -> LLMProvider:
    """Create and return an LLMProvider instance based on configuration."""
    provider_type = config.provider.lower()
    api_key = config.get_effective_api_key()

    if provider_type == "mock":
        return MockProvider()
    elif provider_type == "gemini":
        return GeminiProvider(
            api_key=api_key or "",
            model=config.model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            base_url=config.base_url,
        )
    elif provider_type in ("openai", "ollama", "local"):
        base_url = config.base_url
        if provider_type == "ollama" and not base_url:
            base_url = "http://localhost:11434/v1"
        return OpenAICompatProvider(
            api_key=api_key,
            model=config.model,
            base_url=base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
    else:
        raise ValueError(f"Unsupported LLM provider: '{config.provider}'. Choose from gemini, openai, ollama, mock.")
