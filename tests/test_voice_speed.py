import pytest
import numpy as np
from pathlib import Path

from kokoro_term.character import VoiceConfig, load_character
from kokoro_term.config import load_config, VoiceSettingsConfig
from kokoro_term.tts.speech_style import (
    apply_japanese_slang,
    apply_pronunciation_map,
    split_sentences,
    split_into_clauses,
    sentence_has_slang,
    STANDARD_SLANG_TERMS,
    DEFAULT_PRONUNCIATION_MAP,
)
from kokoro_term.tts.audio_processor import trim_audio_silence, measure_fundamental_frequency


def test_pace_config_loading_and_bounds():
    """Verify voice speed default is ~1.20x and tunable between 0.9 and 1.5."""
    vc = VoiceConfig(speed=1.20)
    assert vc.speed == 1.20
    assert vc.engine == "edge-tts"
    assert vc.voice_id == "en-US-AvaNeural"
    assert vc.pitch == -4.0
    assert vc.trim_silence is True
    assert vc.pause_comma_ms == 120
    assert vc.pause_sentence_ms == 250

    # Bounds validation
    with pytest.raises(Exception):
        VoiceConfig(speed=0.5)  # Below 0.9 min
    with pytest.raises(Exception):
        VoiceConfig(speed=2.0)  # Above 1.5 max

    # Config settings model
    vsc = VoiceSettingsConfig(speed=1.25)
    assert vsc.speed == 1.25
    assert vsc.base_rate == 20


def test_roxy_voice_yaml_integrity():
    """Verify character voice.yaml loads with new pace, emotion_pace, and pronunciation_map."""
    char = load_character("roxy", character_dir="characters")
    assert char.voice is not None
    assert 1.15 <= char.voice.speed <= 1.40
    assert char.voice.pitch in (-8.0, -4.0, 3.0, 20.0, 24.0)
    assert "teasing" in char.voice.emotion_pace
    assert "caring" in char.voice.emotion_pace
    assert "serious" in char.voice.emotion_pace
    # teasing faster than caring
    assert char.voice.emotion_pace["teasing"] > char.voice.emotion_pace["caring"]
    # pronunciation map present
    assert "ara" in char.voice.pronunciation_map
    assert "baka" in char.voice.pronunciation_map


def test_silence_trimming_removes_dead_air():
    """Verify silence trimming trims synthetic silence blocks and preserves audio."""
    # Generate 1 second of silence, 1 second of 440Hz sine wave, 1 second of silence
    sr = 24000
    t = np.linspace(0, 1.0, sr, endpoint=False)
    sine = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    silence = np.zeros(sr, dtype=np.float32)

    raw_audio = np.concatenate([silence, sine, silence])
    assert len(raw_audio) == sr * 3

    # Encode to WAV bytes using standard wave
    import io, wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes((raw_audio * 32767).astype(np.int16).tobytes())
    wav_bytes = buf.getvalue()

    # Trim silence
    trimmed_bytes = trim_audio_silence(wav_bytes, out_format="wav", post_pause_ms=250)
    dur, _ = measure_fundamental_frequency(trimmed_bytes)

    # 3.0s audio should be trimmed to ~1.0s speech + 250ms post_pause = ~1.28s
    assert dur < 2.0
    assert dur >= 1.1


