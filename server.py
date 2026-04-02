#!/usr/bin/env python3
"""
Reel Agent — Server

FastAPI service exposing:
  - Test UI:          GET  /
  - Async generate:   POST /api/generate      → {job_id, status}
  - Job status:       GET  /api/status/{id}   → {job_id, status, step, video_url?}
  - OpenClaw webhook: POST /webhook/in        → {job_id, status}
  - Manual override:  POST /webhook/manual-override/{id}
  - Static output:    /output/*

Usage:
    python server.py
    Open http://localhost:8000
"""

import asyncio
import hmac
import json
import logging
import os
import shutil
import sys
import time as _time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

# Add scripts to path so skill modules can be imported by name (e.g. `import analyze_photos`).
# This is the SINGLE authoritative insert; function-level inserts elsewhere are unnecessary.
# Scripts also run standalone via `python script.py`, so a full package migration is deferred.
SCRIPTS_DIR = Path(__file__).parent / "skills" / "listing-video" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

OUTPUT_BASE = Path(__file__).parent / "skills" / "listing-video" / "output"
OUTPUT_BASE.mkdir(parents=True, exist_ok=True)
DEFAULT_BRIDGE_STATE_PATH = Path(
    os.getenv(
        "OPENCLAW_BRIDGE_STATE_PATH",
        "~/.openclaw/workspace-realtor-social/.openclaw/reel-agent-bridge-state.json",
    )
).expanduser()

# ---------------------------------------------------------------------------
# Structured audit logger — JSON events on critical paths (auth, requests)
# ---------------------------------------------------------------------------

_audit_logger = logging.getLogger("reel_agent.audit")


def _structured_log(event: str, **data) -> None:
    """Emit a structured JSON log line to the audit logger.

    Consumed by log aggregators (CloudWatch, Datadog, etc.) in production.
    """
    entry = {"event": event, "ts": _time.time(), **data}
    _audit_logger.info(json.dumps(entry, ensure_ascii=False, default=str))


# Lazy imports — populated in lifespan
_job_mgr = None
_dispatcher = None
_scheduler = None


# ---------------------------------------------------------------------------
# Lifespan: init DB + dispatcher, resume pending jobs on startup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _job_mgr, _dispatcher, _scheduler

    from agent.callback_client import CallbackClient
    from orchestrator.daily_scheduler import DailyScheduler
    from orchestrator.dispatcher import Dispatcher
    from orchestrator.job_manager import JobManager
    from orchestrator.progress_notifier import ProgressNotifier

    _job_mgr = JobManager()
    await _job_mgr.init_db()

    callback_client = CallbackClient()
    notifier = ProgressNotifier(callback_client)
    _dispatcher = Dispatcher(_job_mgr, notifier)

    # Start daily content scheduler as background task
    _scheduler = DailyScheduler(notifier)
    asyncio.create_task(_scheduler.run_forever())

    # Start callback retry loop (flushes queued callbacks every 30s)
    asyncio.create_task(_callback_retry_loop(callback_client))

    # Start watchdog: alert if a job stalls for too long
    asyncio.create_task(_job_watchdog_loop(_job_mgr, notifier))

    # Start disk cleanup loop (every 6h: FAILED 7d, DELIVERED 30d)
    asyncio.create_task(_cleanup_loop())

    # Resume any jobs that were in-flight before a restart
    pending = await _job_mgr.list_pending_jobs()
    if pending:
        print(f"  Resuming {len(pending)} pending job(s)...")
        for job in pending:
            await _dispatcher.submit(job["job_id"])

    if not os.getenv("REEL_AGENT_TOKEN", "").strip():
        _auth_logger.warning(
            "REEL_AGENT_TOKEN not set — all auth-protected endpoints will reject requests"
        )

    print("Reel Agent server ready.")
    yield
    # Graceful shutdown: close persistent DB connection
    if _job_mgr:
        await _job_mgr.close()


_retry_logger = logging.getLogger(__name__)


# Escalating watchdog thresholds (seconds)
_WARN_TIMEOUT = float(os.getenv("JOB_STALL_TIMEOUT", "600"))       # 10 min: first warning
_CRITICAL_TIMEOUT = float(os.getenv("JOB_CRITICAL_TIMEOUT", "1200"))  # 20 min: urgent warning
_CANCEL_TIMEOUT = float(os.getenv("JOB_CANCEL_TIMEOUT", "1800"))   # 30 min: auto-cancel


async def _job_watchdog_loop(
    job_mgr: "JobManager",
    notifier: "ProgressNotifier",
) -> None:
    """Background task: escalating stall detection every 60s.

    10min → warning, 20min → critical, 30min → auto-cancel.
    """
    # Track escalation level per job: 0=none, 1=warned, 2=critical
    escalation: dict[str, int] = {}

    while True:
        try:
            await asyncio.sleep(60)
            now = _time.time()
            pending = await job_mgr.list_pending_jobs()

            for job in pending:
                jid = job["job_id"]
                updated = job.get("step_started_at") or job.get("updated_at", now)
                idle = now - updated
                level = escalation.get(jid, 0)

                if idle >= _CANCEL_TIMEOUT and level < 3:
                    escalation[jid] = 3
                    _retry_logger.warning(
                        "Watchdog: auto-cancelling job %s after %.0fs at step '%s'",
                        jid, idle, job.get("current_step"),
                    )
                    await job_mgr.mark_failed(
                        jid,
                        f"Auto-cancelled: stalled {int(idle/60)}+ min at '{job.get('current_step')}'",
                    )
                    await notifier.notify_failed(
                        jid,
                        f"Your video was automatically cancelled after {int(idle/60)} minutes "
                        "without progress. Please try again.",
                        job,
                    )

                elif idle >= _CRITICAL_TIMEOUT and level < 2:
                    escalation[jid] = 2
                    _retry_logger.warning(
                        "Watchdog CRITICAL: job %s stalled %.0fs at step '%s'",
                        jid, idle, job.get("current_step"),
                    )
                    await notifier.notify_stall_warning(
                        jid,
                        idle_seconds=idle,
                        current_step=job.get("current_step", "unknown"),
                        job=job,
                    )

                elif idle >= _WARN_TIMEOUT and level < 1:
                    escalation[jid] = 1
                    _retry_logger.warning(
                        "Watchdog: job %s stalled %.0fs at step '%s'",
                        jid, idle, job.get("current_step"),
                    )
                    await notifier.notify_stall_warning(
                        jid,
                        idle_seconds=idle,
                        current_step=job.get("current_step", "unknown"),
                        job=job,
                    )

            # Clean up escalation map: remove jobs that are no longer pending
            pending_ids = {j["job_id"] for j in pending}
            escalation = {k: v for k, v in escalation.items() if k in pending_ids}

        except asyncio.CancelledError:
            break
        except Exception as exc:
            _retry_logger.warning("Watchdog loop error: %s", exc)


async def _callback_retry_loop(client: "CallbackClient") -> None:
    """Background task: flush failed callbacks from the retry queue every 30s."""
    while True:
        try:
            await asyncio.sleep(30)
            await client.flush_retry_queue()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            _retry_logger.warning("Callback retry loop error: %s", exc)


