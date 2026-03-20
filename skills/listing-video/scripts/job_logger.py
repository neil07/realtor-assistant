#!/usr/bin/env python3
"""
Listing Video Agent — Job Logger
Provides structured logging for every video generation run.

Usage in other scripts:
    from job_logger import get_logger, init_job_log

    # At pipeline start (once per job):
    logger = init_job_log("/path/to/output/job_dir")

    # In any script:
    logger = get_logger()
    logger.info("Starting photo analysis...")
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_logger = None   # type: logging.Logger | None
_job_dir = None  # type: str | None
_job_start = None  # type: float | None


def init_job_log(job_dir: str, level: int = logging.DEBUG) -> logging.Logger:
    """
    Initialize logging for a video generation job.

    Creates `run.log` (human-readable) and `run.jsonl` (machine-readable)
    inside the job output directory.
    """
    global _logger, _job_dir, _job_start

    _job_dir = job_dir
    _job_start = time.time()
    os.makedirs(job_dir, exist_ok=True)

    logger = logging.getLogger("listing_video")
    logger.setLevel(level)
    logger.handlers.clear()

    # Human-readable log file
    log_path = os.path.join(job_dir, "run.log")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(file_handler)

    # Stderr for real-time visibility (INFO+)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.INFO)
    stderr_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(stderr_handler)

    _logger = logger

    logger.info("=" * 60)
    logger.info("Job started: %s", datetime.now(timezone.utc).isoformat())
    logger.info("Output dir: %s", job_dir)
    logger.info("=" * 60)

    return logger


def get_logger() -> logging.Logger:
    """Get the current job logger. Falls back to a basic stderr logger."""
    global _logger
    if _logger is None:
        _logger = logging.getLogger("listing_video")
        if not _logger.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
            _logger.addHandler(handler)
            _logger.setLevel(logging.DEBUG)
    return _logger


def log_step_start(step_name: str, details: dict = None):
    """Log the beginning of a pipeline step."""
    logger = get_logger()
    logger.info("--- [START] %s ---", step_name)
    if details:
        for k, v in details.items():
            logger.info("  %s: %s", k, v)
    _write_event("step_start", step_name, details)


def log_step_end(step_name: str, result: dict = None):
    """Log the completion of a pipeline step."""
    logger = get_logger()
    status = (result or {}).get("status", "unknown")
    logger.info("--- [END] %s → %s ---", step_name, status)
    if result:
        # Log key fields without dumping entire result
        for k in ("video_path", "audio_path", "engine", "message", "error",
                   "characters", "word_count", "estimated_duration",
                   "cost_usd", "estimated_cost_usd", "task_id"):
            if k in result:
                logger.info("  %s: %s", k, result[k])
    _write_event("step_end", step_name, result)


def log_clip_result(index: int, total: int, result: dict):
    """Log individual clip generation result."""
    logger = get_logger()
    status = result.get("status", "unknown")
    engine = result.get("engine", "?")
    path = result.get("video_path", "?")
    msg = result.get("message", "")

    if status == "success":
        logger.info("  Clip %d/%d ✓  engine=%s  path=%s", index, total, engine, path)
    else:
        logger.warning("  Clip %d/%d ✗  engine=%s  error=%s", index, total, engine, msg)

    _write_event("clip_result", f"clip_{index}", result)


def log_duration_check(video_dur: float, audio_dur: float, action: str):
    """Log the video-vs-audio duration comparison."""
    logger = get_logger()
    logger.info(
        "Duration check: video=%.1fs  audio=%.1fs  gap=%.1fs  action=%s",
        video_dur, audio_dur, audio_dur - video_dur, action,
    )
    _write_event("duration_check", "assembly", {
        "video_duration": video_dur,
        "audio_duration": audio_dur,
        "action": action,
    })


def log_job_summary(result: dict):
    """Log final job summary with timing."""
    logger = get_logger()
    elapsed = time.time() - (_job_start or time.time())

    logger.info("=" * 60)
    logger.info("Job finished: %s", result.get("status", "unknown"))
    logger.info("Total time: %.1fs", elapsed)
    if result.get("vertical"):
        logger.info("Vertical:   %s", result["vertical"])
    if result.get("horizontal"):
        logger.info("Horizontal: %s", result["horizontal"])
    if result.get("status") == "error":
        logger.error("Error: %s", result.get("message", "unknown"))
    logger.info("=" * 60)

    _write_event("job_summary", "final", {
        **result,
        "elapsed_seconds": round(elapsed, 1),
    })


def _write_event(event_type: str, step: str, data: dict = None):
    """Append a structured JSON event to run.jsonl."""
    if not _job_dir:
        return
    jsonl_path = os.path.join(_job_dir, "run.jsonl")
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "elapsed": round(time.time() - (_job_start or time.time()), 2),
        "event": event_type,
        "step": step,
    }
    if data:
        # Avoid serializing huge fields (base64 images etc.)
        clean = {}
        for k, v in data.items():
            if isinstance(v, str) and len(v) > 500:
                clean[k] = v[:200] + f"... ({len(v)} chars)"
            else:
                clean[k] = v
        event["data"] = clean
    try:
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass
