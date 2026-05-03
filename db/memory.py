"""Persistent memory layer: SQLite (relational) + ChromaDB (vector)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import chromadb
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False

# ── SQLite ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_skills (
    agent_id              TEXT PRIMARY KEY,
    skill_level           REAL    DEFAULT 0.5,
    system_prompt_override TEXT
);

CREATE TABLE IF NOT EXISTS task_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type   TEXT,
    agent_id    TEXT,
    tokens_used INTEGER,
    cost_usd    REAL,
    model_used  TEXT,
    timestamp   TEXT
);

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id     TEXT,
    cron_expr    TEXT,
    task_payload TEXT,
    active       INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS pending_results (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER,
    agent_id   TEXT,
    result     TEXT,
    created_at TEXT,
    delivered  INTEGER DEFAULT 0
);
"""


class Database:
    """Thin SQLite wrapper for agent memory."""

    def __init__(self, path: str | Path = "pixel_hr.db") -> None:
        self.path = str(path)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()

    # ── agent_skills ──────────────────────────────────────────────────────────

    def get_skill(self, agent_id: str) -> dict[str, Any]:
        assert self._conn
        row = self._conn.execute(
            "SELECT * FROM agent_skills WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if row:
            return dict(row)
        return {"agent_id": agent_id, "skill_level": 0.5, "system_prompt_override": None}

    def update_skill(
        self,
        agent_id: str,
        skill_level: float,
        system_prompt_override: str | None = None,
    ) -> None:
        assert self._conn
        self._conn.execute(
            """
            INSERT INTO agent_skills (agent_id, skill_level, system_prompt_override)
            VALUES (?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                skill_level            = excluded.skill_level,
                system_prompt_override = excluded.system_prompt_override
            """,
            (agent_id, skill_level, system_prompt_override),
        )
        self._conn.commit()

    # ── task_history ──────────────────────────────────────────────────────────

    def log_task(
        self,
        task_type: str,
        agent_id: str,
        tokens_used: int,
        cost_usd: float,
        model_used: str = "",
    ) -> None:
        assert self._conn
        ts = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO task_history (task_type, agent_id, tokens_used, cost_usd, model_used, timestamp) "
            "VALUES (?,?,?,?,?,?)",
            (task_type, agent_id, tokens_used, cost_usd, model_used, ts),
        )
        self._conn.commit()

    def get_task_history(self, limit: int = 20) -> list[dict[str, Any]]:
        assert self._conn
        rows = self._conn.execute(
            "SELECT * FROM task_history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── pending_results ───────────────────────────────────────────────────────

    def add_pending_result(self, task_id: int, agent_id: str, result: str) -> None:
        assert self._conn
        ts = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO pending_results (task_id, agent_id, result, created_at) VALUES (?,?,?,?)",
            (task_id, agent_id, result, ts),
        )
        self._conn.commit()

    def get_pending_results(self) -> list[dict[str, Any]]:
        assert self._conn
        rows = self._conn.execute(
            "SELECT * FROM pending_results WHERE delivered = 0 ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_delivered(self, result_id: int) -> None:
        assert self._conn
        self._conn.execute(
            "UPDATE pending_results SET delivered = 1 WHERE id = ?", (result_id,)
        )
        self._conn.commit()

    # ── scheduled_tasks ───────────────────────────────────────────────────────

    def get_active_tasks(self) -> list[dict[str, Any]]:
        assert self._conn
        rows = self._conn.execute(
            "SELECT * FROM scheduled_tasks WHERE active = 1"
        ).fetchall()
        return [dict(r) for r in rows]

    def add_scheduled_task(
        self, agent_id: str, cron_expr: str, task_payload: str
    ) -> int:
        assert self._conn
        cur = self._conn.execute(
            "INSERT INTO scheduled_tasks (agent_id, cron_expr, task_payload) VALUES (?,?,?)",
            (agent_id, cron_expr, task_payload),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


# ── ChromaDB ──────────────────────────────────────────────────────────────────

CHROMA_COLLECTIONS = ["hr_policies", "content_history", "persona_templates"]


class VectorMemory:
    """ChromaDB wrapper for agent long-term vector memory."""

    def __init__(self, path: str | Path = "./chroma_db") -> None:
        self.path = str(path)
        self._client: Any = None
        self._collections: dict[str, Any] = {}

    def connect(self) -> None:
        if not _CHROMA_AVAILABLE:
            return
        self._client = chromadb.PersistentClient(path=self.path)
        for name in CHROMA_COLLECTIONS:
            self._collections[name] = self._client.get_or_create_collection(name)

    def add_document(
        self,
        collection: str,
        doc_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self._client or collection not in self._collections:
            return
        self._collections[collection].add(
            ids=[doc_id],
            documents=[text],
            metadatas=[metadata or {}],
        )

    def query(
        self,
        collection: str,
        query_text: str,
        n_results: int = 3,
    ) -> list[dict[str, Any]]:
        if not self._client or collection not in self._collections:
            return []
        results = self._collections[collection].query(
            query_texts=[query_text],
            n_results=n_results,
        )
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        return [{"text": d, "meta": m} for d, m in zip(docs, metas)]
