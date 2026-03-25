#!/usr/bin/env python3
"""
Listing Video Agent — AI Video Generation
Primary: IMA Studio (auto model selection via ima_video_create.py).
Fallback 1: ByteDance Seedance 1.0 Pro via Volcano Ark API.
Fallback 2: Runway Gen-4 Turbo.
"""

import base64
import json
import os
import subprocess
import sys
import time
import requests
from pathlib import Path

ARK_API_BASE = "https://ark.cn-beijing.volces.com/api/v3"
RUNWAY_API_BASE = "https://api.dev.runwayml.com/v1"

# IMA Studio skill script path
IMA_SCRIPT_PATH = os.path.expanduser(
    "~/.openclaw/workspace/skills/ima-video-ai/scripts/ima_video_create.py"
)


def _find_python_for_ima() -> str:
    """Find a Python 3.10+ interpreter for IMA script (requires str|None syntax)."""
    import shutil
    for candidate in ("python3.13", "python3.12", "python3.11", "python3.10"):
        path = shutil.which(candidate)
        if path:
            return path
    # Fallback to python3 — may fail if < 3.10
    return shutil.which("python3") or sys.executable


# ---------------------------------------------------------------------------
# Primary: IMA Studio (subprocess call to ima_video_create.py)
# ---------------------------------------------------------------------------

def generate_ima_clip(
    image_path: str,
    motion_prompt: str,
    duration: int = 5,
    output_path: str = None,
    last_frame_path: str = None,
    aspect_ratio: str = "9:16",
) -> dict:
    """
    Generate a video clip via IMA Studio skill (auto model selection).

    Delegates to ima_video_create.py via subprocess, which handles image
    upload, model routing, task creation, and polling internally.

    Args:
        image_path: Path to first frame image
        motion_prompt: Vivid description of camera motion & scene atmosphere
        duration: Clip duration in seconds
        output_path: Where to save the output video
        last_frame_path: Optional path to last frame image (for scene transitions)
        aspect_ratio: "9:16" for vertical, "16:9" for horizontal

    Returns:
        {"status": "success", "video_path": str, "engine": "ima", "model": str, ...}
    """
    api_key = os.environ.get("IMA_API_KEY")
    if not api_key:
        return {"status": "error", "message": "IMA_API_KEY not set"}

    if not os.path.exists(IMA_SCRIPT_PATH):
        return {"status": "error", "message": f"IMA skill script not found: {IMA_SCRIPT_PATH}"}

    if not output_path:
        output_path = str(Path(image_path).with_suffix(".mp4"))

    # Determine task type
    if last_frame_path and os.path.exists(last_frame_path):
        task_type = "first_last_frame_to_video"
    else:
        task_type = "image_to_video"

    # Build command — IMA script needs Python 3.10+ (uses str|None syntax)
    python_bin = _find_python_for_ima()
    cmd = [
        python_bin, IMA_SCRIPT_PATH,
        "--api-key", api_key,
        "--task-type", task_type,
        "--prompt", motion_prompt,
        "--input-images", image_path,
        "--extra-params", json.dumps({
            "duration": max(5, min(duration, 10)),
            "aspect_ratio": aspect_ratio,
        }),
        "--output-json",
    ]

    # Add last frame for first_last_frame_to_video
    if task_type == "first_last_frame_to_video":
        cmd.extend(["--input-images", last_frame_path])

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "IMA video generation timed out (10 min)"}

    if proc.returncode != 0:
        stderr = proc.stderr[-500:] if proc.stderr else "no stderr"
        return {"status": "error", "message": f"IMA script failed (exit {proc.returncode}): {stderr}"}

    # Parse --output-json result from stdout.
    # The JSON block is multi-line (indent=2) preceded by log lines.
    # Find the last complete JSON object by scanning for lines starting with "{".
    try:
        stdout = proc.stdout.strip()
        ima_result = None
        for i in range(len(stdout) - 1, -1, -1):
            if stdout[i] == "{" and (i == 0 or stdout[i - 1] in ("\n", "\r")):
                try:
                    ima_result = json.loads(stdout[i:])
                    break
                except json.JSONDecodeError:
                    continue
        if ima_result is None:
            return {"status": "error", "message": f"No JSON in IMA output: {stdout[-300:]}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse IMA output: {e}"}

    video_url = ima_result.get("url")
    if not video_url:
        return {"status": "error", "message": f"No video URL in IMA result: {ima_result}"}

    # Download video to output_path
    try:
        video_resp = requests.get(video_url, timeout=120)
        video_resp.raise_for_status()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(video_resp.content)
    except requests.RequestException as e:
        return {"status": "error", "message": f"Failed to download IMA video: {e}"}

    return {
        "status": "success",
        "video_path": output_path,
        "engine": "ima",
        "model": ima_result.get("model_name", ima_result.get("model_id", "auto")),
        "task_id": ima_result.get("task_id"),
        "credit": ima_result.get("credit"),
    }


