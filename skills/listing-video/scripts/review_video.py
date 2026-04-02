#!/usr/bin/env python3
"""
Listing Video Agent — Automated Video Quality Review

Extracts key frames from the final video, sends them to Claude Vision
with buyer + creator scoring personas, and returns structured scores.

Design: DIAGNOSTIC ONLY. Never triggers regeneration.
Scores are stored in review.json and included in the delivery notification.
"""

import base64
import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from motion_metrics import compute_motion_metrics, interpret_motion

load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

REVIEW_PROMPT = (
    Path(__file__).parent.parent / "prompts" / "refer" / "auto_review"
).read_text()


# ---------------------------------------------------------------------------
# Frame Extraction
# ---------------------------------------------------------------------------

def extract_frames(
    video_path: str,
    n_frames: int = 6,
    output_dir: str = None,
) -> list[str]:
    """
    Extract N evenly-spaced key frames from the video using ffmpeg.

    Returns list of image file paths.
    """
    duration_cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "json", video_path,
    ]
    probe = subprocess.run(duration_cmd, capture_output=True, text=True)
    duration = 0.0
    if probe.returncode == 0:
        data = json.loads(probe.stdout)
        duration = float(data.get("format", {}).get("duration", 0))

    if duration <= 0:
        return []

    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="reel_review_")

    os.makedirs(output_dir, exist_ok=True)
    frame_paths = []

    # Sample at 0s, 25%, 50%, 75%, 90%, 100% of duration
    timestamps = [0.5]
    if n_frames > 1:
        step = duration / (n_frames - 1)
        timestamps = [min(i * step, duration - 0.5) for i in range(n_frames)]

    for i, ts in enumerate(timestamps):
        frame_path = os.path.join(output_dir, f"frame_{i:02d}.jpg")
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{ts:.2f}",
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "3",
            frame_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and os.path.exists(frame_path):
            frame_paths.append(frame_path)

    return frame_paths


def _encode_image(image_path: str) -> dict:
    """Encode image as Claude Vision content block."""
    with open(image_path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": data,
        },
    }


# ---------------------------------------------------------------------------
# Review Call
# ---------------------------------------------------------------------------

def review_video(
    video_path: str,
    metadata: dict,
    output_dir: str = None,
) -> dict:
    """
    Run automated video review: extract frames → Claude Vision → structured scores.

    Args:
        video_path: Path to the final assembled video.
        metadata: Dict with keys: duration, scene_count, has_audio,
                  narrations (list of text), address, price, agent_name, style.
        output_dir: Where to save review.json. Defaults to video's directory.

    Returns:
        Dict with keys: scores (nested dict), narrative (str), deliverable (bool),
                        overall_score (0-10), top_issues (list), review_path (str).
        On error: {"status": "error", "message": str}
    """
    if not os.path.exists(video_path):
        return {"status": "error", "message": f"Video not found: {video_path}"}

    if output_dir is None:
        output_dir = str(Path(video_path).parent)

    # Extract frames into a temp subdir
    frames_dir = os.path.join(output_dir, "_review_frames")
    frame_paths = extract_frames(video_path, n_frames=6, output_dir=frames_dir)

    if not frame_paths:
        return {"status": "error", "message": "Could not extract frames from video"}

    # Run motion metrics (OpenCV optical flow — lightweight, no GPU)
    _log = logging.getLogger(__name__)
    motion_metrics = {}
    try:
        motion_metrics = compute_motion_metrics(video_path)
        motion_interpretation = interpret_motion(motion_metrics)
        motion_metrics["interpretation"] = motion_interpretation
        _log.info(
            "Motion metrics: dynamic=%.3f (%s), smooth=%.3f (%s), flicker=%.3f (%s)",
            motion_metrics.get("dynamic_degree", 0),
            motion_interpretation.get("dynamic_label", "?"),
            motion_metrics.get("motion_smoothness", 0),
            motion_interpretation.get("smoothness_label", "?"),
            motion_metrics.get("temporal_flickering", 0),
            motion_interpretation.get("flickering_label", "?"),
        )
    except Exception as exc:
        _log.warning("Motion metrics failed (non-blocking): %s", exc)

    # Build metadata summary for the prompt
    narration_texts = [n.get("text", "") for n in metadata.get("narrations", []) if n.get("text")]
    narration_str = " | ".join(narration_texts[:3]) if narration_texts else "(none)"

    meta_block = (
        f"Video metadata:\n"
        f"- Duration: {metadata.get('duration', '?'):.1f}s\n"
        f"- Scene count: {metadata.get('scene_count', '?')}\n"
        f"- Has audio stream: {metadata.get('has_audio', False)}\n"
        f"- Narrations succeeded: {metadata.get('narrations_succeeded', 0)} / "
        f"{metadata.get('scene_count', '?')}\n"
        f"- Address: {metadata.get('address', '[not provided]')}\n"
        f"- Price: {metadata.get('price', '[not provided]')}\n"
        f"- Agent: {metadata.get('agent_name', '[not provided]')}\n"
        f"- Style: {metadata.get('style', 'professional')}\n"
        f"- Sample narrations: {narration_str}\n"
    )

    # G1: Feed motion context into Claude prompt so it can factor in quantitative data
    if motion_metrics:
        interp = motion_metrics.get("interpretation", {})
        meta_block += (
            f"- Motion analysis: dynamic={motion_metrics.get('dynamic_degree', 0):.2f} "
            f"({interp.get('dynamic_label', '?')}), "
            f"smooth={motion_metrics.get('motion_smoothness', 0):.2f} "
            f"({interp.get('smoothness_label', '?')}), "
            f"flicker={motion_metrics.get('temporal_flickering', 0):.2f} "
            f"({interp.get('flickering_label', '?')})\n"
        )
        motion_issue_list = interp.get("issues", [])
        if motion_issue_list:
            meta_block += f"- Motion issues: {'; '.join(motion_issue_list)}\n"

    # Build Claude message content
    content = []

    content.append({
        "type": "text",
        "text": f"{meta_block}\n\nKey frames from the video ({len(frame_paths)} frames):",
    })

    for i, fp in enumerate(frame_paths):
        content.append({"type": "text", "text": f"Frame {i+1}:"})
        content.append(_encode_image(fp))

    content.append({"type": "text", "text": REVIEW_PROMPT})

    # Call Claude
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": content}],
    )
    response_text = response.content[0].text

    # Parse structured scores
    scores = _parse_scores(response_text)
    narrative = _extract_narrative(response_text)

    # Merge motion issues into top_issues if significant
    top_issues = list(scores.get("top_issues", []))
    motion_issues = (motion_metrics.get("interpretation", {}).get("issues", [])
                     if motion_metrics else [])
    for issue in motion_issues:
        if issue not in top_issues:
            top_issues.append(issue)

    # G2: Motion issues adjust overall_score — quantitative metrics must affect scoring.
    # Severe issues (slideshow, jerky, severe flickering) → -1.0 each; mild → -0.5
    _SEVERE_KEYWORDS = {"slideshow", "severe", "jerky"}
    motion_penalty = sum(
        1.0 if any(kw in issue.lower() for kw in _SEVERE_KEYWORDS) else 0.5
        for issue in motion_issues
    )
    claude_score = scores.get("overall_score", 0)
    adjusted_score = round(max(0, claude_score - motion_penalty), 1)
    if motion_penalty > 0:
        _log.info(
            "Motion penalty: -%.1f (claude=%.1f → adjusted=%.1f)",
            motion_penalty, claude_score, adjusted_score,
        )

    review_result = {
        "status": "success",
        "overall_score": adjusted_score,
        "deliverable": scores.get("deliverable", True),
        "scores": scores,
        "motion_metrics": motion_metrics,
        "narrative": narrative,
        "top_issues": top_issues,
        "frames_used": len(frame_paths),
        "video_path": video_path,
    }

    # Save review.json
    review_path = os.path.join(output_dir, "auto_review.json")
    with open(review_path, "w") as f:
        json.dump(review_result, f, indent=2, ensure_ascii=False)
    review_result["review_path"] = review_path

    # Cleanup frame images
    import shutil
    if os.path.exists(frames_dir):
        shutil.rmtree(frames_dir, ignore_errors=True)

    return review_result


