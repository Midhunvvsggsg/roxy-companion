"""System Environment & Tool Execution Diagnostic Suite (/doctor)."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import Any
from kokoro_term.tools.gui_env import capture_gui_environment


def run_doctor_checks() -> dict[str, Any]:
    """Run full diagnostic health check for Roxy environment and tools."""
    system = platform.system().lower()
    checks: list[dict[str, Any]] = []
    all_passed = True

    # 1. Environment Variables Check (DISPLAY, WAYLAND_DISPLAY, XDG_RUNTIME_DIR, DBUS)
    gui_env = capture_gui_environment()
    has_display = bool(gui_env.get("WAYLAND_DISPLAY") or gui_env.get("DISPLAY"))
    has_runtime = bool(gui_env.get("XDG_RUNTIME_DIR"))
    has_dbus = bool(gui_env.get("DBUS_SESSION_BUS_ADDRESS"))

    if system == "linux":
        env_ok = has_display and has_runtime
        disp_label = gui_env.get("WAYLAND_DISPLAY") or gui_env.get("DISPLAY") or "None"
        wm_label = gui_env.get("XDG_CURRENT_DESKTOP") or "Unknown"
        detail = f"Display: {disp_label} ({wm_label}), RuntimeDir: {gui_env.get('XDG_RUNTIME_DIR')}"
        fix = "" if env_ok else "Ensure WAYLAND_DISPLAY and XDG_RUNTIME_DIR are exported in your desktop session."
    else:
        env_ok = True
        detail = f"Platform {platform.system()} desktop environment active"
        fix = ""

    if not env_ok:
        all_passed = False
    checks.append({"name": "env_vars", "ok": env_ok, "detail": detail, "fix": fix})

    # 2. URL Opening Capability
    if system == "linux":
        xdg_path = shutil.which("xdg-open")
        browser_path = shutil.which("brave") or shutil.which("chromium") or shutil.which("firefox")
        url_ok = bool(xdg_path or browser_path) and has_display
        detail = f"xdg-open at {xdg_path or browser_path}" if url_ok else "No default browser launcher found"
        fix = "" if url_ok else "Install xdg-utils: sudo pacman -S xdg-utils"
    elif system == "windows":
        url_ok = True
        detail = "Windows shell start command available"
        fix = ""
    else:
        url_ok = bool(shutil.which("open"))
        detail = "macOS open command available" if url_ok else "open command not found"
        fix = ""

    if not url_ok:
        all_passed = False
    checks.append({"name": "url_opening", "ok": url_ok, "detail": detail, "fix": fix})

    # 3. mpv Binary Check
    mpv_path = shutil.which("mpv")
    if mpv_path:
        try:
            out = subprocess.check_output([mpv_path, "--version"], stderr=subprocess.STDOUT, timeout=2).decode()
            v_line = out.splitlines()[0] if out.splitlines() else "installed"
            mpv_ok = True
            detail = f"{v_line} at {mpv_path}"
            fix = ""
        except Exception as e:
            mpv_ok = False
            detail = f"mpv execution error: {e}"
            fix = "Reinstall mpv: sudo pacman -S mpv"
    else:
        mpv_ok = False
        detail = "mpv binary not found in PATH"
        fix = "Install mpv: sudo pacman -S mpv (Arch) or winget install mpv.net (Windows)"

    if not mpv_ok:
        all_passed = False
    checks.append({"name": "mpv", "ok": mpv_ok, "detail": detail, "fix": fix})

    # 4. yt-dlp Binary Check
    ytdlp_path = shutil.which("yt-dlp")
    ytdlp_mod = False
    try:
        import yt_dlp
        ytdlp_mod = True
    except Exception:
        pass

    if ytdlp_path or ytdlp_mod:
        ytdlp_ok = True
        v = "binary" if ytdlp_path else "python package"
        detail = f"yt-dlp available ({v} at {ytdlp_path or 'site-packages'})"
        fix = ""
    else:
        ytdlp_ok = False
        detail = "yt-dlp not found in PATH or Python environment"
        fix = "Install yt-dlp: sudo pacman -S yt-dlp (Arch) or pip install yt-dlp"

    if not ytdlp_ok:
        all_passed = False
    checks.append({"name": "yt_dlp", "ok": ytdlp_ok, "detail": detail, "fix": fix})

    # 5. Notifications Check
    if system == "linux":
        notify_path = shutil.which("notify-send")
        notify_ok = bool(notify_path) and has_dbus
        detail = f"notify-send at {notify_path}" if notify_ok else "Desktop notification daemon or notify-send missing"
        fix = "" if notify_ok else "Install libnotify: sudo pacman -S libnotify"
    elif system == "windows":
        notify_ok = True
        detail = "Windows toast notification system"
        fix = ""
    else:
        notify_ok = True
        detail = "macOS notification system"
        fix = ""

    if not notify_ok:
        all_passed = False
    checks.append({"name": "notifications", "ok": notify_ok, "detail": detail, "fix": fix})

    # 6. Microphone Check
    mic_ok = False
    detail = "No microphone input device detected"
    fix = "Connect a microphone or check PipeWire / PulseAudio audio input settings."
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        input_devs = [d for d in devices if d.get("max_input_channels", 0) > 0]
        if input_devs:
            mic_ok = True
            default_in = sd.query_devices(kind="input")
            detail = f"{len(input_devs)} input device(s) found (Default: {default_in.get('name', 'Audio In')})"
            fix = ""
    except Exception as e:
        detail = f"Microphone check error: {e}"

    if not mic_ok:
        all_passed = False
    checks.append({"name": "microphone", "ok": mic_ok, "detail": detail, "fix": fix})

    return {
        "passed": all_passed,
        "checks": checks,
    }
