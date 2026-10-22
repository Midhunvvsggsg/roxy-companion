import sqlite3
import pytest
from kokoro_term.relationship.engine import RelationshipEngine
from kokoro_term.relationship.models import RelationshipState


@pytest.fixture
def rel_engine(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return RelationshipEngine(conn)


def test_initial_state(rel_engine):
    state = rel_engine.get_state("roxy", "user1")
    assert state.character_id == "roxy"
    assert state.user_id == "user1"
    assert state.affection == 50.0
    assert state.trust == 50.0
    assert state.familiarity == 10.0
    assert state.mood == "neutral"
    assert state.tsundere_level == 70.0


def test_evaluate_praise(rel_engine):
    initial = rel_engine.get_state("roxy", "user1")
    new_state = rel_engine.evaluate_turn("roxy", "user1", "You are such an amazing and cute teacher, Roxy!")

    assert new_state.affection > initial.affection
    assert new_state.trust > initial.trust
    assert new_state.mood == "flustered"
    assert new_state.total_interactions == 1


def test_evaluate_insult(rel_engine):
    initial = rel_engine.get_state("roxy", "user1")
    new_state = rel_engine.evaluate_turn("roxy", "user1", "You are so stupid and annoying.")

    assert new_state.affection < initial.affection
    assert new_state.trust < initial.trust
    assert new_state.tsundere_level > initial.tsundere_level
    assert new_state.mood == "annoyed"


def test_clamping_bounds(rel_engine):
    state = rel_engine.get_state("roxy", "user1")
    state.affection = 150.0
    state.trust = -30.0
    state.clamp_all()

    assert state.affection == 100.0
    assert state.trust == 0.0


def test_set_metric_manually(rel_engine):
    updated = rel_engine.set_metric("roxy", "user1", "affection", 88.0)
    assert updated is not None
    assert updated.affection == 88.0

    # Verify persisted in db
    fetched = rel_engine.get_state("roxy", "user1")
    assert fetched.affection == 88.0


def test_reset_state(rel_engine):
    rel_engine.set_metric("roxy", "user1", "affection", 99.0)
    reset = rel_engine.reset_state("roxy", "user1")

    assert reset.affection == 50.0
    assert reset.trust == 50.0


def test_prompt_guidance_generation(rel_engine):
    state = rel_engine.get_state("roxy", "user1")
    guidance_low = state.build_prompt_guidance()
    assert "Affection: 50/100" in guidance_low

    state.affection = 90.0
    state.familiarity = 75.0
    guidance_high = state.build_prompt_guidance()
    assert "Affection: 90/100" in guidance_high
    assert "Deeply Cherished" in guidance_high or "Close Companion" in guidance_high
