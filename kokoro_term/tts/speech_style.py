from __future__ import annotations

import re


def split_sentences(text: str) -> list[str]:
    """Split text into sentence chunks for low-latency streaming TTS."""
    clean = re.sub(r"\[emotion:[a-zA-Z0-9_-]+\]\s*", "", text).strip()
    if not clean:
        return []

    # Split on sentence terminals while keeping punctuation
    parts = re.split(r"([.!?]+[\s\n]+)", clean)
    sentences = []
    current = ""
    for part in parts:
        current += part
        if re.search(r"[.!?]+[\s\n]*$", current):
            if current.strip():
                sentences.append(current.strip())
            current = ""
    if current.strip():
        sentences.append(current.strip())

    return sentences or [clean]


def apply_speech_style(text: str, emotion: str = "neutral", stutter_on_blush: bool = True) -> str:
    """
    Apply character-specific speech styling (gentle stuttering when flustered, accent tweaks).
    """
    styled = text

    if emotion in ("blush", "flustered") and stutter_on_blush:
        # Subtle gentle stuttering on first consonant or pronoun
        def _stutter_replace(match: re.Match) -> str:
            word = match.group(0)
            if word.lower() in ("what", "why", "where", "how", "who"):
                return f"{word[0]}-{word.lower()}"
            elif word.lower() in ("i", "i'm"):
                return f"I... {word.lower()}"
            elif word.lower() in ("that", "this"):
                return f"Th-{word.lower()}"
            return word

        styled = re.sub(r"\b(What|Why|Where|How|Who|I|I'm|That|This)\b", _stutter_replace, styled, count=1)

    return styled