# ---------------------------------------------------------------------------
# Primary: Seedance 1.0 Pro
# ---------------------------------------------------------------------------

def _encode_image_uri(image_path: str) -> str:
    """Encode an image file as a base64 data URI."""
    with open(image_path, "rb") as f:
        image_b64 = base64.standard_b64encode(f.read()).decode()
    ext = Path(image_path).suffix.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
    media_type = mime.get(ext, "image/jpeg")
    return f"data:{media_type};base64,{image_b64}"


def generate_seedance_clip(
    image_path: str,
    motion_prompt: str,
    duration: int = 5,
    output_path: str = None,
    last_frame_path: str = None,
    model: str = "doubao-seedance-1-0-pro-250528",
    aspect_ratio: str = "9:16",
    resolution: str = "1080p",
) -> dict:
    """
    Generate a video clip from a photo using Seedance 1.0 Pro.

    Supports first-frame-only or first+last frame mode.
    When last_frame_path is provided, Seedance generates a smooth transition
    between the two images, enabling seamless scene chaining.

    Args:
        image_path: Path to first frame image
        motion_prompt: Vivid description of camera motion & scene atmosphere
        duration: Clip duration in seconds (5-10)
        output_path: Where to save the output video
        last_frame_path: Optional path to last frame image (for scene transitions)
        model: Seedance model ID
        aspect_ratio: "9:16" for vertical, "16:9" for horizontal
        resolution: "480p", "720p", or "1080p"

    Returns:
        {"status": "success", "video_path": str, ...}
    """
    api_key = os.environ.get("SEEDDANCE_API_KEY")
    if not api_key:
        return {"status": "error", "message": "SEEDDANCE_API_KEY not set"}

    if not output_path:
        output_path = str(Path(image_path).with_suffix(".mp4"))

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Build content array: first frame + optional last frame + prompt
    first_uri = _encode_image_uri(image_path)
    content = [
        {"type": "image_url", "image_url": {"url": first_uri}},
    ]

    if last_frame_path and os.path.exists(last_frame_path):
        last_uri = _encode_image_uri(last_frame_path)
        content.append({"type": "image_url", "image_url": {"url": last_uri}})

    content.append({"type": "text", "text": motion_prompt})

    # Step 1: Create generation task
    payload = {
        "model": model,
        "content": content,
        "duration": max(5, min(duration, 10)),
        "ratio": aspect_ratio,
        "resolution": resolution,
        "watermark": False,
    }

    try:
        resp = requests.post(
            f"{ARK_API_BASE}/contents/generations/tasks",
            headers=headers,
            json=payload,
            timeout=30,
        )
    except requests.RequestException as e:
        return {"status": "error", "message": f"Seedance API request failed: {e}"}
    if resp.status_code not in (200, 201):
        return {"status": "error", "message": f"Seedance API error {resp.status_code}: {resp.text}"}

    task_id = resp.json().get("id")
    if not task_id:
        return {"status": "error", "message": f"No task ID returned: {resp.text}"}

    # Step 2: Poll for completion (max ~5 min)
    for _ in range(60):
        time.sleep(5)
        try:
            poll = requests.get(
                f"{ARK_API_BASE}/contents/generations/tasks/{task_id}",
                headers=headers,
                timeout=15,
            )
        except requests.RequestException:
            continue
        if poll.status_code != 200:
            continue

        data = poll.json()
        status = data.get("status")

        if status == "succeeded":
            video_url = (data.get("output") or {}).get("video_url")
            if video_url:
                try:
                    video_resp = requests.get(video_url, timeout=60)
                    video_resp.raise_for_status()
                except requests.RequestException as e:
                    return {"status": "error", "message": f"Failed to download Seedance video: {e}"}
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(video_resp.content)
                return {
                    "status": "success",
                    "video_path": output_path,
                    "engine": "seedance",
                    "model": model,
                    "task_id": task_id,
                }
        elif status == "failed":
            error = data.get("error") or data.get("failure") or "unknown"
            return {"status": "error", "message": f"Seedance generation failed: {error}"}

    return {"status": "error", "message": "Timeout waiting for Seedance video generation"}


