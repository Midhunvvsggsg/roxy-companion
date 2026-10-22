from kokoro_term.stt.base import STTProvider, STTResult
from kokoro_term.stt.language import detect_language, get_language_prompt_instruction
from kokoro_term.stt.mock_provider import MockSTTProvider
from kokoro_term.stt.whisper_provider import FasterWhisperProvider

__all__ = [
    "STTProvider",
    "STTResult",
    "detect_language",
    "get_language_prompt_instruction",
    "MockSTTProvider",
    "FasterWhisperProvider",
]
