"""Unit and Integration Tests for Part 2: Tool Execution, Routing, and Doctor."""

import pytest
import asyncio
from kokoro_term.tools.agent import AgentLoop, should_include_tools
from kokoro_term.tools.base import ToolResult
from kokoro_term.tools.builtin.apps import OpenAppTool, OpenUrlTool
from kokoro_term.tools.doctor import run_doctor_checks
from kokoro_term.tools.gui_env import capture_gui_environment, spawn_gui_process, open_url_or_site
from kokoro_term.tools.registry import ToolRegistry
from kokoro_term.tools.permission import PermissionManager
from kokoro_term.tools.audit import AuditLogger
from kokoro_term.tools.resistance import ResistanceManager
from kokoro_term.config import ToolsConfig
from kokoro_term.llm.base import LLMMessage
from kokoro_term.llm.mock import MockProvider
from kokoro_term.relationship.models import RelationshipState


def test_should_include_tools_routing():
    """Verify that action queries reach the tool loop while pure greetings do not."""
    # Must reach the tool loop
    assert should_include_tools("open yt") is True
    assert should_include_tools("open youtube") is True
    assert should_include_tools("play some music") is True
    assert should_include_tools("play idol by yoasobi") is True
    assert should_include_tools("stop the music") is True
    assert should_include_tools("it is not opening") is True
    assert should_include_tools("search for quantum physics") is True
    assert should_include_tools("install mpv") is True
    assert should_include_tools("check git status") is True

    # Pure chitchat & greetings should skip tools for speed
    assert should_include_tools("hello") is False
    assert should_include_tools("hi") is False
    assert should_include_tools("good morning") is False


@pytest.mark.asyncio
async def test_open_app_failed_tool_produces_real_error_not_fake_success():
    """Verify that a failing tool produces a structured error and NOT a fake success."""
    tool = OpenAppTool()
    # Attempt to open a binary that does not exist on the system
    result = await tool.execute(app_name="__nonexistent_dummy_app_xyz_98765__")

    assert result.success is False
    assert result.ok is False
    assert result.exit_code != 0
    err_text = (result.output + " " + (result.error or "")).lower()
    assert "not found" in err_text or "does not exist" in err_text

    # Verify structured dictionary output
    d = result.to_dict()
    assert d["ok"] is False
    assert d["detail"] != ""
    assert d["exit_code"] is not None


@pytest.mark.asyncio
async def test_open_app_youtube_shortcut():
    """Verify that 'open yt' or 'open youtube' resolves to https://www.youtube.com."""
    tool = OpenAppTool()
    # In test environment, verify that opening 'youtube' invokes browser/xdg-open with youtube.com
    res = open_url_or_site("youtube", wait_sec=0.1)
    assert res["url"] == "https://www.youtube.com"


def test_doctor_diagnostic_suite():
    """Verify /doctor runs all required checks and returns pass/fail with fixes."""
    doc = run_doctor_checks()
    assert "passed" in doc
    assert "checks" in doc
    check_names = {c["name"] for c in doc["checks"]}
    assert "env_vars" in check_names
    assert "url_opening" in check_names
    assert "mpv" in check_names
    assert "yt_dlp" in check_names
    assert "notifications" in check_names
    assert "microphone" in check_names

    for c in doc["checks"]:
        assert "ok" in c
        assert "detail" in c
        if not c["ok"]:
            assert c["fix"] != "", f"Failed check {c['name']} must include a recommended fix"


@pytest.mark.asyncio
async def test_agent_loop_strips_tool_call_from_token_stream():
    """Verify that raw <tool_call> tags are never leaked in streamed tokens."""
    config = ToolsConfig()
    registry = ToolRegistry()
    permission = PermissionManager(config=config)
    audit = AuditLogger(log_path="data/test_audit.log")
    resistance = ResistanceManager()

    agent = AgentLoop(
        config=config,
        registry=registry,
        permission=permission,
        audit=audit,
        resistance=resistance,
    )

    mock_llm = MockProvider()
    messages = [LLMMessage(role="user", content="open yt")]
    rel = RelationshipState(character_id="roxy", user_id="midhun")

    tokens_received = []
    tool_events = []

    async for event in agent.run_agent_loop(llm=mock_llm, messages=messages, rel_state=rel):
        if event.get("type") == "token":
            tok = event["token"]
            assert "<tool_call>" not in tok, f"Leaked <tool_call> in token: {tok}"
            assert "</tool_call>" not in tok, f"Leaked </tool_call> in token: {tok}"
            tokens_received.append(tok)
        elif event.get("type") in ("tool_start", "confirm_required"):
            tool_events.append(event["tool"])

    # Verify tool was detected and routed
    assert "open_app" in tool_events
    # Verify stream had verbal lead-in without tool call tags
    full_stream = "".join(tokens_received)
    assert "<tool_call>" not in full_stream
