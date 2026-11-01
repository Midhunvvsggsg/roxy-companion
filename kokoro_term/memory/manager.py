from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from kokoro_term.config import MemoryConfig
from kokoro_term.llm.base import LLMMessage, LLMProvider
from kokoro_term.memory.db import get_db_connection
from kokoro_term.memory.models import Episode, Fact, MessageRecord
from kokoro_term.relationship.engine import RelationshipEngine


def extract_preferred_name_from_text(text: str) -> Optional[str]:
    """Extract requested preferred name from natural language user input."""
    t = text.strip()
    t = re.sub(r"[\"\x27]", "", t)
    t = re.sub(r"[\.,!?;]+$", "", t)
    t = re.sub(r"\s+from\s+now\s+on\b.*$", "", t, flags=re.IGNORECASE).strip()

    parts = re.split(r"\b(?:call me|address me as|refer to me as|my name is)\s+", t, flags=re.IGNORECASE)
    if len(parts) > 1:
        candidate = parts[-1].strip()
        candidate = re.split(r"[\.,!?;]|\b(?:please|now|ok|okay|instead|thanks|thank you)\b", candidate, flags=re.IGNORECASE)[0].strip()
        words = candidate.split()
        if words:
            cand_name = " ".join(words[:2]) if len(words) > 1 and words[1].lower() in ("san", "sama", "kun", "chan", "senpai") else words[0]
            if cand_name.lower() not in ("what", "who", "why", "how", "please", "something", "anything", "back", "again", "later"):
                return cand_name
    return None


