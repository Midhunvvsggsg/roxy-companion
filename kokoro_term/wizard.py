from __future__ import annotations

from pathlib import Path
from typing import Optional
import yaml

from kokoro_term.avatar.generator import generate_roxy_sprite_pack
from kokoro_term.llm.base import LLMMessage, LLMProvider


def list_available_characters(characters_dir: str | Path = "characters") -> list[dict[str, str]]:
    """Scan the characters directory and list metadata for all discovered characters."""
    char_path = Path(characters_dir)
    results = []
    if not char_path.exists():
        return results

    for item in sorted(char_path.iterdir()):
        if item.is_dir() and (item / "character.yaml").exists():
            try:
                with open(item / "character.yaml", "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                    results.append({
                        "id": item.name,
                        "name": data.get("name", item.name),
                        "title": data.get("title", ""),
                    })
            except Exception:
                results.append({"id": item.name, "name": item.name, "title": ""})

    return results


def scaffold_new_character(
    char_id: str,
    name: str,
    title: str = "",
    bio: str = "",
    traits: Optional[list[str]] = None,
    characters_dir: str | Path = "characters",
) -> Path:
    """Create a new character folder complete with character.yaml, voice.yaml, and sprite pack."""
    clean_id = char_id.strip().lower().replace(" ", "_")
    target_dir = Path(characters_dir) / clean_id
    target_dir.mkdir(parents=True, exist_ok=True)

    char_data = {
        "name": name,
        "display_name": name.split()[0],
        "title": title or "Digital Companion",
        "bio": bio or f"A wonderful AI companion named {name}.",
        "personality_traits": traits or ["friendly", "supportive", "curious"],
        "speaking_style": {
            "summary": "Polite and helpful.",
            "rules": [
                "Address the user kindly.",
                "Include an emotion tag in brackets at the start of every reply: [emotion:neutral], [emotion:happy], [emotion:blush], [emotion:thinking].",
            ],
        },
        "emotions": ["neutral", "happy", "blush", "pout", "sad", "surprised", "thinking"],
        "default_emotion": "neutral",
    }

    with open(target_dir / "character.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(char_data, f, sort_keys=False)

    voice_data = {
        "engine": "kokoro",
        "voice_id": "af_sarah",
        "speed": 1.0,
        "pitch": 1.0,
        "lang": "en-us",
        "speech_style": {
            "stutter_on_blush": True,
        },
    }
    with open(target_dir / "voice.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(voice_data, f, sort_keys=False)

    # Generate starter avatar sprite pack
    generate_roxy_sprite_pack(output_dir=target_dir / "avatar")

    return target_dir


async def draft_character_card(
    prompt_description: str,
    llm: LLMProvider,
    characters_dir: str | Path = "characters",
) -> tuple[str, Path]:
    """Ask the LLM to draft a structured character card from a short prompt description."""
    system_prompt = (
        "You are an anime character designer. Given a brief description, design a rich character card.\n"
        "Respond ONLY with valid YAML matching this structure:\n"
        "name: 'Full Name'\n"
        "display_name: 'Short Name'\n"
        "title: 'Class / Title'\n"
        "bio: '2-3 sentences of authentic backstory and personality.'\n"
        "personality_traits:\n"
        "  - trait_one\n"
        "  - trait_two\n"
        "speaking_style:\n"
        "  summary: 'Description of mannerisms and tone.'\n"
        "  rules:\n"
        "    - 'Rule 1'\n"
        "    - 'Include an emotion tag at start: [emotion:neutral], [emotion:happy], [emotion:blush], [emotion:thinking].'\n"
    )

    reply = await llm.chat([
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="user", content=f"Design character: {prompt_description}"),
    ])

    # Strip code block if returned
    clean_yaml = reply.strip()
    if clean_yaml.startswith("```"):
        clean_yaml = clean_yaml.split("\n", 1)[-1]
        if clean_yaml.endswith("```"):
            clean_yaml = clean_yaml.rsplit("```", 1)[0]

    data = yaml.safe_load(clean_yaml) or {}
    name = data.get("name", "New Character")
    char_id = name.lower().replace(" ", "_")

    target_dir = Path(characters_dir) / char_id
    target_dir.mkdir(parents=True, exist_ok=True)

    with open(target_dir / "character.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)

    voice_data = {
        "engine": "kokoro",
        "voice_id": "af_sarah",
        "speed": 1.0,
        "pitch": 1.0,
        "lang": "en-us",
    }
    with open(target_dir / "voice.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(voice_data, f, sort_keys=False)

    generate_roxy_sprite_pack(output_dir=target_dir / "avatar")
    return char_id, target_dir
