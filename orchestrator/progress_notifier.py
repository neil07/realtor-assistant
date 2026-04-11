#!/usr/bin/env python3
"""
Reel Agent — Progress Notifier

Sends progress, delivery, and failure notifications to OpenClaw
via the CallbackClient. All methods are fire-and-forget safe.
"""

import logging
import os
from pathlib import Path
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


def _normalize_daily_insight_payload(insight: dict) -> dict:
    """Accept both flat and v2 content-pack insight shapes."""
    briefing = insight.get("briefing") or {}
    social = insight.get("social_post") or {}
    meta = insight.get("_meta") or {}

    headline = briefing.get("headline") or insight.get("headline", "")
    key_numbers = briefing.get("key_numbers") or insight.get("key_numbers", "")
    talking_points_buyers = briefing.get("talking_points_buyers") or insight.get(
        "talking_points_buyers", []
    )
    talking_points_sellers = briefing.get("talking_points_sellers") or insight.get(
        "talking_points_sellers", []
    )
    caption = social.get("caption") or insight.get("caption", "")
    hashtags = social.get("hashtags") or insight.get("hashtags", [])
    topic_type = meta.get("topic_type") or insight.get("content_type") or insight.get(
        "topic", "unknown"
    )
    forward_buyer = insight.get("forward_buyer", {})
    forward_seller = insight.get("forward_seller", {})

    return {
        "headline": headline,
        "key_numbers": key_numbers,
        "talking_points_buyers": talking_points_buyers,
        "talking_points_sellers": talking_points_sellers,
        "caption": caption,
        "hashtags": hashtags,
        "topic_type": topic_type,
        "forward_buyer": forward_buyer.get("text", "") if isinstance(forward_buyer, dict) else "",
        "forward_seller": forward_seller.get("text", "") if isinstance(forward_seller, dict) else "",
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

    async def notify_quality_blocked(
        self,
        job_id: str,
        score: float,
        top_issues: list[str],
        job: dict,
    ) -> None:
        """Notify user that video quality is below delivery threshold.

        Offers three choices: retry, degraded delivery, or cancel.
        """
        url = job.get("callback_url") or self._build_url("/events")
        if not url:
            logger.warning(
                "No callback URL for job %s — quality block notification not sent (score=%.1f)",
                job_id, score,
            )
            return

        override_url = self._build_url(f"/webhook/manual-override/{job_id}")

        await self.client.send(url, {
            "type": "quality_blocked",
            "job_id": job_id,
            "openclaw_msg_id": job.get("openclaw_msg_id"),
            "agent_phone": job.get("agent_phone"),
            "score": score,
            "top_issues": top_issues[:3],
            "message": (
                f"Video scored {score:.1f}/10 — below quality threshold. "
                "Choose: retry (re-generate), accept (deliver as-is), or cancel."
            ),
            "actions": {
                "retry_url": f"{override_url}?action=retry",
                "accept_url": f"{override_url}?action=mark_delivered",
                "cancel_url": f"{override_url}?action=cancel",
            },
        })

    async def notify_stall_warning(
        self,
        job_id: str,
        idle_seconds: float,
        current_step: str,
        job: dict,
    ) -> None:
        """Warn the user that a job appears stalled."""
        url = job.get("callback_url") or self._build_url("/events")
        if not url:
            return

        override_url = self._build_url(f"/webhook/manual-override/{job_id}")
        minutes = int(idle_seconds / 60)

        await self.client.send(url, {
            "type": "stall_warning",
            "job_id": job_id,
            "openclaw_msg_id": job.get("openclaw_msg_id"),
            "agent_phone": job.get("agent_phone"),
            "idle_minutes": minutes,
            "current_step": current_step,
            "message": (
                f"Your video has been processing for {minutes}+ minutes "
                f"(stuck at: {current_step}). I'm still working on it — "
                "if it takes much longer, you can retry or cancel."
            ),
            "actions": {
                "retry_url": f"{override_url}?action=retry",
                "cancel_url": f"{override_url}?action=cancel",
            },
        })

    async def notify_photo_suggestion(
        self,
        job_id: str,
        analysis: dict,
        job: dict,
    ) -> None:
        """Suggest the agent add more/better photos (non-blocking advisory).

        Triggered when avg quality < 6 or missing key shots detected.
        Pipeline continues regardless — this is a nudge, not a gate.
        """
        url = job.get("callback_url") or self._build_url("/events")
        if not url:
            return

        summary = analysis.get("property_summary", {})
        photos = analysis.get("photos", [])

        # Build concrete suggestions
        suggestions = []
        missing = summary.get("missing_shots", [])
        if missing:
            suggestions.append(f"Could use: {', '.join(missing[:4])}")

        low_quality = [
            p for p in photos
            if p.get("quality_score", 10) < 5 and p.get("quality_issues")
        ]
        for p in low_quality[:2]:
            room = p.get("room_type", "photo").replace("_", " ")
            issue = p["quality_issues"][0]
            suggestions.append(f"{room.title()}: {issue}")

        if not suggestions:
            return  # nothing actionable to suggest

        await self.client.send(url, {
            "type": "photo_suggestion",
            "job_id": job_id,
            "openclaw_msg_id": job.get("openclaw_msg_id"),
            "agent_phone": job.get("agent_phone"),
            "suggestions": suggestions,
            "message": (
                "Quick tip: your video is being made, but adding a few more "
                "photos could make it even better."
            ),
        })

    async def notify_script_preview(
        self,
        job_id: str,
        script: dict,
        scenes: list[dict],
        job: dict,
    ) -> None:
        """Push script preview so the agent can see what the voiceover will say.

        Non-blocking — pipeline continues immediately. Agent can send
        feedback later to trigger a revision.
        """
        url = job.get("callback_url") or self._build_url("/events")
        if not url:
            return

        scene_summary = [
            {
                "sequence": s.get("sequence"),
                "room": Path(s.get("first_frame", "")).stem,
                "narration_words": len((s.get("text_narration") or "").split()),
            }
            for s in scenes
        ]

        await self.client.send(url, {
            "type": "script_preview",
            "job_id": job_id,
            "openclaw_msg_id": job.get("openclaw_msg_id"),
            "agent_phone": job.get("agent_phone"),
            "script": {
                "hook": script.get("hook", ""),
                "walkthrough": script.get("walkthrough", ""),
                "closer": script.get("closer", ""),
                "word_count": script.get("word_count", 0),
                "estimated_duration": script.get("estimated_duration", 0),
                "caption": script.get("caption", ""),
            },
            "scenes": {
                "count": len(scenes),
                "structure": scene_summary,
            },
            "message": (
                "Here's your video script preview. "
                "Reply with changes, or I'll keep going!"
            ),
        })

    async def notify_daily_insight(
        self,
        agent_phone: str,
        insight: dict,
        image_paths: dict[str, str],
        agent: dict,
    ) -> None:
        """
        Push daily Content Pack to OpenClaw for delivery to agent.

        Args:
            agent_phone: Agent's WhatsApp number
            insight: Content Pack dict (briefing, social_post, forward_buyer, forward_seller, image_data)
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

        normalized = _normalize_daily_insight_payload(insight)

        await self.client.send(url, {
            "type": "daily_insight",
            "agent_phone": agent_phone,
            "insight": {
                "headline": normalized["headline"],
                "key_numbers": normalized["key_numbers"],
                "talking_points_buyers": normalized["talking_points_buyers"],
                "talking_points_sellers": normalized["talking_points_sellers"],
                "caption": normalized["caption"],
                "hashtags": normalized["hashtags"],
                "topic_type": normalized["topic_type"],
            },
            "forward_buyer": normalized["forward_buyer"],
            "forward_seller": normalized["forward_seller"],
            "image_urls": image_urls,
            "agent_name": agent.get("name", ""),
        })

    async def notify_voice_clone_offer(
        self,
        job_id: str,
        job: dict,
    ) -> None:
        """Suggest voice cloning to agent after their first successful video."""
        url = job.get("callback_url") or self._build_url("/events")
        if not url:
            return

        await self.client.send(url, {
            "type": "voice_clone_offer",
            "job_id": job_id,
            "openclaw_msg_id": job.get("openclaw_msg_id"),
            "agent_phone": job.get("agent_phone"),
            "message": (
                "Your video is ready! Want future videos to sound like YOU? "
                "Send a short video of yourself talking (30+ seconds) "
                "and I'll clone your voice for all future videos."
            ),
        })

    async def notify_voice_clone_result(
        self,
        agent_phone: str,
        result: dict,
    ) -> None:
        """Push voice clone result (preview audio) to the agent."""
        url = self._build_url("/events")
        if not url:
            return

        preview_url = _make_public_url(result.get("preview_audio_path", ""))

        await self.client.send(url, {
            "type": "voice_clone_result",
            "agent_phone": agent_phone,
            "status": result.get("status"),
            "voice_id": result.get("voice_id"),
            "preview_audio_url": preview_url,
            "message": result.get("message", ""),
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
