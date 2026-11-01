from __future__ import annotations

import math
import random
import re
import time
from typing import Optional
from kokoro_term.avatar.compositor import AvatarState
from kokoro_term.avatar.lipsync import LipSyncEngine
from kokoro_term.avatar.manifest import AnimationConfig


EMOTION_TAG_REGEX = re.compile(r"\[(?:emotion|motion):\s*([a-zA-Z0-9_-]+)\s*\]", re.IGNORECASE)
ACTION_TAG_REGEX = re.compile(r"\[(?:action|tool):[^\]]*\]", re.IGNORECASE)

VALID_EMOTIONS = {
    "neutral",
    "happy",
    "smile",
    "embarrassed",
    "blush",
    "serious",
    "shy",
    "angry",
    "pout",
    "sad",
    "surprised",
    "surprise",
    "thinking",
    "halfLidded",
    "dizzy",
    "smug",
    "wink",
}

# Mapping common synonyms
EMOTION_ALIASES = {
    "flustered": "embarrassed",
    "annoyed": "pout",
    "joy": "happy",
    "cheerful": "happy",
    "sorrow": "sad",
    "shock": "surprised",
    "thoughtful": "thinking",
    "pensive": "thinking",
    "confused": "dizzy",
    "playful": "smug",
    "teasing": "smug",
}


def parse_and_strip_emotion_tag(text: str) -> tuple[str, str]:
    """
    Extract the emotion tag from LLM output, map it to a valid emotion,
    and strip all emotion tags completely from displayed/spoken text.
    Handles malformed or missing tags gracefully.
    Returns (cleaned_text, detected_emotion).
    """
    if not text:
        return "", "neutral"

    detected_emotion = "neutral"
    match = EMOTION_TAG_REGEX.search(text)
    if match:
        raw_emo = match.group(1).lower()
        if raw_emo in VALID_EMOTIONS:
            detected_emotion = raw_emo
        elif raw_emo in EMOTION_ALIASES:
            detected_emotion = EMOTION_ALIASES[raw_emo]
        else:
            detected_emotion = "neutral"

    # Strip any emotion or action tags and leading whitespace
    cleaned_text = EMOTION_TAG_REGEX.sub("", text)
    cleaned_text = ACTION_TAG_REGEX.sub("", cleaned_text).strip()
    return cleaned_text, detected_emotion


