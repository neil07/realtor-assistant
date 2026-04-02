#!/usr/bin/env python3
"""
Listing Video Agent — AI Video Generation
Primary: IMA Studio API (Kling, WAN, Hailuo, etc.)
Fallback: Local Ken Burns slideshow (ffmpeg).
"""

import json
import os
import sys
from pathlib import Path

# Ken Burns fallback motion cycle
_KEN_BURNS_MOTIONS = ["slow_push", "pull_back", "slide_left", "slide_right"]

# ---------------------------------------------------------------------------
# Per-clip quality gate — motion-based, no API cost
# Thresholds derived from motion_metrics.interpret_motion() bands
# ---------------------------------------------------------------------------

_CLIP_MIN_DYNAMIC = 0.10       # Below → "PPT feel", trigger re-render
_CLIP_MIN_SMOOTHNESS = 0.35    # Below → "jerky/distorted", trigger re-render
_CLIP_MAX_FLICKERING = 0.15    # Above → "flickering", trigger re-render
_CLIP_HOPELESS_DYNAMIC = 0.05  # Below → give up on AI, use Ken Burns


def _assess_clip_quality(clip_path: str) -> dict:
    """Run motion metrics on a single rendered clip. Returns metrics dict."""
    from motion_metrics import compute_motion_metrics
    try:
        return compute_motion_metrics(clip_path)
    except Exception:
        return {"dynamic_degree": 0.0, "motion_smoothness": 1.0, "temporal_flickering": 0.0, "frame_count": 0}


def _clip_needs_rerender(metrics: dict) -> bool:
    """Check if a clip's motion metrics fall below quality thresholds (3-dim)."""
    return (
        metrics.get("dynamic_degree", 0) < _CLIP_MIN_DYNAMIC
        or metrics.get("motion_smoothness", 1) < _CLIP_MIN_SMOOTHNESS
        or metrics.get("temporal_flickering", 0) > _CLIP_MAX_FLICKERING
    )


def _clip_is_hopeless(metrics: dict) -> bool:
    """Check if a clip is so static that Ken Burns fallback is preferable."""
    return metrics.get("dynamic_degree", 0) < _CLIP_HOPELESS_DYNAMIC

# ---------------------------------------------------------------------------
# IMA Studio — primary engine
# ---------------------------------------------------------------------------

def _crop_to_aspect_ratio(image_path: str, target_w: int, target_h: int) -> str:
    """
    Center-crop an image to the target aspect ratio and return a temp file path.

    IMA Kling generates output at the input image's native ratio regardless of
    the aspect_ratio API parameter. Pre-cropping to 9:16 forces portrait output.
    Returns the original path unchanged if PIL is unavailable or crop is not needed.
    """
    import tempfile
    try:
        from PIL import Image
    except ImportError:
        return image_path

    img = Image.open(image_path)
    src_w, src_h = img.size
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if abs(src_ratio - target_ratio) < 0.02:
        return image_path  # Already correct ratio

    if src_ratio > target_ratio:
        # Image is wider than target — crop sides
        new_w = int(src_h * target_ratio)
        left = (src_w - new_w) // 2
        img = img.crop((left, 0, left + new_w, src_h))
    else:
        # Image is taller than target — crop top/bottom
        new_h = int(src_w / target_ratio)
        top = (src_h - new_h) // 2
        img = img.crop((0, top, src_w, top + new_h))

    suffix = Path(image_path).suffix or ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        tmp_path = f.name
    img.save(tmp_path, quality=95)
    return tmp_path


def generate_ima_clip(
    image_path: str,
    motion_prompt: str,
    duration: int = 5,
    output_path: str = None,
    aspect_ratio: str = "9:16",
    model_id: str = None,
) -> dict:
    """
    Generate a video clip using IMA Studio API (image-to-video).

    Pre-crops input image to the target aspect ratio so IMA outputs portrait
    clips for 9:16 (IMA ignores the aspect_ratio API parameter in practice).
    """
    from ima_client import generate_video_clip

    if not output_path:
        output_path = str(Path(image_path).with_suffix(".mp4"))

    if not model_id:
        model_id = os.environ.get("IMA_VIDEO_MODEL", "wan2.6-i2v")

    # Pre-crop to target aspect ratio
    target_w, target_h = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
    cropped = _crop_to_aspect_ratio(image_path, target_w, target_h)
    tmp_files = [cropped] if cropped != image_path else []

    try:
        return generate_video_clip(
            image_path=cropped,
            motion_prompt=motion_prompt,
            output_path=output_path,
            duration=duration,
            aspect_ratio=aspect_ratio,
            model_id=model_id,
        )
    finally:
        for tmp in tmp_files:
            try:
                os.remove(tmp)
            except OSError:
                pass


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

    # Quality anchors
    prompt += ", photorealistic, high quality, cinematic color grading, no artifacts, no distortion"

    return prompt


