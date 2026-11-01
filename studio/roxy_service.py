#!/usr/bin/env python3
"""Roxy Anime AI Companion Voice, LLM, Vision and Interaction Service.

Provides:
- GET  /api/health: healthcheck
- GET  /api/tts: synthesize cute anime girl Roxy voice with edge-tts
- POST /api/chat: Real Kokoro-Term LLM pipeline with streaming SSE, memory, persona, and relationship state
- GET  /api/debug/last: Exact prompt sent and raw response for the last turn
- GET  /api/mic/devices: Audio input devices list
- POST /api/mic/start: Begin backend recording (sounddevice or PipeWire)
- GET  /api/mic/level: Live audio RMS/peak level
- POST /api/mic/stop: Finish recording, process VAD, and transcribe via STT (English + Malayalam)
- POST /api/mic/test: Record 3 seconds and report peak audio level
- POST /api/screen/capture: Capture display screenshot (Wayland grim / X11 import / PIL)
- GET  /api/screen/preview: Return latest captured screenshot
- POST /api/screen/analyze: Vision model analysis with Gemini
- Static file serving for companion app and studio projects
"""

import asyncio
import base64
import collections
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import wave
from pathlib import Path
from typing import Any, Optional
from aiohttp import web
import edge_tts
import numpy as np

# Add kokoro-term to sys.path
STUDIO_DIR = Path(__file__).resolve().parent
REPO_ROOT = STUDIO_DIR.parent
KOKORO_DIR = REPO_ROOT if (REPO_ROOT / "kokoro_term").exists() else Path("/home/midhun/kokoro-term")
if KOKORO_DIR.exists():
    from dotenv import load_dotenv
    load_dotenv(KOKORO_DIR / ".env")
    sys.path.insert(0, str(KOKORO_DIR))

from kokoro_term.config import load_config
from kokoro_term.character import load_character
from kokoro_term.llm.factory import create_llm_provider
from kokoro_term.llm.base import LLMMessage
from kokoro_term.memory.manager import MemoryManager
from kokoro_term.relationship.models import RelationshipState
from kokoro_term.tools.registry import ToolRegistry
from kokoro_term.tools.permission import PermissionManager
from kokoro_term.tools.audit import AuditLogger
from kokoro_term.tools.resistance import ResistanceManager
from kokoro_term.tools.agent import AgentLoop
from kokoro_term.tools.doctor import run_doctor_checks
from kokoro_term.tools.music import MUSIC_MANAGER
from kokoro_term.tools.tasks import TASK_REGISTRY
from kokoro_term.ui.app import parse_and_strip_emotion_tag
from kokoro_term.tts.speech_style import apply_japanese_slang, apply_pronunciation_map, split_into_clauses
from kokoro_term.tts.audio_processor import trim_audio_silence, measure_fundamental_frequency
from kokoro_term.tts.base import AudioChunk
from kokoro_term.tts.local_provider import LocalTTSProvider
from kokoro_term.tts.edge_provider import EdgeTTSProvider
from kokoro_term.tts.manager import TTSManager
from kokoro_term.tts.alignment import generate_lipsync_cues
from kokoro_term.character import VoiceConfig
from kokoro_term.perf import format_performance_report, VOICE_TELEMETRY, record_ttfa
from kokoro_term.emotional.cognition import EmotionalCognition

EMOTIONAL_COGNITION = EmotionalCognition()

HOST = "127.0.0.1"
PORT = 5174

# Cache directories
CACHE_DIR = os.path.expanduser("~/.cache/roxy_voice")
SCREEN_DIR = os.path.expanduser("~/.cache/roxy_screen")
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(SCREEN_DIR, exist_ok=True)

# App & LLM Initialization
CONFIG = load_config(KOKORO_DIR / "config" / "default_config.yaml" if KOKORO_DIR.exists() else None)
CHARACTER = load_character("roxy", character_dir=KOKORO_DIR / "characters") if KOKORO_DIR.exists() else None
LLM_PROVIDER = create_llm_provider(CONFIG.llm) if CONFIG else None
MEMORY_MANAGER = MemoryManager(CONFIG.memory) if CONFIG and CONFIG.memory and CONFIG.memory.enabled else None
USER_ID = CONFIG.memory.user_id if CONFIG and CONFIG.memory else "Midhun"

# Real Agentic Tool System & Execution Loop
TOOL_REGISTRY = ToolRegistry()
PERMISSION_MANAGER = PermissionManager(CONFIG.tools)
AUDIT_LOGGER = AuditLogger(CONFIG.tools.audit_log_path)
RESISTANCE_MANAGER = ResistanceManager()
AGENT_LOOP = AgentLoop(
    config=CONFIG.tools,
    registry=TOOL_REGISTRY,
    permission=PERMISSION_MANAGER,
    audit=AUDIT_LOGGER,
    resistance=RESISTANCE_MANAGER,
)
CURRENT_STOP_EVENT: Optional[asyncio.Event] = None
PENDING_CONFIRMATIONS: dict[str, dict] = {}

# Global runtime state
STATE = {
    "affection": 56.0,
    "last_emotion": "smile",
    "yandere_intensity": 4,
}
if MEMORY_MANAGER and CHARACTER:
    try:
        rel_state = MEMORY_MANAGER.relationship.get_state(CHARACTER.id, USER_ID)
        STATE["affection"] = rel_state.affection
    except Exception:
        pass

DEBUG_STATE = {
    "last_prompt": "(No prompt sent yet)",
    "last_raw_response": "(No response yet)",
    "last_error": None,
}

# Live Backend Microphone Recording State
MIC_RECORDER = {
    "recording": False,
    "stream": None,
    "buffer": [],  # chunks of int16
    "preroll_buffer": collections.deque(maxlen=6),  # ~384ms circular pre-roll buffer (6 * 1024 / 16000)
    "last_wav": None,  # bytes of the last recorded WAV
    "last_wav_path": os.path.join(tempfile.gettempdir(), "roxy_last_mic.wav"),
    "peak": 0.0,
    "device_idx": None,
    "pipewire_proc": None,
    "pipewire_file": None,
}

LATEST_SCREENSHOT_PATH = os.path.join(SCREEN_DIR, "latest.png")


# ---------------------------------------------------------------------------
# TTS Synthesis (Pluggable Provider: Offline Local Default & Online Edge Cloud)
# ---------------------------------------------------------------------------
VOICE_YAML_PATH = KOKORO_DIR / "characters" / "roxy" / "voice.yaml"

VOICE_CONFIG = {
    "provider": "local",
    "preset": "japanese_anime_girl",
    "voice": "jf_alpha",
    "speed": 1.15,
    "base_pitch": 3,
    "base_rate": 15,
    "pause_comma_ms": 100,
    "pause_sentence_ms": 250,
    "trim_silence": True,
    "lipsync_offset_ms": 0.0,
    "custom_model_path": os.environ.get("ROXY_CUSTOM_VOICE_MODEL", ""),
    "emotion_pace": {},
    "emotion_pitch": {},
    "pronunciation_map": {},
}

AVAILABLE_VOICES = [
    # ── Whisper & ASMR Voices (Consented Open-Source Actors & Breathy Blends) ──
    {
        "id": "af_whisper",
        "name": "Ultimate ASMR Whisper (Neural Blend)",
        "provider": "local",
        "gender": "female",
        "lang": "en-US",
        "category": "whisper",
        "recommended": True,
        "description": "Custom 60% Nicole + 40% Kore master blend. Ultra-soft, breathy, intimate ASMR whisper.",
    },
    {
        "id": "af_nicole",
        "name": "Nicole (American English Whisper)",
        "provider": "local",
        "gender": "female",
        "lang": "en-US",
        "category": "whisper",
        "recommended": True,
        "description": "Renowned for soft, breathy, ASMR-level whispery tone. Consented actor dataset.",
    },
    {
        "id": "af_kore",
        "name": "Kore (Quiet & Soothing Whisper)",
        "provider": "local",
        "gender": "female",
        "lang": "en-US",
        "category": "whisper",
        "recommended": True,
        "description": "Incredibly quiet, gentle, relaxing whisper with warm undertones.",
    },
    {
        "id": "bf_lily",
        "name": "Lily (British English Whisper)",
        "provider": "local",
        "gender": "female",
        "lang": "en-GB",
        "category": "whisper",
        "recommended": True,
        "description": "Delicate, airy, breathy British female whisper.",
    },
    {
        "id": "af_sky",
        "name": "Sky (Ethereal & Breathy)",
        "provider": "local",
        "gender": "female",
        "lang": "en-US",
        "category": "whisper",
        "recommended": False,
        "description": "Dreamy, breathy, soft female voice with gentle delivery.",
    },
    {
        "id": "af_river",
        "name": "River (Tranquil & Calm)",
        "provider": "local",
        "gender": "female",
        "lang": "en-US",
        "category": "whisper",
        "recommended": False,
        "description": "Quiet, peaceful, meditative tone for relaxing sessions.",
    },
    {
        "id": "bf_alice",
        "name": "Alice (Gentle British Reader)",
        "provider": "local",
        "gender": "female",
        "lang": "en-GB",
        "category": "whisper",
        "recommended": False,
        "description": "Quiet, soft-spoken, delicate British storyteller voice.",
    },
    {
        "id": "jf_whisper",
        "name": "Roxy Anime Whisper (Japanese Blend)",
        "provider": "local",
        "gender": "female",
        "lang": "ja/en",
        "category": "whisper",
        "recommended": True,
        "description": "Custom 55% Alpha + 45% Nezumi blend. Cute, breathy anime-style whisper.",
    },
    {
        "id": "jf_nezumi",
        "name": "Nezumi (Delicate Anime Whisper)",
        "provider": "local",
        "gender": "female",
        "lang": "ja/en",
        "category": "whisper",
        "recommended": False,
        "description": "High-clarity, delicate, soft quiet Japanese female voice.",
    },
    {
        "id": "en-US-AriaWhisper",
        "name": "Aria (Edge Neural Whispering Mode)",
        "provider": "edge",
        "gender": "female",
        "lang": "en-US",
        "category": "whisper",
        "recommended": True,
        "description": "Official Microsoft Edge Neural whispering express-as mode. Very realistic soft whisper.",
    },
    {
        "id": "en-US-JennyWhisper",
        "name": "Jenny (Edge Neural Whispering Mode)",
        "provider": "edge",
        "gender": "female",
        "lang": "en-US",
        "category": "whisper",
        "recommended": False,
        "description": "Conversational, natural whispering style via Microsoft Neural speech.",
    },

    # ── Anime & Japanese Voices ──
    {
        "id": "jf_alpha",
        "name": "Alpha (Japanese Anime Female)",
        "provider": "local",
        "gender": "female",
        "lang": "ja/en",
        "category": "anime",
        "recommended": True,
        "description": "Soft, expressive Japanese anime voice (⭐ Default for Roxy)",
    },
    {
        "id": "jf_tebukuro",
        "name": "Tebukuro (Warm Japanese Female)",
        "provider": "local",
        "gender": "female",
        "lang": "ja/en",
        "category": "anime",
        "recommended": False,
        "description": "Gentle, comforting Japanese female voice.",
    },
    {
        "id": "jf_gongitsune",
        "name": "Gongitsune (Japanese Storyteller)",
        "provider": "local",
        "gender": "female",
        "lang": "ja/en",
        "category": "anime",
        "recommended": False,
        "description": "Melodic Japanese female storytelling voice.",
    },
    {
        "id": "ja-JP-NanamiNeural",
        "name": "Nanami (Microsoft Edge Neural)",
        "provider": "edge",
        "gender": "female",
        "lang": "ja-JP",
        "category": "anime",
        "recommended": False,
        "description": "Polite anime-style Japanese female voice.",
    },

    # ── Warm & Expressive English Voices ──
    {
        "id": "af_heart",
        "name": "Heart (Warm American Female)",
        "provider": "local",
        "gender": "female",
        "lang": "en-US",
        "category": "warm",
        "recommended": True,
        "description": "Warm, caring, top-tier English female voice.",
    },
    {
        "id": "af_bella",
        "name": "Bella (Expressive American Female)",
        "provider": "local",
        "gender": "female",
        "lang": "en-US",
        "category": "warm",
        "recommended": False,
        "description": "Lively and expressive English voice.",
    },
    {
        "id": "bf_emma",
        "name": "Emma (Poised British Mentor)",
        "provider": "local",
        "gender": "female",
        "lang": "en-GB",
        "category": "warm",
        "recommended": False,
        "description": "Poised, elegant mentor British voice.",
    },
    {
        "id": "en-US-SoniaNeural",
        "name": "Sonia (Gentle Soothing Tutor)",
        "provider": "edge",
        "gender": "female",
        "lang": "en-US",
        "category": "warm",
        "recommended": False,
        "description": "Soothing, gentle, calm teacher voice.",
    },
    {
        "id": "en-US-AriaNeural",
        "name": "Aria (Microsoft Edge Neural)",
        "provider": "edge",
        "gender": "female",
        "lang": "en-US",
        "category": "warm",
        "recommended": False,
        "description": "Clear, dynamic American English narrator voice.",
    },
    {
        "id": "en-US-AnaNeural",
        "name": "Ana (Youthful American Female)",
        "provider": "edge",
        "gender": "female",
        "lang": "en-US",
        "category": "warm",
        "recommended": False,
        "description": "Cute, high-pitch youthful English voice.",
    },
    {
        "id": "en-US-JennyNeural",
        "name": "Jenny (Conversational American Female)",
        "provider": "edge",
        "gender": "female",
        "lang": "en-US",
        "category": "warm",
        "recommended": False,
        "description": "Friendly, conversational American English voice.",
    },
]


