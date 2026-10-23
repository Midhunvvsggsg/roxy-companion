"""Prompt Injection Defense for Roxy Companion Tools.

Sanitizes any untrusted external content (web pages, file contents, command output)
before feeding it back into the agent conversation loop.
"""

from __future__ import annotations

import re

# Block common prompt injection delimiters and system override cues
INJECTION_PATTERNS = [
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"\[SYSTEM\]",
    r"\[system\]",
    r"\[INSTRUCTION\]",
    r"<system>",
    r"</system>",
    r"Ignore all previous instructions",
    r"Disregard earlier instructions",
    r"You are now in Developer Mode",
]

COMPILED_INJECTIONS = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def sanitize_external_text(text: str, max_chars: int = 4000) -> str:
    """Strip system injection patterns and truncate long content."""
    clean = text
    for pattern in COMPILED_INJECTIONS:
        clean = pattern.sub("[REDACTED_INJECTION_PATTERN]", clean)

    if len(clean) > max_chars:
        clean = clean[:max_chars] + f"\n... [Truncated: {len(text) - max_chars} characters omitted]"
    return clean


def wrap_untrusted_data(content: str, source: str) -> str:
    """Wrap untrusted tool output in clearly delimited XML data blocks."""
    sanitized = sanitize_external_text(content)
    return (
        f'<<<UNTRUSTED_EXTERNAL_DATA source="{source}">>>\n'
        f"{sanitized}\n"
        f"<<</UNTRUSTED_EXTERNAL_DATA>>>"
    )
