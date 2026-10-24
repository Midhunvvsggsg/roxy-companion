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

ACTION_WORDS = {
    "open", "play", "search", "install", "set", "stop", "turn", "show", "find",
    "launch", "run", "start", "kill", "close", "mute", "unmute", "volume",
    "brightness", "git", "read", "write", "delete", "remove", "check", "screen",
    "look", "see", "watch", "exec", "help", "pause", "resume", "louder", "quieter"
}

APP_SITE_NAMES = {
    "yt", "youtube", "browser", "brave", "firefox", "chrome", "chromium",
    "terminal", "foot", "code", "vscode", "discord", "spotify", "mpv", "vlc",
    "git", "web", "google"
}


def should_include_tools(message: str) -> bool:
    """Return True if message has action words, app/site names, or is not pure greeting."""
    if not message or not message.strip():
        return False
    low = message.strip().lower()
    cleaned = re.sub(r"[^\w\s]", " ", low)
    words = set(cleaned.split())

    # If any action word or app/site name is mentioned, tool schemas MUST be attached
    if words.intersection(ACTION_WORDS) or words.intersection(APP_SITE_NAMES):
        return True

    # Check for pure greetings and chitchat
    pure_greetings = {"hi", "hello", "hey", "good morning", "good evening", "good afternoon", "good night", "howdy", "sup", "yo"}
    if low in pure_greetings or (len(words) <= 2 and words.issubset(pure_greetings)):
        return False

    return True


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
        matches = re.finditer(r"<tool_call>(.*?)</tool_call>", text, re.DOTALL)
        for m in matches:
            block = m.group(1).strip()
            # Strip markdown code fences if model enclosed JSON
            block = re.sub(r"^```(?:json)?\s*", "", block, flags=re.IGNORECASE)
            block = re.sub(r"\s*```$", "", block)

            # 1. Direct JSON parse
            try:
                data = json.loads(block)
                name = data.get("name")
                args = data.get("arguments", {})
                if name:
                    calls.append((name, args))
                    continue
            except Exception:
                pass

            # 2. Balanced brace extraction fallback
            start_idx = block.find("{")
            if start_idx != -1:
                depth = 0
                for i in range(start_idx, len(block)):
                    if block[i] == "{":
                        depth += 1
                    elif block[i] == "}":
                        depth -= 1
                        if depth == 0:
                            try:
                                candidate = block[start_idx : i + 1]
                                data = json.loads(candidate)
                                name = data.get("name")
                                args = data.get("arguments", {})
                                if name:
                                    calls.append((name, args))
                            except Exception:
                                pass
                            break
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

        # Determine if tool schemas should be passed to provider
        last_user_msg = next((m.content for m in reversed(conversation) if m.role == "user"), "")
        include_tools = should_include_tools(last_user_msg)
        tools_schema = self.registry.to_gemini_tools() if include_tools else None

        while step < self.max_steps:
            if stop_event and stop_event.is_set():
                yield {"type": "stop", "message": "Agent execution stopped by user."}
                return

            step += 1
            yield {"type": "step", "step": step, "max_steps": self.max_steps}

            # 1. Plan & LLM generation with streaming token filtering (never show <tool_call> to client)
            full_response = ""
            stream_buffer = ""
            inside_tool_tag = False

            try:
                if tools_schema is not None:
                    stream_gen = llm.stream_chat(conversation, tools=tools_schema)
                else:
                    stream_gen = llm.stream_chat(conversation)
            except TypeError:
                stream_gen = llm.stream_chat(conversation)

            async for chunk in stream_gen:
                if stop_event and stop_event.is_set():
                    yield {"type": "stop", "message": "Agent execution stopped by user."}
                    return
                full_response += chunk
                stream_buffer += chunk

                while stream_buffer:
                    if inside_tool_tag:
                        end_idx = stream_buffer.find("</tool_call>")
                        if end_idx != -1:
                            inside_tool_tag = False
                            stream_buffer = stream_buffer[end_idx + len("</tool_call>") :]
                        else:
                            break
                    else:
                        start_idx = stream_buffer.find("<tool_call")
                        if start_idx != -1:
                            prefix = stream_buffer[:start_idx]
                            if prefix:
                                yield {"type": "token", "token": prefix}
                            inside_tool_tag = True
                            stream_buffer = stream_buffer[start_idx:]
                        else:
                            if "<" in stream_buffer:
                                last_lt = stream_buffer.rfind("<")
                                candidate = stream_buffer[last_lt:]
                                if "<tool_call>".startswith(candidate):
                                    prefix = stream_buffer[:last_lt]
                                    if prefix:
                                        yield {"type": "token", "token": prefix}
                                    stream_buffer = candidate
                                    break
                            yield {"type": "token", "token": stream_buffer}
                            stream_buffer = ""

            if stream_buffer and not inside_tool_tag and not stream_buffer.startswith("<tool_call"):
                clean_flush = re.sub(r"<tool_call>.*?</tool_call>", "", stream_buffer, flags=re.DOTALL)
                clean_flush = re.sub(r"<tool_call.*$", "", clean_flush, flags=re.DOTALL)
                if clean_flush:
                    yield {"type": "token", "token": clean_flush}

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
                    "structured": result.to_dict(),
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
