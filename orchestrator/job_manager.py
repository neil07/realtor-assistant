#!/usr/bin/env python3
"""
Reel Agent — Job Manager

SQLite-backed state machine for video generation jobs.
Supports concurrent jobs, status persistence across restarts,
and per-step output storage for resume/retry.

States: QUEUED → ANALYZING → SCRIPTING → PROMPTING → PRODUCING → ASSEMBLING → DELIVERED
        Any state → FAILED | CANCELLED
"""

import json
import os
import time
import uuid
from typing import Any

import aiosqlite

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "jobs.db")

# Valid status transitions (from → set of allowed next states)
TRANSITIONS: dict[str, set[str]] = {
    "QUEUED":     {"ANALYZING", "FAILED", "CANCELLED"},
    "ANALYZING":  {"SCRIPTING", "FAILED", "CANCELLED"},
    "SCRIPTING":  {"PROMPTING", "FAILED", "CANCELLED"},
    "PROMPTING":  {"PRODUCING", "FAILED", "CANCELLED"},
    "PRODUCING":  {"ASSEMBLING", "FAILED", "CANCELLED"},
    "ASSEMBLING": {"DELIVERED", "FAILED", "CANCELLED"},
    "DELIVERED":  set(),
    "FAILED":     {"QUEUED"},   # retry resets to QUEUED
    "CANCELLED":  set(),
}

INIT_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id          TEXT PRIMARY KEY,
    agent_phone     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'QUEUED',
    params          TEXT NOT NULL,
    photo_dir       TEXT NOT NULL,
    file_ids        TEXT,
    output_dir      TEXT,

    analysis        TEXT,
    scenes          TEXT,
    script          TEXT,
    prompts         TEXT,
    clips           TEXT,
    narrations      TEXT,
    video_path      TEXT,

    current_step    TEXT,
    step_started_at REAL,
    retry_count     INTEGER DEFAULT 0,
    last_error      TEXT,
    cost_usd        REAL DEFAULT 0.0,

    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    completed_at    REAL,
    callback_url    TEXT,
    openclaw_msg_id TEXT,

    -- 2.0: revision support
    parent_job_id   TEXT REFERENCES jobs(job_id),
    revision_context TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_agent_phone ON jobs(agent_phone);
