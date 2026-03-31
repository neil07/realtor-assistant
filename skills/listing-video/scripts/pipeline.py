#!/usr/bin/env python3
"""
Reel Agent — End-to-End Pipeline Orchestrator

Chains 5 Skills to produce a listing video from photos:
  Skills 1-3 (Creative) → Skill 4 (Produce) → Skill 5 (Learn)

Skills 1-3 are handled by a single Opus call in creative_director.py:
  - Photo analysis, voiceover script, scene planning, and motion prompts
    are generated in one pass so Claude sees all photos simultaneously.

Usage:
  python pipeline.py <photo_dir> --address "123 Oak St" --price "$500K"
"""

import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Add scripts dir to path for local imports
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

import assemble_final
import creative_director
import generate_voice
import job_logger
import profile_manager
import render_ai_video


def run_pipeline(
    photo_dir: str,
    address: str = "[TBD]",
    price: str = "[TBD]",
    agent_phone: str = "",
    agent_name: str = "",
    style: str = "professional",
    music_preference: str = "modern",
    aspect_ratio: str = "9:16",
    language: str = "en",
    output_dir: str = None,
    progress_callback=None,
) -> dict:
    """
    Run the full video pipeline.

    Args:
        photo_dir: Directory containing listing photos
        address: Property address
        price: Asking price
        agent_phone: Agent phone (for profile lookup)
        agent_name: Agent name (for CTA)
        style: Video style (energetic/elegant/professional)
        music_preference: Music style (modern/piano/acoustic)
        aspect_ratio: Output format ("9:16" or "16:9")
        language: Narration language
        output_dir: Where to save output (default: photo_dir/../output/<timestamp>)
        progress_callback: Optional fn(step, message) for progress updates

    Returns:
        Result dict with video_path, caption, cost, duration, etc.
    """
    start_time = time.time()

    def progress(step, msg):
        if progress_callback:
            progress_callback(step, msg)
        print(f"  [{step}] {msg}")

    # Setup output directory
    if not output_dir:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = str(Path(photo_dir).parent / "output" / timestamp)
    os.makedirs(output_dir, exist_ok=True)

    # Init job logger
    job_logger.init_job_log(output_dir)

    # Load profile if we have a phone number
    user_profile = None
    agent_brief = None
    if agent_phone:
        user_profile = profile_manager.get_profile(agent_phone)
        if user_profile:
            style = user_profile.get("style", style)
            music_preference = user_profile.get("music_preference", music_preference)
            agent_name = user_profile.get("name", agent_name)
            progress("profile", f"Loaded profile for {agent_name}")
        # Load (or auto-initialize) the agent's personal Skill brief
        agent_brief = profile_manager.get_skill_brief(agent_phone, "video")
        progress("profile", f"Skill brief loaded for {agent_phone}")

    # ─── Skills 1-3: 创意决策 (Creative Direction) ────────────────────
    # Single Opus call: sees all photos at once → photo analysis + voiceover
    # script + scene sequence + motion prompts produced in one coherent pass.
    progress("creative", "Generating creative direction (Opus)...")
    job_logger.log_step_start("creative_director", {"photo_dir": photo_dir})

    photo_paths = sorted(
        os.path.join(photo_dir, f)
        for f in os.listdir(photo_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    )

    if not photo_paths:
        return {"error": "No photos found in directory"}

    creative = creative_director.run(
        photo_paths=photo_paths,
        address=address,
        price=price,
        output_dir=output_dir,
        agent_name=agent_name,
        agent_phone=agent_phone,
        style=style,
        language=language,
        custom_brief=agent_brief,
    )

    script = creative["script"]
    scenes = creative["scenes"]

    progress(
        "creative",
        f"{len(photo_paths)} photos → {len(scenes)} scenes | "
        f"{script['word_count']} words | "
        f"{creative['input_tokens']}↑ {creative['output_tokens']}↓ tokens",
    )
    job_logger.log_step_end("creative_director", {
        "photo_count": len(photo_paths),
        "scene_count": len(scenes),
        "word_count": script["word_count"],
        "input_tokens": creative.get("input_tokens"),
        "output_tokens": creative.get("output_tokens"),
    })

    # ─── Skill 4: 生成 (Produce) ──────────────────────────────────────
    progress("skill_4", "Generating AI video clips...")
    job_logger.log_step_start("skill_4_produce", {"style": style})

    clips_dir = os.path.join(output_dir, "clips")
    voice_dir = os.path.join(output_dir, "voice")
    os.makedirs(clips_dir, exist_ok=True)
    os.makedirs(voice_dir, exist_ok=True)

    # 4a. Per-scene voiceover FIRST — get actual audio durations before rendering
    # This lets video clips be generated at the exact narration length (no stretch).
    voice_id = None
    if user_profile and user_profile.get("voice_clone"):
        voice_id = user_profile["voice_clone"]

    narrations = generate_voice.generate_scene_voiceovers(
        scenes=scenes,
        output_dir=voice_dir,
        voice_id=voice_id,
        style=style,
    )
    progress("skill_4", f"Generated {len(narrations)} voiceover segments")

    # Build sequence → actual audio duration map for clip generation
    narration_durations = {
        n["sequence"]: n["duration"]
        for n in narrations
        if n.get("status") == "success" and n.get("duration", 0) > 0
    }

    # 4b. AI video clips — pass actual narration durations so Ken Burns
    # (and IMA when available) generates at exactly the right length.
    clips = render_ai_video.generate_all_clips_v2(
        scene_plan=scenes,
        photo_dir=photo_dir,
        output_dir=clips_dir,
        aspect_ratio=aspect_ratio,
        narration_durations=narration_durations,
    )
    progress("skill_4", f"Rendered {len(clips)} video clips")

    # 4c. Background music (IMA AI → local file fallback)
    progress("skill_4", "Generating background music...")
    music_path = _get_music(output_dir, music_preference, style)

    # 4d. Final assembly
    progress("skill_4", "Assembling final video...")
    result = assemble_final.full_assembly_v2(
        scene_plan=scenes,
        clips_dir=clips_dir,
        narrations=narrations,
        music_path=str(music_path) if music_path else "",
        output_dir=output_dir,
        listing_id=address.replace(" ", "_")[:30],
        aspect_ratio=aspect_ratio,
        address=address if address != "[TBD]" else None,
        price=price or None,
        agent_name=agent_name or None,
        agent_phone=agent_phone or None,
    )

    video_path = result.get("video_path", "")
    progress("skill_4", f"Video ready: {video_path}")

    job_logger.log_step_end("skill_4_produce", {
        "clips": len(clips),
        "narrations": len(narrations),
        "video_path": video_path,
    })

    # ─── Skill 5: 复盘 (Learn) ────────────────────────────────────────
    elapsed = time.time() - start_time
    progress("skill_5", "Reviewing video quality...")

    # Quality review — score video and flag if below delivery threshold
    _DELIVERY_THRESHOLD = 6.5
    review_result = {}
    if video_path and os.path.exists(video_path):
        try:
            import subprocess
            import review_video as reviewer

            # Probe actual video duration via ffprobe (reliable, avoids using
            # pipeline elapsed time which is 10-100x longer than the clip)
            _dur = 0.0
            try:
                _probe = subprocess.check_output(
                    ["ffprobe", "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                    stderr=subprocess.DEVNULL,
                )
                _dur = float(_probe.decode().strip())
            except Exception:
                pass

            review_meta = {
                "duration": _dur,
                "has_audio": result.get("has_audio", True),
                "scene_count": len(scenes),
                "narrations_succeeded": len(narrations),
                "address": address,
                "price": price,
                "agent_name": agent_name,
            }
            review_result = reviewer.review_video(video_path, review_meta)
            score = review_result.get("overall_score", 0)
            deliverable = review_result.get("deliverable", False)
            progress("skill_5", f"Quality score: {score}/10 | deliverable={deliverable}")
            if score < _DELIVERY_THRESHOLD or not deliverable:
                top = review_result.get("top_issues", [])
                progress("skill_5", f"⚠️  Below threshold ({_DELIVERY_THRESHOLD}) — issues: {top[:2]}")
        except Exception as e:
            progress("skill_5", f"Review skipped: {e}")

    job_logger.log_job_summary({
        "total_time": elapsed,
        "photo_count": len(photo_paths),
        "scene_count": len(scenes),
        "word_count": script["word_count"],
        "style": style,
        "aspect_ratio": aspect_ratio,
        "quality_score": review_result.get("overall_score"),
        "deliverable": review_result.get("deliverable"),
    })

    if agent_phone:
        profile_manager.increment_video_count(agent_phone)

    # ─── Result ────────────────────────────────────────────────────────
    return {
        "video_path": video_path,
        "output_dir": output_dir,
        "caption": script.get("caption", ""),
        "script": script["full_script"],
        "scene_count": len(scenes),
        "photo_count": len(photo_paths),
        "word_count": script["word_count"],
        "duration_seconds": elapsed,
        "style": style,
        "aspect_ratio": aspect_ratio,
        "quality_score": review_result.get("overall_score"),
        "deliverable": review_result.get("deliverable"),
        "top_issues": review_result.get("top_issues", []),
    }


def _get_music(output_dir: str, preference: str, style: str) -> str | None:
    """
    Get background music: IMA AI generation (primary) → local file (fallback).

    Returns path to music file, or None if unavailable.
    """
    import logging
    logger = logging.getLogger(__name__)

    # Build a music prompt based on style/preference
    style_prompts = {
        "energetic": "upbeat energetic pop instrumental, fast tempo, exciting real estate tour",
        "elegant": "elegant soft piano and strings, warm luxury real estate showcase",
        "professional": "modern corporate instrumental, clean and professional, light upbeat",
    }
    base_prompt = style_prompts.get(style, style_prompts["professional"])
    if preference and preference not in base_prompt:
        base_prompt = f"{preference} style, {base_prompt}"

    music_output = os.path.join(output_dir, "bgm.mp3")

    # Primary: IMA AI music generation
    try:
        from ima_client import generate_music
        result = generate_music(
            prompt=base_prompt,
            output_path=music_output,
            duration=30,
        )
        if result["status"] == "success":
            logger.info("IMA music generated: %s", music_output)
            return music_output
        logger.warning("IMA music failed: %s", result.get("message", ""))
    except Exception as e:
        logger.warning("IMA music unavailable: %s", e)

    # Fallback: local music files
    music_dir = Path(__file__).parent.parent / "assets" / "music"
    if not music_dir.exists():
        return None

    for ext in ("*.mp3", "*.wav", "*.m4a"):
        for f in music_dir.glob(ext):
            if preference.lower() in f.stem.lower() or style.lower() in f.stem.lower():
                return str(f)

    for ext in ("*.mp3", "*.wav", "*.m4a"):
        files = list(music_dir.glob(ext))
        if files:
            return str(files[0])

    return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Reel Agent Pipeline")
    parser.add_argument("photo_dir", help="Directory with listing photos")
    parser.add_argument("--address", default="[TBD]", help="Property address")
    parser.add_argument("--price", default="[TBD]", help="Asking price")
    parser.add_argument("--agent-name", default="", help="Agent name")
    parser.add_argument("--agent-phone", default="", help="Agent phone")
    parser.add_argument("--style", default="professional", choices=["energetic", "elegant", "professional"])
    parser.add_argument("--music", default="modern", choices=["modern", "piano", "acoustic"])
    parser.add_argument("--aspect-ratio", default="9:16", choices=["9:16", "16:9"])
    parser.add_argument("--language", default="en")
    parser.add_argument("--output", default=None, help="Output directory")
    args = parser.parse_args()

    print("🎬 Reel Agent Pipeline\n")
    result = run_pipeline(
        photo_dir=args.photo_dir,
        address=args.address,
        price=args.price,
        agent_name=args.agent_name,
        agent_phone=args.agent_phone,
        style=args.style,
        music_preference=args.music,
        aspect_ratio=args.aspect_ratio,
        language=args.language,
        output_dir=args.output,
    )

    if "error" in result:
        print(f"\n❌ {result['error']}")
        sys.exit(1)

    print(f"\n{'='*50}")
    print(f"🎬 Video: {result['video_path']}")
    print(f"📁 Output: {result['output_dir']}")
    print(f"📊 {result['photo_count']} photos → {result['scene_count']} scenes")
    print(f"📝 {result['word_count']} words | {result['aspect_ratio']}")
    print(f"⏱️  {result['duration_seconds']:.1f}s total")
    if result.get("quality_score") is not None:
        score = result["quality_score"]
        ok = "✅" if result.get("deliverable") else "❌"
        print(f"\n{ok} Quality: {score}/10 | deliverable={result.get('deliverable')}")
        for issue in result.get("top_issues", [])[:3]:
            print(f"   • {issue}")
    if result.get("caption"):
        print(f"\n📝 Caption:\n{result['caption']}")
