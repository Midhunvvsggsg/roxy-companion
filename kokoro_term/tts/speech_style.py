from __future__ import annotations

import random
import re
from typing import Optional, List


# Recognized Japanese-style slang terms
STANDARD_SLANG_TERMS = [
    "ara",
    "fufu",
    "mou",
    "ne",
    "yosh",
    "hora",
    "sugoi",
    "baka",
    "yare yare",
    "ganbatte",
    "-san",
    "-kun",
]

# Pronunciation overrides for Japanese slang terms in English TTS engines
DEFAULT_PRONUNCIATION_MAP = {
    "ara": "ah-rah",
    "Ara": "Ah-rah",
    "fufu": "foo foo",
    "Fufu": "Foo foo",
    "mou": "moh",
    "Mou": "Moh",
    "ne": "neh",
    "ne?": "neh?",
    "yosh": "yohsh",
    "Yosh": "Yohsh",
    "hora": "hoh-rah",
    "Hora": "Hoh-rah",
    "sugoi": "soo-goy",
    "Sugoi": "Soo-goy",
    "baka": "bah-kah",
    "Baka": "Bah-kah",
    "yare yare": "yah-reh yah-reh",
    "Yare yare": "Yah-reh yah-reh",
    "ganbatte": "gahn-baht-teh",
    "Ganbatte": "Gahn-baht-teh",
    "-san": "-sahn",
    "-kun": "-koon",
}

# Empirically pruned pronunciation map keeping only entries verified to improve Whisper round-trip
REDUCED_PRONUNCIATION_MAP = {
    "ara": "ah-rah",
    "Ara": "Ah-rah",
    "yosh": "yohsh",
    "Yosh": "Yohsh",
    "hora": "hoh-rah",
    "Hora": "Hoh-rah",
    "sugoi": "soo-goy",
    "Sugoi": "Soo-goy",
    "ganbatte": "gahn-baht-teh",
    "Ganbatte": "Gahn-baht-teh",
    "mou": "moh",
    "Mou": "Moh",
    "ne": "neh",
    "ne?": "neh?",
}


