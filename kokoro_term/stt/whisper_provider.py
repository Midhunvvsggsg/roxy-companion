from __future__ import annotations

import asyncio
import io
import time
from typing import Optional
from kokoro_term.stt.base import STTProvider, STTResult


class FasterWhisperProvider(STTProvider):
    """Local, low-latency CPU speech recognition using faster-whisper (CTranslate2 int8)."""

    def __init__(self, model_size: str = "base", compute_type: str = "int8", device: str = "cpu"):
        self.model_size = model_size
        self.compute_type = compute_type
        self.device = device
        self._model = None

    def is_available(self) -> bool:
        try:
            import faster_whisper
            return True
        except ImportError:
            return False

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                cpu_threads=4,
            )
        return self._model

    async def transcribe(self, audio_data: bytes, sample_rate: int = 16000) -> STTResult:
        if not self.is_available():
            return STTResult(text="[Error: faster-whisper is not installed. Install with 'uv add faster-whisper']", language="en")

        start_time = time.perf_counter()
        loop = asyncio.get_running_loop()

        def _run_transcribe():
            model = self._get_model()
            audio_io = io.BytesIO(audio_data)
            # Transcribe with auto language detection (supporting English and Malayalam)
            segments, info = model.transcribe(audio_io, beam_size=2)
            text = " ".join([seg.text.strip() for seg in segments])
            return text, info.language, info.language_probability

        text, lang, prob = await loop.run_in_executor(None, _run_transcribe)
        duration = time.perf_counter() - start_time

        return STTResult(
            text=text,
            language=lang,
            confidence=prob,
            duration_sec=duration,
        )