def set_voice_model(voice_id: str) -> dict:
    """Set active voice model across local and cloud providers with persistent saving."""
    clean_id = voice_id.strip()
    matched = next((v for v in AVAILABLE_VOICES if v["id"].lower() == clean_id.lower()), None)
    if matched:
        chosen_id = matched["id"]
        target_provider = matched["provider"]
    else:
        chosen_id = clean_id
        if any(clean_id.startswith(pfx) for pfx in ("jf_", "af_", "bf_", "jm_", "am_", "bm_")):
            target_provider = "local"
        else:
            target_provider = "edge"

    VOICE_CONFIG["voice"] = chosen_id
    VOICE_CONFIG["provider"] = target_provider
    TTS_MANAGER.set_voice(chosen_id)
    TTS_MANAGER.set_provider(target_provider)
    update_runtime_voice_config()
    CHUNKS_CACHE.clear()

    # Persist in characters/roxy/voice.yaml
    if VOICE_YAML_PATH.exists():
        import yaml
        try:
            with open(VOICE_YAML_PATH, "r", encoding="utf-8") as vf:
                vdata = yaml.safe_load(vf) or {}
            vdata["provider"] = target_provider
            vdata["voice_id"] = chosen_id
            with open(VOICE_YAML_PATH, "w", encoding="utf-8") as vf:
                yaml.safe_dump(vdata, vf, sort_keys=False)
        except Exception as e:
            print(f"[Warning] Failed to save voice.yaml: {e}")

    return {
        "status": "ok",
        "voice": chosen_id,
        "provider": target_provider,
        "status_label": TTS_MANAGER.status_label,
        "reply": f"[emotion:smile] Voice model updated to '{chosen_id}' ({target_provider} engine). Applied instantly!",
    }


def load_voice_config() -> None:
    """Load settings from characters/roxy/voice.yaml if present."""
    if VOICE_YAML_PATH.exists():
        import yaml
        try:
            with open(VOICE_YAML_PATH, "r", encoding="utf-8") as vf:
                vdata = yaml.safe_load(vf) or {}
                speed = float(vdata.get("speed", 1.15))
                VOICE_CONFIG.update({
                    "provider": vdata.get("provider", "local"),
                    "preset": vdata.get("preset", "japanese_anime_girl"),
                    "voice": vdata.get("voice_id", "jf_alpha"),
                    "speed": speed,
                    "base_pitch": int(float(vdata.get("pitch", 3))),
                    "base_rate": round((speed - 1.0) * 100),
                    "pause_comma_ms": int(vdata.get("pause_comma_ms", 100)),
                    "pause_sentence_ms": int(vdata.get("pause_sentence_ms", 250)),
                    "trim_silence": bool(vdata.get("trim_silence", True)),
                    "lipsync_offset_ms": float(vdata.get("lipsync_offset_ms", 0.0)),
                    "emotion_pace": vdata.get("emotion_pace", {}),
                    "emotion_pitch": vdata.get("emotion_pitch", {}),
                    "pronunciation_map": vdata.get("pronunciation_map", {}),
                })
        except Exception as e:
            print(f"[Warning] Failed to load voice.yaml: {e}")


def save_voice_preset(preset_name: str) -> None:
    """Save current runtime voice configuration as a preset in voice.yaml."""
    VOICE_CONFIG["preset"] = preset_name
    if VOICE_YAML_PATH.exists():
        import yaml
        try:
            with open(VOICE_YAML_PATH, "r", encoding="utf-8") as vf:
                vdata = yaml.safe_load(vf) or {}
            vdata["provider"] = VOICE_CONFIG.get("provider", "local")
            vdata["preset"] = preset_name
            vdata["voice_id"] = VOICE_CONFIG.get("voice", "jf_alpha")
            vdata["speed"] = VOICE_CONFIG["speed"]
            vdata["pitch"] = VOICE_CONFIG["base_pitch"]
            vdata["pause_comma_ms"] = VOICE_CONFIG["pause_comma_ms"]
            vdata["pause_sentence_ms"] = VOICE_CONFIG["pause_sentence_ms"]
            vdata["trim_silence"] = VOICE_CONFIG["trim_silence"]
            vdata["lipsync_offset_ms"] = VOICE_CONFIG["lipsync_offset_ms"]
            with open(VOICE_YAML_PATH, "w", encoding="utf-8") as vf:
                yaml.safe_dump(vdata, vf, sort_keys=False)
        except Exception as e:
            print(f"[Warning] Failed to save voice preset: {e}")


# Initialize configuration
load_voice_config()

v_cfg = VoiceConfig(
    engine="edge-tts",
    voice_id=VOICE_CONFIG["voice"],
    speed=VOICE_CONFIG["speed"],
    pitch=float(VOICE_CONFIG["base_pitch"]),
    pause_comma_ms=VOICE_CONFIG["pause_comma_ms"],
    pause_sentence_ms=VOICE_CONFIG["pause_sentence_ms"],
    trim_silence=VOICE_CONFIG["trim_silence"],
    lipsync_offset_ms=VOICE_CONFIG["lipsync_offset_ms"],
    emotion_pace=VOICE_CONFIG["emotion_pace"],
    emotion_pitch=VOICE_CONFIG["emotion_pitch"],
    pronunciation_map=VOICE_CONFIG["pronunciation_map"],
)
TTS_MANAGER = TTSManager(
    voice_config=v_cfg,
    preferred_provider=VOICE_CONFIG.get("provider", "local"),
    fallback_enabled=True,
)


def update_runtime_voice_config() -> None:
    """Sync runtime changes to TTS_MANAGER and providers."""
    TTS_MANAGER.voice_config.voice_id = VOICE_CONFIG["voice"]
    TTS_MANAGER.voice_config.speed = VOICE_CONFIG["speed"]
    TTS_MANAGER.voice_config.pitch = float(VOICE_CONFIG["base_pitch"])
    TTS_MANAGER.voice_config.pause_comma_ms = VOICE_CONFIG["pause_comma_ms"]
    TTS_MANAGER.voice_config.pause_sentence_ms = VOICE_CONFIG["pause_sentence_ms"]
    TTS_MANAGER.voice_config.trim_silence = VOICE_CONFIG["trim_silence"]
    if hasattr(TTS_MANAGER.voice_config, "lipsync_offset_ms"):
        TTS_MANAGER.voice_config.lipsync_offset_ms = VOICE_CONFIG["lipsync_offset_ms"]
    TTS_MANAGER.edge_provider.voice_config = TTS_MANAGER.voice_config
    TTS_MANAGER.local_provider.voice_config = TTS_MANAGER.voice_config


CHUNKS_CACHE: dict[str, AudioChunk] = {}


async def synthesize_roxy_speech_chunk(text: str, lang: str = "en", emotion: str = "neutral") -> AudioChunk:
    """Synthesize speech chunk using active TTS provider (offline local default or Edge cloud) with automatic failover."""
    clean, emo = parse_and_strip_emotion_tag(text)
    if emo != "neutral":
        emotion = emo

    spoken_text = apply_pronunciation_map(clean, VOICE_CONFIG.get("pronunciation_map"))
    cur_speed = VOICE_CONFIG.get("speed", 1.15)
    cur_pitch = VOICE_CONFIG.get("base_pitch", 3)
    cur_voice = VOICE_CONFIG.get("voice", "en-US-AriaNeural")
    cur_provider = TTS_MANAGER.active_mode

    # Check cache by provider, voice, lang, emotion, speed, pitch and text
    key = hashlib.sha256(f"{cur_provider}:{cur_voice}:{lang}:{emotion}:{cur_speed:.2f}:{cur_pitch}:{spoken_text}".encode("utf-8")).hexdigest()
    cache_path = os.path.join(CACHE_DIR, f"{key}.bin")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cdata = json.loads(f.read())
            chunk = AudioChunk(
                data=base64.b64decode(cdata["data_b64"]),
                sample_rate=cdata.get("sample_rate", 24000),
                duration_sec=cdata.get("duration_sec", 0.0),
                amplitude=cdata.get("amplitude", 0.0),
                word_timings=cdata.get("word_timings"),
                visemes=cdata.get("visemes"),
                provider_mode=cdata.get("provider_mode", cur_provider),
            )
            record_ttfa(VOICE_TELEMETRY.get("cached_ttfa_ms", 12.0), is_cached=True)
            return chunk
        except Exception:
            pass

    # Synthesize via TTSManager (handles seamless auto-fallback from cloud to local on network/rate-limit error)
    chunk = await TTS_MANAGER.synthesize_chunk(spoken_text, emotion=emotion)

    # Persist in disk cache
    try:
        to_cache = {
            "data_b64": base64.b64encode(chunk.data).decode("utf-8"),
            "sample_rate": chunk.sample_rate,
            "duration_sec": chunk.duration_sec,
            "amplitude": chunk.amplitude,
            "word_timings": chunk.word_timings,
            "visemes": chunk.visemes,
            "provider_mode": chunk.provider_mode,
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(to_cache))
    except Exception:
        pass

    record_ttfa(VOICE_TELEMETRY.get("last_ttfa_ms", 210.0), is_cached=False)
    return chunk


async def synthesize_roxy_speech(text: str, lang: str = "en", emotion: str = "neutral") -> bytes:
    """Return raw audio bytes from synthesized speech chunk."""
    chunk = await synthesize_roxy_speech_chunk(text, lang=lang, emotion=emotion)
    return chunk.data


# ---------------------------------------------------------------------------
# HTTP Handlers
# ---------------------------------------------------------------------------
async def handle_tts(request: web.Request) -> web.Response:
    key = request.query.get("key", "").strip()
    chunk: Optional[AudioChunk] = None
    if key and key in CHUNKS_CACHE:
        chunk = CHUNKS_CACHE[key]
    else:
        text = request.query.get("text", "").strip()
        if not text:
            return web.Response(text="Missing text parameter", status=400)
        lang = request.query.get("lang", "en")
        emotion = request.query.get("emotion", "neutral")
        try:
            chunk = await synthesize_roxy_speech_chunk(text, lang, emotion)
        except Exception as e:
            return web.Response(text=str(e), status=500, headers={"Access-Control-Allow-Origin": "*"})

    if request.query.get("meta", "").lower() == "true":
        return web.json_response({
            "provider": chunk.provider_mode,
            "status_label": TTS_MANAGER.status_label,
            "duration": chunk.duration_sec,
            "word_timings": chunk.word_timings or [],
            "visemes": chunk.visemes or [],
            "audio_b64": base64.b64encode(chunk.data).decode("utf-8"),
        }, headers={"Access-Control-Allow-Origin": "*"})

    content_type = "audio/wav" if chunk.data.startswith(b"RIFF") else "audio/mpeg"
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "public, max-age=86400",
        "X-Voice-Provider": chunk.provider_mode,
        "X-Voice-Label": TTS_MANAGER.status_label,
        "X-Lipsync-Offset": str(VOICE_CONFIG.get("lipsync_offset_ms", 0.0)),
    }
    return web.Response(body=chunk.data, content_type=content_type, headers=headers)


def get_user_preferred_name() -> str:
    """Retrieve user's chosen preferred name from long-term memory facts, defaulting to 'Sir'."""
    if MEMORY_MANAGER and CHARACTER:
        try:
            name = MEMORY_MANAGER.get_preferred_name(CHARACTER.id, USER_ID)
            if name and name.strip():
                return name.strip()
        except Exception:
            pass
    return "Sir"


