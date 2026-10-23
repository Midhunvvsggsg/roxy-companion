from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kokoro_term.character import load_character
from kokoro_term.config import load_config
from kokoro_term.llm.factory import create_llm_provider
from kokoro_term.memory.manager import MemoryManager
from kokoro_term.tools.agent import AgentLoop
from kokoro_term.tools.audit import AuditLogger
from kokoro_term.tools.permission import PermissionManager
from kokoro_term.tools.registry import ToolRegistry
from kokoro_term.tools.resistance import ResistanceManager
from kokoro_term.ui.app import KokoroApp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="kokoro-term",
        description="Kokoro-Term: An anime AI companion for your terminal.",
    )
    parser.add_argument(
        "-c", "--character",
        type=str,
        default=None,
        help="Character ID to load (e.g., 'roxy')",
    )
    parser.add_argument(
        "-p", "--provider",
        type=str,
        default=None,
        choices=["gemini", "openai", "ollama", "mock"],
        help="LLM provider override",
    )
    parser.add_argument(
        "-m", "--model",
        type=str,
        default=None,
        help="Model identifier override",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Shortcut to run with mock provider (no API key needed)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Path to SQLite memory database",
    )
    parser.add_argument(
        "--sandbox",
        type=str,
        default=None,
        help="Restrict file tools to this directory",
    )
    parser.add_argument(
        "--no-tools",
        action="store_true",
        help="Disable system tool calling layer",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to custom config.yaml",
    )
    parser.add_argument(
        "--avatar-backend",
        type=str,
        default=None,
        choices=["auto", "window", "terminal"],
        help="Avatar display backend: auto, window (PySide6 desktop), or terminal",
    )
    parser.add_argument(
        "--protocol",
        type=str,
        default=None,
        choices=["auto", "sixel", "kitty", "half_block", "ascii"],
        help="Terminal graphics rendering protocol override: sixel, kitty, half_block, ascii",
    )
    parser.add_argument(
        "--video",
        action="store_true",
        help="Play high-resolution 60 FPS avatar video directly inside the terminal via Sixel graphics",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Launch full 60 FPS WebGL 2.5D pseudo-3D companion window",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Terminal Video Playback (Sixel / Foot)
    if args.video:
        import subprocess
        import shutil
        char = args.character or "roxy"
        base_dir = Path(__file__).resolve().parent.parent / "characters" / char / "avatar"
        video_path = base_dir / f"{char}_terminal.mp4"
        if not video_path.exists():
            video_path = base_dir / f"{char}_terminal.webm"
        if not video_path.exists():
            video_path = Path("/home/midhun/kokoro-term/characters/roxy/avatar/roxy_terminal.mp4")

        vo = args.protocol if args.protocol in ["sixel", "kitty"] else "sixel"
        if shutil.which("mpv"):
            print(f"[Kokoro-Term] Playing high-resolution avatar video inside terminal ({vo})... (Press 'q' to stop)")
            subprocess.run(["mpv", f"--vo={vo}", "--loop=inf", str(video_path)])
            return 0
        else:
            print("[Error] 'mpv' is required to render video inside terminal via Sixel graphics.", file=sys.stderr)
            return 1

    # WebGL 60 FPS Companion shortcut
    if args.web:
        import subprocess
        import shutil
        import webbrowser
        import socket
        import time

        # Ensure Python backend service is running on port 5174
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        is_running = s.connect_ex(('127.0.0.1', 5174)) == 0
        s.close()
        if not is_running:
            service_path = Path("/home/midhun/Development/mesh-avatar-studio/tools/roxy_service.py")
            if service_path.exists():
                subprocess.Popen([sys.executable, str(service_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(0.8)

        url = "http://127.0.0.1:5174/companion.html?project=roxy"
        if shutil.which("brave"):
            subprocess.Popen(["brave", f"--app={url}"])
            print("[Kokoro-Term] Launched 60 FPS WebGL Companion in Brave App Mode!")
            return 0
        elif shutil.which("chromium"):
            subprocess.Popen(["chromium", f"--app={url}"])
            print("[Kokoro-Term] Launched 60 FPS WebGL Companion in Chromium App Mode!")
            return 0
        else:
            webbrowser.open(url)
            print("[Kokoro-Term] Opened 60 FPS WebGL Companion in browser!")
            return 0

    # Load configuration
    config = load_config(args.config)

    # CLI Overrides
    if args.protocol and args.protocol != "auto":
        import os
        os.environ["KOKORO_RENDER_PROTOCOL"] = args.protocol
    if args.character:
        config.active_character = args.character
    if args.mock:
        config.llm.provider = "mock"
    elif args.provider:
        config.llm.provider = args.provider
    if args.model:
        config.llm.model = args.model
    if args.db:
        config.memory.db_path = args.db
    if args.sandbox:
        config.tools.sandbox_dir = args.sandbox
    if args.no_tools:
        config.tools.enabled = False
    if args.avatar_backend:
        config.avatar.backend = args.avatar_backend

    # Locate character directory
    char_dir = Path("characters")
    if not (char_dir / config.active_character).exists():
        char_dir = Path(__file__).resolve().parent.parent / "characters"

    try:
        character = load_character(config.active_character, character_dir=char_dir)
    except FileNotFoundError as e:
        print(f"[Error] Failed to load character: {e}", file=sys.stderr)
        return 1

    # Initialize LLM Provider
    try:
        llm_provider = create_llm_provider(config.llm)
    except Exception as e:
        print(f"[Error] Failed to initialize LLM provider: {e}", file=sys.stderr)
        return 1

    # Initialize Memory Manager
    memory_manager = None
    if config.memory and config.memory.enabled:
        try:
            memory_manager = MemoryManager(config.memory)
        except Exception as e:
            print(f"[Warning] Failed to initialize SQLite memory manager ({e}). Running without persistence.", file=sys.stderr)

    # Initialize Tool / Agency System
    tool_registry = None
    agent_loop = None
    if config.tools and config.tools.enabled:
        try:
            tool_registry = ToolRegistry(plugins_dir="tools")
            permission_mgr = PermissionManager(config.tools)
            audit_logger = AuditLogger(config.tools.audit_log_path)
            resistance_mgr = ResistanceManager()
            agent_loop = AgentLoop(
                config=config.tools,
                registry=tool_registry,
                permission=permission_mgr,
                audit=audit_logger,
                resistance=resistance_mgr,
            )
        except Exception as e:
            print(f"[Warning] Failed to initialize tools subsystem: {e}", file=sys.stderr)

    # Run Textual TUI Application
    app = KokoroApp(
        config=config,
        character=character,
        llm_provider=llm_provider,
        memory_manager=memory_manager,
        tool_registry=tool_registry,
        agent_loop=agent_loop,
    )
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
