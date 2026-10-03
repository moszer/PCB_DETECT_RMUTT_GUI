"""Chat history per conversation (one per inspected image), kept in the station SQLite DB."""
from __future__ import annotations

import time
from typing import Dict, List

from .storage_service import storage_service

MAX_KEY_LEN = 512


def _ensure_table() -> None:
    with storage_service._get_connection() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conv_key TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_conv ON chat_messages (conv_key, id)")


_ensure_table()


def history(key: str) -> List[Dict[str, object]]:
    with storage_service._get_connection() as conn:
        rows = conn.execute(
            "SELECT role, content, created_at FROM chat_messages WHERE conv_key = ? ORDER BY id", (key[:MAX_KEY_LEN],)
        ).fetchall()
    return [{"role": r["role"], "content": r["content"], "created_at": r["created_at"]} for r in rows]


def append_exchange(key: str, question: str, answer: str) -> None:
    """Store a question with its answer together, so history always alternates user/assistant."""
    now = time.time()
    with storage_service._get_connection() as conn:
        conn.executemany(
            "INSERT INTO chat_messages (conv_key, role, content, created_at) VALUES (?, ?, ?, ?)",
            [(key[:MAX_KEY_LEN], "user", question, now), (key[:MAX_KEY_LEN], "assistant", answer, now)],
        )


def clear(key: str) -> int:
    with storage_service._get_connection() as conn:
        return conn.execute("DELETE FROM chat_messages WHERE conv_key = ?", (key[:MAX_KEY_LEN],)).rowcount