def _parse_scores(text: str) -> dict:
    """Extract structured scores from the <scores>...</scores> block."""
    match = re.search(r"<scores>\s*(\{.*?\})\s*</scores>", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return {
        "overall_score": 0,
        "deliverable": True,
        "top_issues": ["Could not parse scores from review output"],
    }


def _extract_narrative(text: str) -> str:
    """Return the review text before the <scores> block."""
    idx = text.find("<scores>")
    if idx > 0:
        return text[:idx].strip()
    return text.strip()


# ---------------------------------------------------------------------------
# Formatting helper for delivery messages
# ---------------------------------------------------------------------------

def format_score_summary(review: dict) -> str:
    """
    Format a short score summary for inclusion in delivery notifications.

    Example output:
      📊 Video Score: 7/10
      🏠 Buyer: Hook 8 | Immersion 6 | Info 7
      🎬 Creator: Pacing 8 | Narrative 7 | Audio-sync 9
      ⚠️ Top issue: No price/agent overlay visible
    """
    if review.get("status") != "success":
        return ""

    overall = review.get("overall_score", 0)
    scores = review.get("scores", {})
    buyer = scores.get("buyer", {})
    creator = scores.get("creator", {})
    issues = review.get("top_issues", [])

    motion = review.get("motion_metrics", {})
    motion_interp = motion.get("interpretation", {})

    lines = [
        f"📊 Video Score: {overall}/10",
        f"🏠 Buyer: Hook {buyer.get('hook', '?')} | Immersion {buyer.get('immersion', '?')} | Info {buyer.get('decision_efficiency', '?')}",
        f"🎬 Creator: Pacing {creator.get('pacing', '?')} | Narrative {creator.get('narrative_arc', '?')} | Audio-sync {creator.get('audio_visual_sync', '?')}",
    ]

    if motion:
        dd = motion.get("dynamic_degree", 0)
        ms = motion.get("motion_smoothness", 0)
        tf = motion.get("temporal_flickering", 0)
        lines.append(
            f"🎥 Motion: dynamic {dd:.0%} ({motion_interp.get('dynamic_label', '?')}) | "
            f"smooth {ms:.0%} ({motion_interp.get('smoothness_label', '?')}) | "
            f"flicker {tf:.0%} ({motion_interp.get('flickering_label', '?')})"
        )

    if issues:
        lines.append(f"⚠️ Top issue: {issues[0]}")

    if not review.get("deliverable", True):
        lines.append("🔴 Quality gate: BELOW THRESHOLD — review recommended before sending")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: review_video.py <video_path> [duration] [has_audio] [scene_count]")
        sys.exit(1)

    video = sys.argv[1]
    meta = {
        "duration": float(sys.argv[2]) if len(sys.argv) > 2 else 0,
        "has_audio": sys.argv[3].lower() == "true" if len(sys.argv) > 3 else True,
        "scene_count": int(sys.argv[4]) if len(sys.argv) > 4 else 0,
        "narrations_succeeded": 0,
        "address": "",
        "price": "",
        "agent_name": "",
    }

    result = review_video(video, meta)
    print(json.dumps(result, indent=2, ensure_ascii=False))
