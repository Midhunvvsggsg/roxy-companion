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
    "look", "see", "watch", "exec", "help", "pause", "resume", "louder", "quieter",
    "music", "song", "songs", "track", "tracks", "playing", "skip", "next", "prev",
    "previous", "listen", "hear", "stream", "tune", "tunes", "browse", "visit",
    "news", "headlines", "weather", "sing", "put", "bring", "fire"
}

APP_SITE_NAMES = {
    "yt", "youtube", "yoututbe", "youtub", "yotube", "youtoube", "ytube",
    "browser", "brave", "firefox", "chrome", "chromium",
    "terminal", "foot", "kitty", "code", "vscode", "discord", "spotify", "mpv", "vlc",
    "git", "github", "gitlab", "web", "google", "googl", "news", "reddit", "twitter", "x"
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
        calls: list[tuple[str, dict]] = []
        registered_tool_names = set(self.registry._tools.keys()) if hasattr(self.registry, "_tools") else set()

        def _clean_block(raw: str) -> str:
            b = raw.strip()
            b = re.sub(r"^```(?:json)?\s*", "", b, flags=re.IGNORECASE)
            b = re.sub(r"\s*```$", "", b)
            return b.strip()

        def _extract_from_data(data: Any, default_name: Optional[str] = None) -> list[tuple[str, dict]]:
            results: list[tuple[str, dict]] = []
            if isinstance(data, list):
                for item in data:
                    results.extend(_extract_from_data(item, default_name))
                return results

            if not isinstance(data, dict):
                return results

            # Check OpenAI tool_calls wrapper
            if "tool_calls" in data and isinstance(data["tool_calls"], list):
                for tc in data["tool_calls"]:
                    results.extend(_extract_from_data(tc, default_name))
                return results

            # Check function wrapper
            name = None
            args = None
            if "function" in data and isinstance(data["function"], dict):
                fn = data["function"]
                name = fn.get("name")
                args = fn.get("arguments")
            else:
                name = data.get("name") or data.get("tool") or data.get("action") or data.get("function") or default_name

            if not name or not isinstance(name, str):
                return results

            name = name.strip()

            if args is None:
                if "arguments" in data:
                    args = data["arguments"]
                elif "args" in data:
                    args = data["args"]
                elif "parameters" in data:
                    args = data["parameters"]
                elif "params" in data:
                    args = data["params"]
                else:
                    args = {k: v for k, v in data.items() if k not in ("name", "tool", "action", "function", "type")}

            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {"query": args} if name in ("music_play", "music_search", "youtube_play") else {"target": args}

            if not isinstance(args, dict):
                args = {}

            results.append((name, args))
            return results

        # 1. Match <tool_call ...>...</tool_call> and unclosed <tool_call ...>...
        matches = list(re.finditer(r"<tool_call(?:\s+name=[\"'](?P<tag_name>[^\"']+)[\"'])?>(.*?)(?:</tool_call>|$)", text, re.DOTALL | re.IGNORECASE))
        for m in matches:
            tag_name = m.group("tag_name")
            block = _clean_block(m.group(2))
            if not block and not tag_name:
                continue

            # Try direct JSON parse
            try:
                data = json.loads(block)
                res = _extract_from_data(data, default_name=tag_name)
                if res:
                    calls.extend(res)
                    continue
            except Exception:
                pass

            # Fallback: Find balanced braces in block
            start_idx = block.find("{")
            parsed_any = False
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
                                res = _extract_from_data(data, default_name=tag_name)
                                if res:
                                    calls.extend(res)
                                    parsed_any = True
                                    break
                            except Exception:
                                pass
            if parsed_any:
                continue

            # Fallback: Python-style function call e.g. open_app(app_name="youtube") or music_play("starboy")
            fn_m = re.match(r"^([a-zA-Z0-9_-]+)\s*\((.*?)\)$", block, re.DOTALL)
            if fn_m:
                fn_name = fn_m.group(1).strip()
                args_str = fn_m.group(2).strip()
                parsed_args: dict[str, Any] = {}
                for kw_m in re.finditer(r'([a-zA-Z0-9_]+)\s*=\s*(?:["\'](.*?)["\']|([^,\s]+))', args_str):
                    k = kw_m.group(1)
                    v = kw_m.group(2) if kw_m.group(2) is not None else kw_m.group(3)
                    parsed_args[k] = v
                if not parsed_args and args_str:
                    clean_pos = args_str.strip("\"'")
                    if fn_name in ("music_play", "music_search", "youtube_play"):
                        parsed_args["query"] = clean_pos
                    elif fn_name in ("open_app", "check_app_running"):
                        parsed_args["app_name"] = clean_pos
                    elif fn_name in ("open_url",):
                        parsed_args["url"] = clean_pos
                calls.append((fn_name, parsed_args))

        # 2. Fallback if no <tool_call> tags matched: check markdown code blocks containing json
        if not calls:
            code_blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
            for cb in code_blocks:
                try:
                    data = json.loads(cb.strip())
                    res = _extract_from_data(data)
                    for p in res:
                        if self.registry.get(p[0]):
                            calls.append(p)
                except Exception:
                    pass

        # 3. Fallback: raw JSON objects embedded in text without tags or fences
        if not calls:
            for json_match in re.finditer(r"(\{(?:[^{}]|(?:\{[^{}]*\}))*\})", text, re.DOTALL):
                try:
                    data = json.loads(json_match.group(1))
                    res = _extract_from_data(data)
                    for p in res:
                        if self.registry.get(p[0]):
                            calls.append(p)
                except Exception:
                    pass

        # 4. Fallback: standalone Python-style function call embedded in text for known registered tools
        if not calls and registered_tool_names:
            pattern = r"\b(" + "|".join(re.escape(n) for n in registered_tool_names) + r")\s*\((.*?)\)"
            for fn_m in re.finditer(pattern, text, re.DOTALL):
                fn_name = fn_m.group(1).strip()
                args_str = fn_m.group(2).strip()
                parsed_args = {}
                for kw_m in re.finditer(r'([a-zA-Z0-9_]+)\s*=\s*(?:["\'](.*?)["\']|([^,\s]+))', args_str):
                    k = kw_m.group(1)
                    v = kw_m.group(2) if kw_m.group(2) is not None else kw_m.group(3)
                    parsed_args[k] = v
                if not parsed_args and args_str:
                    clean_pos = args_str.strip("\"'")
                    if fn_name in ("music_play", "music_search", "youtube_play"):
                        parsed_args["query"] = clean_pos
                    elif fn_name in ("open_app", "check_app_running"):
                        parsed_args["app_name"] = clean_pos
                    elif fn_name in ("open_url",):
                        parsed_args["url"] = clean_pos
                calls.append((fn_name, parsed_args))

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
                                if "<tool_call>".startswith(candidate) or candidate.startswith("<tool_call"):
                                    prefix = stream_buffer[:last_lt]
                                    if prefix:
                                        yield {"type": "token", "token": prefix}
                                    stream_buffer = candidate
                                    break
                            if "```" in stream_buffer:
                                last_tick = stream_buffer.rfind("```")
                                candidate_tick = stream_buffer[last_tick:]
                                if "```json".startswith(candidate_tick) or candidate_tick.startswith("```json"):
                                    prefix = stream_buffer[:last_tick]
                                    if prefix:
                                        yield {"type": "token", "token": prefix}
                                    stream_buffer = candidate_tick
                                    break
                            yield {"type": "token", "token": stream_buffer}
                            stream_buffer = ""

            if stream_buffer and not inside_tool_tag:
                clean_flush = re.sub(r"<tool_call(?:\s+[^>]*)?>[\s\S]*?(?:<\/tool_call>|$)", "", stream_buffer, flags=re.DOTALL | re.IGNORECASE)
                clean_flush = re.sub(r"```(?:json)?\s*\{[\s\S]*?\}\s*```", "", clean_flush, flags=re.DOTALL | re.IGNORECASE)
                clean_flush = re.sub(r"```(?:json)?\s*\{[\s\S]*$", "", clean_flush, flags=re.DOTALL | re.IGNORECASE)
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
                user_label = rel_state.user_id if (rel_state and getattr(rel_state, "user_id", None)) else "the user"
                conversation.append(
                    LLMMessage(
                        role="user",
                        content=f"[System Observation from tool '{tool_name}']:\n{safe_obs}\n\nNow verify this result and reply warmly in character to {user_label}.",
                    )
                )

        yield {"type": "done", "response": "Completed maximum planned steps."}
