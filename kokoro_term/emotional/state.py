from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class CoreEmotion(str, Enum):
    JOY = "joy"
    TRUST = "trust"
    FEAR = "fear"
    SURPRISE = "surprise"
    SADNESS = "sadness"
    ANTICIPATION = "anticipation"
    ANGER = "anger"


class EmotionalState(BaseModel):
    """Roxy's inner emotional state, tracking multi-layered feelings and physical demeanor."""

    # Primary emotions (0.0 to 1.0)
    joy: float = Field(default=0.4, ge=0.0, le=1.0)
    trust: float = Field(default=0.6, ge=0.0, le=1.0)
    fear: float = Field(default=0.0, ge=0.0, le=1.0)
    surprise: float = Field(default=0.0, ge=0.0, le=1.0)
    sadness: float = Field(default=0.0, ge=0.0, le=1.0)
    anticipation: float = Field(default=0.3, ge=0.0, le=1.0)
    anger: float = Field(default=0.0, ge=0.0, le=1.0)

    # Dimensional axes
    valence: float = Field(default=0.4, ge=-1.0, le=1.0)   # negative (-1.0) to positive (+1.0)
    arousal: float = Field(default=0.4, ge=0.0, le=1.0)    # calm (0.0) to excited/agitated (1.0)
    dominance: float = Field(default=0.5, ge=0.0, le=1.0)  # submissive (0.0) to assertive (1.0)

    # Narrative inner life
    inner_monologue: str = "I'm ready to assist Midhun-san with whatever he needs today."
    emotional_memory_tag: str = "Ready and focused"
    unresolved_tension: Optional[str] = None

    # Temporal dynamics
    mood_momentum: float = 0.0          # Positive = mood lifting, Negative = darkening
    emotional_inertia: float = 0.65     # 0.0 = volatile, 1.0 = immovable baseline
    last_thought_time: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Visual / Avatar Directives derived from emotion
    recommended_pose: str = "normal"          # normal, thinking, flustered, pointing, waving, smug
    recommended_expression: str = "smile"     # smile, blush, pout, dizzy, surprise, neutral, serious, sweat
    pout_intensity: float = 0.0               # For puffed cheek reaction
    blush_intensity: float = 0.0              # 0.0 to 1.0

    def dominant_emotion(self) -> str:
        emotions = {
            "joy": self.joy,
            "trust": self.trust,
            "fear": self.fear,
            "surprise": self.surprise,
            "sadness": self.sadness,
            "anticipation": self.anticipation,
            "anger": self.anger,
        }
        return max(emotions, key=emotions.get)

    def blend_description(self) -> str:
        """Human-readable description of blended emotional state."""
        if self.joy > 0.6 and self.trust > 0.6:
            return "deeply affectionate and warmly attached"
        if self.joy > 0.6 and self.anticipation > 0.5:
            return "high-spirited, excited, and eager to help"
        if self.anger > 0.4 and self.trust > 0.5:
            return "scolding affectionately, slightly annoyed at reckless work habits"
        if self.sadness > 0.4 and self.trust > 0.5:
            return "quietly worried and protective about user's health"
        if self.fear > 0.4 or self.surprise > 0.6:
            return "flustered, caught off guard, and trying to recover composure"
        if self.joy < 0.2 and self.sadness > 0.5:
            return "melancholic and longing for connection"
        
        dominant = self.dominant_emotion()
        return f"feeling mostly {dominant} with a calm focus"

    def determine_avatar_directives(self) -> None:
        """Derive recommended pose and expression from emotional state."""
        # 1. Expressions
        if self.fear > 0.5 or (self.joy > 0.6 and self.valence > 0.6 and self.arousal > 0.6):
            self.recommended_expression = "blush"
            self.blush_intensity = min(1.0, max(self.joy, self.fear))
        elif self.anger > 0.4:
            self.recommended_expression = "pout"
            self.pout_intensity = self.anger
        elif self.surprise > 0.5:
            self.recommended_expression = "surprise"
        elif self.sadness > 0.4:
            self.recommended_expression = "sad"
        elif self.joy > 0.4:
            self.recommended_expression = "smile"
        elif self.arousal > 0.6 and self.dominance > 0.6:
            self.recommended_expression = "serious"
        else:
            self.recommended_expression = "neutral"

        # 2. Poses
        if self.recommended_expression in ("blush", "embarrassed") or self.blush_intensity > 0.6:
            self.recommended_pose = "flustered"
        elif self.arousal < 0.3 and self.valence >= 0.0:
            self.recommended_pose = "thinking"
        elif self.anger > 0.4 or self.dominance > 0.7:
            self.recommended_pose = "pointing"
        elif self.joy > 0.6 and self.anticipation > 0.5:
            self.recommended_pose = "waving"
        else:
            self.recommended_pose = "normal"

    def decay_towards_baseline(self, hours_elapsed: float) -> None:
        """Decay acute emotions back towards character baseline during prolonged idle time."""
        decay = min(1.0, hours_elapsed / 12.0)
        baseline_joy = 0.35
        baseline_trust = 0.55
        baseline_fear = 0.0
        baseline_anger = 0.0
        baseline_sadness = 0.0

        self.joy += (baseline_joy - self.joy) * decay
        self.trust += (baseline_trust - self.trust) * decay
        self.fear += (baseline_fear - self.fear) * decay
        self.anger += (baseline_anger - self.anger) * decay
        self.sadness += (baseline_sadness - self.sadness) * decay
        self.unresolved_tension = None if decay > 0.8 else self.unresolved_tension
        self.determine_avatar_directives()