async def _cleanup_loop() -> None:
    """Background task: clean up old job output directories every 6 hours."""
    from orchestrator.cleanup import cleanup_old_jobs

    while True:
        try:
            await asyncio.sleep(6 * 3600)
            await cleanup_old_jobs()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            _retry_logger.warning("Cleanup loop error: %s", exc)


# ---------------------------------------------------------------------------
# Rate limiting (slowapi)
# ---------------------------------------------------------------------------
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Reel Agent", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.mount("/output", StaticFiles(directory=str(OUTPUT_BASE)), name="output")

# Operator Console
from console.router import router as console_router
from console.memory_schema import get_recommended_experience

app.include_router(console_router)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_job_mgr():
    if _job_mgr is None:
        raise HTTPException(503, "Server not ready")
    return _job_mgr


def _get_dispatcher():
    if _dispatcher is None:
        raise HTTPException(503, "Server not ready")
    return _dispatcher


_auth_logger = logging.getLogger("reel_agent.auth")


def _require_backend_auth(authorization: str | None = Header(default=None)) -> None:
    """Protect API routes with mandatory Bearer token auth.

    When REEL_AGENT_TOKEN is not set the server still starts (for dev convenience)
    but all auth-protected requests are rejected with 403.
    """
    expected = os.getenv("REEL_AGENT_TOKEN", "").strip()
    if not expected:
        _structured_log("auth", result="rejected", reason="token_not_configured")
        raise HTTPException(
            403,
            "REEL_AGENT_TOKEN not configured — all authenticated requests are rejected",
        )

    if not authorization or not authorization.startswith("Bearer "):
        _structured_log("auth", result="rejected", reason="missing_token")
        raise HTTPException(401, "Missing bearer token")

    token = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, expected):
        _structured_log("auth", result="rejected", reason="invalid_token")
        raise HTTPException(401, "Invalid bearer token")


@app.get("/health")
async def health() -> dict[str, str | bool]:
    return {"ok": True, "status": "live"}


def _video_url(video_path: str) -> str | None:
    if not video_path or not os.path.isfile(video_path):
        return None
    try:
        rel = os.path.relpath(video_path, str(OUTPUT_BASE))
        return f"/output/{rel}"
    except ValueError:
        return None


def _load_json_file(path: Path) -> dict | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_diagnostics_summary(output_dir: str | None) -> dict | None:
    if not output_dir:
        return None

    output_path = Path(output_dir)
    diag_path = output_path / "diagnostics.json"
    report_path = output_path / "diagnostics_report.md"
    data = _load_json_file(diag_path)
    if not data:
        return None

    summary = data.get("summary", {})
    final = data.get("final", {})
    return {
        "available": True,
        "path": str(diag_path),
        "report_path": str(report_path) if report_path.exists() else None,
        "updated_at": data.get("updated_at"),
        "scene_count": summary.get("scene_count"),
        "render_fallback_scenes": summary.get("render_fallback_scenes", []),
        "render_failed_scenes": summary.get("render_failed_scenes", []),
        "tts_fallback_scenes": summary.get("tts_fallback_scenes", []),
        "tts_failed_scenes": summary.get("tts_failed_scenes", []),
        "assembly_adjusted_scenes": summary.get("assembly_adjusted_scenes", []),
        "final_has_audio": summary.get("final_has_audio"),
        "suspected_causes": summary.get("suspected_causes", []),
        "final": {
            "status": final.get("status"),
            "video_path": final.get("video_path"),
            "aspect_ratio": final.get("aspect_ratio"),
            "total_duration": final.get("total_duration"),
            "has_audio": final.get("has_audio"),
            "narrations_succeeded": final.get("narrations_succeeded"),
            "audio_warning": final.get("audio_warning"),
        },
    }


def _load_review_summary(output_dir: str | None) -> dict | None:
    if not output_dir:
        return None

    output_path = Path(output_dir)
    for filename in ("auto_review_v2.json", "auto_review_v1.json", "auto_review.json"):
        review_path = output_path / filename
        data = _load_json_file(review_path)
        if not data:
            continue
        return {
            "available": True,
            "path": str(review_path),
            "status": data.get("status"),
            "overall_score": data.get("overall_score"),
            "deliverable": data.get("deliverable"),
            "top_issues": data.get("top_issues", []),
            "narrative": data.get("narrative"),
        }

    return None


def _coerce_current_insight(payload: Any, bridge_agent_state: dict | None) -> dict | None:
    """Resolve the current daily insight object from request payload or bridge state."""
    if payload.current_insight:
        return payload.current_insight
    if bridge_agent_state and isinstance(bridge_agent_state.get("lastDailyInsight"), dict):
        return bridge_agent_state["lastDailyInsight"]
    return None


