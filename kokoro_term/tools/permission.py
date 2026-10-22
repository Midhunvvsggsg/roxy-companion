from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from kokoro_term.config import ToolsConfig
from kokoro_term.tools.base import BaseTool, ToolTier


DANGEROUS_COMMAND_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\brmdir\s+/s\b",
    r"\bdel\s+/f\b",
    r"\bformat\b",
    r"\bmkfs\b",
    r"\bdd\b",
    r"\bsudo\b",
    r"\bchmod\s+-R\s+777\b",
    r"\bchown\b",
    r"\breg\s+delete\b",
    r"\bdiskpart\b",
    r":(){ :|:& };:",  # fork bomb
]


class PermissionManager:
    """Enforces safety tiers, session permissions, and directory sandboxing."""

    def __init__(self, config: ToolsConfig):
        self.config = config
        self.approved_moderate_session: set[str] = set()

    def check_sandbox(self, path: str | Path) -> bool:
        """Verify that the target path does not violate sandbox boundary if configured."""
        if not self.config.sandbox_dir:
            return True

        sandbox_root = Path(self.config.sandbox_dir).expanduser().resolve()
        target = Path(path).expanduser().resolve()

        try:
            target.relative_to(sandbox_root)
            return True
        except ValueError:
            return False

    def classify_command_tier(self, command: str) -> ToolTier:
        """Dynamically detect if a shell command contains dangerous system operations."""
        import re
        cmd_lower = command.lower()
        for pat in DANGEROUS_COMMAND_PATTERNS:
            if re.search(pat, cmd_lower):
                return "dangerous"
        return "moderate"

    def requires_confirmation(self, tool: BaseTool, arguments: dict) -> tuple[bool, str]:
        """
        Check if a tool call requires user confirmation before execution.
        Returns (needs_confirmation, reason_or_prompt).
        """
        tier = tool.tier

        # Dynamic escalation for shell execution
        if tool.name == "run_command" and "command" in arguments:
            tier = self.classify_command_tier(arguments["command"])

        # Check sandbox for path-based tools
        if "path" in arguments:
            if not self.check_sandbox(arguments["path"]):
                return True, f"[Sandbox Violation] Path '{arguments['path']}' is outside allowed directory: {self.config.sandbox_dir}"

        if tier == "safe":
            return False, ""

        if tier == "moderate":
            if self.config.auto_approve_moderate:
                return False, ""
            call_sig = f"{tool.name}:{sorted(arguments.items())}"
            if call_sig in self.approved_moderate_session:
                return False, ""
            return True, f"Moderate operation: {tool.name} with {arguments}"

        if tier == "dangerous":
            return True, f"[DANGEROUS OPERATION] {tool.name} with {arguments}. Explicit confirmation required."

        return False, ""

    def approve_for_session(self, tool_name: str, arguments: dict) -> None:
        call_sig = f"{tool_name}:{sorted(arguments.items())}"
        self.approved_moderate_session.add(call_sig)
