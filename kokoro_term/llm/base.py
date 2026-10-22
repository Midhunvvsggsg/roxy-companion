from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Literal, Optional
from pydantic import BaseModel


class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMProvider(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    async def stream_chat(self, messages: list[LLMMessage]) -> AsyncIterator[str]:
        """Yield response tokens or chunks asynchronously as they arrive."""
        yield ""  # For generator typing

    async def chat(self, messages: list[LLMMessage]) -> str:
        """Non-streaming fallback."""
        chunks: list[str] = []
        async for chunk in self.stream_chat(messages):
            chunks.append(chunk)
        return "".join(chunks)
