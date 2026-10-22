from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Label, Static

from rich.text import Text
from kokoro_term.avatar.generator import generate_roxy_sprite_pack
from kokoro_term.avatar.renderer import image_to_half_block
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

    def __init__(self, character: Character, **kwargs):
        super().__init__(**kwargs)
        self.character = character
        self.avatar_dir = Path("characters") / character.id / "avatar"
        if not self.avatar_dir.exists():
            self.avatar_dir = Path(__file__).resolve().parent.parent.parent / "characters" / character.id / "avatar"

        self.sprite_pack = SpritePack(self.avatar_dir)
        protocol = detect_render_protocol()
        self.avatar_mode = "half_block" if protocol in ("kitty", "sixel", "half_block") else "ascii"

    def on_mount(self) -> None:
        # Subtle idle animation ticking at 4 FPS for near-zero CPU usage
        self.set_interval(0.25, self.tick_animation)

    def tick_animation(self) -> None:
        self.refresh()

    def update_relationship(self, state: RelationshipState) -> None:
        self.affection = state.affection
        self.trust = state.trust
        self.familiarity = state.familiarity
        self.mood = state.mood
        self.stage = state.get_relationship_stage()

    def render(self) -> Text:
        import time
        now = time.time()

        content = Text()
        content.append(self.character.name + "\n", style="bold blue")
        content.append(self.character.title + "\n\n", style="dim")

        rendered_art = False
        if self.avatar_mode == "half_block" and self.sprite_pack.has_sprites():
            frame = self.sprite_pack.get_composite_frame(
                emotion=self.current_emotion,
                is_speaking=self.is_speaking,
                time_sec=now,
            )
            if frame:
                ansi_str = image_to_half_block(frame, width=20, height=20)
                content.append_text(Text.from_ansi(ansi_str))
                content.append("\n\n")
                rendered_art = True

        if not rendered_art:
            art = EMOTION_ART.get(self.current_emotion, EMOTION_ART["neutral"])
            content.append(art + "\n\n", style="bold white")

        aff_bar = _progress_bar(self.affection, width=8)
        trust_bar = _progress_bar(self.trust, width=8)

        content.append(self.stage + "\n\n", style="bold yellow")
        content.append("Affection: ", style="dim")
        content.append(f"{self.affection:4.1f}% [{aff_bar}]\n", style="green")
        content.append("Trust:     ", style="dim")
        content.append(f"{self.trust:4.1f}% [{trust_bar}]\n", style="cyan")
        content.append("Mood:      ", style="dim")
        content.append(f"{self.mood.capitalize()}\n", style="magenta")
        content.append("Mic:       ", style="dim")
        content.append("Off (Text Mode)\n", style="yellow")
        content.append("Task:      ", style="dim")
        content.append(f"{self.current_task}", style="cyan")

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
        width: 34;
        height: 1fr;
        border: round $secondary;
        padding: 1;
        background: $panel;
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

    #input-container {
        height: auto;
        dock: bottom;
        padding: 0 1;
    }

    #user-input {
        width: 100%;
        border: tall $accent;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+q", "quit", "Quit", show=False),
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

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-container"):
            yield VerticalScroll(id="chat-scroll")
            yield AvatarPanel(character=self.character, id="avatar-panel")
        with Container(id="input-container"):
            yield Input(placeholder=f"Talk to {self.character.display_name}... (Press Enter to send)", id="user-input")
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"Kokoro-Term | {self.character.name}"
        self.sub_title = "AI Terminal Companion"

        chat_scroll = self.query_one("#chat-scroll", VerticalScroll)
        avatar_panel = self.query_one("#avatar-panel", AvatarPanel)

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

    def _prepare_system_prompt(self, current_user_query: str = "") -> str:
        """Build the complete system prompt including base personality, memory, relationship, and tools."""
        base_prompt = self.character.build_system_prompt(user_name=self.user_id)
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
                "- /status: View character & relationship meters\n"
                "- /status set <metric> <val>: Manually adjust a trait slider\n"
                "- /status reset: Reset relationship to baseline\n"
                "- /character list: List installed characters\n"
                "- /character use <name>: Hot-swap active companion on the fly\n"
                "- /character new <id> <name>: Interactive character generator\n"
                "- /perf: Display process RAM, DB size, and resource telemetry\n"
                "- /tools: List registered agency tools and permission tiers\n"
                "- /audit: View recent security audit logs\n"
                "- /memory show: List long-term facts & recent episodes\n"
                "- /memory forget <term/id>: Remove a fact from memory\n"
                "- /memory export [file]: Save all memory to Markdown\n"
                "- /memory wipe: Erase all memory for this character\n"
                "- /clear: Clear chat window\n"
                "- /quit: Exit application"
            )
            await chat_scroll.mount(ChatMessageWidget(sender="System", text=help_text, is_user=False))

        elif root_cmd == "/perf":
            report = format_performance_report(self.config, self.character, self.config.memory.db_path)
            await chat_scroll.mount(ChatMessageWidget(sender="System", text=report, is_user=False))

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
                    facts = self.memory.get_facts(self.character.id, self.user_id, active_only=True)
                    episodes = self.memory.get_recent_episodes(self.character.id, self.user_id, limit=3)

                    lines = ["[bold]🧠 Stored Memory:[/bold]"]
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

        elif root_cmd == "/clear":
            self.action_clear_chat()
        elif root_cmd == "/quit":
            self.exit()
        else:
            await chat_scroll.mount(
                ChatMessageWidget(sender="System", text=f"Unknown command '{cmd}'. Type /help for options.", is_user=False)
            )
        chat_scroll.scroll_end(animate=False)

    @work(exclusive=True)
    async def _stream_assistant_response(self) -> None:
        self.is_responding = True
        chat_scroll = self.query_one("#chat-scroll", VerticalScroll)
        avatar_panel = self.query_one("#avatar-panel", AvatarPanel)
        avatar_panel.is_speaking = True

        bot_widget = ChatMessageWidget(sender=self.character.display_name, text="...", is_user=False)
        await chat_scroll.mount(bot_widget)
        chat_scroll.scroll_end(animate=False)

        full_raw_text = ""
        displayed_text = ""
        detected_emotion = "neutral"
        emotion_detected = False

        try:
            async for chunk in self.llm.stream_chat(self.messages):
                full_raw_text += chunk

                if not emotion_detected:
                    match = re.search(r"\[emotion:([a-zA-Z0-9_-]+)\]", full_raw_text)
                    if match:
                        detected_emotion = match.group(1).lower()
                        avatar_panel.current_emotion = detected_emotion
                        emotion_detected = True
                        displayed_text = re.sub(r"\[emotion:[a-zA-Z0-9_-]+\]\s*", "", full_raw_text)
                    else:
                        if len(full_raw_text) > 30:
                            displayed_text = full_raw_text
                else:
                    displayed_text = re.sub(r"\[emotion:[a-zA-Z0-9_-]+\]\s*", "", full_raw_text)

                # Clean tool_call tags from live display so user sees natural text
                clean_display = re.sub(r"<tool_call>.*?</tool_call>", "", displayed_text, flags=re.DOTALL).strip()
                bot_widget.update_text(clean_display or "...")
                chat_scroll.scroll_end(animate=False)

            # Check if assistant invoked any tools
            if self.agent_loop and self.tools and self.config.tools.enabled:
                tool_calls = self.agent_loop.parse_tool_calls(full_raw_text)
                if tool_calls:
                    for tool_name, args in tool_calls:
                        tool = self.tools.get(tool_name)
                        if not tool:
                            continue

                        needs_confirm, reason = self.agent_loop.permission.requires_confirmation(tool, args)
                        if needs_confirm:
                            # Resistance Behavior: Register pending confirmation & produce single in-character objection
                            self.agent_loop.resistance.register_pending(tool_name, args)
                            rel_state = (
                                self.memory.relationship.get_state(self.character.id, self.user_id)
                                if self.memory
                                else RelationshipState(character_id=self.character.id, user_id=self.user_id)
                            )
                            objection = self.agent_loop.resistance.generate_objection(tool, args, rel_state)
                            clean_objection = re.sub(r"\[emotion:[a-zA-Z0-9_-]+\]\s*", "", objection)
                            bot_widget.update_text(clean_objection)
                            return
                        else:
                            # Execute safe / pre-approved tool
                            avatar_panel.current_task = f"Running {tool.name}..."
                            result = await self.agent_loop.execute_tool(tool, args)
                            avatar_panel.current_task = "Idle"

                            # Display result notice in chat
                            tool_notice = f"[dim][Executed {tool.name}][/dim]\n{result.output or result.error}"
                            await chat_scroll.mount(ChatMessageWidget(sender="System", text=tool_notice, is_user=False))
                            chat_scroll.scroll_end(animate=False)

        except Exception as e:
            bot_widget.update_text(f"[Error generating response: {e}]")
        finally:
            self.is_responding = False
            avatar_panel.is_speaking = False
            avatar_panel.current_task = "Idle"
            cleaned_final = re.sub(r"\[emotion:[a-zA-Z0-9_-]+\]\s*", "", full_raw_text).strip()
            if cleaned_final:
                # Store assistant response in SQLite memory
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
                    self.messages.append(LLMMessage(role="assistant", content=full_raw_text))

            chat_scroll.scroll_end(animate=False)

    @work(exclusive=False)
    async def _check_memory_consolidation(self) -> None:
        """Background consolidation worker running silently when idle."""
        if self.memory:
            try:
                await self.memory.consolidate_if_needed(self.character.id, self.user_id, self.llm)
            except Exception:
                pass
