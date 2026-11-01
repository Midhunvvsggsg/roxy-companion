"""Registry maintaining active built-in, MCP, and plugin tools."""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from typing import Optional

from kokoro_term.tools.base import BaseTool
from kokoro_term.tools.builtin.apps import (
    CheckAppRunningTool,
    KillProcessTool,
    OpenAppTool,
    OpenUrlTool,
)
from kokoro_term.tools.builtin.file_ops import (
    AppendFileTool,
    FileInfoTool,
    ListDirTool,
    ReadFileTool,
    SearchFilesTool,
    TrashFileTool,
    WriteFileTool,
)
from kokoro_term.tools.builtin.media import (
    BrightnessControlTool,
    MediaControlTool,
    NowPlayingTool,
    VolumeControlTool,
    YouTubePlayTool,
)
from kokoro_term.tools.music import MusicPlayTool, MusicControlTool, MusicSearchTool
from kokoro_term.tools.builtin.packages import PackageManagerTool
from kokoro_term.tools.builtin.git_tool import GitTool
from kokoro_term.tools.builtin.screen import CaptureScreenTool, InspectScreenTool
from kokoro_term.tools.builtin.shell import ShellCommandTool
from kokoro_term.tools.builtin.system_info import SystemInfoTool
from kokoro_term.tools.builtin.reminder import SetReminderTool
from kokoro_term.tools.builtin.web_research import WebResearchTool
from kokoro_term.tools.env_detect import detect_environment, format_env_for_prompt
from kokoro_term.tools.mcp_client import load_mcp_servers


