from pathlib import Path
import pytest
from kokoro_term.character import load_character, Character


def test_load_roxy_character():
    char = load_character("roxy", character_dir="characters")
    assert char.id == "roxy"
    assert char.name == "Roxy Migurdia"
    assert "serious_and_diligent" in char.personality_traits
    assert "shy_and_tsundere" in char.personality_traits
    assert "neutral" in char.emotions
    assert "blush" in char.emotions


def test_system_prompt_generation():
    char = load_character("roxy", character_dir="characters")
    prompt = char.build_system_prompt(user_name="Rudeus")
    assert "Roxy Migurdia" in prompt
    assert "Water Saint-Class Magician" in prompt
    assert "[emotion:neutral]" in prompt
    assert "Rudeus" in prompt


def test_missing_character_raises_error():
    with pytest.raises(FileNotFoundError):
        load_character("non_existent_character_xyz", character_dir="characters")
