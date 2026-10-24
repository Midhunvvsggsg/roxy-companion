"""GUI Environment Capture and Safe Detached Process Spawning for Roxy Agent."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from typing import Any, Optional

_CAPTURED_ENV: Optional[dict[str, str]] = None


def capture_gui_environment(force_refresh: bool = False) -> dict[str, str]:
    """Capture critical GUI, Desktop, and Window Manager environment variables.

    When Roxy runs as a background service or daemon, processes need DISPLAY,
    WAYLAND_DISPLAY, XDG_RUNTIME_DIR, and DBUS_SESSION_BUS_ADDRESS to open GUI
    windows (e.g. browser, mpv, foot, apps) in the user's active session.
    """
    global _CAPTURED_ENV
    if _CAPTURED_ENV is not None and not force_refresh:
        return _CAPTURED_ENV

    env = dict(os.environ)
    system = platform.system().lower()

    if system == "linux":
        uid = os.getuid()
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"

        # Capture or detect WAYLAND_DISPLAY
        if "WAYLAND_DISPLAY" not in env or not env["WAYLAND_DISPLAY"]:
            if os.path.exists(runtime_dir):
                for candidate in ["wayland-1", "wayland-0"]:
                    if os.path.exists(os.path.join(runtime_dir, candidate)):
                        env["WAYLAND_DISPLAY"] = candidate
                        break

        # Capture or detect DISPLAY
        if "DISPLAY" not in env or not env["DISPLAY"]:
            # Default X11 display
            env["DISPLAY"] = ":0"

        # Capture or detect DBUS_SESSION_BUS_ADDRESS
        if "DBUS_SESSION_BUS_ADDRESS" not in env or not env["DBUS_SESSION_BUS_ADDRESS"]:
            dbus_socket = os.path.join(runtime_dir, "bus")
            if os.path.exists(dbus_socket):
                env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={dbus_socket}"

        env["XDG_RUNTIME_DIR"] = runtime_dir

        # Preserve WM-specific variables
        for wm_var in (
            "HYPRLAND_INSTANCE_SIGNATURE",
            "HYPRLAND_CMD",
            "SWAYSOCK",
            "I3SOCK",
            "XDG_CURRENT_DESKTOP",
            "XDG_SESSION_DESKTOP",
            "XDG_SESSION_TYPE",
            "XDG_BACKEND",
            "MOZ_ENABLE_WAYLAND",
            "QT_QPA_PLATFORM",
        ):
            if wm_var in os.environ:
                env[wm_var] = os.environ[wm_var]

    elif system == "windows":
        for win_var in (
            "SYSTEMROOT",
            "APPDATA",
            "LOCALAPPDATA",
            "USERPROFILE",
            "COMSPEC",
            "PATHEXT",
            "TEMP",
            "TMP",
        ):
            if win_var in os.environ:
                env[win_var] = os.environ[win_var]

    _CAPTURED_ENV = env
    return _CAPTURED_ENV


def spawn_gui_process(cmd: list[str], wait_sec: float = 2.0) -> dict[str, Any]:
    """Spawn a GUI process detached (new session, stdin/stdout devnull) with captured GUI env.

    Arguments are passed as a LIST (never through a shell string) to prevent command injection.
    Waits up to `wait_sec` (default 2.0s) and verifies the process started successfully:
    - If it exits with 0: success (e.g. xdg-open delegating to existing browser window).
    - If it exits with non-zero: failure, reporting stderr.
    - If it is still alive: success, returning PID.
    """
    if not isinstance(cmd, list) or not cmd:
        return {
            "ok": False,
            "pid": None,
            "exit_code": -1,
            "stderr": "Command must be a non-empty list of string arguments.",
            "detail": "Invalid command arguments.",
        }

    # Ensure all arguments are strings
    cmd_list = [str(arg) for arg in cmd]
    env = capture_gui_environment()
    system = platform.system().lower()

    try:
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.PIPE,
            "env": env,
        }

        if system == "windows":
            # DETACHED_PROCESS = 0x00000008, CREATE_NEW_PROCESS_GROUP = 0x00000200
            kwargs["creationflags"] = 0x00000008 | 0x00000200
        else:
            kwargs["start_new_session"] = True

        proc = subprocess.Popen(cmd_list, **kwargs)

        # Wait up to wait_sec to verify startup
        start_time = time.monotonic()
        while time.monotonic() - start_time < wait_sec:
            ret = proc.poll()
            if ret is not None:
                # Process terminated
                stderr_data = ""
                if proc.stderr:
                    try:
                        stderr_data = proc.stderr.read().decode(errors="replace").strip()
                    except Exception:
                        pass

                if ret == 0:
                    return {
                        "ok": True,
                        "pid": proc.pid,
                        "exit_code": 0,
                        "stderr": "",
                        "detail": f"Process completed successfully with exit code 0 (PID {proc.pid}).",
                    }
                else:
                    err_msg = stderr_data or f"Process failed with exit code {ret}."
                    return {
                        "ok": False,
                        "pid": proc.pid,
                        "exit_code": ret,
                        "stderr": stderr_data,
                        "detail": err_msg,
                    }
            time.sleep(0.08)

        # Process is still running after wait_sec -> successful background launch
        return {
            "ok": True,
            "pid": proc.pid,
            "exit_code": None,
            "stderr": "",
            "detail": f"Process '{os.path.basename(cmd_list[0])}' started and is running (PID {proc.pid}).",
        }

    except FileNotFoundError:
        return {
            "ok": False,
            "pid": None,
            "exit_code": 127,
            "stderr": f"Executable not found: {cmd_list[0]}",
            "detail": f"Command '{cmd_list[0]}' is not installed or not in PATH.",
        }
    except Exception as e:
        return {
            "ok": False,
            "pid": None,
            "exit_code": -1,
            "stderr": str(e),
            "detail": f"Failed to spawn process: {e}",
        }


def open_url_or_site(target: str, wait_sec: float = 2.0) -> dict[str, Any]:
    """Open a URL or site name in the default browser through xdg-open / start.

    Reuses existing window where supported by browser/DE.
    Normalizes 'yt' or 'youtube' to https://www.youtube.com.
    """
    clean_target = target.strip()

    # Normalize shortcuts
    low = clean_target.lower()
    if low in ("yt", "youtube"):
        url = "https://www.youtube.com"
    elif low in ("github", "gh"):
        url = "https://github.com"
    elif low in ("google",):
        url = "https://www.google.com"
    elif not (clean_target.startswith("http://") or clean_target.startswith("https://")):
        if "." in clean_target and " " not in clean_target:
            url = f"https://{clean_target}"
        else:
            url = f"https://www.youtube.com/results?search_query={clean_target}"
    else:
        url = clean_target

    system = platform.system().lower()
    if system == "linux":
        # Prefer xdg-open to reuse existing window and default browser
        if shutil.which("xdg-open"):
            cmd = ["xdg-open", url]
        else:
            browser = shutil.which("brave") or shutil.which("chromium") or shutil.which("firefox")
            cmd = [browser, url] if browser else ["xdg-open", url]
    elif system == "windows":
        cmd = ["cmd.exe", "/c", "start", "", url]
    elif system == "darwin":
        cmd = ["open", url]
    else:
        cmd = ["xdg-open", url]

    res = spawn_gui_process(cmd, wait_sec=wait_sec)
    res["url"] = url
    return res
