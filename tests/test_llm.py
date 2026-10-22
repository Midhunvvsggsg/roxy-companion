import pytest
from kokoro_term.config import LLMConfig
from kokoro_term.llm.base import LLMMessage
from kokoro_term.llm.factory import create_llm_provider
from kokoro_term.llm.gemini import GeminiProvider
from kokoro_term.llm.mock import MockProvider
from kokoro_term.llm.openai_compat import OpenAICompatProvider


@pytest.mark.asyncio
async def test_mock_provider_streaming():
    provider = MockProvider(delay=0.0)
    messages = [
        LLMMessage(role="system", content="You are Roxy"),
        LLMMessage(role="user", content="You are so cute and smart!"),
    ]
    chunks = []
    async for chunk in provider.stream_chat(messages):
        chunks.append(chunk)

    full_text = "".join(chunks)
    assert "[emotion:blush]" in full_text
    assert "teasing" in full_text or "teacher" in full_text


@pytest.mark.asyncio
async def test_mock_provider_chat_fallback():
    provider = MockProvider(delay=0.0)
    messages = [
        LLMMessage(role="user", content="Hello Roxy"),
    ]
    reply = await provider.chat(messages)
    assert "[emotion:neutral]" in reply
    assert "Roxy Migurdia" in reply


def test_factory_creates_providers():
    gemini_conf = LLMConfig(provider="gemini", api_key="dummy")
    assert isinstance(create_llm_provider(gemini_conf), GeminiProvider)

    openai_conf = LLMConfig(provider="openai", api_key="dummy")
    assert isinstance(create_llm_provider(openai_conf), OpenAICompatProvider)

    mock_conf = LLMConfig(provider="mock")
    assert isinstance(create_llm_provider(mock_conf), MockProvider)


def test_gemini_message_conversion():
    provider = GeminiProvider(api_key="dummy")
    messages = [
        LLMMessage(role="system", content="System instruction"),
        LLMMessage(role="user", content="Hello"),
        LLMMessage(role="assistant", content="Hi there"),
    ]
    sys_inst, contents = provider._convert_messages(messages)
    assert sys_inst == {"parts": [{"text": "System instruction"}]}
    assert len(contents) == 2
    assert contents[0]["role"] == "user"
    assert contents[1]["role"] == "model"
