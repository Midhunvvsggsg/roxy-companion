from pathlib import Path
import pytest
from kokoro_term.character import load_character
from kokoro_term.config import AppConfig
from kokoro_term.llm.mock import MockProvider
from kokoro_term.perf import format_performance_report, get_process_memory_mb
from kokoro_term.wizard import (
    draft_character_card,
    list_available_characters,
    scaffold_new_character,
)


def test_list_available_characters():
    chars = list_available_characters("characters")
    assert any(c["id"] == "roxy" for c in chars)


def test_scaffold_new_character(tmp_path):
    char_dir = tmp_path / "characters"
    created = scaffold_new_character(
        char_id="sylphiette",
        name="Sylphiette",
        title="Silent Magician",
        characters_dir=char_dir,
    )
    assert created.exists()
    assert (created / "character.yaml").exists()
    assert (created / "voice.yaml").exists()
    assert (created / "avatar" / "manifest.yaml").exists()

    char = load_character("sylphiette", character_dir=char_dir)
    assert char.name == "Sylphiette"
    assert char.title == "Silent Magician"


@pytest.mark.asyncio
async def test_draft_character_card(tmp_path):
    char_dir = tmp_path / "characters"

    class MockDesignerLLM(MockProvider):
        async def chat(self, messages):
            return (
                "name: 'Eris Greyrat'\n"
                "display_name: 'Eris'\n"
                "title: 'Sword King'\n"
                "bio: 'A fierce and energetic red-haired noble swordswoman.'\n"
                "personality_traits:\n"
                "  - energetic\n"
                "  - proud\n"
            )

    llm = MockDesignerLLM()
    cid, path = await draft_character_card("A tsundere red-haired swordswoman", llm, characters_dir=char_dir)
    assert cid == "eris_greyrat"
    assert path.exists()
    char = load_character(cid, character_dir=char_dir)
    assert char.name == "Eris Greyrat"


def test_performance_report():
    mem = get_process_memory_mb()
    assert isinstance(mem, float)
    assert mem >= 0.0

    conf = AppConfig()
    char = load_character("roxy", character_dir="characters")
    report = format_performance_report(conf, char)
    assert "Process Memory" in report
    assert "Roxy Migurdia" in report
