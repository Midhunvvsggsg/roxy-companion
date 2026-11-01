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
    "news", "headlines", "weather", "sing", "put", "bring", "fire", "research", "latest", "what", "lookup",
    "remind", "reminder", "timer", "alarm", "schedule", "alert"
}

APP_SITE_NAMES = {
    "yt", "youtube", "yoututbe", "youtub", "yotube", "youtoube", "ytube",
    "browser", "brave", "firefox", "chrome", "chromium",
    "terminal", "foot", "kitty", "code", "vscode", "discord", "spotify", "mpv", "vlc",
    "git", "github", "gitlab", "web", "google", "googl", "news", "reddit", "twitter", "x"
}

TERMINAL_ACTION_TOOLS = {
    "music_play",
    "music_control",
    "youtube_play",
    "open_app",
    "open_url",
    "set_reminder",
}

SUCCESS_PATTERNS = [
    r"\b(?:is|now)\s+playing\b",
    r"\bplaying\b",
    r"\bstarted playing\b",
    r"\bopened\b",
    r"\bhas been opened\b",
    r"\bdone\b",
    r"\bfinished\b",
    r"\bhere you go\b",
    r"\bhere is\b",
    r"\bstreaming\b",
    r"\bplay(?:ing|ed)?\s+now\b",
    r"\bsong\s+is\s+playing\b",
    r"\benjoy\s+the\s+(?:music|song|track)\b",
    r"\bput\s+on\b",
]


