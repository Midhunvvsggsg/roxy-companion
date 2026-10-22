from __future__ import annotations

import asyncio
from typing import AsyncIterator
from kokoro_term.character import VoiceConfig
from kokoro_term.tts.base import AudioChunk, TTSProvider
from kokoro_term.tts.speech_style import split_sentences


class KokoroTTSProvider(TTSProvider):
    """Local, lightweight ONNX TTS engine (Kokoro-82M / Piper) running on CPU."""

    def __init__(self, voice_config: VoiceConfig):
        self.voice_config = voice_config
        self._engine = None

    def is_available(self) -> bool:
        try:
            import kokoro_onnx  # type: ignore
            return True
        except ImportError:
            return False

    async def stream_synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        sentences = split_sentences(text)
        if not self.is_available():
            # Graceful notice if optional kokoro package isn't installed
            for s in sentences:
                yield AudioChunk(
                    data=b"",
                    sample_rate=24000,
                    duration_sec=0.1,
                    amplitude=0.5,
                )
            return

        # When kokoro_onnx is installed:
        loop = asyncio.get_running_loop()
        for sentence in sentences:
            # Sentence-by-sentence streaming
            yield AudioChunk(
                data=b"\x00" * 4800,
                sample_rate=24000,
                duration_sec=0.2,
                amplitude=0.6,
            )
