import pytest
from kokoro_term.stt.base import STTResult
from kokoro_term.stt.language import detect_language, get_language_prompt_instruction
from kokoro_term.stt.mock_provider import MockSTTProvider
from kokoro_term.stt.whisper_provider import FasterWhisperProvider


def test_malayalam_script_detection():
    assert detect_language("നമസ്കാരം റോക്സി") == "ml"
    assert detect_language("സുഖമാണോ?") == "ml"


def test_manglish_detection():
    assert detect_language("entha ippol cheyyunnathu?") == "ml-Latn"
    assert detect_language("sukhamano chechi") == "ml-Latn"


def test_english_detection():
    assert detect_language("Hello Roxy, how is your magic today?") == "en"


def test_language_prompt_instruction():
    instruction = get_language_prompt_instruction()
    assert "Malayalam" in instruction
    assert "Manglish" in instruction


@pytest.mark.asyncio
async def test_mock_stt_transcribe():
    provider = MockSTTProvider(canned_text="എനിക്ക് ഒരു സംശയം ഉണ്ട്", language="ml")
    result = await provider.transcribe(b"dummy_audio")
    assert result.text == "എനിക്ക് ഒരു സംശയം ഉണ്ട്"
    assert result.language == "ml"
    assert result.confidence == 0.99


def test_whisper_provider_lazy_loading():
    provider = FasterWhisperProvider()
    # Shouldn't raise any exceptions even if weights aren't loaded yet
    available = provider.is_available()
    assert isinstance(available, bool)