def contains_premature_success_wording(text: str) -> bool:
    """Check if text contains premature success claims before tool results are verified."""
    clean = re.sub(r"<tool_call(?:\s+[^>]*)?>[\s\S]*?(?:<\/tool_call>|$)", "", text, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"```(?:json)?\s*\{[\s\S]*?\}\s*```", "", clean, flags=re.DOTALL | re.IGNORECASE)
    low = clean.lower()
    return any(re.search(pat, low) for pat in SUCCESS_PATTERNS)


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
                    args = {"query": args} if name in ("music_play", "music_search", "youtube_play", "web_research") else {"target": args}

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
                    if fn_name in ("music_play", "music_search", "youtube_play", "web_research"):
                        parsed_args["query"] = clean_pos
                    elif fn_name in ("open_app", "check_app_running"):
                        parsed_args["app_name"] = clean_pos
                    elif fn_name in ("open_url",):
                        parsed_args["url"] = clean_pos
                calls.append((fn_name, parsed_args))

        # 5. Fallback: bracketed action tag e.g. [action:music_play ...] or [action:tool_name]
        if not calls and registered_tool_names:
            action_pat = r"\[(?:action|tool):\s*([a-zA-Z0-9_-]+)(?:\s*(?:\((.*?)\)|:\s*(.*?)|(\{.*?\})))?\]"
            for act_m in re.finditer(action_pat, text, re.DOTALL | re.IGNORECASE):
                t_name = act_m.group(1).strip()
                if self.registry.get(t_name):
                    raw_fn = act_m.group(2)
                    raw_colon = act_m.group(3)
                    raw_json = act_m.group(4)
                    parsed_args = {}
                    if raw_json:
                        try:
                            parsed_args = json.loads(raw_json)
                        except Exception:
                            pass
                    elif raw_colon:
                        c_val = raw_colon.strip().strip("\"'")
                        if t_name in ("music_play", "music_search", "youtube_play", "web_research"):
                            parsed_args["query"] = c_val
                        elif t_name in ("open_app", "check_app_running"):
                            parsed_args["app_name"] = c_val
                        elif t_name in ("open_url",):
                            parsed_args["url"] = c_val
                    elif raw_fn:
                        for kw_m in re.finditer(r'([a-zA-Z0-9_]+)\s*=\s*(?:["\'](.*?)["\']|([^,\s]+))', raw_fn):
                            k = kw_m.group(1)
                            v = kw_m.group(2) if kw_m.group(2) is not None else kw_m.group(3)
                            parsed_args[k] = v
                        if not parsed_args and raw_fn.strip():
                            c_val = raw_fn.strip().strip("\"'")
                            if t_name in ("music_play", "music_search", "youtube_play", "web_research"):
                                parsed_args["query"] = c_val
                            elif t_name in ("open_app", "check_app_running"):
                                parsed_args["app_name"] = c_val
                            elif t_name in ("open_url",):
                                parsed_args["url"] = c_val
                    if not parsed_args.get("query") and t_name in ("music_play", "music_search", "youtube_play"):
                        m_by = re.search(r"['\"]([^'\"]+)['\"]\s+by\s+([A-Za-z0-9\s]+?)(?:[.,?!]|$)", text, re.IGNORECASE)
                        if m_by:
                            parsed_args["query"] = f"{m_by.group(1).strip()} {m_by.group(2).strip()}"
                        else:
                            quotes = re.findall(r"['\"]([^'\"]{2,50})['\"]", text)
                            ignore_q = {"smile", "blush", "serious", "shy", "surprise", "music", "song", "neutral", "halflidded", "action", "tool"}
                            for q_str in quotes:
                                if q_str.strip().lower() not in ignore_q:
                                    parsed_args["query"] = q_str.strip()
                                    break
                    calls.append((t_name, parsed_args))

        # Deduplicate calls: never call the same terminal action tool multiple times in a single step
        deduped: list[tuple[str, dict]] = []
        seen_t: set[str] = set()
        for t_name, t_args in calls:
            if t_name in TERMINAL_ACTION_TOOLS:
                if t_name in seen_t:
                    continue
                seen_t.add(t_name)
            deduped.append((t_name, t_args))

        return deduped

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
        executed_tool_results: list[tuple[str, bool, ToolResult]] = []
        seen_tool_invocations: set[tuple[str, str]] = set()

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

            # If an action tool has already executed successfully in this turn,
            # this step is a pure confirmation/synthesis turn: suppress tool schema
            has_succ_action = any(
                succ for prev_name, succ, _ in executed_tool_results
                if prev_name in TERMINAL_ACTION_TOOLS and succ
            )
            current_tools_schema = None if has_succ_action else tools_schema

            # 1. Plan & LLM generation with streaming token filtering (never show <tool_call> or [action:] to client)
            full_response = ""
            stream_buffer = ""
            inside_tool_tag = False

            try:
                if current_tools_schema is not None:
                    stream_gen = llm.stream_chat(conversation, tools=current_tools_schema)
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
                                if contains_premature_success_wording(prefix):
                                    yield {"type": "token", "token": "On it! Setting that up...\n"}
                                else:
                                    clean_p = re.sub(r"\[(?:action|tool):[^\]]*\]", "", prefix, flags=re.IGNORECASE)
                                    if clean_p:
                                        yield {"type": "token", "token": clean_p}
                            inside_tool_tag = True
                            stream_buffer = stream_buffer[start_idx:]
                        else:
                            # Strip any bracketed action tags
                            stream_buffer = re.sub(r"\[(?:action|tool):[^\]]*\]", "", stream_buffer, flags=re.IGNORECASE)
                            if "<" in stream_buffer:
                                last_lt = stream_buffer.rfind("<")
                                candidate = stream_buffer[last_lt:]
                                if "<tool_call>".startswith(candidate) or candidate.startswith("<tool_call"):
                                    prefix = stream_buffer[:last_lt]
                                    if prefix:
                                        if contains_premature_success_wording(prefix):
                                            yield {"type": "token", "token": "On it! Setting that up...\n"}
                                        else:
                                            yield {"type": "token", "token": prefix}
                                    stream_buffer = candidate
                                    break
                            if "[" in stream_buffer:
                                last_lb = stream_buffer.rfind("[")
                                candidate_lb = stream_buffer[last_lb:]
                                if any(candidate_lb.lower().startswith(p) for p in ("[action", "[tool")):
                                    prefix = stream_buffer[:last_lb]
                                    if prefix:
                                        if contains_premature_success_wording(prefix):
                                            yield {"type": "token", "token": "On it! Setting that up...\n"}
                                        else:
                                            yield {"type": "token", "token": prefix}
                                    stream_buffer = candidate_lb
                                    break
                            if "```" in stream_buffer:
                                last_tick = stream_buffer.rfind("```")
                                candidate_tick = stream_buffer[last_tick:]
                                if "```json".startswith(candidate_tick) or candidate_tick.startswith("```json"):
                                    prefix = stream_buffer[:last_tick]
                                    if prefix:
                                        if contains_premature_success_wording(prefix):
                                            yield {"type": "token", "token": "On it! Setting that up...\n"}
                                        else:
                                            yield {"type": "token", "token": prefix}
                                    stream_buffer = candidate_tick
                                    break
                            yield {"type": "token", "token": stream_buffer}
                            stream_buffer = ""

            if stream_buffer and not inside_tool_tag:
                clean_flush = re.sub(r"<tool_call(?:\s+[^>]*)?>[\s\S]*?(?:<\/tool_call>|$)", "", stream_buffer, flags=re.DOTALL | re.IGNORECASE)
                clean_flush = re.sub(r"```(?:json)?\s*\{[\s\S]*?\}\s*```", "", clean_flush, flags=re.DOTALL | re.IGNORECASE)
                clean_flush = re.sub(r"```(?:json)?\s*\{[\s\S]*$", "", clean_flush, flags=re.DOTALL | re.IGNORECASE)
                clean_flush = re.sub(r"\[(?:action|tool):[^\]]*\]?", "", clean_flush, flags=re.IGNORECASE)
                if clean_flush:
                    yield {"type": "token", "token": clean_flush}

            # 2. Check for tool calls
            tool_calls = self.parse_tool_calls(full_response)
            if not tool_calls and step == 1 and not executed_tool_results:
                low_u = last_user_msg.strip().lower()
                if re.search(r"\b(?:play|stream|listen\s+to|put\s+on)\b", low_u) and (
                    re.search(r"\b(?:music|song|songs|track|tracks|lofi|audio|soundtrack|album|yt|youtube|tune|tunes)\b", low_u)
                    or any(w in low_u for w in ["starboy", "idol", "believer", "queen", "beat", "beats", "lofi"])
                ):
                    from kokoro_term.tools.music import sanitize_music_query
                    clean_music_q = sanitize_music_query(last_user_msg)
                    tool_calls = [("music_play", {"query": clean_music_q})]

            # Filter out looping or repeat tool calls
            valid_calls: list[tuple[str, dict]] = []
            for t_name, t_args in tool_calls:
                # Terminal action tools that already succeeded in this turn must NEVER re-execute
                if any(succ for prev_name, succ, _ in executed_tool_results if prev_name == t_name and t_name in TERMINAL_ACTION_TOOLS and succ):
                    continue
                # Do not repeat the exact same tool invocation in the same turn
                args_repr = json.dumps(t_args, sort_keys=True) if isinstance(t_args, dict) else str(t_args)
                if (t_name, args_repr) in seen_tool_invocations:
                    continue
                valid_calls.append((t_name, t_args))

            tool_calls = valid_calls

            if not tool_calls:
                # Post-tool response guard:
                if executed_tool_results:
                    # 1. If prior tools failed, block false success wording
                    failed_tools = [(t_name, res) for (t_name, succ, res) in executed_tool_results if not succ]
                    if failed_tools and contains_premature_success_wording(full_response):
                        failed_name, failed_res = failed_tools[-1]
                        err_detail = failed_res.error or failed_res.detail or "Execution failed"
                        full_response = f"I wasn't able to {failed_name.replace('_', ' ')}: {err_detail}."

                    # 2. If music_play succeeded: ensure response does not contain mixup apologies or hallucinated track
                    succ_music = [(t_name, res) for (t_name, succ, res) in executed_tool_results if succ and t_name == "music_play"]
                    if succ_music:
                        _, music_res = succ_music[-1]
                        track_info = {}
                        if music_res.data and isinstance(music_res.data, dict):
                            track_info = music_res.data.get("track", {})
                        if not track_info and hasattr(music_res, "structured") and isinstance(music_res.structured, dict):
                            track_info = music_res.structured.get("track", {})

                        real_title = track_info.get("title", "")
                        real_channel = track_info.get("channel", "")

                        has_mixup = any(w in full_response.lower() for w in ("mix-up", "mixup", "mistake", "roxy music", "instead, i played"))
                        if real_title:
                            clean_t = re.sub(r"\(.*?\)|\[.*?\]", "", real_title).strip().lower()
                            has_title_match = any(w in full_response.lower() for w in clean_t.split() if len(w) > 3)
                            has_channel_match = real_channel.lower() in full_response.lower() if real_channel else False
                            if has_mixup or not (has_title_match or has_channel_match):
                                full_response = f"[emotion:smile] Playing '{real_title}' by {real_channel} for you, sir. Enjoy the music!"

                clean_final_resp = re.sub(r"\[(?:action|tool):[^\]]*\]", "", full_response, flags=re.IGNORECASE).strip()
                yield {"type": "done", "response": clean_final_resp}
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
                    executed_tool_results.append((tool_name, False, ToolResult(success=False, error=err_text)))
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

                # Auto-fill query from model text or user message if omitted or generic placeholder
                if tool_name in ("music_play", "music_search", "youtube_play") and (not args.get("query") or str(args.get("query")).strip() in ("", "songs", "music", "song")):
                    cand_q = None
                    m_by = re.search(r"['\"]([^'\"]+)['\"]\s+by\s+([A-Za-z0-9\s]+?)(?:[.,?!]|$)", full_response, re.IGNORECASE)
                    if m_by:
                        cand_q = f"{m_by.group(1).strip()} {m_by.group(2).strip()}"
                    else:
                        quotes = re.findall(r"['\"]([^'\"]{2,50})['\"]", full_response)
                        ignore_q = {"smile", "blush", "serious", "shy", "surprise", "music", "song", "neutral", "halflidded", "action", "tool"}
                        for q_str in quotes:
                            if q_str.strip().lower() not in ignore_q:
                                cand_q = q_str.strip()
                                break
                    if cand_q:
                        args["query"] = cand_q
                    else:
                        from kokoro_term.tools.music import sanitize_music_query
                        clean_q = sanitize_music_query(last_user_msg)
                        args["query"] = clean_q or "trending hits"

                args_repr = json.dumps(args, sort_keys=True) if isinstance(args, dict) else str(args)
                seen_tool_invocations.add((tool_name, args_repr))

                # Safe / Moderate execution
                yield {
                    "type": "tool_start",
                    "tool": tool_name,
                    "args": args,
                    "tier": tier,
                }

                result = await self.execute_tool(tool, args)
                executed_tool_results.append((tool_name, result.success, result))
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
                if result.success and tool_name in TERMINAL_ACTION_TOOLS:
                    obs_prompt = (
                        f"[System Observation from tool '{tool_name}']:\n{safe_obs}\n\n"
                        f"The action has finished executing successfully. DO NOT invoke any tools, do not output `<tool_call>` blocks, and do not include `[action:...]` tags. "
                        f"Provide only your final spoken conversational response in character to {user_label} confirming what is now playing or completed."
                    )
                else:
                    obs_prompt = f"[System Observation from tool '{tool_name}']:\n{safe_obs}\n\nNow verify this result and reply warmly in character to {user_label}."

                conversation.append(LLMMessage(role="user", content=obs_prompt))

        yield {"type": "done", "response": "Completed maximum planned steps."}