# ---------------------------------------------------------------------------
# Fallback: Runway Gen-4 Turbo
# ---------------------------------------------------------------------------

def generate_runway_clip(
    image_path: str,
    motion_prompt: str,
    duration: int = 5,
    output_path: str = None,
    model: str = "gen4_turbo",
    aspect_ratio: str = "9:16",
) -> dict:
    """
    Fallback: Generate a video clip from a photo using Runway Gen-4.
    """
    api_key = os.environ.get("RUNWAY_API_KEY")
    if not api_key:
        return {"status": "error", "message": "RUNWAY_API_KEY not set"}

    if not output_path:
        output_path = str(Path(image_path).with_suffix(".mp4"))

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Runway-Version": "2024-11-06",
    }

    with open(image_path, "rb") as f:
        image_b64 = base64.standard_b64encode(f.read()).decode()

    ext = Path(image_path).suffix.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
    media_type = mime.get(ext, "image/jpeg")
    image_uri = f"data:{media_type};base64,{image_b64}"

    # Map common aspect ratios to Runway's expected format
    runway_ratio_map = {
        "9:16": "720:1280",
        "16:9": "1280:720",
        "4:3": "1104:832",
        "3:4": "832:1104",
        "1:1": "960:960",
    }
    runway_ratio = runway_ratio_map.get(aspect_ratio, aspect_ratio)

    payload = {
        "model": model,
        "promptImage": image_uri,
        "promptText": motion_prompt,
        "duration": duration,
        "ratio": runway_ratio,
    }

    try:
        resp = requests.post(f"{RUNWAY_API_BASE}/image_to_video", headers=headers, json=payload, timeout=30)
    except requests.RequestException as e:
        return {"status": "error", "message": f"Runway API request failed: {e}"}
    if resp.status_code != 200:
        return {"status": "error", "message": f"Runway API error {resp.status_code}: {resp.text}"}

    task_id = resp.json().get("id")
    if not task_id:
        return {"status": "error", "message": "No task ID returned"}

    credits_per_sec = {"gen4_turbo": 5, "gen4": 12, "gen4_aleph": 15}.get(model, 5)

    for _ in range(60):
        time.sleep(5)
        try:
            poll = requests.get(f"{RUNWAY_API_BASE}/tasks/{task_id}", headers=headers, timeout=15)
        except requests.RequestException:
            continue
        if poll.status_code != 200:
            continue

        data = poll.json()
        status = data.get("status")

        if status == "SUCCEEDED":
            video_url = data.get("output", [None])[0]
            if video_url:
                try:
                    video_resp = requests.get(video_url, timeout=60)
                    video_resp.raise_for_status()
                except requests.RequestException as e:
                    return {"status": "error", "message": f"Failed to download Runway video: {e}"}
                Path(output_path).write_bytes(video_resp.content)
                return {
                    "status": "success",
                    "video_path": output_path,
                    "engine": "runway",
                    "cost_credits": credits_per_sec * duration,
                    "cost_usd": credits_per_sec * duration * 0.01,
                }
        elif status == "FAILED":
            return {"status": "error", "message": f"Runway failed: {data.get('failure', 'unknown')}"}

    return {"status": "error", "message": "Timeout waiting for Runway video generation"}


