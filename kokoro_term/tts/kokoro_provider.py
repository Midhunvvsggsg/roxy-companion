from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path
from typing import AsyncIterator, Optional, List, Dict
import numpy as np

from kokoro_term.character import VoiceConfig
from kokoro_term.tts.base import AudioChunk, TTSProvider
from kokoro_term.tts.speech_style import (
    split_sentences,
    apply_pronunciation_map,
)
from kokoro_term.tts.alignment import generate_lipsync_cues

logger = logging.getLogger("kokoro_term.tts.kokoro")


class KokoroTTSProvider(TTSProvider):
    """Local, high-quality ONNX neural TTS engine (Kokoro-82M) running on CPU."""

    def __init__(self, voice_config: Optional[VoiceConfig] = None):
        self.voice_config = voice_config or VoiceConfig()
        self._engine = None
        self._find_model_paths()

    def _find_model_paths(self) -> None:
        """Locate ONNX model and voices binary files."""
        candidates_dir = [
            Path("models/kokoro"),
            Path(__file__).resolve().parent.parent.parent / "models" / "kokoro",
            Path.home() / ".cache" / "kokoro",
        ]
        self.model_path: Optional[Path] = None
        self.voices_path: Optional[Path] = None

        for d in candidates_dir:
            if not d.exists():
                continue
            int8_onnx = d / "kokoro-v1.0.int8.onnx"
            std_onnx = d / "kokoro-v1.0.onnx"
            voices = d / "voices-v1.0.bin"

            if (int8_onnx.exists() or std_onnx.exists()) and voices.exists():
                self.model_path = int8_onnx if int8_onnx.exists() else std_onnx
                self.voices_path = voices
                break

    @property
    def provider_mode(self) -> str:
        return "local"

    def is_available(self) -> bool:
        if not self.model_path or not self.voices_path:
            self._find_model_paths()
        if not (self.model_path and self.model_path.exists() and self.voices_path and self.voices_path.exists()):
            return False
        try:
            import kokoro_onnx  # type: ignore
            import soundfile  # type: ignore
            return True
        except ImportError:
            return False

    def _get_engine(self):
        if self._engine is None and self.is_available():
            from kokoro_onnx import Kokoro
            self._engine = Kokoro(str(self.model_path), str(self.voices_path))
        return self._engine

    def _synthesize_sync(self, text: str, emotion: str = "neutral") -> tuple[bytes, float, list[dict], list[dict]]:
        """Synchronous synthesis helper executed in threadpool executor."""
        engine = self._get_engine()
        if not engine:
            return b"", 0.0, [], []

        import soundfile as sf

        clean_text = text.strip()
        if hasattr(self.voice_config, "pronunciation_map") and self.voice_config.pronunciation_map:
            clean_text = apply_pronunciation_map(clean_text, self.voice_config.pronunciation_map)

        voice_id = getattr(self.voice_config, "voice_id", None) or "jf_alpha"
        valid_voices = engine.get_voices()
        voice_target = voice_id

        # Custom master whisper blends using consented open-source actor embeddings
        if voice_id == "af_whisper":
            try:
                v1 = engine.get_voice_style("af_nicole")
                v2 = engine.get_voice_style("af_kore")
                voice_target = 0.60 * v1 + 0.40 * v2
            except Exception:
                voice_target = "af_nicole"
        elif voice_id == "jf_whisper":
            try:
                v1 = engine.get_voice_style("jf_alpha")
                v2 = engine.get_voice_style("jf_nezumi")
                voice_target = 0.55 * v1 + 0.45 * v2
            except Exception:
                voice_target = "jf_alpha"
        elif voice_id not in valid_voices:
            voice_target = "jf_alpha"
            voice_id = "jf_alpha"

        speed = float(getattr(self.voice_config, "speed", 1.0) or 1.0)

        # Detect language (ja for Japanese text, otherwise en-us / en-gb)
        lang = "en-us"
        if any("\u3040" <= c <= "\u30ff" or "\u4e00" <= c <= "\u9fff" for c in clean_text):
            lang = "ja"
        elif voice_id.startswith("bf_"):
            lang = "en-gb"

        samples, sr = engine.create(clean_text, voice=voice_target, speed=speed, lang=lang)
        dur = float(len(samples)) / float(sr)

        out_buf = io.BytesIO()
        sf.write(out_buf, samples, sr, format="WAV", subtype="PCM_16")
        wav_bytes = out_buf.getvalue()

        visemes = generate_lipsync_cues(wav_bytes, clean_text)

        # Approximate word timings across duration
        words = clean_text.split()
        word_timings = []
        if words and dur > 0:
            w_dur = dur / len(words)
            t = 0.0
            for w in words:
                word_timings.append({
                    "word": w,
                    "start": round(t, 3),
                    "end": round(t + w_dur, 3),
                })
                t += w_dur

        return wav_bytes, dur, visemes, word_timings

    async def synthesize_chunk(self, text: str, emotion: str = "neutral") -> AudioChunk:
        if not self.is_available():
            return AudioChunk(
                data=b"",
                sample_rate=24000,
                duration_sec=0.0,
                amplitude=0.0,
                provider_mode="local",
            )

        loop = asyncio.get_running_loop()
        wav_bytes, dur, visemes, word_timings = await loop.run_in_executor(
            None, self._synthesize_sync, text, emotion
        )

        stages = {
            "stage1_raw.wav": wav_bytes,
            "stage5_final.wav": wav_bytes,
        }

        return AudioChunk(
            data=wav_bytes,
            sample_rate=24000,
            duration_sec=dur,
            amplitude=0.7,
            word_timings=word_timings,
            visemes=visemes,
            provider_mode="local",
            stages=stages,
        )

    async def stream_synthesize(self, text: str, emotion: str = "neutral") -> AsyncIterator[AudioChunk]:
        sentences = split_sentences(text)
        for s in sentences:
            if not s.strip():
                continue
            chunk = await self.synthesize_chunk(s, emotion=emotion)
            yield chunk