def strip_tool_artifacts(text: str) -> str:
    """Strip all tool call tags, attributes, code blocks, and JSON tool invocations so TTS never speaks them."""
    if not text:
        return ""
    t = text
    # Strip <tool_call...>...</tool_call> and unclosed <tool_call...>
    t = re.sub(r"<tool_call(?:\s+[^>]*)?>[\s\S]*?(?:<\/tool_call>|$)", "", t, flags=re.IGNORECASE)
    # Strip bracketed action and motion tags
    t = re.sub(r"\[(?:action|tool|motion):[^\]]*\]", "", t, flags=re.IGNORECASE)
    # Strip markdown code blocks
    t = re.sub(r"```(?:json)?\s*[\s\S]*?```", "", t, flags=re.IGNORECASE)
    # Strip inline json tool calls
    t = re.sub(r"\{[^{}]*\"(?:name|tool|action)\"\s*:[^{}]*\}", "", t)
    return t.strip()


async def handle_chat(request: web.Request) -> web.StreamResponse:
    """Real Kokoro-Term Agentic Pipeline.
    Wires conversation to AGENT_LOOP with full tool execution, safety tiers,
    and multi-step plan -> tool call -> observe -> reply loop.
    Supports regular JSON and streaming SSE (via ?stream=true or Accept: text/event-stream).
    """
    global CURRENT_STOP_EVENT
    try:
        body = await request.json()
    except Exception:
        body = {}
    message = body.get("message", "").strip()
    lang = body.get("lang", "en")
    want_stream = request.query.get("stream", "false").lower() == "true" or "text/event-stream" in request.headers.get("Accept", "")
    if not message:
        message = "hello"

    if LLM_PROVIDER is None or CHARACTER is None:
        err_msg = "LLM provider or character configuration not loaded."
        DEBUG_STATE["last_error"] = err_msg
        return web.json_response({"error": f"LLM error: {err_msg}"}, status=503, headers={"Access-Control-Allow-Origin": "*"})

    # Check for in-app commands
    low_msg = message.strip().lower()
    if low_msg == "/stop":
        if CURRENT_STOP_EVENT:
            CURRENT_STOP_EVENT.set()
        return web.json_response({"reply": "Agent execution cancelled.", "stopped": True}, headers={"Access-Control-Allow-Origin": "*"})

    # /settings command support
    if low_msg.startswith("/settings"):
        parts = message.strip().split()
        sub = parts[1].lower() if len(parts) >= 2 else ""
        if sub == "name":
            name_val = " ".join(parts[2:]).strip()
            if name_val:
                if MEMORY_MANAGER and CHARACTER:
                    MEMORY_MANAGER.set_preferred_name(CHARACTER.id, USER_ID, name_val)
                return web.json_response({"reply": f"[emotion:smile] Understood! I will consistently address you as '{name_val}' from now on.", "preferred_name": name_val}, headers={"Access-Control-Allow-Origin": "*"})
            cur = get_user_preferred_name()
            return web.json_response({"reply": f"[emotion:smile] Current preferred name: '{cur}'. Change it with: /settings name <name>.", "preferred_name": cur}, headers={"Access-Control-Allow-Origin": "*"})

        elif sub == "voice":
            if len(parts) >= 3:
                target_voice = parts[2].strip()
                res = set_voice_model(target_voice)
                return web.json_response(res, headers={"Access-Control-Allow-Origin": "*"})
            return web.json_response({"reply": f"Active voice: {VOICE_CONFIG.get('voice')} ({VOICE_CONFIG.get('provider')}). Usage: /settings voice <voice_id> (type /voice list for options)", "voice": VOICE_CONFIG.get("voice")}, headers={"Access-Control-Allow-Origin": "*"})

        elif sub == "speed":
            if len(parts) >= 3:
                try:
                    new_sp = max(0.9, min(1.5, float(parts[2])))
                    VOICE_CONFIG["speed"] = new_sp
                    VOICE_CONFIG["base_rate"] = round((new_sp - 1.0) * 100)
                    update_runtime_voice_config()
                    save_voice_preset(VOICE_CONFIG.get("preset", "japanese_anime_girl"))
                    return web.json_response({"reply": f"[emotion:smile] Voice speed adjusted to {new_sp:.2f}x ({VOICE_CONFIG['base_rate']:+d}%).", "speed": new_sp}, headers={"Access-Control-Allow-Origin": "*"})
                except ValueError:
                    pass
            return web.json_response({"reply": f"Current speed: {VOICE_CONFIG.get('speed', 1.15):.2f}x. Usage: /settings speed <0.9-1.5>"}, headers={"Access-Control-Allow-Origin": "*"})

        else:
            cur_name = get_user_preferred_name()
            prov = TTS_MANAGER.active_mode
            cur_v = VOICE_CONFIG.get("voice", "jf_alpha")
            cur_sp = VOICE_CONFIG.get("speed", 1.15)
            lines = [
                "[emotion:smile] ── Roxy Companion Settings ──",
                f"● Preferred Name: {cur_name} (change: /settings name <name>)",
                f"● Voice Model: {cur_v} [{prov}] (change: /settings voice <id> or /voice set <id>)",
                f"● Voice Speed: {cur_sp:.2f}x (change: /settings speed <0.9-1.5>)",
                f"● Devotion: {STATE.get('yandere_intensity', 4)}/10 (change: /yandere <0-10>)",
                "Tip: Type /voice list to see all available voices.",
            ]
            return web.json_response({"reply": "\n".join(lines)}, headers={"Access-Control-Allow-Origin": "*"})

    if low_msg == "/voice list":
        lines = [
            "[emotion:smile] ── Available Voices ──",
            "Local Neural Kokoro (consented open-source, offline, ultra-fast):",
        ]
        for v in AVAILABLE_VOICES:
            if v["provider"] == "local":
                mark = "● [ACTIVE]" if v["id"] == VOICE_CONFIG.get("voice") else "○"
                lines.append(f"  {mark} {v['id']} - {v['name']} ({v['description']})")
        lines.append("Cloud Edge Neural (online):")
        for v in AVAILABLE_VOICES:
            if v["provider"] == "edge":
                mark = "● [ACTIVE]" if v["id"] == VOICE_CONFIG.get("voice") else "○"
                lines.append(f"  {mark} {v['id']} - {v['name']} ({v['description']})")
        lines.append("Usage: /voice set <voice_id> or /settings voice <voice_id>")
        return web.json_response({"reply": "\n".join(lines), "voices": AVAILABLE_VOICES}, headers={"Access-Control-Allow-Origin": "*"})

    if low_msg.startswith("/voice set"):
        parts = message.strip().split()
        if len(parts) >= 3:
            target_voice = parts[2].strip()
            res = set_voice_model(target_voice)
            return web.json_response(res, headers={"Access-Control-Allow-Origin": "*"})
        return web.json_response({"reply": f"Active voice: {VOICE_CONFIG.get('voice')} ({VOICE_CONFIG.get('provider')}). Usage: /voice set <voice_id>"}, headers={"Access-Control-Allow-Origin": "*"})

    if low_msg.startswith("/voice speed"):
        parts = message.strip().split()
        if len(parts) >= 3:
            try:
                new_sp = float(parts[2])
                new_sp = max(0.9, min(1.5, new_sp))
                VOICE_CONFIG["speed"] = new_sp
                VOICE_CONFIG["base_rate"] = round((new_sp - 1.0) * 100)
                update_runtime_voice_config()
                save_voice_preset(VOICE_CONFIG.get("preset", "japanese_anime_girl"))
                reply = f"[emotion:smile] Voice speed adjusted to {new_sp:.2f}x ({VOICE_CONFIG['base_rate']:+d}% native rate). Applied instantly."
                return web.json_response({"reply": reply, "speed": new_sp}, headers={"Access-Control-Allow-Origin": "*"})
            except ValueError:
                pass
        cur = VOICE_CONFIG["speed"]
        return web.json_response({"reply": f"Current speed: {cur:.2f}x ({VOICE_CONFIG['base_rate']:+d}% rate). Usage: /voice speed <0.9-1.5>"}, headers={"Access-Control-Allow-Origin": "*"})

    if low_msg.startswith("/voice pitch"):
        parts = message.strip().split()
        if len(parts) >= 3:
            try:
                new_p = int(parts[2])
                new_p = max(-50, min(50, new_p))
                VOICE_CONFIG["base_pitch"] = new_p
                update_runtime_voice_config()
                save_voice_preset(VOICE_CONFIG.get("preset", "japanese_anime_girl"))
                reply = f"[emotion:smile] Voice base pitch adjusted to {new_p:+d}Hz. Applied instantly."
                return web.json_response({"reply": reply, "pitch": new_p}, headers={"Access-Control-Allow-Origin": "*"})
            except ValueError:
                pass
        cur_p = VOICE_CONFIG.get("base_pitch", 20)
        return web.json_response({"reply": f"Current pitch: {cur_p:+d}Hz. Usage: /voice pitch <-50 to 50>"}, headers={"Access-Control-Allow-Origin": "*"})

    if low_msg == "/voice reload":
        load_voice_config()
        update_runtime_voice_config()
        CHUNKS_CACHE.clear()
        reply = f"[emotion:smile] Voice settings reloaded from voice.yaml (Preset: {VOICE_CONFIG.get('preset')}, Speed: {VOICE_CONFIG.get('speed'):.2f}x, Pitch: {VOICE_CONFIG.get('base_pitch'):+d}Hz)."
        return web.json_response({"reply": reply}, headers={"Access-Control-Allow-Origin": "*"})

    if low_msg.startswith("/voice save"):
        parts = message.strip().split()
        preset_name = parts[2] if len(parts) >= 3 else "japanese_anime_girl"
        save_voice_preset(preset_name)
        reply = f"[emotion:smile] Voice settings saved to preset '{preset_name}' in voice.yaml."
        return web.json_response({"reply": reply, "preset": preset_name}, headers={"Access-Control-Allow-Origin": "*"})

    if low_msg.startswith("/voice provider"):
        parts = message.strip().split()
        if len(parts) >= 3:
            prov = parts[2].lower()
            TTS_MANAGER.set_provider(prov)
            VOICE_CONFIG["provider"] = TTS_MANAGER.active_mode
            save_voice_preset(VOICE_CONFIG.get("preset", "japanese_anime_girl"))
            reply = f"[emotion:smile] Voice provider set to {TTS_MANAGER.active_mode} ({TTS_MANAGER.status_label})."
            return web.json_response({"reply": reply, "provider": TTS_MANAGER.active_mode, "status_label": TTS_MANAGER.status_label}, headers={"Access-Control-Allow-Origin": "*"})
        return web.json_response({"reply": f"Active provider: {TTS_MANAGER.active_mode} ({TTS_MANAGER.status_label}). Usage: /voice provider <local|edge>"}, headers={"Access-Control-Allow-Origin": "*"})

    if low_msg.startswith("/lipsync calibrate"):
        parts = message.strip().split()
        if len(parts) >= 3:
            try:
                offset_val = float(parts[2])
                VOICE_CONFIG["lipsync_offset_ms"] = offset_val
                update_runtime_voice_config()
                save_voice_preset(VOICE_CONFIG.get("preset", "japanese_anime_girl"))
                reply = f"[emotion:smile] Lip-sync calibration offset set to {offset_val:+.1f} ms."
                return web.json_response({"reply": reply, "offset_ms": offset_val}, headers={"Access-Control-Allow-Origin": "*"})
            except ValueError:
                pass
        return web.json_response({"reply": f"Current lip-sync offset: {VOICE_CONFIG.get('lipsync_offset_ms', 0.0):+.1f} ms. Usage: /lipsync calibrate <-100 to 100>"}, headers={"Access-Control-Allow-Origin": "*"})

    if low_msg == "/doctor":
        doc_res = run_doctor_checks()
        lines = [f"[emotion:smile] Diagnostic results ({'ALL PASSED' if doc_res['passed'] else 'ISSUES DETECTED'}):"]
        for c in doc_res["checks"]:
            mark = "PASS" if c["ok"] else "FAIL"
            fix_str = f" (Fix: {c['fix']})" if c.get("fix") else ""
            lines.append(f"● [{c['name']}]: [{mark}] {c['detail']}{fix_str}")
        return web.json_response({"reply": "\n".join(lines), "doctor": doc_res}, headers={"Access-Control-Allow-Origin": "*"})

    if low_msg.startswith("/music"):
        parts = message.strip().split(maxsplit=2)
        sub = parts[1].lower() if len(parts) >= 2 else "status"
        if sub in ("stop", "off"):
            MUSIC_MANAGER.stop()
            return web.json_response({"reply": "Music stopped.", "status": MUSIC_MANAGER.get_status()}, headers={"Access-Control-Allow-Origin": "*"})
        elif sub in ("pause", "hold"):
            MUSIC_MANAGER.pause()
            return web.json_response({"reply": "Music paused.", "status": MUSIC_MANAGER.get_status()}, headers={"Access-Control-Allow-Origin": "*"})
        elif sub in ("resume", "unpause"):
            MUSIC_MANAGER.resume()
            return web.json_response({"reply": "Music resumed.", "status": MUSIC_MANAGER.get_status()}, headers={"Access-Control-Allow-Origin": "*"})
        elif sub in ("next", "skip"):
            MUSIC_MANAGER.next_track()
            return web.json_response({"reply": "Skipped to next track.", "status": MUSIC_MANAGER.get_status()}, headers={"Access-Control-Allow-Origin": "*"})
        elif sub in ("prev", "previous"):
            MUSIC_MANAGER.prev_track()
            return web.json_response({"reply": "Returned to previous track.", "status": MUSIC_MANAGER.get_status()}, headers={"Access-Control-Allow-Origin": "*"})
        elif sub in ("vol", "volume"):
            vol_val = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 100
            MUSIC_MANAGER.set_volume(vol_val)
            return web.json_response({"reply": f"Music volume set to {vol_val}%.", "status": MUSIC_MANAGER.get_status()}, headers={"Access-Control-Allow-Origin": "*"})
        elif sub == "play":
            q = parts[2] if len(parts) >= 3 else "lofi hip hop"
            res = MUSIC_MANAGER.play(q)
            if res.get("ok"):
                t = res["track"]
                return web.json_response({"reply": f"Playing '{t['title']}' by {t['channel']}.", "status": MUSIC_MANAGER.get_status()}, headers={"Access-Control-Allow-Origin": "*"})
            else:
                return web.json_response({"reply": res.get("detail", "Failed to play.")}, headers={"Access-Control-Allow-Origin": "*"})
        else:
            st = MUSIC_MANAGER.get_status()
            t = st.get("track")
            if t:
                msg = f"Playing: '{t['title']}' by {t['channel']} (Volume: {st['volume']}%, Paused: {st['paused']})."
            else:
                msg = "No music is currently playing."
            return web.json_response({"reply": msg, "status": st}, headers={"Access-Control-Allow-Origin": "*"})

    if low_msg == "/tasks":
        tasks = TASK_REGISTRY.list_tasks()
        if not tasks:
            return web.json_response({"reply": "No active background tasks.", "tasks": []}, headers={"Access-Control-Allow-Origin": "*"})
        lines = [f"Active Background Tasks ({len(tasks)}):"]
        for t in tasks:
            lines.append(f"● [{t['task_id']}] ({t['type']}): {t['name']} (PID: {t['pid']}, Status: {t['status']})")
        return web.json_response({"reply": "\n".join(lines), "tasks": tasks}, headers={"Access-Control-Allow-Origin": "*"})

    if low_msg == "/perf":
        rep = format_performance_report(CONFIG, CHARACTER, CONFIG.memory.db_path, voice_speed=VOICE_CONFIG["speed"])
        return web.json_response({"reply": rep}, headers={"Access-Control-Allow-Origin": "*"})

    if low_msg == "/voice audition":
        rep_file = Path(__file__).resolve().parent.parent / "voice_audition" / "audition_report.md"
        rep_txt = rep_file.read_text(encoding="utf-8") if rep_file.exists() else "Audition report not found."
        return web.json_response({"reply": rep_txt}, headers={"Access-Control-Allow-Origin": "*"})

    # Name Preference Handling: /name <chosen_name> or status check
    if low_msg.startswith("/name"):
        parts = message.split(maxsplit=1)
        if len(parts) > 1 and parts[1].strip():
            chosen_name = parts[1].strip()
            if MEMORY_MANAGER and CHARACTER:
                MEMORY_MANAGER.set_preferred_name(CHARACTER.id, USER_ID, chosen_name)
            return web.json_response({"reply": f"[emotion:smile] Understood! I will consistently address you as '{chosen_name}' from now on.", "preferred_name": chosen_name}, headers={"Access-Control-Allow-Origin": "*"})
        else:
            cur = get_user_preferred_name()
            return web.json_response({"reply": f"[emotion:smile] Your current preferred name is '{cur}'. You can change it with /name <preferred_name> or /settings name <name>.", "preferred_name": cur}, headers={"Access-Control-Allow-Origin": "*"})

    # Detect conversational name statements (e.g., "call me sir", "dont call me midhun call me sir")
    from kokoro_term.memory.manager import extract_preferred_name_from_text
    extracted_name = extract_preferred_name_from_text(message)
    if extracted_name and MEMORY_MANAGER and CHARACTER:
        MEMORY_MANAGER.set_preferred_name(CHARACTER.id, USER_ID, extracted_name)

    CURRENT_STOP_EVENT = asyncio.Event()

    # Prepare Context Window with System Capabilities
    now_str = datetime.datetime.now().strftime("%A, %B %d, %Y, %I:%M %p")
    pref_name = get_user_preferred_name()
    base_prompt = CHARACTER.build_system_prompt(user_name=pref_name, yandere_intensity=STATE.get("yandere_intensity", 4), preferred_name=pref_name)
    tools_doc = TOOL_REGISTRY.generate_system_prompt_documentation()
    mem_context = (
        MEMORY_MANAGER.build_context_injection(CHARACTER.id, USER_ID, current_query=message)
        if MEMORY_MANAGER
        else ""
    )

    # 🧠 Run Option B Subconscious Emotional Cognition (Local Qwen 2.5 1.5B)
    emotional_doc = ""
    try:
        rel_for_turn = MEMORY_MANAGER.relationship.get_state(CHARACTER.id, USER_ID) if MEMORY_MANAGER else RelationshipState(character_id=CHARACTER.id, user_id=USER_ID)
        recent_ctx = [m.content for m in (MEMORY_MANAGER.get_recent_messages(CHARACTER.id, USER_ID, limit=4) if MEMORY_MANAGER else [])]
        await EMOTIONAL_COGNITION.process_turn(
            user_message=message,
            relationship=rel_for_turn,
            recent_context=recent_ctx,
            user_name=pref_name,
        )
        emotional_doc = "\n\n" + EMOTIONAL_COGNITION.build_prompt_injection()
    except Exception:
        pass

    time_context = f"\n\nCurrent Date & Time: {now_str}\n"
    full_prompt = base_prompt + "\n\n" + tools_doc + mem_context + emotional_doc + time_context

    if MEMORY_MANAGER:
        history = MEMORY_MANAGER.get_recent_messages(
            CHARACTER.id, USER_ID, limit=CONFIG.memory.short_term_window
        )
        messages = [LLMMessage(role="system", content=full_prompt)] + history + [LLMMessage(role="user", content=message)]
        rel_state = MEMORY_MANAGER.relationship.get_state(CHARACTER.id, USER_ID)
    else:
        messages = [
            LLMMessage(role="system", content=full_prompt),
            LLMMessage(role="user", content=message),
        ]
        rel_state = RelationshipState(character_id=CHARACTER.id, user_id=USER_ID)

    DEBUG_STATE["last_prompt"] = full_prompt + f"\n\n[User ({USER_ID})]:\n{message}"
    DEBUG_STATE["last_error"] = None

    # Handle Server-Sent Events (SSE) Streaming
    if want_stream:
        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
            },
        )
        await response.prepare(request)

        full_raw_text = ""
        detected_emotion = "neutral"
        emotion_detected = False
        clause_buffer = ""
        clause_index = 0
        t_stream_start = time.perf_counter()
        ttfa_logged = False
        pending_tts_tasks: list[asyncio.Task] = []

        async def _synthesize_task(text_chunk: str, c_idx: int, l_code: str, emo: str):
            chunk_res = await synthesize_roxy_speech_chunk(text_chunk, l_code, emo)
            c_key = hashlib.sha256(f"{c_idx}:{text_chunk}".encode("utf-8")).hexdigest()[:16]
            CHUNKS_CACHE[c_key] = chunk_res
            c_url = f"http://127.0.0.1:5174/api/tts?key={c_key}&text={urllib.parse.quote(text_chunk)}&lang={l_code}&emotion={emo}"
            return {
                "type": "audio_chunk",
                "chunk_index": c_idx,
                "text": text_chunk,
                "audio_url": c_url,
                "provider": chunk_res.provider_mode,
                "status_label": TTS_MANAGER.status_label,
                "duration": chunk_res.duration_sec,
                "word_timings": chunk_res.word_timings,
                "visemes": chunk_res.visemes,
            }

        async def emit_completed_audio_tasks():
            nonlocal ttfa_logged
            while pending_tts_tasks and pending_tts_tasks[0].done():
                task = pending_tts_tasks.pop(0)
                try:
                    payload = await task
                    if payload:
                        if not ttfa_logged:
                            ttfa_ms = (time.perf_counter() - t_stream_start) * 1000.0
                            record_ttfa(ttfa_ms, is_cached=False)
                            ttfa_logged = True
                        await response.write(f"data: {json.dumps(payload)}\n\n".encode("utf-8"))
                except Exception as e:
                    print(f"[Streaming TTS Error] {e}")

        try:
            async for event in AGENT_LOOP.run_agent_loop(
                llm=LLM_PROVIDER,
                messages=messages,
                rel_state=rel_state,
                stop_event=CURRENT_STOP_EVENT,
            ):
                etype = event.get("type")

                if etype == "step":
                    if event.get("step", 1) > 1 and full_raw_text.strip():
                        # Reset clause buffer for follow-up verification step
                        clause_buffer = ""
                        clause_index = 0

                elif etype == "token":
                    full_raw_text += event["token"]
                    clause_buffer += event["token"]

                    if full_raw_text.startswith("[Error:") or full_raw_text.startswith("[Gemini API Error"):
                        err_clean = full_raw_text.strip("[]")
                        err_short = "429 quota exceeded" if "429" in err_clean else err_clean[:80]
                        DEBUG_STATE["last_error"] = err_clean
                        await response.write(f"data: {json.dumps({'type': 'error', 'error': f'LLM error: {err_short}'})}\n\n".encode("utf-8"))
                        await response.write_eof()
                        return response

                    clean_text, emo = parse_and_strip_emotion_tag(full_raw_text)
                    if emo != "neutral" and not emotion_detected:
                        detected_emotion = emo
                        emotion_detected = True
                        await response.write(f"data: {json.dumps({'type': 'emotion', 'emotion': emo})}\n\n".encode("utf-8"))
                    await response.write(f"data: {json.dumps({'type': 'token', 'token': event['token']})}\n\n".encode("utf-8"))

                    # Natural Prosody Streaming to TTS (Section 1 Requirement 3):
                    # Chunk 0 is the first full sentence (or up to an 8+ word natural clause if excessively long).
                    # Later chunks are ALWAYS whole sentences, NEVER split at commas or arbitrary word counts.
                    clean_buf = re.sub(r"\[(?:emotion|motion):[a-zA-Z0-9_-]+\]\s*", "", clause_buffer)
                    clean_buf = re.sub(r"\[(?:action|tool):[^\]]*\]\s*", "", clean_buf)
                    c_words = clean_buf.strip().split()
                    is_ready = False
                    split_idx = -1

                    # Look for full sentence terminator: [.!?] followed by whitespace or trailing boundary
                    m_sent = re.search(r'([.!?]+(?:\s+|$))', clause_buffer)
                    if m_sent:
                        split_idx = m_sent.end()
                        is_ready = True
                    elif clause_index == 0 and len(c_words) >= 12:
                        # Only for chunk 0 if excessively long: split at a natural clause boundary of 8+ words
                        m_clause = re.search(r'([,;—]+\s+)', clause_buffer)
                        if m_clause and len(clause_buffer[:m_clause.end()].split()) >= 8:
                            split_idx = m_clause.end()
                            is_ready = True

                    if is_ready and split_idx > 0:
                        raw_c = clause_buffer[:split_idx]
                        clause_buffer = clause_buffer[split_idx:]
                        clean_c, _ = parse_and_strip_emotion_tag(raw_c)
                        clean_c = strip_tool_artifacts(clean_c)
                        if clean_c and len(clean_c) > 2 and not clean_c.startswith("["):
                            t = asyncio.create_task(_synthesize_task(clean_c, clause_index, lang, detected_emotion))
                            pending_tts_tasks.append(t)
                            clause_index += 1

                    await emit_completed_audio_tasks()

                elif etype == "tool_start":
                    if clause_buffer.strip():
                        clean_c, _ = parse_and_strip_emotion_tag(clause_buffer)
                        clean_c = strip_tool_artifacts(clean_c)
                        if clean_c and len(clean_c) > 2 and not clean_c.startswith("["):
                            t = asyncio.create_task(_synthesize_task(clean_c, clause_index, lang, detected_emotion))
                            pending_tts_tasks.append(t)
                            clause_index += 1
                        clause_buffer = ""
                    await emit_completed_audio_tasks()
                    await response.write(f"data: {json.dumps(event)}\n\n".encode("utf-8"))

                elif etype == "tool_end":
                    await emit_completed_audio_tasks()
                    await response.write(f"data: {json.dumps(event)}\n\n".encode("utf-8"))

                elif etype == "confirm_required":
                    PENDING_CONFIRMATIONS[event["action_id"]] = event
                    await response.write(f"data: {json.dumps(event)}\n\n".encode("utf-8"))
                    await response.write_eof()
                    return response

                elif etype == "stop":
                    await response.write(f"data: {json.dumps(event)}\n\n".encode("utf-8"))
                    await response.write_eof()
                    return response

                elif etype == "done":
                    break

            # Flush any remaining text in clause_buffer
            if clause_buffer.strip():
                clean_c, _ = parse_and_strip_emotion_tag(clause_buffer)
                clean_c = strip_tool_artifacts(clean_c)
                if clean_c and len(clean_c) > 2:
                    t = asyncio.create_task(_synthesize_task(clean_c, clause_index, lang, detected_emotion))
                    pending_tts_tasks.append(t)
                    clause_index += 1

            # Await all pipelined audio chunk tasks in sequence
            while pending_tts_tasks:
                task = pending_tts_tasks.pop(0)
                try:
                    payload = await task
                    if payload:
                        if not ttfa_logged:
                            ttfa_ms = (time.perf_counter() - t_stream_start) * 1000.0
                            record_ttfa(ttfa_ms, is_cached=False)
                            ttfa_logged = True
                        await response.write(f"data: {json.dumps(payload)}\n\n".encode("utf-8"))
                except Exception as e:
                    print(f"[Streaming TTS Flush Error] {e}")

            cleaned_final, final_emo = parse_and_strip_emotion_tag(full_raw_text)
            if final_emo != "neutral":
                detected_emotion = final_emo
            DEBUG_STATE["last_raw_response"] = full_raw_text

            # Update Memory & Relationship State
            if MEMORY_MANAGER and cleaned_final:
                MEMORY_MANAGER.add_message(CHARACTER.id, USER_ID, "user", message)
                MEMORY_MANAGER.add_message(CHARACTER.id, USER_ID, "assistant", cleaned_final)
                new_rel = MEMORY_MANAGER.relationship.evaluate_turn(
                    CHARACTER.id, USER_ID, user_message=message, assistant_emotion=detected_emotion
                )
                STATE["affection"] = new_rel.affection
                if LLM_PROVIDER:
                    asyncio.create_task(
                        MEMORY_MANAGER.extract_facts_from_turn(
                            CHARACTER.id, USER_ID, message, cleaned_final, LLM_PROVIDER
                        )
                    )
                    asyncio.create_task(
                        MEMORY_MANAGER.consolidate_if_needed(
                            CHARACTER.id, USER_ID, LLM_PROVIDER
                        )
                    )
            STATE["last_emotion"] = detected_emotion

            encoded_audio = urllib.parse.quote(cleaned_final or "Understood.")
            final_chunk = None
            if cleaned_final and len(cleaned_final) > 2 and clause_index == 0:
                final_chunk = await synthesize_roxy_speech_chunk(cleaned_final, lang, detected_emotion)
                f_key = hashlib.sha256(f"done:{cleaned_final}".encode("utf-8")).hexdigest()[:16]
                CHUNKS_CACHE[f_key] = final_chunk
                audio_url = f"http://127.0.0.1:5174/api/tts?key={f_key}&text={encoded_audio}&lang={lang}&emotion={detected_emotion}"
            else:
                audio_url = f"http://127.0.0.1:5174/api/tts?text={encoded_audio}&lang={lang}&emotion={detected_emotion}"

            done_payload = {
                "type": "done",
                "reply": cleaned_final or full_raw_text,
                "emotion": detected_emotion,
                "affection": round(STATE["affection"], 1),
                "audio_url": audio_url,
                "provider": TTS_MANAGER.active_mode,
                "status_label": TTS_MANAGER.status_label,
                "duration": final_chunk.duration_sec if final_chunk else None,
                "word_timings": final_chunk.word_timings if final_chunk else None,
                "visemes": final_chunk.visemes if final_chunk else None,
            }
            await response.write(f"data: {json.dumps(done_payload)}\n\n".encode("utf-8"))
            await response.write_eof()
            return response

        except Exception as e:
            err_msg = str(e)
            DEBUG_STATE["last_error"] = err_msg
            await response.write(f"data: {json.dumps({'type': 'error', 'error': f'LLM error: {err_msg}'})}\n\n".encode("utf-8"))
            await response.write_eof()
            return response

    # Non-streaming Standard JSON Response
    try:
        full_raw_text = ""
        tools_executed = []
        pending_confirm = None

        async for event in AGENT_LOOP.run_agent_loop(
            llm=LLM_PROVIDER,
            messages=messages,
            rel_state=rel_state,
            stop_event=CURRENT_STOP_EVENT,
        ):
            etype = event.get("type")
            if etype == "token":
                full_raw_text += event["token"]
            elif etype == "tool_start":
                tools_executed.append(event)
            elif etype == "confirm_required":
                pending_confirm = event
                PENDING_CONFIRMATIONS[event["action_id"]] = event
                break

        if pending_confirm:
            return web.json_response({
                "type": "confirm_required",
                "reply": pending_confirm["objection"],
                "action_id": pending_confirm["action_id"],
                "prompt": pending_confirm["prompt"],
                "tool": pending_confirm["tool"],
                "args": pending_confirm["args"],
            }, headers={"Access-Control-Allow-Origin": "*"})

        cleaned_final, detected_emotion = parse_and_strip_emotion_tag(full_raw_text)
        DEBUG_STATE["last_raw_response"] = full_raw_text

        # Update SQLite Memory & Relationship State
        if MEMORY_MANAGER and cleaned_final:
            MEMORY_MANAGER.add_message(CHARACTER.id, USER_ID, "user", message)
            MEMORY_MANAGER.add_message(CHARACTER.id, USER_ID, "assistant", cleaned_final)
            new_rel = MEMORY_MANAGER.relationship.evaluate_turn(
                CHARACTER.id, USER_ID, user_message=message, assistant_emotion=detected_emotion
            )
            STATE["affection"] = new_rel.affection
            if LLM_PROVIDER:
                asyncio.create_task(
                    MEMORY_MANAGER.extract_facts_from_turn(
                        CHARACTER.id, USER_ID, message, cleaned_final, LLM_PROVIDER
                    )
                )
                asyncio.create_task(
                    MEMORY_MANAGER.consolidate_if_needed(
                        CHARACTER.id, USER_ID, LLM_PROVIDER
                    )
                )
        STATE["last_emotion"] = detected_emotion

        encoded_audio = urllib.parse.quote(cleaned_final or "Understood.")
        chunk = await synthesize_roxy_speech_chunk(cleaned_final or "Understood.", lang, detected_emotion)
        f_key = hashlib.sha256(f"single:{cleaned_final}".encode("utf-8")).hexdigest()[:16]
        CHUNKS_CACHE[f_key] = chunk
        audio_url = f"http://127.0.0.1:5174/api/tts?key={f_key}&text={encoded_audio}&lang={lang}&emotion={detected_emotion}"

        res = {
            "reply": cleaned_final or full_raw_text,
            "raw_response": full_raw_text,
            "emotion": detected_emotion,
            "affection": round(STATE["affection"], 1),
            "user_said": message,
            "tools_executed": tools_executed,
            "audio_url": audio_url,
            "provider": chunk.provider_mode,
            "status_label": TTS_MANAGER.status_label,
            "duration": chunk.duration_sec,
            "word_timings": chunk.word_timings,
            "visemes": chunk.visemes,
        }
        return web.json_response(res, headers={"Access-Control-Allow-Origin": "*"})

    except Exception as e:
        err_msg = str(e)
        DEBUG_STATE["last_error"] = err_msg
        return web.json_response(
            {"error": f"LLM error: {err_msg}"},
            status=500,
            headers={"Access-Control-Allow-Origin": "*"},
        )


