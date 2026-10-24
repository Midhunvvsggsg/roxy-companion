from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional
from pydantic import BaseModel


class STTResult(BaseModel):
    text: str
    language: str = "en"
    confidence: float = 1.0
    duration_sec: float = 0.0
    is_unclear: bool = False
    is_low_confidence: bool = False


class STTProvider(ABC):
    """Abstract interface for Speech-to-Text providers."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider and model weights are installed and available."""
        pass

    @abstractmethod
    async def transcribe(self, audio_data: bytes, sample_rate: int = 16000) -> STTResult:
        """Transcribe audio bytes to text with automatic language detection."""
        pass