class AnimationEngine:
    """Manages breathing, autonomous blinking, emotion crossfades, and speaking sway."""

    def __init__(self, config: Optional[AnimationConfig] = None):
        self.config = config or AnimationConfig()

        self.current_emotion: str = "neutral"
        self.target_emotion: str = "neutral"
        self.current_pose: str = "normal"
        self.emotion_transition_progress: float = 1.0

        # Blinking state
        self._next_blink_time: float = time.time() + random.uniform(
            self.config.blink_interval_min, self.config.blink_interval_max
        )
        self._is_blinking: bool = False
        self._blink_start_time: float = 0.0

        # Speaking & Lip-sync
        self.is_speaking: bool = False
        self.speaking_start_time: float = 0.0
        self.lipsync_engine: Optional[LipSyncEngine] = None
        self.mouth_override: Optional[str] = None

    def set_emotion(self, emotion: str) -> None:
        clean = EMOTION_ALIASES.get(emotion.lower(), emotion.lower())
        if clean in VALID_EMOTIONS:
            self.current_emotion = clean
            self.target_emotion = clean

    def set_pose(self, pose: str) -> None:
        self.current_pose = pose.lower().strip()

    def set_speaking(self, speaking: bool, lipsync: Optional[LipSyncEngine] = None) -> None:
        self.is_speaking = speaking
        if speaking:
            self.speaking_start_time = time.time()
            self.lipsync_engine = lipsync
        else:
            self.lipsync_engine = None
            self.mouth_override = None

    def set_mouth_shape(self, shape: Optional[str]) -> None:
        self.mouth_override = shape

    def set_mouth_level(self, level: float) -> None:
        if level < 0.1:
            self.mouth_override = "closed"
        elif level < 0.35:
            self.mouth_override = "u"
        elif level < 0.65:
            self.mouth_override = "a"
        else:
            self.mouth_override = "o"

    def update(self, now: float) -> AvatarState:
        """Calculate dynamic avatar state for the current animation frame."""
        # 1. Breathing (slow sine oscillation <= 1.5% canvas height ~8-12px)
        breathe_phase = 2.0 * math.pi * self.config.breathing_frequency * now
        offset_y = math.sin(breathe_phase) * self.config.breathing_amplitude_px

        # 2. Speaking head sway & Secondary hair physics lag
        offset_x = 0.0
        if self.is_speaking:
            sway_phase = 2.0 * math.pi * 1.8 * (now - self.speaking_start_time)
            offset_x = math.sin(sway_phase) * self.config.head_sway_amplitude_px

        # Dynamic hair physics (inertia lag behind head sway + subtle gentle breeze)
        hair_phase = breathe_phase - 0.45
        hair_offset_x = math.sin(hair_phase) * 5.0 + math.sin(now * 1.4) * 1.6

        # 3. Autonomous Blinking
        eye_state = "open"
        if not self._is_blinking:
            if now >= self._next_blink_time:
                self._is_blinking = True
                self._blink_start_time = now
        else:
            blink_elapsed = now - self._blink_start_time
            if blink_elapsed < self.config.blink_duration * 0.35:
                eye_state = "half"
            elif blink_elapsed < self.config.blink_duration * 0.7:
                eye_state = "closed"
            elif blink_elapsed < self.config.blink_duration:
                eye_state = "half"
            else:
                self._is_blinking = False
                self._next_blink_time = now + random.uniform(
                    self.config.blink_interval_min, self.config.blink_interval_max
                )
                eye_state = "open"

        # 4. Lip-sync Mouth Shape (Casual natural vowel cycling with cadence)
        if self.mouth_override:
            mouth_state = self.mouth_override
        elif self.is_speaking and self.lipsync_engine:
            playback_t = now - self.speaking_start_time
            mouth_state = self.lipsync_engine.get_mouth_shape(playback_t)
        elif self.is_speaking:
            # Casual natural Japanese vowel cadence with micro-pauses
            SPEECH_CADENCE = ["a", "u", "i", "e", "a", "o", "closed", "e"]
            step = int((now - self.speaking_start_time) * 6.0) % len(SPEECH_CADENCE)
            mouth_state = SPEECH_CADENCE[step]
        else:
            mouth_state = "closed"

        # 5. Overlays, Eyebrows & Funny Reactions based on emotion
        brow_state = "neutral"
        blush = False
        overlays = []

        if self.current_emotion in ("embarrassed", "blush"):
            blush = True
            brow_state = "neutral"
            if eye_state == "open":
                eye_state = "half"
        elif self.current_emotion == "pout":
            brow_state = "angry"
            blush = True
            if not self.is_speaking and mouth_state == "closed":
                mouth_state = "u"
        elif self.current_emotion == "angry":
            brow_state = "angry"
            blush = True
        elif self.current_emotion == "sad":
            brow_state = "sad"
            if eye_state == "open":
                eye_state = "half"
        elif self.current_emotion == "surprised":
            brow_state = "surprised"
            if mouth_state == "closed" and not self.is_speaking:
                mouth_state = "o"
        elif self.current_emotion == "dizzy":
            brow_state = "surprised"
            if eye_state == "open":
                eye_state = "half"
            overlays.append("sweat")
            if mouth_state == "closed" and not self.is_speaking:
                mouth_state = "o"
        elif self.current_emotion == "smug":
            brow_state = "neutral"
            blush = True
            if mouth_state == "closed" and not self.is_speaking:
                mouth_state = "i"
        elif self.current_emotion == "wink":
            brow_state = "neutral"
            eye_state = "half"
            blush = True
            if mouth_state == "closed" and not self.is_speaking:
                mouth_state = "a"
        elif self.current_emotion == "thinking":
            brow_state = "neutral"
            overlays.append("sweat")
            if eye_state == "open":
                eye_state = "half"
        elif self.current_emotion == "happy":
            blush = True
            if mouth_state == "closed" and not self.is_speaking:
                mouth_state = "a"

        return AvatarState(
            emotion=self.current_emotion,
            eye_state=eye_state,
            brow_state=brow_state,
            mouth_state=mouth_state,
            blush=blush,
            overlays=overlays,
            offset_y=offset_y,
            offset_x=offset_x,
            hair_offset_x=hair_offset_x,
            pose=self.current_pose,
        )
