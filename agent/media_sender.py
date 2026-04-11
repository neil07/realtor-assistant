#!/usr/bin/env python3
"""
Media Sender — Unified media attachment layer for OpenClaw.

Provides two mechanisms for sending media back to WhatsApp users:

1. **MEDIA: directive** (primary) — Append ``MEDIA:/path/to/file`` lines to the
   agent reply text.  OpenClaw extracts these and sends each file as a WhatsApp
   media attachment automatically.

2. **GCS upload** (fallback) — If the MEDIA: directive is unavailable or fails,
   upload the file to ``gs://reel-agent-videos/`` and return a public URL that
   can be included inline in the reply text.
"""

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Extensions OpenClaw accepts as media attachments.
ALLOWED_EXTENSIONS: set[str] = {
    ".mp3", ".mp4", ".ogg", ".wav",
    ".jpg", ".jpeg", ".png", ".webp",
}

GCS_BUCKET = "gs://reel-agent-videos"
GCS_PUBLIC_BASE = "https://storage.googleapis.com/reel-agent-videos"


def format_reply_with_media(text: str, media_paths: list[str]) -> str:
    """Append MEDIA: directives to reply text for each valid media file.

    Only includes files that exist on disk and have an allowed extension.

    Args:
        text: The original reply text.
        media_paths: List of absolute file paths to attach.

    Returns:
        Reply text with ``MEDIA:`` lines appended (one per valid file).
    """
    directives: list[str] = []
    for path in media_paths:
        p = Path(path)
        if not p.is_file():
            logger.warning("Media file does not exist, skipping: %s", path)
            continue
        if p.suffix.lower() not in ALLOWED_EXTENSIONS:
            logger.warning("Media file extension not allowed, skipping: %s", path)
            continue
        directives.append(f"MEDIA:{path}")

    if not directives:
        return text

    return text.rstrip() + "\n\n" + "\n".join(directives)


def upload_to_gcs_fallback(local_path: str) -> str | None:
    """Fallback: upload file to GCS and return public URL.

    Uses ``gsutil cp`` to upload to ``gs://reel-agent-videos/``.

    Args:
        local_path: Absolute path to the local file.

    Returns:
        Public URL on success (``https://storage.googleapis.com/reel-agent-videos/{filename}``),
        or ``None`` on failure.
    """
    if not os.path.isfile(local_path):
        logger.warning("Cannot upload to GCS — file not found: %s", local_path)
        return None

    filename = os.path.basename(local_path)
    dest = f"{GCS_BUCKET}/{filename}"

    try:
        subprocess.run(
            ["gsutil", "cp", local_path, dest],
            check=True,
            capture_output=True,
            timeout=120,
        )
        public_url = f"{GCS_PUBLIC_BASE}/{filename}"
        logger.info("Uploaded to GCS: %s → %s", local_path, public_url)
        return public_url
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.error("GCS upload failed for %s: %s", local_path, exc)
        return None
