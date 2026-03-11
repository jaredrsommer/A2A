"""Knowledge base — curated entries for persistent knowledge."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """Curated knowledge entries backed by SQLite.

    Unlike MemoryStore (automatic task history), KnowledgeBase stores
    manually curated entries — project conventions, API docs, decisions, etc.
    """

    def __init__(self, db: aiosqlite.Connection):
        self._db = db

    async def initialize(self) -> None:
        """Create knowledge tables."""
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT DEFAULT '[]',
                source_task_id TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_knowledge_tags ON knowledge(tags);
        """)
        await self._db.commit()

    async def add_entry(
        self,
        title: str,
        content: str,
        tags: list[str] | None = None,
        source_task_id: str = "",
    ) -> int:
        """Add a knowledge entry."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            """INSERT INTO knowledge (title, content, tags, source_task_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (title, content, json.dumps(tags or []), source_task_id, now, now),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def update_entry(self, entry_id: int, title: str = "", content: str = "", tags: list[str] | None = None) -> bool:
        """Update a knowledge entry."""
        entry = await self.get_entry(entry_id)
        if not entry:
            return False

        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """UPDATE knowledge SET title = ?, content = ?, tags = ?, updated_at = ? WHERE id = ?""",
            (
                title or entry["title"],
                content or entry["content"],
                json.dumps(tags) if tags is not None else entry["tags_raw"],
                now,
                entry_id,
            ),
        )
        await self._db.commit()
        return True

    async def delete_entry(self, entry_id: int) -> bool:
        """Delete a knowledge entry."""
        cursor = await self._db.execute("DELETE FROM knowledge WHERE id = ?", (entry_id,))
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_entry(self, entry_id: int) -> dict | None:
        """Get a single entry."""
        async with self._db.execute(
            "SELECT id, title, content, tags, source_task_id, created_at, updated_at FROM knowledge WHERE id = ?",
            (entry_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return _row_to_dict(row)

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search knowledge entries by keyword."""
        pattern = f"%{query}%"
        async with self._db.execute(
            """SELECT id, title, content, tags, source_task_id, created_at, updated_at
               FROM knowledge WHERE title LIKE ? OR content LIKE ? OR tags LIKE ?
               ORDER BY updated_at DESC LIMIT ?""",
            (pattern, pattern, pattern, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def get_by_tag(self, tag: str, limit: int = 20) -> list[dict]:
        """Get entries with a specific tag."""
        pattern = f'%"{tag}"%'
        async with self._db.execute(
            """SELECT id, title, content, tags, source_task_id, created_at, updated_at
               FROM knowledge WHERE tags LIKE ? ORDER BY updated_at DESC LIMIT ?""",
            (pattern, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def get_all(self, limit: int = 50) -> list[dict]:
        """Get all entries."""
        async with self._db.execute(
            """SELECT id, title, content, tags, source_task_id, created_at, updated_at
               FROM knowledge ORDER BY updated_at DESC LIMIT ?""",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]


def _row_to_dict(row: tuple) -> dict:
    return {
        "id": row[0],
        "title": row[1],
        "content": row[2],
        "tags": json.loads(row[3]) if row[3] else [],
        "tags_raw": row[3],
        "source_task_id": row[4],
        "created_at": row[5],
        "updated_at": row[6],
    }
