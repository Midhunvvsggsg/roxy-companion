import pytest
from kokoro_term.character import VoiceConfig
from kokoro_term.tts.kokoro_provider import KokoroTTSProvider
from kokoro_term.tts.mock_provider import MockTTSProvider
from kokoro_term.tts.speech_style import apply_speech_style, split_sentences


def test_split_sentences():
    text = "Hello there! How are you doing today? I am preparing water magic. Let us begin."
    sentences = split_sentences(text)
    assert len(sentences) == 4
    assert sentences[0] == "Hello there!"
    assert sentences[1] == "How are you doing today?"


def test_apply_speech_style_flustered_stutter():
    styled = apply_speech_style("What are you saying?!", emotion="blush", stutter_on_blush=True)
    assert "W-what are you saying?!" in styled

    neutral = apply_speech_style("What are you saying?!", emotion="neutral", stutter_on_blush=True)
    assert neutral == "What are you saying?!"


@pytest.mark.asyncio
async def test_mock_tts_streaming_and_amplitude():
    provider = MockTTSProvider(delay_per_sentence=0.0)
    chunks = []
    async for chunk in provider.stream_synthesize("Hello master. Ready for our lesson?"):
        chunks.append(chunk)

    assert len(chunks) >= 4
    # Verify lip-sync amplitude is emitted
    amplitudes = [c.amplitude for c in chunks]
    assert max(amplitudes) > 0.0
    assert any(a > 0.4 for a in amplitudes)


def test_kokoro_provider_availability():
    vc = VoiceConfig()
    provider = KokoroTTSProvider(vc)
    assert isinstance(provider.is_available(), bool)
