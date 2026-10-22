from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from pydantic import BaseModel


class AudioChunk(BaseModel):
    data: bytes
    sample_rate: int = 24000
    duration_sec: float = 0.0
    amplitude: float = 0.0  # Normalized audio amplitude 0.0 to 1.0 for avatar lip-sync
    phoneme: Optional[str] = None


class TTSProvider(ABC):
    """Abstract interface for streaming Text-to-Speech engines."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider and model weights are installed and available."""
        pass

    @abstractmethod
    async def stream_synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        """Synthesize text into audio chunks sentence-by-sentence, emitting lip-sync amplitudes."""
        yield AudioChunk(data=b"")
