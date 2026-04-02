#!/usr/bin/env python3
"""
Reel Agent — Callback Client

Sends outbound HTTP callbacks to OpenClaw when job status changes.
Failed callbacks are queued in SQLite for background retry (exponential backoff).
Non-critical: failures never propagate to the pipeline.
"""

import ipaddress
import json
import logging
import os
import time
from urllib.parse import urlparse

import aiosqlite
import httpx

logger = logging.getLogger(__name__)

OPENCLAW_CALLBACK_SECRET = os.getenv("OPENCLAW_CALLBACK_SECRET", "")
CALLBACK_TIMEOUT = 10  # seconds

# Retry queue DB path — same directory as jobs.db
_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "jobs.db")

# Exponential backoff: 30s, 60s, 120s, …
RETRY_BACKOFF_BASE = 30
# Default max retry attempts (configurable via env)
DEFAULT_MAX_ATTEMPTS = int(os.getenv("CALLBACK_MAX_ATTEMPTS", "10"))


def _is_safe_callback_url(url: str) -> bool:
    """Reject callback URLs pointing to private/reserved IP ranges (SSRF protection)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname or ""
        if not hostname:
            return False
        # Block obvious loopback/metadata hostnames
        if hostname in ("localhost", "metadata.google.internal"):
            return False
        # Try to parse as IP address directly
        try:
            addr = ipaddress.ip_address(hostname)
            return addr.is_global
        except ValueError:
            pass
        # Hostname is a domain name — allow (DNS resolution happens at request time;
        # full DNS-rebinding protection would require resolving here, but that adds
        # latency and complexity; blocking raw IPs covers the most common SSRF vectors)
        return True
    except Exception:
        return False


class CallbackClient:
    """Async HTTP client for OpenClaw outbound callbacks with retry queue."""

    def __init__(self, timeout: int = CALLBACK_TIMEOUT, db_path: str = _DB_PATH):
        self._timeout = timeout
        self._db_path = db_path

    async def send(self, url: str, payload: dict) -> bool:
        """
        POST payload to url. Returns True on 2xx.
        On failure, enqueues for background retry. Never raises.
        """
        if not url:
            return False

        if not _is_safe_callback_url(url):
            logger.warning("Callback URL blocked by SSRF filter: %s", url)
            return False

        ok = await self._do_send(url, payload)
        if not ok:
            await self._enqueue(url, payload, error="initial send failed")
        return ok

    async def _do_send(self, url: str, payload: dict) -> bool:
        """Raw HTTP POST. Returns True on 2xx, False otherwise."""
        headers = {"Content-Type": "application/json"}
        if OPENCLAW_CALLBACK_SECRET:
            headers["X-Reel-Secret"] = OPENCLAW_CALLBACK_SECRET

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code >= 400:
                    logger.warning(
                        "Callback to %s returned %d: %s",
                        url, resp.status_code, resp.text[:200],
                    )
                    return False
                return True
        except httpx.TimeoutException:
            logger.warning("Callback timeout: %s", url)
            return False
        except Exception as exc:
            logger.warning("Callback error (%s): %s", url, exc)
            return False

    async def _enqueue(self, url: str, payload: dict, error: str = "") -> None:
        """Insert a failed callback into the retry queue."""
        now = time.time()
        next_retry = now + RETRY_BACKOFF_BASE
        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """INSERT INTO callback_queue
                       (url, payload, attempts, max_attempts, next_retry, created_at, last_error)
                       VALUES (?, ?, 1, ?, ?, ?, ?)""",
                    (url, json.dumps(payload, ensure_ascii=False),
                     DEFAULT_MAX_ATTEMPTS, next_retry, now, error),
                )
                await db.commit()
            logger.info("Callback queued for retry: %s", url)
        except Exception as exc:
            logger.warning("Failed to enqueue callback: %s", exc)

    async def flush_retry_queue(self) -> int:
        """
        Process due callbacks from the retry queue.
        Returns number of callbacks successfully sent.
        Called periodically by a background task.
        """
        now = time.time()
        sent = 0
        rows: list[dict] = []
        try:
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM callback_queue WHERE next_retry <= ? ORDER BY next_retry ASC LIMIT 20",
                    (now,),
                ) as cursor:
                    rows = [dict(r) for r in await cursor.fetchall()]

                for row in rows:
                    payload = json.loads(row["payload"])
                    ok = await self._do_send(row["url"], payload)

                    if ok:
                        await db.execute("DELETE FROM callback_queue WHERE id = ?", (row["id"],))
                        sent += 1
                    else:
                        attempts = row["attempts"] + 1
                        if attempts >= row["max_attempts"]:
                            logger.warning(
                                "Callback to %s exhausted %d attempts — moving to dead letter",
                                row["url"], attempts,
                            )
                            await db.execute(
                                """INSERT INTO dead_letter_callbacks
                                   (url, payload, attempts, created_at, dead_at, last_error)
                                   VALUES (?, ?, ?, ?, ?, ?)""",
                                (row["url"], row["payload"], attempts,
                                 row["created_at"], now, "exhausted retries"),
                            )
                            await db.execute("DELETE FROM callback_queue WHERE id = ?", (row["id"],))
                        else:
                            next_retry = now + RETRY_BACKOFF_BASE * (2 ** (attempts - 1))
                            await db.execute(
                                "UPDATE callback_queue SET attempts = ?, next_retry = ?, last_error = ? WHERE id = ?",
                                (attempts, next_retry, "retry failed", row["id"]),
                            )

                await db.commit()
        except Exception as exc:
            logger.warning("flush_retry_queue error: %s", exc)

        if sent:
            logger.info("Callback retry: %d/%d sent successfully", sent, len(rows))
        return sent
