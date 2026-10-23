from kokoro_term.avatar.animation import AnimationEngine, parse_and_strip_emotion_tag
from kokoro_term.avatar.backends.base import AvatarBackend
from kokoro_term.avatar.backends.factory import create_avatar_backend
from kokoro_term.avatar.backends.terminal_backend import TerminalAvatarBackend
from kokoro_term.avatar.backends.window_backend import WindowAvatarBackend
from kokoro_term.avatar.compositor import AvatarCompositor, AvatarState
from kokoro_term.avatar.lipsync import AmplitudeLipSync, LipSyncEngine, VisemeLipSync, generate_test_speech_wav
from kokoro_term.avatar.manifest import AvatarManifest
from kokoro_term.avatar.renderer import image_to_half_block, render_to_rich_text
from kokoro_term.avatar.terminal import detect_render_protocol

__all__ = [
    "AvatarManifest",
    "AvatarCompositor",
    "AvatarState",
    "AnimationEngine",
    "parse_and_strip_emotion_tag",
    "LipSyncEngine",
    "AmplitudeLipSync",
    "VisemeLipSync",
    "generate_test_speech_wav",
    "AvatarBackend",
    "WindowAvatarBackend",
    "TerminalAvatarBackend",
    "create_avatar_backend",
    "image_to_half_block",
    "render_to_rich_text",
    "detect_render_protocol",
]
