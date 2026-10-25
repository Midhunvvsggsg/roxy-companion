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
    word_timings: Optional[list[dict]] = None  # [{"word": str, "start": float, "end": float}]
    visemes: Optional[list[dict]] = None       # [{"time": float, "viseme": str}]
    provider_mode: str = "local"               # "cloud" or "local"
    stages: Optional[dict[str, bytes]] = None  # Captured pipeline stages: stage1_raw, stage2_trimmed, etc.


class TTSProviderError(Exception):
    """Raised when a TTS provider encounters a network, endpoint, or synthesis error."""
    pass


class TTSProvider(ABC):
    """Abstract interface for streaming and single-chunk Text-to-Speech engines."""

    @property
    @abstractmethod
    def provider_mode(self) -> str:
        """Return 'cloud' or 'local'."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider dependencies and model weights are installed/available."""
        pass

    @abstractmethod
    async def stream_synthesize(self, text: str, emotion: str = "neutral") -> AsyncIterator[AudioChunk]:
        """Synthesize text into streaming audio chunks with word timings and lip-sync cues."""
        yield AudioChunk(data=b"", provider_mode=self.provider_mode)

    @abstractmethod
    async def synthesize_chunk(self, text: str, emotion: str = "neutral") -> AudioChunk:
        """Synthesize a single clause/sentence into an AudioChunk."""
        pass
