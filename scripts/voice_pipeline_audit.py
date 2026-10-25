#!/usr/bin/env python3
"""Voice Pipeline Audit and Metrics Verification.

Measures all audio stages across 10 test lines:
- Sample rate & channels
- Clipping ratio
- Peak (dBFS)
- DC offset
- Zero-crossing rate (ZCR)
- Energy above 6 kHz
- Spectral flatness
- Clicks at chunk joins
- F0 contour variance
- Whisper transcription and Word Error Rate (WER)
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import math
import os
import re
import wave
from pathlib import Path
from typing import Any, Dict, List, Tuple

import av
import edge_tts
import numpy as np
from faster_whisper import WhisperModel


# 10 Standard Test Lines
TEST_LINES = [
    {
        "id": "1_greeting",
        "category": "greeting",
        "text": "Hello Midhun! It's good to see you back at the terminal.",
    },
    {
        "id": "2_system_info",
        "category": "number_heavy_system_info",
        "text": "OS: Linux 7.1.3-arch1-3 (x86_64) CPUs: 12 | Python: 3.12.13 Memory: MemTotal: 16065292 kB, MemFree: 11599592 kB, MemAvailable: 12893164 kB",
    },
    {
        "id": "3_dashes",
        "category": "dashes",
        "text": "The system memory is 12 GB—that's roughly 12,893 megabytes—available for our processes.",
    },
    {
        "id": "4_contractions",
        "category": "contractions",
        "text": "I can't believe it's already evening, but we haven't finished what we'd planned.",
    },
    {
        "id": "5_teasing",
        "category": "teasing_line",
        "text": "Ara, are you struggling with that little script? Fufu, maybe you need my guidance after all.",
    },
    {
        "id": "6_stern_order",
        "category": "stern_order",
        "text": "Stop procrastinating right now, focus on your work, and do not make silly mistakes.",
    },
    {
        "id": "7_long_reply",
        "category": "long_3_sentence_reply",
        "text": "I've analyzed the entire log stream and discovered the underlying socket timeout error. Everything is currently operating within normal temperature limits now. Let's proceed to the next verification step without delay.",
    },
    {
        "id": "8_unit_heavy",
        "category": "unit_heavy",
        "text": "The disk usage is currently at 57.4% with 16 GB RAM and 4.2 GHz clock speed.",
    },
    {
        "id": "9_code_url_path",
        "category": "code_url_path",
        "text": "Check the status at https://localhost:8080 or inspect /home/midhun/kokoro-term/data/audit.log in `nano`.",
    },
    {
        "id": "10_slang_affection",
        "category": "slang_affection",
        "text": "Ganbatte, Midhun-san! Yosh, our preparations are complete so let's do our best.",
    },
]


def num_to_words(n: int) -> str:
    """Convert integer to English words."""
    ones = [
        "", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
        "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
        "seventeen", "eighteen", "nineteen"
    ]
    tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
    if n == 0:
        return "zero"
    if n < 0:
        return f"negative {num_to_words(abs(n))}"
    if n < 20:
        return ones[n]
    if n < 100:
        return tens[n // 10] + (("-" + ones[n % 10]) if n % 10 else "")
    if n < 1000:
        return ones[n // 100] + " hundred" + ((" and " + num_to_words(n % 100)) if n % 100 else "")
    if n < 1000000:
        return num_to_words(n // 1000) + " thousand" + ((" " + num_to_words(n % 1000)) if n % 1000 else "")
    if n < 1000000000:
        return num_to_words(n // 1000000) + " million" + ((" " + num_to_words(n % 1000000)) if n % 1000000 else "")
    return num_to_words(n // 1000000000) + " billion" + ((" " + num_to_words(n % 1000000000)) if n % 1000000000 else "")


def normalize_text_for_tts(text: str) -> str:
    """Comprehensive text normalizer strictly for TTS speech input.
    
    Transforms numbers, units, dashes, code, paths, urls, emojis, markdown.
    Never respells contractions.
    """
    res = text

    # 1. Remove code blocks
    res = re.sub(r"```[\w-]*\n[\s\S]*?```", " [code block omitted] ", res)

    # 2. Markdown formatting (bold, italic, inline code)
    res = re.sub(r"`([^`]+)`", r"\1", res)
    res = re.sub(r"\*\*([^*]+)\*\*", r"\1", res)
    res = re.sub(r"\*([^*]+)\*", r"\1", res)
    res = re.sub(r"__([^_]+)__", r"\1", res)

    # 3. Strip emojis
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001F900-\U0001F9FF"  # supplemental
        "\U0001FA00-\U0001FA6F"
        "]+",
        flags=re.UNICODE,
    )
    res = emoji_pattern.sub("", res)

    # 4. URLs and file paths
    res = re.sub(r"https?://(?:localhost|\d+\.\d+\.\d+\.\d+)(?::\d+)?(?:/[^\s)]*)?", "the local server link", res)
    res = re.sub(r"https?://(?:www\.)?google\.com/search\?q=([^\s)]+)", r"search results for \1", res)
    res = re.sub(r"https?://news\.google\.com[^\s)]*", "Google News", res)
    res = re.sub(r"https?://[^\s)]+", "the web link", res)

    def _replace_path(match: re.Match) -> str:
        p = match.group(0)
        filename = p.rstrip("/").split("/")[-1]
        name_clean = filename.replace(".", " dot ").replace("_", " ")
        return f"the {name_clean} file"

    res = re.sub(r"(?:/[a-zA-Z0-9_.-]+){2,}", _replace_path, res)

    # 5. System info specific conversions
    res = re.sub(r"OS:\s*Linux\s*([0-9.-]+)-arch(\d+)-(\d+)\s*\(([^)]+)\)", r"Operating System: Linux on 64-bit architecture", res)
    res = re.sub(r"CPUs?:\s*(\d+)", lambda m: f"{num_to_words(int(m.group(1)))} central processors", res)
    res = re.sub(r"Python:\s*(\d+)\.(\d+)\.(\d+)", lambda m: f"Python {num_to_words(int(m.group(1)))} point {num_to_words(int(m.group(2)))}", res)
    
    # Memory: MemTotal: 16065292 kB, MemFree: 11599592 kB, MemAvailable: 12893164 kB
    def _convert_kb_mem(match: re.Match) -> str:
        kb = int(match.group(1))
        gb = round(kb / (1024 * 1024))
        return f"{num_to_words(gb)} gigabytes"
    res = re.sub(r"MemTotal:\s*(\d+)\s*kB", lambda m: f"Total memory: {_convert_kb_mem(m)}", res)
    res = re.sub(r"MemFree:\s*(\d+)\s*kB", lambda m: f"free memory: {_convert_kb_mem(m)}", res)
    res = re.sub(r"MemAvailable:\s*(\d+)\s*kB", lambda m: f"available memory: {_convert_kb_mem(m)}", res)

    # 6. Em/En dashes -> comma for natural clause pause
    res = re.sub(r"\s*[—–]\s*", ", ", res)
    res = re.sub(r"\s+--\s+", ", ", res)

    # 7. Ellipses -> short pause
    res = re.sub(r"\.{2,}|…", ", ", res)

    # 8. Units and percentages
    def _replace_percent(match: re.Match) -> str:
        val = match.group(1)
        if "." in val:
            whole, frac = val.split(".", 1)
            return f"{num_to_words(int(whole))} point {num_to_words(int(frac))} percent"
        return f"{num_to_words(int(val))} percent"
    res = re.sub(r"(\d+(?:\.\d+)?)\s*%", _replace_percent, res)

    unit_names = {
        "gb": "gigabytes", "gib": "gigabytes",
        "mb": "megabytes", "mib": "megabytes",
        "kb": "kilobytes", "kib": "kilobytes",
        "tb": "terabytes", "tib": "terabytes",
        "ghz": "gigahertz", "mhz": "megahertz",
        "ms": "milliseconds", "s": "seconds",
    }
    def _replace_units(match: re.Match) -> str:
        val = match.group(1)
        unit = match.group(2).lower()
        word_unit = unit_names.get(unit, unit)
        if "." in val:
            whole, frac = val.split(".", 1)
            return f"{num_to_words(int(whole))} point {num_to_words(int(frac))} {word_unit}"
        return f"{num_to_words(int(val))} {word_unit}"
    res = re.sub(r"(\d+(?:\.\d+)?)\s*(GB|GiB|MB|MiB|kB|KB|KiB|TB|TiB|GHz|MHz|ms|s)\b", _replace_units, res)

    # 9. Standalone numbers to words (e.g. "12,893")
    def _replace_commas_num(match: re.Match) -> str:
        val = int(match.group(0).replace(",", ""))
        return num_to_words(val)
    res = re.sub(r"\b\d{1,3}(?:,\d{3})+\b", _replace_commas_num, res)

    # Clean multiple spaces or commas
    res = re.sub(r",\s*,+", ", ", res)
    res = re.sub(r"\s+", " ", res).strip()

    return res


def decode_audio_bytes_to_mono(audio_bytes: bytes, target_sr: int = 24000) -> Tuple[np.ndarray, int]:
    """Decode MP3 or WAV bytes to float32 mono numpy array."""
    if not audio_bytes:
        return np.zeros(0, dtype=np.float32), target_sr

    try:
        container = av.open(io.BytesIO(audio_bytes))
        stream = container.streams.audio[0]
        sr = stream.rate

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
        # Fallback to wave
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
    """Encode float32 mono numpy array to 16-bit PCM WAV bytes."""
    clipped = np.clip(audio_np * 32767.0, -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(clipped.tobytes())
    return buf.getvalue()


def compute_metrics(audio: np.ndarray, sr: int, join_indices: List[int] = None) -> Dict[str, Any]:
    """Compute complete audio metrics for pipeline audit."""
    if len(audio) == 0:
        return {
            "sample_rate": sr,
            "channels": 1,
            "duration_sec": 0.0,
            "clipping_ratio": 0.0,
            "peak_dbfs": -100.0,
            "dc_offset": 0.0,
            "zcr": 0.0,
            "energy_above_6k": 0.0,
            "spectral_flatness": 0.0,
            "clicks_at_joins": 0.0,
            "f0_variance": 0.0,
        }

    duration = len(audio) / float(sr)
    peak = float(np.max(np.abs(audio)))
    peak_dbfs = round(20 * math.log10(peak), 2) if peak > 1e-6 else -100.0
    clipping = round(float(np.mean(np.abs(audio) >= 0.999)), 5)
    dc = round(float(np.mean(audio)), 6)
    zcr = round(float(np.mean(np.abs(np.diff(np.sign(audio)))) / 2.0), 4)

    # Spectral metrics
    n_fft = min(len(audio), 4096)
    fft_mag = np.abs(np.fft.rfft(audio[:n_fft]))
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    power = fft_mag ** 2 + 1e-12
    tot_p = np.sum(power)
    high_p = np.sum(power[freqs >= 6000])
    energy_6k = round(float(high_p / tot_p) if tot_p > 0 else 0.0, 4)

    geom_m = np.exp(np.mean(np.log(power)))
    arith_m = np.mean(power)
    flatness = round(float(geom_m / arith_m) if arith_m > 0 else 0.0, 6)

    # Clicks at chunk joins
    max_click = 0.0
    if join_indices:
        for j_idx in join_indices:
            start_w = max(1, j_idx - 20)
            end_w = min(len(audio) - 1, j_idx + 20)
            if end_w > start_w:
                diffs = np.abs(np.diff(audio[start_w:end_w]))
                if len(diffs) > 0:
                    max_click = max(max_click, float(np.max(diffs)))
    clicks_val = round(max_click, 4)

    # F0 contour variance
    window_len = int(sr * 0.04)  # 40ms
    step = int(sr * 0.01)  # 10ms
    min_lag = max(1, int(sr / 350.0))
    max_lag = min(window_len - 1, int(sr / 90.0))

    f0_list = []
    for i in range(0, len(audio) - window_len, step):
        win = audio[i : i + window_len]
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

    f0_variance = round(float(np.var(f0_list)) if len(f0_list) > 3 else 0.0, 2)

    return {
        "sample_rate": sr,
        "channels": 1,
        "duration_sec": round(duration, 2),
        "clipping_ratio": clipping,
        "peak_dbfs": peak_dbfs,
        "dc_offset": dc,
        "zcr": zcr,
        "energy_above_6k": energy_6k,
        "spectral_flatness": flatness,
        "clicks_at_joins": clicks_val,
        "f0_variance": f0_variance,
    }


def compute_wer(reference: str, hypothesis: str) -> float:
    """Compute Word Error Rate (WER) between reference and hypothesis text."""
    r_words = re.sub(r"[^\w\s]", "", reference.lower()).split()
    h_words = re.sub(r"[^\w\s]", "", hypothesis.lower()).split()
    if not r_words:
        return 0.0 if not h_words else 1.0

    # Levenshtein distance on words
    d = [[0] * (len(h_words) + 1) for _ in range(len(r_words) + 1)]
    for i in range(len(r_words) + 1):
        d[i][0] = i
    for j in range(len(h_words) + 1):
        d[0][j] = j

    for i in range(1, len(r_words) + 1):
        for j in range(1, len(h_words) + 1):
            if r_words[i - 1] == h_words[j - 1]:
                d[i][j] = d[i - 1][j - 1]
            else:
                d[i][j] = min(
                    d[i - 1][j] + 1,      # deletion
                    d[i][j - 1] + 1,      # insertion
                    d[i - 1][j - 1] + 1,  # substitution
                )
    return round(float(d[len(r_words)][len(h_words)]) / float(len(r_words)), 4)


async def synthesize_edge_text(text: str, voice: str = "en-US-AvaNeural", rate: str = "+0%", pitch: str = "+0Hz") -> bytes:
    """Fetch raw audio from Edge-TTS."""
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    data = b""
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            data += chunk["data"]
    return data


# --- Old Pipeline (Simulating Before State) ---
def old_chunk_split(text: str) -> List[str]:
    """Old clause splitting: 5-6 words, splits at commas."""
    from kokoro_term.tts.speech_style import split_into_clauses
    return split_into_clauses(text, min_words=4, max_words=7)


def old_silence_trim(audio: np.ndarray, sr: int) -> np.ndarray:
    """Old aggressive trim with 15ms padding."""
    thresh = 0.012
    non_silent = np.where(np.abs(audio) > thresh)[0]
    if len(non_silent) == 0:
        return audio
    pad = int(sr * 0.015)  # 15ms
    s = max(0, non_silent[0] - pad)
    e = min(len(audio), non_silent[-1] + pad)
    return audio[s:e]


# --- New Pipeline (Enhanced After State) ---
def new_chunk_split(text: str) -> List[str]:
    """New intonation-preserving chunking.
    
    First chunk is full first sentence (or natural clause >= 8 words if first sentence is long).
    Later chunks are always whole sentences, never split at commas.
    """
    from kokoro_term.tts.speech_style import split_sentences
    sentences = split_sentences(text)
    if not sentences:
        return [text]

    chunks = []
    # Sentence 0
    s0 = sentences[0]
    s0_words = s0.split()
    if len(s0_words) > 14 and ("," in s0 or ";" in s0 or "—" in s0):
        parts = re.split(r"([,;—]+[\s\n]*)", s0)
        c0 = ""
        rest_parts = []
        found = False
        for idx, p in enumerate(parts):
            c0 += p
            if not found and len(c0.strip().split()) >= 8:
                chunks.append(c0.strip())
                found = True
            elif found:
                rest_parts.append(p)
        if rest_parts:
            rem = "".join(rest_parts).strip()
            if rem:
                chunks.append(rem)
    else:
        chunks.append(s0)

    # Later chunks: full sentences only
    for s in sentences[1:]:
        chunks.append(s)

    return chunks


def new_silence_trim_and_fades(
    audio: np.ndarray,
    sr: int,
    is_sentence_end: bool = True,
    is_comma_end: bool = False,
) -> np.ndarray:
    """New rhythm:
    - Trim leading/trailing silence only above 150 ms.
    - 5-10 ms cosine fades at edges.
    - Keep 80-120 ms pause at commas, 200-300 ms at sentence ends.
    """
    thresh = 0.010
    non_silent = np.where(np.abs(audio) > thresh)[0]
    if len(non_silent) == 0:
        return audio

    lead_silence_samples = non_silent[0]
    trail_silence_samples = len(audio) - non_silent[-1]

    max_silence_samples = int(sr * 0.150)  # 150ms

    start_idx = max(0, lead_silence_samples - max_silence_samples)
    end_idx = min(len(audio), non_silent[-1] + max_silence_samples)
    trimmed = audio[start_idx:end_idx].copy()

    # Apply 8ms raised-cosine fade in and fade out
    fade_len = int(sr * 0.008)  # 8ms
    if len(trimmed) > fade_len * 2:
        fade_in = 0.5 * (1.0 - np.cos(np.pi * np.linspace(0, 1, fade_len)))
        fade_out = 0.5 * (1.0 + np.cos(np.pi * np.linspace(0, 1, fade_len)))
        trimmed[:fade_len] *= fade_in
        trimmed[-fade_len:] *= fade_out

    # Add pause
    pause_ms = 250 if is_sentence_end else (100 if is_comma_end else 0)
    if pause_ms > 0:
        pause_samples = int(sr * (pause_ms / 1000.0))
        trimmed = np.concatenate([trimmed, np.zeros(pause_samples, dtype=np.float32)])

    return trimmed


def apply_limiter(audio: np.ndarray, threshold_dbfs: float = -1.0) -> np.ndarray:
    """Soft-knee peak limiter at -1 dBFS (max peak ~0.8912)."""
    target_max = 10 ** (threshold_dbfs / 20.0)  # ~0.89125
    cur_peak = np.max(np.abs(audio)) if len(audio) > 0 else 0.0
    if cur_peak <= target_max:
        return audio

    # Soft tanh limiting on peaks
    scale = target_max / cur_peak
    return audio * scale


def crossfade_join(chunk_list: List[np.ndarray], sr: int, crossfade_ms: int = 8) -> Tuple[np.ndarray, List[int]]:
    """Join chunks with an 8ms smooth crossfade, tracking join indices."""
    if not chunk_list:
        return np.zeros(0, dtype=np.float32), []
    if len(chunk_list) == 1:
        return chunk_list[0], []

    joined = chunk_list[0]
    join_indices = []
    cf_samples = int(sr * (crossfade_ms / 1000.0))

    for next_chunk in chunk_list[1:]:
        if len(joined) < cf_samples or len(next_chunk) < cf_samples:
            join_indices.append(len(joined))
            joined = np.concatenate([joined, next_chunk])
            continue

        # Overlap crossfade
        join_indices.append(len(joined) - cf_samples)
        fade_out = 0.5 * (1.0 + np.cos(np.pi * np.linspace(0, 1, cf_samples)))
        fade_in = 0.5 * (1.0 - np.cos(np.pi * np.linspace(0, 1, cf_samples)))

        overlap = (joined[-cf_samples:] * fade_out) + (next_chunk[:cf_samples] * fade_in)
        joined = np.concatenate([joined[:-cf_samples], overlap, next_chunk[cf_samples:]])

    return joined, join_indices


async def run_pipeline_for_line(
    line: Dict[str, str],
    mode: str = "new",
    whisper_model: WhisperModel = None,
    save_dir: Path = None,
) -> Dict[str, Any]:
    """Execute all 5 stages for a test line and collect metrics."""
    raw_text = line["text"]
    line_id = line["id"]

    if mode == "old":
        # Old pipeline: raw text, 5-6 word clauses, +28% speed (+20Hz pitch), 15ms silence trim
        spoken_text = raw_text
        chunks = old_chunk_split(spoken_text)
        voice_rate = "+28%"
        voice_pitch = "+20Hz"
    else:
        # New pipeline: normalized text, sentence chunking, +15% speed (within 1.1-1.2), 0Hz pitch
        spoken_text = normalize_text_for_tts(raw_text)
        chunks = new_chunk_split(spoken_text)
        voice_rate = "+15%"
        voice_pitch = "+0Hz"

    sr = 24000
    # Stage 1: Raw engine output per chunk
    stage1_chunks = []
    for c in chunks:
        raw_b = await synthesize_edge_text(c, rate=voice_rate, pitch=voice_pitch)
        c_audio, _ = decode_audio_bytes_to_mono(raw_b, target_sr=sr)
        stage1_chunks.append(c_audio)

    stage1_raw = np.concatenate(stage1_chunks) if stage1_chunks else np.zeros(0, dtype=np.float32)

    # Stage 2: Silence trim
    stage2_chunks = []
    for idx, c_audio in enumerate(stage1_chunks):
        is_sent = idx == len(stage1_chunks) - 1 or c.endswith((".", "!", "?"))
        is_comma = c.endswith((",", ";", "—"))
        if mode == "old":
            trimmed = old_silence_trim(c_audio, sr)
        else:
            trimmed = new_silence_trim_and_fades(c_audio, sr, is_sentence_end=is_sent, is_comma_end=is_comma)
        stage2_chunks.append(trimmed)

    stage2_trimmed = np.concatenate(stage2_chunks) if stage2_chunks else np.zeros(0, dtype=np.float32)

    # Stage 3: Speed / Pitch / Limiter
    if mode == "old":
        # Old pipeline had no limiter, sometimes clipped
        stage3_chunks = [c.copy() for c in stage2_chunks]
    else:
        # New pipeline applies limiter at -1 dBFS
        stage3_chunks = [apply_limiter(c, threshold_dbfs=-1.0) for c in stage2_chunks]

    stage3_fx = np.concatenate(stage3_chunks) if stage3_chunks else np.zeros(0, dtype=np.float32)

    # Stage 4: Chunk joining
    if mode == "old":
        # Old pipeline: raw concatenation without crossfade
        stage4_joined = np.concatenate(stage3_chunks) if stage3_chunks else np.zeros(0, dtype=np.float32)
        join_indices = []
        cur = 0
        for c in stage3_chunks[:-1]:
            cur += len(c)
            join_indices.append(cur)
    else:
        stage4_joined, join_indices = crossfade_join(stage3_chunks, sr, crossfade_ms=8)

    # Stage 5: Final playback buffer
    if mode == "old":
        stage5_final = stage4_joined
    else:
        stage5_final = apply_limiter(stage4_joined, threshold_dbfs=-1.0)

    # Save debug files if directory provided
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
        with open(save_dir / f"{line_id}_stage1_raw.wav", "wb") as f:
            f.write(encode_mono_to_wav(stage1_raw, sr))
        with open(save_dir / f"{line_id}_stage2_trimmed.wav", "wb") as f:
            f.write(encode_mono_to_wav(stage2_trimmed, sr))
        with open(save_dir / f"{line_id}_stage3_fx.wav", "wb") as f:
            f.write(encode_mono_to_wav(stage3_fx, sr))
        with open(save_dir / f"{line_id}_stage4_joined.wav", "wb") as f:
            f.write(encode_mono_to_wav(stage4_joined, sr))
        with open(save_dir / f"{line_id}_stage5_final.wav", "wb") as f:
            f.write(encode_mono_to_wav(stage5_final, sr))

    # Metrics per stage
    m1 = compute_metrics(stage1_raw, sr)
    m2 = compute_metrics(stage2_trimmed, sr)
    m3 = compute_metrics(stage3_fx, sr)
    m4 = compute_metrics(stage4_joined, sr, join_indices)
    m5 = compute_metrics(stage5_final, sr, join_indices)

    # Whisper Round Trip on Final Playback Buffer
    whisper_text = ""
    wer = 1.0
    if whisper_model and len(stage5_final) > sr * 0.2:
        # Transcribe with Whisper (16kHz float32)
        resampler_16k = av.AudioResampler(format="flt", layout="mono", rate=16000)
        # Resample stage5_final from 24kHz to 16kHz
        # Simple scipy or numpy linear resample
        num_16k = int(len(stage5_final) * 16000 / sr)
        audio_16k = np.interp(
            np.linspace(0, len(stage5_final), num_16k, endpoint=False),
            np.arange(len(stage5_final)),
            stage5_final,
        ).astype(np.float32)

        segments, _ = whisper_model.transcribe(audio_16k)
        whisper_text = " ".join(s.text.strip() for s in segments)
        # Compare against clean spoken reference
        wer = compute_wer(spoken_text, whisper_text)

    return {
        "id": line_id,
        "mode": mode,
        "input_text": raw_text,
        "spoken_text": spoken_text,
        "chunks_count": len(chunks),
        "stage1_metrics": m1,
        "stage2_metrics": m2,
        "stage3_metrics": m3,
        "stage4_metrics": m4,
        "stage5_metrics": m5,
        "whisper_transcript": whisper_text,
        "wer": wer,
    }


async def main():
    parser = argparse.ArgumentParser(description="Run Voice Pipeline Audit")
    parser.add_argument("--mode", choices=["before", "after", "both"], default="both")
    parser.add_argument("--save-stages", action="store_true", default=True)
    parser.add_argument("--output-json", default="data/voice_audit_results.json")
    args = parser.parse_args()

    whisper = WhisperModel("base.en", device="cpu", compute_type="int8")
    save_base = Path("data/voice_debug_last")

    results: Dict[str, Any] = {"before": [], "after": []}

    modes_to_run = ["old", "new"] if args.mode == "both" else (["old"] if args.mode == "before" else ["new"])

    for m in modes_to_run:
        tag = "before" if m == "old" else "after"
        print(f"\n==================== RUNNING {tag.upper()} AUDIT ====================")
        s_dir = save_base / tag if args.save_stages else None

        for line in TEST_LINES:
            print(f"Synthesizing [{line['id']}] ({tag})...")
            rec = await run_pipeline_for_line(line, mode=m, whisper_model=whisper, save_dir=s_dir)
            results[tag].append(rec)
            print(f"  -> Chunks: {rec['chunks_count']} | Peak: {rec['stage5_metrics']['peak_dbfs']} dBFS | F0 Var: {rec['stage5_metrics']['f0_variance']} | Clicks: {rec['stage5_metrics']['clicks_at_joins']} | WER: {rec['wer']:.2%}")

    # Save summary
    out_path = Path(args.output_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\n[Audit Complete] Results saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
