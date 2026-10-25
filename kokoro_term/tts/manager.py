from __future__ import annotations

import logging
from pathlib import Path
from typing import AsyncIterator, Callable, Optional, Dict, Any

from kokoro_term.character import VoiceConfig
from kokoro_term.tts.base import AudioChunk, TTSProvider, TTSProviderError
from kokoro_term.tts.edge_provider import EdgeTTSProvider
from kokoro_term.tts.local_provider import LocalTTSProvider

logger = logging.getLogger("kokoro_term.tts")


class TTSManager:
    """Manages online (Edge-TTS) and offline (Local) TTS engines with seamless auto-fallback.

    - Exposes current provider status: [Voice: cloud] or [Voice: local].
    - Supports pinning tts.provider (prevents silent fallback).
    - Visible notices with failure reasons when fallback occurs.
    - Tracks stage debug files for `/voice debug last`.
    """

    def __init__(
        self,
        voice_config: Optional[VoiceConfig] = None,
        preferred_provider: str = "edge",
        fallback_enabled: bool = True,
        pinned: bool = False,
    ):
        self.voice_config = voice_config or VoiceConfig()
        self.preferred_provider = preferred_provider.lower()
        self.fallback_enabled = fallback_enabled
        self.pinned = pinned

        self.edge_provider = EdgeTTSProvider(self.voice_config)
        self.local_provider = LocalTTSProvider(self.voice_config)

        self._active_mode: str = "cloud" if self.preferred_provider in ("edge", "cloud") else "local"
        self._last_fallback_reason: Optional[str] = None
        self.last_fallback_notice: Optional[str] = None
        self.fallback_listener: Optional[Callable[[str], None]] = None

        # Stage debug storage for `/voice debug last`
        self.last_debug_stages: Dict[str, bytes] = {}
        self.last_synthesized_text: str = ""

    @property
    def active_mode(self) -> str:
        """Return 'cloud' or 'local'."""
        return self._active_mode

    @property
    def status_label(self) -> str:
        """Formatted label for status bars and telemetry: '[Voice: cloud]' or '[Voice: local]'."""
        pin_suffix = " (pinned)" if self.pinned else ""
        return f"[Voice: {self._active_mode}{pin_suffix}]"

    def set_provider(self, provider: str, pin: bool = False) -> None:
        """Manually switch preferred provider ('edge'/'cloud' or 'local') and optionally pin it."""
        clean = provider.strip().lower()
        if clean in ("edge", "cloud", "online"):
            self.preferred_provider = "edge"
            self._active_mode = "cloud"
        else:
            self.preferred_provider = "local"
            self._active_mode = "local"
        self.pinned = pin

    def consume_fallback_notice(self) -> Optional[str]:
        """Return and clear any pending visible fallback notice for the UI."""
        notice = self.last_fallback_notice
        self.last_fallback_notice = None
        return notice

    def _record_fallback(self, error: Exception) -> None:
        self._last_fallback_reason = str(error)
        msg = f"[Voice Fallback] Cloud Edge-TTS failed: {error}. Switched to local provider."
        self.last_fallback_notice = msg
        logger.warning(msg)
        if self.fallback_listener:
            try:
                self.fallback_listener(msg)
            except Exception:
                pass

    async def synthesize_chunk(self, text: str, emotion: str = "neutral") -> AudioChunk:
        """Synthesize a text chunk with visible notice fallback if cloud fails."""
        self.last_synthesized_text = text

        if self._active_mode == "cloud":
            try:
                chunk = await self.edge_provider.synthesize_chunk(text, emotion=emotion)
                if chunk.data:
                    self.last_debug_stages["stage1_raw.wav"] = chunk.data
                    self.last_debug_stages["stage5_final.wav"] = chunk.data
                return chunk
            except Exception as e:
                if self.pinned:
                    logger.error(f"[Voice Error] Cloud TTS failed: {e}. Provider is pinned to cloud.")
                    raise
                self._record_fallback(e)
                if self.fallback_enabled:
                    self._active_mode = "local"
                    local_chunk = await self.local_provider.synthesize_chunk(text, emotion=emotion)
                    if local_chunk.data:
                        self.last_debug_stages["stage1_raw.wav"] = local_chunk.data
                        self.last_debug_stages["stage5_final.wav"] = local_chunk.data
                    return local_chunk
                raise

        # Local provider
        chunk = await self.local_provider.synthesize_chunk(text, emotion=emotion)
        if chunk.data:
            self.last_debug_stages["stage1_raw.wav"] = chunk.data
            self.last_debug_stages["stage5_final.wav"] = chunk.data
        return chunk

    async def stream_synthesize(self, text: str, emotion: str = "neutral") -> AsyncIterator[AudioChunk]:
        """Stream audio chunks with real-time visible notice fallback."""
        self.last_synthesized_text = text

        if self._active_mode == "cloud":
            try:
                async for chunk in self.edge_provider.stream_synthesize(text, emotion=emotion):
                    if chunk.data:
                        self.last_debug_stages["stage1_raw.wav"] = chunk.data
                        self.last_debug_stages["stage5_final.wav"] = chunk.data
                    yield chunk
                return
            except Exception as e:
                if self.pinned:
                    logger.error(f"[Voice Error] Cloud TTS streaming failed: {e}. Provider is pinned to cloud.")
                    raise
                self._record_fallback(e)
                if self.fallback_enabled:
                    self._active_mode = "local"

        async for chunk in self.local_provider.stream_synthesize(text, emotion=emotion):
            if chunk.data:
                self.last_debug_stages["stage1_raw.wav"] = chunk.data
                self.last_debug_stages["stage5_final.wav"] = chunk.data
            yield chunk

    def save_last_debug_stages(self, output_dir: Optional[Path | str] = None) -> list[str]:
        """Save captured audio stage files to disk for `/voice debug last`."""
        target_dir = Path(output_dir or "data/voice_debug_last")
        target_dir.mkdir(parents=True, exist_ok=True)
        saved_files = []

        for name, data in self.last_debug_stages.items():
            fpath = target_dir / name
            with open(fpath, "wb") as f:
                f.write(data)
            saved_files.append(str(fpath))

        return saved_files
