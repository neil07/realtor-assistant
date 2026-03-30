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
import json
import os
import shutil
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

# Add scripts to path
SCRIPTS_DIR = Path(__file__).parent / "skills" / "listing-video" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

OUTPUT_BASE = Path(__file__).parent / "skills" / "listing-video" / "output"
OUTPUT_BASE.mkdir(parents=True, exist_ok=True)

# Lazy imports — populated in lifespan
_job_mgr = None
_dispatcher = None
_scheduler = None


# ---------------------------------------------------------------------------
# Lifespan: init DB + dispatcher, resume pending jobs on startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _job_mgr, _dispatcher

    from agent.callback_client import CallbackClient
    from orchestrator.daily_scheduler import DailyScheduler
    from orchestrator.dispatcher import Dispatcher
    from orchestrator.job_manager import JobManager
    from orchestrator.progress_notifier import ProgressNotifier

    _job_mgr = JobManager()
    await _job_mgr.init_db()

    notifier = ProgressNotifier(CallbackClient())
    _dispatcher = Dispatcher(_job_mgr, notifier)

    # Start daily content scheduler as background task
    _scheduler = DailyScheduler(notifier)
    asyncio.create_task(_scheduler.run_forever())

    # Resume any jobs that were in-flight before a restart
    pending = await _job_mgr.list_pending_jobs()
    if pending:
        print(f"  Resuming {len(pending)} pending job(s)...")
        for job in pending:
            await _dispatcher.submit(job["job_id"])

    print("Reel Agent server ready.")
    yield
    # Graceful shutdown: running tasks will finish naturally


app = FastAPI(title="Reel Agent", lifespan=lifespan)
app.mount("/output", StaticFiles(directory=str(OUTPUT_BASE)), name="output")


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
async def generate_video(
    photos: list[UploadFile] = File(...),
    address: str = Form("[TBD]"),
    price: str = Form("[TBD]"),
    agent_name: str = Form(""),
    agent_phone: str = Form(""),
    style: str = Form("professional"),
    music: str = Form("modern"),
    aspect_ratio: str = Form("9:16"),
    language: str = Form("en"),
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

    return {"job_id": db_job_id, "status": "QUEUED"}


# ---------------------------------------------------------------------------
# API: Job status
# ---------------------------------------------------------------------------

@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    """Poll job status with delivery, review, and diagnostics summaries."""
    job_mgr = _get_job_mgr()
    summary = await job_mgr.get_job_summary(job_id)
    if not summary:
        raise HTTPException(404, "Job not found")

    resp = dict(summary)
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
    photo_paths: list[str]            # paths to photos already saved on disk
    params: dict = {}
    callback_url: str | None = None
    openclaw_msg_id: str | None = None


class FeedbackPayload(BaseModel):
    job_id: str
    agent_phone: str
    feedback_text: str                # raw text from WhatsApp ("换个更活泼的音乐")
    revision_round: int = 1


@app.post("/api/daily-trigger")
async def daily_trigger(secret: str = ""):
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
async def webhook_feedback(payload: FeedbackPayload):
    """
    OpenClaw calls this when an agent provides revision feedback after video delivery.
    Classifies the feedback, updates the agent's preference profile,
    and queues a new revision job starting from the right step.

    Returns: {job_id, re_run_from, classified} so OpenClaw can track the new job.
    """
    job_mgr = _get_job_mgr()
    dispatcher = _get_dispatcher()

    # Import here to avoid circular deps at module load
    sys.path.insert(0, str(SCRIPTS_DIR))
    import feedback_classifier
    import profile_manager

    # 1. Classify the feedback
    classified = await asyncio.to_thread(
        feedback_classifier.classify, payload.feedback_text
    )

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
async def webhook_in(payload: WebhookPayload):
    """
    OpenClaw calls this when a user has confirmed requirements.
    Photos must already be saved to disk by OpenClaw before calling.

    Special actions (no photos needed):
      - params.action == "disable_daily_push": opt agent out of daily content push
      - params.action == "enable_daily_push":  re-enable after opt-out
    """
    action = payload.params.get("action")

    if action in ("disable_daily_push", "enable_daily_push"):
        sys.path.insert(0, str(SCRIPTS_DIR))
        import profile_manager

        enabled = action == "enable_daily_push"
        await asyncio.to_thread(
            profile_manager.update_profile,
            payload.agent_phone,
            {"content_preferences": {"daily_push_enabled": enabled}},
        )
        return {"action": action, "daily_push_enabled": enabled}

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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    print("Reel Agent Server")
    print("   Open http://localhost:8000\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
