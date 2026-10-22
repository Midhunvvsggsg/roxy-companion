import asyncio
from pathlib import Path
import pytest

from kokoro_term.config import ToolsConfig
from kokoro_term.relationship.models import RelationshipState
from kokoro_term.tools.agent import AgentLoop
from kokoro_term.tools.audit import AuditLogger
from kokoro_term.tools.builtin.file_ops import (
    ReadFileTool,
    SearchFilesTool,
    TrashFileTool,
    WriteFileTool,
)
from kokoro_term.tools.builtin.shell import ShellCommandTool
from kokoro_term.tools.builtin.system_info import SystemInfoTool
from kokoro_term.tools.permission import PermissionManager
from kokoro_term.tools.registry import ToolRegistry
from kokoro_term.tools.resistance import ResistanceManager


@pytest.mark.asyncio
async def test_system_info_tool():
    tool = SystemInfoTool()
    res = await tool.execute()
    assert res.success is True
    assert "OS:" in res.output
    assert "CPUs:" in res.output


@pytest.mark.asyncio
async def test_file_ops_tools(tmp_path):
    target_file = tmp_path / "test.txt"
    writer = WriteFileTool()
    reader = ReadFileTool()

    # Write
    w_res = await writer.execute(path=str(target_file), content="Hello Roxy!\nLine 2")
    assert w_res.success is True
    assert target_file.exists()

    # Overwrite and verify diff
    w_res2 = await writer.execute(path=str(target_file), content="Hello Roxy Migurdia!\nLine 2")
    assert w_res2.diff is not None
    assert "-Hello Roxy!" in w_res2.diff
    assert "+Hello Roxy Migurdia!" in w_res2.diff

    # Read
    r_res = await reader.execute(path=str(target_file), start_line=1, max_lines=1)
    assert r_res.success is True
    assert "Hello Roxy Migurdia!" in r_res.output

    # Search
    searcher = SearchFilesTool()
    s_res = await searcher.execute(directory=str(tmp_path), pattern="*.txt")
    assert s_res.success is True
    assert "test.txt" in s_res.output

    # Trash
    trasher = TrashFileTool()
    t_res = await trasher.execute(path=str(target_file))
    assert t_res.success is True
    assert not target_file.exists()


@pytest.mark.asyncio
async def test_shell_command_tool():
    tool = ShellCommandTool()
    res = await tool.execute(command="echo 'Magic Water Arrow'")
    assert res.success is True
    assert "Magic Water Arrow" in res.output


def test_permission_manager_tiers():
    config = ToolsConfig()
    pm = PermissionManager(config)

    sys_tool = SystemInfoTool()
    needs_confirm, _ = pm.requires_confirmation(sys_tool, {})
    assert needs_confirm is False

    write_tool = WriteFileTool()
    needs_confirm, _ = pm.requires_confirmation(write_tool, {"path": "a.txt", "content": "x"})
    assert needs_confirm is True

    # Pre-approve in session
    pm.approve_for_session("write_file", {"path": "a.txt", "content": "x"})
    needs_confirm2, _ = pm.requires_confirmation(write_tool, {"path": "a.txt", "content": "x"})
    assert needs_confirm2 is False

    # Dangerous command dynamic escalation
    shell_tool = ShellCommandTool()
    assert pm.classify_command_tier("ls -la") == "moderate"
    assert pm.classify_command_tier("rm -rf /") == "dangerous"


def test_sandbox_enforcement(tmp_path):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    config = ToolsConfig(sandbox_dir=str(sandbox))
    pm = PermissionManager(config)

    safe_path = sandbox / "allowed.txt"
    unsafe_path = tmp_path / "outside.txt"

    assert pm.check_sandbox(safe_path) is True
    assert pm.check_sandbox(unsafe_path) is False

    write_tool = WriteFileTool()
    needs_confirm, reason = pm.requires_confirmation(write_tool, {"path": str(unsafe_path), "content": "bad"})
    assert needs_confirm is True
    assert "Sandbox Violation" in reason


def test_audit_logger(tmp_path):
    log_file = tmp_path / "test_audit.log"
    logger = AuditLogger(log_file)

    logger.log(
        tool_name="read_file",
        arguments={"path": "foo.txt"},
        tier="safe",
        approved=True,
        user_confirmed=False,
        duration_ms=12.5,
        success=True,
        output="sample output",
    )

    entries = logger.get_recent(limit=5)
    assert len(entries) == 1
    assert entries[0].tool_name == "read_file"
    assert entries[0].success is True


def test_resistance_manager():
    rm = ResistanceManager()
    rel = RelationshipState(character_id="roxy", user_id="user1", affection=80.0, tsundere_level=75.0)

    tool = TrashFileTool()
    objection = rm.generate_objection(tool, {"path": "important_project/"}, rel)
    assert "[emotion:blush]" in objection
    assert "reckless" in objection or "ruin" in objection
    assert "confirm" in objection

    assert rm.is_user_confirming("yes, please do it") is True
    assert rm.is_user_confirming("no, stop") is False

    rm.register_pending("trash_file", {"path": "foo"})
    assert rm.has_pending() is True
    tool_name, args = rm.consume_pending()
    assert tool_name == "trash_file"
    assert rm.has_pending() is False


def test_agent_tool_call_parsing():
    text = (
        "Let me look up the system information for you.\n"
        "<tool_call>\n"
        '{"name": "system_info", "arguments": {}}\n'
        "</tool_call>\n"
        "And now reading a file:\n"
        '<tool_call>{"name": "read_file", "arguments": {"path": "main.py"}}</tool_call>'
    )
    reg = ToolRegistry()
    loop = AgentLoop(ToolsConfig(), reg, PermissionManager(ToolsConfig()), AuditLogger(), ResistanceManager())
    calls = loop.parse_tool_calls(text)

    assert len(calls) == 2
    assert calls[0] == ("system_info", {})
    assert calls[1] == ("read_file", {"path": "main.py"})
