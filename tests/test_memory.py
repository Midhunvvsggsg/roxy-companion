import json
from pathlib import Path
import pytest
from kokoro_term.config import MemoryConfig
from kokoro_term.llm.base import LLMMessage, LLMProvider
from kokoro_term.memory.manager import MemoryManager


class MockConsolidationLLM(LLMProvider):
    async def stream_chat(self, messages):
        yield json.dumps({
            "summary": "User and Roxy discussed advanced water magic and terminal setup.",
            "facts": [
                {"category": "project", "key": "active_project", "value": "kokoro-term"},
                {"category": "preference", "key": "favorite_editor", "value": "neovim"},
            ]
        })


@pytest.fixture
def temp_memory(tmp_path):
    db_file = tmp_path / "test_memory.db"
    config = MemoryConfig(db_path=str(db_file), short_term_window=5, auto_consolidate_interval=3)
    return MemoryManager(config)


def test_add_and_retrieve_messages(temp_memory):
    temp_memory.add_message("roxy", "user1", "user", "Hello Roxy!")
    temp_memory.add_message("roxy", "user1", "assistant", "Greetings, student.")

    recent = temp_memory.get_recent_messages("roxy", "user1", limit=10)
    assert len(recent) == 2
    assert recent[0].role == "user"
    assert recent[0].content == "Hello Roxy!"
    assert recent[1].role == "assistant"
    assert recent[1].content == "Greetings, student."


def test_fact_upsert_and_contradiction_resolution(temp_memory):
    # Initial fact
    temp_memory.upsert_fact("roxy", "user1", "preference", "beverage", "green tea")
    facts = temp_memory.get_facts("roxy", "user1")
    assert len(facts) == 1
    assert facts[0].key == "beverage"
    assert facts[0].value == "green tea"

    # Contradiction / update: user changed preference
    temp_memory.upsert_fact("roxy", "user1", "preference", "beverage", "black coffee")
    updated_facts = temp_memory.get_facts("roxy", "user1")
    assert len(updated_facts) == 1
    assert updated_facts[0].value == "black coffee"


def test_forget_fact(temp_memory):
    temp_memory.upsert_fact("roxy", "user1", "identity", "name", "Midhun")
    temp_memory.upsert_fact("roxy", "user1", "habit", "wakes_up", "6am")

    assert len(temp_memory.get_facts("roxy", "user1")) == 2

    # Forget by keyword
    count = temp_memory.forget_fact("roxy", "user1", "wakes_up")
    assert count == 1
    active_facts = temp_memory.get_facts("roxy", "user1", active_only=True)
    assert len(active_facts) == 1
    assert active_facts[0].key == "name"


def test_fts5_memory_search(temp_memory):
    temp_memory.upsert_fact("roxy", "user1", "project", "companion", "Waifu-Terminal using Python")
    results = temp_memory.search_memory("roxy", "user1", "companion")
    assert len(results) >= 1
    assert "Waifu-Terminal" in results[0]


@pytest.mark.asyncio
async def test_consolidation(temp_memory):
    temp_memory.add_message("roxy", "user1", "user", "Let's work on water magic.")
    temp_memory.add_message("roxy", "user1", "assistant", "Understood. Open the terminal.")
    temp_memory.add_message("roxy", "user1", "user", "I prefer using neovim.")

    llm = MockConsolidationLLM()
    episode = await temp_memory.consolidate("roxy", "user1", llm)

    assert episode is not None
    assert "water magic" in episode.summary
    assert episode.message_count == 3

    # Check extracted facts
    facts = temp_memory.get_facts("roxy", "user1")
    fact_dict = {f.key: f.value for f in facts}
    assert fact_dict.get("active_project") == "kokoro-term"
    assert fact_dict.get("favorite_editor") == "neovim"


def test_context_injection_formatting(temp_memory):
    temp_memory.upsert_fact("roxy", "user1", "identity", "role", "Magician Apprentice")
    injection = temp_memory.build_context_injection("roxy", "user1")

    assert "Known Facts & Preferences about User:" in injection
    assert "[identity] role: Magician Apprentice" in injection


