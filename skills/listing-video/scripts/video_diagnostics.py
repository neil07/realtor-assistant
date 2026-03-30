#!/usr/bin/env python3
"""
Listing Video Agent — Per-job diagnostics

Creates a compact, scene-level diagnostic artifact for each generated video:
  {job_dir}/diagnostics.json
  {job_dir}/diagnostics_report.md

This is intentionally separate from run.log/run.jsonl:
  - run.log is good for raw execution history
  - diagnostics.json answers "why is this video quality bad?" quickly
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _job_path(job_dir: str) -> Path:
    return Path(job_dir).resolve()


def _diag_path(job_dir: str) -> Path:
    return _job_path(job_dir) / "diagnostics.json"


def _report_path(job_dir: str) -> Path:
    return _job_path(job_dir) / "diagnostics_report.md"


def _get_lock(job_dir: str) -> threading.Lock:
    key = str(_job_path(job_dir))
    with _LOCKS_GUARD:
        if key not in _LOCKS:
            _LOCKS[key] = threading.Lock()
        return _LOCKS[key]


def _default_doc(job_dir: str) -> dict:
    return {
        "version": 1,
        "job_dir": str(_job_path(job_dir)),
        "created_at": _now(),
        "updated_at": _now(),
        "scenes": {},
        "summary": {},
        "final": {},
    }


def _load_doc(job_dir: str) -> dict:
    path = _diag_path(job_dir)
    if not path.exists():
        return _default_doc(job_dir)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _default_doc(job_dir)


def _write_doc(job_dir: str, doc: dict) -> None:
    path = _diag_path(job_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as tmp:
        json.dump(doc, tmp, ensure_ascii=False, indent=2)
        tmp_path = tmp.name
    os.replace(tmp_path, path)


def _update(job_dir: str, updater) -> None:
    lock = _get_lock(job_dir)
    with lock:
        doc = _load_doc(job_dir)
        updater(doc)
        doc["updated_at"] = _now()
        _refresh_summary(doc)
        _write_doc(job_dir, doc)
        _report_path(job_dir).write_text(_build_report(doc), encoding="utf-8")


def _scene_key(sequence: int) -> str:
    return f"{int(sequence):02d}"


def _ensure_scene(doc: dict, sequence: int) -> dict:
    key = _scene_key(sequence)
    scene = doc["scenes"].setdefault(
        key,
        {
            "sequence": int(sequence),
            "scene": {},
            "render": {"attempts": []},
            "tts": {"attempts": []},
            "assembly": {},
        },
    )
    scene.setdefault("render", {"attempts": []})
    scene["render"].setdefault("attempts", [])
    scene.setdefault("tts", {"attempts": []})
    scene["tts"].setdefault("attempts", [])
    scene.setdefault("assembly", {})
    return scene


def _probe_media(path: str | None) -> dict:
    if not path or not os.path.exists(path):
        return {"exists": False}

    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-show_entries",
        "format=duration:stream=codec_type,width,height",
        "-of",
        "json",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {"exists": True, "probe_error": result.stderr[-300:]}

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"exists": True, "probe_error": "invalid ffprobe output"}

    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    return {
        "exists": True,
        "duration": round(float(data.get("format", {}).get("duration", 0.0) or 0.0), 2),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "size_bytes": os.path.getsize(path),
        "path": path,
    }


def _classify_error(message: str | None) -> str:
    text = (message or "").lower()
    if not text:
        return "unknown"
    if "timed out" in text:
        return "timeout"
    if "not set" in text:
        return "configuration"
    if "model" in text and "not found" in text:
        return "model_config"
    if "task failed" in text:
        return "vendor_task_failed"
    if "poll error" in text:
        return "vendor_poll_error"
    if "upload" in text:
        return "upload_failure"
    if "ffmpeg" in text or "ffprobe" in text:
        return "media_processing"
    return "runtime"


def record_scene_plan(job_dir: str, scene_plan: list[dict]) -> None:
    def updater(doc: dict) -> None:
        for scene_data in scene_plan:
            scene = _ensure_scene(doc, scene_data["sequence"])
            narration = (scene_data.get("text_narration") or "").strip()
            scene["scene"] = {
                "first_frame": scene_data.get("first_frame"),
                "last_frame": scene_data.get("last_frame"),
                "scene_desc": scene_data.get("scene_desc"),
                "motion_prompt": scene_data.get("motion_prompt"),
                "narration": narration,
                "narration_word_count": len(narration.split()) if narration else 0,
            }

    _update(job_dir, updater)


def record_render_diagnostics(
    job_dir: str,
    sequence: int,
    requested_duration: int,
    attempts: list[dict],
    final_result: dict,
) -> None:
    def updater(doc: dict) -> None:
        scene = _ensure_scene(doc, sequence)
        render = scene["render"]
        render["requested_duration"] = requested_duration
        render["attempts"] = attempts
        render["status"] = final_result.get("status")
        render["engine"] = final_result.get("engine")
        render["model"] = final_result.get("model")
        render["fallback_used"] = any(a.get("engine") != "ima" for a in attempts if a.get("status") == "success")
        render["error"] = final_result.get("message")
        render["probe"] = _probe_media(final_result.get("video_path"))

    _update(job_dir, updater)


def record_tts_diagnostics(
    job_dir: str,
    sequence: int,
    text: str,
    attempts: list[dict],
    final_result: dict,
) -> None:
    def updater(doc: dict) -> None:
        scene = _ensure_scene(doc, sequence)
        tts = scene["tts"]
        tts["text"] = text
        tts["characters"] = len(text)
        tts["attempts"] = attempts
        tts["status"] = final_result.get("status")
        tts["engine"] = final_result.get("engine")
        tts["model"] = final_result.get("model")
        tts["error"] = final_result.get("message")
        tts["probe"] = _probe_media(final_result.get("audio_path"))

    _update(job_dir, updater)


def record_assembly_diagnostics(
    job_dir: str,
    sequence: int,
    clip_duration_before: float,
    narration_duration: float | None,
    adjustment: str,
    merge_status: str,
    output_path: str,
    adjustment_ratio: float | None = None,
    note: str | None = None,
) -> None:
    def updater(doc: dict) -> None:
        scene = _ensure_scene(doc, sequence)
        scene["assembly"] = {
            "clip_duration_before": round(clip_duration_before, 2),
            "narration_duration": round(narration_duration, 2) if narration_duration is not None else None,
            "adjustment": adjustment,
            "adjustment_ratio": round(adjustment_ratio, 3) if adjustment_ratio else None,
            "merge_status": merge_status,
            "note": note,
            "probe": _probe_media(output_path),
        }

    _update(job_dir, updater)


def record_final_diagnostics(job_dir: str, result: dict) -> None:
    def updater(doc: dict) -> None:
        doc["final"] = {
            "status": result.get("status"),
            "video_path": result.get("video_path"),
            "aspect_ratio": result.get("aspect_ratio"),
            "total_duration": result.get("total_duration"),
            "has_audio": result.get("has_audio"),
            "narrations_succeeded": result.get("narrations_succeeded"),
            "audio_warning": result.get("audio_warning"),
            "probe": _probe_media(result.get("video_path")),
        }

    _update(job_dir, updater)


def rebuild_report(job_dir: str) -> dict:
    lock = _get_lock(job_dir)
    with lock:
        doc = _load_doc(job_dir)
        _refresh_summary(doc)
        _write_doc(job_dir, doc)
        _report_path(job_dir).write_text(_build_report(doc), encoding="utf-8")
        return doc


def _refresh_summary(doc: dict) -> None:
    scene_items = [doc["scenes"][k] for k in sorted(doc["scenes"].keys())]
    render_fallback = []
    render_failed = []
    tts_fallback = []
    tts_failed = []
    assembly_adjusted = []
    scenes_without_audio = []

    for scene in scene_items:
        seq = scene["sequence"]
        render = scene.get("render", {})
        tts = scene.get("tts", {})
        assembly = scene.get("assembly", {})

        if render.get("fallback_used"):
            render_fallback.append(seq)
        if render.get("status") == "error":
            render_failed.append(seq)

        attempts = tts.get("attempts") or []
        if tts.get("status") == "success" and len(attempts) > 1:
            tts_fallback.append(seq)
        if tts.get("status") == "error":
            tts_failed.append(seq)

        if assembly.get("adjustment") in {"stretch", "loop", "trim"}:
            assembly_adjusted.append(seq)
        if assembly.get("probe", {}).get("exists") and not assembly.get("probe", {}).get("has_audio", False):
            scenes_without_audio.append(seq)

    suspected_causes = []
    if render_fallback:
        suspected_causes.append(
            f"AI video generation fell back on scenes {', '.join(_fmt(render_fallback))}. "
            "Quality may reflect fallback motion instead of the primary model."
        )
    if render_failed:
        suspected_causes.append(
            f"Primary video generation failed on scenes {', '.join(_fmt(render_failed))}."
        )
    if tts_fallback:
        suspected_causes.append(
            f"TTS provider fallback happened on scenes {', '.join(_fmt(tts_fallback))}."
        )
    if tts_failed:
        suspected_causes.append(
            f"TTS failed on scenes {', '.join(_fmt(tts_failed))}; those scenes may be silent or music-only."
        )
    if assembly_adjusted:
        suspected_causes.append(
            f"Scene timing was force-adjusted on scenes {', '.join(_fmt(assembly_adjusted))} "
            "(stretch/loop/trim), which can make pacing feel off."
        )
    if scenes_without_audio:
        suspected_causes.append(
            f"Merged scene clips without audio detected on scenes {', '.join(_fmt(scenes_without_audio))}."
        )

    final = doc.get("final") or {}
    final_has_audio = final.get("has_audio")
    if final_has_audio is False:
        suspected_causes.append("Final video has no audio stream.")

    if not suspected_causes and scene_items:
        suspected_causes.append(
            "No pipeline fallback or assembly anomaly detected. "
            "If quality is still poor, the likely cause is prompt/model output quality rather than an execution failure."
        )

    doc["summary"] = {
        "scene_count": len(scene_items),
        "render_fallback_scenes": render_fallback,
        "render_failed_scenes": render_failed,
        "tts_fallback_scenes": tts_fallback,
        "tts_failed_scenes": tts_failed,
        "assembly_adjusted_scenes": assembly_adjusted,
        "scene_clips_without_audio": scenes_without_audio,
        "final_has_audio": final_has_audio,
        "suspected_causes": suspected_causes,
    }


def _fmt(values: list[int]) -> list[str]:
    return [f"{v:02d}" for v in values]


def _build_report(doc: dict) -> str:
    summary = doc.get("summary", {})
    lines = [
        "# Video Diagnostics",
        "",
        f"- Updated: {doc.get('updated_at')}",
        f"- Job dir: `{doc.get('job_dir')}`",
        f"- Scenes: {summary.get('scene_count', 0)}",
        f"- Final audio present: {summary.get('final_has_audio')}",
        "",
        "## Suspected Causes",
    ]

    causes = summary.get("suspected_causes") or ["No issues detected yet."]
    for cause in causes:
        lines.append(f"- {cause}")

    lines.extend(["", "## Scene Breakdown"])

    for key in sorted(doc.get("scenes", {}).keys()):
        scene = doc["scenes"][key]
        meta = scene.get("scene", {})
        render = scene.get("render", {})
        tts = scene.get("tts", {})
        assembly = scene.get("assembly", {})

        lines.extend(
            [
                "",
                f"### Scene {key}",
                f"- Desc: {meta.get('scene_desc') or '[missing]'}",
                f"- Frames: {meta.get('first_frame')} -> {meta.get('last_frame')}",
                f"- Render: {render.get('status')} via {render.get('engine')} "
                f"(fallback={render.get('fallback_used', False)})",
                f"- TTS: {tts.get('status')} via {tts.get('engine')}",
                f"- Assembly: {assembly.get('adjustment', 'none')} / merge={assembly.get('merge_status')}",
            ]
        )

        render_attempts = render.get("attempts") or []
        if render_attempts:
            lines.append("- Render attempts:")
            for attempt in render_attempts:
                msg = attempt.get("message") or ""
                lines.append(
                    f"  - {attempt.get('engine')} {attempt.get('status')} "
                    f"(model={attempt.get('model')}, error_type={attempt.get('error_type')}, message={msg})"
                )

        tts_attempts = tts.get("attempts") or []
        if tts_attempts:
            lines.append("- TTS attempts:")
            for attempt in tts_attempts:
                msg = attempt.get("message") or ""
                lines.append(
                    f"  - {attempt.get('engine')} {attempt.get('status')} "
                    f"(model={attempt.get('model')}, error_type={attempt.get('error_type')}, message={msg})"
                )

    lines.extend(["", "## Final Output", "", "```json", json.dumps(doc.get("final", {}), ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)


def build_attempt_record(engine: str, status: str, result: dict, **extra) -> dict:
    message = result.get("message")
    return {
        "engine": engine,
        "status": status,
        "model": result.get("model") or extra.get("model"),
        "task_id": result.get("task_id"),
        "message": message,
        "error_type": _classify_error(message) if status == "error" else None,
        **extra,
    }
