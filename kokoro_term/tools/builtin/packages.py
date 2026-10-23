"""Package Manager Tool for Roxy Agent."""

from __future__ import annotations

import asyncio
import shutil
from typing import Any, Optional
from kokoro_term.tools.base import BaseTool, ToolResult
from kokoro_term.tools.env_detect import detect_environment


class PackageManagerTool(BaseTool):
    name = "package_manager"
    description = "Check installed packages, search packages, or install/update software via system package manager."
    parameters = {
        "action": {
            "type": "string",
            "description": "Action: 'check' | 'search' | 'install' | 'update'",
        },
        "package": {
            "type": "string",
            "description": "Package name to check, search, or install",
        },
    }
    tier = "dangerous"  # dynamic: check/search are safe, install/update are dangerous

    async def execute(self, action: str, package: Optional[str] = None, **kwargs) -> ToolResult:
        env = detect_environment()
        pm = env.get("package_manager")
        if not pm:
            return ToolResult(
                success=False,
                output="",
                error="No supported package manager detected on this system.",
            )

        act = action.strip().lower()

        if act == "check":
            if not package:
                return ToolResult(success=False, output="", error="Missing package name for 'check'")
            if pm == "pacman":
                cmd = ["pacman", "-Q", package]
            elif pm == "apt":
                cmd = ["dpkg", "-s", package]
            elif pm == "dnf":
                cmd = ["rpm", "-q", package]
            elif pm == "brew":
                cmd = ["brew", "list", package]
            elif pm == "winget":
                cmd = ["winget", "list", "--id", package]
            else:
                return ToolResult(success=False, output="", error=f"Unsupported package manager: {pm}")

        elif act == "search":
            if not package:
                return ToolResult(success=False, output="", error="Missing query for 'search'")
            if pm == "pacman":
                cmd = ["pacman", "-Ss", package]
            elif pm == "apt":
                cmd = ["apt-cache", "search", package]
            elif pm == "dnf":
                cmd = ["dnf", "search", package]
            elif pm == "brew":
                cmd = ["brew", "search", package]
            elif pm == "winget":
                cmd = ["winget", "search", package]
            else:
                return ToolResult(success=False, output="", error=f"Unsupported package manager: {pm}")

        elif act == "install":
            if not package:
                return ToolResult(success=False, output="", error="Missing package name for 'install'")
            if pm == "pacman":
                cmd = ["sudo", "pacman", "-S", "--noconfirm", package]
            elif pm == "apt":
                cmd = ["sudo", "apt-get", "install", "-y", package]
            elif pm == "dnf":
                cmd = ["sudo", "dnf", "install", "-y", package]
            elif pm == "brew":
                cmd = ["brew", "install", package]
            elif pm == "winget":
                cmd = ["winget", "install", "--exact", "--id", package]
            else:
                return ToolResult(success=False, output="", error=f"Unsupported package manager: {pm}")

        elif act == "update":
            if pm == "pacman":
                cmd = ["sudo", "pacman", "-Syu", "--noconfirm"]
            elif pm == "apt":
                cmd = ["sudo", "apt-get", "update"]
            elif pm == "dnf":
                cmd = ["sudo", "dnf", "upgrade", "-y"]
            elif pm == "brew":
                cmd = ["brew", "upgrade"]
            elif pm == "winget":
                cmd = ["winget", "upgrade", "--all"]
            else:
                return ToolResult(success=False, output="", error=f"Unsupported package manager: {pm}")

        else:
            return ToolResult(success=False, output="", error=f"Unknown action: {act}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            out_str = stdout.decode(errors="replace").strip()
            err_str = stderr.decode(errors="replace").strip()

            if proc.returncode != 0:
                return ToolResult(
                    success=False,
                    output=out_str,
                    error=err_str or f"Package command failed with exit code {proc.returncode}",
                )

            return ToolResult(
                success=True,
                output=out_str or f"Successfully executed '{' '.join(cmd)}'",
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Package execution error: {e}")
