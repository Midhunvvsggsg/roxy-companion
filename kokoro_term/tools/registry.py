from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from typing import Optional

from kokoro_term.tools.base import BaseTool
from kokoro_term.tools.builtin.apps import OpenAppTool, OpenUrlTool
from kokoro_term.tools.builtin.file_ops import (
    ReadFileTool,
    SearchFilesTool,
    TrashFileTool,
    WriteFileTool,
)
from kokoro_term.tools.builtin.system_info import SystemInfoTool
from kokoro_term.tools.builtin.shell import ShellCommandTool


class ToolRegistry:
    """Registry maintaining active built-in and plugin tools."""

    def __init__(self, plugins_dir: Optional[str | Path] = None):
        self._tools: dict[str, BaseTool] = {}
        self._register_builtins()

        if plugins_dir:
            self.load_plugins(plugins_dir)

    def _register_builtins(self) -> None:
        builtins: list[BaseTool] = [
            SystemInfoTool(),
            ReadFileTool(),
            WriteFileTool(),
            SearchFilesTool(),
            TrashFileTool(),
            ShellCommandTool(),
            OpenUrlTool(),
            OpenAppTool(),
        ]
        for tool in builtins:
            self.register(tool)

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

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
        """Format tools description and invocation syntax for LLM context."""
        docs = [
            "### Available System Tools & Capabilities:",
            "You have direct permission-governed access to the user's computer through tools.",
            "To invoke a tool, output a tool call block in your response using this exact syntax:",
            "<tool_call>",
            '{"name": "tool_name", "arguments": {"param1": "val1"}}',
            "</tool_call>",
            "",
            "Tools:",
        ]

        for t in self.list_tools():
            tier_badge = f"[{t.tier.upper()}]"
            docs.append(f"- **{t.name}** {tier_badge}: {t.description}")
            if t.parameters:
                params_str = ", ".join(f"{k}: {v.get('type', 'any')}" for k, v in t.parameters.items())
                docs.append(f"  Params: ({params_str})")

        docs.append("")
        docs.append("You may call multiple tools or combine tools with spoken dialogue.")
        return "\n".join(docs) + "\n"
