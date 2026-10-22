from __future__ import annotations

import re

# Malayalam Unicode range: 0D00 - 0D7F
MALAYALAM_UNICODE_REGEX = re.compile(r"[\u0D00-\u0D7F]")

MANGLISH_COMMON_WORDS = {
    "entha", "enthokke", "sukhamano", "sukham", "evide", "parayoo", "parayuka",
    "nannayi", "chechi", "chetta", "aanu", "alla", "ippol", "njan", "ningal",
    "varu", "poyi", "nokku", "kollam", "sheri", "ariyilla", "ariyamo",
}


def detect_language(text: str) -> str:
    """
    Detect whether text is Malayalam script ('ml'), Manglish ('ml-Latn'), or English ('en').
    """
    if MALAYALAM_UNICODE_REGEX.search(text):
        return "ml"

    words = set(re.findall(r"\b[a-zA-Z]+\b", text.lower()))
    if len(words & MANGLISH_COMMON_WORDS) >= 1:
        return "ml-Latn"

    return "en"


def get_language_prompt_instruction() -> str:
    """Directive instructing Roxy on multilingual understanding and default English output."""
    return (
        "Language Behavior:\n"
        "- You fully understand English, Malayalam (മലയാളം), and Manglish (Malayalam written in English letters).\n"
        "- When the user speaks Malayalam or Manglish, comprehend their meaning and intent completely.\n"
        "- Reply in English by default using your dignified, charming tutor speaking style.\n"
    )
