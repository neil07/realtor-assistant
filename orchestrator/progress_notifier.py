#!/usr/bin/env python3
"""
Reel Agent — Progress Notifier

Sends progress, delivery, and failure notifications to OpenClaw
via the CallbackClient. All methods are fire-and-forget safe.
"""

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.callback_client import CallbackClient

logger = logging.getLogger(__name__)

# Progress messages shown to the WhatsApp user via OpenClaw
STEP_MESSAGES = {
    "analyzing":   "Analyzing your photos...",
    "scripting":   "Writing the voiceover script...",
    "prompting":   "Planning camera moves...",
    "producing":   "Generating AI video clips (this takes ~2 min)...",
    "assembling":  "Assembling the final video...",
    "done":        "Your listing video is ready!",
}


class ProgressNotifier:
    """Sends job lifecycle events to OpenClaw."""

    def __init__(self, callback_client: "CallbackClient"):
        self.client = callback_client
        self._base_url = os.getenv("OPENCLAW_CALLBACK_BASE_URL", "")

    async def notify_progress(
        self,
        job_id: str,
        step: str,
        message: str,
        job: dict,
    ) -> None:
        """Send a progress update. Non-critical — swallows all errors."""
        url = job.get("callback_url") or self._build_url("/events")
        if not url:
            return
        await self.client.send(url, {
            "type": "progress",
            "job_id": job_id,
            "openclaw_msg_id": job.get("openclaw_msg_id"),
            "agent_phone": job.get("agent_phone"),
            "step": step,
            "message": message,
        })

    async def notify_delivered(
        self,
        job_id: str,
        result: dict,
        job: dict,
    ) -> None:
        """Notify OpenClaw that the video is ready."""
        url = job.get("callback_url") or self._build_url("/events")
        if not url:
            logger.info("No callback URL for job %s — skipping delivery notification", job_id)
            return

        # Build public-accessible video URL if base URL is set
        video_path = result.get("video_path", "")
        video_url = _make_video_url(video_path)

        await self.client.send(url, {
            "type": "delivered",
            "job_id": job_id,
            "openclaw_msg_id": job.get("openclaw_msg_id"),
            "agent_phone": job.get("agent_phone"),
            "video_url": video_url,
            "video_path": video_path,
            "caption": result.get("caption", ""),
            "scene_count": result.get("scene_count", 0),
            "word_count": result.get("word_count", 0),
            "aspect_ratio": result.get("aspect_ratio", "9:16"),
        })

    async def notify_failed(
        self,
        job_id: str,
        error: str,
        job: dict,
    ) -> None:
        """Notify OpenClaw of a job failure with override link."""
        url = job.get("callback_url") or self._build_url("/events")
        if not url:
            return

        retry_count = job.get("retry_count", 0)
        override_url = self._build_url(f"/webhook/manual-override/{job_id}")

        await self.client.send(url, {
            "type": "failed",
            "job_id": job_id,
            "openclaw_msg_id": job.get("openclaw_msg_id"),
            "agent_phone": job.get("agent_phone"),
            "error": error,
            "retry_count": retry_count,
            "override_url": override_url,  # ops team can click to retry/cancel
        })

    async def notify_daily_insight(
        self,
        agent_phone: str,
        insight: dict,
        image_paths: dict[str, str],
        agent: dict,
    ) -> None:
        """
        Push daily market insight to OpenClaw for delivery to agent.

        Args:
            agent_phone: Agent's WhatsApp number
            insight: Generated insight dict (headline, body, caption, hashtags, ...)
            image_paths: Dict of format_name → local file path
            agent: Full agent profile dict
        """
        url = self._build_url("/events")
        if not url:
            logger.info(
                "No callback URL configured — daily insight for %s not pushed", agent_phone
            )
            return

        # Convert local paths to public URLs
        image_urls = {
            fmt: _make_image_url(path)
            for fmt, path in image_paths.items()
        }

        await self.client.send(url, {
            "type": "daily_insight",
            "agent_phone": agent_phone,
            "insight": {
                "topic": insight.get("topic", ""),
                "headline": insight.get("headline", ""),
                "caption": insight.get("caption", ""),
                "hashtags": insight.get("hashtags", []),
                "cta": insight.get("cta", ""),
                "content_type": insight.get("content_type", "market_stat"),
            },
            "image_urls": image_urls,
            "agent_name": agent.get("name", ""),
        })

    def _build_url(self, path: str) -> str:
        base = self._base_url.rstrip("/")
        return f"{base}{path}" if base else ""


def _make_public_url(local_path: str) -> str:
    """Convert a local /output/... path to a public URL if PUBLIC_BASE_URL is set."""
    base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    if not base or not local_path:
        return local_path
    try:
        idx = local_path.find("/output/")
        if idx >= 0:
            return f"{base}{local_path[idx:]}"
    except Exception:
        pass
    return local_path


# Aliases kept for call-site clarity
_make_image_url = _make_public_url
_make_video_url = _make_public_url
