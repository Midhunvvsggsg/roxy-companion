from __future__ import annotations

import io
import math
import wave
from typing import Optional, Tuple, List
import numpy as np
import av


def decode_audio_to_mono(audio_bytes: bytes, target_sr: int = 24000) -> Tuple[np.ndarray, int]:
    """Decode audio bytes (MP3, WAV, OGG) to float32 mono array at target sample rate."""
    if not audio_bytes:
        return np.zeros(0, dtype=np.float32), target_sr

    try:
        container = av.open(io.BytesIO(audio_bytes))
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="flt", layout="mono", rate=target_sr)
        frames = []
        for frame in container.decode(audio=0):
            frames.extend(resampler.resample(frame))
        frames.extend(resampler.resample(None))

        if not frames:
            return np.zeros(0, dtype=np.float32), target_sr

        audio_np = np.concatenate([f.to_ndarray()[0] for f in frames])
        return audio_np, target_sr
    except Exception:
        # Fallback to standard wave module
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                sr = wf.getframerate()
                n = wf.getnframes()
                raw = wf.readframes(n)
                int_arr = np.frombuffer(raw, dtype=np.int16)
                float_arr = int_arr.astype(np.float32) / 32767.0
                return float_arr, sr
        except Exception:
            return np.zeros(0, dtype=np.float32), target_sr


