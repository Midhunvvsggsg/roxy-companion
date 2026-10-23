from pathlib import Path
import pytest
from kokoro_term.character import load_character, Character


def test_load_roxy_character():
    char = load_character("roxy", character_dir="characters")
    assert char.id == "roxy"
    assert char.name == "Roxy Migurdia"
    assert "mature_and_protective" in char.personality_traits
    assert "quietly_possessive" in char.personality_traits
    assert "neutral" in char.emotions
    assert "blush" in char.emotions


def test_system_prompt_generation():
    char = load_character("roxy", character_dir="characters")
    prompt = char.build_system_prompt(user_name="Midhun", yandere_intensity=4)
    assert "Roxy Migurdia" in prompt
    assert "Water Saint-Class Magician" in prompt
    assert "[emotion:neutral]" in prompt
    assert "Midhun" in prompt
    assert "Devotion & Yandere Intensity: 4/10" in prompt

    # Test safe word relax mode (intensity 0)
    prompt_relax = char.build_system_prompt(user_name="Midhun", yandere_intensity=0)
    assert "Safe Word / Relax Mode Activated" in prompt_relax


def test_missing_character_raises_error():
    with pytest.raises(FileNotFoundError):
        load_character("non_existent_character_xyz", character_dir="characters")
