"""Tests for automatic execution of small desktop tasks, music routing, and tolerant tool parsing."""

import pytest
import asyncio
from unittest.mock import patch, MagicMock

from kokoro_term.config import ToolsConfig
from kokoro_term.tools.agent import AgentLoop, should_include_tools
from kokoro_term.tools.base import ToolResult
from kokoro_term.tools.builtin.apps import OpenAppTool, OpenUrlTool
from kokoro_term.tools.builtin.media import YouTubePlayTool
from kokoro_term.tools.music import MusicPlayTool, MusicControlTool, MUSIC_MANAGER
from kokoro_term.tools.gui_env import open_url_or_site
from kokoro_term.tools.registry import ToolRegistry
from kokoro_term.tools.permission import PermissionManager
from kokoro_term.tools.audit import AuditLogger
from kokoro_term.tools.resistance import ResistanceManager
from kokoro_term.llm.base import LLMMessage, LLMProvider
from kokoro_term.relationship.models import RelationshipState


def test_permission_small_tasks_auto_approved():
    """Verify that small tasks (open_app, open_url, music, media, system_info) never require confirmation."""
    cfg = ToolsConfig(dangerous_actions="ask", auto_approve_moderate=False)
    pm = PermissionManager(cfg)
    reg = ToolRegistry()

    small_task_tools = [
        ("open_app", {"app_name": "youtube"}),
        ("open_app", {"app_name": "brave"}),
        ("open_url", {"url": "https://news.google.com"}),
        ("youtube_play", {"query": "cat video"}),
        ("music_play", {"query": "lofi hip hop"}),
        ("music_control", {"action": "pause"}),
        ("music_search", {"query": "starboy"}),
        ("media_control", {"action": "play-pause"}),
        ("volume_control", {"action": "set", "level": 80}),
        ("brightness_control", {"action": "set", "level": 70}),
        ("now_playing", {}),
        ("system_info", {}),
        ("check_app_running", {"app_name": "brave"}),
    ]

    for tool_name, args in small_task_tools:
        tool = reg.get(tool_name)
        assert tool is not None, f"Tool {tool_name} must exist in registry"
        needs_confirm, reason = pm.requires_confirmation(tool, args)
        assert not needs_confirm, f"Small task '{tool_name}' with {args} must not require confirmation! Reason given: {reason}"
        assert pm.classify_tool_tier(tool, args) == "safe", f"Tool '{tool_name}' should classify as safe tier"


def test_parse_tool_calls_tolerant_formats():
    """Verify parse_tool_calls succeeds with diverse JSON structures and function calls."""
    cfg = ToolsConfig()
    reg = ToolRegistry()
    pm = PermissionManager(cfg)
    audit = AuditLogger("data/test_audit.log")
    rm = ResistanceManager()
    agent = AgentLoop(cfg, reg, pm, audit, rm)

    # 1. Standard format
    out1 = '<tool_call>{"name": "open_app", "arguments": {"app_name": "youtube"}}</tool_call>'
    calls1 = agent.parse_tool_calls(out1)
    assert calls1 == [("open_app", {"app_name": "youtube"})]

    # 2. "args" key instead of "arguments"
    out2 = '<tool_call>\n{"name": "open_app", "args": {"app_name": "youtube"}}\n</tool_call>'
    calls2 = agent.parse_tool_calls(out2)
    assert calls2 == [("open_app", {"app_name": "youtube"})]

    # 3. Top-level flat parameters
    out3 = '<tool_call>\n{"name": "music_play", "query": "lofi hip hop beats"}\n</tool_call>'
    calls3 = agent.parse_tool_calls(out3)
    assert calls3 == [("music_play", {"query": "lofi hip hop beats"})]

    # 4. XML tag attribute
    out4 = '<tool_call name="open_app">{"app_name": "youtube"}</tool_call>'
    calls4 = agent.parse_tool_calls(out4)
    assert calls4 == [("open_app", {"app_name": "youtube"})]

    # 5. Python-style function call
    out5 = '<tool_call>open_app(app_name="youtube")</tool_call>'
    calls5 = agent.parse_tool_calls(out5)
    assert calls5 == [("open_app", {"app_name": "youtube"})]

    # 6. Python-style positional call
    out6 = '<tool_call>music_play("starboy")</tool_call>'
    calls6 = agent.parse_tool_calls(out6)
    assert calls6 == [("music_play", {"query": "starboy"})]

    # 7. Markdown code fence fallback
    out7 = '```json\n{"name": "open_app", "arguments": {"app_name": "brave"}}\n```'
    calls7 = agent.parse_tool_calls(out7)
    assert calls7 == [("open_app", {"app_name": "brave"})]

    # 8. Unclosed <tool_call> tag
    out8 = '<tool_call name="open_app">{"app_name": "youtube"}'
    calls8 = agent.parse_tool_calls(out8)
    assert calls8 == [("open_app", {"app_name": "youtube"})]

    # 9. Raw embedded JSON in text
    out9 = 'Opening YouTube right away! {"name": "open_app", "arguments": {"app_name": "youtube"}}'
    calls9 = agent.parse_tool_calls(out9)
    assert calls9 == [("open_app", {"app_name": "youtube"})]

    # 10. Standalone Python function call in text
    out10 = 'Here you go! open_app(app_name="youtube")'
    calls10 = agent.parse_tool_calls(out10)
    assert calls10 == [("open_app", {"app_name": "youtube"})]

    # 11. OpenAI tool_calls wrapper with stringified arguments
    out11 = '{"tool_calls": [{"function": {"name": "open_url", "arguments": "{\\"url\\": \\"https://news.google.com\\"}"}}]}'
    calls11 = agent.parse_tool_calls(out11)
    assert calls11 == [("open_url", {"url": "https://news.google.com"})]


