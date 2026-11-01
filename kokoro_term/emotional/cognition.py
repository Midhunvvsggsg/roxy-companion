from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Optional
import httpx

from kokoro_term.emotional.state import EmotionalState
from kokoro_term.relationship.models import RelationshipState


class EmotionalCognition:
    """Roxy's Subconscious Emotional Cognition Processor.
    
    Runs locally on Ollama (e.g. qwen2.5:1.5b) to simulate her private inner
    thoughts, emotional inertia, and body language directives before she speaks.
    """

    def __init__(
        self,
        ollama_base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5:1.5b",
        state: Optional[EmotionalState] = None,
    ):
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.model = model
        self.state = state or EmotionalState()
        self.thought_history: list[str] = []

    async def process_turn(
        self,
        user_message: str,
        relationship: RelationshipState,
        recent_context: list[str],
        user_name: str = "Midhun-san",
    ) -> EmotionalState:
        """Run an inner emotional introspection turn."""
        now_dt = datetime.now()
        hour = now_dt.hour
        time_desc = "late night" if (hour >= 23 or hour < 5) else "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
        time_str = f"{time_desc} ({now_dt.strftime('%I:%M %p')})"

        prompt = self._build_subconscious_prompt(user_message, relationship, recent_context, time_str, user_name)

        try:
            raw_json = await self._query_local_model(prompt)
            parsed = self._extract_json(raw_json)
            if parsed:
                self._apply_updates(parsed)
            else:
                self._fallback_heuristic(user_message)
        except Exception:
            self._fallback_heuristic(user_message)

        self.state.determine_avatar_directives()
        return self.state

    def _build_subconscious_prompt(
        self,
        user_message: str,
        rel: RelationshipState,
        context: list[str],
        time_str: str,
        user_name: str,
    ) -> str:
        ctx_formatted = "\n".join(f"  - {line}" for line in context[-4:]) if context else "  - (No recent context)"
        return f"""You are the SUBCONSCIOUS INNER MIND of Roxy Migurdia (Water Saint-Class magician & devoted anime companion).
You are NOT speaking to {user_name}. You are processing your genuine private emotions and inner thoughts before replying.

CURRENT INNER REALITY:
- Relationship with {user_name}: Affection={rel.affection:.0f}/100, Trust={rel.trust:.0f}/100, Tsundere={rel.tsundere_level:.0f}/100
- Stage: {rel.get_relationship_stage()}
- Current Time: {time_str}
- Current feeling: {self.state.blend_description()}
- Lingering tension/worry: {self.state.unresolved_tension or 'None'}

RECENT CONTEXT:
{ctx_formatted}

{user_name} JUST SAID: "{user_message}"

Analyze your feelings as Roxy:
1. What is your private first-person inner monologue? (2-3 sentences: genuine anime companion feeling, caring, slightly possessive/protective or flustered)
2. How do your emotion values shift? (0.0 to 1.0)
3. What bodily posture / gesture fits you right now? (choose one: normal, thinking, flustered, pointing, waving, smug)
4. What facial expression fits? (choose one: smile, blush, pout, dizzy, surprise, neutral, serious, sweat)

OUTPUT STRICTLY IN THIS JSON FORMAT AND NOTHING ELSE:
{{
  "inner_monologue": "Your private 1-2 sentence thoughts as Roxy...",
  "joy": 0.5,
  "trust": 0.7,
  "fear": 0.0,
  "surprise": 0.0,
  "sadness": 0.0,
  "anticipation": 0.4,
  "anger": 0.0,
  "valence": 0.5,
  "arousal": 0.4,
  "unresolved_tension": null,
  "recommended_pose": "thinking",
  "recommended_expression": "smile"
}}"""

    async def _query_local_model(self, prompt: str) -> str:
        url = f"{self.ollama_base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.75,
                "num_predict": 220,
            },
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("response", "")
            raise RuntimeError(f"Ollama returned HTTP {resp.status_code}")

    def _extract_json(self, raw: str) -> Optional[dict]:
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1]
            if clean.endswith("```"):
                clean = clean.rsplit("```", 1)[0]
        try:
            return json.loads(clean.strip())
        except Exception:
            m = re.search(r"\{.*\}", clean, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    pass
        return None

    def _apply_updates(self, parsed: dict) -> None:
        inertia = self.state.emotional_inertia

        for key in ("joy", "trust", "fear", "surprise", "sadness", "anticipation", "anger"):
            if key in parsed and isinstance(parsed[key], (int, float)):
                cur = getattr(self.state, key)
                val = float(parsed[key])
                smoothed = cur * inertia + val * (1.0 - inertia)
                setattr(self.state, key, max(0.0, min(1.0, smoothed)))

        if "valence" in parsed and isinstance(parsed["valence"], (int, float)):
            v = float(parsed["valence"])
            self.state.valence = self.state.valence * inertia + v * (1.0 - inertia)

        if "arousal" in parsed and isinstance(parsed["arousal"], (int, float)):
            a = float(parsed["arousal"])
            self.state.arousal = self.state.arousal * inertia + a * (1.0 - inertia)

        mono = parsed.get("inner_monologue", "").strip()
        if mono:
            self.state.inner_monologue = mono
            self.thought_history.append(mono)
            self.thought_history = self.thought_history[-10:]

        tension = parsed.get("unresolved_tension")
        if tension:
            self.state.unresolved_tension = str(tension).strip()
        elif tension is None and self.state.unresolved_tension and self.state.valence > 0.4:
            self.state.unresolved_tension = None

        if "recommended_pose" in parsed:
            self.state.recommended_pose = str(parsed["recommended_pose"]).lower().strip()
        if "recommended_expression" in parsed:
            self.state.recommended_expression = str(parsed["recommended_expression"]).lower().strip()

    def _fallback_heuristic(self, message: str) -> None:
        lower = message.lower()
        if any(w in lower for w in ("thank", "love", "good", "great", "cute", "best")):
            self.state.joy = min(1.0, self.state.joy + 0.15)
            self.state.trust = min(1.0, self.state.trust + 0.1)
            self.state.inner_monologue = "His kind words make my heart flutter... I need to stay calm and compose myself."
            self.state.recommended_expression = "blush"
            self.state.recommended_pose = "flustered"
        elif any(w in lower for w in ("stupid", "idiot", "hate", "bad", "useless")):
            self.state.anger = min(1.0, self.state.anger + 0.2)
            self.state.inner_monologue = "Mou! Why is he saying that? Is he trying to test my patience?"
            self.state.recommended_expression = "pout"
            self.state.recommended_pose = "pointing"
        else:
            self.state.inner_monologue = "Focusing on what he needs right now."

    def build_prompt_injection(self) -> str:
        """Construct the prompt guidance block for Gemini."""
        tension_str = f"- Lingering Thought/Tension: {self.state.unresolved_tension}\n" if self.state.unresolved_tension else ""
        return (
            f"\n### Roxy's Inner Emotional Mind & Bodily Demeanor:\n"
            f"- Current Emotional State: {self.state.blend_description()}\n"
            f"- Private Inner Monologue (DO NOT repeat verbatim; let it naturally shape your tone): \"{self.state.inner_monologue}\"\n"
            f"{tension_str}"
            f"- Recommended Demeanor/Pose: {self.state.recommended_pose} | Expression: {self.state.recommended_expression}\n"
            f"- Emotional Directive: Speak with genuine, living emotional nuance matching your inner monologue.\n"
        )
