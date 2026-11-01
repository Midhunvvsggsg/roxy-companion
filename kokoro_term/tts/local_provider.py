from __future__ import annotations

import io
import re
import wave
from typing import AsyncIterator, Optional, List, Dict
import numpy as np

from kokoro_term.character import VoiceConfig
from kokoro_term.tts.base import AudioChunk, TTSProvider
from kokoro_term.tts.speech_style import split_sentences, apply_pronunciation_map
from kokoro_term.tts.alignment import generate_lipsync_cues


class LocalTTSProvider(TTSProvider):
    """Offline, private local Text-to-Speech provider.

    Zero network transmission. Supports local ONNX Kokoro-82M neural TTS
    with a lightweight built-in formant-cadence speech engine fallback.
    """

    def __init__(self, voice_config: Optional[VoiceConfig] = None):
        self.voice_config = voice_config or VoiceConfig()
        from kokoro_term.tts.kokoro_provider import KokoroTTSProvider
        self._kokoro = KokoroTTSProvider(self.voice_config)

    @property
    def provider_mode(self) -> str:
        return "local"

    def is_available(self) -> bool:
        return True

    def _synthesize_local_audio(
        self, text: str, sample_rate: int = 24000
    ) -> tuple[bytes, List[Dict], float]:
        """Generate local offline speech audio with syllable cadence and phoneme timings."""
        clean = re.sub(r"\[emotion:[a-zA-Z0-9_-]+\]", "", text).strip()
        words = clean.split()
        if not words:
            return b"", [], 0.0

        # Calculate word boundaries
        speed = self.voice_config.speed if self.voice_config else 1.20
        speed_factor = 1.0 / max(0.5, speed)

        word_timings = []
        t = 0.05
        for w in words:
            # Word duration ~180ms - 400ms adjusted for word length and speed
            w_dur = max(0.12, (0.07 + 0.04 * len(w)) * speed_factor)
            word_timings.append({
                "word": w,
                "start": round(t, 3),
                "end": round(t + w_dur, 3),
                "duration": round(w_dur, 3),
            })
            # 60ms gap between words (reduced for faster pace)
            t += w_dur + (0.05 * speed_factor)

        total_duration = t + 0.15
        total_samples = int(sample_rate * total_duration)

        # Generate smooth speech carrier with formant resonances
        time_arr = np.linspace(0, total_duration, total_samples, endpoint=False)
        base_f0 = 200.0  # Hz (mature warm tone)

        # Subtle natural pitch intonation contour
        pitch_contour = base_f0 + 15.0 * np.sin(2 * np.pi * 1.8 * time_arr)
        carrier = 0.4 * np.sin(2 * np.pi * pitch_contour * time_arr)
        # Add 2nd and 3rd formants for vocal warmth
        carrier += 0.25 * np.sin(2 * np.pi * (pitch_contour * 2.2) * time_arr)
        carrier += 0.15 * np.sin(2 * np.pi * (pitch_contour * 3.5) * time_arr)

        # Envelope based on word timings
        envelope = np.zeros(total_samples, dtype=np.float32)
        for w in word_timings:
            s_idx = int(w["start"] * sample_rate)
            e_idx = min(total_samples, int(w["end"] * sample_rate))
            w_len = e_idx - s_idx
            if w_len > 0:
                # Hann window syllable envelope
                envelope[s_idx:e_idx] = np.sin(np.pi * np.linspace(0, 1, w_len)) ** 1.5

        final_pcm = (carrier * envelope * 28000.0).astype(np.int16)

        out_buf = io.BytesIO()
        with wave.open(out_buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(final_pcm.tobytes())

        audio_bytes = out_buf.getvalue()
        return audio_bytes, word_timings, total_duration

    async def synthesize_chunk(self, text: str, emotion: str = "neutral") -> AudioChunk:
        if hasattr(self, "_kokoro") and self._kokoro.is_available():
            try:
                chunk = await self._kokoro.synthesize_chunk(text, emotion=emotion)
                if chunk.data:
                    return chunk
            except Exception:
                pass

        audio_bytes, word_timings, dur = self._synthesize_local_audio(text)
        offset_ms = 0.0
        visemes = generate_lipsync_cues(audio_bytes, text, word_timings=word_timings, offset_ms=offset_ms)

        stages = {
            "stage1_raw.wav": audio_bytes,
            "stage2_trimmed.wav": audio_bytes,
            "stage3_fx.wav": audio_bytes,
            "stage4_joined.wav": audio_bytes,
            "stage5_final.wav": audio_bytes,
        }

        return AudioChunk(
            data=audio_bytes,
            sample_rate=24000,
            duration_sec=dur,
            amplitude=0.6,
            word_timings=word_timings,
            visemes=visemes,
            provider_mode="local",
            stages=stages,
        )

    async def stream_synthesize(self, text: str, emotion: str = "neutral") -> AsyncIterator[AudioChunk]:
        if hasattr(self, "_kokoro") and self._kokoro.is_available():
            try:
                has_any = False
                async for chunk in self._kokoro.stream_synthesize(text, emotion=emotion):
                    if chunk.data:
                        has_any = True
                        yield chunk
                if has_any:
                    return
            except Exception:
                pass

        sentences = split_sentences(text)
        for s in sentences:
            chunk = await self.synthesize_chunk(s, emotion=emotion)
            yield chunk
