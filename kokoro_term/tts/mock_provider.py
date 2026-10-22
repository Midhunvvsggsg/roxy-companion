from __future__ import annotations

import asyncio
from typing import AsyncIterator
from kokoro_term.tts.base import AudioChunk, TTSProvider
from kokoro_term.tts.speech_style import split_sentences


class MockTTSProvider(TTSProvider):
    """Mock streaming TTS engine emitting audio chunks and amplitude lip-sync data."""

    def __init__(self, delay_per_sentence: float = 0.05):
        self.delay = delay_per_sentence

    def is_available(self) -> bool:
        return True

    async def stream_synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        sentences = split_sentences(text)
        for s in sentences:
            words = s.split()
            # Generate simulated audio chunks with varying amplitude for lip-sync
            for i, _ in enumerate(words):
                # Amplitude pulses between 0.3 and 0.9 while speaking
                amplitude = 0.4 + (0.5 if i % 2 == 0 else 0.1)
                yield AudioChunk(
                    data=b"\x00" * 400,  # Synthetic PCM bytes
                    sample_rate=24000,
                    duration_sec=0.15,
                    amplitude=amplitude,
                )
                if self.delay > 0:
                    await asyncio.sleep(self.delay)

            # Trailing pause at sentence boundary
            yield AudioChunk(
                data=b"\x00" * 100,
                sample_rate=24000,
                duration_sec=0.1,
                amplitude=0.0,
            )
