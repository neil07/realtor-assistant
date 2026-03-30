#!/usr/bin/env python3
"""
Reel Agent — Callback Client

Sends outbound HTTP callbacks to OpenClaw when job status changes.
Non-critical: failures are logged but never propagate to the pipeline.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

OPENCLAW_CALLBACK_SECRET = os.getenv("OPENCLAW_CALLBACK_SECRET", "")
CALLBACK_TIMEOUT = 10  # seconds


class CallbackClient:
    """Async HTTP client for OpenClaw outbound callbacks."""

    def __init__(self, timeout: int = CALLBACK_TIMEOUT):
        self._timeout = timeout

    async def send(self, url: str, payload: dict) -> bool:
        """
        POST payload to url. Returns True on 2xx, False otherwise.
        Never raises — caller should not care if callback fails.
        """
        if not url:
            return False
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
