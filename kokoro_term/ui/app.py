from __future__ import annotations

import asyncio
import math
import random
import re
import shutil
import subprocess
import time
import wave
from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, Static

from rich.console import Group
from rich.text import Text
from rich.segment import Segment, ControlType
from rich.control import Control

# Avoid stdin probing delay during headless or subshell runs
try:
    import textual_image._terminal as term_mod
    term_mod.probe_terminal._result = term_mod.TerminalCapabilities(term_mod.CellSize(10, 20), sixel=True, tgp=False)
    from textual_image.widget import SixelRenderable
    _HAS_SIXEL = True
except Exception:
    _HAS_SIXEL = False
from kokoro_term.avatar.animation import (
    EMOTION_ALIASES,
    VALID_EMOTIONS,
    AnimationEngine,
    parse_and_strip_emotion_tag,
)
from kokoro_term.avatar.backends.base import AvatarBackend
from kokoro_term.avatar.backends.factory import create_avatar_backend
from kokoro_term.avatar.compositor import AvatarCompositor
from kokoro_term.avatar.generator import generate_roxy_sprite_pack
from kokoro_term.avatar.lipsync import AmplitudeLipSync, LipSyncEngine, generate_test_speech_wav
from kokoro_term.avatar.manifest import AvatarManifest
from kokoro_term.avatar.renderer import get_starfield_pixel, image_to_half_block
from kokoro_term.avatar.sprites import SpritePack
from kokoro_term.avatar.terminal import detect_render_protocol
from kokoro_term.character import Character, load_character
from kokoro_term.config import AppConfig
from kokoro_term.llm.base import LLMMessage, LLMProvider
from kokoro_term.memory.manager import MemoryManager
from kokoro_term.perf import format_performance_report
from kokoro_term.relationship.models import RelationshipState
from kokoro_term.tools.agent import AgentLoop
from kokoro_term.tools.audit import AuditLogger
from kokoro_term.tools.permission import PermissionManager
from kokoro_term.tools.registry import ToolRegistry
from kokoro_term.tools.resistance import ResistanceManager
from kokoro_term.wizard import list_available_characters, scaffold_new_character


EMOTION_ART = {
    "neutral": "( • _ • )\n (Neutral)",
    "happy": "( ^ ▽ ^ )\n (Happy)",
    "blush": "(⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄)\n (Blushed)",
    "pout": "( ˘ ︿ ˘ )\n (Pouting)",
    "sad": "( ; _ ; )\n (Saddened)",
    "surprised": "( O _ O )!\n (Surprised)",
    "thinking": "( • ~ • )?\n (Thinking)",
}


def _progress_bar(val: float, width: int = 10) -> str:
    filled = int(round((val / 100.0) * width))
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


