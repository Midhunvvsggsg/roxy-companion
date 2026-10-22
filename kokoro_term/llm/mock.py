from __future__ import annotations

import asyncio
from typing import AsyncIterator

from kokoro_term.llm.base import LLMMessage, LLMProvider


class MockProvider(LLMProvider):
    """Deterministic mock provider for testing and offline development."""

    def __init__(self, character_name: str = "Roxy", delay: float = 0.02):
        self.character_name = character_name
        self.delay = delay

    async def stream_chat(self, messages: list[LLMMessage]) -> AsyncIterator[str]:
        last_user_msg = ""
        for m in reversed(messages):
            if m.role == "user":
                last_user_msg = m.content.lower()
                break

        if "hello" in last_user_msg or "hi" in last_user_msg:
            full_reply = (
                "[emotion:neutral] Greetings. I am Roxy Migurdia. Are you ready for today's lesson, "
                "or did you have a specific question about your terminal environment?"
            )
        elif "cute" in last_user_msg or "love" in last_user_msg or "praise" in last_user_msg:
            full_reply = (
                "[emotion:blush] W-what are you saying so suddenly?! I am your teacher, so please "
                "refrain from teasing me like that! A-ano... let's focus on the task at hand, okay?"
            )
        elif "help" in last_user_msg or "magic" in last_user_msg:
            full_reply = (
                "[emotion:thinking] Let me analyze the situation. As a Water Saint-Class magician, "
                "I advise approaching this methodically. Tell me what error you are encountering."
            )
        else:
            full_reply = (
                f"[emotion:happy] I understand. Regarding '{last_user_msg or 'your inquiry'}', "
                "I will guide you step by step. Let us proceed carefully."
            )

        words = full_reply.split(" ")
        for i, word in enumerate(words):
            chunk = word if i == 0 else " " + word
            yield chunk
            if self.delay > 0:
                await asyncio.sleep(self.delay)
