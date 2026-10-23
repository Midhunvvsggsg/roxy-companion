from __future__ import annotations

import asyncio
import io
import re
import time
from typing import Optional
from kokoro_term.stt.base import STTProvider, STTResult


HALLUCINATION_PATTERNS = {
    "thank you for watching",
    "thanks for watching",
    "thank you",
    "thank you.",
    "subtitles by",
    "translated by",
    "[music]",
    "(music)",
    "music",
    "you",
    "subscribe",
    "bye",
    "bye bye",
    "see you next time",
    "please subscribe",
    "like and subscribe",
    "amara.org",
}

MANGLISH_INITIAL_PROMPT = (
    "English conversation with Manglish phrases such as: "
    "enthokkeyundu, vishesham, njan, ippo, varam, sukhamano, sherikkum, "
    "namaskaram, pinne, cheyyuka, entha, evide, engane."
)


class FasterWhisperProvider(STTProvider):
    """Local, low-latency CPU speech recognition using faster-whisper (CTranslate2 int8) + Silero VAD."""

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
            try:
                self._model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                    cpu_threads=4,
                )
            except Exception:
                # Fallback to tiny if base fails
                self._model = WhisperModel(
                    "tiny",
                    device=self.device,
                    compute_type=self.compute_type,
                    cpu_threads=4,
                )
        return self._model

    async def transcribe(self, audio_data: bytes | memoryview | list, sample_rate: int = 16000) -> STTResult:
        if not self.is_available():
            return STTResult(text="[Error: faster-whisper is not installed. Install with 'uv add faster-whisper']", language="en")

        start_time = time.perf_counter()
        loop = asyncio.get_running_loop()

        def _run_transcribe():
            import numpy as np
            model = self._get_model()

            if isinstance(audio_data, (bytes, bytearray, memoryview)):
                raw_bytes = bytes(audio_data)
                if raw_bytes[:4] == b"RIFF":
                    import wave
                    with wave.open(io.BytesIO(raw_bytes), "rb") as wf:
                        n = wf.getnframes()
                        raw = wf.readframes(n)
                        audio_arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                else:
                    audio_arr = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            elif isinstance(audio_data, np.ndarray):
                audio_arr = audio_data.astype(np.float32)
                if audio_arr.dtype == np.int16:
                    audio_arr = audio_arr / 32768.0
            else:
                audio_arr = np.array(audio_data, dtype=np.float32)

            if len(audio_arr) == 0:
                return "", "en", 0.0, False

            # Energy gate: check peak and RMS level
            peak = float(np.max(np.abs(audio_arr)))
            rms = float(np.sqrt(np.mean(audio_arr**2)))
            if peak < 0.012 or rms < 0.003:
                # Dead air / pure room silence
                return "", "en", 0.0, False

            # AGC (Automatic Gain Control) normalization
            if 0 < peak < 0.65:
                gain = min(0.75 / peak, 4.0)
                audio_arr = np.clip(audio_arr * gain, -1.0, 1.0)

            # Silero-VAD + auto language transcription
            try:
                segments_gen, info = model.transcribe(
                    audio_arr,
                    beam_size=2,
                    initial_prompt=MANGLISH_INITIAL_PROMPT,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=400, speech_pad_ms=200),
                )
                segments = list(segments_gen)
            except Exception:
                # Fallback without VAD if VAD model fails
                segments_gen, info = model.transcribe(
                    audio_arr,
                    beam_size=2,
                    initial_prompt=MANGLISH_INITIAL_PROMPT,
                )
                segments = list(segments_gen)

            collected_texts = []
            probs = []
            for seg in segments:
                t = seg.text.strip()
                t_clean = re.sub(r"[^\w\s]", "", t).lower().strip()
                if not t_clean or t_clean in HALLUCINATION_PATTERNS:
                    continue
                collected_texts.append(t)
                if hasattr(seg, "avg_logprob"):
                    # Convert avg_logprob to approximate probability
                    probs.append(min(1.0, max(0.0, float(np.exp(seg.avg_logprob)))))

            text = " ".join(collected_texts).strip()
            confidence = float(np.mean(probs)) if probs else float(info.language_probability)

            # Check if text is gibberish, empty, or too low confidence
            is_unclear = False
            if not text:
                is_unclear = False  # Pure silence
            elif confidence < 0.30 or (len(text) <= 3 and confidence < 0.50):
                is_unclear = True

            return text, info.language, confidence, is_unclear

        text, lang, prob, is_unclear = await loop.run_in_executor(None, _run_transcribe)
        duration = time.perf_counter() - start_time

        return STTResult(
            text=text,
            language=lang,
            confidence=prob,
            duration_sec=duration,
            is_unclear=is_unclear,
        )