class MemoryManager:
    """Three-layer adaptive memory system: short-term window, episodic summaries, and semantic facts."""

    def __init__(self, config: MemoryConfig):
        self.config = config
        self.conn = get_db_connection(config.db_path)
        self.relationship = RelationshipEngine(self.conn)

    def add_message(
        self,
        character_id: str,
        user_id: str,
        role: str,
        content: str,
        emotion: Optional[str] = None,
    ) -> MessageRecord:
        """Store a chat message in the SQLite conversation history."""
        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO messages (character_id, user_id, role, content, emotion, consolidated, timestamp)
                VALUES (?, ?, ?, ?, ?, 0, ?)
                """,
                (character_id, user_id, role, content, emotion, now),
            )
            msg_id = cursor.lastrowid

        return MessageRecord(
            id=msg_id,
            character_id=character_id,
            user_id=user_id,
            role=role,
            content=content,
            emotion=emotion,
            consolidated=False,
            timestamp=now,
        )

    def get_recent_messages(
        self, character_id: str, user_id: str, limit: Optional[int] = None
    ) -> list[LLMMessage]:
        """Fetch the most recent N messages as LLMMessages for the short-term conversation context."""
        lim = limit or self.config.short_term_window
        cursor = self.conn.execute(
            """
            SELECT role, content FROM (
                SELECT id, role, content FROM messages
                WHERE character_id = ? AND user_id = ?
                ORDER BY id DESC LIMIT ?
            ) ORDER BY id ASC
            """,
            (character_id, user_id, lim),
        )
        return [LLMMessage(role=row["role"], content=row["content"]) for row in cursor.fetchall()]

    def upsert_fact(
        self,
        character_id: str,
        user_id: str,
        category: str,
        key: str,
        value: str,
        confidence: float = 1.0,
    ) -> Fact:
        """Insert or update a long-term user fact with contradiction resolution."""
        now = datetime.now(timezone.utc).isoformat()
        clean_key = key.strip().lower()
        clean_cat = category.strip().lower()

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO facts (character_id, user_id, category, key, value, confidence, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(character_id, user_id, category, key) DO UPDATE SET
                    value = excluded.value,
                    confidence = excluded.confidence,
                    active = 1,
                    updated_at = excluded.updated_at
                """,
                (character_id, user_id, clean_cat, clean_key, value.strip(), confidence, now, now),
            )

        return Fact(
            character_id=character_id,
            user_id=user_id,
            category=clean_cat,
            key=clean_key,
            value=value.strip(),
            confidence=confidence,
            active=True,
            created_at=now,
            updated_at=now,
        )

    def get_preferred_name(self, character_id: str, user_id: str) -> Optional[str]:
        """Retrieve user's stored preferred name overriding defaults."""
        cursor = self.conn.execute(
            """
            SELECT value FROM facts
            WHERE character_id = ? AND user_id = ? AND active = 1
            AND (key IN ('preferred_name', 'user_name', 'name', 'nickname', 'call_me') OR (category = 'identity' AND key LIKE '%name%'))
            ORDER BY CASE WHEN key = 'preferred_name' THEN 0 WHEN key = 'call_me' THEN 1 ELSE 2 END, id DESC LIMIT 1
            """,
            (character_id, user_id),
        )
        row = cursor.fetchone()
        if row and row["value"]:
            return row["value"].strip()
        return None

    def set_preferred_name(self, character_id: str, user_id: str, name: str) -> Fact:
        """Store or update user's preferred name as a permanent identity fact, retiring older contradictory names."""
        clean_name = name.strip()
        with self.conn:
            self.conn.execute(
                """
                UPDATE facts SET active = 0
                WHERE character_id = ? AND user_id = ?
                AND (key IN ('preferred_name', 'user_name', 'name', 'nickname', 'call_me') OR (category = 'identity' AND key LIKE '%name%'))
                """,
                (character_id, user_id),
            )
        return self.upsert_fact(character_id, user_id, "identity", "preferred_name", clean_name, confidence=1.0)

    async def extract_facts_from_turn(
        self,
        character_id: str,
        user_id: str,
        user_message: str,
        assistant_reply: str,
        llm_provider: LLMProvider,
    ) -> list[Fact]:
        """Analyze a conversation turn to automatically extract persistent user facts, preferences, and projects."""
        clean_msg = user_message.strip()
        saved: list[Fact] = []

        cand_name = extract_preferred_name_from_text(clean_msg)
        if cand_name:
            f = self.set_preferred_name(character_id, user_id, cand_name)
            saved.append(f)

        if len(clean_msg) < 8 or clean_msg.lower() in ("hi", "hello", "hey", "goof", "yes", "no", "ok", "confirm"):
            return saved

        prompt = (
            f"You are a memory analysis engine for companion assistant Roxy.\n"
            f"Analyze this single conversation turn with user '{user_id}'.\n"
            f"Identify if the user stated or directly implied any persistent facts, preferences, current projects, "
            f"skills, habits, technical stacks, schedule/routines, or personal details about themselves.\n"
            f"Do NOT extract temporary states (like 'user is sleepy today') or trivial chit-chat.\n"
            f"Respond ONLY with a JSON array in this exact schema, or [] if no persistent facts are found:\n"
            f'[\n  {{"category": "preference|project|identity|habit|tech_stack", "key": "short_snake_case_key", "value": "concise description"}}\n]\n\n'
            f"User message: {user_message}\n"
            f"Assistant response: {assistant_reply}"
        )

        try:
            reply = await llm_provider.chat([LLMMessage(role="system", content=prompt)])
            clean_reply = reply.strip()
            if clean_reply.startswith("```"):
                clean_reply = clean_reply.split("\n", 1)[-1]
                if clean_reply.endswith("```"):
                    clean_reply = clean_reply.rsplit("```", 1)[0]
            items = json.loads(clean_reply.strip())
            if isinstance(items, list):
                for item in items:
                    cat = item.get("category", "general")
                    k = item.get("key", "").strip()
                    v = item.get("value", "").strip()
                    if k and v:
                        if k in ("name", "preferred_name", "user_name", "nickname", "call_me") and self.get_preferred_name(character_id, user_id):
                            continue
                        f = self.upsert_fact(character_id, user_id, cat, k, v)
                        saved.append(f)
            return saved
        except Exception:
            return saved

    def get_facts(self, character_id: str, user_id: str, active_only: bool = True) -> list[Fact]:
        """Retrieve all long-term facts for a character-user pair."""
        query = "SELECT * FROM facts WHERE character_id = ? AND user_id = ?"
        params: list[object] = [character_id, user_id]
        if active_only:
            query += " AND active = 1"
        query += " ORDER BY category ASC, key ASC"

        cursor = self.conn.execute(query, params)
        return [Fact(**dict(row)) for row in cursor.fetchall()]

    def forget_fact(self, character_id: str, user_id: str, query_or_id: str) -> int:
        """Deactivate or remove a fact matching an ID or key search term."""
        with self.conn:
            if query_or_id.isdigit():
                cursor = self.conn.execute(
                    "UPDATE facts SET active = 0 WHERE id = ? AND character_id = ? AND user_id = ?",
                    (int(query_or_id), character_id, user_id),
                )
            else:
                pattern = f"%{query_or_id.strip().lower()}%"
                cursor = self.conn.execute(
                    """
                    UPDATE facts SET active = 0
                    WHERE character_id = ? AND user_id = ?
                    AND (key LIKE ? OR value LIKE ? OR category LIKE ?)
                    """,
                    (character_id, user_id, pattern, pattern, pattern),
                )
            return cursor.rowcount

    def search_memory(self, character_id: str, user_id: str, query: str, limit: int = 5) -> list[str]:
        """Search across both facts and episodes using SQLite FTS5."""
        if not query.strip():
            return []

        # Sanitize FTS5 query
        clean_q = "".join(c for c in query if c.isalnum() or c.isspace()).strip()
        if not clean_q:
            return []

        fts_term = " OR ".join(clean_q.split())
        results: list[str] = []

        try:
            # Search facts
            f_cursor = self.conn.execute(
                """
                SELECT f.category, f.key, f.value
                FROM facts_fts fts
                JOIN facts f ON f.id = fts.rowid
                WHERE facts_fts MATCH ? AND f.character_id = ? AND f.user_id = ? AND f.active = 1
                LIMIT ?
                """,
                (fts_term, character_id, user_id, limit),
            )
            for row in f_cursor.fetchall():
                results.append(f"Fact ({row['category']}): {row['key']} = {row['value']}")

            # Search episodic summaries
            e_cursor = self.conn.execute(
                """
                SELECT e.summary
                FROM episodes_fts fts
                JOIN episodes e ON e.id = fts.rowid
                WHERE episodes_fts MATCH ? AND e.character_id = ? AND e.user_id = ?
                LIMIT ?
                """,
                (fts_term, character_id, user_id, limit),
            )
            for row in e_cursor.fetchall():
                results.append(f"Episode: {row['summary']}")
        except Exception:
            pass

        return results[:limit]

    def get_recent_episodes(self, character_id: str, user_id: str, limit: int = 3) -> list[Episode]:
        """Fetch the most recent consolidated episodic summaries."""
        cursor = self.conn.execute(
            """
            SELECT * FROM episodes
            WHERE character_id = ? AND user_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (character_id, user_id, limit),
        )
        return [Episode(**dict(row)) for row in cursor.fetchall()]

    async def consolidate_if_needed(
        self,
        character_id: str,
        user_id: str,
        llm_provider: LLMProvider,
    ) -> Optional[Episode]:
        """Check unconsolidated message count and trigger episodic memory consolidation when threshold reached."""
        cursor = self.conn.execute(
            """
            SELECT COUNT(*) AS count FROM messages
            WHERE character_id = ? AND user_id = ? AND consolidated = 0
            """,
            (character_id, user_id),
        )
        count = cursor.fetchone()["count"]

        if count < self.config.auto_consolidate_interval:
            return None

        return await self.consolidate(character_id, user_id, llm_provider)

    async def consolidate(
        self,
        character_id: str,
        user_id: str,
        llm_provider: LLMProvider,
    ) -> Optional[Episode]:
        """Summarize unconsolidated messages into an episode and extract permanent user facts."""
        cursor = self.conn.execute(
            """
            SELECT id, role, content FROM messages
            WHERE character_id = ? AND user_id = ? AND consolidated = 0
            ORDER BY id ASC
            """,
            (character_id, user_id),
        )
        rows = cursor.fetchall()
        if not rows:
            return None

        convo_lines = [f"{r['role'].upper()}: {r['content']}" for r in rows]
        convo_text = "\n".join(convo_lines)
        msg_ids = [r["id"] for r in rows]

        prompt = (
            "You are a memory consolidation engine. Analyze the following conversation excerpt and:\n"
            "1. Produce a concise 1-2 sentence narrative summary of what happened or what was discussed.\n"
            "2. Extract any new or updated personal facts, preferences, habits, or projects about the user.\n"
            "Respond ONLY with valid JSON in this exact structure:\n"
            "{\n"
            '  "summary": "...",\n'
            '  "facts": [\n'
            '    {"category": "preference|habit|project|identity|schedule", "key": "...", "value": "..."}\n'
            "  ]\n"
            "}\n\n"
            f"Conversation:\n{convo_text}"
        )

        reply = await llm_provider.chat([LLMMessage(role="system", content=prompt)])

        summary = "Past interaction between user and companion."
        facts_to_save: list[dict] = []

        # Parse JSON from reply
        try:
            # Strip markdown code fences if present
            clean_reply = reply.strip()
            if clean_reply.startswith("```"):
                clean_reply = clean_reply.split("\n", 1)[-1]
                if clean_reply.endswith("```"):
                    clean_reply = clean_reply.rsplit("```", 1)[0]
            parsed = json.loads(clean_reply.strip())
            summary = parsed.get("summary", summary)
            facts_to_save = parsed.get("facts", [])
        except Exception:
            # Fallback summary if parsing fails
            summary = f"Interaction discussing: {rows[0]['content'][:60]}..."

        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            c = self.conn.execute(
                """
                INSERT INTO episodes (character_id, user_id, summary, message_count, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (character_id, user_id, summary, len(msg_ids), now),
            )
            episode_id = c.lastrowid

            # Save extracted facts
            for item in facts_to_save:
                cat = item.get("category", "general")
                k = item.get("key", "")
                v = item.get("value", "")
                if k and v:
                    self.upsert_fact(character_id, user_id, cat, k, v)

            # Mark messages as consolidated
            placeholders = ",".join("?" for _ in msg_ids)
            self.conn.execute(
                f"UPDATE messages SET consolidated = 1 WHERE id IN ({placeholders})",
                msg_ids,
            )

        return Episode(
            id=episode_id,
            character_id=character_id,
            user_id=user_id,
            summary=summary,
            message_count=len(msg_ids),
            created_at=now,
        )

    def build_context_injection(
        self,
        character_id: str,
        user_id: str,
        current_query: str = "",
    ) -> str:
        """Construct the memory context block to be injected into the system prompt."""
        sections = []

        # 1. Preferred Name & Identity Guidance
        pref_name = self.get_preferred_name(character_id, user_id)
        if pref_name:
            sections.append(f"User Preferred Name & Identity:\n- User's preferred name is '{pref_name}'. You MUST address the user exclusively and consistently as '{pref_name}'.")

        # 2. Facts
        facts = self.get_facts(character_id, user_id, active_only=True)
        if facts:
            fact_lines = [
                f"- [{f.category}] {f.key}: {f.value}"
                for f in facts
                if f.key not in ("name", "preferred_name", "user_name", "nickname", "call_me")
            ]
            if fact_lines:
                sections.append("Known Facts & Preferences about User:\n" + "\n".join(fact_lines))

        # 2. Recent episodes
        episodes = self.get_recent_episodes(character_id, user_id, limit=2)
        if episodes:
            ep_lines = [f"- {e.summary}" for e in reversed(episodes)]
            sections.append("Previous Interaction History:\n" + "\n".join(ep_lines))

        # 3. Relevant search matches for the current user query
        if current_query:
            relevant = self.search_memory(character_id, user_id, current_query, limit=3)
            if relevant:
                sections.append("Relevant Recalled Memories:\n" + "\n".join(f"- {r}" for r in relevant))

        # 4. Relationship and Demeanor Guidance
        rel_guidance = self.relationship.get_state(character_id, user_id).build_prompt_guidance()

        memory_block = ""
        if sections:
            memory_block = "\n\n### Companion Long-Term Memory:\n" + "\n\n".join(sections) + "\n"

        return memory_block + rel_guidance

    def export_memory(self, character_id: str, user_id: str, filepath: Optional[str | Path] = None) -> Path:
        """Export all memory data (facts, episodes, recent messages) to a readable markdown file."""
        facts = self.get_facts(character_id, user_id, active_only=False)
        episodes = self.get_recent_episodes(character_id, user_id, limit=50)
        recent = self.get_recent_messages(character_id, user_id, limit=50)

        lines = [
            f"# Memory Export for {character_id} (User: {user_id})",
            f"Generated: {datetime.now(timezone.utc).isoformat()}\n",
            "## 📌 Long-Term Facts",
        ]
        if facts:
            for f in facts:
                status = "Active" if f.active else "Forgotten"
                lines.append(f"- **[{f.category}]** `{f.key}`: {f.value} *(status: {status})*")
        else:
            lines.append("- *(No facts recorded)*")

        lines.append("\n## 📖 Episodic Memory Summaries")
        if episodes:
            for e in episodes:
                lines.append(f"- **{e.created_at[:10]}** ({e.message_count} msgs): {e.summary}")
        else:
            lines.append("- *(No episodes recorded)*")

        lines.append("\n## 💬 Recent Messages")
        for m in recent:
            lines.append(f"- **{m.role.upper()}**: {m.content}")

        content = "\n".join(lines)

        out_path = Path(filepath or f"memory_export_{character_id}_{user_id}.md")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)

        return out_path

    def wipe_memory(self, character_id: str, user_id: str) -> None:
        """Erase all messages, episodes, and facts for a character and user."""
        with self.conn:
            self.conn.execute("DELETE FROM messages WHERE character_id = ? AND user_id = ?", (character_id, user_id))
            self.conn.execute("DELETE FROM episodes WHERE character_id = ? AND user_id = ?", (character_id, user_id))
            self.conn.execute("DELETE FROM facts WHERE character_id = ? AND user_id = ?", (character_id, user_id))
