from __future__ import annotations

import sqlite3
from pathlib import Path


def get_db_connection(db_path: str | Path) -> sqlite3.Connection:
    """Connect to SQLite database and ensure tables and FTS5 indices are initialized."""
    path = Path(db_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row

    # Optimize for concurrency and performance
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")

    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Create schema, indices, and FTS5 search tables if they do not exist."""
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                emotion TEXT,
                consolidated INTEGER DEFAULT 0,
                timestamp TEXT NOT NULL
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_char_user ON messages(character_id, user_id, id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_consolidated ON messages(consolidated);")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                message_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_char_user ON episodes(character_id, user_id);")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(character_id, user_id, category, key)
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_char_user_cat ON facts(character_id, user_id, category);")

        # FTS5 tables for keyword/semantic ranking
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
                key,
                value,
                category,
                content='facts',
                content_rowid='id'
            );
        """)

        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
                summary,
                content='episodes',
                content_rowid='id'
            );
        """)

        # Triggers to keep FTS updated with table modifications
        conn.executescript("""
            CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
                INSERT INTO facts_fts(rowid, key, value, category) VALUES (new.id, new.key, new.value, new.category);
            END;
            CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
                INSERT INTO facts_fts(facts_fts, rowid, key, value, category) VALUES('delete', old.id, old.key, old.value, old.category);
            END;
            CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
                INSERT INTO facts_fts(facts_fts, rowid, key, value, category) VALUES('delete', old.id, old.key, old.value, old.category);
                INSERT INTO facts_fts(rowid, key, value, category) VALUES (new.id, new.key, new.value, new.category);
            END;

            CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
                INSERT INTO episodes_fts(rowid, summary) VALUES (new.id, new.summary);
            END;
            CREATE TRIGGER IF NOT EXISTS episodes_ad AFTER DELETE ON episodes BEGIN
                INSERT INTO episodes_fts(episodes_fts, rowid, summary) VALUES('delete', old.id, old.summary);
            END;
        """)