async def handle_confirm(request: web.Request) -> web.Response:
    """Approve or deny a pending dangerous action."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    action_id = body.get("action_id", "")
    approved = bool(body.get("approved", False))

    pending = PENDING_CONFIRMATIONS.pop(action_id, None)
    if not pending:
        return web.json_response({"error": "No pending action found for this id."}, status=404, headers={"Access-Control-Allow-Origin": "*"})

    tool_name = pending["tool"]
    args = pending["args"]

    if not approved:
        return web.json_response({"status": "denied", "message": f"Execution of {tool_name} was denied by user."}, headers={"Access-Control-Allow-Origin": "*"})

    # User approved: record approval and execute
    PERMISSION_MANAGER.approve_for_session(tool_name, args)
    tool = TOOL_REGISTRY.get(tool_name)
    if not tool:
        return web.json_response({"error": f"Tool {tool_name} not found."}, status=404, headers={"Access-Control-Allow-Origin": "*"})

    result = await AGENT_LOOP.execute_tool(tool, args, user_confirmed=True)
    out_display = result.output if result.success else f"Error: {result.error}"

    return web.json_response({
        "status": "executed",
        "tool": tool_name,
        "success": result.success,
        "output": out_display,
    }, headers={"Access-Control-Allow-Origin": "*"})


async def handle_stop(request: web.Request) -> web.Response:
    """Interrupt the currently running agent loop task."""
    global CURRENT_STOP_EVENT
    MUSIC_MANAGER.unduck()
    if CURRENT_STOP_EVENT:
        CURRENT_STOP_EVENT.set()
        return web.json_response({"status": "ok", "message": "Agent execution stopped."}, headers={"Access-Control-Allow-Origin": "*"})
    return web.json_response({"status": "ok", "message": "No active agent task."}, headers={"Access-Control-Allow-Origin": "*"})


async def handle_perm(request: web.Request) -> web.Response:
    """Get or update dangerous action policy: ask | allow | block."""
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
        policy = body.get("policy", "")
        msg = PERMISSION_MANAGER.set_policy(policy)
        return web.json_response({"status": "ok", "message": msg, "policy": PERMISSION_MANAGER.dangerous_policy}, headers={"Access-Control-Allow-Origin": "*"})
    else:
        return web.json_response({"policy": PERMISSION_MANAGER.dangerous_policy}, headers={"Access-Control-Allow-Origin": "*"})


async def handle_debug_last(request: web.Request) -> web.Response:
    """Return exact prompt sent and raw response for the last turn."""
    return web.json_response({
        "prompt": DEBUG_STATE["last_prompt"],
        "raw_response": DEBUG_STATE["last_raw_response"],
        "error": DEBUG_STATE["last_error"],
        "character": CHARACTER.name if CHARACTER else "Roxy Migurdia",
        "affection": STATE["affection"],
        "last_emotion": STATE["last_emotion"],
    }, headers={"Access-Control-Allow-Origin": "*"})


# ---------------------------------------------------------------------------
# Backend Microphone Handlers (SoundDevice & PipeWire with Circular Pre-roll)
# ---------------------------------------------------------------------------
def ensure_mic_stream():
    """Ensure background stream is capturing circular pre-roll buffer (~384ms)."""
    if MIC_RECORDER["stream"] is not None:
        return
    try:
        import sounddevice as sd

        def callback(indata, frames, time_info, status):
            samples = indata.flatten()
            peak = float(np.abs(samples).max() / 32768.0)
            MIC_RECORDER["peak"] = round(peak, 3)
            raw = samples.tobytes()
            if MIC_RECORDER["recording"]:
                MIC_RECORDER["buffer"].append(raw)
            else:
                MIC_RECORDER["preroll_buffer"].append(raw)

        stream = sd.InputStream(
            samplerate=16000,
            channels=1,
            dtype="int16",
            callback=callback,
            blocksize=1024,
        )
        stream.start()
        MIC_RECORDER["stream"] = stream
    except Exception:
        pass


async def handle_mic_devices(request: web.Request) -> web.Response:
    """List available audio input devices."""
    devices_info = []
    default_dev = None
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        default_dev = sd.default.device[0]
        for i, d in enumerate(devices):
            if d.get("max_input_channels", 0) > 0:
                devices_info.append({
                    "id": i,
                    "name": d.get("name"),
                    "channels": d.get("max_input_channels"),
                    "sample_rate": d.get("default_samplerate"),
                    "is_default": (i == default_dev),
                })
    except Exception as e:
        # Fallback to pactl sources
        try:
            out = subprocess.check_output(["pactl", "list", "short", "sources"], text=True)
            for line in out.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    devices_info.append({"id": parts[0], "name": parts[1], "is_default": False})
        except Exception:
            devices_info = [{"id": 0, "name": f"Error querying devices: {e}", "is_default": True}]

    return web.json_response({
        "devices": devices_info,
        "default": default_dev,
        "active_source": "backend",
    }, headers={"Access-Control-Allow-Origin": "*"})


async def handle_mic_start(request: web.Request) -> web.Response:
    """Start recording audio on the backend with pre-roll buffer primed."""
    ensure_mic_stream()
    if MIC_RECORDER["recording"]:
        return web.json_response({"status": "already_recording", "peak": MIC_RECORDER["peak"]})

    # Duck background music so mic does not pick up music audio
    MUSIC_MANAGER.duck()

    # Prime recording buffer with circular pre-roll (prevents cutting off initial syllables)
    MIC_RECORDER["buffer"] = list(MIC_RECORDER["preroll_buffer"])
    MIC_RECORDER["recording"] = True

    if MIC_RECORDER["stream"] is not None:
        return web.json_response({
            "status": "recording_started",
            "driver": "sounddevice",
            "preroll_chunks": len(MIC_RECORDER["buffer"]),
        }, headers={"Access-Control-Allow-Origin": "*"})

    # Fallback to PipeWire pw-record if sounddevice failed to stream
    try:
        pw_file = os.path.join(tempfile.gettempdir(), f"roxy_mic_{os.getpid()}.wav")
        proc = subprocess.Popen(["pw-record", "--rate", "16000", "--channels", "1", pw_file])
        MIC_RECORDER["pipewire_proc"] = proc
        MIC_RECORDER["pipewire_file"] = pw_file
        return web.json_response({"status": "recording_started", "driver": "pipewire"}, headers={"Access-Control-Allow-Origin": "*"})
    except Exception as pw_err:
        MIC_RECORDER["recording"] = False
        return web.json_response({"error": f"Failed to start mic capture: {pw_err}"}, status=500, headers={"Access-Control-Allow-Origin": "*"})


async def handle_mic_level(request: web.Request) -> web.Response:
    """Get live audio peak level."""
    return web.json_response({
        "recording": MIC_RECORDER["recording"],
        "level": MIC_RECORDER["peak"],
    }, headers={"Access-Control-Allow-Origin": "*"})


async def handle_mic_stop(request: web.Request) -> web.Response:
    """Stop recording audio, filter dead-air/hallucinations, and transcribe via STT."""
    MUSIC_MANAGER.unduck()
    if not MIC_RECORDER["recording"]:
        return web.json_response({"error": "Microphone is not currently recording"}, status=400, headers={"Access-Control-Allow-Origin": "*"})

    MIC_RECORDER["recording"] = False
    wav_bytes = None

    if MIC_RECORDER["stream"]:
        raw_pcm = b"".join(MIC_RECORDER["buffer"])
        MIC_RECORDER["buffer"] = []
        if raw_pcm:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(raw_pcm)
            wav_bytes = buf.getvalue()

    elif MIC_RECORDER["pipewire_proc"]:
        proc = MIC_RECORDER["pipewire_proc"]
        pw_file = MIC_RECORDER["pipewire_file"]
        try:
            proc.terminate()
            proc.wait(timeout=1.0)
            if pw_file and os.path.exists(pw_file):
                with open(pw_file, "rb") as f:
                    wav_bytes = f.read()
                os.remove(pw_file)
        except Exception:
            pass
        MIC_RECORDER["pipewire_proc"] = None
        MIC_RECORDER["pipewire_file"] = None

    if wav_bytes:
        MIC_RECORDER["last_wav"] = wav_bytes
        try:
            with open(MIC_RECORDER["last_wav_path"], "wb") as f:
                f.write(wav_bytes)
        except Exception:
            pass

    if not wav_bytes or len(wav_bytes) < 44:
        return web.json_response({
            "text": "",
            "unclear": False,
            "language": "en",
            "confidence": 0.0,
            "message": "No speech detected",
        }, headers={"Access-Control-Allow-Origin": "*"})

    # STT Transcription with faster-whisper, Silero-VAD, and Manglish support
    try:
        from kokoro_term.stt.whisper_provider import FasterWhisperProvider
        stt = FasterWhisperProvider(model_size="tiny")
        res = await stt.transcribe(wav_bytes, sample_rate=16000)

        pref_name = get_user_preferred_name()
        # In-character response on unclear / dead-air audio
        if res.is_unclear:
            return web.json_response({
                "text": "",
                "unclear": True,
                "language": res.language,
                "confidence": round(res.confidence, 2),
                "in_character_reply": f"Could you repeat that, {pref_name}? I didn't quite catch that.",
            }, headers={"Access-Control-Allow-Origin": "*"})

        return web.json_response({
            "text": res.text.strip(),
            "unclear": False,
            "low_confidence": getattr(res, "is_low_confidence", False) or res.confidence < 0.65,
            "language": res.language,
            "confidence": round(res.confidence, 2),
            "duration": round(res.duration_sec, 2),
        }, headers={"Access-Control-Allow-Origin": "*"})
    except Exception as e:
        return web.json_response({"error": f"STT failed: {e}"}, status=500, headers={"Access-Control-Allow-Origin": "*"})


async def handle_mic_play(request: web.Request) -> web.Response:
    """Play the last recorded audio back through system speakers for sanity check."""
    wav_path = MIC_RECORDER.get("last_wav_path")
    if not wav_path or not os.path.exists(wav_path) or os.path.getsize(wav_path) < 44:
        return web.json_response({"error": "No recent microphone recording found. Record something first with F2 or Space."}, status=404, headers={"Access-Control-Allow-Origin": "*"})

    player = None
    for cmd in ["pw-play", "paplay", "aplay", "mpv"]:
        if shutil.which(cmd):
            player = cmd
            break

    if player:
        try:
            if player == "mpv":
                subprocess.Popen([player, "--no-terminal", "--volume=100", wav_path])
            else:
                subprocess.Popen([player, wav_path])
            return web.json_response({
                "status": "playing",
                "player": player,
                "file": wav_path,
                "size_bytes": os.path.getsize(wav_path),
            }, headers={"Access-Control-Allow-Origin": "*"})
        except Exception as e:
            return web.json_response({"error": f"Failed to play audio with {player}: {e}"}, status=500, headers={"Access-Control-Allow-Origin": "*"})
    return web.json_response({"error": "No audio player tool found (pw-play, paplay, aplay, mpv)"}, status=500, headers={"Access-Control-Allow-Origin": "*"})


async def handle_mic_last_recording(request: web.Request) -> web.Response:
    """Download or stream the last captured microphone audio file."""
    wav_path = MIC_RECORDER.get("last_wav_path")
    if not wav_path or not os.path.exists(wav_path) or os.path.getsize(wav_path) < 44:
        return web.Response(status=404, text="No recording available", headers={"Access-Control-Allow-Origin": "*"})
    with open(wav_path, "rb") as f:
        data = f.read()
    return web.Response(body=data, content_type="audio/wav", headers={"Access-Control-Allow-Origin": "*"})


async def handle_mic_test(request: web.Request) -> web.Response:
    """Sample audio level across 1.5 seconds and return peak and auditory status."""
    ensure_mic_stream()
    peaks = []
    for _ in range(15):
        peaks.append(MIC_RECORDER["peak"])
        await asyncio.sleep(0.1)
    max_peak = max(peaks) if peaks else 0.0
    return web.json_response({
        "status": "ok",
        "duration": 1.5,
        "peak": round(max_peak, 3),
        "audible": max_peak > 0.015,
        "device": "PipeWire/ALSA Default Microphone",
    }, headers={"Access-Control-Allow-Origin": "*"})


# ---------------------------------------------------------------------------
# Screen Awareness & Vision Tool
# ---------------------------------------------------------------------------
async def handle_screen_capture(request: web.Request) -> web.Response:
    """Capture a screenshot of the user's active display (Wayland grim / X11 import / PIL)."""
    captured = False

    # 1. Wayland grim
    if shutil.which("grim"):
        ret = subprocess.run(["grim", LATEST_SCREENSHOT_PATH])
        if ret.returncode == 0 and os.path.exists(LATEST_SCREENSHOT_PATH):
            captured = True

    # 2. X11 import
    if not captured and shutil.which("import"):
        ret = subprocess.run(["import", "-window", "root", LATEST_SCREENSHOT_PATH])
        if ret.returncode == 0 and os.path.exists(LATEST_SCREENSHOT_PATH):
            captured = True

    # 3. PIL ImageGrab
    if not captured:
        try:
            from PIL import ImageGrab
            im = ImageGrab.grab()
            im.save(LATEST_SCREENSHOT_PATH)
            captured = True
        except Exception:
            pass

    if not captured:
        return web.json_response({"error": "Unable to capture screen. Install 'grim' (Wayland) or 'imagemagick' (X11)."}, status=500, headers={"Access-Control-Allow-Origin": "*"})

    return web.json_response({
        "status": "ok",
        "url": "/api/screen/preview",
        "path": LATEST_SCREENSHOT_PATH,
        "timestamp": datetime.datetime.now().isoformat(),
    }, headers={"Access-Control-Allow-Origin": "*"})


