from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any
from kokoro_term.tools.base import BaseTool, ToolResult


class GitTool(BaseTool):
    name = "git_tool"
    description = (
        "Inspect and analyze Git repositories: status, diff, log, branch, or show commit details. "
        "Ideal for assisting the user with code reviews, branch checks, and tracking recent changes."
    )
    parameters = {
        "action": {
            "type": "string",
            "enum": ["status", "diff", "log", "branch", "show"],
            "description": "The git action to inspect: 'status', 'diff', 'log', 'branch', or 'show'",
        },
        "repo_path": {
            "type": "string",
            "description": "Path to the repository root directory (default is current directory '.')",
            "default": ".",
        },
        "args": {
            "type": "string",
            "description": "Optional extra git flags or parameters (e.g. '--stat', '-n 5', 'HEAD~1', or file paths)",
            "default": "",
        },
    }
    tier = "safe"

    async def dry_run(self, action: str, repo_path: str = ".", args: str = "", **kwargs) -> str:
        return f"Would run: git {action} {args} in {repo_path}"

    async def execute(self, action: str, repo_path: str = ".", args: str = "", **kwargs) -> ToolResult:
        if not shutil.which("git"):
            return ToolResult(success=False, output="", error="git binary is not installed or not found in PATH.")

        clean_path = os.path.expanduser(repo_path.strip() or ".")
        if not os.path.isdir(clean_path):
            return ToolResult(success=False, output="", error=f"Target path '{clean_path}' does not exist or is not a directory.")

        valid_actions = {"status", "diff", "log", "branch", "show"}
        clean_action = action.strip().lower()
        if clean_action not in valid_actions:
            return ToolResult(
                success=False,
                output="",
                error=f"Invalid git action '{action}'. Choose from: {sorted(valid_actions)}",
            )

        cmd = ["git", clean_action]

        # Sensible defaults for actions if no extra args provided
        if clean_action == "log" and not args:
            cmd.extend(["-n", "5", "--oneline", "--decorate"])
        elif clean_action == "status" and not args:
            cmd.append("-s")

        if args.strip():
            # Split sanitized arguments
            cmd.extend(args.strip().split())

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=clean_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=15.0,
            )

            stdout = stdout_bytes.decode(errors="replace").strip()
            stderr = stderr_bytes.decode(errors="replace").strip()

            if process.returncode != 0:
                err_msg = stderr or stdout or f"Git exited with returncode {process.returncode}"
                return ToolResult(success=False, output=stdout, error=err_msg)

            output_text = stdout if stdout else "(No output / repository is clean)"
            # Cap display length if diff or log is massive
            if len(output_text) > 4000:
                output_text = output_text[:4000] + "\n... [truncated 4000+ chars]"

            return ToolResult(success=True, output=output_text)

        except asyncio.TimeoutError:
            return ToolResult(success=False, output="", error="Git operation timed out after 15 seconds.")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
