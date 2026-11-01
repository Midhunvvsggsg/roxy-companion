import pytest
import asyncio
from kokoro_term.emotional.state import EmotionalState
from kokoro_term.emotional.cognition import EmotionalCognition
from kokoro_term.emotional.heartbeat import AutonomousHeartbeat
from kokoro_term.relationship.models import RelationshipState
from kokoro_term.avatar.animation import AnimationEngine, parse_and_strip_emotion_tag
from kokoro_term.avatar.compositor import AvatarState


def test_emotional_state_defaults_and_blend():
    st = EmotionalState(joy=0.8, trust=0.8, anger=0.0)
    assert "affectionate" in st.blend_description()
    st.determine_avatar_directives()
    assert st.recommended_expression in ("smile", "blush")


def test_emotional_state_decay():
    st = EmotionalState(joy=1.0, anger=0.8, unresolved_tension="Midhun was upset")
    st.decay_towards_baseline(hours_elapsed=12.0)
    assert st.anger < 0.5
    assert st.joy < 0.8
    assert st.unresolved_tension is None


def test_animation_engine_hair_and_casual_lipsync():
    engine = AnimationEngine()
    engine.set_emotion("pout")
    engine.set_pose("pointing")
    assert engine.current_emotion == "pout"
    assert engine.current_pose == "pointing"

    # Test update
    now = 1000.0
    state = engine.update(now)
    assert isinstance(state, AvatarState)
    assert state.hair_offset_x != 0.0
    assert state.brow_state == "angry"

    # Test speech cadence
    engine.set_speaking(True)
    state_speaking = engine.update(now + 0.1)
    assert state_speaking.mouth_state in ("a", "u", "i", "e", "o", "closed")


@pytest.mark.asyncio
async def test_emotional_cognition_fallback():
    cog = EmotionalCognition(ollama_base_url="http://127.0.0.1:99999") # Intentionally bad port to test fallback
    rel = RelationshipState(character_id="roxy", user_id="test")
    state = await cog.process_turn("Thank you so much Roxy!", rel, [], "Midhun")
    assert state.joy > 0.4
    assert state.recommended_expression in ("smile", "blush")
