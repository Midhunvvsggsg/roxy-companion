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
    async def stream_chat(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict]] = None,
    ) -> AsyncIterator[str]:
        """Yield response tokens or chunks asynchronously as they arrive."""
        yield ""  # For generator typing

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict]] = None,
    ) -> str:
        """Non-streaming fallback."""
        chunks: list[str] = []
        try:
            if tools is not None:
                gen = self.stream_chat(messages, tools=tools)
            else:
                gen = self.stream_chat(messages)
        except TypeError:
            gen = self.stream_chat(messages)

        async for chunk in gen:
            chunks.append(chunk)
        return "".join(chunks)