# ---------------------------------------------------------------------------
# Motion Prompt Builder — vivid, lively, real-estate-aware
# ---------------------------------------------------------------------------

def build_motion_prompt(room_type: str, highlights: list, style: str = "cinematic") -> str:
    """
    Generate a vivid motion prompt for video generation.

    Designed for real estate: camera movements feel like a professional tour,
    scenes include subtle life cues (people, light play, atmosphere) to make
    the space feel lived-in and aspirational.
    """
    base_prompts = {
        "exterior": (
            "Cinematic drone descending toward the front facade at golden hour, "
            "warm sunlight casting long shadows across the driveway, a gentle breeze "
            "rustling the landscaping, the front door slightly ajar as if welcoming guests"
        ),
        "living": (
            "Slow dolly gliding into the living room, afternoon sunlight streaming through "
            "sheer curtains and painting warm stripes across the floor, a coffee cup on the "
            "side table, the space feeling calm and inviting"
        ),
        "kitchen": (
            "Smooth tracking shot drifting along the countertop, catching the gleam of "
            "polished stone and stainless steel, soft pendant lights glowing above the island, "
            "fresh fruit in a bowl adding a pop of color, warm and appetizing atmosphere"
        ),
        "dining": (
            "Gentle dolly forward toward the dining table, place settings catching the "
            "light from a chandelier overhead, a vase of fresh flowers as centerpiece, "
            "the room radiating warmth and togetherness"
        ),
        "master_bedroom": (
            "Slow push into the master suite, morning light filtering through floor-to-ceiling "
            "windows, crisp white linens on the bed gently catching the breeze from a cracked "
            "window, a serene and private retreat"
        ),
        "bedroom": (
            "Subtle dolly revealing the bedroom, soft daylight illuminating the pillows and "
            "throws, a reading lamp glowing on the nightstand, quiet and restful mood"
        ),
        "master_bath": (
            "Slow lateral tracking across the spa-like master bath, steam gently rising from "
            "the freestanding tub, natural stone textures catching diffused skylight, a plush "
            "towel draped over the edge, luxurious and tranquil"
        ),
        "bathroom": (
            "Gentle reveal pulling back to show the full bathroom, clean tile gleaming under "
            "vanity lighting, a folded towel and small plant on the counter adding a lived-in touch"
        ),
        "backyard": (
            "Slow cinematic pull-back from patio level, revealing the full backyard landscape "
            "at golden hour, string lights just beginning to glow, mature trees framing the sky, "
            "a couple of lounge chairs positioned for relaxation"
        ),
        "pool": (
            "Smooth tracking shot skimming across the pool surface, turquoise water reflecting "
            "afternoon sunlight in dancing patterns, a towel draped on a lounger poolside, "
            "palm fronds swaying gently in the breeze"
        ),
        "aerial": (
            "Slow descending aerial establishing shot, the property emerging from the wider "
            "neighborhood context, rooftops and greenery stretching to the horizon, the lot's "
            "scale and positioning becoming clear as the camera lowers"
        ),
        "garage": (
            "Slow push into the spacious garage, overhead lights revealing clean epoxy floors "
            "and organized storage, enough room for two cars with workspace to spare"
        ),
        "gym": (
            "Tracking shot across the fitness area, a resident mid-workout on the treadmill, "
            "mirrors reflecting rows of equipment, energetic yet polished atmosphere, "
            "natural light streaming through high windows"
        ),
        "lounge": (
            "Gentle dolly through the communal lounge, a small group chatting on modern sofas, "
            "floor-to-ceiling windows framing the city view, warm ambient lighting and curated "
            "artwork on the walls"
        ),
        "office": (
            "Slow push into the home office, a desk lamp casting a focused warm glow, "
            "bookshelves lined with volumes, natural light from a side window, "
            "a productive and inspiring workspace"
        ),
        "laundry": (
            "Gentle reveal of the laundry room, neatly stacked linens on open shelving, "
            "modern appliances side by side, bright overhead lighting, practical and tidy"
        ),
        "floorplan": (
            "The flat floor plan lifts and transforms into a three-dimensional walkthrough, "
            "walls rising from the blueprint, furniture materializing in each room, "
            "camera gliding through the imagined living space"
        ),
    }

    prompt = base_prompts.get(
        room_type,
        "Slow cinematic dolly forward, natural lighting gently shifting across the space, "
        "inviting and well-composed atmosphere"
    )

    # Weave in photo-specific highlights
    if highlights:
        detail = ", ".join(highlights[:2])
        prompt += f", highlighting {detail}"

    # Style / mood modifiers
    if style == "elegant":
        prompt += ", elegant and luxurious palette, soft warm tones, subtle lens flare"
    elif style == "energetic":
        prompt += ", vibrant and dynamic energy, bright saturated colors, lively pace"
    elif style == "modern":
        prompt += ", clean minimalist aesthetic, cool neutral tones, crisp lines"

    # Quality anchors (important for Seedance prompt adherence)
    prompt += ", photorealistic, high quality, cinematic color grading, no artifacts, no distortion"

    return prompt


