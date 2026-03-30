#!/usr/bin/env python3
"""
Listing Video Agent — Job Logger

Per-job structured logging. Each job gets its own JobLogger instance,
which is safe for concurrent jobs running in the same process.

Usage (new per-job style, used by dispatcher):
    logger = JobLogger(job_dir="/path/to/output", job_id="20240101_abc123")
    logger.log_step_start("analyze_photos")

Usage (legacy module-level functions, used by pipeline.py CLI):
    from job_logger import init_job_log, get_logger, log_step_start

Both styles write to:
    {job_dir}/run.log    — human-readable
    {job_dir}/run.jsonl  — machine-readable JSONL events
"""

import json
import logging
import os
import sys
import time
from datetime import UTC, datetime


class JobLogger:
    """
    Per-job logger. Create one instance per job_id.
    Thread-safe: each instance has independent state.
    """

    def __init__(self, job_dir: str, job_id: str = "standalone", level: int = logging.DEBUG):
        self.job_dir = job_dir
        self.job_id = job_id
        self._start = time.time()
        os.makedirs(job_dir, exist_ok=True)

        # Use a unique logger name per job to avoid handler bleed
        self._logger = logging.getLogger(f"listing_video.{job_id}")
        self._logger.setLevel(level)
        self._logger.handlers.clear()
        self._logger.propagate = False

        # Human-readable log file
        log_path = os.path.join(job_dir, "run.log")
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        ))
        self._logger.addHandler(fh)

        # Stderr for real-time visibility (INFO+)
        sh = logging.StreamHandler(sys.stderr)
        sh.setLevel(logging.INFO)
        sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        self._logger.addHandler(sh)

        self._logger.info("=" * 60)
        self._logger.info("Job started: %s  id=%s", datetime.now(UTC).isoformat(), job_id)
        self._logger.info("Output dir: %s", job_dir)
        self._logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Structured event helpers
    # ------------------------------------------------------------------

    def log_step_start(self, step_name: str, details: dict = None):
        self._logger.info("--- [START] %s ---", step_name)
        if details:
            for k, v in details.items():
                self._logger.info("  %s: %s", k, v)
        self._write_event("step_start", step_name, details)

    def log_step_end(self, step_name: str, result: dict = None):
        status = (result or {}).get("status", "unknown")
        self._logger.info("--- [END] %s → %s ---", step_name, status)
        if result:
            for k in ("video_path", "audio_path", "engine", "message", "error",
                      "characters", "word_count", "estimated_duration",
                      "cost_usd", "estimated_cost_usd", "task_id"):
                if k in result:
                    self._logger.info("  %s: %s", k, result[k])
        self._write_event("step_end", step_name, result)

    def log_clip_result(self, index: int, total: int, result: dict):
        status = result.get("status", "unknown")
        engine = result.get("engine", "?")
        path = result.get("video_path", "?")
        msg = result.get("message", "")
        if status == "success":
            self._logger.info("  Clip %d/%d OK  engine=%s  path=%s", index, total, engine, path)
        else:
            self._logger.warning("  Clip %d/%d FAIL  engine=%s  error=%s", index, total, engine, msg)
        self._write_event("clip_result", f"clip_{index}", result)

    def log_duration_check(self, video_dur: float, audio_dur: float, action: str):
        self._logger.info(
            "Duration check: video=%.1fs  audio=%.1fs  gap=%.1fs  action=%s",
            video_dur, audio_dur, audio_dur - video_dur, action,
        )
        self._write_event("duration_check", "assembly", {
            "video_duration": video_dur,
            "audio_duration": audio_dur,
            "action": action,
        })

    def log_job_summary(self, result: dict):
        elapsed = time.time() - self._start
        self._logger.info("=" * 60)
        self._logger.info("Job finished: %s", result.get("status", "unknown"))
        self._logger.info("Total time: %.1fs", elapsed)
        if result.get("vertical"):
            self._logger.info("Vertical:   %s", result["vertical"])
        if result.get("horizontal"):
            self._logger.info("Horizontal: %s", result["horizontal"])
        if result.get("status") == "error":
            self._logger.error("Error: %s", result.get("message", "unknown"))
        self._logger.info("=" * 60)
        self._write_event("job_summary", "final", {
            **result,
            "elapsed_seconds": round(elapsed, 1),
        })

    def info(self, msg: str, *args):
        self._logger.info(msg, *args)

    def warning(self, msg: str, *args):
        self._logger.warning(msg, *args)

    def error(self, msg: str, *args):
        self._logger.error(msg, *args)

    def debug(self, msg: str, *args):
        self._logger.debug(msg, *args)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write_event(self, event_type: str, step: str, data: dict = None):
        """Append a structured JSON event to run.jsonl."""
        jsonl_path = os.path.join(self.job_dir, "run.jsonl")
        event = {
            "ts": datetime.now(UTC).isoformat(),
            "elapsed": round(time.time() - self._start, 2),
            "event": event_type,
            "step": step,
            "job_id": self.job_id,
        }
        if data:
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


# ---------------------------------------------------------------------------
# Legacy module-level API — keeps pipeline.py (CLI) working without changes
# ---------------------------------------------------------------------------

_instance: JobLogger | None = None


def init_job_log(job_dir: str, level: int = logging.DEBUG) -> logging.Logger:
    """
    Initialize module-level logger (legacy, used by pipeline.py).
    Returns the underlying logging.Logger for drop-in compatibility.
    """
    global _instance
    _instance = JobLogger(job_dir=job_dir, job_id="cli", level=level)
    return _instance._logger


def get_logger() -> logging.Logger:
    """Return the module-level logger, creating a fallback if not initialized."""
    global _instance
    if _instance is None:
        _instance = JobLogger(job_dir="/tmp/reel_agent_fallback", job_id="fallback")
    return _instance._logger


def log_step_start(step_name: str, details: dict = None):
    global _instance
    if _instance:
        _instance.log_step_start(step_name, details)


def log_step_end(step_name: str, result: dict = None):
    global _instance
    if _instance:
        _instance.log_step_end(step_name, result)


def log_clip_result(index: int, total: int, result: dict):
    global _instance
    if _instance:
        _instance.log_clip_result(index, total, result)


def log_duration_check(video_dur: float, audio_dur: float, action: str):
    global _instance
    if _instance:
        _instance.log_duration_check(video_dur, audio_dur, action)


def log_job_summary(result: dict):
    global _instance
    if _instance:
        _instance.log_job_summary(result)