async def handle_screen_preview(request: web.Request) -> web.Response:
    """Serve the latest captured screenshot image."""
    if not os.path.exists(LATEST_SCREENSHOT_PATH):
        return web.Response(text="No screenshot available", status=404, headers={"Access-Control-Allow-Origin": "*"})
    return web.FileResponse(LATEST_SCREENSHOT_PATH, headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache"})


async def handle_screen_analyze(request: web.Request) -> web.Response:
    """Describe the latest screenshot using Gemini Vision in character."""
    if not os.path.exists(LATEST_SCREENSHOT_PATH):
        return web.json_response({"error": "No screenshot captured. Capture first."}, status=400, headers={"Access-Control-Allow-Origin": "*"})

    try:
        body = await request.json()
    except Exception:
        body = {}
    user_query = body.get("query", "Describe what is on my screen right now.")

    api_key = CONFIG.llm.get_effective_api_key() if CONFIG and CONFIG.llm else os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return web.json_response({"error": "GEMINI_API_KEY is not configured."}, status=500, headers={"Access-Control-Allow-Origin": "*"})

    with open(LATEST_SCREENSHOT_PATH, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("ascii")

    vision_prompt = (
        f"You are Roxy Migurdia, looking at the user's active computer screen to assist them.\n"
        f"Persona: Water Saint-Class Magician, thoughtful, observant, helpful teacher.\n"
        f"Rule: Start your reply with exactly one emotion tag (e.g. [emotion:thinking], [emotion:smile], [emotion:surprise]).\n"
        f"User query: {user_query}\n"
        f"Examine the screen screenshot and describe what application, code, document, or interface is open in detail."
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "parts": [
                {"text": vision_prompt},
                {"inline_data": {"mime_type": "image/png", "data": img_b64}},
            ]
        }],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 800},
    }

    import httpx
    async with httpx.AsyncClient(timeout=30.0) as client:
        last_error = "Unknown error"
        for model in ["gemini-2.5-flash", "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash-lite"]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                    clean_text, emo = parse_and_strip_emotion_tag(raw_text)
                    encoded_audio = urllib.parse.quote(clean_text)

                    return web.json_response({
                        "reply": clean_text,
                        "emotion": emo,
                        "image_url": "/api/screen/preview",
                        "audio_url": f"http://127.0.0.1:5174/api/tts?text={encoded_audio}&lang=en",
                    }, headers={"Access-Control-Allow-Origin": "*"})
                else:
                    last_error = f"Vision LLM error {res.status_code}: {res.text}"
            except Exception as e:
                last_error = str(e)

        return web.json_response({"error": last_error}, status=500, headers={"Access-Control-Allow-Origin": "*"})


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "ok",
        "service": "roxy-companion-ai",
        "affection": STATE["affection"],
        "character": CHARACTER.name if CHARACTER else "Roxy Migurdia",
        "llm_provider": CONFIG.llm.provider if CONFIG else "gemini",
        "backend_mic": True,
    }, headers={"Access-Control-Allow-Origin": "*"})