# ---------------------------------------------------------------------------
# Orchestrator: generate all clips (Seedance primary → Runway fallback)
# ---------------------------------------------------------------------------

def generate_all_clips(
    storyboard: dict,
    photo_dir: str,
    output_dir: str,
    aspect_ratio: str = "9:16",
    style: str = "professional",
    progress_callback=None,
) -> list[dict]:
    """
    Generate all AI video clips defined in the storyboard.

    Pipeline: Seedance 1.0 Pro (primary) → Runway Gen-4 Turbo (fallback).
    """
    from job_logger import get_logger, log_step_start, log_step_end, log_clip_result

    logger = get_logger()
    os.makedirs(output_dir, exist_ok=True)
    results = []

    ai_clips = [s for s in storyboard["storyboard"] if s["render_type"] == "ai_video"]
    total = len(ai_clips)

    log_step_start("ai_video_generation", {
        "total_clips": total,
        "aspect_ratio": aspect_ratio,
        "style": style,
    })

    for i, clip in enumerate(ai_clips, 1):
        photo_path = os.path.join(photo_dir, f"photo_{clip['photo_index']}.jpg")
        output_path = os.path.join(output_dir, f"ai_clip_{clip['sequence']:02d}.mp4")

        if progress_callback:
            progress_callback(f"Generating AI clip {i}/{total}: {clip.get('motion', 'cinematic')}...")

        # Build motion prompt
        motion_prompt = clip.get("motion_prompt") or build_motion_prompt(
            room_type=clip.get("room_type", "other"),
            highlights=clip.get("highlights", []),
            style=style,
        )

        duration = clip.get("timestamp_end", 5) - clip.get("timestamp_start", 0)
        duration = min(max(duration, 5), 10)

        logger.debug(
            "Clip %d/%d: room=%s  duration=%ds  prompt=%.80s...",
            i, total, clip.get("room_type", "?"), duration, motion_prompt,
        )

        # Primary: IMA Studio
        result = generate_ima_clip(
            image_path=photo_path,
            motion_prompt=motion_prompt,
            duration=duration,
            output_path=output_path,
            aspect_ratio=aspect_ratio,
        )

        # Fallback 1: Seedance
        if result["status"] == "error":
            logger.warning("IMA failed for clip %d: %s", i, result["message"])
            if progress_callback:
                progress_callback(f"IMA failed, trying Seedance fallback...")
            result = generate_seedance_clip(
                image_path=photo_path,
                motion_prompt=motion_prompt,
                duration=duration,
                output_path=output_path,
                aspect_ratio=aspect_ratio,
            )

        # Fallback 2: Runway
        if result["status"] == "error":
            logger.warning("Seedance failed for clip %d: %s", i, result["message"])
            if progress_callback:
                progress_callback(f"Seedance failed, trying Runway fallback...")
            result = generate_runway_clip(
                image_path=photo_path,
                motion_prompt=motion_prompt,
                duration=duration,
                output_path=output_path,
                aspect_ratio=aspect_ratio,
            )

        result["sequence"] = clip["sequence"]
        results.append(result)
        log_clip_result(i, total, result)

    succeeded = sum(1 for r in results if r.get("status") == "success")
    log_step_end("ai_video_generation", {
        "status": "success" if succeeded > 0 else "error",
        "succeeded": succeeded,
        "failed": total - succeeded,
    })

    return results