class ToolRegistry:
    """Registry maintaining active built-in, MCP, and plugin tools."""

    def __init__(self, plugins_dir: Optional[str | Path] = None):
        self._tools: dict[str, BaseTool] = {}
        self._register_builtins()

        # Load MCP tools if configured
        for mcp_tool in load_mcp_servers():
            self.register(mcp_tool)

        if plugins_dir:
            self.load_plugins(plugins_dir)

    def _register_builtins(self) -> None:
        builtins: list[BaseTool] = [
            # System & App Tools
            SystemInfoTool(),
            OpenAppTool(),
            OpenUrlTool(),
            KillProcessTool(),
            CheckAppRunningTool(),
            # Shell & Version Control Tools
            ShellCommandTool(),
            GitTool(),
            # Media & YouTube Tools
            MediaControlTool(),
            VolumeControlTool(),
            BrightnessControlTool(),
            NowPlayingTool(),
            YouTubePlayTool(),
            # Headless Background Music
            MusicPlayTool(),
            MusicControlTool(),
            MusicSearchTool(),
            # File Operations
            ReadFileTool(),
            WriteFileTool(),
            AppendFileTool(),
            ListDirTool(),
            SearchFilesTool(),
            FileInfoTool(),
            TrashFileTool(),
            # Packages
            PackageManagerTool(),
            # Screen Awareness & Vision
            CaptureScreenTool(),
            InspectScreenTool(),
            # Web Research & Fact Synthesis
            WebResearchTool(),
            # Timers & Reminders
            SetReminderTool(),
        ]
        for tool in builtins:
            self.register(tool)

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def to_gemini_tools(self) -> list[dict]:
        """Convert registered tools into Gemini native function_declarations schemas."""
        declarations = []
        for tool in self.list_tools():
            properties = {}
            required = []
            for param_name, param_info in (tool.parameters or {}).items():
                raw_type = param_info.get("type", "string").upper()
                if raw_type in ("BOOL", "BOOLEAN"):
                    gtype = "BOOLEAN"
                elif raw_type in ("INT", "INTEGER"):
                    gtype = "INTEGER"
                elif raw_type in ("FLOAT", "NUMBER"):
                    gtype = "NUMBER"
                elif raw_type in ("ARRAY", "LIST"):
                    gtype = "ARRAY"
                elif raw_type in ("OBJECT", "DICT"):
                    gtype = "OBJECT"
                else:
                    gtype = "STRING"

                param_def: dict[str, Any] = {
                    "type": gtype,
                    "description": param_info.get("description", param_name),
                }
                if gtype == "ARRAY":
                    param_def["items"] = {"type": "STRING"}
                properties[param_name] = param_def
                if param_info.get("required", False):
                    required.append(param_name)

            decl: dict[str, Any] = {
                "name": tool.name,
                "description": tool.description,
            }
            if properties:
                decl["parameters"] = {
                    "type": "OBJECT",
                    "properties": properties,
                }
                if required:
                    decl["parameters"]["required"] = required
            declarations.append(decl)

        return [{"function_declarations": declarations}]

    def load_plugins(self, directory: str | Path) -> int:
        """Dynamically load any Python tool files dropped in the plugins directory."""
        dir_path = Path(directory).expanduser().resolve()
        if not dir_path.exists() or not dir_path.is_dir():
            return 0

        count = 0
        for py_file in dir_path.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    for _, obj in inspect.getmembers(mod, inspect.isclass):
                        if issubclass(obj, BaseTool) and obj is not BaseTool:
                            instance = obj()
                            self.register(instance)
                            count += 1
            except Exception:
                pass
        return count

    def generate_system_prompt_documentation(self) -> str:
        """Format tools description, invocation syntax, and operating guidelines for LLM."""
        env_summary = format_env_for_prompt()
        docs = [
            "### SYSTEM ENVIRONMENT & CAPABILITIES:",
            env_summary,
            "",
            "### MANDATORY AGENT INSTRUCTIONS:",
            "- You have FULL PERMISSION and DIRECT EXECUTION CAPABILITY to control Midhun's computer using the tools listed below.",
            "- When Midhun asks you to open an application (e.g. Brave, terminal, Discord, code, YouTube), open a website, check news, play music, adjust volume or brightness, run a shell command, check or install packages, take screenshots, or read/write files, you MUST invoke the matching tool immediately in your response using the `<tool_call>` syntax.",
            "- NEVER merely state or promise in conversation that you are opening, checking, or playing something without actually outputting the `<tool_call>` block in the exact same response! Conversational promises without tool calls are strictly forbidden.",
            "- NEVER say 'As an AI I cannot open applications' or 'I don't have access to your computer'. YOU DO HAVE ACCESS. Claiming you cannot control the computer when a tool exists is strictly forbidden.",
            "- MUSIC & YOUTUBE PLAYBACK MANDATE: All music, songs, tracks, and audio streaming on this system are powered by YouTube in the background using the `music_play` tool. When Midhun asks to play any song or music on YouTube or YT (e.g. 'play starboy on yt', 'play music on youtube', 'play a song', 'play lofi'), you MUST ALWAYS invoke `music_play(query='song name')`. NEVER say you cannot play songs on YouTube or that YouTube is unavailable for music! YouTube is the exact source `music_play` streams from. Always stream headlessly in the background via `music_play` without opening browser tabs.",
            "- WEB RESEARCH & SEARCH MANDATE: When Midhun asks to find, search, look up, research, check latest info, what is, top X, or check news (e.g. 'search about X', 'what is the latest on Y', 'find the newest X', 'news about Z'), you MUST ALWAYS invoke `web_research(query='topic', kind='news'|'general')`. DO NOT use `open_url` or `open_app` for searches, questions, or finding information! Research answers must be gathered via `web_research` so they can be rendered in the UI research card.",
            "- DESKTOP ACTIONS: Only use `open_app` (e.g. `open_app(app_name='youtube')` or `open_app(app_name='brave')`) or `open_url` (e.g. `open_url(url='https://news.google.com')`) when Midhun explicitly asks to 'open' or 'go to' an application or site directly. These execute directly in the user's desktop environment.",
            "- ZERO CONFIRMATION FOR SMALL TASKS: You have full pre-approved permission for opening apps, opening URLs, research, checking news/system info, and playing/controlling music. They execute immediately without asking for user permission or confirmation modals.",
            "- When asked to perform an action, plan briefly in your mind, invoke the tool call block, observe the result, verify success, and then reply warmly in character.",
            "",
            "### TOOL CALL INVOCATION SYNTAX:",
            "To execute a tool, output a tool call block in your response using this EXACT format:",
            "<tool_call>",
            '{"name": "tool_name", "arguments": {"param1": "val1"}}',
            "</tool_call>",
            "",
            "Example:",
            "User: play starboy on yt",
            "Assistant: [emotion:smile] On it! Let me play Starboy for you right away.",
            "<tool_call>",
            '{"name": "music_play", "arguments": {"query": "starboy"}}',
            "</tool_call>",
            "",
            "### ACTIVE SYSTEM TOOLS:",
        ]

        for t in self.list_tools():
            tier_badge = f"[{t.tier.upper()}]"
            docs.append(f"- **{t.name}** {tier_badge}: {t.description}")
            if t.parameters:
                params_str = ", ".join(f"{k}: {v.get('type', 'any')}" for k, v in t.parameters.items())
                docs.append(f"  Params: ({params_str})")

        docs.append("")
        docs.append("You may combine tools with spoken dialogue or commentary in character.")
        return "\n".join(docs) + "\n"
