#!/usr/bin/env python3
"""
Reel Agent — End-to-End Pipeline Orchestrator

Chains 5 Skills to produce a listing video from photos:
  Skill 1 (Understand) → Skill 2 (Script) → Skill 3 (Prompt) → Skill 4 (Produce) → Skill 5 (Learn)

Usage:
  python pipeline.py <photo_dir> --address "123 Oak St" --price "$500K"
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Add scripts dir to path for local imports
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

import analyze_photos
import assemble_final
import generate_script
import generate_voice
import job_logger
import plan_scenes
import profile_manager
import render_ai_video
import write_video_prompts


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
    if agent_phone:
        user_profile = profile_manager.get_profile(agent_phone)
        if user_profile:
            style = user_profile.get("style", style)
            music_preference = user_profile.get("music_preference", music_preference)
            agent_name = user_profile.get("name", agent_name)
            progress("profile", f"Loaded profile for {agent_name}")

    # ─── Skill 1: 需求深挖 (Understand) ───────────────────────────────
    progress("skill_1", "Analyzing photos...")
    job_logger.log_step_start("skill_1_understand", {"photo_dir": photo_dir})

    photo_paths = sorted(
        os.path.join(photo_dir, f)
        for f in os.listdir(photo_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    )

    if not photo_paths:
        return {"error": "No photos found in directory"}

    analysis = analyze_photos.run(photo_paths)
    sorted_photos = analyze_photos.sort_photos(analysis)

    progress("skill_1", f"Analyzed {len(photo_paths)} photos")
    job_logger.log_step_end("skill_1_understand", {
        "photo_count": len(photo_paths),
        "rooms_detected": [p.get("room_type") for p in sorted_photos],
    })

    # Save analysis
    with open(os.path.join(output_dir, "analysis.json"), "w") as f:
        json.dump(analysis, f, indent=2)

    # ─── Skill 2: 剧本 (Script) ───────────────────────────────────────
    progress("skill_2", "Planning scenes & writing script...")
    job_logger.log_step_start("skill_2_script", {"address": address, "price": price})

    # 2a. Scene planning
    scenes = plan_scenes.run(
        photo_dir=photo_dir,
        property_info=f"Address: {address}\nPrice: {price}\nAgent: {agent_name}",
        language=language,
    )
    progress("skill_2", f"Planned {len(scenes)} scenes")

    # 2b. Voiceover script
    script = generate_script.run(
        photo_analysis=analysis,
        address=address,
        price=price,
        agent_name=agent_name,
        agent_phone=agent_phone,
    )
    progress("skill_2", f"Script: {script['word_count']} words, ~{script['estimated_duration']:.0f}s")

    if script.get("validation_issues"):
        progress("skill_2", f"Script issues: {script['validation_issues']}")

    job_logger.log_step_end("skill_2_script", {
        "scene_count": len(scenes),
        "word_count": script["word_count"],
    })

    # Save script & scenes
    with open(os.path.join(output_dir, "scenes.json"), "w") as f:
        json.dump(scenes, f, indent=2)
    with open(os.path.join(output_dir, "script.json"), "w") as f:
        json.dump(script, f, indent=2)

    # ─── Skill 3: 分镜 (Prompt) ───────────────────────────────────────
    progress("skill_3", "Writing video prompts...")
    job_logger.log_step_start("skill_3_prompt", {"scene_count": len(scenes)})

    prompts = write_video_prompts.run_batch(scenes, photo_dir)

    # Merge prompts back into scenes
    prompt_map = {p["sequence"]: p["motion_prompt"] for p in prompts}
    for scene in scenes:
        scene["motion_prompt"] = prompt_map.get(scene["sequence"], "")

    progress("skill_3", f"Generated {len(prompts)} video prompts")
    job_logger.log_step_end("skill_3_prompt", {"prompt_count": len(prompts)})

    with open(os.path.join(output_dir, "prompts.json"), "w") as f:
        json.dump(prompts, f, indent=2)

    # ─── Skill 4: 生成 (Produce) ──────────────────────────────────────
    progress("skill_4", "Generating AI video clips...")
    job_logger.log_step_start("skill_4_produce", {"style": style})

    clips_dir = os.path.join(output_dir, "clips")
    voice_dir = os.path.join(output_dir, "voice")
    os.makedirs(clips_dir, exist_ok=True)
    os.makedirs(voice_dir, exist_ok=True)

    # 4a. AI video clips
    clips = render_ai_video.generate_all_clips_v2(
        scene_plan=scenes,
        photo_dir=photo_dir,
        output_dir=clips_dir,
        aspect_ratio=aspect_ratio,
    )
    progress("skill_4", f"Rendered {len(clips)} video clips")

    # 4b. Per-scene voiceover
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
    progress("skill_5", "Logging & learning...")

    job_logger.log_job_summary({
        "total_time": elapsed,
        "photo_count": len(photo_paths),
        "scene_count": len(scenes),
        "word_count": script["word_count"],
        "style": style,
        "aspect_ratio": aspect_ratio,
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
    if result.get("caption"):
        print(f"\n📝 Caption:\n{result['caption']}")
