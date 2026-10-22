from __future__ import annotations

from kokoro_term.stt.base import STTProvider, STTResult
from kokoro_term.stt.language import detect_language


class MockSTTProvider(STTProvider):
    """Deterministic STT provider for tests and text-only mode."""

    def __init__(self, canned_text: str = "Hello Roxy", language: str = "en"):
        self.canned_text = canned_text
        self.language = language

    def is_available(self) -> bool:
        return True

    async def transcribe(self, audio_data: bytes, sample_rate: int = 16000) -> STTResult:
        lang = detect_language(self.canned_text)
        return STTResult(
            text=self.canned_text,
            language=lang,
            confidence=0.99,
            duration_sec=0.01,
        )