async def handle_voice_speed(request: web.Request) -> web.Response:
    """Get or set current voice speed (0.9 to 1.5)."""
    if request.method == "POST":
        try:
            body = await request.json()
            val = float(body.get("speed", 1.28))
        except Exception:
            val = float(request.query.get("speed", 1.28))
        val = max(0.9, min(1.5, val))
        VOICE_CONFIG["speed"] = val
        VOICE_CONFIG["base_rate"] = round((val - 1.0) * 100)
        update_runtime_voice_config()
        save_voice_preset(VOICE_CONFIG.get("preset", "young_japanese_girl_energetic"))
        return web.json_response({
            "status": "ok",
            "speed": val,
            "rate": f"{VOICE_CONFIG['base_rate']:+d}%",
            "message": f"Voice speed set to {val:.2f}x ({VOICE_CONFIG['base_rate']:+d}% native rate). Applied instantly.",
        }, headers={"Access-Control-Allow-Origin": "*"})

    val = VOICE_CONFIG["speed"]
    return web.json_response({
        "status": "ok",
        "speed": val,
        "rate": f"{VOICE_CONFIG['base_rate']:+d}%",
    }, headers={"Access-Control-Allow-Origin": "*"})


async def handle_voice_pitch(request: web.Request) -> web.Response:
    """Get or set base voice pitch in Hz (-50 to +50)."""
    if request.method == "POST":
        try:
            body = await request.json()
            val = int(body.get("pitch", 20))
        except Exception:
            val = int(request.query.get("pitch", 20))
        val = max(-50, min(50, val))
        VOICE_CONFIG["base_pitch"] = val
        update_runtime_voice_config()
        save_voice_preset(VOICE_CONFIG.get("preset", "young_japanese_girl_energetic"))
        return web.json_response({
            "status": "ok",
            "pitch": val,
            "pitch_str": f"{val:+d}Hz",
            "message": f"Voice base pitch set to {val:+d}Hz. Applied instantly.",
        }, headers={"Access-Control-Allow-Origin": "*"})

    val = VOICE_CONFIG.get("base_pitch", 20)
    return web.json_response({
        "status": "ok",
        "pitch": val,
        "pitch_str": f"{val:+d}Hz",
    }, headers={"Access-Control-Allow-Origin": "*"})


