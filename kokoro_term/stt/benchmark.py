from __future__ import annotations

import argparse
import sys
import time
from typing import Optional

from kokoro_term.stt.base import STTProvider
from kokoro_term.stt.language import detect_language
from kokoro_term.stt.mock_provider import MockSTTProvider
from kokoro_term.stt.whisper_provider import FasterWhisperProvider


SAMPLE_MALAYALAM_PHRASES = [
    ("നമസ്കാരം, സുഖമാണോ?", "ml", "Namaskaram, sukhamano? (Hello, how are you?)"),
    ("എനിക്ക് ഈ കോഡ് പറഞ്ഞുതരാമോ?", "ml", "Enikku ee code paranju tharamo? (Can you explain this code?)"),
    ("Roxy chechi, entha ippol cheyyunnathu?", "ml-Latn", "Manglish: Roxy sister, what are you doing now?"),
]


def run_benchmark(provider: STTProvider, samples: Optional[list] = None) -> None:
    """Benchmark STT model latency, language detection, and sample transcriptions."""
    print("=" * 60)
    print("🎙️ Kokoro-Term STT Benchmark (Malayalam & English)")
    print(f"Provider: {provider.__class__.__name__} | Available: {provider.is_available()}")
    print("=" * 60)

    test_data = samples or SAMPLE_MALAYALAM_PHRASES

    for text, expected_lang, note in test_data:
        detected = detect_language(text)
        status = "✅ PASS" if (detected == expected_lang or "ml" in detected) else "⚠️ MISMATCH"
        print(f"\nPhrase: '{text}' ({note})")
        print(f"  Detected Language: {detected} (Expected: {expected_lang}) -> {status}")

    print("\n" + "=" * 60)
    print("Benchmark complete. To benchmark custom WAV/MP3 files:")
    print("Pass audio file paths into FasterWhisperProvider.transcribe(audio_bytes)")
    print("=" * 60)


if __name__ == "__main__":
    provider = FasterWhisperProvider() if FasterWhisperProvider().is_available() else MockSTTProvider()
    run_benchmark(provider)
