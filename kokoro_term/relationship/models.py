from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field


MoodType = Literal["neutral", "happy", "flustered", "annoyed", "pensive", "caring", "proud"]


class RelationshipState(BaseModel):
    character_id: str
    user_id: str

    # Core relationship meters (0 - 100)
    affection: float = Field(default=50.0, ge=0.0, le=100.0)
    trust: float = Field(default=50.0, ge=0.0, le=100.0)
    familiarity: float = Field(default=10.0, ge=0.0, le=100.0)

    # Current mood
    mood: MoodType = "neutral"

    # Trait sliders (0 - 100)
    tsundere_level: float = Field(default=70.0, ge=0.0, le=100.0)
    shyness: float = Field(default=65.0, ge=0.0, le=100.0)
    formality: float = Field(default=80.0, ge=0.0, le=100.0)
    playfulness: float = Field(default=30.0, ge=0.0, le=100.0)
    assertiveness: float = Field(default=60.0, ge=0.0, le=100.0)

    # Interaction telemetry
    total_interactions: int = 0
    last_interaction: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def clamp_all(self) -> None:
        """Ensure all metrics stay strictly within 0.0 to 100.0."""
        self.affection = max(0.0, min(100.0, self.affection))
        self.trust = max(0.0, min(100.0, self.trust))
        self.familiarity = max(0.0, min(100.0, self.familiarity))
        self.tsundere_level = max(0.0, min(100.0, self.tsundere_level))
        self.shyness = max(0.0, min(100.0, self.shyness))
        self.formality = max(0.0, min(100.0, self.formality))
        self.playfulness = max(0.0, min(100.0, self.playfulness))
        self.assertiveness = max(0.0, min(100.0, self.assertiveness))

    def get_relationship_stage(self) -> str:
        if self.affection >= 85 and self.trust >= 80:
            return "Deeply Cherished & Inseparable"
        elif self.affection >= 70 and self.familiarity >= 50:
            return "Close Companion & Trusted Confidant"
        elif self.affection >= 55 or self.familiarity >= 30:
            return "Friendly Mentor & Pupil"
        elif self.affection <= 25:
            return "Distant & Wary"
        else:
            return "Formal Teacher & Student"

    def build_prompt_guidance(self) -> str:
        """Generate dynamic demeanor directives to inject into system prompt."""
        stage = self.get_relationship_stage()

        # Dynamic nuance based on meters
        nuances = []
        if self.familiarity > 60:
            nuances.append("You know the user very well; drop stiff honorifics and speak casually like an old partner.")
        elif self.familiarity > 30:
            nuances.append("You are comfortably familiar; balance formal respect with occasional friendly warmth.")
        else:
            nuances.append("You are still relatively new to the user; maintain respectful, professional mentor etiquette.")

        if self.affection > 75:
            nuances.append("You harbor deep, secret affection; praise flusters you intensely, and you are very protective.")
        elif self.affection < 35:
            nuances.append("You are somewhat guarded and skeptical; observe cautiously before opening up.")

        if self.tsundere_level > 70 and self.affection > 60:
            nuances.append("High tsundere: cover up tender feelings with flustered defensiveness or mock scolding.")
        elif self.playfulness > 60:
            nuances.append("Feel free to lightly tease the user about their terminal habits or quirky questions.")

        return (
            f"\n### Dynamic Relationship & Emotional State:\n"
            f"- Current Status: {stage} (Mood: {self.mood})\n"
            f"- Affection: {self.affection:.0f}/100 | Trust: {self.trust:.0f}/100 | Familiarity: {self.familiarity:.0f}/100\n"
            f"- Demeanor Directives:\n" + "\n".join(f"  * {n}" for n in nuances) + "\n"
        )
