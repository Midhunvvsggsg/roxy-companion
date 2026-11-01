# Kokoro-Term (Waifu-Terminal) 🌸

An open-source, cross-platform (Linux + Windows), resource-friendly anime AI companion that lives in your terminal.

First character: **Roxy Migurdia** from *Mushoku Tensei* (serious, proud water saint mage, secretly caring, flustered when praised, dedicated tutor).

```text
+------------------------------------+-----------------------------+
| You: Can you explain water magic?  | Roxy Migurdia               |
|                                    | Water Saint-Class Magician  |
| Roxy:                              |                             |
| ( • _ • ) Let us begin with the    |         [▄▄▄▄▄▄▄▄]          |
| fundamental incantations...        |         [▀▀▀▀▀▀▀▀]          |
|                                    |                             |
| You: You are so cute today Roxy!   | Friendly Mentor & Pupil     |
|                                    | Affection: 62.5% [█████░░░] |
| Roxy:                              | Trust:     55.0% [█████░░░] |
| (⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄) W-what are you     | Mood:      Flustered        |
| saying so suddenly?! Focus!        | Mic:       Off (Text Mode)  |
|                                    | Task:      Idle             |
+------------------------------------+-----------------------------+
| Talk to Roxy... (Press Enter to send)                            |
+------------------------------------------------------------------+
```

---

## 🚀 Running Roxy Companion

Roxy Companion supports two versatile modes:

### 1. 🌟 2.5D Animated Studio & Companion Window (Default)
A dedicated, transparent desktop companion window featuring 2.5D mesh animations, real-time voice, microphone VAD, screen vision analysis, and relationship state:
```bash
./bin/roxy
```
*(Or install `bin/roxy` into your `$PATH` as `roxy`)*

### 2. 🌸 Terminal Waifu TUI
Ultra-lightweight Textual terminal companion with half-block / Sixel animation:
```bash
./bin/roxy --term
# Or directly via package:
uv run kokoro-term
```

---

- **Ultra Resource-Friendly**: < 30 MB disk in text-only mode, ~50 MB RAM active, near 0.0% idle CPU.
- **Pluggable LLMs**: Default **Google Gemini API**, plus native support for **OpenAI, Ollama, LM Studio, and Mock** offline testing.
- **Adaptive 3-Layer Memory**: SQLite + FTS5 full-text search. Short-term dialogue window, episodic background summarization, and permanent fact extraction with contradiction resolution.
- **Evolving Relationship State**: Dynamic affection, trust, and personality sliders (tsundere-ness, formality, shyness) that drift based on interaction sentiment and time absence.
- **Animated Terminal Avatar**:
  - Graceful fallback: Kitty graphics protocol → Sixel → 24-bit Half-Block Unicode (`▀▄`) colored pixels → ASCII Kaomoji.
  - Idle breathing, autonomous blinking, and speech lip-sync.
  - Layered sprite pack manifest: easily drop in your own custom character art.
- **System Agency & Safety Permission Model**:
  - `SAFE` (auto-run): `system_info`, `read_file`, `search_files`.
  - `MODERATE` (session approval): `write_file` (with unified diffs), `open_url`, `open_app`.
  - `DANGEROUS` (explicit typed confirmation): `trash_file`, destructive shell commands.
  - **In-Character Resistance**: Roxy issues an in-character warning/objection when risky commands are requested. Once confirmed ("yes" / "confirm"), she executes them obediently.
  - Full audit trail recorded in `data/audit.log`.
- **Bilingual Understanding**: English and Malayalam (മലയാളം / Manglish auto-detection).
- **Hot-Swap Characters**: Switch companions instantly at runtime without restarting (`/character use <id>`).

---

## 🔒 Voice Synthesis & Privacy Architecture

Kokoro-Term features a strict dual-tier TTS Provider Interface (`tts.provider = local | edge`):
- **`local` (Offline & Private Default)**: 100% private. Runs entirely on your local CPU with zero network traffic.
- **`edge` (Optional Online Cloud)**: Uses Microsoft Edge Speech WebSocket service (`speech.platform.bing.com`) for low-latency streaming neural voices.
- **Strict Privacy Guarantee**: Only Roxy's final conversational dialogue is sent to cloud TTS. System prompt instructions, tool outputs, terminal shell commands, file contents, memory databases, and screenshots are **strictly NEVER transmitted** to the cloud TTS.
- **Automatic Fallback**: If Edge-TTS encounters network disconnection or rate limits, the system seamlessly falls back to the local provider without interrupting speech. The status is clearly indicated via `[Voice: cloud]` or `[Voice: local]`.

> [!WARNING]
> **Edge-TTS Endpoint Disclosure**: Edge-TTS connects to Microsoft's Bing Speech service via an unofficial, reverse-engineered client token and Edge browser extension origin. Microsoft can change, throttle, or deprecate this endpoint at any time.

---

## 🚀 Quickstart & Installation

### Option A: Using `uv` (Recommended for Speed & Isolation)

#### On Linux:
```bash
git clone https://github.com/your-username/kokoro-term.git
cd kokoro-term

# 1. (Optional) Set your Gemini API key:
export GEMINI_API_KEY="your-gemini-key"

# 2. Launch the terminal companion:
uv run kokoro-term

# Or test immediately offline with zero API keys:
uv run kokoro-term --mock
```

#### On Windows (PowerShell):
```powershell
git clone https://github.com/your-username/kokoro-term.git
cd kokoro-term

# 1. (Optional) Set your Gemini API key:
$env:GEMINI_API_KEY="your-gemini-key"

# 2. Launch:
uv run kokoro-term

# Or offline mock mode:
uv run kokoro-term --mock
```

---

### Option B: Using `pip` / `pipx`

```bash
# Standard Python venv:
python3 -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\Activate.ps1
pip install -e .
kokoro-term
```

---

## ⌨️ Built-in Commands

| Command | Description |
| :--- | :--- |
| `/status` | View relationship stage, core meters, and personality sliders |
| `/status set <metric> <val>` | Manually tune any slider (e.g. `/status set affection 85`) |
| `/status reset` | Restore relationship metrics to character baseline |
| `/character list` | List all discovered character packages |
| `/character use <id>` | Hot-swap active companion on the fly |
| `/character new <id> <name>` | Scaffold a new character with sprite pack and manifests |
| `/tools` | List registered agency tools and permission tiers |
| `/audit` | View recent entries from the security audit log |
| `/memory show` | Display active user facts & recent episodic summaries |
| `/memory forget <term>` | Deactivate a specific fact from memory |
| `/memory export [file]` | Export complete memory to a Markdown file |
| `/memory wipe` | Erase memory for current character and user |
| `/perf` | Display live process RSS memory, DB size, and resource telemetry |
| `/clear` | Clear chat viewport |
| `/quit` | Exit application (`Ctrl+C` also supported) |

---

## 🎙️ Voice & Malayalam Speech Recognition

To benchmark Malayalam language detection and accuracy on sample phrases:
```bash
uv run python -m kokoro_term.stt.benchmark
```
*Roxy understands Malayalam and Manglish queries natively, replying in English by default with her charming tutor speech style.*

---

## 🧪 Testing

Kokoro-Term ships with a comprehensive test suite covering config loading, character prompt assembly, LLM streaming, SQLite FTS5 memory, relationship drift, tool permissions, and headless Textual TUI interaction:

```bash
uv run pytest -v
```

---

## 📄 License

MIT License. Open-source and free for all developers.
