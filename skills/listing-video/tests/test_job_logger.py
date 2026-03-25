#!/usr/bin/env python3
"""Tests for job_logger — structured logging."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import job_logger


def _reset_logger():
    """Reset global state between tests."""
    job_logger._logger = None
    job_logger._job_dir = None
    job_logger._job_start = None


# --- init_job_log ---

def test_init_creates_log_files():
    _reset_logger()
    with tempfile.TemporaryDirectory() as tmp:
        logger = job_logger.init_job_log(tmp)
        assert logger is not None
        assert (Path(tmp) / "run.log").exists()
    _reset_logger()


def test_get_logger_without_init():
    _reset_logger()
    logger = job_logger.get_logger()
    assert logger is not None
    assert logger.name == "listing_video"
    _reset_logger()


# --- _write_event ---

def test_write_event_appends_jsonl():
    _reset_logger()
    with tempfile.TemporaryDirectory() as tmp:
        job_logger.init_job_log(tmp)
        job_logger._write_event("test_event", "test_step", {"key": "value"})

        jsonl_path = Path(tmp) / "run.jsonl"
        lines = jsonl_path.read_text().strip().split("\n")
        # init_job_log doesn't write events, so we should have 1 line
        event = json.loads(lines[-1])
        assert event["event"] == "test_event"
        assert event["step"] == "test_step"
        assert event["data"]["key"] == "value"
    _reset_logger()


def test_write_event_truncates_long_strings():
    _reset_logger()
    with tempfile.TemporaryDirectory() as tmp:
        job_logger.init_job_log(tmp)
        long_val = "x" * 1000
        job_logger._write_event("test", "step", {"big": long_val})

        jsonl_path = Path(tmp) / "run.jsonl"
        event = json.loads(jsonl_path.read_text().strip().split("\n")[-1])
        assert len(event["data"]["big"]) < 500
        assert "1000 chars" in event["data"]["big"]
    _reset_logger()


def test_write_event_noop_without_job_dir():
    _reset_logger()
    # Should not raise
    job_logger._write_event("test", "step", {"key": "val"})
    _reset_logger()


# --- log_step_start / log_step_end ---

def test_log_step_writes_events():
    _reset_logger()
    with tempfile.TemporaryDirectory() as tmp:
        job_logger.init_job_log(tmp)
        job_logger.log_step_start("photo_analysis", {"count": 5})
        job_logger.log_step_end("photo_analysis", {"status": "success"})

        jsonl_path = Path(tmp) / "run.jsonl"
        lines = jsonl_path.read_text().strip().split("\n")
        events = [json.loads(l) for l in lines]
        types = [e["event"] for e in events]
        assert "step_start" in types
        assert "step_end" in types
    _reset_logger()


# --- log_job_summary ---

def test_log_job_summary():
    _reset_logger()
    with tempfile.TemporaryDirectory() as tmp:
        job_logger.init_job_log(tmp)
        job_logger.log_job_summary({"status": "success", "vertical": "/out/v.mp4"})

        jsonl_path = Path(tmp) / "run.jsonl"
        last = json.loads(jsonl_path.read_text().strip().split("\n")[-1])
        assert last["event"] == "job_summary"
        assert last["data"]["status"] == "success"
        assert "elapsed_seconds" in last["data"]
    _reset_logger()
