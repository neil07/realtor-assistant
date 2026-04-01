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
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

# Add scripts to path
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

# Operator Console
from console.router import router as console_router

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


def _require_backend_auth(authorization: str | None = Header(default=None)) -> None:
    """Protect OpenClaw-facing API routes with optional Bearer token auth."""
    expected = os.getenv("REEL_AGENT_TOKEN", "").strip()
    if not expected:
        return

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")

    token = authorization.removeprefix("Bearer ").strip()
    if token != expected:
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
_DAILY_INSIGHT_KEYWORDS = {
    "daily insight",
    "insight",
    "market insight",
    "daily update",
    "market update",
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


def _read_bridge_agent_state(agent_phone: str) -> dict | None:
    """Best-effort read of the OpenClaw bridge state for post-render controls."""
    try:
        raw = json.loads(DEFAULT_BRIDGE_STATE_PATH.read_text("utf-8"))
    except Exception:
        return None

    agents = raw.get("agents")
    if not isinstance(agents, dict):
        return None

    agent_state = agents.get(agent_phone)
    return agent_state if isinstance(agent_state, dict) else None


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

    # 2. Style selection
    for keyword, style in _STYLE_KEYWORDS.items():
        if keyword in t:
            return {
                "intent": "style_selection",
                "action": "set_style",
                "style": style,
                "response": f"Style set to {style} ✨",
            }

    # 3. Confirmation
    if words & _CONFIRM_KEYWORDS:
        return {
            "intent": "confirm",
            "action": "confirm_and_generate",
            "response": "Starting video generation... 🎬",
        }

    # 4. Explicit help / first-contact
    if _looks_like_help_request(t):
        is_zh = any(ord(c) > 0x4E00 for c in t) if t else False
        return {
            "intent": "first_contact" if not profile else "help",
            "action": "welcome",
            "response": _WELCOME_MSG_ZH if is_zh else _WELCOME_MSG,
        }

    # 5. Daily push control
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

    # 6. Primary product paths: keep message routing thin and recognize these
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

    # 7. Post-render actions.
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

    # 8. New-user empty / ambiguous input falls back to welcome
    if not profile:
        is_zh = any(ord(c) > 0x4E00 for c in t) if t else False
        return {
            "intent": "first_contact",
            "action": "welcome",
            "response": _WELCOME_MSG_ZH if is_zh else _WELCOME_MSG,
        }

    # 9. Off-topic
    if t:
        return {
            "intent": "off_topic",
            "action": "reject",
            "response": (
                "I only do listing videos and market content 📹 — send me photos or say 'help'!"
            ),
        }

    # 10. Empty message
    return {
        "intent": "unknown",
        "action": "prompt",
        "response": "Send me listing photos to make a video, or say 'help' to see what I can do!",
    }


@app.post("/api/message")
async def handle_message(
    payload: MessagePayload,
    _auth: None = Depends(_require_backend_auth),
):
    """
    Universal message handler — text-command + intent routing.

    This is the primary entry point for channels without buttons.
    OpenClaw routes every user message here; the response tells
    OpenClaw what to do next (show buttons, start job, etc.).

    Works identically to button-based flow — every button has a
    text equivalent so the UX is consistent across platforms.
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

    # Add text-command hints for the next step (so OpenClaw can show them)
    text_hints = _get_text_hints(result["intent"], profile)
    result["text_commands"] = text_hints
    result["agent_phone"] = phone
    result["has_profile"] = profile is not None

    # For listing_video intent with media: auto-start if profile has style
    has_style = profile and profile.get("preferences", {}).get("style")
    if result["action"] == "start_video" and has_style:
        style = profile["preferences"]["style"]
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
    if intent == "daily_insight":
        return {
            "next": "Ask for today's market content",
            "examples": ["daily insight", "shorter", "more professional"],
        }
    if intent in ("listing_video", "property_content"):
        if profile and profile.get("preferences", {}).get("style"):
            return {
                "next": "Confirm or change style",
                "examples": ["go", "elegant", "professional"],
            }
        return {
            "next": "Pick a style or send photos",
            "examples": ["elegant", "professional", "energetic", "(send photos)"],
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
    # Import here to avoid circular deps at module load
    sys.path.insert(0, str(SCRIPTS_DIR))
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
async def webhook_in(
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
# Admin — Skill Brief Management
# ---------------------------------------------------------------------------

_ADMIN_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Skill Brief 管理</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          margin: 0; background: #f8f9fa; color: #212529; }}
  .nav {{ background: #1a1a2e; color: #fff; padding: 14px 24px;
          font-size: 15px; font-weight: 600; }}
  .nav a {{ color: #7ec8e3; text-decoration: none; margin-left: 16px; font-weight: 400; }}
  .container {{ max-width: 960px; margin: 32px auto; padding: 0 24px; }}
  h2 {{ font-size: 20px; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff;
           box-shadow: 0 1px 4px rgba(0,0,0,.08); border-radius: 8px;
           overflow: hidden; }}
  th {{ background: #f1f3f5; font-size: 12px; text-transform: uppercase;
        letter-spacing: .05em; padding: 10px 16px; text-align: left; }}
  td {{ padding: 10px 16px; border-top: 1px solid #e9ecef; font-size: 14px; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px;
            font-size: 11px; font-weight: 600; }}
  .badge-custom {{ background: #d1fae5; color: #065f46; }}
  .badge-default {{ background: #e5e7eb; color: #374151; }}
  .btn {{ display: inline-block; padding: 5px 12px; border-radius: 6px;
          font-size: 13px; text-decoration: none; background: #3b82f6;
          color: #fff; }}
  .btn:hover {{ background: #2563eb; }}
  /* Editor page */
  .editor-wrap {{ background: #fff; border-radius: 8px; padding: 24px;
                  box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  textarea {{ width: 100%; height: 520px; font-family: "SF Mono", Menlo, monospace;
              font-size: 13px; line-height: 1.6; border: 1px solid #d1d5db;
              border-radius: 6px; padding: 12px; box-sizing: border-box;
              resize: vertical; }}
  .actions {{ margin-top: 14px; display: flex; gap: 10px; align-items: center; }}
  .btn-save {{ background: #10b981; padding: 8px 20px; font-size: 14px; }}
  .btn-save:hover {{ background: #059669; }}
  .btn-reset {{ background: #ef4444; padding: 8px 16px; font-size: 14px; }}
  .btn-reset:hover {{ background: #dc2626; }}
  .toast {{ display:none; padding: 8px 16px; border-radius: 6px; font-size: 13px;
            background: #d1fae5; color: #065f46; }}
</style>
</head>
<body>
<div class="nav">🎬 Reel Agent Admin
  <a href="/admin">经纪人列表</a>
  <a href="/">测试界面</a>
</div>
{body}
<script>
async function saveSkill(phone, skillType) {{
  const content = document.getElementById('editor').value;
  const res = await fetch(`/admin/agents/${{phone}}/skills/${{skillType}}`, {{
    method: 'PUT',
    headers: {{'Content-Type': 'text/plain'}},
    body: content,
  }});
  const toast = document.getElementById('toast');
  if (res.ok) {{
    toast.style.display = 'inline';
    toast.textContent = '✅ 已保存';
    setTimeout(() => toast.style.display = 'none', 2500);
  }} else {{
    toast.style.background = '#fee2e2'; toast.style.color = '#991b1b';
    toast.style.display = 'inline';
    toast.textContent = '❌ 保存失败';
  }}
}}
async function resetSkill(phone, skillType) {{
  if (!confirm('确定恢复为全局默认 Brief？当前内容会丢失。')) return;
  const res = await fetch(`/admin/agents/${{phone}}/skills/${{skillType}}/reset`, {{method: 'POST'}});
  if (res.ok) location.reload();
}}
</script>
</body>
</html>"""


def _require_admin(request: Request) -> None:
    """Simple token auth for admin routes. Skip check if ADMIN_TOKEN not set."""
    token = os.environ.get("ADMIN_TOKEN", "")
    if not token:
        return  # No token configured — open access (dev mode)
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {token}":
        raise HTTPException(403, "Invalid or missing admin token")


@app.get("/admin", response_class=HTMLResponse)
async def admin_list_agents(request: Request):
    """Admin UI: list all agents and their Skill brief status."""
    _require_admin(request)
    import profile_manager

    briefs = await asyncio.to_thread(profile_manager.list_skill_briefs)
    # Also include agents that have profiles but no custom brief yet
    all_profiles = []
    profiles_dir = Path(__file__).parent / "skills" / "listing-video" / "profiles"
    for p in sorted(profiles_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text())
            all_profiles.append(data.get("phone", p.stem))
        except Exception:
            pass

    brief_index = {b["phone"]: b for b in briefs}
    rows = ""
    for phone in all_profiles:
        safe = profile_manager._safe_phone(phone)
        b = brief_index.get(safe, {})
        is_custom = b.get("is_customized", False)
        badge = (
            '<span class="badge badge-custom">已定制</span>'
            if is_custom
            else '<span class="badge badge-default">使用默认</span>'
        )
        edit_url = f"/admin/agents/{phone}/skills/video/edit"
        rows += f"<tr><td>{phone}</td><td>video</td><td>{badge}</td><td><a class='btn' href='{edit_url}'>编辑 Brief</a></td></tr>"

    body = f"""
    <div class="container">
      <h2>经纪人 Skill Brief 管理</h2>
      <table>
        <thead><tr><th>手机号</th><th>Skill</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""
    return _ADMIN_HTML.format(body=body)


@app.get("/admin/agents/{phone}/skills/{skill_type}/edit", response_class=HTMLResponse)
async def admin_edit_skill_ui(phone: str, skill_type: str, request: Request):
    """Admin UI: edit a specific agent's Skill brief in the browser."""
    _require_admin(request)
    import profile_manager

    content = await asyncio.to_thread(profile_manager.get_skill_brief, phone, skill_type)
    escaped = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    body = f"""
    <div class="container">
      <h2>编辑 Skill Brief — {phone} / {skill_type}</h2>
      <div class="editor-wrap">
        <textarea id="editor">{escaped}</textarea>
        <div class="actions">
          <button class="btn btn-save" onclick="saveSkill('{phone}','{skill_type}')">保存</button>
          <button class="btn btn-reset" onclick="resetSkill('{phone}','{skill_type}')">恢复默认</button>
          <span id="toast" class="toast"></span>
        </div>
      </div>
    </div>"""
    return _ADMIN_HTML.format(body=body)


@app.get("/admin/agents/{phone}/skills/{skill_type}")
async def admin_get_skill(phone: str, skill_type: str, request: Request):
    """API: return the raw Markdown content of an agent's Skill brief."""
    _require_admin(request)
    import profile_manager

    content = await asyncio.to_thread(profile_manager.get_skill_brief, phone, skill_type)
    return {"phone": phone, "skill_type": skill_type, "content": content}


@app.put("/admin/agents/{phone}/skills/{skill_type}", status_code=204)
async def admin_update_skill(phone: str, skill_type: str, request: Request):
    """API: overwrite an agent's Skill brief with plain-text Markdown body."""
    _require_admin(request)
    import profile_manager

    content = (await request.body()).decode("utf-8")
    if not content.strip():
        raise HTTPException(400, "Brief content cannot be empty")
    await asyncio.to_thread(profile_manager.update_skill_brief, phone, content, skill_type)


@app.post("/admin/agents/{phone}/skills/{skill_type}/reset", status_code=204)
async def admin_reset_skill(phone: str, skill_type: str, request: Request):
    """API: reset an agent's Skill brief to the global default."""
    _require_admin(request)
    import profile_manager

    default_path = (
        Path(__file__).parent / "skills" / "listing-video" / "prompts" / "creative_director.md"
    )
    if not default_path.exists():
        raise HTTPException(404, "Global default brief not found")
    content = default_path.read_text()
    await asyncio.to_thread(profile_manager.update_skill_brief, phone, content, skill_type)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    print("Reel Agent Server")
    print("   Open http://localhost:8000\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