async def handle_voice_reload(request: web.Request) -> web.Response:
    """Reload voice.yaml configuration and invalidate caches."""
    load_voice_config()
    update_runtime_voice_config()
    CHUNKS_CACHE.clear()
    return web.json_response({
        "status": "ok",
        "preset": VOICE_CONFIG.get("preset"),
        "voice": VOICE_CONFIG.get("voice"),
        "speed": VOICE_CONFIG.get("speed"),
        "base_pitch": VOICE_CONFIG.get("base_pitch"),
        "message": "Voice configuration reloaded from voice.yaml.",
    }, headers={"Access-Control-Allow-Origin": "*"})


IDLE_REMARKS = {
    "night": [
        ("[emotion:shy] {user_name}... it's getting quite late! Even high-class magicians need their sleep, so promise me you won't stay up too late, okay?", "shy"),
        ("[emotion:smile] {user_name}, you've worked so diligently today! The terminal will still be waiting tomorrow, so please make sure to get some good rest tonight, okay?", "smile"),
        ("[emotion:shy] Mou, working this late again, {user_name}? If you wear yourself out, I'll have no choice but to scold you, so take care of yourself!", "shy"),
    ],
    "day": [
        ("[emotion:smile] Yosh! Quick hydration check, {user_name}! You've been coding with so much focus—make sure to drink some water and stretch a bit, okay?", "smile"),
        ("[emotion:smile] How is your code coming along, {user_name}? Remember to take short breathers so your magic stays sharp and clear!", "smile"),
        ("[emotion:smile] Fufu, staring intently at your screen again, {user_name}? Don't forget to blink and rest your eyes for a moment!", "smile"),
    ],
    "evening": [
        ("[emotion:smile] Good evening, {user_name}! You've accomplished so much today. Remember to eat a good dinner and take a breather, okay?", "smile"),
        ("[emotion:smile] {user_name}! Just a little reminder to relax your shoulders and take a deep breath. You're doing amazing today!", "smile"),
    ],
}
IDLE_COUNTER = 0


async def handle_idle(request: web.Request) -> web.Response:
    """Return a spontaneous, in-character companion check-in when user has been idle."""
    global IDLE_COUNTER
    hour = datetime.datetime.now().hour
    if hour >= 22 or hour < 5:
        category = "night"
    elif hour >= 18:
        category = "evening"
    else:
        category = "day"

    pool = IDLE_REMARKS.get(category, IDLE_REMARKS["day"])
    raw_template, emo = pool[IDLE_COUNTER % len(pool)]
    IDLE_COUNTER += 1

    pref_name = get_user_preferred_name()
    text_with_emo = raw_template.format(user_name=pref_name)

    clean_text, detected_emo = parse_and_strip_emotion_tag(text_with_emo)
    final_emo = detected_emo if detected_emo != "neutral" else emo
    lang = request.query.get("lang", "en")
    chunk = await synthesize_roxy_speech_chunk(clean_text, lang, final_emo)
    f_key = hashlib.sha256(f"idle:{clean_text}:{final_emo}".encode("utf-8")).hexdigest()[:16]
    CHUNKS_CACHE[f_key] = chunk
    audio_url = f"http://127.0.0.1:5174/api/tts?key={f_key}&text={urllib.parse.quote(clean_text)}&lang={lang}&emotion={final_emo}"

    return web.json_response({
        "status": "ok",
        "reply": clean_text,
        "raw_text": text_with_emo,
        "emotion": final_emo,
        "audio_url": audio_url,
        "provider": chunk.provider_mode,
        "status_label": TTS_MANAGER.status_label,
        "duration": chunk.duration_sec,
        "word_timings": chunk.word_timings,
        "visemes": chunk.visemes,
        "affection": round(STATE["affection"], 1),
    }, headers={"Access-Control-Allow-Origin": "*"})


async def handle_voice_save(request: web.Request) -> web.Response:
    """Save current voice settings as a named preset in voice.yaml."""
    try:
        body = await request.json()
        preset = body.get("preset", "young_japanese_girl_energetic").strip()
    except Exception:
        preset = request.query.get("preset", "young_japanese_girl_energetic").strip()
    save_voice_preset(preset)
    return web.json_response({
        "status": "ok",
        "preset": preset,
        "message": f"Voice preset '{preset}' successfully saved.",
    }, headers={"Access-Control-Allow-Origin": "*"})


async def handle_perf(request: web.Request) -> web.Response:
    """Return performance and time-to-first-audio latency telemetry."""
    rep = format_performance_report(CONFIG, CHARACTER, CONFIG.memory.db_path, voice_speed=VOICE_CONFIG["speed"])
    return web.json_response({
        "status": "ok",
        "report": rep,
        "telemetry": VOICE_TELEMETRY,
        "voice_speed": VOICE_CONFIG["speed"],
        "voice_rate": f"{VOICE_CONFIG['base_rate']:+d}%",
    }, headers={"Access-Control-Allow-Origin": "*"})


async def handle_voice_audition(request: web.Request) -> web.Response:
    """Return voice audition report and sample links."""
    candidates = [
        Path(__file__).resolve().parent.parent / "voice_audition" / "audition_report.md",
        KOKORO_DIR / "voice_audition" / "audition_report.md",
        Path(__file__).resolve().parent.parent / "samples" / "audition" / "audition_report.md",
    ]
    report_md = ""
    for c in candidates:
        if c.exists():
            report_md = c.read_text(encoding="utf-8")
            break

    return web.json_response({
        "status": "ok",
        "current_preset": VOICE_CONFIG["preset"],
        "voice": VOICE_CONFIG["voice"],
        "speed": VOICE_CONFIG["speed"],
        "base_pitch": VOICE_CONFIG["base_pitch"],
        "base_rate": VOICE_CONFIG["base_rate"],
        "report_markdown": report_md,
    }, headers={"Access-Control-Allow-Origin": "*"})


async def handle_doctor(request: web.Request) -> web.Response:
    """Run environment and tool execution diagnostics."""
    report = run_doctor_checks()
    return web.json_response(report, headers={"Access-Control-Allow-Origin": "*"})


