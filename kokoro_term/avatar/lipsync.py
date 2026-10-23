from __future__ import annotations

import math
import struct
import wave
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
import numpy as np


class LipSyncEngine(ABC):
    """Abstract interface for lip-sync mapping."""

    @abstractmethod
    def get_mouth_shape(self, timestamp_sec: float) -> str:
        """Return the active mouth shape for the given audio playback timestamp."""
        pass


class AmplitudeLipSync(LipSyncEngine):
    """
    Computes RMS audio envelope and maps amplitude to mouth shapes
    with exponential smoothing and hysteresis to prevent jitter.
    """

    def __init__(
        self,
        close_threshold: float = 0.05,
        open_threshold: float = 0.25,
        wide_threshold: float = 0.55,
        smoothing: float = 0.4,
    ):
        self.close_threshold = close_threshold
        self.open_threshold = open_threshold
        self.wide_threshold = wide_threshold
        self.smoothing = smoothing

        self._current_amplitude: float = 0.0
        self._current_mouth: str = "closed"
        self._timeline: list[tuple[float, float, str]] = [] # (start_sec, end_sec, mouth_shape)

    def load_audio_pcm(self, pcm_bytes: bytes, sample_rate: int = 24000, chunk_ms: int = 50) -> None:
        """Process PCM audio bytes and compute smoothed mouth shape timeline."""
        if not pcm_bytes:
            self._timeline = []
            return

        chunk_size = int(sample_rate * (chunk_ms / 1000.0)) * 2 # 16-bit
        self._timeline = []

        total_bytes = len(pcm_bytes)
        t = 0.0
        smoothed_amp = 0.0

        for offset in range(0, total_bytes, chunk_size):
            chunk = pcm_bytes[offset : offset + chunk_size]
            if len(chunk) < 4:
                continue

            # Convert 16-bit PCM bytes to numpy array
            count = len(chunk) // 2
            samples = np.frombuffer(chunk[: count * 2], dtype=np.int16).astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(samples ** 2)))

            # Exponential moving average smoothing
            smoothed_amp = (self.smoothing * rms) + ((1.0 - self.smoothing) * smoothed_amp)

            # Hysteresis mapping
            if smoothed_amp < self.close_threshold:
                mouth = "closed"
            elif smoothed_amp < self.open_threshold:
                mouth = "u"
            elif smoothed_amp < self.wide_threshold:
                mouth = "a"
            else:
                mouth = "o"

            chunk_duration = len(chunk) / (sample_rate * 2)
            self._timeline.append((t, t + chunk_duration, mouth))
            t += chunk_duration

    def get_mouth_shape(self, timestamp_sec: float) -> str:
        if not self._timeline or timestamp_sec < 0:
            return "closed"

        for start, end, shape in self._timeline:
            if start <= timestamp_sec <= end:
                return shape

        return "closed"


class VisemeLipSync(LipSyncEngine):
    """Phoneme / Viseme-based lip-sync mapping."""

    VISEME_MAP = {
        "A": "a",
        "AA": "a",
        "AE": "a",
        "AH": "a",
        "AO": "o",
        "AW": "a",
        "AY": "a",
        "B": "closed",
        "CH": "i",
        "D": "i",
        "DH": "i",
        "EH": "e",
        "ER": "u",
        "EY": "e",
        "F": "u",
        "G": "i",
        "HH": "a",
        "IH": "i",
        "IY": "i",
        "JH": "i",
        "K": "i",
        "L": "i",
        "M": "closed",
        "N": "i",
        "NG": "i",
        "OW": "o",
        "OY": "o",
        "P": "closed",
        "R": "u",
        "S": "i",
        "SH": "i",
        "T": "i",
        "TH": "i",
        "UH": "u",
        "UW": "u",
        "V": "u",
        "W": "u",
        "Y": "i",
        "Z": "i",
        "ZH": "i",
    }

    def __init__(self):
        self._cues: list[tuple[float, float, str]] = [] # (start_sec, end_sec, mouth_shape)

    def set_cues(self, cues: list[tuple[float, float, str]]) -> None:
        """Set timed viseme cues: [(start_sec, end_sec, phoneme_or_viseme), ...]"""
        self._cues = []
        for start, end, cue in cues:
            mouth = self.VISEME_MAP.get(cue.upper(), "closed")
            self._cues.append((start, end, mouth))

    def get_mouth_shape(self, timestamp_sec: float) -> str:
        for start, end, mouth in self._cues:
            if start <= timestamp_sec <= end:
                return mouth
        return "closed"


def generate_test_speech_wav(filepath: str | Path = "data/test_talk.wav", duration_sec: float = 3.0) -> Path:
    """Generate a clean synthetic modulated sine-wave speech WAV file for lip-sync verification."""
    p = Path(filepath)
    p.parent.mkdir(parents=True, exist_ok=True)

    sample_rate = 24000
    total_samples = int(sample_rate * duration_sec)

    # Generate speech-like modulated vowels (syllables)
    t = np.linspace(0, duration_sec, total_samples, endpoint=False)
    # Fundamental frequency ~220 Hz modulated with cadence
    pitch = 220.0 + 30.0 * np.sin(2 * np.pi * 1.5 * t)
    carrier = np.sin(2 * np.pi * pitch * t)
    # Syllable envelope pulsing at ~4 Hz
    envelope = np.clip(np.sin(2 * np.pi * 3.5 * t) ** 2, 0.05, 0.95)
    audio = (carrier * envelope * 24000.0).astype(np.int16)

    with wave.open(str(p), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio.tobytes())

    return p