CREATE INDEX IF NOT EXISTS idx_jobs_status      ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at  ON jobs(created_at);
"""

# Step name → column name mapping
STEP_COLUMNS = {
    "analysis":   "analysis",
    "scenes":     "scenes",
    "script":     "script",
    "prompts":    "prompts",
    "clips":      "clips",
    "narrations": "narrations",
}


class JobManager:
    """Async interface to the jobs SQLite database."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    async def init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(INIT_SQL)
            await db.commit()

    # ------------------------------------------------------------------
    # Job lifecycle
    # ------------------------------------------------------------------

    async def create_job(
        self,
        agent_phone: str,
        photo_dir: str,
        params: dict,
        output_dir: str | None = None,
        callback_url: str | None = None,
        openclaw_msg_id: str | None = None,
        parent_job_id: str | None = None,
        revision_context: dict | None = None,
    ) -> str:
        """Create a new QUEUED job. Returns job_id."""
        now = time.time()
        job_id = f"{int(now)}_{uuid.uuid4().hex[:8]}"
        if output_dir is None:
            output_dir = os.path.join(
                os.path.dirname(photo_dir), job_id
            )
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO jobs (
                    job_id, agent_phone, status, params,
                    photo_dir, output_dir, callback_url, openclaw_msg_id,
                    created_at, updated_at,
                    parent_job_id, revision_context
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id, agent_phone, "QUEUED",
                    json.dumps(params, ensure_ascii=False),
                    photo_dir, output_dir, callback_url, openclaw_msg_id,
                    now, now,
                    parent_job_id,
                    json.dumps(revision_context, ensure_ascii=False) if revision_context else None,
                ),
            )
            await db.commit()
        return job_id

    async def get_job(self, job_id: str) -> dict | None:
        """Fetch a job by ID. Returns None if not found."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def update_status(
        self,
        job_id: str,
        status: str,
        current_step: str | None = None,
        **extra_fields: Any,
    ) -> None:
        """
        Update job status + updated_at + optional extra fields.
        Allowed extra_fields: file_ids, output_dir, video_path, cost_usd,
                              completed_at, last_error, retry_count.
        """
        allowed_extras = {
            "file_ids", "output_dir", "video_path", "cost_usd",
            "completed_at", "last_error", "retry_count", "step_started_at",
        }
        filtered = {k: v for k, v in extra_fields.items() if k in allowed_extras}

        set_clauses = ["status = ?", "updated_at = ?"]
        values: list[Any] = [status, time.time()]

        if current_step is not None:
            set_clauses.append("current_step = ?")
            values.append(current_step)
            set_clauses.append("step_started_at = ?")
            values.append(time.time())

        for col, val in filtered.items():
            set_clauses.append(f"{col} = ?")
            if isinstance(val, (dict, list)):
                values.append(json.dumps(val, ensure_ascii=False))
            else:
                values.append(val)

        values.append(job_id)
        sql = f"UPDATE jobs SET {', '.join(set_clauses)} WHERE job_id = ?"

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(sql, values)
            await db.commit()

    async def save_step_output(
        self, job_id: str, step_name: str, output: dict | list
    ) -> None:
        """Serialize and persist a Skill's output to the corresponding column."""
        col = STEP_COLUMNS.get(step_name)
        if not col:
            raise ValueError(f"Unknown step: {step_name}. Valid: {list(STEP_COLUMNS)}")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                f"UPDATE jobs SET {col} = ?, updated_at = ? WHERE job_id = ?",
                (json.dumps(output, ensure_ascii=False, default=str), time.time(), job_id),
            )
            await db.commit()

    async def load_step_output(
        self, job_id: str, step_name: str
    ) -> dict | list | None:
        """Deserialize a Skill's output. Returns None if not yet saved."""
        col = STEP_COLUMNS.get(step_name)
        if not col:
            raise ValueError(f"Unknown step: {step_name}")
        async with aiosqlite.connect(self.db_path) as db, db.execute(
            f"SELECT {col} FROM jobs WHERE job_id = ?", (job_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                return json.loads(row[0])
            return None

    async def mark_failed(
        self, job_id: str, error: str, retry_count: int | None = None
    ) -> None:
        """Mark job as FAILED, record the error message."""
        updates: dict[str, Any] = {"last_error": error}
        if retry_count is not None:
            updates["retry_count"] = retry_count
        await self.update_status(job_id, "FAILED", **updates)

    async def mark_cancelled(self, job_id: str) -> None:
        await self.update_status(job_id, "CANCELLED")

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def list_pending_jobs(self) -> list[dict]:
        """
        Return all jobs that are in-flight (not yet terminal).
        Used on service startup to resume interrupted work.
        """
        terminal = ("DELIVERED", "FAILED", "CANCELLED")
        placeholders = ",".join("?" for _ in terminal)
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT * FROM jobs WHERE status NOT IN ({placeholders})"
                " ORDER BY created_at ASC",
                terminal,
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def list_jobs_by_phone(
        self, agent_phone: str, limit: int = 20
    ) -> list[dict]:
        """Return recent jobs for a given WhatsApp number."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT job_id, status, current_step, created_at, completed_at, video_path"
                " FROM jobs WHERE agent_phone = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (agent_phone, limit),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def get_job_summary(self, job_id: str) -> dict | None:
        """Lightweight job summary (no large JSON blobs)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT job_id, agent_phone, status, current_step,
                          retry_count, last_error, cost_usd,
                          created_at, updated_at, completed_at, video_path, output_dir
                   FROM jobs WHERE job_id = ?""",
                (job_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