def num_to_words(n: int) -> str:
    """Convert integer to English words."""
    ones = [
        "", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
        "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
        "seventeen", "eighteen", "nineteen",
    ]
    tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
    if n == 0:
        return "zero"
    if n < 0:
        return f"negative {num_to_words(abs(n))}"
    if n < 20:
        return ones[n]
    if n < 100:
        return tens[n // 10] + (("-" + ones[n % 10]) if n % 10 else "")
    if n < 1000:
        return ones[n // 100] + " hundred" + ((" and " + num_to_words(n % 100)) if n % 100 else "")
    if n < 1000000:
        return num_to_words(n // 1000) + " thousand" + ((" " + num_to_words(n % 1000)) if n % 1000 else "")
    if n < 1000000000:
        return num_to_words(n // 1000000) + " million" + ((" " + num_to_words(n % 1000000)) if n % 1000000 else "")
    return num_to_words(n // 1000000000) + " billion" + ((" " + num_to_words(n % 1000000000)) if n % 1000000000 else "")


def normalize_text_for_tts(text: str) -> str:
    """Prepare text for TTS audio synthesis (never displayed in UI).
    
    Rules:
    - Numbers and units: "16 GB" -> "sixteen gigabytes", "57.4%" -> "fifty-seven point four percent"
    - Em/En dashes -> commas
    - Ellipses -> short pauses (commas)
    - URLs, file paths, and code blocks removed or verbalized
    - Emojis and markdown removed
    - Contractions stay as normal text and are NEVER respelled
    """
    clean = re.sub(r"\[emotion:[a-zA-Z0-9_-]+\]\s*", "", text).strip()
    if not clean:
        return ""

    res = clean

    # 1. Strip code blocks
    res = re.sub(r"```[\w-]*\n[\s\S]*?```", " [code block omitted] ", res)

    # 2. Markdown formatting (bold, italic, inline code)
    res = re.sub(r"`([^`]+)`", r"\1", res)
    res = re.sub(r"\*\*([^*]+)\*\*", r"\1", res)
    res = re.sub(r"\*([^*]+)\*", r"\1", res)
    res = re.sub(r"__([^_]+)__", r"\1", res)

    # 3. Strip emojis
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FA6F"
        "]+",
        flags=re.UNICODE,
    )
    res = emoji_pattern.sub("", res)

    # 4. URLs and file paths
    res = re.sub(r"https?://(?:localhost|\d+\.\d+\.\d+\.\d+)(?::\d+)?(?:/[^\s)]*)?", "the local server link", res)
    res = re.sub(r"https?://(?:www\.)?google\.com/search\?q=([^\s)]+)", r"search results for \1", res)
    res = re.sub(r"https?://news\.google\.com[^\s)]*", "Google News", res)
    res = re.sub(r"https?://[^\s)]+", "the web link", res)

    def _replace_path(match: re.Match) -> str:
        p = match.group(0)
        filename = p.rstrip("/").split("/")[-1]
        name_clean = filename.replace(".", " dot ").replace("_", " ")
        return f"the {name_clean} file"

    res = re.sub(r"(?:/[a-zA-Z0-9_.-]+){2,}", _replace_path, res)

    # 5. System info specific conversions
    res = re.sub(r"OS:\s*Linux\s*([0-9.-]+)-arch(\d+)-(\d+)\s*\(([^)]+)\)", r"Operating System: Linux on 64-bit architecture", res)
    res = re.sub(r"CPUs?:\s*(\d+)", lambda m: f"{num_to_words(int(m.group(1)))} central processors", res)
    res = re.sub(r"Python:\s*(\d+)\.(\d+)\.(\d+)", lambda m: f"Python {num_to_words(int(m.group(1)))} point {num_to_words(int(m.group(2)))}", res)

    def _convert_kb_mem(match: re.Match) -> str:
        kb = int(match.group(1))
        gb = round(kb / (1024 * 1024))
        return f"{num_to_words(gb)} gigabytes"

    res = re.sub(r"MemTotal:\s*(\d+)\s*kB", lambda m: f"Total memory: {_convert_kb_mem(m)}", res)
    res = re.sub(r"MemFree:\s*(\d+)\s*kB", lambda m: f"free memory: {_convert_kb_mem(m)}", res)
    res = re.sub(r"MemAvailable:\s*(\d+)\s*kB", lambda m: f"available memory: {_convert_kb_mem(m)}", res)

    # 6. Em/En dashes -> comma for natural clause pause
    res = re.sub(r"\s*[—–]\s*", ", ", res)
    res = re.sub(r"\s+--\s+", ", ", res)

    # 7. Ellipses -> short pause
    res = re.sub(r"\.{2,}|…", ", ", res)

    # 8. Units and percentages
    def _replace_percent(match: re.Match) -> str:
        val = match.group(1)
        if "." in val:
            whole, frac = val.split(".", 1)
            return f"{num_to_words(int(whole))} point {num_to_words(int(frac))} percent"
        return f"{num_to_words(int(val))} percent"

    res = re.sub(r"(\d+(?:\.\d+)?)\s*%", _replace_percent, res)

    unit_names = {
        "gb": "gigabytes", "gib": "gigabytes",
        "mb": "megabytes", "mib": "megabytes",
        "kb": "kilobytes", "kib": "kilobytes",
        "tb": "terabytes", "tib": "terabytes",
        "ghz": "gigahertz", "mhz": "megahertz",
        "ms": "milliseconds", "s": "seconds",
    }

    def _replace_units(match: re.Match) -> str:
        val = match.group(1)
        unit = match.group(2).lower()
        word_unit = unit_names.get(unit, unit)
        if "." in val:
            whole, frac = val.split(".", 1)
            return f"{num_to_words(int(whole))} point {num_to_words(int(frac))} {word_unit}"
        return f"{num_to_words(int(val))} {word_unit}"

    res = re.sub(r"(\d+(?:\.\d+)?)\s*(GB|GiB|MB|MiB|kB|KB|KiB|TB|TiB|GHz|MHz|ms|s)\b", _replace_units, res)

    # 9. Standalone formatted numbers
    def _replace_commas_num(match: re.Match) -> str:
        val = int(match.group(0).replace(",", ""))
        return num_to_words(val)

    res = re.sub(r"\b\d{1,3}(?:,\d{3})+\b", _replace_commas_num, res)

    # Clean multiple spaces or commas
    res = re.sub(r",\s*,+", ", ", res)
    res = re.sub(r"\s+", " ", res).strip()

    return res


def split_sentences(text: str) -> list[str]:
    """Split text into sentence chunks for natural prosody."""
    clean = re.sub(r"\[emotion:[a-zA-Z0-9_-]+\]\s*", "", text).strip()
    if not clean:
        return []

    # Split on sentence terminals while keeping punctuation
    parts = re.split(r"([.!?]+[\s\n]+)", clean)
    sentences = []
    current = ""
    for part in parts:
        current += part
        if re.search(r"[.!?]+[\s\n]*$", current):
            if current.strip():
                sentences.append(current.strip())
            current = ""
    if current.strip():
        sentences.append(current.strip())

    return sentences or [clean]


def split_into_clauses(text: str, min_words: int = 4, max_words: int = 7) -> list[str]:
    """Legacy helper maintained for backward compatibility."""
    clean = re.sub(r"\[emotion:[a-zA-Z0-9_-]+\]\s*", "", text).strip()
    if not clean:
        return []

    sentences = split_sentences(clean)
    clauses: list[str] = []
    for s in sentences:
        words = s.split()
        if len(words) <= max_words:
            clauses.append(s)
        else:
            parts = re.split(r"([,;:—–]+[\s\n]*)", s)
            curr = ""
            for p in parts:
                curr += p
                c_words = curr.strip().split()
                if len(c_words) >= min_words:
                    clauses.append(curr.strip())
                    curr = ""
            if curr.strip():
                if len(curr.strip().split()) < min_words and clauses:
                    clauses[-1] = f"{clauses[-1]} {curr.strip()}"
                else:
                    clauses.append(curr.strip())

    return clauses or [clean]


def chunk_text_for_tts(text: str) -> list[str]:
    """Chunk text into natural intonation units for streaming TTS.
    
    Rules:
    - The first chunk is the first full sentence (or up to a natural clause of 8+ words
      if the first sentence is excessively long).
    - Later chunks are whole sentences, never split at commas.
    """
    clean = re.sub(r"\[emotion:[a-zA-Z0-9_-]+\]\s*", "", text).strip()
    if not clean:
        return []

    sentences = split_sentences(clean)
    if not sentences:
        return [clean]

    chunks: list[str] = []

    # First chunk handling: sentence 0
    s0 = sentences[0]
    words_s0 = s0.split()
    if len(words_s0) > 14 and ("," in s0 or ";" in s0 or "—" in s0):
        parts = re.split(r"([,;—]+[\s\n]*)", s0)
        c0 = ""
        rest_parts: list[str] = []
        found = False
        for p in parts:
            c0 += p
            if not found and len(c0.strip().split()) >= 8:
                chunks.append(c0.strip())
                found = True
            elif found:
                rest_parts.append(p)
        if rest_parts:
            rem = "".join(rest_parts).strip()
            if rem:
                chunks.append(rem)
    else:
        chunks.append(s0)

    # Later chunks are always full sentences, NEVER split at commas
    for s in sentences[1:]:
        chunks.append(s)

    return chunks


def apply_contractions(text: str) -> str:
    """Ensure natural spoken rhythm with contractions instead of stiff phrasing."""
    replacements = [
        (r"\bI am\b", "I'm"),
        (r"\bI have\b", "I've"),
        (r"\bI will\b", "I'll"),
        (r"\bdo not\b", "don't"),
        (r"\bDo not\b", "Don't"),
        (r"\bcannot\b", "can't"),
        (r"\bCannot\b", "Can't"),
        (r"\bwill not\b", "won't"),
        (r"\bWill not\b", "Won't"),
        (r"\bis not\b", "isn't"),
        (r"\bIs not\b", "Isn't"),
        (r"\bare not\b", "aren't"),
        (r"\bAre not\b", "Aren't"),
        (r"\byou are\b", "you're"),
        (r"\bYou are\b", "You're"),
        (r"\blet us\b", "let's"),
        (r"\bLet us\b", "Let's"),
        (r"\bwhat is\b", "what's"),
        (r"\bWhat is\b", "What's"),
        (r"\bthat is\b", "that's"),
        (r"\bThat is\b", "That's"),
        (r"\bthere is\b", "there's"),
        (r"\bThere is\b", "There's"),
    ]
    res = text
    for pattern, repl in replacements:
        res = re.sub(pattern, repl, res)
    return res


def sentence_has_slang(sentence: str) -> bool:
    """Check if a sentence already contains any recognized Japanese-style slang term."""
    lower = sentence.lower()
    for term in STANDARD_SLANG_TERMS:
        if term.startswith("-"):
            if term in lower:
                return True
        else:
            if re.search(rf"\b{re.escape(term)}\b", lower):
                return True
    return False


def apply_japanese_slang(
    text: str,
    emotion: str = "neutral",
    accent_strength: float = 0.25,
    user_name: str = "Midhun",
    rng: Optional[random.Random] = None,
) -> str:
    """Apply tasteful touches of Japanese-style anime slang.

    Rules:
    - Never more than one slang term per sentence.
    - At most about 1 in 4 sentences (requires >= 3 non-slang sentences between touches).
    - Never put two interjections in a row.
    - Natural placement at start or end.
    - Uses contractions and natural spoken flow.
    """
    clean_text = apply_contractions(text)
    sentences = split_sentences(clean_text)
    if not sentences:
        return clean_text

    r = rng or random.Random()
    modified_sentences: list[str] = []
    # Spacing counter to enforce at most 1 in 4 sentences (requires >= 3 non-slang sentences between touches)
    sentences_since_last_slang = 3
    last_ended_with_interjection = False

    for s_idx, sentence in enumerate(sentences):
        # 1. Check if sentence already has slang
        if sentence_has_slang(sentence):
            modified_sentences.append(sentence)
            sentences_since_last_slang = 0
            last_ended_with_interjection = False
            continue

        # 2. Check frequency constraint: at most 1 in 4 sentences
        should_add = (
            sentences_since_last_slang >= 3
            and accent_strength > 0.0
            and (r.random() < accent_strength or (s_idx == 0 and accent_strength >= 0.25))
        )

        if not should_add:
            modified_sentences.append(sentence)
            sentences_since_last_slang += 1
            last_ended_with_interjection = False
            continue

        # 3. Select appropriate slang touch
        emo = emotion.lower()
        ends_with_q = sentence.endswith("?")

        start_touch: Optional[str] = None
        end_touch: Optional[str] = None

        if emo in ("teasing", "blush", "shy", "flustered"):
            roll = r.random()
            if roll < 0.4:
                start_touch = "Ara,"
            elif roll < 0.7:
                start_touch = "Fufu,"
            else:
                if emo in ("blush", "flustered"):
                    start_touch = "Baka..."
                else:
                    end_touch = "...baka."
        elif emo in ("serious", "stern", "commanding"):
            if r.random() < 0.6:
                start_touch = "Yare yare,"
            else:
                start_touch = "Ganbatte,"
        elif emo in ("happy", "smile"):
            roll = r.random()
            if roll < 0.35:
                start_touch = "Yosh,"
            elif roll < 0.70:
                start_touch = "Hora,"
            else:
                end_touch = "Sugoi!"
        elif emo in ("caring", "gentle"):
            roll = r.random()
            if roll < 0.5:
                start_touch = "Ara,"
            else:
                end_touch = "ne?" if ends_with_q else "...ne."
        else:  # neutral
            roll = r.random()
            if roll < 0.3:
                start_touch = "Ara,"
            elif roll < 0.6:
                start_touch = "Yosh,"
            elif roll < 0.8:
                start_touch = "Hora,"
            else:
                end_touch = "ne?" if ends_with_q else "...ne."

        # Guard: Never put two interjections in a row!
        if last_ended_with_interjection and start_touch:
            start_touch = None
            end_touch = "ne?" if ends_with_q else "...ne."

        new_sentence = sentence
        if start_touch:
            first_word_match = re.match(r"^(\w+)(.*)", sentence)
            if first_word_match and start_touch.endswith(","):
                first_word = first_word_match.group(1)
                rest = first_word_match.group(2)
                if first_word not in ("I", "I'm", "I've", "I'll", user_name):
                    first_word = first_word[0].lower() + first_word[1:]
                new_sentence = f"{start_touch} {first_word}{rest}"
            else:
                new_sentence = f"{start_touch} {sentence}"
            last_ended_with_interjection = False
        elif end_touch:
            clean_end = re.sub(r"[.!?]+$", "", sentence).strip()
            if end_touch.startswith("..."):
                new_sentence = f"{clean_end}{end_touch}"
            elif end_touch.startswith("ne"):
                punct = "?" if ends_with_q else "."
                new_sentence = f"{clean_end}, ne{punct}"
            else:
                new_sentence = f"{clean_end}—{end_touch}"
            last_ended_with_interjection = True

        modified_sentences.append(new_sentence)
        sentences_since_last_slang = 0

    return " ".join(modified_sentences)


def apply_pronunciation_map(
    text: str, pronunciation_map: Optional[dict[str, str]] = None
) -> str:
    """Replace Japanese slang words with phonetic respellings for accurate TTS synthesis.
    
    Only applies to entries explicitly present in pronunciation_map.
    """
    mapping = pronunciation_map if pronunciation_map is not None else DEFAULT_PRONUNCIATION_MAP
    if not mapping:
        return text

    res = text
    if "-san" in mapping:
        res = re.sub(r"-san\b", mapping["-san"], res, flags=re.IGNORECASE)
    if "-kun" in mapping:
        res = re.sub(r"-kun\b", mapping["-kun"], res, flags=re.IGNORECASE)

    sorted_words = sorted(
        [k for k in mapping.keys() if not k.startswith("-")],
        key=lambda x: len(x),
        reverse=True,
    )

    for word in sorted_words:
        phonetic = mapping[word]
        pattern = rf"\b{re.escape(word)}\b"
        res = re.sub(pattern, phonetic, res, flags=re.IGNORECASE)

    return res


def apply_speech_style(
    text: str,
    emotion: str = "neutral",
    stutter_on_blush: bool = True,
    accent_strength: float = 0.0,
    user_name: str = "Midhun",
) -> str:
    """Apply complete character-specific speech styling (slang touches + blush stutter)."""
    styled = text

    if emotion in ("blush", "flustered", "shy") and stutter_on_blush:
        def _stutter_replace(match: re.Match) -> str:
            word = match.group(0)
            if word.lower() in ("what", "why", "where", "how", "who"):
                return f"{word[0]}-{word.lower()}"
            elif word.lower() in ("i", "i'm"):
                return f"I... {word.lower()}"
            elif word.lower() in ("that", "this"):
                return f"Th-{word.lower()}"
            return word

        styled = re.sub(
            r"\b(What|Why|Where|How|Who|I|I'm|That|This)\b",
            _stutter_replace,
            styled,
            count=1,
        )

    if accent_strength > 0.0:
        styled = apply_japanese_slang(
            styled,
            emotion=emotion,
            accent_strength=accent_strength,
            user_name=user_name,
        )

    return styled