def test_open_url_or_site_routing():
    """Verify URL and shortcut normalization."""
    # YouTube shortcuts & typos
    assert open_url_or_site("youtube", wait_sec=0.01)["url"] == "https://www.youtube.com"
    assert open_url_or_site("yoututbe", wait_sec=0.01)["url"] == "https://www.youtube.com"
    assert open_url_or_site("yt", wait_sec=0.01)["url"] == "https://www.youtube.com"
    assert open_url_or_site("open youtube", wait_sec=0.01)["url"] == "https://www.youtube.com"
    assert open_url_or_site("open yoututbe", wait_sec=0.01)["url"] == "https://www.youtube.com"

    # News shortcuts
    assert open_url_or_site("news", wait_sec=0.01)["url"] == "https://news.google.com"
    assert open_url_or_site("latest news", wait_sec=0.01)["url"] == "https://news.google.com"
    assert open_url_or_site("check latest news", wait_sec=0.01)["url"] == "https://news.google.com"

    # Web search without opening YouTube
    search_res = open_url_or_site("quantum computing headlines", wait_sec=0.01)
    assert "google.com/search" in search_res["url"]
    assert "youtube.com" not in search_res["url"]


@pytest.mark.asyncio
async def test_music_routing_without_browser_tab():
    """Verify that user music requests route to headless music_play and never open browser tabs."""
    tool = MusicPlayTool()
    assert tool.tier == "safe"
    assert "mpv" in tool.description
    assert "NEVER opens a browser tab" in tool.description

    # Ensure OpenAppTool with 'music' redirects gracefully to headless player
    app_tool = OpenAppTool()
    with patch.object(MUSIC_MANAGER, "play") as mock_play:
        mock_play.return_value = {
            "ok": True,
            "track": {"title": "Lofi Chill", "channel": "Artist", "duration": 180, "url": "https://yt.com"},
            "mode": "replace",
            "detail": "Playing Lofi Chill by Artist.",
        }
        res = await app_tool.execute(app_name="music", args="lofi hip hop")
        assert res.success is True
        mock_play.assert_called_once_with("lofi hip hop")

    # Ensure OpenAppTool with 'open brave' normalizes and doesn't fail
    with patch("kokoro_term.tools.builtin.apps.spawn_gui_process") as mock_spawn:
        mock_spawn.return_value = {"ok": True, "pid": 4321, "exit_code": None, "stderr": "", "detail": "Success"}
        res2 = await app_tool.execute(app_name="open brave")
        assert res2.success is True

    # Ensure YouTubePlayTool intercepts music requests to play headlessly without opening browser tabs
    yt_tool = YouTubePlayTool()
    assert yt_tool.tier == "safe"
    with patch.object(MUSIC_MANAGER, "play") as mock_music_play:
        mock_music_play.return_value = {
            "ok": True,
            "track": {"title": "Starboy", "channel": "The Weeknd", "duration": 230, "url": "https://yt.com"},
            "mode": "replace",
            "detail": "Playing Starboy by The Weeknd.",
        }
        res3 = await yt_tool.execute(query="play starboy song")
        assert res3.success is True
        assert "headlessly in background without opening browser tabs" in res3.output
        mock_music_play.assert_called_once_with("starboy song")


@pytest.mark.asyncio
async def test_agent_loop_executes_small_task_without_confirmation_modal():
    """Verify that run_agent_loop automatically executes small tasks without emitting confirm_required."""
    cfg = ToolsConfig()
    reg = ToolRegistry()
    pm = PermissionManager(cfg)
    audit = AuditLogger("data/test_audit.log")
    rm = ResistanceManager()
    agent = AgentLoop(cfg, reg, pm, audit, rm)

    class CustomTestLLM(LLMProvider):
        def __init__(self):
            self.step = 0

        async def stream_chat(self, messages, tools=None):
            self.step += 1
            if self.step == 1:
                yield "Opening YouTube right now! "
                yield '<tool_call>{"name": "open_app", "args": {"app_name": "youtube"}}</tool_call>'
            else:
                yield "YouTube is now open for you!"

    llm = CustomTestLLM()
    messages = [LLMMessage(role="user", content="open youtube")]
    rel = RelationshipState(character_id="roxy", user_id="Opppah")

    events = []
    with patch("kokoro_term.tools.gui_env.spawn_gui_process") as mock_spawn:
        mock_spawn.return_value = {"ok": True, "pid": 1234, "exit_code": 0, "stderr": "", "detail": "Success"}
        async for evt in agent.run_agent_loop(llm=llm, messages=messages, rel_state=rel):
            events.append(evt)

    event_types = [e["type"] for e in events]
    # confirm_required MUST NOT be in event types
    assert "confirm_required" not in event_types
    # tool_start and tool_end MUST be in event types
    assert "tool_start" in event_types
    assert "tool_end" in event_types
    assert "done" in event_types