def encode_mono_to_wav(audio_np: np.ndarray, sample_rate: int = 24000) -> bytes:
    """Encode float32 mono array to 16-bit PCM WAV bytes."""
    clipped = np.clip(audio_np * 32767.0, -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(clipped.tobytes())
    return buf.getvalue()


def apply_fades(audio: np.ndarray, sr: int = 24000, fade_ms: float = 8.0) -> np.ndarray:
    """Apply raised-cosine 5-10 ms fade-in and fade-out to prevent clicks at chunk boundaries."""
    if len(audio) == 0:
        return audio

    fade_samples = int(sr * (fade_ms / 1000.0))
    if len(audio) < fade_samples * 2:
        return audio

    result = audio.copy()
    fade_in = 0.5 * (1.0 - np.cos(np.pi * np.linspace(0, 1, fade_samples)))
    fade_out = 0.5 * (1.0 + np.cos(np.pi * np.linspace(0, 1, fade_samples)))

    result[:fade_samples] *= fade_in
    result[-fade_samples:] *= fade_out
    return result


def apply_limiter(audio: np.ndarray, threshold_dbfs: float = -1.0) -> np.ndarray:
    """Soft peak limiter capped at -1 dBFS (amplitude ~0.89125) to avoid clipping and harsh distortion."""
    if len(audio) == 0:
        return audio

    target_peak = 10.0 ** (threshold_dbfs / 20.0)  # ~0.89125
    cur_peak = float(np.max(np.abs(audio)))
    if cur_peak <= target_peak:
        return audio

    scale = target_peak / cur_peak
    return audio * scale


def crossfade_chunks(
    chunk_a: np.ndarray, chunk_b: np.ndarray, sr: int = 24000, crossfade_ms: float = 8.0
) -> np.ndarray:
    """Smoothly crossfade between two audio chunks over 5-10 ms."""
    if len(chunk_a) == 0:
        return chunk_b
    if len(chunk_b) == 0:
        return chunk_a

    cf_samples = int(sr * (crossfade_ms / 1000.0))
    if len(chunk_a) < cf_samples or len(chunk_b) < cf_samples:
        return np.concatenate([chunk_a, chunk_b])

    fade_out = 0.5 * (1.0 + np.cos(np.pi * np.linspace(0, 1, cf_samples)))
    fade_in = 0.5 * (1.0 - np.cos(np.pi * np.linspace(0, 1, cf_samples)))

    overlap = (chunk_a[-cf_samples:] * fade_out) + (chunk_b[:cf_samples] * fade_in)
    return np.concatenate([chunk_a[:-cf_samples], overlap, chunk_b[cf_samples:]])


def join_audio_chunks(chunks: List[np.ndarray], sr: int = 24000, crossfade_ms: float = 8.0) -> np.ndarray:
    """Join a list of audio chunks using smooth crossfades and a final -1 dBFS limiter."""
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    if len(chunks) == 1:
        return apply_limiter(chunks[0])

    joined = chunks[0]
    for nxt in chunks[1:]:
        joined = crossfade_chunks(joined, nxt, sr=sr, crossfade_ms=crossfade_ms)

    return apply_limiter(joined)


def trim_audio_silence(
    audio_bytes: bytes,
    threshold: float = 0.010,
    lead_padding_ms: int = 150,
    trail_padding_ms: int = 150,
    post_pause_ms: int = 0,
    out_format: str = "wav",
    sample_rate: int = 24000,
) -> bytes:
    """Trim leading and trailing silence above 150 ms without touching internal pauses.

    Applies anti-click fades and optional post-pause (e.g. 100ms for commas, 250ms for sentence ends).
    Uses a single sample rate (24000 Hz) and clean WAV encoding to avoid double lossy re-encoding.
    """
    if not audio_bytes:
        return audio_bytes

    mono, sr = decode_audio_to_mono(audio_bytes, target_sr=sample_rate)
    if len(mono) == 0:
        return audio_bytes

    non_silent = np.where(np.abs(mono) > threshold)[0]
    if len(non_silent) == 0:
        return audio_bytes

    lead_silence_samples = non_silent[0]
    trail_silence_samples = len(mono) - non_silent[-1]

    max_lead_samples = int(sr * (lead_padding_ms / 1000.0))
    max_trail_samples = int(sr * (trail_padding_ms / 1000.0))

    start_idx = max(0, lead_silence_samples - max_lead_samples)
    end_idx = min(len(mono), non_silent[-1] + max_trail_samples)
    trimmed = mono[start_idx:end_idx].copy()

    # Apply 8ms boundary fades
    trimmed = apply_fades(trimmed, sr=sr, fade_ms=8.0)

    # Append requested pause (e.g. 100ms for clause, 250ms for sentence)
    if post_pause_ms > 0:
        pause_samples = int(sr * (post_pause_ms / 1000.0))
        trimmed = np.concatenate([trimmed, np.zeros(pause_samples, dtype=np.float32)])

    # Apply limiter
    trimmed = apply_limiter(trimmed, threshold_dbfs=-1.0)

    if out_format.lower() == "wav":
        return encode_mono_to_wav(trimmed, sample_rate=sr)

    # MP3 output fallback
    try:
        out_buf = io.BytesIO()
        out_c = av.open(out_buf, mode="w", format="mp3")
        out_s = out_c.add_stream("mp3", rate=sr)
        out_s.bit_rate = 128000
        resampler = av.AudioResampler(format=out_s.format.name, rate=sr)
        frame = av.AudioFrame.from_ndarray(trimmed[None, :], format="flt", layout="mono")
        frame.sample_rate = sr
        for r_frame in resampler.resample(frame):
            for pkt in out_s.encode(r_frame):
                out_c.mux(pkt)
        for r_frame in resampler.resample(None):
            for pkt in out_s.encode(r_frame):
                out_c.mux(pkt)
        for pkt in out_s.encode():
            out_c.mux(pkt)
        out_c.close()
        res = out_buf.getvalue()
        return res if len(res) > 50 else audio_bytes
    except Exception:
        return encode_mono_to_wav(trimmed, sample_rate=sr)


def measure_fundamental_frequency(
    audio_bytes: bytes,
    min_freq: float = 90.0,
    max_freq: float = 350.0,
) -> Tuple[float, float]:
    """Measure duration in seconds and median fundamental frequency (F0) in Hz."""
    if not audio_bytes:
        return 0.0, 0.0

    mono, sr = decode_audio_to_mono(audio_bytes)
    if len(mono) == 0:
        return 0.0, 0.0

    duration_sec = len(mono) / float(sr)
    window_len = int(sr * 0.04)  # 40ms
    step = int(sr * 0.01)  # 10ms hop
    min_lag = max(1, int(sr / max_freq))
    max_lag = min(window_len - 1, int(sr / min_freq))

    f0_list = []
    for i in range(0, len(mono) - window_len, step):
        win = mono[i : i + window_len]
        rms = np.sqrt(np.mean(win**2))
        if rms < 0.02:
            continue

        corr = np.correlate(win, win, mode="full")
        corr = corr[len(win) - 1 :]
        sub = corr[min_lag:max_lag]
        if len(sub) == 0:
            continue

        peak_idx = min_lag + np.argmax(sub)
        if corr[0] > 0 and (corr[peak_idx] / corr[0]) > 0.35:
            pitch_hz = sr / float(peak_idx)
            if min_freq <= pitch_hz <= max_freq:
                f0_list.append(pitch_hz)

    median_f0 = float(np.median(f0_list)) if f0_list else 0.0
    return duration_sec, median_f0


def measure_f0_variance(
    audio_bytes: bytes,
    min_freq: float = 90.0,
    max_freq: float = 350.0,
) -> float:
    """Measure the variance of fundamental frequency across voiced frames."""
    if not audio_bytes:
        return 0.0

    mono, sr = decode_audio_to_mono(audio_bytes)
    if len(mono) == 0:
        return 0.0

    window_len = int(sr * 0.04)  # 40ms
    step = int(sr * 0.01)  # 10ms
    min_lag = max(1, int(sr / max_freq))
    max_lag = min(window_len - 1, int(sr / min_freq))

    f0_list = []
    for i in range(0, len(mono) - window_len, step):
        win = mono[i : i + window_len]
        rms = np.sqrt(np.mean(win**2))
        if rms < 0.02:
            continue
        corr = np.correlate(win, win, mode="full")
        corr = corr[len(win) - 1 :]
        sub = corr[min_lag:max_lag]
        if len(sub) == 0:
            continue
        peak_idx = min_lag + np.argmax(sub)
        if corr[0] > 0 and (corr[peak_idx] / corr[0]) > 0.35:
            pitch_hz = sr / float(peak_idx)
            f0_list.append(pitch_hz)

    return float(np.var(f0_list)) if len(f0_list) > 3 else 0.0
