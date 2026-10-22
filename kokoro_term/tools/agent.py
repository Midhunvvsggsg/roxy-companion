from __future__ import annotations

import json
import re
import time
from typing import AsyncIterator, Optional

from kokoro_term.config import ToolsConfig
from kokoro_term.llm.base import LLMMessage, LLMProvider
from kokoro_term.relationship.models import RelationshipState
from kokoro_term.tools.audit import AuditLogger
from kokoro_term.tools.base import BaseTool, ToolResult
from kokoro_term.tools.permission import PermissionManager
from kokoro_term.tools.registry import ToolRegistry
from kokoro_term.tools.resistance import ResistanceManager


TOOL_CALL_REGEX = re.compile(r"<tool_call>\s*({.*?})\s*</tool_call>", re.DOTALL)


class AgentLoop:
    """Orchestrates multi-step planning, tool invocation, permission checking, and observation loops."""

    def __init__(
        self,
        config: ToolsConfig,
        registry: ToolRegistry,
        permission: PermissionManager,
        audit: AuditLogger,
        resistance: ResistanceManager,
    ):
        self.config = config
        self.registry = registry
        self.permission = permission
        self.audit = audit
        self.resistance = resistance

    def parse_tool_calls(self, text: str) -> list[tuple[str, dict]]:
        calls = []
        for match in TOOL_CALL_REGEX.finditer(text):
            raw_json = match.group(1).strip()
            try:
                data = json.loads(raw_json)
                name = data.get("name")
                args = data.get("arguments", {})
                if name:
                    calls.append((name, args))
            except Exception:
                pass
        return calls

    async def execute_tool(
        self,
        tool: BaseTool,
        arguments: dict,
        user_confirmed: bool = False,
    ) -> ToolResult:
        start_t = time.perf_counter()
        try:
            result = await tool.execute(**arguments)
            duration_ms = (time.perf_counter() - start_t) * 1000.0

            self.audit.log(
                tool_name=tool.name,
                arguments=arguments,
                tier=tool.tier,
                approved=True,
                user_confirmed=user_confirmed,
                duration_ms=duration_ms,
                success=result.success,
                output=result.output,
                error=result.error,
            )
            return result
        except Exception as e:
            duration_ms = (time.perf_counter() - start_t) * 1000.0
            err_msg = str(e)
            self.audit.log(
                tool_name=tool.name,
                arguments=arguments,
                tier=tool.tier,
                approved=True,
                user_confirmed=user_confirmed,
                duration_ms=duration_ms,
                success=False,
                output="",
                error=err_msg,
            )
            return ToolResult(success=False, output="", error=err_msg)
