from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from kokoro_term.relationship.models import RelationshipState


PRAISE_PATTERNS = [
    r"\b(cute|pretty|beautiful|adorable|smart|genius|kind|sweet|wonderful|amazing|great)\b",
    r"\b(thank you|thanks|arigato|appreciate|grateful)\b",
    r"\b(love you|like you|proud of you|best teacher|good teacher)\b",
]

NEGATIVE_PATTERNS = [
    r"\b(stupid|idiot|useless|annoying|shut up|hate you|terrible|bad)\b",
    r"\b(baka|dumb|incompetent|fool)\b",
]

GREETING_PATTERNS = [
    r"\b(hello|hi|hey|good morning|good evening|konnichiwa|welcome back)\b",
]


class RelationshipEngine:
    """Manages relationship state, slow personality evolution, and deterministic drift."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._init_table()

    def _init_table(self) -> None:
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS relationship_state (
                    character_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    affection REAL NOT NULL DEFAULT 50.0,
                    trust REAL NOT NULL DEFAULT 50.0,
                    familiarity REAL NOT NULL DEFAULT 10.0,
                    mood TEXT NOT NULL DEFAULT 'neutral',
                    tsundere_level REAL NOT NULL DEFAULT 70.0,
                    shyness REAL NOT NULL DEFAULT 65.0,
                    formality REAL NOT NULL DEFAULT 80.0,
                    playfulness REAL NOT NULL DEFAULT 30.0,
                    assertiveness REAL NOT NULL DEFAULT 60.0,
                    total_interactions INTEGER NOT NULL DEFAULT 0,
                    last_interaction TEXT NOT NULL,
                    PRIMARY KEY (character_id, user_id)
                );
            """)

    def get_state(self, character_id: str, user_id: str) -> RelationshipState:
        """Fetch relationship state from SQLite or initialize with character defaults."""
        cursor = self.conn.execute(
            "SELECT * FROM relationship_state WHERE character_id = ? AND user_id = ?",
            (character_id, user_id),
        )
        row = cursor.fetchone()
        if not row:
            now = datetime.now(timezone.utc).isoformat()
            state = RelationshipState(character_id=character_id, user_id=user_id, last_interaction=now)
            self.save_state(state)
            return state

        return RelationshipState(
            character_id=row["character_id"],
            user_id=row["user_id"],
            affection=row["affection"],
            trust=row["trust"],
            familiarity=row["familiarity"],
            mood=row["mood"],
            tsundere_level=row["tsundere_level"],
            shyness=row["shyness"],
            formality=row["formality"],
            playfulness=row["playfulness"],
            assertiveness=row["assertiveness"],
            total_interactions=row["total_interactions"],
            last_interaction=row["last_interaction"],
        )

    def save_state(self, state: RelationshipState) -> None:
        """Persist state to SQLite."""
        state.clamp_all()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO relationship_state (
                    character_id, user_id, affection, trust, familiarity, mood,
                    tsundere_level, shyness, formality, playfulness, assertiveness,
                    total_interactions, last_interaction
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(character_id, user_id) DO UPDATE SET
                    affection = excluded.affection,
                    trust = excluded.trust,
                    familiarity = excluded.familiarity,
                    mood = excluded.mood,
                    tsundere_level = excluded.tsundere_level,
                    shyness = excluded.shyness,
                    formality = excluded.formality,
                    playfulness = excluded.playfulness,
                    assertiveness = excluded.assertiveness,
                    total_interactions = excluded.total_interactions,
                    last_interaction = excluded.last_interaction
                """,
                (
                    state.character_id,
                    state.user_id,
                    state.affection,
                    state.trust,
                    state.familiarity,
                    state.mood,
                    state.tsundere_level,
                    state.shyness,
                    state.formality,
                    state.playfulness,
                    state.assertiveness,
                    state.total_interactions,
                    state.last_interaction,
                ),
            )

    def evaluate_turn(
        self,
        character_id: str,
        user_id: str,
        user_message: str,
        assistant_emotion: Optional[str] = None,
    ) -> RelationshipState:
        """Process turn interaction through deterministic rule engine with slow drift."""
        state = self.get_state(character_id, user_id)
        now = datetime.now(timezone.utc)

        # 1. Check time absence drift (if > 48h since last turn)
        try:
            last_time = datetime.fromisoformat(state.last_interaction)
            hours_elapsed = (now - last_time).total_seconds() / 3600.0
            if hours_elapsed > 48.0:
                # Slight cooling: formality recovers slightly, mood is pensive
                state.familiarity = max(0.0, state.familiarity - 1.5)
                state.formality = min(100.0, state.formality + 1.0)
                state.mood = "pensive"
        except Exception:
            pass

        # 2. Rule-based sentiment scoring
        lower_msg = user_message.lower()

        is_praise = any(re.search(pat, lower_msg) for pat in PRAISE_PATTERNS)
        is_negative = any(re.search(pat, lower_msg) for pat in NEGATIVE_PATTERNS)
        is_greeting = any(re.search(pat, lower_msg) for pat in GREETING_PATTERNS)

        if is_negative:
            # Harsh words: affection & trust drop, tsundere rises, formality increases
            state.affection -= 3.5
            state.trust -= 3.0
            state.tsundere_level += 2.0
            state.formality += 1.5
            state.mood = "annoyed"
        elif is_praise:
            # Genuine praise: affection & trust rise, shyness increases, mood flustered
            state.affection += 2.5
            state.trust += 1.5
            state.familiarity += 0.8
            state.shyness = min(100.0, state.shyness + 1.0)
            state.formality = max(10.0, state.formality - 0.8)
            state.mood = "flustered"
        elif is_greeting:
            state.familiarity += 0.5
            state.affection += 0.5
            state.mood = "happy"
        else:
            # Normal conversational turns: steady familiarity growth, gradual thaw of formality
            state.familiarity += 0.4
            state.trust += 0.3
            state.formality = max(10.0, state.formality - 0.3)
            state.mood = "neutral"

        # If LLM returned a specific emotion, align mood with it
        if assistant_emotion:
            emotion_clean = assistant_emotion.lower()
            if emotion_clean in ("blush", "happy", "pout", "sad", "surprised", "thinking"):
                if emotion_clean == "blush":
                    state.mood = "flustered"
                elif emotion_clean == "pout":
                    state.mood = "annoyed"
                else:
                    state.mood = emotion_clean  # type: ignore

        # As familiarity and affection grow, playfulness gradually increases
        if state.familiarity > 40 and state.affection > 60:
            state.playfulness = min(80.0, state.playfulness + 0.3)

        state.total_interactions += 1
        state.last_interaction = now.isoformat()
        state.clamp_all()

        self.save_state(state)
        return state

    def set_metric(self, character_id: str, user_id: str, metric_name: str, value: float) -> Optional[RelationshipState]:
        """Manually adjust a relationship or trait slider."""
        state = self.get_state(character_id, user_id)
        metric = metric_name.strip().lower()

        if hasattr(state, metric):
            setattr(state, metric, value)
            state.clamp_all()
            self.save_state(state)
            return state
        return None

    def reset_state(self, character_id: str, user_id: str) -> RelationshipState:
        """Reset relationship to initial character baseline."""
        now = datetime.now(timezone.utc).isoformat()
        new_state = RelationshipState(character_id=character_id, user_id=user_id, last_interaction=now)
        self.save_state(new_state)
        return new_state