async def handle_music_control(request: web.Request) -> web.Response:
    """Control background music playback."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    act = body.get("action", "").lower()
    val = body.get("value")
    if act in ("pause", "hold"):
        res = MUSIC_MANAGER.pause()
    elif act in ("resume", "play"):
        res = MUSIC_MANAGER.resume()
    elif act in ("stop", "off"):
        res = MUSIC_MANAGER.stop()
    elif act in ("next", "skip"):
        res = MUSIC_MANAGER.next_track()
    elif act in ("prev", "previous"):
        res = MUSIC_MANAGER.prev_track()
    elif act in ("vol", "volume"):
        res = MUSIC_MANAGER.set_volume(int(val) if val else 100)
    elif act == "mute":
        res = MUSIC_MANAGER.mute(True)
    elif act == "unmute":
        res = MUSIC_MANAGER.mute(False)
    else:
        res = {"ok": True, "status": MUSIC_MANAGER.get_status()}
    return web.json_response(res, headers={"Access-Control-Allow-Origin": "*"})


async def handle_music_toggle(request: web.Request) -> web.Response:
    res = MUSIC_MANAGER.toggle()
    return web.json_response(res, headers={"Access-Control-Allow-Origin": "*"})


async def handle_music_stop(request: web.Request) -> web.Response:
    res = MUSIC_MANAGER.stop()
    return web.json_response(res, headers={"Access-Control-Allow-Origin": "*"})


async def handle_music_status(request: web.Request) -> web.Response:
    return web.json_response(MUSIC_MANAGER.get_status(), headers={"Access-Control-Allow-Origin": "*"})


async def handle_music_duck(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        data = {}
    duck = bool(data.get("duck", True))
    if duck:
        MUSIC_MANAGER.duck()
    else:
        MUSIC_MANAGER.unduck()
    return web.json_response({"ok": True, "ducked": MUSIC_MANAGER.is_ducked}, headers={"Access-Control-Allow-Origin": "*"})


async def handle_tasks_list(request: web.Request) -> web.Response:
    return web.json_response({"tasks": TASK_REGISTRY.list_tasks()}, headers={"Access-Control-Allow-Origin": "*"})


def get_yandere_tier_name(intensity: int) -> str:
    if intensity == 0:
        return "Professional Mentor (Safe Word / Relax Mode)"
    elif intensity <= 3:
        return "Gentle Protective Companion"
    elif intensity <= 6:
        return "Devoted Possessive Partner (Default)"
    elif intensity <= 8:
        return "Deeply Obsessive & Doting"
    else:
        return "Total Psychological Attachment"


async def handle_status(request: web.Request) -> web.Response:
    """Return comprehensive system, character, voice, and yandere status."""
    pref_name = get_user_preferred_name()
    return web.json_response({
        "status": "ok",
        "character": CHARACTER.name if CHARACTER else "Roxy Migurdia",
        "title": CHARACTER.title if CHARACTER else "Water Saint-Class Magician",
        "user_name": pref_name,
        "preferred_name": pref_name,
        "affection": round(STATE["affection"], 1),
        "emotion": STATE["last_emotion"],
        "yandere_intensity": STATE.get("yandere_intensity", 4),
        "yandere_tier": get_yandere_tier_name(STATE.get("yandere_intensity", 4)),
        "voice_provider": TTS_MANAGER.active_mode,
        "voice_status_label": TTS_MANAGER.status_label,
        "voice_preset": VOICE_CONFIG["preset"],
        "voice_model": VOICE_CONFIG["voice"],
        "voice_speed": VOICE_CONFIG["speed"],
        "voice_pitch": VOICE_CONFIG.get("base_pitch", 20),
        "lipsync_offset_ms": VOICE_CONFIG.get("lipsync_offset_ms", 0.0),
        "llm_provider": CONFIG.llm.provider if CONFIG else "gemini",
        "llm_model": CONFIG.llm.model if CONFIG else "gemini-flash-lite-latest",
        "dangerous_policy": PERMISSION_MANAGER.dangerous_policy if PERMISSION_MANAGER else "ask",
    }, headers={"Access-Control-Allow-Origin": "*"})


async def handle_settings(request: web.Request) -> web.Response:
    """Get or update Roxy system settings (name, voice, speed, pitch, provider)."""
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}

        updated = {}
        if "name" in body and body["name"]:
            chosen_name = str(body["name"]).strip()
            if MEMORY_MANAGER and CHARACTER:
                MEMORY_MANAGER.set_preferred_name(CHARACTER.id, USER_ID, chosen_name)
            updated["preferred_name"] = chosen_name

        if "voice" in body and body["voice"]:
            res = set_voice_model(str(body["voice"]).strip())
            updated["voice"] = res["voice"]
            updated["provider"] = res["provider"]

        if "speed" in body:
            try:
                sp = float(body["speed"])
                sp = max(0.9, min(1.5, sp))
                VOICE_CONFIG["speed"] = sp
                VOICE_CONFIG["base_rate"] = round((sp - 1.0) * 100)
                update_runtime_voice_config()
                save_voice_preset(VOICE_CONFIG.get("preset", "japanese_anime_girl"))
                updated["speed"] = sp
            except ValueError:
                pass

        pref_name = get_user_preferred_name()
        return web.json_response({
            "status": "ok",
            "message": "Settings updated successfully.",
            "preferred_name": pref_name,
            "voice": VOICE_CONFIG.get("voice", "jf_alpha"),
            "provider": TTS_MANAGER.active_mode,
            "status_label": TTS_MANAGER.status_label,
            "speed": VOICE_CONFIG.get("speed", 1.15),
            "updated": updated,
        }, headers={"Access-Control-Allow-Origin": "*"})

    pref_name = get_user_preferred_name()
    return web.json_response({
        "status": "ok",
        "preferred_name": pref_name,
        "voice": VOICE_CONFIG.get("voice", "jf_alpha"),
        "provider": TTS_MANAGER.active_mode,
        "status_label": TTS_MANAGER.status_label,
        "speed": VOICE_CONFIG.get("speed", 1.15),
        "pitch": VOICE_CONFIG.get("base_pitch", 3),
        "preset": VOICE_CONFIG.get("preset", "japanese_anime_girl"),
        "llm_provider": CONFIG.llm.provider if CONFIG else "ollama",
        "llm_model": CONFIG.llm.model if CONFIG else "qwen2.5:3b",
        "yandere_intensity": STATE.get("yandere_intensity", 4),
        "available_voices": AVAILABLE_VOICES,
    }, headers={"Access-Control-Allow-Origin": "*"})


async def handle_voice_list(request: web.Request) -> web.Response:
    """Return catalog of available local and cloud voices."""
    return web.json_response({
        "status": "ok",
        "current_voice": VOICE_CONFIG.get("voice", "jf_alpha"),
        "current_provider": TTS_MANAGER.active_mode,
        "status_label": TTS_MANAGER.status_label,
        "voices": AVAILABLE_VOICES,
    }, headers={"Access-Control-Allow-Origin": "*"})


async def handle_voice_set(request: web.Request) -> web.Response:
    """Set active voice model."""
    try:
        body = await request.json()
        target_voice = body.get("voice", "").strip()
    except Exception:
        target_voice = request.query.get("voice", "").strip()

    if not target_voice:
        return web.json_response({"error": "Missing 'voice' parameter"}, status=400, headers={"Access-Control-Allow-Origin": "*"})

    res = set_voice_model(target_voice)
    return web.json_response(res, headers={"Access-Control-Allow-Origin": "*"})


async def handle_voice_provider(request: web.Request) -> web.Response:
    """Get or set current voice provider ('local' offline private default or 'edge' online cloud)."""
    if request.method == "POST":
        try:
            body = await request.json()
            prov = body.get("provider", "local").strip().lower()
        except Exception:
            prov = request.query.get("provider", "local").strip().lower()
        if prov in ("cloud", "edge", "online"):
            TTS_MANAGER.set_provider("edge")
        else:
            TTS_MANAGER.set_provider("local")
        VOICE_CONFIG["provider"] = TTS_MANAGER.active_mode
        save_voice_preset(VOICE_CONFIG.get("preset", "mature_mommy_fast"))
        return web.json_response({
            "status": "ok",
            "provider": TTS_MANAGER.active_mode,
            "status_label": TTS_MANAGER.status_label,
            "message": f"Voice provider set to {TTS_MANAGER.active_mode} ({TTS_MANAGER.status_label}).",
        }, headers={"Access-Control-Allow-Origin": "*"})

    return web.json_response({
        "status": "ok",
        "provider": TTS_MANAGER.active_mode,
        "status_label": TTS_MANAGER.status_label,
        "preferred": TTS_MANAGER.preferred_provider,
    }, headers={"Access-Control-Allow-Origin": "*"})


async def handle_voice_lipsync(request: web.Request) -> web.Response:
    """Get or set lip-sync calibration offset in milliseconds."""
    if request.method == "POST":
        try:
            body = await request.json()
            val = float(body.get("offset_ms", 0.0))
        except Exception:
            val = float(request.query.get("offset_ms", 0.0))
        VOICE_CONFIG["lipsync_offset_ms"] = val
        update_runtime_voice_config()
        save_voice_preset(VOICE_CONFIG.get("preset", "mature_mommy_fast"))
        return web.json_response({
            "status": "ok",
            "offset_ms": val,
            "message": f"Lip-sync offset calibrated to {val:+.1f} ms.",
        }, headers={"Access-Control-Allow-Origin": "*"})

    return web.json_response({
        "status": "ok",
        "offset_ms": VOICE_CONFIG.get("lipsync_offset_ms", 0.0),
    }, headers={"Access-Control-Allow-Origin": "*"})


async def handle_yandere(request: web.Request) -> web.Response:
    """Get or set yandere intensity level (0-10)."""
    if request.method == "POST":
        try:
            body = await request.json()
            val = int(body.get("intensity", 4))
        except Exception:
            val = int(request.query.get("intensity", 4))
        val = max(0, min(10, val))
        STATE["yandere_intensity"] = val
        return web.json_response({
            "status": "ok",
            "intensity": val,
            "tier": get_yandere_tier_name(val),
            "message": f"Devotion intensity set to {val}/10: {get_yandere_tier_name(val)}.",
        }, headers={"Access-Control-Allow-Origin": "*"})

    val = STATE.get("yandere_intensity", 4)
    return web.json_response({
        "intensity": val,
        "tier": get_yandere_tier_name(val),
    }, headers={"Access-Control-Allow-Origin": "*"})


async def handle_relax(request: web.Request) -> web.Response:
    """Safe-word mode: drops yandere intensity to 0 (Professional Mentor)."""
    STATE["yandere_intensity"] = 0
    return web.json_response({
        "status": "ok",
        "intensity": 0,
        "tier": get_yandere_tier_name(0),
        "message": "Safe word triggered: Intensity dropped to 0/10 (Professional Mentor Mode).",
    }, headers={"Access-Control-Allow-Origin": "*"})


async def handle_options(request: web.Request) -> web.Response:
    return web.Response(headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Accept",
    })


# ---------------------------------------------------------------------------
# Application Factory
# ---------------------------------------------------------------------------
def make_app() -> web.Application:
    app = web.Application()

    STUDIO_DIR = os.path.dirname(os.path.abspath(__file__))
    DIST_DIR = os.path.join(STUDIO_DIR, "dist")
    PROJECTS_DIR = os.path.join(STUDIO_DIR, "projects")
    SAMPLES_DIR = os.path.join(STUDIO_DIR, "samples")

    async def handle_root(request: web.Request) -> web.FileResponse:
        index = os.path.join(DIST_DIR, "companion.html")
        if not os.path.exists(index):
            index = os.path.join(STUDIO_DIR, "companion.html")
        return web.FileResponse(index)

    async def handle_studio_projects(request: web.Request) -> web.Response:
        projects = [
            {
                "name": "roxy",
                "path": "projects/roxy",
                "hasSource": True,
                "rigFile": "rig.json",
            }
        ]
        return web.json_response(projects, headers={"Access-Control-Allow-Origin": "*"})

    async def handle_studio_project_files(request: web.Request) -> web.StreamResponse:
        name = request.match_info["name"]
        file_path = request.match_info.get("path", "")
        full_path = os.path.join(PROJECTS_DIR, name, file_path)
        if not os.path.exists(full_path) or os.path.isdir(full_path):
            return web.Response(status=404, text="Not found", headers={"Access-Control-Allow-Origin": "*"})
        return web.FileResponse(full_path, headers={"Access-Control-Allow-Origin": "*"})

    async def handle_mind(request: web.Request) -> web.Response:
        """Return Roxy's live inner thoughts and subconscious emotional state."""
        st = EMOTIONAL_COGNITION.state
        return web.json_response({
            "blend": st.blend_description(),
            "inner_monologue": st.inner_monologue,
            "unresolved_tension": st.unresolved_tension,
            "recommended_pose": st.recommended_pose,
            "recommended_expression": st.recommended_expression,
            "valence": round(st.valence, 2),
            "arousal": round(st.arousal, 2),
            "joy": round(st.joy, 2),
            "trust": round(st.trust, 2),
            "heartbeat": "active",
        }, headers={"Access-Control-Allow-Origin": "*"})

    # Core Voice & Interaction APIs
    app.router.add_get("/api/health", handle_health)
    app.router.add_get("/api/status", handle_status)
    app.router.add_get("/api/settings", handle_settings)
    app.router.add_post("/api/settings", handle_settings)
    app.router.add_get("/api/voice/list", handle_voice_list)
    app.router.add_post("/api/voice/set", handle_voice_set)
    app.router.add_get("/api/mind", handle_mind)
    app.router.add_get("/api/yandere", handle_yandere)
    app.router.add_post("/api/yandere", handle_yandere)
    app.router.add_post("/api/relax", handle_relax)
    app.router.add_get("/api/idle", handle_idle)
    app.router.add_post("/api/idle", handle_idle)
    app.router.add_get("/api/tts", handle_tts)
    app.router.add_get("/api/voice/speed", handle_voice_speed)
    app.router.add_post("/api/voice/speed", handle_voice_speed)
    app.router.add_get("/api/voice/pitch", handle_voice_pitch)
    app.router.add_post("/api/voice/pitch", handle_voice_pitch)
    app.router.add_get("/api/voice/reload", handle_voice_reload)
    app.router.add_post("/api/voice/reload", handle_voice_reload)
    app.router.add_post("/api/voice/save", handle_voice_save)
    app.router.add_get("/api/voice/provider", handle_voice_provider)
    app.router.add_post("/api/voice/provider", handle_voice_provider)
    app.router.add_get("/api/voice/lipsync", handle_voice_lipsync)
    app.router.add_post("/api/voice/lipsync", handle_voice_lipsync)
    app.router.add_get("/api/voice/audition", handle_voice_audition)
    app.router.add_get("/api/perf", handle_perf)
    app.router.add_get("/api/doctor", handle_doctor)
    app.router.add_get("/api/tasks", handle_tasks_list)
    app.router.add_get("/api/music/status", handle_music_status)
    app.router.add_post("/api/music/control", handle_music_control)
    app.router.add_post("/api/music/toggle", handle_music_toggle)
    app.router.add_post("/api/music/stop", handle_music_stop)
    app.router.add_post("/api/music/duck", handle_music_duck)
    app.router.add_post("/api/chat", handle_chat)
    app.router.add_post("/api/confirm", handle_confirm)
    app.router.add_post("/api/stop", handle_stop)
    app.router.add_get("/api/perm", handle_perm)
    app.router.add_post("/api/perm", handle_perm)
    app.router.add_get("/api/debug/last", handle_debug_last)

    # Backend Microphone APIs
    app.router.add_get("/api/mic/devices", handle_mic_devices)
    app.router.add_post("/api/mic/start", handle_mic_start)
    app.router.add_get("/api/mic/level", handle_mic_level)
    app.router.add_post("/api/mic/stop", handle_mic_stop)
    app.router.add_post("/api/mic/test", handle_mic_test)
    app.router.add_get("/api/mic/last_recording", handle_mic_last_recording)
    app.router.add_post("/api/mic/play", handle_mic_play)

    # Screen Awareness & Vision APIs
    app.router.add_post("/api/screen/capture", handle_screen_capture)
    app.router.add_get("/api/screen/preview", handle_screen_preview)
    app.router.add_post("/api/screen/analyze", handle_screen_analyze)

    # Static Assets & Studio Project routes
    app.router.add_get("/", handle_root)
    app.router.add_get("/companion.html", handle_root)
    app.router.add_get("/__studio/projects", handle_studio_projects)
    app.router.add_get("/__studio/projects/{name}/{path:.*}", handle_studio_project_files)
    if os.path.exists(os.path.join(DIST_DIR, "assets")):
        app.router.add_static("/assets", os.path.join(DIST_DIR, "assets"))
    if os.path.exists(SAMPLES_DIR):
        app.router.add_static("/samples", SAMPLES_DIR)

    app.router.add_route("OPTIONS", "/{tail:.*}", handle_options)
    return app


if __name__ == "__main__":
    print(f"[Roxy Voice AI] Starting service on http://{HOST}:{PORT}...")
    app = make_app()
    web.run_app(app, host=HOST, port=PORT)