# ---------------------------------------------------------------------------
# Orchestrator: generate all clips (IMA primary → Ken Burns fallback)
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

    Pipeline: IMA Studio (primary) → Ken Burns slideshow (fallback).
    """
    from job_logger import get_logger, log_clip_result, log_step_end, log_step_start

    logger = get_logger()
    os.makedirs(output_dir, exist_ok=True)
    results = []

    ai_clips = [s for s in storyboard["storyboard"] if s["render_type"] == "ai_video"]
    total = len(ai_clips)

    log_step_start("ai_video_generation", {
        "total_clips": total,
        "aspect_ratio": aspect_ratio,
        "style": style,
        "engine": "ima",
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

        # Fallback: Ken Burns slideshow (local ffmpeg, no API needed)
        if result["status"] == "error":
            logger.warning("IMA failed for clip %d: %s", i, result["message"])
            if progress_callback:
                progress_callback("Using Ken Burns slideshow fallback...")
            from render_slideshow import create_ken_burns_clip

            motion = _KEN_BURNS_MOTIONS[(i - 1) % len(_KEN_BURNS_MOTIONS)]
            resolution = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
            result = create_ken_burns_clip(
                image_path=photo_path,
                output_path=output_path,
                duration=float(duration),
                motion=motion,
                resolution=resolution,
            )
            if result.get("status") == "success":
                result["engine"] = "ken_burns"

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
    narration_durations: dict[int, float] | None = None,
) -> list[dict]:
    """
    Generate all AI video clips from an AI scene plan — fully parallel.

    All IMA tasks are submitted concurrently (one thread per scene) and polled
    simultaneously. Total wall-clock time ≈ slowest single clip (~3-5 min),
    not N × clip time.

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
        narration_durations: Optional {sequence: actual_audio_seconds} from TTS.
                             When provided, clips are generated at the exact audio
                             duration — eliminates stretch/slow-motion artifacts.

    Returns:
        List of result dicts per clip, sorted by sequence.
    """
    import math
    from concurrent.futures import ThreadPoolExecutor, as_completed

    import video_diagnostics
    from job_logger import get_logger, log_clip_result, log_step_end, log_step_start

    logger = get_logger()
    os.makedirs(output_dir, exist_ok=True)
    total = len(scene_plan)
    job_dir = str(Path(output_dir).parent)

    video_diagnostics.record_scene_plan(job_dir, scene_plan)

    log_step_start("ai_video_generation_v2", {
        "total_scenes": total,
        "aspect_ratio": aspect_ratio,
        "mode": "parallel_image_to_video",
        "engine": "ima",
    })

    def _generate_one(scene: dict) -> dict:
        """Generate one clip: IMA primary → Ken Burns fallback on failure."""
        seq = scene["sequence"]
        first_frame = scene["first_frame"]
        last_frame = scene.get("last_frame", first_frame)
        narration = scene.get("text_narration", "")

        first_path = os.path.join(photo_dir, first_frame)
        output_path = os.path.join(output_dir, f"scene_{seq:02d}.mp4")

        motion_prompt = scene.get("motion_prompt") or build_motion_prompt(
            room_type="other", highlights=[], style="cinematic",
        )

        if narration_durations and seq in narration_durations:
            estimated_dur = max(3, min(int(math.ceil(narration_durations[seq])), 8))
        elif narration:
            word_count = len(narration.split())
            estimated_dur = max(4, min(int(word_count / 3.0) + 1, 6))
        else:
            estimated_dur = 5

        # wan2.6-i2v accepts any duration; kling requires 5 or 10.
        # Snap only when needed (checked inside generate_ima_clip via model_id).
        ima_dur = estimated_dur

        logger.info(
            "Scene %02d submit: first=%s  dur=%ds  prompt=%.60s...",
            seq, first_frame, ima_dur, motion_prompt,
        )

        result = generate_ima_clip(
            image_path=first_path,
            motion_prompt=motion_prompt,
            duration=ima_dur,
            output_path=output_path,
            aspect_ratio=aspect_ratio,
        )

        attempts = [video_diagnostics.build_attempt_record(
            engine="ima",
            status=result.get("status", "error"),
            result=result,
            requested_duration=estimated_dur,
            aspect_ratio=aspect_ratio,
            first_frame=first_frame,
            last_frame=last_frame,
        )]

        # ── Per-clip quality gate: check IMA output, selective re-render ──
        if result["status"] == "success":
            clip_path = result.get("video_path", output_path)
            metrics_v1 = _assess_clip_quality(clip_path)
            attempts[-1]["motion_metrics"] = metrics_v1

            if _clip_needs_rerender(metrics_v1):
                logger.info(
                    "Scene %02d quality gate: dd=%.3f ms=%.3f tf=%.3f — re-rendering...",
                    seq,
                    metrics_v1.get("dynamic_degree", 0),
                    metrics_v1.get("motion_smoothness", 1),
                    metrics_v1.get("temporal_flickering", 0),
                )

                # Render v2 to a separate path, then compare
                v2_path = output_path.replace(".mp4", "_qg.mp4")
                result_v2 = generate_ima_clip(
                    image_path=first_path,
                    motion_prompt=motion_prompt,
                    duration=ima_dur,
                    output_path=v2_path,
                    aspect_ratio=aspect_ratio,
                )

                v2_attempt = video_diagnostics.build_attempt_record(
                    engine="ima",
                    status=result_v2.get("status", "error"),
                    result=result_v2,
                    requested_duration=estimated_dur,
                    aspect_ratio=aspect_ratio,
                    first_frame=first_frame,
                    last_frame=last_frame,
                    reason="quality_gate_rerender",
                )

                best_metrics = metrics_v1

                if result_v2.get("status") == "success":
                    metrics_v2 = _assess_clip_quality(v2_path)
                    v2_attempt["motion_metrics"] = metrics_v2

                    dd_v1 = metrics_v1.get("dynamic_degree", 0)
                    dd_v2 = metrics_v2.get("dynamic_degree", 0)

                    if dd_v2 >= dd_v1:
                        # v2 wins (or tie — prefer fresher render)
                        os.replace(v2_path, output_path)
                        result = result_v2
                        result["video_path"] = output_path
                        best_metrics = metrics_v2
                        logger.info("Scene %02d: v2 wins (dd=%.3f vs %.3f)", seq, dd_v2, dd_v1)
                    else:
                        # v1 wins, discard v2
                        try:
                            os.remove(v2_path)
                        except OSError:
                            pass
                        best_metrics = metrics_v1
                        logger.info("Scene %02d: v1 wins (dd=%.3f vs %.3f)", seq, dd_v1, dd_v2)
                else:
                    # v2 IMA failed, keep v1
                    logger.info("Scene %02d: v2 IMA failed, keeping v1", seq)

                attempts.append(v2_attempt)

                # If best version is still hopeless → trigger Ken Burns fallback
                if _clip_is_hopeless(best_metrics):
                    logger.warning(
                        "Scene %02d: best dd=%.3f < %.3f — Ken Burns fallback",
                        seq,
                        best_metrics.get("dynamic_degree", 0),
                        _CLIP_HOPELESS_DYNAMIC,
                    )
                    result["status"] = "quality_fallback"

        # Fallback: Ken Burns if IMA fails or quality is hopeless
        if result.get("status") in ("error", "quality_fallback"):
            reason = (
                "quality below threshold"
                if result.get("status") == "quality_fallback"
                else result.get("message", "unknown error")
            )
            logger.warning(
                "Scene %02d falling back to Ken Burns: %s", seq, reason,
            )
            from render_slideshow import create_ken_burns_clip

            motion = _KEN_BURNS_MOTIONS[(seq - 1) % len(_KEN_BURNS_MOTIONS)]
            resolution = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
            result = create_ken_burns_clip(
                image_path=first_path,
                output_path=output_path,
                duration=float(estimated_dur),
                motion=motion,
                resolution=resolution,
            )
            if result.get("status") == "success":
                result["engine"] = "ken_burns"

            attempts.append(video_diagnostics.build_attempt_record(
                engine="ken_burns",
                status=result.get("status", "error"),
                result=result,
                requested_duration=estimated_dur,
                aspect_ratio=aspect_ratio,
                first_frame=first_frame,
                last_frame=last_frame,
            ))

        # Record diagnostics once, after potential fallback
        video_diagnostics.record_render_diagnostics(
            job_dir=job_dir,
            sequence=seq,
            requested_duration=estimated_dur,
            attempts=attempts,
            final_result=result,
        )

        result["sequence"] = seq
        result["attempts"] = attempts
        logger.info("Scene %02d done: engine=%s  path=%s",
                     seq, result.get("engine", "?"), result.get("video_path", ""))
        return result

    results: list[dict] = []
    # IMA is IO-bound, GIL is not a bottleneck. Cap at 6 to avoid
    # overwhelming IMA API rate limits and local resource exhaustion.
    max_workers = min(total, int(os.environ.get("RENDER_MAX_WORKERS", "6")))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_generate_one, s): s["sequence"] for s in scene_plan}
        completed = 0
        for future in as_completed(futures):
            seq = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                logger.error("Scene %02d crashed: %s", seq, exc)
                result = {"sequence": seq, "status": "error", "message": str(exc)}
            completed += 1
            results.append(result)
            log_clip_result(completed, total, result)
            if progress_callback:
                progress_callback(f"Scene {seq:02d} done ({completed}/{total})")

    # as_completed order is non-deterministic — sort for downstream assembly
    results.sort(key=lambda r: r["sequence"])

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
    if len(sys.argv) < 3:
        print("Usage: render_ai_video.py <image_path> <motion_prompt> [duration] [output_path]")
        sys.exit(1)

    result = generate_ima_clip(
        image_path=sys.argv[1],
        motion_prompt=sys.argv[2],
        duration=int(sys.argv[3]) if len(sys.argv) > 3 else 5,
        output_path=sys.argv[4] if len(sys.argv) > 4 else None,
    )
    print(json.dumps(result, indent=2))
