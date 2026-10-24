"""Tests for Part 4: Speech Recognition Vocabulary, Fuzzy Matching, Name Preference, and Forehead Masking."""

import re
import pytest
from kokoro_term.character import load_character
from kokoro_term.memory.manager import MemoryManager
from kokoro_term.config import MemoryConfig
from kokoro_term.stt.whisper_provider import (
    fuzzy_correct_roxy_name,
    CUSTOM_VOCABULARY_PROMPT,
    FasterWhisperProvider,
)
from kokoro_term.tts.speech_style import apply_pronunciation_map


class TestSpeechRecognitionEnhancements:
    def test_fuzzy_correct_roxy_name_variants(self):
        """Verify misheard variants of Roxy ('Oxy', 'Rock see', 'Roxie', etc.) are corrected."""
        cases = [
            ("Hey Oxy, play some music", "Hey Roxy, play some music"),
            ("Rock see, what is the weather?", "Roxy, what is the weather?"),
            ("Can you hear me roxie?", "Can you hear me Roxy?"),
            ("yo rocky play a song", "yo Roxy play a song"),
            ("oxey, stop", "Roxy, stop"),
            ("rock-see what time is it", "Roxy what time is it"),
            ("Roxi, open terminal", "Roxy, open terminal"),
            ("rock sea, pause", "Roxy, pause"),
        ]
        for input_text, expected in cases:
            assert fuzzy_correct_roxy_name(input_text) == expected

    def test_custom_vocabulary_contains_critical_tokens(self):
        """Custom vocabulary / initial prompt contains names, apps, and control commands."""
        for token in ["Roxy", "Midhun-san", "Opppah", "YouTube", "play", "music", "open", "stop"]:
            assert token in CUSTOM_VOCABULARY_PROMPT


class TestNamePreferenceConsistency:
    def test_name_preference_stored_and_used_consistently(self, tmp_path):
        """User's chosen spelling overrides defaults and is consistently applied without alternation."""
        char = load_character("roxy", character_dir="characters")

        # Test with 'Opppah'
        prompt_opppah = char.build_system_prompt(
            user_name="Midhun",
            yandere_intensity=4,
            preferred_name="Opppah",
        )
        assert "Opppah" in prompt_opppah
        assert "Lean on me, Opppah..." in prompt_opppah
        assert "Welcome back, Opppah." in prompt_opppah
        assert "Strict Name Consistency: You MUST address the user EXCLUSIVELY and CONSISTENTLY as 'Opppah'" in prompt_opppah

        # Ensure it does not switch or fall back to Midhun-san in the directive examples
        assert "Lean on me, Midhun-san" not in prompt_opppah
        assert "Welcome back, Midhun-san" not in prompt_opppah

        # Test with 'Midhun-san'
        prompt_midhun = char.build_system_prompt(
            user_name="Midhun",
            yandere_intensity=4,
            preferred_name="Midhun-san",
        )
        assert "Lean on me, Midhun-san..." in prompt_midhun
        assert "Strict Name Consistency: You MUST address the user EXCLUSIVELY and CONSISTENTLY as 'Midhun-san'" in prompt_midhun

    def test_pronunciation_map_applies_only_to_tts_input(self):
        """Pronunciation respellings apply only to TTS phonetics, keeping displayed text unaltered."""
        display_text = "Welcome back, Opppah! Would you like me to play music?"
        pronunciation_map = {
            "Opppah": "Oppa",
            "opppah": "oppa",
        }
        spoken_text = apply_pronunciation_map(display_text, pronunciation_map)

        # TTS input is phonetically tuned
        assert "Oppa" in spoken_text
        assert "Opppah" not in spoken_text

        # Display text remains strictly untouched
        assert "Opppah" in display_text
