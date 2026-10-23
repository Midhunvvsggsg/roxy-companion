"""Multi-step Agent Execution Loop with Planning, Tool Calling, and Observation."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, AsyncIterator, Callable, Optional

from kokoro_term.config import ToolsConfig
from kokoro_term.llm.base import LLMMessage, LLMProvider
from kokoro_term.relationship.models import RelationshipState
from kokoro_term.tools.audit import AuditLogger
from kokoro_term.tools.base import BaseTool, ToolResult
from kokoro_term.tools.injection_defense import wrap_untrusted_data
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
        self.max_steps = getattr(config, "max_agent_steps", 5)
        self.active_tasks: dict[str, asyncio.Event] = {}

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
        timeout_sec: float = 20.0,
    ) -> ToolResult:
        start_t = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                tool.execute(**arguments),
                timeout=timeout_sec,
            )
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
        except asyncio.TimeoutError:
            duration_ms = (time.perf_counter() - start_t) * 1000.0
            err_msg = f"Tool '{tool.name}' timed out after {timeout_sec}s."
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

    async def run_agent_loop(
        self,
        llm: LLMProvider,
        messages: list[LLMMessage],
        rel_state: RelationshipState,
        stop_event: Optional[asyncio.Event] = None,
        on_event: Optional[Callable[[dict[str, Any]], Any]] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run the full multi-step agent loop:
        plan -> tool call -> observe -> verify -> reply.
        Yields event dictionaries for streaming SSE and TUI updates.
        """
        conversation = list(messages)
        step = 0

        while step < self.max_steps:
            if stop_event and stop_event.is_set():
                yield {"type": "stop", "message": "Agent execution stopped by user."}
                return

            step += 1
            yield {"type": "step", "step": step, "max_steps": self.max_steps}

            # 1. Plan & LLM generation
            full_response = ""
            async for chunk in llm.stream_chat(conversation):
                if stop_event and stop_event.is_set():
                    yield {"type": "stop", "message": "Agent execution stopped by user."}
                    return
                full_response += chunk
                yield {"type": "token", "token": chunk}

            # 2. Check for tool calls
            tool_calls = self.parse_tool_calls(full_response)
            if not tool_calls:
                # No more tools called: this is the final verbal response!
                yield {"type": "done", "response": full_response}
                return

            # Append assistant response with tool calls to conversation
            conversation.append(LLMMessage(role="assistant", content=full_response))

            # 3. Execute tools
            for tool_name, args in tool_calls:
                if stop_event and stop_event.is_set():
                    yield {"type": "stop", "message": "Agent execution stopped by user."}
                    return

                tool = self.registry.get(tool_name)
                if not tool:
                    err_text = f"Tool '{tool_name}' not found in registry."
                    wrapped_err = wrap_untrusted_data(err_text, source=f"system:{tool_name}")
                    conversation.append(LLMMessage(role="user", content=f"[Observation from {tool_name}]:\n{wrapped_err}"))
                    yield {"type": "tool_error", "tool": tool_name, "error": err_text}
                    continue

                # Permission & Confirmation Check
                tier = self.permission.classify_tool_tier(tool, args)
                needs_confirm, reason = self.permission.requires_confirmation(tool, args)

                if needs_confirm:
                    # In-character resistance objection
                    objection = self.resistance.generate_objection(tool, args, rel_state)
                    action_id = f"act_{int(time.time()*1000)}"
                    self.resistance.register_pending(tool_name, args)

                    yield {
                        "type": "confirm_required",
                        "tool": tool_name,
                        "args": args,
                        "tier": tier,
                        "action_id": action_id,
                        "prompt": reason,
                        "objection": objection,
                    }
                    return  # Pauses turn until user confirms or denies

                # Safe / Moderate execution
                yield {
                    "type": "tool_start",
                    "tool": tool_name,
                    "args": args,
                    "tier": tier,
                }

                result = await self.execute_tool(tool, args)
                out_display = result.output if result.success else f"Error: {result.error}"

                yield {
                    "type": "tool_end",
                    "tool": tool_name,
                    "success": result.success,
                    "output": out_display,
                    "tier": tier,
                }

                # 4. Observe: Sanitize and wrap untrusted data, append to conversation
                raw_obs = result.format_for_llm()
                safe_obs = wrap_untrusted_data(raw_obs, source=tool_name)
                conversation.append(
                    LLMMessage(
                        role="user",
                        content=f"[System Observation from tool '{tool_name}']:\n{safe_obs}\n\nNow verify this result and reply warmly to Midhun.",
                    )
                )

        yield {"type": "done", "response": "Completed maximum planned steps."}
