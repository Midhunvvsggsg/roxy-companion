import numpy as np
import pytest
from pathlib import Path
from PIL import Image

from kokoro_term.avatar.animation import (
    AnimationEngine,
    VALID_EMOTIONS,
    parse_and_strip_emotion_tag,
)
from kokoro_term.avatar.backends.factory import create_avatar_backend
from kokoro_term.avatar.backends.terminal_backend import TerminalAvatarBackend
from kokoro_term.avatar.backends.window_backend import WindowAvatarBackend
from kokoro_term.avatar.compositor import AvatarCompositor, AvatarState
from kokoro_term.avatar.lipsync import (
    AmplitudeLipSync,
    VisemeLipSync,
    generate_test_speech_wav,
)
from kokoro_term.avatar.manifest import AvatarManifest
from scripts.slice_expressions import check_misalignment


def test_avatar_manifest_schema():
    manifest_path = Path("characters/roxy/avatar/manifest.yaml")
    assert manifest_path.exists()
    manifest = AvatarManifest.load(manifest_path)

    assert manifest.character == "roxy"
    assert tuple(manifest.canvas_size) == (1024, 1024)
    assert "base" in manifest.layers
    assert "open" in manifest.eye_states
    assert "closed" in manifest.mouth_states
    assert "neutral" in manifest.emotions
    assert manifest.animation.breathing_frequency > 0


def test_avatar_compositor_caching_and_dirty_checking():
    avatar_dir = Path("characters/roxy/avatar")
    compositor = AvatarCompositor(avatar_dir, target_size=(128, 128))

    state1 = AvatarState(emotion="neutral", eye_state="open", mouth_state="closed")
    frame1 = compositor.composite(state1)
    assert isinstance(frame1, Image.Image)
    assert frame1.size == (128, 128)
    initial_count = compositor.composite_count
    assert initial_count >= 1

    # Calling with identical state must hit cache (no recomposition)
    frame2 = compositor.composite(state1)
    assert compositor.composite_count == initial_count
    assert frame1 is frame2

    # Changing state must trigger recomposition
    state2 = AvatarState(emotion="embarrassed", eye_state="half", mouth_state="u", blush=True)
    frame3 = compositor.composite(state2)
    assert compositor.composite_count == initial_count + 1
    assert compositor.last_frame_duration_ms >= 0.0


def test_animation_engine_cycles():
    engine = AnimationEngine()
    engine.set_emotion("embarrassed")

    # Frame 1: breathing check
    state_t0 = engine.update(now=10.0)
    assert state_t0.blush is True
    assert state_t0.emotion == "embarrassed"

    # Frame 2: breathing offset changes with time
    state_t1 = engine.update(now=11.0)
    assert state_t1.offset_y != state_t0.offset_y

    # Test speaking head sway
    engine.set_speaking(True)
    state_speak = engine.update(now=11.2)
    assert state_speak.offset_x != 0.0

    # Test mouth override
    engine.set_mouth_shape("o")
    state_mouth = engine.update(now=11.2)
    assert state_mouth.mouth_state == "o"

    engine.set_mouth_level(0.2)
    state_mouth_lvl = engine.update(now=11.2)
    assert state_mouth_lvl.mouth_state == "u"

    engine.set_speaking(False)


def test_parse_and_strip_emotion_tag():
    # Standard emotion tag
    text = "[emotion:happy] Good morning! Ready to practice water magic?"
    clean, emo = parse_and_strip_emotion_tag(text)
    assert clean == "Good morning! Ready to practice water magic?"
    assert emo == "happy"

    # Tag with synonym / alias
    text2 = "W-what are you saying?! [emotion:flustered]"
    clean2, emo2 = parse_and_strip_emotion_tag(text2)
    assert clean2 == "W-what are you saying?!"
    assert emo2 == "embarrassed"

    # Tag in middle of text
    text3 = "Wait [emotion:thinking] let me check the spellbook."
    clean3, emo3 = parse_and_strip_emotion_tag(text3)
    assert clean3 == "Wait  let me check the spellbook."
    assert emo3 == "thinking"

    # Missing tag
    text4 = "Just regular conversation."
    clean4, emo4 = parse_and_strip_emotion_tag(text4)
    assert clean4 == "Just regular conversation."
    assert emo4 == "neutral"

    # Malformed tag
    text5 = "[emotion:not_a_real_emotion] Hello there."
    clean5, emo5 = parse_and_strip_emotion_tag(text5)
    assert clean5 == "Hello there."
    assert emo5 == "neutral"