# ---------------------------------------------------------------------------
# V2 Pipeline: scene-plan-driven generation (first+last frame, AI prompts)
# ---------------------------------------------------------------------------

def generate_all_clips_v2(
    scene_plan: list[dict],
    photo_dir: str,
    output_dir: str,
    aspect_ratio: str = "9:16",
    progress_callback=None,
) -> list[dict]:
    """
    Generate all AI video clips from an AI scene plan.

    This is the V2 pipeline that uses:
    - First+last frame pairs for seamless scene transitions
    - AI-written prompts (scene_plan[i]["motion_prompt"]) instead of templates
    - Per-scene narration-driven duration

    Args:
        scene_plan: List of scene dicts from plan_scenes + write_video_prompts.
                    Each dict must have:
                      - sequence: int
                      - first_frame: str (filename)
                      - last_frame: str (filename, can equal first_frame)
                      - motion_prompt: str (AI-written or template fallback)
                      - text_narration: str (for duration estimation)
        photo_dir: Directory containing the source photos
        output_dir: Directory to save generated clips
        aspect_ratio: Video aspect ratio

    Returns:
        List of result dicts per clip
    """
    from job_logger import get_logger, log_step_start, log_step_end, log_clip_result

    logger = get_logger()
    os.makedirs(output_dir, exist_ok=True)
    results = []
    total = len(scene_plan)

    log_step_start("ai_video_generation_v2", {
        "total_scenes": total,
        "aspect_ratio": aspect_ratio,
        "mode": "first+last_frame",
    })

    for i, scene in enumerate(scene_plan, 1):
        seq = scene["sequence"]
        first_frame = scene["first_frame"]
        last_frame = scene.get("last_frame", first_frame)
        narration = scene.get("text_narration", "")

        first_path = os.path.join(photo_dir, first_frame)
        last_path = os.path.join(photo_dir, last_frame) if last_frame != first_frame else None
        output_path = os.path.join(output_dir, f"scene_{seq:02d}.mp4")

        if progress_callback:
            progress_callback(f"Generating scene {i}/{total}: {scene.get('scene_desc', '')[:40]}...")

        # Priority: cinematic_motion prompt > write_prompts prompt > template fallback
        motion_prompt = (
            scene.get("ai_motion_prompt")
            or scene.get("motion_prompt")
            or build_motion_prompt(room_type="other", highlights=[], style="cinematic")
        )

        # Estimate duration from narration (~3.5 words/sec), clamp to 5-10s
        if narration:
            word_count = len(narration.split())
            estimated_dur = max(5, min(int(word_count / 3.5) + 1, 10))
        else:
            estimated_dur = 5

        logger.debug(
            "Scene %d/%d: first=%s  last=%s  dur=%ds  prompt=%.80s...",
            i, total, first_frame, last_frame, estimated_dur, motion_prompt,
        )

        # Primary: IMA Studio (supports first+last frame)
        result = generate_ima_clip(
            image_path=first_path,
            motion_prompt=motion_prompt,
            duration=estimated_dur,
            output_path=output_path,
            last_frame_path=last_path,
            aspect_ratio=aspect_ratio,
        )

        # Fallback 1: Seedance with first+last frame
        if result["status"] == "error":
            logger.warning("IMA failed for scene %d: %s", i, result["message"])
            if progress_callback:
                progress_callback(f"IMA failed, trying Seedance fallback...")
            result = generate_seedance_clip(
                image_path=first_path,
                motion_prompt=motion_prompt,
                duration=estimated_dur,
                output_path=output_path,
                last_frame_path=last_path,
                aspect_ratio=aspect_ratio,
            )

        # Fallback 2: Runway (single frame only)
        if result["status"] == "error":
            logger.warning("Seedance failed for scene %d: %s", i, result["message"])
            if progress_callback:
                progress_callback(f"Seedance failed, trying Runway fallback...")
            result = generate_runway_clip(
                image_path=first_path,
                motion_prompt=motion_prompt,
                duration=estimated_dur,
                output_path=output_path,
                aspect_ratio=aspect_ratio,
            )

        result["sequence"] = seq
        results.append(result)
        log_clip_result(i, total, result)

    succeeded = sum(1 for r in results if r.get("status") == "success")
    log_step_end("ai_video_generation_v2", {
        "status": "success" if succeeded > 0 else "error",
        "succeeded": succeeded,
        "failed": total - succeeded,
    })

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate AI video clips")
    subparsers = parser.add_subparsers(dest="command")

    # Single clip
    single = subparsers.add_parser("single", help="Generate single AI clip")
    single.add_argument("image", help="Input image path")
    single.add_argument("prompt", help="Motion prompt")
    single.add_argument("--duration", type=int, default=5, help="Duration in seconds")
    single.add_argument("--output", default=None, help="Output video path")
    single.add_argument("--last-frame", default=None, help="Last frame image path")
    single.add_argument("--aspect-ratio", default="9:16", help="Aspect ratio")

    # Batch from scene plan
    batch = subparsers.add_parser("batch", help="Generate all clips from scene plan")
    batch.add_argument("--scene-plan-file", required=True, help="Scene plan JSON file")
    batch.add_argument("--photo-dir", required=True, help="Photo directory")
    batch.add_argument("--output-dir", required=True, help="Output directory")
    batch.add_argument("--aspect-ratio", default="9:16", help="Aspect ratio")

    args = parser.parse_args()

    if args.command == "single":
        result = generate_ima_clip(
            image_path=args.image, motion_prompt=args.prompt,
            duration=args.duration, output_path=args.output,
            last_frame_path=args.last_frame, aspect_ratio=args.aspect_ratio,
        )
        if result["status"] == "error":
            result = generate_seedance_clip(
                image_path=args.image, motion_prompt=args.prompt,
                duration=args.duration, output_path=args.output,
                last_frame_path=args.last_frame, aspect_ratio=args.aspect_ratio,
            )
        if result["status"] == "error":
            result = generate_runway_clip(
                image_path=args.image, motion_prompt=args.prompt,
                duration=args.duration, output_path=args.output,
                aspect_ratio=args.aspect_ratio,
            )
        print(json.dumps(result, indent=2))

    elif args.command == "batch":
        scene_plan = json.loads(Path(args.scene_plan_file).read_text())
        results = generate_all_clips_v2(
            scene_plan=scene_plan, photo_dir=args.photo_dir,
            output_dir=args.output_dir, aspect_ratio=args.aspect_ratio,
        )
        print(json.dumps(results, indent=2))

    else:
        parser.print_help()
        sys.exit(1)
