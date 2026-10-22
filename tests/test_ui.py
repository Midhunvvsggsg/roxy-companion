import pytest
from textual.widgets import Input, Static
from textual.containers import VerticalScroll

from kokoro_term.character import load_character
from kokoro_term.config import AppConfig, LLMConfig, MemoryConfig, ToolsConfig
from kokoro_term.llm.mock import MockProvider
from kokoro_term.memory.manager import MemoryManager
from kokoro_term.tools.agent import AgentLoop
from kokoro_term.tools.audit import AuditLogger
from kokoro_term.tools.permission import PermissionManager
from kokoro_term.tools.registry import ToolRegistry
from kokoro_term.tools.resistance import ResistanceManager
from kokoro_term.ui.app import KokoroApp, ChatMessageWidget, AvatarPanel
from kokoro_term.wizard import scaffold_new_character


@pytest.mark.asyncio
async def test_app_mount_and_initial_state(tmp_path):
    db_file = tmp_path / "ui_test.db"
    config = AppConfig(
        llm=LLMConfig(provider="mock"),
        memory=MemoryConfig(db_path=str(db_file)),
    )
    character = load_character("roxy", character_dir="characters")
    provider = MockProvider(delay=0.0)
    memory = MemoryManager(config.memory)

    app = KokoroApp(config=config, character=character, llm_provider=provider, memory_manager=memory)

    async with app.run_test() as pilot:
        avatar_panel = app.query_one("#avatar-panel", AvatarPanel)
        assert avatar_panel.current_emotion == "neutral"
        assert avatar_panel.character.name == "Roxy Migurdia"
        assert avatar_panel.affection == 50.0

        chat_scroll = app.query_one("#chat-scroll", VerticalScroll)
        assert len(chat_scroll.children) >= 1


@pytest.mark.asyncio
async def test_app_chat_interaction_and_persistence(tmp_path):
    db_file = tmp_path / "ui_test2.db"
    config = AppConfig(
        llm=LLMConfig(provider="mock"),
        memory=MemoryConfig(db_path=str(db_file)),
    )
    character = load_character("roxy", character_dir="characters")
    provider = MockProvider(delay=0.0)
    memory = MemoryManager(config.memory)

    app = KokoroApp(config=config, character=character, llm_provider=provider, memory_manager=memory)

    async with app.run_test() as pilot:
        input_widget = app.query_one("#user-input", Input)
        input_widget.value = "You are so cute!"
        await pilot.press("enter")
        await pilot.pause(0.1)

        avatar_panel = app.query_one("#avatar-panel", AvatarPanel)
        assert avatar_panel.current_emotion == "blush"
        # Affection rose from praise
        assert avatar_panel.affection > 50.0

    # Verify message was stored in SQLite
    msgs = memory.get_recent_messages("roxy", "default_user")
    assert len(msgs) == 2
    assert msgs[0].content == "You are so cute!"
    assert "[emotion:blush]" in msgs[1].content


@pytest.mark.asyncio
async def test_app_memory_commands(tmp_path):
    db_file = tmp_path / "ui_test3.db"
    config = AppConfig(
        llm=LLMConfig(provider="mock"),
        memory=MemoryConfig(db_path=str(db_file)),
    )
    character = load_character("roxy", character_dir="characters")
    provider = MockProvider(delay=0.0)
    memory = MemoryManager(config.memory)
    memory.upsert_fact("roxy", "default_user", "identity", "name", "Midhun")

    app = KokoroApp(config=config, character=character, llm_provider=provider, memory_manager=memory)

    async with app.run_test() as pilot:
        input_widget = app.query_one("#user-input", Input)

        # /memory show
        input_widget.value = "/memory show"
        await pilot.press("enter")
        await pilot.pause(0.05)

        # /memory forget
        input_widget.value = "/memory forget name"
        await pilot.press("enter")
        await pilot.pause(0.05)

        # /memory export
        export_target = str(tmp_path / "tui_exported.md")
        input_widget.value = f"/memory export {export_target}"
        await pilot.press("enter")
        await pilot.pause(0.05)

        # /memory wipe
        input_widget.value = "/memory wipe"
        await pilot.press("enter")
        await pilot.pause(0.05)

    assert len(memory.get_facts("roxy", "default_user")) == 0


