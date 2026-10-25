from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import wave
from typing import Optional, List, Dict, Tuple
import numpy as np


# Rhubarb mouth shape letter mapping to anime mouth shapes
RHUBARB_TO_MOUTH = {
    "A": "closed",  # Closed mouth (M, P, B)
    "B": "u",       # Slightly open mouth (S, T, D)
    "C": "a",       # Open mouth (EH, AE)
    "D": "a",       # Wide open mouth (AA)
    "E": "o",       # Slightly rounded mouth (AO, ER)
    "F": "u",       # Puckered lips (UW, OW, W)
    "G": "i",       # Upper teeth on lower lip (F, V)
    "H": "a",       # Wide mouth (L, Y)
    "X": "closed",  # Idle / Rest mouth
}

# Letter/syllable heuristics for phoneme estimation
VOWEL_MOUTH_MAP = {
    "a": "a",
    "e": "e",
    "i": "i",
    "o": "o",
    "u": "u",
}
CONSONANT_MOUTH_MAP = {
    "m": "closed",
    "p": "closed",
    "b": "closed",
    "f": "u",
    "v": "u",
    "w": "u",
    "s": "i",
    "z": "i",
    "t": "i",
    "d": "i",
    "k": "i",
    "g": "i",
    "n": "i",
    "l": "i",
    "r": "u",
    "h": "a",
    "y": "i",
}


def run_rhubarb_lipsync(
    audio_wav_bytes: bytes,
    dialog_text: str,
) -> Optional[List[Dict[str, float | str]]]:
    """Run Rhubarb Lip Sync if binary is installed on the host system.

    Uses the known transcript as the dialog file (-d) to achieve maximum alignment accuracy.
    Returns list of visemes: [{'time': float, 'viseme': str}, ...] or None if Rhubarb unavailable.
    """
    rhubarb_bin = shutil.which("rhubarb")
    if not rhubarb_bin:
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = os.path.join(tmpdir, "chunk.wav")
        txt_path = os.path.join(tmpdir, "dialog.txt")

        with open(wav_path, "wb") as f:
            f.write(audio_wav_bytes)

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(dialog_text)

        cmd = [
            rhubarb_bin,
            "-f", "json",
            "-d", txt_path,
            "--extendedShapes", "GHX",
            wav_path,
        ]

        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2.0,
                check=True,
            )
            out_json = json.loads(proc.stdout.decode("utf-8"))
            mouth_cues = out_json.get("mouthCues", [])
            visemes = []
            for cue in mouth_cues:
                shape = RHUBARB_TO_MOUTH.get(cue.get("value", "X"), "closed")
                visemes.append({
                    "time": round(float(cue.get("start", 0.0)), 3),
                    "end": round(float(cue.get("end", 0.0)), 3),
                    "viseme": shape,
                })
            return visemes
        except Exception:
            return None


def estimate_word_visemes(
    word: str, start_sec: float, end_sec: float
) -> List[Dict[str, float | str]]:
    """Estimate mouth shape progression across a word's duration aligned to WordBoundary timings."""
    clean_word = re.sub(r"[^\w]", "", word).lower()
    dur = max(0.06, end_sec - start_sec)
    if not clean_word:
        return [{"time": round(start_sec, 3), "end": round(end_sec, 3), "viseme": "closed"}]

    shapes: List[str] = []
    for ch in clean_word:
        if ch in VOWEL_MOUTH_MAP:
            shapes.append(VOWEL_MOUTH_MAP[ch])
        elif ch in CONSONANT_MOUTH_MAP:
            # Only add consonant if previous wasn't same shape
            c_shape = CONSONANT_MOUTH_MAP[ch]
            if not shapes or shapes[-1] != c_shape:
                shapes.append(c_shape)

    if not shapes:
        shapes = ["a"]

    # Allocate time proportionally
    dt = dur / len(shapes)
    result = []
    for idx, s in enumerate(shapes):
        t_start = start_sec + idx * dt
        t_end = t_start + dt
        result.append({
            "time": round(t_start, 3),
            "end": round(t_end, 3),
            "viseme": s,
        })
    return result


def align_visemes_to_words(
    text: str,
    word_timings: List[Dict],
    offset_ms: float = 0.0,
) -> List[Dict[str, float | str]]:
    """Construct a continuous timed viseme sequence from WordBoundary events."""
    if not word_timings:
        return []

    shift = offset_ms / 1000.0
    visemes: List[Dict[str, float | str]] = []
    prev_end = 0.0

    for w in word_timings:
        w_text = w.get("word", "")
        start = max(0.0, w.get("start", 0.0) + shift)
        end = max(start + 0.05, w.get("end", start + 0.1) + shift)

        # If there is a pause between words (>50ms), close mouth
        if start - prev_end > 0.05:
            visemes.append({
                "time": round(prev_end, 3),
                "end": round(start, 3),
                "viseme": "closed",
            })

        word_cues = estimate_word_visemes(w_text, start, end)
        visemes.extend(word_cues)
        prev_end = end

    return visemes


def generate_lipsync_cues(
    audio_wav_bytes: bytes,
    text: str,
    word_timings: Optional[List[Dict]] = None,
    offset_ms: float = 0.0,
) -> List[Dict[str, float | str]]:
    """Complete multi-tier lip-sync alignment hierarchy:

    1. Rhubarb Lip Sync with transcript dialog file (highest accuracy if installed)
    2. Fallback: Phoneme estimation from text aligned to WordBoundary timings
    3. Fallback: Proportional sentence phonemes or amplitude
    """
    # Tier 1: Try Rhubarb Lip Sync with transcript dialog
    rhubarb_cues = run_rhubarb_lipsync(audio_wav_bytes, text)
    if rhubarb_cues:
        if offset_ms != 0.0:
            shift = offset_ms / 1000.0
            for cue in rhubarb_cues:
                cue["time"] = round(max(0.0, cue["time"] + shift), 3)
                cue["end"] = round(max(0.0, cue["end"] + shift), 3)
        return rhubarb_cues

    # Tier 2: Align text phonemes to WordBoundary timestamps
    if word_timings:
        return align_visemes_to_words(text, word_timings, offset_ms=offset_ms)

    # Tier 3: Proportional distribution based on words in text
    words = text.strip().split()
    if not words:
        return []
    # Default estimate assuming ~250ms per word
    synthetic_words = []
    t = 0.0
    for w in words:
        w_dur = 0.05 + 0.04 * len(w)
        synthetic_words.append({"word": w, "start": t, "end": t + w_dur})
        t += w_dur + 0.05

    return align_visemes_to_words(text, synthetic_words, offset_ms=offset_ms)