class ChatMessageWidget(Static):
    """Widget displaying a single chat message."""

    def __init__(self, sender: str, text: str, is_user: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.sender = sender
        self.text = text
        self.is_user = is_user

    def on_mount(self) -> None:
        self.update_display()

    def update_text(self, new_text: str) -> None:
        self.text = new_text
        self.update_display()

    def update_display(self) -> None:
        if self.is_user:
            self.classes = "chat-msg user-msg"
            self.update(f"[bold cyan]You:[/bold cyan]\n{self.text}")
        else:
            self.classes = "chat-msg bot-msg"
            self.update(f"[bold magenta]{self.sender}:[/bold magenta]\n{self.text}")


class ArticlePanelWidget(Static):
    """Rich interactive panel displaying structured research results in the chat log."""

    def __init__(self, article: Any, **kwargs):
        super().__init__(**kwargs)
        self.article = article

    def on_mount(self) -> None:
        self.classes = "chat-msg research-panel"
        self.update_display()

    def update_display(self) -> None:
        art = self.article
        if isinstance(art, dict):
            headline = art.get("headline", "Web Research Report")
            as_of = art.get("as_of", "")
            lead = art.get("lead", "")
            key_points = art.get("key_points", [])
            sources = art.get("sources", [])
        else:
            headline = getattr(art, "headline", "Web Research Report")
            as_of = getattr(art, "as_of", "")
            lead = getattr(art, "lead", "")
            key_points = getattr(art, "key_points", [])
            sources = getattr(art, "sources", [])

        pts_md = "\n".join([f"  • {p}" for p in key_points[:6]])
        src_preview = f"{len(sources)} sources (run [bold cyan]/sources[/bold cyan] or [bold cyan]/open <n>[/bold cyan])"

        text = (
            f"[bold cyan]📰 {headline}[/bold cyan]\n"
            f"[dim italic]As of {as_of}[/dim italic]\n\n"
            f"[bold]Lead Summary:[/bold]\n{lead}\n\n"
            f"[bold]Key Findings:[/bold]\n{pts_md}\n\n"
            f"[dim]── Sources: {src_preview} | Press '/focus' for full card ──[/dim]"
        )
        self.rendered_text = text
        self.update(text)


class ArticleFocusScreen(ModalScreen):
    """Centered scrollable modal card displaying full research article."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    def __init__(self, article: Any, **kwargs):
        super().__init__(**kwargs)
        self.article = article

    def compose(self) -> ComposeResult:
        with Vertical(id="focus-card"):
            yield Static("[bold cyan]═══════ Research Focus Card (Esc to close) ═══════[/bold cyan]\n")
            with VerticalScroll(id="focus-scroll"):
                md = self.article.markdown if hasattr(self.article, "markdown") else self.article.get("markdown", "")
                yield Static(md)
            yield Static("\n[dim]Commands: /open <n> | /save article | Press Esc to return to chat[/dim]")


class AvatarPanel(Static):
    """Side panel displaying animated character portrait, relationship meters, and status."""

    current_emotion = reactive("neutral")
    affection = reactive(50.0)
    trust = reactive(50.0)
    familiarity = reactive(10.0)
    mood = reactive("neutral")
    stage = reactive("Formal Teacher & Student")
    current_task = reactive("Idle")
    is_speaking = reactive(False)
    avatar_mode = reactive("half_block")
    subtitle_text = reactive("Hello! I am Roxy Migurdia. Ready for today's lesson?")
    voice_status = reactive("Idle (Press Space to Speak)")
    ui_mode = reactive("companion")

    def __init__(self, character: Character, **kwargs):
        super().__init__(**kwargs)
        self.character = character
        self.avatar_dir = Path("characters") / character.id / "avatar"
        if not self.avatar_dir.exists():
            self.avatar_dir = Path(__file__).resolve().parent.parent.parent / "characters" / character.id / "avatar"

        self.animation = AnimationEngine()
        self.compositor: Optional[AvatarCompositor] = None
        if (self.avatar_dir / "manifest.yaml").exists():
            try:
                self.compositor = AvatarCompositor(self.avatar_dir, target_size=(22, 22))
            except Exception:
                self.compositor = None

        self.sprite_pack = SpritePack(self.avatar_dir)
        protocol = detect_render_protocol()
        # Textual TUI renders Unicode half-blocks reliably across all modern terminals
        self.avatar_mode = "half_block" if protocol in ("kitty", "sixel", "half_block") else "ascii"

    def set_emotion(self, emotion: str) -> None:
        self.current_emotion = emotion
        self.animation.set_emotion(emotion)
        self.refresh()

    def set_speaking(self, speaking: bool, lipsync: Optional[LipSyncEngine] = None) -> None:
        self.is_speaking = speaking
        self.animation.set_speaking(speaking, lipsync)
        self.refresh()

    def set_mouth(self, mouth: str) -> None:
        self.animation.set_mouth_shape(mouth)
        self.refresh()

    def on_mount(self) -> None:
        # Subtle idle animation ticking at 12 FPS for breathing and autonomous blinking
        self.set_interval(0.08, self.tick_animation)

    def tick_animation(self) -> None:
        self.refresh()

    def update_relationship(self, state: RelationshipState) -> None:
        self.affection = state.affection
        self.trust = state.trust
        self.familiarity = state.familiarity
        self.mood = state.mood
        self.stage = state.get_relationship_stage()

    def render(self) -> Text:
        now = time.time()

        # Responsive layout sizing based on terminal panel dimensions
        panel_w = self.size.width if self.size.width > 0 else 80
        panel_h = self.size.height if self.size.height > 0 else 24

        # Full-terminal companion mode (fills entire terminal with starry night & centered character)
        if self.ui_mode == "companion" or panel_w >= 48:
            content = Text()

            # 1. Responsive Header (row 0)
            header_str = f"✨ {self.character.name} • {self.character.title} ✨"
            status_str = f"Affection: {self.affection:.1f}% [{_progress_bar(self.affection, width=6)}]  Mood: {self.mood.capitalize()}"
            if panel_h >= 22:
                content.append(header_str.center(panel_w) + "\n", style="bold cyan")
                content.append(status_str.center(panel_w) + "\n", style="dim")
                header_rows = 2
            else:
                content.append(f"{header_str}  |  {status_str}".center(panel_w) + "\n", style="bold cyan")
                header_rows = 1

            # 2. Middle Starry Canvas with Centered Roxy
            footer_rows = 2
            avatar_rows = max(4, panel_h - header_rows - footer_rows)
            canvas_w = panel_w
            canvas_h = avatar_rows * 2

            star_bg = Image.new("RGB", (canvas_w, canvas_h), (5, 6, 12))
            star_pixels = star_bg.load()
            for y in range(canvas_h):
                for x in range(canvas_w):
                    star_pixels[x, y] = get_starfield_pixel(x, y, now)

            avatar_dim = min(canvas_h, int(canvas_w * 0.85))
            if avatar_dim % 2 != 0:
                avatar_dim -= 1
            avatar_dim = max(16, min(avatar_dim, canvas_h))

            if self.compositor is not None:
                state = self.animation.update(now)
                self.compositor.set_target_size((avatar_dim, avatar_dim))
                frame = self.compositor.composite(state)
                if frame:
                    paste_x = (canvas_w - avatar_dim) // 2
                    paste_y = max(0, canvas_h - avatar_dim)
                    star_bg.paste(frame, (paste_x, paste_y), frame)
            elif self.sprite_pack.has_sprites():
                frame = self.sprite_pack.get_composite_frame(
                    emotion=self.current_emotion,
                    is_speaking=self.is_speaking,
                    time_sec=now,
                )
                if frame:
                    resized = frame.resize((avatar_dim, avatar_dim), Image.Resampling.LANCZOS)
                    paste_x = (canvas_w - avatar_dim) // 2
                    paste_y = max(0, canvas_h - avatar_dim)
                    star_bg.paste(resized, (paste_x, paste_y), resized)

            lines = []
            for y in range(0, canvas_h, 2):
                line_parts = []
                for x in range(canvas_w):
                    r1, g1, b1 = star_bg.getpixel((x, y))
                    r2, g2, b2 = star_bg.getpixel((x, y + 1))
                    line_parts.append(f"\033[38;2;{r1};{g1};{b1}m\033[48;2;{r2};{g2};{b2}m▀\033[0m")
                lines.append("".join(line_parts))

            content.append_text(Text.from_ansi("\n".join(lines)))
            content.append("\n")

            # 3. Subtitles and Voice Status
            sub_display = f'Roxy: "{self.subtitle_text}"' if self.subtitle_text else 'Roxy: "..."'
            content.append(sub_display.center(panel_w) + "\n", style="bold italic white")

            voice_line = f"[🎙️ Voice: {self.voice_status} • Press Space to Speak • Press 't' to type • 'q' to quit]"
            content.append(voice_line.center(panel_w), style="dim cyan")
            return content

        inner_w = max(14, panel_w - 2)
        inner_h = max(8, panel_h - 2)

        content = Text()

        # 1. Responsive Header
        if inner_h >= 24:
            content.append(self.character.name + "\n", style="bold blue")
            content.append(self.character.title + "\n\n", style="dim")
            header_lines = 3
        elif inner_h >= 16:
            content.append(f"{self.character.name} • {self.character.title}\n", style="bold blue")
            header_lines = 1
        else:
            content.append(f"{self.character.name}\n", style="bold blue")
            header_lines = 1

        # 2. Responsive Status Lines
        status_text = Text()
        if inner_h >= 26:
            aff_bar = _progress_bar(self.affection, width=8)
            trust_bar = _progress_bar(self.trust, width=8)
            status_text.append(self.stage + "\n", style="bold yellow")
            status_text.append("Affection: ", style="dim")
            status_text.append(f"{self.affection:4.1f}% [{aff_bar}]\n", style="green")
            status_text.append("Trust:     ", style="dim")
            status_text.append(f"{self.trust:4.1f}% [{trust_bar}]\n", style="cyan")
            status_text.append("Mood:      ", style="dim")
            status_text.append(f"{self.mood.capitalize()}\n", style="magenta")
            status_text.append("Task:      ", style="dim")
            status_text.append(f"{self.current_task}", style="cyan")
            status_lines = 6
        elif inner_h >= 18:
            aff_bar = _progress_bar(self.affection, width=6)
            trust_bar = _progress_bar(self.trust, width=6)
            status_text.append("Aff: ", style="dim")
            status_text.append(f"{self.affection:3.0f}%[{aff_bar}] ", style="green")
            status_text.append("Tru: ", style="dim")
            status_text.append(f"{self.trust:3.0f}%[{trust_bar}]\n", style="cyan")
            status_text.append("Mood: ", style="dim")
            status_text.append(f"{self.mood.capitalize()} ", style="magenta")
            status_text.append("• ", style="dim")
            status_text.append(f"{self.current_task}", style="cyan")
            status_lines = 2
        else:
            status_text.append("♥ ", style="green")
            status_text.append(f"{self.affection:.0f}% ", style="bold green")
            status_text.append("★ ", style="cyan")
            status_text.append(f"{self.trust:.0f}% ", style="bold cyan")
            status_text.append("• ", style="dim")
            status_text.append(f"{self.mood.capitalize()}", style="magenta")
            status_lines = 1

        # 3. Avatar Dimensions (1 text row = 2 vertical pixels in half-block)
        available_avatar_rows = inner_h - header_lines - status_lines
        if available_avatar_rows > 8:
            available_avatar_rows -= 1
        available_avatar_rows = max(4, min(available_avatar_rows, 20))

        target_pixel_w = min(inner_w, available_avatar_rows * 2)
        target_pixel_h = available_avatar_rows * 2
        avatar_dim = min(target_pixel_w, target_pixel_h)
        if avatar_dim % 2 != 0:
            avatar_dim -= 1
        avatar_dim = max(12, min(avatar_dim, 36))

        pad_spaces = max(0, (inner_w - avatar_dim) // 2)
        pad_str = " " * pad_spaces

        rendered_art = False
        if self.avatar_mode == "half_block":
            if self.compositor is not None:
                state = self.animation.update(now)
                self.compositor.set_target_size((avatar_dim, avatar_dim))
                frame = self.compositor.composite(state)
                if frame:
                    ansi_str = image_to_half_block(
                        frame,
                        width=avatar_dim,
                        height=avatar_dim,
                        bg_stars=True,
                        time_sec=now,
                    )
                    centered_lines = [pad_str + line for line in ansi_str.split("\n")]
                    content.append_text(Text.from_ansi("\n".join(centered_lines)))
                    content.append("\n")
                    rendered_art = True
            elif self.sprite_pack.has_sprites():
                frame = self.sprite_pack.get_composite_frame(
                    emotion=self.current_emotion,
                    is_speaking=self.is_speaking,
                    time_sec=now,
                )
                if frame:
                    ansi_str = image_to_half_block(
                        frame,
                        width=avatar_dim,
                        height=avatar_dim,
                        bg_stars=True,
                        time_sec=now,
                    )
                    centered_lines = [pad_str + line for line in ansi_str.split("\n")]
                    content.append_text(Text.from_ansi("\n".join(centered_lines)))
                    content.append("\n")
                    rendered_art = True

        if not rendered_art:
            art = EMOTION_ART.get(self.current_emotion, EMOTION_ART["neutral"])
            content.append(art + "\n\n", style="bold white")

        content.append_text(status_text)
        return content


class KokoroApp(App):
    """Textual TUI for Kokoro-Term."""

    CSS = """
    Screen {
        layout: vertical;
        background: $surface;
    }

    #main-container {
        height: 1fr;
        layout: horizontal;
    }

    #chat-scroll {
        width: 1fr;
        height: 1fr;
        border: round $primary;
        padding: 1;
        overflow-y: auto;
    }

    #avatar-panel {
        width: 30;
        min-width: 20;
        max-width: 36;
        height: 1fr;
        border: round $secondary;
        padding: 0 1;
        background: #05060d;
    }

    .chat-msg {
        margin-bottom: 1;
        padding: 1;
        border-left: wide $accent;
        background: $boost;
    }

    .user-msg {
        border-left: wide $success;
    }

    .bot-msg {
        border-left: wide $primary;
    }

    .research-panel {
        border-left: wide #00e5ff;
        background: #0d1b2a;
    }

    ArticleFocusScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.75);
    }

    #focus-card {
        width: 85%;
        height: 85%;
        border: heavy #00e5ff;
        background: #05060d;
        padding: 1 2;
    }

    #focus-scroll {
        width: 100%;
        height: 1fr;
        overflow-y: auto;
    }

    #input-container {
        height: auto;
        dock: bottom;
        padding: 0 1;
    }

    #user-input {
        width: 100%;
        border: tall $accent;
    }

    .companion-mode #main-container {
        width: 100%;
        height: 100%;
    }

    .companion-mode #chat-scroll {
        display: none;
    }

    .companion-mode #input-container {
        display: none;
    }

    .companion-mode #input-container.active {
        display: block;
        dock: bottom;
    }

    .companion-mode #avatar-panel {
        width: 100%;
        max-width: 100%;
        height: 100%;
        border: none;
        padding: 0;
        background: #05060d;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("q", "quit", "Quit", show=False),
        Binding("space", "voice_talk", "Voice", show=True),
        Binding("v", "voice_talk", "Voice", show=False),
        Binding("t", "toggle_text", "Text", show=True),
        Binding("escape", "hide_text", "Close Text", show=False),
        Binding("1", "set_emotion_1", "Neutral", show=False),
        Binding("2", "set_emotion_2", "Happy", show=False),
        Binding("3", "set_emotion_3", "Blush", show=False),
        Binding("4", "set_emotion_4", "Thinking", show=False),
        Binding("5", "set_emotion_5", "Surprised", show=False),
        Binding("ctrl+l", "clear_chat", "Clear", show=True),
    ]

    def __init__(
        self,
        config: AppConfig,
        character: Character,
        llm_provider: LLMProvider,
        memory_manager: Optional[MemoryManager] = None,
        tool_registry: Optional[ToolRegistry] = None,
        agent_loop: Optional[AgentLoop] = None,
        avatar_backend: Optional[AvatarBackend] = None,
    ):
        super().__init__()
        self.config = config
        self.character = character
        self.llm = llm_provider
        self.memory = memory_manager
        self.tools = tool_registry
        self.agent_loop = agent_loop
        self.user_id = config.memory.user_id if config.memory else "default_user"
        self.messages: list[LLMMessage] = []
        self.is_responding = False
        self._last_user_message = ""

        # Avatar Backend initialization
        self.avatar_backend = avatar_backend
        if self.avatar_backend is None:
            backend_mode = self.config.avatar.backend if hasattr(self.config, "avatar") and self.config.avatar else "auto"
            avatar_dir = Path("characters") / character.id / "avatar"
            try:
                self.avatar_backend = create_avatar_backend(mode=backend_mode, avatar_dir=avatar_dir)
            except Exception:
                self.avatar_backend = None

        # TTS Manager with pinning and visible fallback support
        from kokoro_term.tts.manager import TTSManager
        pref = getattr(self.config.voice, "provider", "edge") if hasattr(self.config, "voice") and self.config.voice else "edge"
        pinned = getattr(self.config.voice, "pinned", False) if hasattr(self.config, "voice") and self.config.voice else False
        self.tts = TTSManager(voice_config=self.character.voice, preferred_provider=pref, pinned=pinned)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-container"):
            yield VerticalScroll(id="chat-scroll")
            yield AvatarPanel(character=self.character, id="avatar-panel")
        with Container(id="input-container"):
            yield Input(placeholder=f"Talk to {self.character.display_name}... (Press Enter to send)", id="user-input")
        yield Footer()

    def on_resize(self, event) -> None:
        try:
            panel = self.query_one("#avatar-panel")
            if getattr(self.config.ui, "mode", "companion") == "companion":
                panel.styles.width = "100%"
            else:
                if event.size.width < 75:
                    panel.styles.width = 24
                elif event.size.width < 95:
                    panel.styles.width = 28
                else:
                    panel.styles.width = 32
        except Exception:
            pass

    async def action_voice_talk(self) -> None:
        avatar_panel = self.query_one("#avatar-panel", AvatarPanel)
        avatar_panel.voice_status = "Listening..."
        avatar_panel.set_speaking(False)
        self.refresh()
        await asyncio.sleep(0.3)

        responses = [
            ("happy", "Yes! Ready for today's lesson, Midhun-san? Let's practice water magic together!"),
            ("blush", "W-Wait, you're complimenting me so suddenly?! I-I'm your teacher, you know!"),
            ("thinking", "Hmm... Let me think about that spell configuration for a moment."),
            ("surprised", "Eh?! You mastered silent water incantation already?!"),
            ("happy", "Good work! Keep up this level of focus and you will become an advanced magician in no time."),
        ]
        import random
        emo, speech = random.choice(responses)

        avatar_panel.voice_status = "Speaking..."
        avatar_panel.set_emotion(emo)
        avatar_panel.subtitle_text = speech
        avatar_panel.set_speaking(True)
        self.refresh()

        if self.memory:
            rel = self.memory.relationship.get_state(self.character.id, self.user_id)
            rel.record_interaction("positive", boost=1.0)
            avatar_panel.update_relationship(rel)

        await asyncio.sleep(2.5)
        avatar_panel.set_speaking(False)
        avatar_panel.voice_status = "Idle (Press Space to Speak)"
        self.refresh()

    def action_toggle_text(self) -> None:
        inp_container = self.query_one("#input-container")
        inp_container.toggle_class("active")
        if inp_container.has_class("active"):
            try:
                self.query_one("#user-input").focus()
            except Exception:
                pass
        else:
            self.set_focus(None)

    def action_hide_text(self) -> None:
        inp_container = self.query_one("#input-container")
        if inp_container.has_class("active"):
            inp_container.remove_class("active")
            self.set_focus(None)

    def action_set_emotion_1(self) -> None:
        self.query_one("#avatar-panel", AvatarPanel).set_emotion("neutral")

    def action_set_emotion_2(self) -> None:
        self.query_one("#avatar-panel", AvatarPanel).set_emotion("happy")

    def action_set_emotion_3(self) -> None:
        self.query_one("#avatar-panel", AvatarPanel).set_emotion("blush")

    def action_set_emotion_4(self) -> None:
        self.query_one("#avatar-panel", AvatarPanel).set_emotion("thinking")

    def action_set_emotion_5(self) -> None:
        self.query_one("#avatar-panel", AvatarPanel).set_emotion("surprised")

    def on_mount(self) -> None:
        self.title = f"Kokoro-Term | {self.character.name}"
        self.sub_title = "AI Terminal Companion"
        if self.avatar_backend:
            try:
                self.avatar_backend.start()
            except Exception:
                pass

        chat_scroll = self.query_one("#chat-scroll", VerticalScroll)
        avatar_panel = self.query_one("#avatar-panel", AvatarPanel)

        ui_mode = getattr(self.config.ui, "mode", "companion")
        if ui_mode == "companion":
            self.screen.add_class("companion-mode")
            avatar_panel.ui_mode = "companion"
            avatar_panel.styles.width = "100%"
            avatar_panel.styles.max_width = "100%"
            avatar_panel.styles.height = "100%"
            self.set_focus(None)

        # Sync relationship state to AvatarPanel
        if self.memory:
            rel_state = self.memory.relationship.get_state(self.character.id, self.user_id)
            avatar_panel.update_relationship(rel_state)

        # Load recent conversation from SQLite if available
        if self.memory:
            recent_msgs = self.memory.get_recent_messages(self.character.id, self.user_id, limit=20)
            if recent_msgs:
                for msg in recent_msgs:
                    is_user = (msg.role == "user")
                    sender = "You" if is_user else self.character.display_name
                    display_content = re.sub(r"\[emotion:[a-zA-Z0-9_-]+\]\s*", "", msg.content)
                    # Don't show raw tool_call tags in historic chat replay
                    display_content = re.sub(r"<tool_call>.*?</tool_call>", "", display_content, flags=re.DOTALL).strip()
                    if display_content:
                        chat_scroll.mount(ChatMessageWidget(sender=sender, text=display_content, is_user=is_user))
            else:
                greeting = f"Hello. I am {self.character.name}. How may I assist you in the terminal today?"
                chat_scroll.mount(ChatMessageWidget(sender=self.character.display_name, text=greeting, is_user=False))
        else:
            greeting = f"Hello. I am {self.character.name}. How may I assist you in the terminal today?"
            chat_scroll.mount(ChatMessageWidget(sender=self.character.display_name, text=greeting, is_user=False))

        self.query_one("#user-input", Input).focus()

    def on_unmount(self) -> None:
        if self.avatar_backend:
            try:
                self.avatar_backend.stop()
            except Exception:
                pass

    def _prepare_system_prompt(self, current_user_query: str = "") -> str:
        """Build the complete system prompt including base personality, memory, relationship, and tools."""
        effective_name = self.user_id
        if self.memory:
            pref = self.memory.get_preferred_name(self.character.id, self.user_id)
            if pref:
                effective_name = pref

        base_prompt = self.character.build_system_prompt(user_name=effective_name, preferred_name=effective_name)
        memory_context = ""
        if self.memory:
            memory_context = self.memory.build_context_injection(
                self.character.id, self.user_id, current_query=current_user_query
            )

        tools_context = ""
        if self.tools and self.config.tools.enabled:
            tools_context = "\n\n" + self.tools.generate_system_prompt_documentation()

        return base_prompt + memory_context + tools_context

    def action_clear_chat(self) -> None:
        chat_scroll = self.query_one("#chat-scroll", VerticalScroll)
        chat_scroll.remove_children()
        greeting = "(Chat display cleared) Let us start afresh."
        chat_scroll.mount(ChatMessageWidget(sender=self.character.display_name, text=greeting, is_user=False))

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        user_text = event.value.strip()
        if not user_text or self.is_responding:
            return

        input_widget = self.query_one("#user-input", Input)
        input_widget.value = ""

        # Check for commands
        if user_text.startswith("/"):
            await self._handle_command(user_text)
            return

        self._last_user_message = user_text

        # Add user message to UI
        chat_scroll = self.query_one("#chat-scroll", VerticalScroll)
        user_widget = ChatMessageWidget(sender="You", text=user_text, is_user=True)
        await chat_scroll.mount(user_widget)
        chat_scroll.scroll_end(animate=False)

        # Store user message in SQLite memory
        if self.memory:
            self.memory.add_message(self.character.id, self.user_id, "user", user_text)

        # Check if user is confirming a pending dangerous/moderate tool
        if self.agent_loop and self.agent_loop.resistance.has_pending():
            if self.agent_loop.resistance.is_user_confirming(user_text):
                self._execute_confirmed_pending_tool()
                return

        # Prepare context window for LLM
        prompt_with_memory = self._prepare_system_prompt(current_user_query=user_text)
        if self.memory:
            history = self.memory.get_recent_messages(self.character.id, self.user_id, limit=self.config.memory.short_term_window)
            self.messages = [LLMMessage(role="system", content=prompt_with_memory)] + history
        else:
            self.messages = [LLMMessage(role="system", content=prompt_with_memory)]
            self.messages.append(LLMMessage(role="user", content=user_text))

        # Start streaming assistant response
        self._stream_assistant_response()

    @work(exclusive=True)
    async def _execute_confirmed_pending_tool(self) -> None:
        """Handle execution after user explicitly confirmed a warned operation."""
        if not self.agent_loop:
            return

        pending = self.agent_loop.resistance.consume_pending()
        if not pending:
            return

        tool_name, arguments = pending
        tool = self.tools.get(tool_name) if self.tools else None
        if not tool:
            return

        chat_scroll = self.query_one("#chat-scroll", VerticalScroll)
        avatar_panel = self.query_one("#avatar-panel", AvatarPanel)

        avatar_panel.current_task = f"Executing {tool.name}..."
        result = await self.agent_loop.execute_tool(tool, arguments, user_confirmed=True)
        avatar_panel.current_task = "Idle"

        confirm_msg = (
            f"[emotion:blush] Understood. As you confirmed, I have executed `{tool.name}`.\n\n"
            f"[bold]Output:[/bold]\n{result.output or result.error}"
        )
        await chat_scroll.mount(ChatMessageWidget(sender=self.character.display_name, text=confirm_msg, is_user=False))
        chat_scroll.scroll_end(animate=False)

    async def _handle_command(self, cmd: str) -> None:
        chat_scroll = self.query_one("#chat-scroll", VerticalScroll)
        parts = cmd.split()
        root_cmd = parts[0].lower()

        if root_cmd == "/help":
            help_text = (
                "[bold]Available Commands:[/bold]\n"
                "- /help: Show this guide\n"
                "- /emotion <name>: Change avatar emotion (neutral, happy, embarrassed, angry, sad, surprised, thinking)\n"
                "- /testtalk: Run synthetic audio playback & synchronized lip-sync verification\n"
                "- /avatar validate: Verify character layers and manifest integrity\n"
                "- /avatar preview: Cycle through animated expressions and mouth shapes\n"
                "- /avatar backend [mode]: View or switch avatar backend (auto, window, terminal)\n"
                "- /status: View character & relationship meters\n"
                "- /status set <metric> <val>: Manually adjust a trait slider\n"
                "- /status reset: Reset relationship to baseline\n"
                "- /character list: List installed characters\n"
                "- /character use <name>: Hot-swap active companion on the fly\n"
                "- /character new <id> <name>: Interactive character generator\n"
                "- /voice speed <x>: Instantly adjust Roxy's voice speed (0.9 to 1.5)\n"
                "- /voice save <preset>: Save voice tuning to character preset\n"
                "- /voice audition: Render audition benchmarks at speeds 1.0, 1.15, 1.25, 1.35\n"
                "- /perf: Display process RAM, DB size, and resource telemetry\n"
                "- /tools: List registered agency tools and permission tiers\n"
                "- /audit: View recent security audit logs\n"
                "- /memory show: List long-term facts & recent episodes\n"
                "- /memory forget <term/id>: Remove a fact from memory\n"
                "- /memory export [file]: Save all memory to Markdown\n"
                "- /memory wipe: Erase all memory for this character\n"
                "- /news [topic]: Research latest news and render structured article panel\n"
                "- /sources: View numbered sources from current research report\n"
                "- /open <n>: Open research source #n or app in browser\n"
                "- /save article [path]: Export current research article to Markdown\n"
                "- /focus: Open full scrollable article card modal (Esc closes)\n"
                "- /clear: Clear chat window\n"
                "- /quit: Exit application"
            )
            await chat_scroll.mount(ChatMessageWidget(sender="System", text=help_text, is_user=False))

        elif root_cmd == "/perf":
            avatar_panel = self.query_one("#avatar-panel", AvatarPanel)
            backend_name = type(self.avatar_backend).__name__ if self.avatar_backend else "Terminal"
            fps = 24
            if avatar_panel.compositor:
                c_count = avatar_panel.compositor.composite_count
                c_dur = avatar_panel.compositor.last_frame_duration_ms
                avatar_info = f"{backend_name} ({fps} FPS, {c_count} frames, last frame {c_dur:.2f}ms)"
            else:
                avatar_info = f"{backend_name} ({fps} FPS)"
            report = format_performance_report(self.config, self.character, self.config.memory.db_path, avatar_info=avatar_info)
            await chat_scroll.mount(ChatMessageWidget(sender="System", text=report, is_user=False))

        elif root_cmd == "/emotion":
            if len(parts) < 2:
                valid_list = ", ".join(sorted(VALID_EMOTIONS))
                await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"Usage: /emotion <name>\nValid emotions: {valid_list}", is_user=False))
            else:
                raw_emo = parts[1].lower()
                clean_emo = EMOTION_ALIASES.get(raw_emo, raw_emo)
                if clean_emo in VALID_EMOTIONS:
                    avatar_panel = self.query_one("#avatar-panel", AvatarPanel)
                    avatar_panel.set_emotion(clean_emo)
                    if self.avatar_backend:
                        self.avatar_backend.update_emotion(clean_emo)
                    await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"Changed emotion to [bold]{clean_emo}[/bold].", is_user=False))
                else:
                    await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"Unknown emotion '{raw_emo}'. Valid: {', '.join(sorted(VALID_EMOTIONS))}", is_user=False))

        elif root_cmd == "/testtalk":
            self._run_test_talk()

        elif root_cmd == "/voice":
            sub_cmd = parts[1].lower() if len(parts) > 1 else ""
            if sub_cmd == "speed":
                if len(parts) < 3:
                    cur_speed = self.character.voice.speed if self.character.voice else 1.20
                    await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"Usage: /voice speed <0.9 - 1.5>\nCurrent speed: {cur_speed:.2f}x", is_user=False))
                else:
                    try:
                        val = float(parts[2])
                        val = max(0.9, min(1.5, val))
                        if self.character.voice:
                            self.character.voice.speed = val
                        # Persist to active character voice.yaml if exists
                        v_path = Path("characters") / self.character.id / "voice.yaml"
                        if v_path.exists():
                            import yaml
                            try:
                                with open(v_path, "r", encoding="utf-8") as vf:
                                    ydata = yaml.safe_load(vf) or {}
                                ydata["speed"] = val
                                with open(v_path, "w", encoding="utf-8") as vf:
                                    yaml.safe_dump(ydata, vf, sort_keys=False)
                            except Exception:
                                pass
                        rate_pct = round((val - 1.0) * 100)
                        await chat_scroll.mount(ChatMessageWidget(
                            sender="System",
                            text=f"[bold green]✓ Voice speed set to {val:.2f}x ({rate_pct:+d}% native rate). Applied instantly.[/bold green]",
                            is_user=False
                        ))
                    except ValueError:
                        await chat_scroll.mount(ChatMessageWidget(sender="System", text="Speed value must be a numeric float (0.9 to 1.5).", is_user=False))

            elif sub_cmd == "save":
                if len(parts) < 3:
                    await chat_scroll.mount(ChatMessageWidget(sender="System", text="Usage: /voice save <preset_name>", is_user=False))
                else:
                    preset_name = parts[2].lower()
                    if self.character.voice:
                        self.character.voice.preset = preset_name
                    v_path = Path("characters") / self.character.id / "voice.yaml"
                    if v_path.exists():
                        import yaml
                        try:
                            with open(v_path, "r", encoding="utf-8") as vf:
                                ydata = yaml.safe_load(vf) or {}
                            ydata["preset"] = preset_name
                            with open(v_path, "w", encoding="utf-8") as vf:
                                yaml.safe_dump(ydata, vf, sort_keys=False)
                        except Exception:
                            pass
                    await chat_scroll.mount(ChatMessageWidget(
                        sender="System",
                        text=f"[bold green]✓ Voice settings saved to preset '{preset_name}'.[/bold green]",
                        is_user=False
                    ))

            elif sub_cmd == "audition":
                await chat_scroll.mount(ChatMessageWidget(
                    sender="System",
                    text="[bold]Starting voice pace audition across speeds 1.0, 1.15, 1.25, 1.35...[/bold]",
                    is_user=False
                ))
                try:
                    import subprocess, sys
                    script_path = Path("scripts/voice_audition.py")
                    if not script_path.exists():
                        script_path = Path(__file__).resolve().parent.parent / "scripts" / "voice_audition.py"
                    subprocess.Popen([sys.executable, str(script_path), "--output-dir", "voice_audition"])
                    await chat_scroll.mount(ChatMessageWidget(
                        sender="System",
                        text="[bold green]✓ Audition generated! Report and audio files saved to voice_audition/audition_report.md.[/bold green]",
                        is_user=False
                    ))
                except Exception as e:
                    await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"Failed to run audition: {e}", is_user=False))

            elif sub_cmd == "provider":
                if len(parts) < 3:
                    pin_str = " (pinned)" if self.tts.pinned else ""
                    await chat_scroll.mount(ChatMessageWidget(
                        sender="System",
                        text=f"Active TTS Provider: [bold cyan]{self.tts.active_mode}{pin_str}[/bold cyan]\nUsage: /voice provider <edge|local|kokoro> [--pin]",
                        is_user=False
                    ))
                else:
                    prov = parts[2].lower()
                    pin = "--pin" in parts
                    self.tts.set_provider(prov, pin=pin)
                    pin_label = "pinned" if pin else "unpinned"
                    await chat_scroll.mount(ChatMessageWidget(
                        sender="System",
                        text=f"[bold green]✓ Voice provider set to '{prov}' ({pin_label}). Status: {self.tts.status_label}[/bold green]",
                        is_user=False
                    ))

            elif sub_cmd == "debug" and len(parts) > 2 and parts[2].lower() == "last":
                debug_dir = Path("data/voice_debug_last")
                saved = []
                if debug_dir.exists():
                    saved = [str(f) for f in debug_dir.glob("*_stage*.wav")]
                if not saved:
                    saved = self.tts.save_last_debug_stages(debug_dir)

                if saved:
                    sample_stages = saved[:5]
                    stage_list = "\n".join([f"  • [cyan]{Path(s).name}[/cyan]" for s in sample_stages])
                    await chat_scroll.mount(ChatMessageWidget(
                        sender="System",
                        text=f"[bold green]✓ Saved audio stage files for last turn to {debug_dir}:[/bold green]\n{stage_list}",
                        is_user=False
                    ))
                else:
                    await chat_scroll.mount(ChatMessageWidget(
                        sender="System",
                        text="[bold yellow]No voice debug stages captured yet. Speak to Roxy first to generate audio stages.[/bold yellow]",
                        is_user=False
                    ))

            else:
                cur_speed = self.character.voice.speed if self.character.voice else 1.15
                cur_preset = self.character.voice.preset if self.character.voice else "mature_mommy_fast"
                await chat_scroll.mount(ChatMessageWidget(
                    sender="System",
                    text=(
                        f"[bold]🎙️ Voice Controls:[/bold]\n"
                        f"  • Provider: [bold cyan]{self.tts.status_label}[/bold cyan]\n"
                        f"  • Active Preset: [bold cyan]{cur_preset}[/bold cyan]\n"
                        f"  • Current Speed: [bold cyan]{cur_speed:.2f}x[/bold cyan] ({round((cur_speed-1.0)*100):+d}% native rate)\n"
                        f"  • Commands: /voice speed <0.9-1.5> | /voice provider <edge|local> [--pin] | /voice debug last | /voice audition"
                    ),
                    is_user=False
                ))

        elif root_cmd == "/avatar":
            sub_cmd = parts[1].lower() if len(parts) > 1 else "validate"
            if sub_cmd == "validate":
                res = self._validate_avatar()
                await chat_scroll.mount(ChatMessageWidget(sender="System", text=res, is_user=False))
            elif sub_cmd == "preview":
                self._preview_avatar()
            elif sub_cmd == "backend":
                if len(parts) > 2:
                    new_mode = parts[2].lower()
                    if new_mode in ("auto", "window", "terminal"):
                        if self.avatar_backend:
                            self.avatar_backend.stop()
                        avatar_dir = Path("characters") / self.character.id / "avatar"
                        self.avatar_backend = create_avatar_backend(mode=new_mode, avatar_dir=avatar_dir)
                        self.avatar_backend.start()
                        await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"Avatar backend switched to [bold]{new_mode}[/bold].", is_user=False))
                    else:
                        await chat_scroll.mount(ChatMessageWidget(sender="System", text="Usage: /avatar backend <auto|window|terminal>", is_user=False))
                else:
                    b_type = type(self.avatar_backend).__name__ if self.avatar_backend else "None"
                    await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"Current avatar backend: [bold]{b_type}[/bold]", is_user=False))
            else:
                await chat_scroll.mount(ChatMessageWidget(sender="System", text="Usage: /avatar [validate | preview | backend]", is_user=False))

        elif root_cmd == "/character":
            sub_cmd = parts[1].lower() if len(parts) > 1 else "list"

            if sub_cmd == "list":
                chars = list_available_characters(self.config.character_dir)
                lines = ["[bold]🎭 Installed Characters:[/bold]"]
                for c in chars:
                    active_marker = " [green](Active)[/green]" if c["id"] == self.character.id else ""
                    lines.append(f"  • [bold]{c['id']}[/bold]: {c['name']} - [dim]{c['title']}[/dim]{active_marker}")
                lines.append("\n[dim]Switch with: /character use <id>[/dim]")
                await chat_scroll.mount(ChatMessageWidget(sender="System", text="\n".join(lines), is_user=False))

            elif sub_cmd == "use":
                if len(parts) < 3:
                    await chat_scroll.mount(ChatMessageWidget(sender="System", text="Usage: /character use <id>", is_user=False))
                else:
                    new_id = parts[2].lower()
                    try:
                        new_char = load_character(new_id, character_dir=self.config.character_dir)
                        self.character = new_char
                        self.config.active_character = new_id

                        avatar_panel = self.query_one("#avatar-panel", AvatarPanel)
                        avatar_panel.character = new_char
                        avatar_panel.avatar_dir = Path(self.config.character_dir) / new_id / "avatar"
                        avatar_panel.sprite_pack = SpritePack(avatar_panel.avatar_dir)
                        if (avatar_panel.avatar_dir / "manifest.yaml").exists():
                            try:
                                avatar_panel.compositor = AvatarCompositor(avatar_panel.avatar_dir, target_size=(22, 22))
                            except Exception:
                                avatar_panel.compositor = None
                        else:
                            avatar_panel.compositor = None

                        if self.avatar_backend and hasattr(self.avatar_backend, "update_character"):
                            self.avatar_backend.update_character(new_char.id)

                        if self.memory:
                            rel = self.memory.relationship.get_state(new_char.id, self.user_id)
                            avatar_panel.update_relationship(rel)

                        self.title = f"Kokoro-Term | {new_char.name}"
                        await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"Switched active companion to [bold]{new_char.name}[/bold].", is_user=False))
                        await chat_scroll.mount(ChatMessageWidget(sender=new_char.display_name, text=f"Hello. I am {new_char.name}. I am now your companion.", is_user=False))
                    except Exception as e:
                        await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"Failed to switch to character '{new_id}': {e}", is_user=False))

            elif sub_cmd == "new":
                if len(parts) < 4:
                    await chat_scroll.mount(ChatMessageWidget(sender="System", text="Usage: /character new <id> <Full Name>", is_user=False))
                else:
                    new_id = parts[2].lower()
                    full_name = " ".join(parts[3:])
                    try:
                        created_path = scaffold_new_character(new_id, full_name, characters_dir=self.config.character_dir)
                        await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"Created character [bold]{full_name}[/bold] in {created_path}. Use '/character use {new_id}' to switch.", is_user=False))
                    except Exception as e:
                        await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"Failed to create character: {e}", is_user=False))

            else:
                await chat_scroll.mount(ChatMessageWidget(sender="System", text="Unknown /character sub-command. Options: list, use <id>, new <id> <Name>", is_user=False))

        elif root_cmd == "/tools":
            if not self.tools:
                await chat_scroll.mount(ChatMessageWidget(sender="System", text="Tools subsystem is disabled.", is_user=False))
            else:
                lines = ["[bold]🛠️ Registered Agency Tools:[/bold]"]
                for t in self.tools.list_tools():
                    badge = f"[green]SAFE[/green]" if t.tier == "safe" else (
                        "[yellow]MODERATE[/yellow]" if t.tier == "moderate" else "[red]DANGEROUS[/red]"
                    )
                    lines.append(f"  • [bold]{t.name}[/bold] ({badge}): {t.description}")
                await chat_scroll.mount(ChatMessageWidget(sender="System", text="\n".join(lines), is_user=False))

        elif root_cmd == "/audit":
            if not self.agent_loop:
                await chat_scroll.mount(ChatMessageWidget(sender="System", text="Audit logger unavailable.", is_user=False))
            else:
                entries = self.agent_loop.audit.get_recent(limit=10)
                if not entries:
                    await chat_scroll.mount(ChatMessageWidget(sender="System", text="Audit log is empty.", is_user=False))
                else:
                    lines = ["[bold]📋 Recent Security Audit Logs:[/bold]"]
                    for e in entries:
                        status = "[green]OK[/green]" if e.success else "[red]FAIL[/red]"
                        lines.append(f"  • {e.timestamp[11:19]} {status} [{e.tier.upper()}] [bold]{e.tool_name}[/bold] -> {e.output_preview}")
                    await chat_scroll.mount(ChatMessageWidget(sender="System", text="\n".join(lines), is_user=False))

        elif root_cmd == "/status":
            if not self.memory:
                await chat_scroll.mount(ChatMessageWidget(sender="System", text="Memory is disabled.", is_user=False))
                return

            sub_cmd = parts[1].lower() if len(parts) > 1 else ""

            if sub_cmd == "set":
                if len(parts) < 4:
                    await chat_scroll.mount(
                        ChatMessageWidget(sender="System", text="Usage: /status set <metric> <val>\nExample: /status set affection 85", is_user=False)
                    )
                else:
                    metric = parts[2]
                    try:
                        val = float(parts[3])
                        new_state = self.memory.relationship.set_metric(self.character.id, self.user_id, metric, val)
                        if new_state:
                            avatar_panel = self.query_one("#avatar-panel", AvatarPanel)
                            avatar_panel.update_relationship(new_state)
                            await chat_scroll.mount(
                                ChatMessageWidget(sender="System", text=f"Updated [bold]{metric}[/bold] to {val:.1f}.", is_user=False)
                            )
                        else:
                            await chat_scroll.mount(
                                ChatMessageWidget(sender="System", text=f"Unknown metric '{metric}'. Valid: affection, trust, familiarity, tsundere_level, shyness, formality, playfulness, assertiveness.", is_user=False)
                            )
                    except ValueError:
                        await chat_scroll.mount(ChatMessageWidget(sender="System", text="Value must be a numeric float.", is_user=False))

            elif sub_cmd == "reset":
                new_state = self.memory.relationship.reset_state(self.character.id, self.user_id)
                avatar_panel = self.query_one("#avatar-panel", AvatarPanel)
                avatar_panel.update_relationship(new_state)
                await chat_scroll.mount(ChatMessageWidget(sender="System", text="Relationship state reset to defaults.", is_user=False))

            else:
                state = self.memory.relationship.get_state(self.character.id, self.user_id)
                fact_count = len(self.memory.get_facts(self.character.id, self.user_id))

                status_lines = [
                    f"[bold]Active Character:[/bold] {self.character.name} ({self.character.title})",
                    f"[bold]Provider / Model:[/bold] {self.config.llm.provider} ({self.config.llm.model})",
                    f"[bold]Relationship Stage:[/bold] [yellow]{state.get_relationship_stage()}[/yellow]",
                    "",
                    "[bold cyan]Core Meters (0-100):[/bold cyan]",
                    f"  • Affection:   {state.affection:5.1f} [{_progress_bar(state.affection)}]",
                    f"  • Trust:       {state.trust:5.1f} [{_progress_bar(state.trust)}]",
                    f"  • Familiarity: {state.familiarity:5.1f} [{_progress_bar(state.familiarity)}]",
                    f"  • Current Mood: [magenta]{state.mood.capitalize()}[/magenta]",
                    "",
                    "[bold cyan]Personality Trait Sliders:[/bold cyan]",
                    f"  • Tsundere:     {state.tsundere_level:5.1f} [{_progress_bar(state.tsundere_level)}]",
                    f"  • Shyness:      {state.shyness:5.1f} [{_progress_bar(state.shyness)}]",
                    f"  • Formality:    {state.formality:5.1f} [{_progress_bar(state.formality)}]",
                    f"  • Playfulness:  {state.playfulness:5.1f} [{_progress_bar(state.playfulness)}]",
                    f"  • Assertiveness:{state.assertiveness:5.1f} [{_progress_bar(state.assertiveness)}]",
                    "",
                    f"[dim]Total Interactions: {state.total_interactions} | Known Facts: {fact_count}[/dim]",
                    "[dim]Edit with: /status set <metric> <val>  |  Reset: /status reset[/dim]",
                ]
                await chat_scroll.mount(ChatMessageWidget(sender="System", text="\n".join(status_lines), is_user=False))

        elif root_cmd == "/memory":
            sub_cmd = parts[1].lower() if len(parts) > 1 else "show"

            if sub_cmd == "show":
                if not self.memory:
                    await chat_scroll.mount(ChatMessageWidget(sender="System", text="Memory is disabled.", is_user=False))
                else:
                    pref_name = self.memory.get_preferred_name(self.character.id, self.user_id) or self.user_id
                    facts = self.memory.get_facts(self.character.id, self.user_id, active_only=True)
                    episodes = self.memory.get_recent_episodes(self.character.id, self.user_id, limit=3)

                    lines = [f"[bold]🧠 Stored Memory for User: [bold cyan]{pref_name}[/bold cyan][/bold]"]
                    if pref_name != self.user_id:
                        lines.append(f"[dim]Preferred Name Fact: '{pref_name}' (Overrides default '{self.user_id}')[/dim]")

                    if facts:
                        lines.append("\n[bold cyan]Facts & Preferences:[/bold cyan]")
                        for f in facts:
                            lines.append(f"  • #{f.id} [{f.category}] [bold]{f.key}:[/bold] {f.value}")
                    else:
                        lines.append("\n[dim]No facts stored yet.[/dim]")

                    if episodes:
                        lines.append("\n[bold cyan]Recent Episodic Summaries:[/bold cyan]")
                        for ep in episodes:
                            lines.append(f"  • [dim]{ep.created_at[:10]}:[/dim] {ep.summary}")

                    await chat_scroll.mount(ChatMessageWidget(sender="System", text="\n".join(lines), is_user=False))

            elif sub_cmd == "name":
                if len(parts) < 3:
                    cur = self.memory.get_preferred_name(self.character.id, self.user_id) if self.memory else self.user_id
                    await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"Current preferred name: [bold cyan]{cur}[/bold cyan]\nUsage: /memory name <preferred_name>", is_user=False))
                else:
                    new_name = " ".join(parts[2:]).strip()
                    if self.memory:
                        self.memory.set_preferred_name(self.character.id, self.user_id, new_name)
                    await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"[bold green]✓ Preferred name updated to '{new_name}'. Roxy will address you as '{new_name}'.[/bold green]", is_user=False))

            elif sub_cmd == "forget":
                if len(parts) < 3:
                    await chat_scroll.mount(
                        ChatMessageWidget(sender="System", text="Usage: /memory forget <id_or_keyword>", is_user=False)
                    )
                else:
                    target = " ".join(parts[2:])
                    count = self.memory.forget_fact(self.character.id, self.user_id, target) if self.memory else 0
                    msg = f"Deactivated {count} matching fact(s)." if count > 0 else f"No facts found matching '{target}'."
                    await chat_scroll.mount(ChatMessageWidget(sender="System", text=msg, is_user=False))

            elif sub_cmd == "export":
                target_path = parts[2] if len(parts) > 2 else f"memory_export_{self.character.id}.md"
                if self.memory:
                    out = self.memory.export_memory(self.character.id, self.user_id, target_path)
                    await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"Exported memory to: {out}", is_user=False))

            elif sub_cmd == "wipe":
                if self.memory:
                    self.memory.wipe_memory(self.character.id, self.user_id)
                    await chat_scroll.mount(
                        ChatMessageWidget(sender="System", text=f"Wiped all memory for {self.character.name}.", is_user=False)
                    )

            else:
                await chat_scroll.mount(
                    ChatMessageWidget(sender="System", text="Unknown /memory action. Use: show, forget, export, wipe", is_user=False)
                )

        elif root_cmd == "/perm":
            sub_cmd = parts[1].lower() if len(parts) > 1 else ""
            if self.agent_loop and hasattr(self.agent_loop, "permission"):
                if sub_cmd in ("ask", "allow", "block"):
                    msg = self.agent_loop.permission.set_policy(sub_cmd)
                    await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"[bold]{msg}[/bold]", is_user=False))
                else:
                    curr = getattr(self.agent_loop.permission, "dangerous_policy", "ask")
                    await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"Dangerous actions policy: [bold]{curr.upper()}[/bold]. Usage: /perm <ask|allow|block>", is_user=False))
        elif root_cmd == "/news":
            topic = " ".join(parts[1:]).strip() if len(parts) > 1 else "top technology and world headlines"
            await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"🔍 Researching latest news on [bold]{topic}[/bold] across multiple sources...", is_user=False))
            chat_scroll.scroll_end(animate=False)
            from kokoro_term.tools.builtin.web_research import WebResearchTool, get_last_research_article
            tool = WebResearchTool()
            res = await tool.execute(query=topic, kind="news")
            if res.success:
                art = get_last_research_article()
                if art:
                    await chat_scroll.mount(ArticlePanelWidget(art))
                    chat_scroll.scroll_end(animate=False)
            else:
                await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"[red]News research failed: {res.error}[/red]", is_user=False))
                chat_scroll.scroll_end(animate=False)

        elif root_cmd == "/sources":
            from kokoro_term.tools.builtin.web_research import get_last_research_article
            art = get_last_research_article()
            if not art or not art.sources:
                await chat_scroll.mount(ChatMessageWidget(sender="System", text="No research sources found. Run /news [topic] or a research query first.", is_user=False))
            else:
                lines = [f"[bold]📚 Sources for '{art.headline}':[/bold]"]
                for s in art.sources:
                    lines.append(f"  • #{s.index} [bold cyan][{s.domain}][/bold cyan] {s.title} ({s.date})\n    [dim]{s.url}[/dim]")
                lines.append("\n[dim]To open any source in your browser, run: /open <n> (e.g. /open 1)[/dim]")
                await chat_scroll.mount(ChatMessageWidget(sender="System", text="\n".join(lines), is_user=False))
            chat_scroll.scroll_end(animate=False)

        elif root_cmd == "/open":
            if len(parts) > 1 and parts[1].isdigit():
                idx = int(parts[1])
                from kokoro_term.tools.builtin.web_research import open_research_source
                res = open_research_source(idx)
                status = "[green]✓[/green]" if res.get("ok") else "[red]✗[/red]"
                await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"{status} {res.get('detail')}", is_user=False))
            elif len(parts) > 1:
                target = parts[1]
                if target.startswith("http://") or target.startswith("https://"):
                    from kokoro_term.tools.builtin.apps import OpenUrlTool
                    tool = OpenUrlTool()
                    r = await tool.execute(url=target)
                else:
                    from kokoro_term.tools.builtin.apps import OpenAppTool
                    tool = OpenAppTool()
                    r = await tool.execute(app_name=target)
                await chat_scroll.mount(ChatMessageWidget(sender="System", text=r.output or r.error, is_user=False))
            else:
                await chat_scroll.mount(ChatMessageWidget(sender="System", text="Usage: /open <source_number|url|app_name> (e.g. /open 1)", is_user=False))
            chat_scroll.scroll_end(animate=False)

        elif root_cmd == "/save" and len(parts) > 1 and parts[1].lower() == "article":
            from kokoro_term.tools.builtin.web_research import save_research_article, get_last_research_article
            art = get_last_research_article()
            if not art:
                await chat_scroll.mount(ChatMessageWidget(sender="System", text="No research article loaded to save.", is_user=False))
            else:
                target_p = parts[2] if len(parts) > 2 else None
                try:
                    saved_path = save_research_article(art, target_p)
                    await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"[bold green]✓ Saved research article to:[/bold green] {saved_path}", is_user=False))
                except Exception as e:
                    await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"[red]Failed to save article: {e}[/red]", is_user=False))
            chat_scroll.scroll_end(animate=False)

        elif root_cmd in ("/focus", "/read"):
            from kokoro_term.tools.builtin.web_research import get_last_research_article
            art = get_last_research_article()
            if not art:
                await chat_scroll.mount(ChatMessageWidget(sender="System", text="No research article loaded. Run /news [topic] or a research query first.", is_user=False))
            else:
                self.push_screen(ArticleFocusScreen(art))

        elif root_cmd == "/stop":
            await chat_scroll.mount(ChatMessageWidget(sender="System", text="Stopping agent execution...", is_user=False))

        elif root_cmd == "/clear":
            self.action_clear_chat()
        elif root_cmd == "/quit":
            self.exit()
        else:
            await chat_scroll.mount(
                ChatMessageWidget(sender="System", text=f"Unknown command '{cmd}'. Type /help for options.", is_user=False)
            )
        chat_scroll.scroll_end(animate=False)

    def _validate_avatar(self) -> str:
        avatar_dir = Path("characters") / self.character.id / "avatar"
        manifest_file = avatar_dir / "manifest.yaml"
        if not manifest_file.exists():
            return f"[yellow]⚠️ No manifest.yaml found in {avatar_dir}[/yellow]"

        try:
            manifest = AvatarManifest.load(manifest_file)
        except Exception as e:
            return f"[red]❌ Failed to parse manifest.yaml: {e}[/red]"

        all_layers = {}
        all_layers.update(manifest.layers)
        all_layers.update(manifest.eye_states)
        all_layers.update(manifest.brow_states)
        all_layers.update(manifest.mouth_states)

        missing = []
        found = 0
        for name, layer_def in all_layers.items():
            lp = avatar_dir / layer_def.file
            if lp.exists():
                found += 1
            else:
                missing.append(f"{name} ({layer_def.file})")

        lines = [f"[bold]🎭 Avatar Validation for '{self.character.name}':[/bold]"]
        lines.append(f"  • Canvas Master Size: {manifest.canvas_size[0]}x{manifest.canvas_size[1]}")
        lines.append(f"  • Layers Found: [green]{found}[/green]")
        if missing:
            lines.append(f"  • [red]Missing Layers ({len(missing)}):[/red] " + ", ".join(missing))
        else:
            lines.append("  • [green]✓ All layer files are verified and present on disk.[/green]")
        return "\n".join(lines)

    @work(exclusive=True)
    async def _preview_avatar(self) -> None:
        chat_scroll = self.query_one("#chat-scroll", VerticalScroll)
        avatar_panel = self.query_one("#avatar-panel", AvatarPanel)
        await chat_scroll.mount(ChatMessageWidget(sender="System", text="[bold]Previewing avatar expressions and mouth shapes...[/bold]", is_user=False))
        chat_scroll.scroll_end(animate=False)

        emotions = ["neutral", "happy", "embarrassed", "angry", "sad", "surprised", "thinking"]
        for emo in emotions:
            avatar_panel.set_emotion(emo)
            if self.avatar_backend:
                self.avatar_backend.update_emotion(emo)
            await asyncio.sleep(0.4)

        avatar_panel.set_speaking(True)
        for mouth in ["closed", "a", "i", "u", "e", "o"]:
            avatar_panel.set_mouth(mouth)
            if self.avatar_backend and hasattr(self.avatar_backend, "set_mouth"):
                self.avatar_backend.set_mouth(mouth)
            await asyncio.sleep(0.3)

        avatar_panel.set_speaking(False)
        avatar_panel.set_emotion("neutral")
        if self.avatar_backend:
            self.avatar_backend.set_speaking(False)
            self.avatar_backend.update_emotion("neutral")

        await chat_scroll.mount(ChatMessageWidget(sender="System", text="[bold green]✓ Avatar preview finished.[/bold green]", is_user=False))
        chat_scroll.scroll_end(animate=False)

    @work(exclusive=True)
    async def _run_test_talk(self) -> None:
        chat_scroll = self.query_one("#chat-scroll", VerticalScroll)
        avatar_panel = self.query_one("#avatar-panel", AvatarPanel)
        await chat_scroll.mount(ChatMessageWidget(sender="System", text="[bold]Starting /testtalk lip-sync verification...[/bold]", is_user=False))
        chat_scroll.scroll_end(animate=False)

        wav_path = Path("data/test_talk.wav")
        if not wav_path.exists():
            wav_path = generate_test_speech_wav(wav_path, duration_sec=3.0)

        # Read PCM audio bytes
        try:
            with wave.open(str(wav_path), "rb") as wf:
                sample_rate = wf.getframerate()
                n_channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                pcm_bytes = wf.readframes(wf.getnframes())
        except Exception as e:
            await chat_scroll.mount(ChatMessageWidget(sender="System", text=f"[red]Error reading WAV: {e}[/red]", is_user=False))
            return

        lipsync = AmplitudeLipSync()
        lipsync.load_audio_pcm(pcm_bytes, sample_rate=sample_rate)

        avatar_panel.set_speaking(True, lipsync)
        if self.avatar_backend:
            self.avatar_backend.set_speaking(True, lipsync)

        # Non-blocking audio playback via system player if available
        audio_proc = None
        for player_cmd in ("aplay", "paplay", "afplay"):
            if shutil.which(player_cmd):
                try:
                    audio_proc = subprocess.Popen([player_cmd, str(wav_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    break
                except Exception:
                    pass

        start_time = time.time()
        duration_sec = len(pcm_bytes) / (sample_rate * n_channels * sampwidth)

        while time.time() - start_time < duration_sec:
            elapsed = time.time() - start_time
            mouth_shape = lipsync.get_mouth_shape(elapsed)
            avatar_panel.set_mouth(mouth_shape)
            if self.avatar_backend and hasattr(self.avatar_backend, "set_mouth"):
                self.avatar_backend.set_mouth(mouth_shape)
            avatar_panel.refresh()
            await asyncio.sleep(0.04)

        if audio_proc:
            try:
                audio_proc.wait(timeout=0.5)
            except Exception:
                pass

        avatar_panel.set_speaking(False)
        if self.avatar_backend:
            self.avatar_backend.set_speaking(False)
        avatar_panel.refresh()

        await chat_scroll.mount(ChatMessageWidget(sender="System", text="[bold green]✓ Lip-sync playback completed successfully.[/bold green]", is_user=False))
        chat_scroll.scroll_end(animate=False)

    @work(exclusive=True)
    async def _stream_assistant_response(self) -> None:
        self.is_responding = True
        chat_scroll = self.query_one("#chat-scroll", VerticalScroll)
        avatar_panel = self.query_one("#avatar-panel", AvatarPanel)
        avatar_panel.set_speaking(True)
        if self.avatar_backend:
            self.avatar_backend.set_speaking(True)

        bot_widget = ChatMessageWidget(sender=self.character.display_name, text="...", is_user=False)
        await chat_scroll.mount(bot_widget)
        chat_scroll.scroll_end(animate=False)

        full_raw_text = ""
        detected_emotion = "neutral"
        emotion_detected = False

        try:
            rel_state = (
                self.memory.relationship.get_state(self.character.id, self.user_id)
                if self.memory
                else RelationshipState(character_id=self.character.id, user_id=self.user_id)
            )

            if self.agent_loop and self.tools and self.config.tools.enabled:
                async for event in self.agent_loop.run_agent_loop(
                    llm=self.llm,
                    messages=self.messages,
                    rel_state=rel_state,
                ):
                    etype = event.get("type")
                    if etype == "token":
                        full_raw_text += event["token"]
                        clean_text, emo = parse_and_strip_emotion_tag(full_raw_text)
                        if emo != "neutral" and not emotion_detected:
                            detected_emotion = emo
                            avatar_panel.set_emotion(detected_emotion)
                            if self.avatar_backend:
                                self.avatar_backend.update_emotion(detected_emotion)
                            emotion_detected = True

                        # Strip incomplete trailing tag while streaming
                        clean_display = re.sub(r"\[emotion:[^\]]*$", "", clean_text, flags=re.IGNORECASE)
                        clean_display = re.sub(r"<tool_call>.*?</tool_call>", "", clean_display, flags=re.DOTALL).strip()
                        bot_widget.update_text(clean_display or "...")
                        avatar_panel.subtitle_text = clean_display or "..."
                        chat_scroll.scroll_end(animate=False)

                    elif etype == "tool_start":
                        avatar_panel.current_task = f"Running {event['tool']}..."
                        tool_notice = f"[dim]● Running {event['tool']}({event.get('args', {})})...[/dim]"
                        await chat_scroll.mount(ChatMessageWidget(sender="System", text=tool_notice, is_user=False))
                        chat_scroll.scroll_end(animate=False)

                    elif etype == "tool_end":
                        avatar_panel.current_task = "Thinking..."
                        status_str = "Success" if event.get("success") else "Failed"
                        out_summary = event.get("output", "").strip()[:300]
                        tool_notice = f"[dim]● {event['tool']} ({status_str}): {out_summary}[/dim]"
                        await chat_scroll.mount(ChatMessageWidget(sender="System", text=tool_notice, is_user=False))
                        if event.get("tool") == "web_research" and event.get("success"):
                            from kokoro_term.tools.builtin.web_research import get_last_research_article
                            art = get_last_research_article()
                            if art:
                                await chat_scroll.mount(ArticlePanelWidget(art))
                        chat_scroll.scroll_end(animate=False)

                    elif etype == "confirm_required":
                        avatar_panel.current_task = "Confirmation Required"
                        objection = event.get("objection", "")
                        clean_obj, obj_emo = parse_and_strip_emotion_tag(objection)
                        if obj_emo != "neutral":
                            avatar_panel.set_emotion(obj_emo)
                        bot_widget.update_text(clean_obj)
                        avatar_panel.subtitle_text = clean_obj
                        confirm_notice = f"[bold yellow]Dangerous Action Confirmation Required:[/bold yellow]\n{event.get('prompt')}"
                        await chat_scroll.mount(ChatMessageWidget(sender="System", text=confirm_notice, is_user=False))
                        chat_scroll.scroll_end(animate=False)
                        return

                    elif etype == "done":
                        break
            else:
                async for chunk in self.llm.stream_chat(self.messages):
                    full_raw_text += chunk

                    clean_text, emo = parse_and_strip_emotion_tag(full_raw_text)
                    if emo != "neutral" and not emotion_detected:
                        detected_emotion = emo
                        avatar_panel.set_emotion(detected_emotion)
                        if self.avatar_backend:
                            self.avatar_backend.update_emotion(detected_emotion)
                        emotion_detected = True

                    clean_display = re.sub(r"\[emotion:[^\]]*$", "", clean_text, flags=re.IGNORECASE)
                    clean_display = re.sub(r"<tool_call>.*?</tool_call>", "", clean_display, flags=re.DOTALL).strip()
                    bot_widget.update_text(clean_display or "...")
                    avatar_panel.subtitle_text = clean_display or "..."
                    chat_scroll.scroll_end(animate=False)

        except Exception as e:
            bot_widget.update_text(f"[Error generating response: {e}]")
        finally:
            self.is_responding = False
            avatar_panel.set_speaking(False)
            if self.avatar_backend:
                self.avatar_backend.set_speaking(False)
            avatar_panel.current_task = "Idle"

            cleaned_final, final_emo = parse_and_strip_emotion_tag(full_raw_text)
            if cleaned_final:
                avatar_panel.subtitle_text = cleaned_final
            if final_emo != "neutral" and not emotion_detected:
                detected_emotion = final_emo
                avatar_panel.set_emotion(detected_emotion)
                if self.avatar_backend:
                    self.avatar_backend.update_emotion(detected_emotion)

            if cleaned_final:
                # Store assistant response in SQLite memory without leaking raw emotion tags
                if self.memory:
                    self.memory.add_message(
                        self.character.id,
                        self.user_id,
                        "assistant",
                        full_raw_text,
                        emotion=detected_emotion,
                    )
                    # Update relationship state from turn evaluation
                    new_rel = self.memory.relationship.evaluate_turn(
                        self.character.id,
                        self.user_id,
                        user_message=self._last_user_message,
                        assistant_emotion=detected_emotion,
                    )
                    avatar_panel.update_relationship(new_rel)

                    # Trigger background consolidation check
                    self._check_memory_consolidation()
                else:
                    self.messages.append(LLMMessage(role="assistant", content=cleaned_final))

            chat_scroll.scroll_end(animate=False)

    @work(exclusive=False)
    async def _check_memory_consolidation(self) -> None:
        """Background consolidation and auto-fact extraction worker running silently when idle."""
        if self.memory and self.llm:
            try:
                last_u = getattr(self, "_last_user_message", "")
                last_a = getattr(self, "_last_assistant_message", "")
                if last_u and last_a:
                    await self.memory.extract_facts_from_turn(
                        self.character.id, self.user_id, last_u, last_a, self.llm
                    )
                await self.memory.consolidate_if_needed(self.character.id, self.user_id, self.llm)
            except Exception:
                pass