def test_amplitude_lipsync_envelope():
    lipsync = AmplitudeLipSync()

    # Generate silence PCM
    silence = np.zeros(2400, dtype=np.int16).tobytes()
    lipsync.load_audio_pcm(silence, sample_rate=24000, chunk_ms=50)
    assert lipsync.get_mouth_shape(0.02) == "closed"

    # Generate high amplitude PCM (simulated loud speech)
    t = np.linspace(0, 0.5, 12000, endpoint=False)
    loud = (np.sin(2 * np.pi * 300 * t) * 30000).astype(np.int16).tobytes()
    lipsync.load_audio_pcm(loud, sample_rate=24000, chunk_ms=50)

    shapes = [lipsync.get_mouth_shape(ti) for ti in np.linspace(0.05, 0.45, 8)]
    assert any(s in ("a", "o") for s in shapes)


def test_viseme_lipsync():
    viseme = VisemeLipSync()
    cues = [
        (0.0, 0.2, "B"),
        (0.2, 0.5, "AA"),
        (0.5, 0.8, "OW"),
        (0.8, 1.0, "M"),
    ]
    viseme.set_cues(cues)
    assert viseme.get_mouth_shape(0.1) == "closed"
    assert viseme.get_mouth_shape(0.3) == "a"
    assert viseme.get_mouth_shape(0.6) == "o"
    assert viseme.get_mouth_shape(0.9) == "closed"
    assert viseme.get_mouth_shape(1.5) == "closed"


def test_generate_test_speech_wav(tmp_path):
    wav_path = tmp_path / "test_speech.wav"
    out = generate_test_speech_wav(wav_path, duration_sec=1.5)
    assert out.exists()
    assert out.stat().st_size > 1000


def test_slicer_misalignment_check():
    # Two identical arrays
    base = np.zeros((100, 100, 4), dtype=np.uint8)
    variant_clean = np.zeros((100, 100, 4), dtype=np.uint8)
    # Modify within allowed box (ymin: 20-40, xmin: 20-40)
    variant_clean[20:40, 20:40, :3] = 200

    misaligned, outside_diffs = check_misalignment(base, variant_clean, (20, 20, 40, 40))
    assert not misaligned
    assert outside_diffs == 0

    # Modify outside allowed box (indicating shift/misalignment)
    variant_drift = variant_clean.copy()
    variant_drift[60:90, 60:90, :3] = 200 # 900 pixels shifted outside box
    misaligned, outside_diffs = check_misalignment(base, variant_drift, (20, 20, 40, 40))
    assert misaligned
    assert outside_diffs >= 80


def test_terminal_avatar_backend():
    avatar_dir = Path("characters/roxy/avatar")
    backend = TerminalAvatarBackend(avatar_dir=avatar_dir, target_size=(20, 20))
    backend.start()
    backend.update_emotion("happy")
    ansi_frame = backend.render_current_ansi_frame(width=20, height=20)
    assert isinstance(ansi_frame, str)
    assert "▀" in ansi_frame
    backend.stop()


def test_avatar_backend_factory():
    # Force terminal mode
    backend_term = create_avatar_backend(mode="terminal", avatar_dir="characters/roxy/avatar")
    assert isinstance(backend_term, TerminalAvatarBackend)

    # Force window mode
    backend_win = create_avatar_backend(mode="window", avatar_dir="characters/roxy/avatar")
    assert isinstance(backend_win, WindowAvatarBackend)
    # Window backend event safety: closing or failed connect must not crash
    backend_win.update_emotion("neutral")
    backend_win.set_speaking(False)
    backend_win.stop()
