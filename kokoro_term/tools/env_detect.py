"""Operating System and Environment Detection & Caching for Roxy Agent."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import Any, Optional

_CACHED_ENV: Optional[dict[str, Any]] = None


def detect_environment(force_refresh: bool = False) -> dict[str, Any]:
    global _CACHED_ENV
    if _CACHED_ENV is not None and not force_refresh:
        return _CACHED_ENV

    sys_name = platform.system()
    info: dict[str, Any] = {
        "os": sys_name,
        "release": platform.release(),
        "arch": platform.machine(),
        "distro": "Unknown",
        "distro_id": "unknown",
        "package_manager": None,
        "display_server": "unknown",
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or "unknown",
        "browser": None,
        "helpers": {},
    }

    if sys_name == "Linux":
        # Check /etc/os-release
        if os.path.exists("/etc/os-release"):
            try:
                with open("/etc/os-release", "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("PRETTY_NAME="):
                            info["distro"] = line.split("=", 1)[1].strip().strip('"')
                        elif line.startswith("ID=") and info["distro_id"] == "unknown":
                            info["distro_id"] = line.split("=", 1)[1].strip().strip('"').lower()
            except Exception:
                pass

        # Detect package manager
        for pm in ["pacman", "apt", "dnf", "zypper", "apk", "brew"]:
            if shutil.which(pm):
                info["package_manager"] = pm
                break

        # Detect display server
        if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
            info["display_server"] = "Wayland"
        elif os.environ.get("DISPLAY"):
            info["display_server"] = "X11"

    elif sys_name == "Windows":
        info["distro"] = f"Windows {platform.version()}"
        info["distro_id"] = "windows"
        for pm in ["winget", "choco", "scoop"]:
            if shutil.which(pm):
                info["package_manager"] = pm
                break
        info["display_server"] = "DWM"

    elif sys_name == "Darwin":
        info["distro"] = f"macOS {platform.mac_ver()[0]}"
        info["distro_id"] = "macos"
        if shutil.which("brew"):
            info["package_manager"] = "brew"
        info["display_server"] = "Quartz"

    # Detect default/installed browsers
    for b in ["brave", "chromium", "google-chrome", "firefox"]:
        if shutil.which(b):
            info["browser"] = b
            break

    # Detect installed CLI helpers
    helper_list = [
        "playerctl",
        "wpctl",
        "pactl",
        "brightnessctl",
        "grim",
        "slurp",
        "mpv",
        "yt-dlp",
        "rg",
        "grep",
        "hyprctl",
        "swaymsg",
        "pkill",
        "pgrep",
    ]
    for h in helper_list:
        path = shutil.which(h)
        info["helpers"][h] = path is not None

    _CACHED_ENV = info
    return info


def format_env_for_prompt() -> str:
    env = detect_environment()
    helpers = [h for h, present in env["helpers"].items() if present]
    lines = [
        f"- OS: {env['distro']} ({env['os']} {env['release']})",
        f"- Display / WM: {env['display_server']} | {env['desktop']}",
        f"- Package Manager: {env['package_manager'] or 'None'}",
        f"- Default Browser: {env['browser'] or 'System default'}",
        f"- Available System Helpers: {', '.join(helpers) if helpers else 'Standard shell tools'}",
    ]
    return "\n".join(lines)
