"""Task memory store — SQLite-backed persistent memory."""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


class MemoryStore:
    """SQLite-backed store for task results and agent history.

    Supports keyword/TF-IDF search for finding relevant past work.
    """

    def __init__(self, db_path: str = "data/memory.db"):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open database and create tables."""
        self._db = await aiosqlite.connect(str(self._db_path))
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS task_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                agent_name TEXT DEFAULT '',
                project_id TEXT DEFAULT '',
                input_text TEXT NOT NULL,
                output_text TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_task_results_task_id ON task_results(task_id);
            CREATE INDEX IF NOT EXISTS idx_task_results_agent_id ON task_results(agent_id);
            CREATE INDEX IF NOT EXISTS idx_task_results_project_id ON task_results(project_id);
        """)
        await self._db.commit()
        logger.info(f"MemoryStore initialized at {self._db_path}")

    async def save_task_result(
        self,
        task_id: str,
        agent_id: str,
        input_text: str,
        output_text: str,
        agent_name: str = "",
        project_id: str = "",
        metadata: dict | None = None,
    ) -> int:
        """Save a completed task result to memory."""
        if not self._db:
            raise RuntimeError("MemoryStore not initialized")

        cursor = await self._db.execute(
            """INSERT INTO task_results
               (task_id, agent_id, agent_name, project_id, input_text, output_text, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task_id,
                agent_id,
                agent_name,
                project_id,
                input_text,
                output_text,
                json.dumps(metadata or {}),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def search_similar(self, query: str, limit: int = 5) -> list[dict]:
        """Search for similar past tasks using keyword/TF-IDF matching."""
        if not self._db:
            return []

        # Get all results for scoring
        async with self._db.execute(
            "SELECT id, task_id, agent_id, agent_name, input_text, output_text, created_at FROM task_results"
        ) as cursor:
            rows = await cursor.fetchall()

        if not rows:
            return []

        # Simple TF-IDF scoring
        query_terms = _tokenize(query)
        if not query_terms:
            return []

        # Build document frequencies
        doc_count = len(rows)
        doc_freq: Counter = Counter()
        doc_tokens: list[list[str]] = []

        for row in rows:
            tokens = _tokenize(f"{row[4]} {row[5]}")
            doc_tokens.append(tokens)
            for term in set(tokens):
                doc_freq[term] += 1

        # Score each document
        scored = []
        for i, row in enumerate(rows):
            tokens = doc_tokens[i]
            if not tokens:
                continue
            tf = Counter(tokens)
            score = 0.0
            for term in query_terms:
                if term in tf:
                    tf_val = tf[term] / len(tokens)
                    idf_val = math.log(doc_count / (1 + doc_freq.get(term, 0)))
                    score += tf_val * idf_val

            if score > 0:
                scored.append((score, row))

        scored.sort(key=lambda x: x[0], reverse=True)

        return [
            {
                "id": row[0],
                "task_id": row[1],
                "agent_id": row[2],
                "agent_name": row[3],
                "input": row[4][:500],
                "output": row[5][:500],
                "created_at": row[6],
                "relevance_score": round(score, 4),
            }
            for score, row in scored[:limit]
        ]

    async def get_agent_history(self, agent_id: str, limit: int = 20) -> list[dict]:
        """Get recent task history for a specific agent."""
        if not self._db:
            return []

        async with self._db.execute(
            """SELECT task_id, input_text, output_text, created_at
               FROM task_results WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?""",
            (agent_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()

        return [
            {
                "task_id": row[0],
                "input": row[1][:500],
                "output": row[2][:500],
                "created_at": row[3],
            }
            for row in rows
        ]

    async def get_project_context(self, project_id: str, limit: int = 20) -> list[dict]:
        """Get task history for a project."""
        if not self._db:
            return []

        async with self._db.execute(
            """SELECT task_id, agent_id, agent_name, input_text, output_text, created_at
               FROM task_results WHERE project_id = ? ORDER BY created_at DESC LIMIT ?""",
            (project_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()

        return [
            {
                "task_id": row[0],
                "agent_id": row[1],
                "agent_name": row[2],
                "input": row[3][:500],
                "output": row[4][:500],
                "created_at": row[5],
            }
            for row in rows
        ]

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer for TF-IDF."""
    text = text.lower()
    tokens = re.findall(r'\b[a-z_][a-z0-9_]*\b', text)
    # Filter stop words
    stop = {"the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "can", "shall", "to", "of", "in", "for",
            "on", "with", "at", "by", "from", "as", "into", "through", "during",
            "before", "after", "above", "below", "between", "and", "but", "or",
            "not", "no", "nor", "so", "yet", "both", "either", "neither", "each",
            "every", "all", "any", "few", "more", "most", "other", "some", "such",
            "than", "too", "very", "just", "also", "it", "its", "this", "that",
            "these", "those", "i", "me", "my", "we", "us", "our", "you", "your",
            "he", "him", "his", "she", "her", "they", "them", "their", "what",
            "which", "who", "whom", "when", "where", "why", "how"}
    return [t for t in tokens if t not in stop and len(t) > 1]