@pytest.mark.asyncio
async def test_app_status_commands(tmp_path):
    db_file = tmp_path / "ui_test4.db"
    config = AppConfig(
        llm=LLMConfig(provider="mock"),
        memory=MemoryConfig(db_path=str(db_file)),
    )
    character = load_character("roxy", character_dir="characters")
    provider = MockProvider(delay=0.0)
    memory = MemoryManager(config.memory)

    app = KokoroApp(config=config, character=character, llm_provider=provider, memory_manager=memory)

    async with app.run_test() as pilot:
        input_widget = app.query_one("#user-input", Input)

        # /status
        input_widget.value = "/status"
        await pilot.press("enter")
        await pilot.pause(0.05)

        # /status set affection 85.0
        input_widget.value = "/status set affection 85.0"
        await pilot.press("enter")
        await pilot.pause(0.05)

        avatar_panel = app.query_one("#avatar-panel", AvatarPanel)
        assert avatar_panel.affection == 85.0

        # /status reset
        input_widget.value = "/status reset"
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert avatar_panel.affection == 50.0


@pytest.mark.asyncio
async def test_app_tools_commands(tmp_path):
    db_file = tmp_path / "ui_test5.db"
    audit_file = tmp_path / "test_audit.log"
    config = AppConfig(
        llm=LLMConfig(provider="mock"),
        memory=MemoryConfig(db_path=str(db_file)),
        tools=ToolsConfig(audit_log_path=str(audit_file)),
    )
    character = load_character("roxy", character_dir="characters")
    provider = MockProvider(delay=0.0)
    memory = MemoryManager(config.memory)

    reg = ToolRegistry()
    perm = PermissionManager(config.tools)
    audit = AuditLogger(config.tools.audit_log_path)
    res = ResistanceManager()
    agent = AgentLoop(config.tools, reg, perm, audit, res)

    app = KokoroApp(
        config=config,
        character=character,
        llm_provider=provider,
        memory_manager=memory,
        tool_registry=reg,
        agent_loop=agent,
    )

    async with app.run_test() as pilot:
        input_widget = app.query_one("#user-input", Input)

        # /tools
        input_widget.value = "/tools"
        await pilot.press("enter")
        await pilot.pause(0.05)

        # /audit
        input_widget.value = "/audit"
        await pilot.press("enter")
        await pilot.pause(0.05)

        chat_scroll = app.query_one("#chat-scroll", VerticalScroll)
        assert len(chat_scroll.children) >= 3


@pytest.mark.asyncio
async def test_app_character_hot_swap_and_perf(tmp_path):
    char_dir = tmp_path / "characters"
    # Copy roxy to test char_dir
    roxy_dir = scaffold_new_character("roxy", "Roxy Migurdia", title="Water Saint", characters_dir=char_dir)
    scaffold_new_character("sylphy", "Sylphiette", title="Silent Magician", characters_dir=char_dir)

    db_file = tmp_path / "ui_test6.db"
    config = AppConfig(
        active_character="roxy",
        character_dir=str(char_dir),
        llm=LLMConfig(provider="mock"),
        memory=MemoryConfig(db_path=str(db_file)),
    )
    character = load_character("roxy", character_dir=char_dir)
    provider = MockProvider(delay=0.0)
    memory = MemoryManager(config.memory)

    app = KokoroApp(
        config=config,
        character=character,
        llm_provider=provider,
        memory_manager=memory,
    )

    async with app.run_test() as pilot:
        input_widget = app.query_one("#user-input", Input)

        # /character list
        input_widget.value = "/character list"
        await pilot.press("enter")
        await pilot.pause(0.05)

        # /perf
        input_widget.value = "/perf"
        await pilot.press("enter")
        await pilot.pause(0.05)

        # /character use sylphy
        input_widget.value = "/character use sylphy"
        await pilot.press("enter")
        await pilot.pause(0.05)

        assert app.character.id == "sylphy"
        assert app.character.name == "Sylphiette"
