#!/usr/bin/env python3
"""
Reel Agent — Disk Cleanup

Removes output directories for old terminal jobs to reclaim disk space.
  - FAILED jobs:    after 7 days  (configurable via CLEANUP_FAILED_DAYS)
  - CANCELLED jobs: after 7 days
  - DELIVERED jobs: after 30 days (configurable via CLEANUP_DELIVERED_DAYS)

Called periodically by the server lifespan background loop.
"""

import logging
import os
import shutil
import time

import aiosqlite

logger = logging.getLogger(__name__)

FAILED_RETENTION_DAYS = int(os.getenv("CLEANUP_FAILED_DAYS", "7"))
DELIVERED_RETENTION_DAYS = int(os.getenv("CLEANUP_DELIVERED_DAYS", "30"))

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "jobs.db")


async def cleanup_old_jobs(db_path: str = DB_PATH) -> dict:
    """Delete output directories for old terminal jobs.

    Returns:
        Summary dict: {cleaned: int, errors: int, freed_dirs: [...]}
    """
    now = time.time()
    failed_cutoff = now - (FAILED_RETENTION_DAYS * 86400)
    delivered_cutoff = now - (DELIVERED_RETENTION_DAYS * 86400)

    cleaned = 0
    errors = 0
    freed_dirs: list[str] = []

    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row

            # Find eligible jobs
            async with db.execute(
                """SELECT job_id, status, output_dir, completed_at, updated_at
                   FROM jobs
                   WHERE output_dir IS NOT NULL
                     AND (
                       (status IN ('FAILED', 'CANCELLED') AND COALESCE(completed_at, updated_at) < ?)
                       OR
                       (status = 'DELIVERED' AND COALESCE(completed_at, updated_at) < ?)
                     )
                   ORDER BY updated_at ASC
                   LIMIT 50""",
                (failed_cutoff, delivered_cutoff),
            ) as cursor:
                rows = [dict(r) for r in await cursor.fetchall()]

            for row in rows:
                output_dir = row["output_dir"]
                if not output_dir or not os.path.isdir(output_dir):
                    # Already cleaned or never created — just clear the column
                    await db.execute(
                        "UPDATE jobs SET output_dir = NULL WHERE job_id = ?",
                        (row["job_id"],),
                    )
                    continue

                try:
                    shutil.rmtree(output_dir)
                    freed_dirs.append(output_dir)
                    cleaned += 1
                    # Null out output_dir so we don't try again
                    await db.execute(
                        "UPDATE jobs SET output_dir = NULL WHERE job_id = ?",
                        (row["job_id"],),
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to clean %s for job %s: %s",
                        output_dir, row["job_id"], exc,
                    )
                    errors += 1

            # Also prune old dead letter callbacks (>30 days)
            dl_cutoff = now - (30 * 86400)
            await db.execute(
                "DELETE FROM dead_letter_callbacks WHERE dead_at < ?",
                (dl_cutoff,),
            )

            await db.commit()

    except Exception as exc:
        logger.warning("cleanup_old_jobs error: %s", exc)
        errors += 1

    if cleaned:
        logger.info(
            "Disk cleanup: removed %d output dirs (%d errors)", cleaned, errors
        )
    return {"cleaned": cleaned, "errors": errors, "freed_dirs": freed_dirs}
