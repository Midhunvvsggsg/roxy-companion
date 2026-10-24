from __future__ import annotations

import json
from typing import AsyncIterator
import httpx

from kokoro_term.llm.base import LLMMessage, LLMProvider


class GeminiProvider(LLMProvider):
    """Gemini API provider with SSE streaming."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        base_url: str | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.base_url = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")

    def _convert_messages(self, messages: list[LLMMessage]) -> tuple[dict | None, list[dict]]:
        system_instruction = None
        contents = []

        for msg in messages:
            if msg.role == "system":
                system_instruction = {"parts": [{"text": msg.content}]}
            elif msg.role == "user":
                contents.append({"role": "user", "parts": [{"text": msg.content}]})
            elif msg.role == "assistant":
                contents.append({"role": "model", "parts": [{"text": msg.content}]})

        # Gemini requires at least one user content
        if not contents:
            contents.append({"role": "user", "parts": [{"text": "Hello"}]})

        return system_instruction, contents

    async def stream_chat(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict]] = None,
    ) -> AsyncIterator[str]:
        if not self.api_key:
            yield "[Error: GEMINI_API_KEY is not configured. Please set GEMINI_API_KEY in .env or your environment.]"
            return

        sys_inst, contents = self._convert_messages(messages)
        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
            },
        }
        if sys_inst:
            payload["system_instruction"] = sys_inst
        if tools:
            payload["tools"] = tools

        url = f"{self.base_url}/models/{self.model}:streamGenerateContent?key={self.api_key}&alt=sse"

        timeout = httpx.Timeout(30.0, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload) as response:
                    if response.status_code != 200:
                        error_body = await response.aread()
                        yield f"[Gemini API Error {response.status_code}: {error_body.decode(errors='ignore')}]"
                        return

                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[len("data:"):].strip()
                        if not data_str:
                            continue
                        try:
                            parsed = json.loads(data_str)
                            candidates = parsed.get("candidates", [])
                            if candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                for part in parts:
                                    if "functionCall" in part:
                                        fn_call = part["functionCall"]
                                        fn_name = fn_call.get("name")
                                        fn_args = fn_call.get("args", {})
                                        call_json = json.dumps({"name": fn_name, "arguments": fn_args})
                                        yield f"<tool_call>{call_json}</tool_call>"
                                    elif "text" in part:
                                        yield part["text"]
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            yield f"[Connection Error: {e}]"