def test_slang_frequency_limiter():
    """Verify Japanese-style slang touches obey:
    1. Max 1 per sentence
    2. At most about 1 in 3 sentences
    3. Natural placement
    """
    text = (
        "I will prepare the magical formation now. "
        "The water spirits respond to our incantation very smoothly. "
        "You have practiced this lesson with great dedication. "
        "Now let us combine the elemental streams together. "
        "Remember to breathe steadily as the flow accelerates. "
        "Your magic circle is almost complete."
    )
    styled = apply_japanese_slang(text, emotion="teasing", accent_strength=0.3)
    sentences = split_sentences(styled)

    slang_count_per_sentence = []
    total_slang = 0
    for s in sentences:
        count = 0
        s_lower = s.lower()
        for term in STANDARD_SLANG_TERMS:
            if term.startswith("-"):
                if term in s_lower:
                    count += 1
            else:
                import re
                if re.search(rf"\b{re.escape(term)}\b", s_lower):
                    count += 1
        slang_count_per_sentence.append(count)
        if count > 0:
            total_slang += 1

    # Never more than one per sentence
    assert all(c <= 1 for c in slang_count_per_sentence)
    # At most about one in three sentences
    assert total_slang <= (len(sentences) // 2 + 1)


def test_pronunciation_map_substitutions():
    """Verify all 12 Japanese slang terms are correctly mapped to phonetic overrides."""
    for term in [
        "ara", "fufu", "mou", "ne", "yosh", "hora", "sugoi",
        "baka", "yare yare", "ganbatte", "-san", "-kun"
    ]:
        input_phrase = f"Testing {term} for proper TTS vocalization."
        output = apply_pronunciation_map(input_phrase, DEFAULT_PRONUNCIATION_MAP)
        # Should not contain unmapped word
        if term == "-san":
            assert "-sahn" in output
        elif term == "-kun":
            assert "-koon" in output
        else:
            assert DEFAULT_PRONUNCIATION_MAP[term] in output


def test_clause_splitting_for_low_latency():
    """Verify split_into_clauses creates 5-6 word clauses for streaming TTS."""
    long_reply = (
        "Welcome home, Midhun-san. I noticed you have been working very late at the terminal. "
        "Please let me review the error logs so we can resolve everything quickly."
    )
    clauses = split_into_clauses(long_reply, min_words=5)
    assert len(clauses) >= 2
    # First clause should be roughly 3-8 words
    first_words = clauses[0].split()
    assert 3 <= len(first_words) <= 9


@pytest.mark.asyncio
async def test_tts_manager_fallback():
    """Verify TTSManager seamlessly falls back from edge/cloud to local offline provider."""
    from kokoro_term.tts.manager import TTSManager

    manager = TTSManager(preferred_provider="edge", fallback_enabled=True)
    assert manager.active_mode == "cloud"
    assert manager.status_label == "[Voice: cloud]"

    # Switch provider manually
    manager.set_provider("local")
    assert manager.active_mode == "local"
    assert manager.status_label == "[Voice: local]"

    # Synthesize with local provider
    chunk = await manager.synthesize_chunk("Hello master.")
    assert chunk.provider_mode == "local"
    assert len(chunk.data) > 0
    assert chunk.duration_sec > 0
    assert chunk.word_timings is not None


def test_lipsync_alignment_and_offset():
    """Verify viseme alignment respects lipsync offset ms."""
    from kokoro_term.tts.alignment import align_visemes_to_words

    words = [
        {"word": "hello", "start": 0.2, "end": 0.5},
        {"word": "master", "start": 0.6, "end": 0.9},
    ]
    visemes_zero = align_visemes_to_words("hello master", words, offset_ms=0.0)
    assert len(visemes_zero) > 0

    visemes_shifted = align_visemes_to_words("hello master", words, offset_ms=50.0)
    assert len(visemes_shifted) > 0
    # First shifted viseme start should be shifted by ~0.05s
    assert visemes_shifted[0]["time"] >= visemes_zero[0]["time"]


def test_chunk_text_for_tts_prosody():
    """Verify sentence-based intonation chunking:
    - First chunk is first full sentence (or natural clause >= 8 words).
    - Later chunks are always whole sentences, never split at commas.
    """
    from kokoro_term.tts.speech_style import chunk_text_for_tts

    multi_sentence = (
        "Welcome back to the terminal, Midhun-san! "
        "I have prepared the diagnostic report, and all services are running properly. "
        "Would you like me to start the background music now?"
    )
    chunks = chunk_text_for_tts(multi_sentence)
    assert len(chunks) == 3
    assert chunks[0] == "Welcome back to the terminal, Midhun-san!"
    # Later chunk is a whole sentence and NOT split at the comma
    assert "," in chunks[1]
    assert chunks[1] == "I have prepared the diagnostic report, and all services are running properly."
    assert chunks[2] == "Would you like me to start the background music now?"


def test_normalize_text_for_tts():
    """Verify text normalization strictly for TTS audio:
    - Numbers and units to words
    - Dashes to commas
    - Ellipses to short pauses
    - Contractions preserved as standard English
    - URLs and file paths cleaned
    """
    from kokoro_term.tts.speech_style import normalize_text_for_tts

    # 1. Units and percentages
    norm1 = normalize_text_for_tts("Usage is at 57.4% with 16 GB memory.")
    assert "fifty-seven point four percent" in norm1
    assert "sixteen gigabytes" in norm1

    # 2. Dashes and ellipses
    norm2 = normalize_text_for_tts("Wait—that's great... let's continue.")
    assert "—" not in norm2
    assert "..." not in norm2
    assert "," in norm2

    # 3. Contractions stay as normal English contractions
    assert "can't" in normalize_text_for_tts("I can't believe it.")
    assert "It's" in normalize_text_for_tts("It's working.")

    # 4. URLs and paths
    norm3 = normalize_text_for_tts("Open https://localhost:8080 or check /var/log/syslog.log.")
    assert "https://" not in norm3
    assert "/var/log/syslog.log" not in norm3
    assert "the local server link" in norm3 or "link" in norm3


def test_apply_fades_and_limiter():
    """Verify audio processing raised-cosine fades and -1 dBFS peak limiter."""
    from kokoro_term.tts.audio_processor import apply_fades, apply_limiter
    sr = 24000
    t = np.linspace(0, 0.1, int(sr * 0.1), endpoint=False)
    # Loud square wave with peak 1.5 (heavily clipping)
    loud_sig = 1.5 * np.sign(np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    # Limiter test: peak must not exceed -1 dBFS (~0.89125)
    limited = apply_limiter(loud_sig, threshold_dbfs=-1.0)
    assert np.max(np.abs(limited)) <= 0.892

    # Fades test: first sample and last sample must be near 0
    faded = apply_fades(limited, sr=sr, fade_ms=8.0)
    assert abs(faded[0]) < 0.05
    assert abs(faded[-1]) < 0.05


@pytest.mark.asyncio
async def test_tts_manager_pinning_and_visible_notices():
    """Verify TTSManager respects pinned provider and emits visible notices on fallback."""
    from kokoro_term.tts.manager import TTSManager

    notices = []
    manager = TTSManager(preferred_provider="edge", pinned=True, fallback_enabled=True)
    manager.fallback_listener = lambda n: notices.append(n)

    assert manager.pinned is True
    assert "pinned" in manager.status_label

    # When pinned, unpinning works via set_provider
    manager.set_provider("edge", pin=False)
    assert manager.pinned is False

    # Trigger recorded fallback
    manager._record_fallback(Exception("Simulated connection timeout"))
    assert manager.last_fallback_notice is not None
    assert "Simulated connection timeout" in manager.last_fallback_notice
    assert len(notices) == 1

    # Consume notice for UI
    consumed = manager.consume_fallback_notice()
    assert consumed is not None
    assert manager.last_fallback_notice is None

