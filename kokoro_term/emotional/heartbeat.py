from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Callable, Optional
import httpx

from kokoro_term.emotional.cognition import EmotionalCognition
from kokoro_term.relationship.engine import RelationshipEngine


class AutonomousHeartbeat:
    """Roxy's Autonomous Subconscious Heartbeat Loop.
    
    Runs periodically in the background when the user is idle or deep in thought.
    Enables Roxy to experience spontaneous thoughts, worry about user's health/sleep,
    and proactively initiate interactions or shift bodily expressions.
    """

    def __init__(
        self,
        cognition: EmotionalCognition,
        relationship_engine: RelationshipEngine,
        character_id: str = "roxy",
        user_id: str = "default_user",
        user_name: str = "Midhun-san",
        interval_seconds: float = 300.0,  # Run check every 5 minutes
        on_spontaneous_thought: Optional[Callable[[str, str, str], None]] = None,
    ):
        self.cognition = cognition
        self.relationship_engine = relationship_engine
        self.character_id = character_id
        self.user_id = user_id
        self.user_name = user_name
        self.interval_seconds = interval_seconds
        self.on_spontaneous_thought = on_spontaneous_thought

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.last_user_activity = datetime.now(timezone.utc)
        self.last_thought_summary: str = ""

    def notify_user_activity(self) -> None:
        """Call this whenever the user submits a message or interacts with the terminal."""
        self.last_user_activity = datetime.now(timezone.utc)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._heartbeat_loop())

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.interval_seconds)
                if not self._running:
                    break

                now = datetime.now(timezone.utc)
                idle_minutes = (now - self.last_user_activity).total_seconds() / 60.0

                # Only mind-wander if user has been idle for >= 5 minutes
                if idle_minutes >= 4.0:
                    await self._generate_autonomous_reflection(idle_minutes)

            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(30.0)

    async def _generate_autonomous_reflection(self, idle_minutes: float) -> None:
        """Query local model for an idle mind-wandering reflection."""
        rel = self.relationship_engine.get_state(self.character_id, self.user_id)
        local_hour = datetime.now().hour
        time_str = datetime.now().strftime("%I:%M %p")

        prompt = f"""You are the SUBCONSCIOUS MIND of anime companion Roxy Migurdia.
The user, {self.user_name}, has been silent for {int(idle_minutes)} minutes.
Current time: {time_str} (hour={local_hour}).
Current feeling: {self.cognition.state.blend_description()}
Relationship: Affection={rel.affection:.0f}/100, Trust={rel.trust:.0f}/100, Tsundere={rel.tsundere_level:.0f}/100.

You are watching him or quietly thinking to yourself while he is busy or away.
Reflect on:
- Is it late at night? Are you worried about his sleep, food, or posture?
- Are you missing his attention, or feeling patient and fond?
- What is your inner thought?
- Should you proactively speak, or just stay quiet and watch affectionately?

OUTPUT STRICTLY AS JSON:
{{
  "inner_thought": "Your 1-2 sentence private thought as Roxy...",
  "proactive_speech": "optional 1-sentence gentle comment to Midhun, or null if staying quiet",
  "recommended_expression": "smile|blush|pout|dizzy|surprise|neutral|serious|sweat",
  "recommended_pose": "normal|thinking|flustered|pointing|waving|smug",
  "urgency": 0.0 to 1.0
}}"""

        try:
            url = f"{self.cognition.ollama_base_url}/api/generate"
            payload = {
                "model": self.cognition.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.8, "num_predict": 180},
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    import json
                    parsed = json.loads(resp.json().get("response", "{}"))
                    thought = parsed.get("inner_thought", "")
                    speech = parsed.get("proactive_speech")
                    expr = parsed.get("recommended_expression", "neutral")
                    pose = parsed.get("recommended_pose", "normal")
                    urgency = float(parsed.get("urgency", 0.0))

                    if thought:
                        self.cognition.state.inner_monologue = thought
                        self.cognition.state.recommended_expression = expr
                        self.cognition.state.recommended_pose = pose
                        self.last_thought_summary = thought

                    # If urgency > 0.7 or speech is recommended and late night, notify UI
                    if self.on_spontaneous_thought and (urgency > 0.75 or (local_hour >= 23 and speech)):
                        self.on_spontaneous_thought(thought, speech or "", expr)
        except Exception:
            pass
