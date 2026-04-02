#!/usr/bin/env python3
"""
Reel Agent — Error Classifier

Maps raw technical errors to user-friendly messages + suggested actions.
Used by the notifier to send helpful failure notifications instead of stack traces.

Design: P4 (Collaborator) — the system should explain failures, not just report them.
"""

import re

# (regex pattern, user_message, action_hint)
_PATTERNS: list[tuple[str, str, str]] = [
    # Timeout
    (r"(?i)timed?\s*out|timeout",
     "Video generation took longer than expected.",
     "retry"),

    # API key / auth
    (r"(?i)api.?key|unauthorized|403|authentication|ELEVENLABS_API_KEY|OPENAI_API_KEY|IMA_APP",
     "A required service credential is missing or expired.",
     "contact_support"),

    # Rate limit
    (r"(?i)rate.?limit|429|too many requests",
     "We're temporarily at capacity. Your video will be retried shortly.",
     "auto_retry"),

    # No photos / bad input
    (r"(?i)no photos found|photo_paths is empty",
     "No usable photos were found. Please send at least 3 clear listing photos.",
     "resend_photos"),

    # Photo quality
    (r"(?i)no photos suitable|0.*ai_video_worthy",
     "The photos provided aren't suitable for AI video. Try photos with better lighting and resolution.",
     "resend_photos"),

    # Quality gate
    (r"(?i)quality gate.*failed|quality_blocked",
     "The generated video didn't meet our quality standards.",
     "retry_or_feedback"),

    # ffmpeg / assembly
    (r"(?i)ffmpeg|assembly.*fail|no video stream|0 bytes",
     "Video assembly encountered a technical issue.",
     "retry"),

    # IMA Studio / render
    (r"(?i)ima.*error|render.*fail|kling|video generation failed",
     "AI video rendering encountered an issue.",
     "retry"),

    # TTS / voice
    (r"(?i)tts.*fail|voice.*fail|all.*narrations failed",
     "Voice generation had issues — the video may be missing narration.",
     "retry"),

    # Disk / storage
    (r"(?i)no space|disk full|OSError.*28|errno 28",
     "Server storage is full. Our team has been notified.",
     "contact_support"),

    # Network
    (r"(?i)connection.*refused|connect.*error|network|DNS",
     "A network issue prevented us from completing your video.",
     "retry"),

    # State machine
    (r"(?i)invalid state transition",
     "An internal scheduling error occurred.",
     "contact_support"),
]

# Compiled patterns for performance
_COMPILED = [(re.compile(p), msg, action) for p, msg, action in _PATTERNS]


def classify_error(raw_error: str) -> dict:
    """Classify a raw error string into a user-friendly message.

    Returns:
        {
            "user_message": str,     # Safe to show to the end user
            "action": str,           # retry | auto_retry | resend_photos | contact_support | retry_or_feedback
            "technical_detail": str,  # Original error (for logs/admin only)
        }
    """
    if not raw_error:
        return {
            "user_message": "Something went wrong. We're looking into it.",
            "action": "retry",
            "technical_detail": "",
        }

    for pattern, user_msg, action in _COMPILED:
        if pattern.search(raw_error):
            return {
                "user_message": user_msg,
                "action": action,
                "technical_detail": raw_error[:500],
            }

    # Default: generic message
    return {
        "user_message": "Something unexpected happened while generating your video.",
        "action": "retry",
        "technical_detail": raw_error[:500],
    }