# ---------------------------------------------------------------------------
# Test UI
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def upload_page():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reel Agent — Test</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0a0a; color: #e0e0e0;
            min-height: 100vh; padding: 40px 20px;
        }
        .container { max-width: 640px; margin: 0 auto; }
        h1 { font-size: 28px; margin-bottom: 8px; }
        h1 span { font-size: 32px; }
        .subtitle { color: #888; margin-bottom: 32px; }
        .upload-zone {
            border: 2px dashed #333; border-radius: 12px;
            padding: 48px 24px; text-align: center;
            cursor: pointer; transition: all 0.2s; margin-bottom: 24px;
        }
        .upload-zone:hover, .upload-zone.dragover { border-color: #4A90D9; background: #111; }
        .upload-zone input { display: none; }
        .upload-icon { font-size: 48px; margin-bottom: 12px; }
        .upload-text { color: #888; }
        .file-count { color: #4A90D9; font-weight: 600; margin-top: 8px; }
        .form-group { margin-bottom: 16px; }
        label { display: block; color: #888; font-size: 13px; margin-bottom: 4px; }
        input[type="text"], select {
            width: 100%; padding: 10px 12px;
            background: #1a1a1a; border: 1px solid #333;
            border-radius: 8px; color: #e0e0e0; font-size: 14px;
        }
        .row { display: flex; gap: 12px; }
        .row .form-group { flex: 1; }
        button {
            width: 100%; padding: 14px;
            background: #4A90D9; color: white; border: none;
            border-radius: 8px; font-size: 16px; font-weight: 600;
            cursor: pointer; transition: background 0.2s; margin-top: 8px;
        }
        button:hover { background: #3a7bc8; }
        button:disabled { background: #333; cursor: not-allowed; }
        .progress {
            margin-top: 24px; padding: 16px;
            background: #111; border-radius: 8px;
            display: none; font-family: 'SF Mono', monospace; font-size: 13px;
            line-height: 1.8;
        }
        .step { color: #888; }
        .step.done { color: #4caf50; }
        .step.active { color: #4A90D9; }
        .step.error { color: #f44336; }
        .result { margin-top: 24px; padding: 20px; background: #111; border-radius: 8px; display: none; }
        .result video { width: 100%; border-radius: 8px; margin-bottom: 12px; }
        .caption { padding: 12px; background: #1a1a1a; border-radius: 8px; font-size: 14px; white-space: pre-wrap; }
        .thumbs { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 12px; }
        .thumbs img { width: 64px; height: 64px; object-fit: cover; border-radius: 6px; }
        .rand-btn { all: unset; color: #4A90D9; cursor: pointer; font-size: 12px; margin-left: 6px; }
        .rand-btn:hover { text-decoration: underline; }
        #jobId { color: #888; font-size: 12px; margin-top: 8px; font-family: monospace; }
    </style>
</head>
<body>
<div class="container">
    <h1><span>🎬</span> Reel Agent</h1>
    <p class="subtitle">Upload listing photos, get a video.</p>

    <form id="uploadForm" enctype="multipart/form-data">
        <div class="upload-zone" id="dropZone">
            <div class="upload-icon">📸</div>
            <div class="upload-text">Drop listing photos here or click to browse</div>
            <div class="file-count" id="fileCount"></div>
            <div class="thumbs" id="thumbs"></div>
            <input type="file" id="photos" name="photos" multiple accept="image/*">
        </div>
        <div class="row">
            <div class="form-group" style="flex:2">
                <label>Address <button type="button" onclick="randomize()" class="rand-btn">🎲 Random</button></label>
                <input type="text" name="address" id="address">
            </div>
            <div class="form-group" style="flex:1">
                <label>Price</label>
                <input type="text" name="price" id="price">
            </div>
        </div>
        <div class="row">
            <div class="form-group">
                <label>Agent Name</label>
                <input type="text" name="agent_name" value="Neo" placeholder="Your name">
            </div>
            <div class="form-group">
                <label>Agent Phone</label>
                <input type="text" name="agent_phone" value="+60175029017" placeholder="+1234567890">
            </div>
        </div>
        <div class="row">
            <div class="form-group">
                <label>Video Style</label>
                <select name="style">
                    <option value="professional">Professional</option>
                    <option value="elegant">Elegant</option>
                    <option value="energetic">Energetic</option>
                </select>
            </div>
            <div class="form-group">
                <label>Music</label>
                <select name="music">
                    <option value="modern">Modern Upbeat</option>
                    <option value="piano">Piano Ambient</option>
                    <option value="acoustic">Acoustic Warm</option>
                </select>
            </div>
        </div>
        <div class="row">
            <div class="form-group">
                <label>Aspect Ratio</label>
                <select name="aspect_ratio">
                    <option value="9:16">9:16 Vertical</option>
                    <option value="16:9">16:9 Horizontal</option>
                </select>
            </div>
            <div class="form-group">
                <label>Language</label>
                <select name="language">
                    <option value="en">English</option>
                    <option value="zh">中文</option>
                    <option value="ms">Bahasa Melayu</option>
                </select>
            </div>
        </div>
        <button type="submit" id="submitBtn">Generate Video 🎬</button>
    </form>
    <div id="jobId"></div>
    <div class="progress" id="progress"></div>
    <div class="result" id="result"></div>
</div>

<script>
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('photos');
const fileCount = document.getElementById('fileCount');
const thumbs = document.getElementById('thumbs');
const form = document.getElementById('uploadForm');
const progressEl = document.getElementById('progress');
const resultEl = document.getElementById('result');
const submitBtn = document.getElementById('submitBtn');
const jobIdEl = document.getElementById('jobId');

let selectedFiles = [];
let pollTimer = null;

const addresses = [
    {addr:'4821 Timber Creek Dr, Frisco, TX 75034', price:'$875,000'},
    {addr:'1203 Magnolia Blvd, Austin, TX 78704', price:'$1,250,000'},
    {addr:'567 Palm Harbor Way, Miami, FL 33139', price:'$2,100,000'},
    {addr:'2910 Sunset Ridge Ln, Scottsdale, AZ 85260', price:'$1,680,000'},
    {addr:'88 Oceanview Terrace, La Jolla, CA 92037', price:'$3,450,000'},
    {addr:'1455 Willow Park Ave, Nashville, TN 37215', price:'$925,000'},
    {addr:'302 Lakeshore Dr, Lake Tahoe, NV 89449', price:'$2,800,000'},
    {addr:'7714 Peachtree Rd NE, Atlanta, GA 30305', price:'$1,150,000'},
    {addr:'619 Harbor View Ct, Charleston, SC 29401', price:'$1,375,000'},
    {addr:'2200 Aspen Creek Blvd, Denver, CO 80220', price:'$785,000'},
];
function randomize() {
    const a = addresses[Math.floor(Math.random()*addresses.length)];
    document.getElementById('address').value = a.addr;
    document.getElementById('price').value = a.price;
}
randomize();

dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => {
    e.preventDefault(); dropZone.classList.remove('dragover');
    handleFiles(e.dataTransfer.files);
});
fileInput.addEventListener('change', e => handleFiles(e.target.files));

function handleFiles(files) {
    selectedFiles = Array.from(files).filter(f => f.type.startsWith('image/'));
    fileCount.textContent = selectedFiles.length + ' photos selected';
    thumbs.innerHTML = '';
    selectedFiles.forEach(f => {
        const img = document.createElement('img');
        img.src = URL.createObjectURL(f);
        thumbs.appendChild(img);
    });
}

const STEP_LABELS = {
    QUEUED: '⏳ Queued',
    ANALYZING: '🔍 Analyzing photos',
    SCRIPTING: '✍️ Writing script',
    PROMPTING: '🎬 Planning shots',
    PRODUCING: '⚡ Rendering video + voice',
    ASSEMBLING: '🎞️ Assembling final video',
    DELIVERED: '✅ Done!',
    FAILED: '❌ Failed',
};

form.addEventListener('submit', async e => {
    e.preventDefault();
    if (!selectedFiles.length) { alert('Please upload photos first'); return; }
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Submitting...';
    progressEl.style.display = 'block';
    resultEl.style.display = 'none';
    progressEl.innerHTML = '<div class="step active">⏳ Uploading photos...</div>';

    const fd = new FormData();
    selectedFiles.forEach(f => fd.append('photos', f));
    fd.append('address', form.address.value || '[TBD]');
    fd.append('price', form.price.value || '[TBD]');
    fd.append('agent_name', form.agent_name.value || '');
    fd.append('agent_phone', form.agent_phone.value || '');
    fd.append('style', form.style.value);
    fd.append('music', form.music.value);
    fd.append('aspect_ratio', form.aspect_ratio.value);
    fd.append('language', form.language.value);

    try {
        const res = await fetch('/api/generate', { method: 'POST', body: fd });
        const data = await res.json();
        if (data.error) {
            progressEl.innerHTML = '<div class="step error">❌ ' + data.error + '</div>';
            submitBtn.disabled = false;
            submitBtn.textContent = 'Generate Video 🎬';
            return;
        }

        const jobId = data.job_id;
        jobIdEl.textContent = 'Job: ' + jobId;
        submitBtn.textContent = 'Processing...';
        pollStatus(jobId);
    } catch (err) {
        progressEl.innerHTML = '<div class="step error">❌ ' + err.message + '</div>';
        submitBtn.disabled = false;
        submitBtn.textContent = 'Generate Video 🎬';
    }
});

function pollStatus(jobId) {
    pollTimer = setInterval(async () => {
        try {
            const res = await fetch('/api/status/' + jobId);
            const data = await res.json();
            const label = STEP_LABELS[data.status] || data.status;
            progressEl.innerHTML = '<div class="step active">' + label + '</div>';

            if (data.status === 'DELIVERED') {
                clearInterval(pollTimer);
                showResult(data);
                submitBtn.disabled = false;
                submitBtn.textContent = 'Generate Video 🎬';
            } else if (data.status === 'FAILED' || data.status === 'CANCELLED') {
                clearInterval(pollTimer);
                progressEl.innerHTML = '<div class="step error">❌ ' + (data.last_error || 'Failed') + '</div>';
                submitBtn.disabled = false;
                submitBtn.textContent = 'Generate Video 🎬';
            }
        } catch (err) { /* ignore poll errors */ }
    }, 3000);
}

function showResult(data) {
    progressEl.innerHTML = '<div class="step done">✅ Done!</div>';
    let html = '';
    if (data.video_url) {
        html += '<video controls><source src="' + data.video_url + '" type="video/mp4"></video>';
    }
    html += '<div class="caption">';
    if (data.caption) html += '<strong>📱 Caption:</strong><br>' + data.caption;
    if (data.review && data.review.available) {
        html += '<br><br><strong>📊 Review:</strong><br>';
        html += 'Score: ' + (data.review.overall_score ?? '?') + '/10';
        if (typeof data.review.deliverable === 'boolean') {
            html += ' | Deliverable: ' + (data.review.deliverable ? 'yes' : 'no');
        }
        if (data.review.top_issues && data.review.top_issues.length) {
            html += '<br>Top issues: ' + data.review.top_issues.join(' | ');
        }
    }
    if (data.diagnostics && data.diagnostics.available) {
        html += '<br><br><strong>🩺 Diagnostics:</strong><br>';
        const causes = data.diagnostics.suspected_causes || [];
        html += 'Render fallback scenes: ' + JSON.stringify(data.diagnostics.render_fallback_scenes || []) + '<br>';
        html += 'TTS fallback scenes: ' + JSON.stringify(data.diagnostics.tts_fallback_scenes || []) + '<br>';
        html += 'Assembly adjusted scenes: ' + JSON.stringify(data.diagnostics.assembly_adjusted_scenes || []) + '<br>';
        html += 'Final audio: ' + data.diagnostics.final_has_audio + '<br>';
        if (causes.length) {
            html += 'Likely causes: ' + causes.join(' | ');
        }
    }
    html += '</div>';
    resultEl.innerHTML = html;
    resultEl.style.display = 'block';
}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# API: Async generate (returns job_id immediately)
# ---------------------------------------------------------------------------


@app.post("/api/generate")
@limiter.limit("5/minute")
async def generate_video(
    request: Request,
    photos: list[UploadFile] = File(...),
    address: str = Form("[TBD]"),
    price: str = Form("[TBD]"),
    agent_name: str = Form(""),
    agent_phone: str = Form(""),
    style: str = Form("professional"),
    music: str = Form("modern"),
    aspect_ratio: str = Form("9:16"),
    language: str = Form("en"),
    _auth: None = Depends(_require_backend_auth),
):
    """Upload photos and queue a video generation job. Returns job_id immediately."""
    job_mgr = _get_job_mgr()
    dispatcher = _get_dispatcher()

    # Create job directory and save photos
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    job_dir = OUTPUT_BASE / job_id
    photo_dir = job_dir / "photos"
    photo_dir.mkdir(parents=True, exist_ok=True)

    for photo in photos:
        dest = photo_dir / (photo.filename or f"photo_{uuid.uuid4().hex[:6]}.jpg")
        with open(dest, "wb") as f:
            shutil.copyfileobj(photo.file, f)

    params = {
        "address": address,
        "price": price,
        "agent_name": agent_name,
        "style": style,
        "music": music,
        "aspect_ratio": aspect_ratio,
        "language": language,
    }

    db_job_id = await job_mgr.create_job(
        agent_phone=agent_phone or "test",
        photo_dir=str(photo_dir),
        params=params,
        output_dir=str(job_dir),
    )

    await dispatcher.submit(db_job_id)

    _structured_log(
        "job_created",
        job_id=db_job_id,
        agent_phone=agent_phone or "test",
        photo_count=len(photos),
        style=style,
        aspect_ratio=aspect_ratio,
        language=language,
    )

    return {"job_id": db_job_id, "status": "QUEUED"}


# ---------------------------------------------------------------------------
# API: Job status
# ---------------------------------------------------------------------------


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    """Poll job status with delivery, review, diagnostics, and timing info."""
    job_mgr = _get_job_mgr()
    summary = await job_mgr.get_job_summary(job_id)
    if not summary:
        raise HTTPException(404, "Job not found")

    resp = dict(summary)
    now = _time.time()
    is_terminal = summary.get("status") in ("DELIVERED", "FAILED", "CANCELLED")

    # ── Timing ──────────────────────────────────────────────────────
    created = summary.get("created_at", now)
    completed = summary.get("completed_at")
    resp["elapsed_seconds"] = max(0, round((completed or now) - created, 1))

    step_started = summary.get("step_started_at")
    if step_started and not is_terminal:
        resp["step_elapsed_seconds"] = max(0, round(now - step_started, 1))
    else:
        resp["step_elapsed_seconds"] = None

    resp.pop("step_started_at", None)

    # ── Params summary (non-sensitive subset) ───────────────────────
    resp["params_summary"] = None
    if raw_params := summary.get("params"):
        try:
            p = json.loads(raw_params) if isinstance(raw_params, str) else raw_params
            if isinstance(p, dict):
                resp["params_summary"] = {k: p.get(k) for k in ("style", "aspect_ratio", "language")}
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
    resp.pop("params", None)

    # ── Video URL + enrichments ────────────────────────────────────
    if summary.get("video_path"):
        resp["video_url"] = _video_url(summary["video_path"])
    resp["diagnostics"] = _load_diagnostics_summary(summary.get("output_dir"))
    resp["review"] = _load_review_summary(summary.get("output_dir"))
    return resp


# ---------------------------------------------------------------------------
# Webhook: OpenClaw inbound
# ---------------------------------------------------------------------------


class WebhookPayload(BaseModel):
    agent_phone: str
    photo_paths: list[str]  # paths to photos already saved on disk
    params: dict = {}
    callback_url: str | None = None
    openclaw_msg_id: str | None = None


class FeedbackPayload(BaseModel):
    job_id: str | None = None
    agent_phone: str
    feedback_text: str  # raw text from WhatsApp ("换个更活泼的音乐")
    revision_round: int = 1
    feedback_scope: Literal["video", "insight"] = "video"
    current_insight: dict[str, Any] | None = None
    callback_url: str | None = None
    agent_name: str | None = None


class MessagePayload(BaseModel):
    """Universal text-message entry — works on channels with or without buttons."""

    agent_phone: str
    text: str = ""
    has_media: bool = False
    media_paths: list[str] = []
    callback_url: str | None = None
    openclaw_msg_id: str | None = None


# ---------------------------------------------------------------------------
# Message UX: universal text-command router (button-free channels)
# ---------------------------------------------------------------------------

# Text-command lookup — works as first-class fallback when channel has no buttons
_STYLE_KEYWORDS = {
    "elegant": "elegant",
    "优雅": "elegant",
    "✨": "elegant",
    "professional": "professional",
    "专业": "professional",
    "💼": "professional",
    "energetic": "energetic",
    "活力": "energetic",
    "🔥": "energetic",
}
_CONFIRM_KEYWORDS = {
    "go",
    "ok",
    "yes",
    "done",
    "sure",
    "confirm",
    "确认",
    "好的",
    "开始",
    "好",
    "可以",
}
_SKIP_KEYWORDS = {"skip", "pass", "跳过", "不用", "no"}
_PUBLISH_KEYWORDS = {"publish", "post", "发布", "send", "发"}
_ADJUST_KEYWORDS = {"adjust", "change", "tweak", "调整", "改", "修改"}
_REDO_KEYWORDS = {"redo", "again", "remake", "重做", "重来"}
_STOP_PUSH_KEYWORDS = {
    "stop push",
    "pause push",
    "unsubscribe",
    "no more",
    "停止推送",
    "暂停推送",
    "不要了",
    "取消推送",
}
_START_PUSH_KEYWORDS = {
    "resume push",
    "start push",
    "restart push",
    "恢复推送",
    "继续推",
    "重新订阅",
}
_HELP_KEYWORDS = {"help", "?", "帮助", "怎么用", "what can you do"}
_APP_QUESTION_KEYWORDS = {
    "is this an app",
    "what is this",
    "how do i use this",
    "how does this work",
    "what do you do",
}
_TRUST_QUESTION_KEYWORDS = {
    "secure",
    "security",
    "safe",
    "spam",
    "legit",
    "legitimate",
}
_PRICING_QUESTION_KEYWORDS = {
    "how much",
    "how much per month",
    "per month",
    "price",
    "pricing",
    "cost",
}
_FIRST_STEP_QUESTION_KEYWORDS = {
    "first step",
    "where do i start",
    "what should i do first",
    "tell me the first step",
    "don't know these tools",
    "do not know these tools",
}
_DAILY_INSIGHT_KEYWORDS = {
    "daily insight",
    "insight",
    "market insight",
    "daily update",
    "market update",
    "daily content",
    "market content",
    "content for today",
    "content today",
    "每日资讯",
    "每日洞察",
    "市场洞察",
    "今日资讯",
    "今日洞察",
}
_PROPERTY_CONTENT_KEYWORDS = {
    "listing",
    "open house",
    "just listed",
    "new listing",
    "property",
    "photos",
    "房源",
    "房子",
    "楼盘",
    "开放日",
    "看房",
    "照片",
}
_PROPERTY_HINT_WORDS = {
    "st",
    "street",
    "rd",
    "road",
    "ave",
    "avenue",
    "blvd",
    "drive",
    "dr",
    "lane",
    "ln",
    "court",
    "ct",
    "way",
    "house",
}

_SUPPORTED_DAILY_INSIGHT_REFINEMENTS = {
    "shorter",
    "more professional",
}

# Welcome message + capability framing (first-contact)
_WELCOME_MSG = (
    "Hey! I'm Reel Agent 🎬\n\n"
    "This isn't a big app flow — just send listing photos and I'll turn them into a video, or say 'daily insight' for ready-to-post market content.\n\n"
    "Best first step: send 6-10 listing photos."
)

_WELCOME_MSG_ZH = (
    "你好！我是 Reel Agent 🎬\n\n"
    "这不是那种复杂 App 流程——你直接发房源照片，我就帮你做成视频；或者说 'daily insight'，我给你可直接发布的市场资讯。\n\n"
    "最好的第一步：直接发 6-10 张房源照片。"
)


def _looks_like_help_request(text: str) -> bool:
    t = text.strip().lower()
    if not t:
        return False

    words = {word.strip(",.!?;:") for word in t.split()}
    if t in _HELP_KEYWORDS or words & _HELP_KEYWORDS:
        return True

    return any(keyword in t for keyword in _HELP_KEYWORDS if " " in keyword)


def _normalize_command_text(text: str) -> str:
    return text.strip().lower().strip(" \t\r\n.,!?;:")


def _contains_any_phrase(text: str, keywords: set[str]) -> bool:
    t = _normalize_command_text(text)
    return any(keyword in t for keyword in keywords)


def _match_style_selection(text: str) -> str | None:
    normalized = _normalize_command_text(text)
    for keyword, style in _STYLE_KEYWORDS.items():
        if normalized == keyword:
            return style
    return None


def _looks_like_app_question(text: str) -> bool:
    return _contains_any_phrase(text, _APP_QUESTION_KEYWORDS)


def _looks_like_trust_question(text: str) -> bool:
    return _contains_any_phrase(text, _TRUST_QUESTION_KEYWORDS)


def _looks_like_pricing_question(text: str) -> bool:
    return _contains_any_phrase(text, _PRICING_QUESTION_KEYWORDS)


def _looks_like_first_step_question(text: str) -> bool:
    return _contains_any_phrase(text, _FIRST_STEP_QUESTION_KEYWORDS)


def _looks_like_daily_insight_request(text: str) -> bool:
    t = text.strip().lower()
    return any(keyword in t for keyword in _DAILY_INSIGHT_KEYWORDS)


def _looks_like_property_content_request(text: str) -> bool:
    t = text.strip().lower()
    if any(keyword in t for keyword in _PROPERTY_CONTENT_KEYWORDS):
        return True

    words = {word.strip(",.!?;:") for word in t.split()}
    if any(word in words for word in _PROPERTY_HINT_WORDS):
        return True

    has_digit = any(ch.isdigit() for ch in t)
    has_address_word = any(word in words for word in _PROPERTY_HINT_WORDS)
    return has_digit and has_address_word


def _build_starter_task(recommended_path: str) -> dict | None:
    if recommended_path == "insight_first":
        return {
            "label": "Reply daily insight",
            "command": "daily insight",
        }
    if recommended_path == "interview_first":
        return {
            "label": "Answer one quick question",
            "command": "tell me the first step",
        }
    return {
        "label": "Send 6-10 listing photos",
        "command": "(send photos)",
    }


def _infer_recommended_path(intent: str, profile: dict | None) -> str:
    if profile:
        return get_recommended_experience(profile)["recommended_path"]
    if intent in {"daily_insight", "daily_insight_refinement"}:
        return "insight_first"
    return "video_first"


def _read_bridge_agent_state(agent_phone: str) -> dict | None:
    """Best-effort read of the OpenClaw bridge state for post-render controls."""
    try:
        raw = json.loads(DEFAULT_BRIDGE_STATE_PATH.read_text("utf-8"))
    except Exception:
        _structured_log("bridge_state_read", agent_phone=agent_phone, result="file_error")
        return None

    agents = raw.get("agents")
    if not isinstance(agents, dict):
        _structured_log("bridge_state_read", agent_phone=agent_phone, result="no_agents")
        return None

    agent_state = agents.get(agent_phone)
    if not isinstance(agent_state, dict):
        _structured_log("bridge_state_read", agent_phone=agent_phone, result="not_found")
        return None
    return agent_state


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _infer_post_render_context(last_job: dict | None, bridge_agent_state: dict | None) -> str | None:
    """
    Determine the most recent user-facing render context.

    Returns one of:
    - "delivered"
    - "daily_insight"
    - None
    """
    latest_kind = None
    latest_ts = None

    if last_job and last_job.get("status") == "DELIVERED":
        latest_kind = "delivered"
        latest_ts = _parse_iso_dt(last_job.get("updated_at")) or _parse_iso_dt(last_job.get("completed_at"))

    if bridge_agent_state:
        last_delivery = bridge_agent_state.get("lastDelivery")
        if isinstance(last_delivery, dict):
            delivery_ts = _parse_iso_dt(last_delivery.get("updatedAt"))
            if latest_kind is None or (delivery_ts and (latest_ts is None or delivery_ts >= latest_ts)):
                latest_kind = "delivered"
                latest_ts = delivery_ts

        last_daily_insight = bridge_agent_state.get("lastDailyInsight")
        if isinstance(last_daily_insight, dict):
            insight_ts = _parse_iso_dt(last_daily_insight.get("updatedAt"))
            if latest_kind is None or (insight_ts and (latest_ts is None or insight_ts >= latest_ts)):
                latest_kind = "daily_insight"
                latest_ts = insight_ts

    return latest_kind


def _classify_intent(
    text: str,
    has_media: bool,
    profile: dict | None,
    last_job: dict | None,
    bridge_agent_state: dict | None = None,
) -> dict:
    """
    [TEST-ONLY in production] Keyword-based intent classifier.

    In production, OpenClaw's Router Skill handles intent routing directly
    (calling /webhook/in, /webhook/feedback etc. without going through here).
    This function exists for local testing and as a reference implementation
    of the routing rules that should be replicated in the OpenClaw Router Skill.

    See DECISIONS.md D9 for the architectural rationale.

    Classify user intent from raw text. Returns action dict.
    This is the text-command fallback — every button interaction
    has a text equivalent so buttonless channels work identically.
    """
    t = text.strip().lower()
    words = set(t.split())
    post_render_context = _infer_post_render_context(last_job, bridge_agent_state)

    # 1. Media present → listing video request (asset-first)
    if has_media:
        return {
            "intent": "listing_video",
            "action": "start_video",
            "response": "Got your photos! Let me take a look... 📸",
        }

    # 2. Trust-first entry questions.
    if _looks_like_app_question(t):
        return {
            "intent": "app_question",
            "action": "explain_use",
            "response": (
                "No app install needed. Just chat with me here: send 6-10 listing photos "
                "for a video, or say 'daily insight' for a ready-to-post market update."
            ),
        }

    if _looks_like_trust_question(t):
        return {
            "intent": "trust_question",
            "action": "reassure_trust",
            "response": (
                "Fair question. I only use the photos and requests you send here to make listing "
                "videos or market content. Safest first try: send 6-10 listing photos and you'll "
                "see exactly what comes back."
            ),
        }

    if _looks_like_pricing_question(t):
        return {
            "intent": "pricing_question",
            "action": "explain_pricing",
            "response": (
                "I don't quote plan pricing inside this chat yet. The fastest way to evaluate it "
                "is to try one starter task first: send 6-10 listing photos, or say 'daily insight'."
            ),
        }

    if _looks_like_first_step_question(t):
        return {
            "intent": "first_step_question",
            "action": "recommend_starter_task",
            "response": (
                "Start with one simple task: send 6-10 listing photos. "
                "If I still need your style, I'll ask one quick follow-up."
            ),
        }

    # 3. Daily push control
    if any(kw in t for kw in _STOP_PUSH_KEYWORDS):
        return {
            "intent": "stop_push",
            "action": "disable_daily_push",
            "response": "Daily insights paused ✅ Say 'resume push' anytime to restart.",
        }
    if any(kw in t for kw in _START_PUSH_KEYWORDS):
        return {
            "intent": "resume_push",
            "action": "enable_daily_push",
            "response": "Daily insights resumed! You'll get tomorrow's content at 8 AM 📬",
        }

    # 4. Primary product paths: keep message routing thin and recognize these
    # before treating free text as post-delivery revision feedback.
    if _looks_like_daily_insight_request(t):
        market_area = None
        language = "en"
        if profile:
            content_prefs = profile.get("content_preferences", {})
            prefs = profile.get("preferences", {})
            market_area = content_prefs.get("market_area") or profile.get("city")
            language = content_prefs.get("language") or prefs.get("language") or "en"

        response = "Got it — I can prepare a ready-to-post daily insight for you. 📈"
        if market_area:
            response = f"Got it — I can prepare a ready-to-post daily insight for {market_area}. 📈"

        return {
            "intent": "daily_insight",
            "action": "start_daily_insight",
            "response": response,
            "market_area": market_area,
            "language": language,
        }

    if _looks_like_property_content_request(t):
        return {
            "intent": "property_content",
            "action": "start_property_content",
            "response": (
                "Got it — this looks like a property content request. "
                "Send photos when you're ready and I'll take it from there. 🏡"
            ),
            "awaiting": "media_or_missing_property_context",
        }

    # 5. Post-render actions.
    if post_render_context == "daily_insight":
        if words & _PUBLISH_KEYWORDS:
            return {
                "intent": "publish",
                "action": "publish",
                "response": "Looks good — publishing this daily insight now. 📈",
            }
        if words & _SKIP_KEYWORDS:
            return {
                "intent": "skip",
                "action": "skip",
                "response": "Skipped this daily insight. We can use the next one instead. ⏭️",
            }
        if t:
            return {
                "intent": "daily_insight_refinement",
                "action": "refine_daily_insight",
                "feedback_text": text.strip(),
                "response": "Got it — refining this daily insight now. ✍️",
            }

    if post_render_context == "delivered":
        if words & _PUBLISH_KEYWORDS:
            return {
                "intent": "publish",
                "action": "publish",
                "response": "Great choice! Here's your caption and hashtags 📱",
            }
        if words & _REDO_KEYWORDS:
            return {
                "intent": "redo",
                "action": "redo",
                "response": "Starting from scratch with your photos... 🔄",
            }
        if words & _ADJUST_KEYWORDS or t:
            # Any remaining non-trivial text after delivery = revision feedback.
            return {
                "intent": "revision",
                "action": "submit_feedback",
                "feedback_text": text.strip(),
                "response": "Got it — adjusting now... ⚡",
            }

    # 6. Style selection
    style = _match_style_selection(t)
    if style:
            return {
                "intent": "style_selection",
                "action": "set_style",
                "style": style,
                "response": f"Style set to {style} ✨",
            }

    # 7. Confirmation
    if words & _CONFIRM_KEYWORDS:
        return {
            "intent": "confirm",
            "action": "confirm_and_generate",
            "response": "Starting video generation... 🎬",
        }

    # 8. Explicit help / first-contact
    if _looks_like_help_request(t):
        is_zh = any(ord(c) > 0x4E00 for c in t) if t else False
        return {
            "intent": "first_contact" if not profile else "help",
            "action": "welcome",
            "response": _WELCOME_MSG_ZH if is_zh else _WELCOME_MSG,
        }

    # 9. New-user empty / ambiguous input falls back to welcome
    if not profile:
        is_zh = any(ord(c) > 0x4E00 for c in t) if t else False
        return {
            "intent": "first_contact",
            "action": "welcome",
            "response": _WELCOME_MSG_ZH if is_zh else _WELCOME_MSG,
        }

    # 10. Off-topic
    if t:
        return {
            "intent": "off_topic",
            "action": "reject",
            "response": (
                "I only do listing videos and market content 📹 — send me photos or say 'help'!"
            ),
        }

    # 11. Empty message
    return {
        "intent": "unknown",
        "action": "prompt",
        "response": "Send me listing photos to make a video, or say 'help' to see what I can do!",
    }


@app.post("/api/message")
@app.post("/api/router-test")
@limiter.limit("10/minute")
async def handle_message(
    request: Request,
    payload: MessagePayload,
    _auth: None = Depends(_require_backend_auth),
):
    """
    [TEST-ONLY in production] Universal message + intent routing endpoint.

    PURPOSE (testing): Simulates what OpenClaw's Router Skill does in production.
    Accepts a raw message, classifies intent via keyword matching, and returns
    the action + response OpenClaw should take next. Useful for end-to-end
    pipeline testing without a live OpenClaw connection.

    PRODUCTION ARCHITECTURE (D9): In production, OpenClaw's Router Skill handles
    intent detection and calls /webhook/in or /webhook/feedback directly.
    This endpoint is NOT in the production message path.

    Routing rules (mirror these in OpenClaw Router Skill):
      has_media            → intent: listing_video  → POST /webhook/in
      revision after video → intent: revision       → POST /webhook/feedback
      "daily insight"      → intent: daily_insight  → POST /api/daily-trigger
      "stop push"          → intent: stop_push      → POST /webhook/in {action: disable_daily_push}
    """
    import profile_manager

    phone = payload.agent_phone
    profile = await asyncio.to_thread(profile_manager.get_profile, phone)

    # Find most recent job for this agent (for revision context)
    job_mgr = _get_job_mgr()
    last_job = None
    try:
        jobs = await job_mgr.list_jobs_by_phone(phone, limit=1)
        if jobs:
            last_job = jobs[0]
    except Exception:
        pass  # No jobs yet — that's fine

    bridge_agent_state = _read_bridge_agent_state(phone)

    result = _classify_intent(payload.text, payload.has_media, profile, last_job, bridge_agent_state)

    _structured_log(
        "intent_classified",
        agent_phone=phone,
        intent=result.get("intent"),
        action=result.get("action"),
        has_media=payload.has_media,
        has_profile=profile is not None,
    )

    # Add text-command hints for the next step (so OpenClaw can show them)
    text_hints = _get_text_hints(result["intent"], profile)
    result["text_commands"] = text_hints
    result["agent_phone"] = phone
    result["has_profile"] = profile is not None
    result["recommended_path"] = _infer_recommended_path(result["intent"], profile)
    if result["intent"] in {
        "app_question",
        "trust_question",
        "pricing_question",
        "first_step_question",
    }:
        result["starter_task"] = _build_starter_task(result["recommended_path"])

    # For listing_video intent with media: auto-start only when style already exists.
    style = profile.get("preferences", {}).get("style") if profile else None
    if result["action"] == "start_video" and style:
        result["response"] = (
            f"Got your photos! Using your {style} style... 🎬\nVideo will be ready in ~3 min."
        )
        result["auto_generate"] = True
        result["style"] = style
    elif result["action"] == "start_video":
        result["response"] = (
            "Got your photos! 📸\n\n"
            "Pick a style (type or tap):\n"
            "• elegant ✨\n"
            "• professional 💼\n"
            "• energetic 🔥"
        )
        result["awaiting"] = "style_selection"

    if profile and result.get("recommended_path"):
        activation_updates = {
            "activation": {"last_recommended_path": result["recommended_path"]},
        }
        try:
            await asyncio.to_thread(profile_manager.update_profile, phone, activation_updates)
        except Exception:
            pass

    return result


def _get_text_hints(
    intent: str,
    profile: dict | None,
) -> dict:
    """Return text-command hints for the next expected interaction."""
    if intent in ("first_contact", "help"):
        return {
            "next": "Send listing photos to start",
            "examples": ["(send photos)", "help", "daily insight"],
        }
    if intent in ("app_question", "trust_question", "pricing_question", "first_step_question"):
        return {
            "next": "Try one clear starter task",
            "examples": ["(send photos)", "daily insight"],
        }
    if intent == "daily_insight":
        return {
            "next": "Wait for the draft, then refine or publish",
            "examples": ["shorter", "publish", "skip"],
        }
    if intent == "listing_video":
        return {
            "next": "Wait for video generation",
            "examples": ["(processing...)"],
        }
    if intent == "property_content":
        if profile and profile.get("preferences", {}).get("style"):
            return {
                "next": "Send photos or missing property details",
                "examples": ["(send photos)", "open house this Sunday 2pm"],
            }
        return {
            "next": "Send photos or missing property details",
            "examples": ["(send photos)", "open house this Sunday 2pm"],
        }
    if intent == "style_selection":
        return {"next": "Confirm to start", "examples": ["go", "ok"]}
    if intent == "confirm":
        return {
            "next": "Wait for video",
            "examples": ["(processing...)"],
        }
    if intent in ("publish", "revision", "redo", "skip"):
        return {
            "next": "Send more photos or wait",
            "examples": ["(send photos)", "help"],
        }
    if intent == "daily_insight_refinement":
        return {
            "next": "Refine again or publish",
            "examples": ["shorter", "more professional", "publish", "skip"],
        }
    return {
        "next": "Send photos or say help",
        "examples": ["(send photos)", "help"],
    }


@app.post("/api/daily-trigger")
async def daily_trigger(
    secret: str = "",
    _auth: None = Depends(_require_backend_auth),
):
    """
    Manually trigger daily content generation for all active agents.
    Protected by DAILY_TRIGGER_SECRET env var (if set).
    Useful for testing without waiting for the scheduler.
    """
    expected = os.getenv("DAILY_TRIGGER_SECRET", "")
    if expected and secret != expected:
        raise HTTPException(403, "Invalid secret")

    if _scheduler is None:
        raise HTTPException(503, "Scheduler not ready")

    # Reset last-run guard so we can re-trigger today
    _scheduler._last_run_date = None
    result = await _scheduler.run_once()
    return result


@app.post("/webhook/feedback")
async def webhook_feedback(
    payload: FeedbackPayload,
    _auth: None = Depends(_require_backend_auth),
):
    """
    OpenClaw calls this when an agent provides post-render feedback.

    Supported scopes:
    - video: revision feedback after video delivery (queues a new video job)
    - insight: refine the current daily insight (returns refined content and can re-push callback)
    """
    # Imports available via top-level sys.path.insert (line ~42)
    import feedback_classifier
    import generate_daily_insight
    import profile_manager
    import render_insight_image

    from agent.callback_client import CallbackClient
    from orchestrator.progress_notifier import _make_image_url

    if payload.feedback_scope == "insight":
        bridge_agent_state = _read_bridge_agent_state(payload.agent_phone)
        current_insight = _coerce_current_insight(payload, bridge_agent_state)
        if not current_insight:
            raise HTTPException(400, "current_insight is required for insight feedback")

        profile = await asyncio.to_thread(profile_manager.get_profile, payload.agent_phone)
        agent_name = payload.agent_name or (profile or {}).get("name", "")
        refined = await asyncio.to_thread(
            generate_daily_insight.refine,
            current_insight,
            payload.feedback_text,
            agent_name,
        )

        branding_colors = None
        if profile:
            branding_colors = profile.get("content_preferences", {}).get("branding_colors")

        output_dir = OUTPUT_BASE / f"daily_refine_{payload.agent_phone}_{uuid.uuid4().hex[:8]}"
        image_paths = await asyncio.to_thread(
            render_insight_image.render_all_formats,
            refined.get("headline", "Daily Insight"),
            refined.get("body", refined.get("caption", "")),
            agent_name or "Reel Agent",
            str(output_dir),
            branding_colors,
        )

        if payload.callback_url:
            image_urls = {fmt: _make_image_url(file_path) for fmt, file_path in image_paths.items()}
            await CallbackClient().send(
                payload.callback_url,
                {
                    "type": "daily_insight",
                    "agent_phone": payload.agent_phone,
                    "insight": {
                        "topic": refined.get("topic", ""),
                        "headline": refined.get("headline", ""),
                        "caption": refined.get("caption", ""),
                        "hashtags": refined.get("hashtags", []),
                        "cta": refined.get("cta", ""),
                        "content_type": refined.get("content_type", "market_stat"),
                    },
                    "image_urls": image_urls,
                    "agent_name": agent_name,
                },
            )

        return {
            "feedback_scope": "insight",
            "status": "DELIVERED",
            "insight": refined,
            "image_paths": image_paths,
        }

    if not payload.job_id:
        raise HTTPException(400, "job_id is required for video feedback")

    job_mgr = _get_job_mgr()
    dispatcher = _get_dispatcher()

    # 1. Classify the feedback
    classified = await asyncio.to_thread(feedback_classifier.classify, payload.feedback_text)

    # 2. Update agent profile with learned preference
    original_job = await job_mgr.get_job(payload.job_id)
    if not original_job:
        raise HTTPException(404, f"Job {payload.job_id} not found")

    await asyncio.to_thread(
        profile_manager.record_feedback,
        payload.agent_phone,
        payload.job_id,
        payload.feedback_text,
        classified,
        payload.revision_round,
    )

    # 3. Queue a new revision job starting from the classified re_run_from step
    re_run_from = classified.get("re_run_from", "SCRIPTING")
    revision_context = {
        "feedback": payload.feedback_text,
        "classified": classified,
        "re_run_from": re_run_from,
    }

    import json

    original_params = json.loads(original_job["params"]) if original_job.get("params") else {}

    new_job_id = await job_mgr.create_job(
        agent_phone=payload.agent_phone,
        photo_dir=original_job["photo_dir"],
        params=original_params,
        output_dir=None,
        callback_url=original_job.get("callback_url"),
        parent_job_id=payload.job_id,
        revision_context=revision_context,
    )

    await dispatcher.submit(new_job_id)

    return {
        "feedback_scope": "video",
        "job_id": new_job_id,
        "parent_job_id": payload.job_id,
        "re_run_from": re_run_from,
        "classified": classified,
        "status": "QUEUED",
    }


@app.get("/api/profile/{phone}")
async def get_profile(phone: str):
    """
    OpenClaw queries this before collecting requirements.
    If profile exists with style/music preferences → OpenClaw skips asking.
    If 404 → OpenClaw shows style/music selection buttons.
    """
    import profile_manager

    profile = await asyncio.to_thread(profile_manager.get_profile, phone)
    if not profile:
        raise HTTPException(404, "Profile not found")
    # Return only what OpenClaw needs to decide whether to ask questions
    prefs = profile.get("preferences", {})
    content = profile.get("content_preferences", {})
    return {
        "phone": phone,
        "name": profile.get("name", ""),
        "style": prefs.get("style"),
        "music": prefs.get("music"),
        "language": content.get("language", "en"),
        "market_area": content.get("market_area", ""),
        "branding_colors": content.get("branding_colors"),
        "daily_push_enabled": content.get("daily_push_enabled", True),
        "videos_created": profile.get("stats", {}).get("videos_created", 0),
    }


@app.post("/webhook/in")
@limiter.limit("10/minute")
async def webhook_in(
    request: Request,
    payload: WebhookPayload,
    _auth: None = Depends(_require_backend_auth),
):
    """
    OpenClaw calls this when a user has confirmed requirements.
    Photos must already be saved to disk by OpenClaw before calling.

    Special actions (no photos needed):
      - params.action == "disable_daily_push": opt agent out of daily content push
      - params.action == "enable_daily_push":  re-enable after opt-out
    """
    action = payload.params.get("action")

    if action in ("disable_daily_push", "enable_daily_push"):
        import profile_manager

        enabled = action == "enable_daily_push"
        await asyncio.to_thread(
            profile_manager.update_profile,
            payload.agent_phone,
            {"content_preferences": {"daily_push_enabled": enabled}},
        )
        return {"action": action, "daily_push_enabled": enabled}

    # SSRF protection: validate callback URL before accepting
    if payload.callback_url:
        from agent.callback_client import _is_safe_callback_url

        if not _is_safe_callback_url(payload.callback_url):
            raise HTTPException(400, "callback_url points to a disallowed address")

    job_mgr = _get_job_mgr()
    dispatcher = _get_dispatcher()

    # Use first photo's directory as photo_dir
    if not payload.photo_paths:
        raise HTTPException(400, "photo_paths is empty")

    photo_dir = str(Path(payload.photo_paths[0]).parent)

    job_id = await job_mgr.create_job(
        agent_phone=payload.agent_phone,
        photo_dir=photo_dir,
        params=payload.params,
        callback_url=payload.callback_url,
        openclaw_msg_id=payload.openclaw_msg_id,
    )

    await dispatcher.submit(job_id)

    return {"job_id": job_id, "status": "QUEUED"}


# ---------------------------------------------------------------------------
# Webhook: Manual override (human takeover)
# ---------------------------------------------------------------------------


@app.post("/webhook/manual-override/{job_id}")
async def manual_override(
    job_id: str,
    action: Literal["cancel", "retry", "mark_delivered"],
    _auth: None = Depends(_require_backend_auth),
):
    """
    Human takeover for stuck or failed jobs.
    - cancel:         Stop the job entirely.
    - retry:          Reset to QUEUED and resubmit.
    - mark_delivered: Force DELIVERED status (ops bypass).
    """
    job_mgr = _get_job_mgr()
    dispatcher = _get_dispatcher()

    job = await job_mgr.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if action == "cancel":
        await dispatcher.cancel(job_id)
        return {"job_id": job_id, "action": "cancelled"}

    if action == "retry":
        await job_mgr.update_status(job_id, "QUEUED", retry_count=job.get("retry_count", 0))
        await dispatcher.submit(job_id)
        return {"job_id": job_id, "action": "requeued"}

    if action == "mark_delivered":
        await job_mgr.update_status(job_id, "DELIVERED")
        return {"job_id": job_id, "action": "marked_delivered"}

    raise HTTPException(400, f"Unknown action: {action}")


# Admin Skill Brief routes (extracted to routes/admin.py)
from routes.admin import router as admin_router

app.include_router(admin_router)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    print("Reel Agent Server")
    print("   Open http://localhost:8000\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