def test_export_and_wipe_memory(temp_memory, tmp_path):
    temp_memory.upsert_fact("roxy", "user1", "identity", "name", "Rudeus")
    temp_memory.add_message("roxy", "user1", "user", "Hello Master Roxy")

    export_file = tmp_path / "exported.md"
    temp_memory.export_memory("roxy", "user1", export_file)
    assert export_file.exists()

    content = export_file.read_text(encoding="utf-8")
    assert "Rudeus" in content
    assert "Hello Master Roxy" in content

    # Wipe
    temp_memory.wipe_memory("roxy", "user1")
    assert len(temp_memory.get_facts("roxy", "user1")) == 0
    assert len(temp_memory.get_recent_messages("roxy", "user1")) == 0


class TestSection5NameMemoryAndSeparation:
    def test_preferred_name_storage_and_override(self, temp_memory):
        """User preferred name is stored as long-term fact overriding defaults."""
        assert temp_memory.get_preferred_name("roxy", "user1") is None

        # Store preferred name
        fact = temp_memory.set_preferred_name("roxy", "user1", "Midhun-san")
        assert fact.key == "preferred_name"
        assert fact.value == "Midhun-san"
        assert fact.category == "identity"

        # Verify retrieval
        pref = temp_memory.get_preferred_name("roxy", "user1")
        assert pref == "Midhun-san"

        # Update preferred name (e.g. to 'Opah')
        temp_memory.set_preferred_name("roxy", "user1", "Opah")
        assert temp_memory.get_preferred_name("roxy", "user1") == "Opah"

    def test_preferred_name_injected_into_prompts(self, temp_memory):
        """Stored preferred name is injected into system prompt and memory context."""
        temp_memory.set_preferred_name("roxy", "user1", "Midhun-san")
        pref = temp_memory.get_preferred_name("roxy", "user1")

        # Context injection
        context = temp_memory.build_context_injection("roxy", "user1")
        assert "User Preferred Name & Identity" in context
        assert "Midhun-san" in context

        # Character prompt building
        from kokoro_term.character import load_character
        char = load_character("roxy")
        prompt = char.build_system_prompt(user_name=pref, preferred_name=pref)
        assert "Midhun-san" in prompt
        assert "Strict Name Consistency" in prompt

    @pytest.mark.asyncio
    async def test_fast_name_extraction_from_conversational_turn(self, temp_memory):
        """Statements like 'Call me X' or 'My name is X' are captured as preferred name."""
        llm = MockConsolidationLLM()
        facts = await temp_memory.extract_facts_from_turn(
            "roxy",
            "user1",
            "From now on, please call me Opah.",
            "Understood, Opah. I will address you accordingly.",
            llm,
        )
        assert len(facts) >= 1
        assert temp_memory.get_preferred_name("roxy", "user1") == "Opah"

    def test_tts_respelling_separation_from_display_and_memory(self, temp_memory):
        """Phonetic respellings apply strictly to TTS input, never modifying chat display or memory."""
        from kokoro_term.tts.speech_style import apply_pronunciation_map, normalize_text_for_tts

        raw_display_message = "Good morning, Midhun-san! Let's check the 100 MB update."
        temp_memory.add_message("roxy", "user1", "assistant", raw_display_message)

        # Retrieve stored message
        recent = temp_memory.get_recent_messages("roxy", "user1")
        assert recent[0].content == raw_display_message
        assert "Midhun-san" in recent[0].content  # Never corrupted in storage

        # TTS input processing only transforms the spoken stream
        tts_input = normalize_text_for_tts(raw_display_message)
        spoken_tts = apply_pronunciation_map(tts_input)
        assert "one hundred megabytes" in tts_input

        # Stored memory and display remain clean original text
        assert "one hundred megabytes" not in raw_display_message
        assert recent[0].content == raw_display_message

