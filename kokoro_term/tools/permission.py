"""Permission and Safety Policy Manager for Roxy Agent."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal, Optional

from kokoro_term.config import ToolsConfig
from kokoro_term.tools.base import BaseTool, ToolTier

DangerousPolicy = Literal["ask", "allow", "block"]

DANGEROUS_COMMAND_PATTERNS = [
    r"\brm\s+-[rRf]+\b",
    r"\brmdir\s+/s\b",
    r"\bdel\s+/[fFqQ]+\b",
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
        self.dangerous_policy: DangerousPolicy = getattr(config, "dangerous_actions", "ask")
        self.approved_session_calls: set[str] = set()

    def set_policy(self, policy: str) -> str:
        p = policy.strip().lower()
        if p in ("ask", "allow", "block"):
            self.dangerous_policy = p  # type: ignore
            return f"Dangerous action policy set to [{p.upper()}]."
        return f"Invalid policy '{policy}'. Must be one of: ask | allow | block."

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
        cmd_lower = command.lower()
        for pat in DANGEROUS_COMMAND_PATTERNS:
            if re.search(pat, cmd_lower):
                return "dangerous"
        return "moderate"

    def classify_tool_tier(self, tool: BaseTool, arguments: dict) -> ToolTier:
        """Dynamically classify tool tier based on arguments and operation target."""
        # Dynamic escalation for package installation/updates
        if tool.name == "package_manager":
            act = str(arguments.get("action", "")).lower()
            if act in ("install", "update"):
                return "dangerous"
            return "safe"

        # Dynamic escalation for shell execution
        if tool.name == "run_command" and "command" in arguments:
            cmd_lower = str(arguments["command"]).lower()
            for pat in DANGEROUS_COMMAND_PATTERNS:
                if re.search(pat, cmd_lower):
                    return "dangerous"
            return "moderate"

        # File modifications outside sandbox/workspace
        if tool.name in ("write_file", "append_file") and "path" in arguments:
            if not self.check_sandbox(arguments["path"]):
                return "dangerous"

        return tool.tier

    def requires_confirmation(self, tool: BaseTool, arguments: dict) -> tuple[bool, str]:
        """Check if a tool call requires user confirmation before execution.
        Returns (needs_confirmation, reason_or_prompt).
        """
        # Check sandbox for path-based tools first
        if "path" in arguments:
            if not self.check_sandbox(arguments["path"]):
                return True, f"[Sandbox Violation] Path '{arguments['path']}' is outside allowed directory: {self.config.sandbox_dir}"

        tier = self.classify_tool_tier(tool, arguments)

        if tier == "safe":
            return False, ""

        call_sig = f"{tool.name}:{sorted(str(v) for v in arguments.values())}"
        if call_sig in self.approved_session_calls:
            return False, ""

        if tier == "moderate":
            if getattr(self.config, "auto_approve_moderate", False):
                return False, ""
            return True, f"Moderate operation: {tool.name} with {arguments}"

        if tier == "dangerous":
            if self.dangerous_policy == "allow":
                return False, ""
            if self.dangerous_policy == "block":
                return True, f"[POLICY BLOCKED] Dangerous action '{tool.name}' is strictly blocked by policy."

            prompt = f"Dangerous Action: {tool.name}({arguments})\nAllow? [y/N]"
            return True, prompt

        return False, ""

    def approve_for_session(self, tool_name: str, arguments: dict) -> None:
        call_sig = f"{tool_name}:{sorted(str(v) for v in arguments.values())}"
        self.approved_session_calls.add(call_sig)
