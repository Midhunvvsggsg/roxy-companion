from __future__ import annotations

import asyncio
import io
import re
from typing import AsyncIterator, Optional, List, Dict
import edge_tts

from kokoro_term.character import VoiceConfig
from kokoro_term.tts.base import AudioChunk, TTSProvider, TTSProviderError
from kokoro_term.tts.speech_style import (
    apply_pronunciation_map,
    chunk_text_for_tts,
    normalize_text_for_tts,
)
from kokoro_term.tts.alignment import generate_lipsync_cues
from kokoro_term.tts.audio_processor import trim_audio_silence


class EdgeTTSProvider(TTSProvider):
    """Online cloud Text-to-Speech provider using Microsoft Edge Speech WebSocket service.

    Features:
    - Text normalization for numbers, units, paths, and URLs before synthesis
    - Sentence-based intonation-preserving chunking with prefetching
    - Native rate scaling (1.1x-1.2x) and pitch clamped to <= 1 semitone
    - WordBoundary event extraction for syllable and text-sync accuracy
    - Raised-cosine anti-click fades and -1 dBFS limiter
    """

    def __init__(self, voice_config: Optional[VoiceConfig] = None):
        self.voice_config = voice_config or VoiceConfig(
            engine="edge-tts",
            voice_id="en-US-AvaNeural",
            speed=1.15,
            pitch=0.0,
        )

    @property
    def provider_mode(self) -> str:
        return "cloud"

    def is_available(self) -> bool:
        try:
            import edge_tts
            return True
        except ImportError:
            return False

    def _calculate_prosody(self, emotion: str) -> tuple[str, str]:
        speed = self.voice_config.speed if self.voice_config else 1.15
        # Enforce pitch change at 1 semitone or less (~12 Hz)
        base_pitch = int(self.voice_config.pitch) if self.voice_config else 0
        base_pitch = max(-12, min(12, base_pitch))

        pace_mult = self.voice_config.emotion_pace.get(emotion, 1.0)
        pitch_off = self.voice_config.emotion_pitch.get(emotion, 0)
        pitch_off = max(-6, min(6, pitch_off))

        effective_speed = max(0.9, min(1.3, speed * pace_mult))
        rate_pct = round((effective_speed - 1.0) * 100)
        effective_pitch = max(-12, min(12, base_pitch + pitch_off))

        return f"{effective_pitch:+d}Hz", f"{rate_pct:+d}%"

    async def synthesize_chunk(self, text: str, emotion: str = "neutral") -> AudioChunk:
        clean = re.sub(r"\[emotion:[a-zA-Z0-9_-]+\]", "", text).strip()
        if not clean:
            return AudioChunk(data=b"", provider_mode="cloud")

        normalized = normalize_text_for_tts(clean)
        spoken_text = apply_pronunciation_map(normalized, self.voice_config.pronunciation_map)
        pitch_str, rate_str = self._calculate_prosody(emotion)
        voice = self.voice_config.voice_id or "en-US-AvaNeural"
        is_whisper = "Whisper" in voice
        actual_voice = voice.replace("Whisper", "Neural") if is_whisper else voice

        audio_data = b""
        word_timings: List[Dict] = []

        try:
            if is_whisper:
                ssml_text = f"""<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xmlns:mstts='https://www.w3.org/2001/mstts' xml:lang='en-US'>
<voice name='{actual_voice}'>
<mstts:express-as style='whispering'>
<prosody pitch='{pitch_str}' rate='{rate_str}'>
{spoken_text}
</prosody>
</mstts:express-as>
</voice>
</speak>"""
                communicate = edge_tts.Communicate(ssml_text, actual_voice)
            else:
                communicate = edge_tts.Communicate(
                    spoken_text,
                    actual_voice,
                    rate=rate_str,
                    pitch=pitch_str,
                    boundary="WordBoundary",
                )
            # Add timeout to fail fast and trigger fallback if network hangs
            async with asyncio.timeout(6.0):
                async for chunk in communicate.stream():
                    c_type = chunk["type"]
                    if c_type == "audio":
                        audio_data += chunk["data"]
                    elif c_type == "WordBoundary" and not is_whisper:
                        start_s = round(chunk["offset"] / 10_000_000, 3)
                        dur_s = round(chunk["duration"] / 10_000_000, 3)
                        word_timings.append({
                            "word": chunk.get("text", ""),
                            "start": start_s,
                            "end": round(start_s + dur_s, 3),
                            "duration": dur_s,
                        })

            if len(audio_data) < 100:
                raise TTSProviderError("Edge-TTS returned empty audio stream.")

            # Stage 1: Raw engine output
            from kokoro_term.tts.audio_processor import decode_audio_to_mono, encode_mono_to_wav, apply_limiter
            mono_raw, sr = decode_audio_to_mono(audio_data, target_sr=24000)
            stage1_raw = encode_mono_to_wav(mono_raw, sample_rate=sr)

            # Determine pause length: comma clause (~100ms) vs sentence terminal (~250ms)
            is_sentence = clean.endswith((".", "!", "?"))
            is_comma = clean.endswith((",", ";", "—", "–"))
            pause_ms = (
                getattr(self.voice_config, "pause_sentence_ms", 250)
                if is_sentence
                else (getattr(self.voice_config, "pause_comma_ms", 100) if is_comma else 0)
            )

            # Stage 2: Silence trim
            if getattr(self.voice_config, "trim_silence", True):
                stage2_wav = trim_audio_silence(
                    stage1_raw,
                    lead_padding_ms=150,
                    trail_padding_ms=150,
                    post_pause_ms=pause_ms,
                    out_format="wav",
                )
            else:
                stage2_wav = stage1_raw

            # Stage 3: Speed / Pitch / Limiter FX (-1 dBFS limiter)
            mono_trimmed, _ = decode_audio_to_mono(stage2_wav, target_sr=sr)
            limited = apply_limiter(mono_trimmed, threshold_dbfs=-1.0)
            stage3_wav = encode_mono_to_wav(limited, sample_rate=sr)

            # Stage 4: Chunk joining
            stage4_wav = stage3_wav

            # Stage 5: Final playback buffer
            stage5_wav = stage3_wav
            audio_data = stage5_wav

            stages = {
                "stage1_raw.wav": stage1_raw,
                "stage2_trimmed.wav": stage2_wav,
                "stage3_fx.wav": stage3_wav,
                "stage4_joined.wav": stage4_wav,
                "stage5_final.wav": stage5_wav,
            }

            # Generate viseme alignment cues
            visemes = generate_lipsync_cues(
                audio_data, clean, word_timings=word_timings, offset_ms=0.0
            )

            dur = (
                word_timings[-1]["end"]
                if word_timings
                else len(audio_data) / 48000.0
            )

            return AudioChunk(
                data=audio_data,
                sample_rate=24000,
                duration_sec=round(dur, 2),
                amplitude=0.7,
                word_timings=word_timings,
                visemes=visemes,
                provider_mode="cloud",
                stages=stages,
            )

        except Exception as e:
            raise TTSProviderError(f"Edge-TTS synthesis error: {e}") from e

    async def stream_synthesize(self, text: str, emotion: str = "neutral") -> AsyncIterator[AudioChunk]:
        """Stream chunks with natural prosody and asynchronous prefetching."""
        chunks = chunk_text_for_tts(text)
        if not chunks:
            return

        # Start prefetching the first chunk
        next_task = asyncio.create_task(self.synthesize_chunk(chunks[0], emotion=emotion))

        for idx in range(len(chunks)):
            # Wait for current chunk
            chunk = await next_task
            # Concurrently prefetch next chunk if more chunks remain
            if idx + 1 < len(chunks):
                next_task = asyncio.create_task(
                    self.synthesize_chunk(chunks[idx + 1], emotion=emotion)
                )
            yield chunk
