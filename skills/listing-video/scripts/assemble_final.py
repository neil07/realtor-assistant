#!/usr/bin/env python3
"""
Listing Video Agent — Final Assembly
Combines AI video clips + slideshow clips + voiceover + music + text overlays
into the final deliverable video using ffmpeg.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def concat_clips(
    clip_paths: list[str],
    output_path: str,
    transitions: list[dict] = None,
) -> dict:
    """
    Concatenate video clips with optional crossfade transitions.
    
    Args:
        clip_paths: Ordered list of clip file paths
        output_path: Output video path
        transitions: List of {"type": "crossfade"|"cut", "duration": 0.5}
    """
    if not clip_paths:
        return {"status": "error", "message": "No clips provided"}
    
    # Create concat file
    concat_file = output_path + ".concat.txt"
    with open(concat_file, "w") as f:
        for path in clip_paths:
            f.write(f"file '{os.path.abspath(path)}'\n")
    
    if transitions and any(t.get("type") == "crossfade" for t in transitions):
        # Use xfade filter for crossfade transitions
        result = _concat_with_crossfade(clip_paths, output_path, transitions)
    else:
        # Simple concat
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_file,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            return {"status": "error", "message": result.stderr[-500:]}
    
    # Clean up
    os.remove(concat_file)
    
    return {"status": "success", "video_path": output_path}


def _concat_with_crossfade(
    clip_paths: list[str],
    output_path: str,
    transitions: list[dict],
) -> dict:
    """Concatenate with xfade crossfade transitions."""
    if len(clip_paths) < 2:
        return concat_clips(clip_paths, output_path)
    
    # Build complex filter for crossfade
    inputs = []
    for p in clip_paths:
        inputs.extend(["-i", p])
    
    # Get durations of each clip
    durations = []
    for p in clip_paths:
        dur = get_duration(p)
        durations.append(dur)
    
    # Build xfade chain
    filter_parts = []
    current_input = "[0:v]"
    offset = durations[0]
    
    for i in range(1, len(clip_paths)):
        t = transitions[i-1] if i-1 < len(transitions) else {"type": "crossfade", "duration": 0.5}
        xfade_dur = t.get("duration", 0.5)
        
        if t.get("type") == "cut":
            xfade_dur = 0
        
        next_input = f"[{i}:v]"
        out_label = f"[v{i}]" if i < len(clip_paths) - 1 else "[outv]"
        
        offset_val = offset - xfade_dur
        filter_parts.append(
            f"{current_input}{next_input}xfade=transition=fade:duration={xfade_dur}:offset={offset_val}{out_label}"
        )
        
        current_input = out_label
        offset = offset_val + durations[i]
    
    filter_complex = ";".join(filter_parts)
    
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        output_path,
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        return {"status": "error", "message": result.stderr[-500:]}
    
    return {"status": "success", "video_path": output_path}


def add_audio_layers(
    video_path: str,
    output_path: str,
    voiceover_path: str = None,
    music_path: str = None,
    music_volume: float = 0.15,
    duck_under_voice: bool = True,
) -> dict:
    """
    Add voiceover and background music to the assembled video.
    
    Args:
        video_path: Input video (no audio or existing audio)
        output_path: Output video with audio
        voiceover_path: Path to voiceover audio file
        music_path: Path to background music file
        music_volume: Background music volume (0.0-1.0)
        duck_under_voice: Lower music volume when voice is playing
    """
    inputs = ["-i", video_path]
    filter_parts = []
    
    audio_inputs = []
    
    if voiceover_path:
        inputs.extend(["-i", voiceover_path])
        audio_inputs.append("voice")
    
    if music_path:
        inputs.extend(["-i", music_path])
        audio_inputs.append("music")
    
    if not audio_inputs:
        return {"status": "error", "message": "No audio provided"}
    
    video_duration = get_duration(video_path)
    
    if voiceover_path and music_path:
        voice_idx = 1
        music_idx = 2
        
        if duck_under_voice:
            # Sidechain compression: duck music under voice
            filter_complex = (
                f"[{music_idx}:a]volume={music_volume},atrim=0:{video_duration},apad=whole_dur={video_duration}[music];"
                f"[{voice_idx}:a]apad=whole_dur={video_duration}[voice];"
                f"[music][voice]sidechaincompress=threshold=0.02:ratio=6:attack=200:release=1000[ducked];"
                f"[ducked][voice]amix=inputs=2:duration=longest[outa]"
            )
        else:
            filter_complex = (
                f"[{music_idx}:a]volume={music_volume},atrim=0:{video_duration},apad=whole_dur={video_duration}[music];"
                f"[{voice_idx}:a]apad=whole_dur={video_duration}[voice];"
                f"[music][voice]amix=inputs=2:duration=longest[outa]"
            )
        
        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[outa]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_path,
        ]
    
    elif voiceover_path:
        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_path,
        ]
    
    elif music_path:
        music_idx = 1
        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", f"[{music_idx}:a]volume={music_volume},afade=t=in:d=1,afade=t=out:st={video_duration-2}:d=2[outa]",
            "-map", "0:v",
            "-map", "[outa]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_path,
        ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        return {"status": "error", "message": result.stderr[-500:]}
    
    return {"status": "success", "video_path": output_path}


# Default aspect ratio per publishing channel
CHANNEL_DEFAULTS = {
    "reels": "9:16",
    "tiktok": "9:16",
    "shorts": "9:16",
    "instagram": "9:16",
    "xiaohongshu": "9:16",
    "douyin": "9:16",
    "youtube": "16:9",
    "website": "16:9",
    "mls": "16:9",
    "zillow": "16:9",
}


def resolve_aspect_ratio(
    aspect_ratio: str = None,
    channel: str = None,
) -> str:
    """
    Determine the output aspect ratio.

    Priority: explicit aspect_ratio > channel default > "9:16".
    """
    if aspect_ratio:
        return aspect_ratio
    if channel:
        return CHANNEL_DEFAULTS.get(channel.lower(), "9:16")
    return "9:16"


def create_output_format(
    video_path: str,
    output_dir: str,
    listing_id: str = "listing",
    aspect_ratio: str = "9:16",
) -> dict:
    """
    Create a single output format. Converts between aspect ratios if needed.

    If the source matches the target ratio, it's a simple copy.
    If converting 9:16 → 16:9 (or vice versa), uses blurred background fill.

    Args:
        video_path: Input video path
        output_dir: Output directory
        listing_id: Identifier for filename
        aspect_ratio: Target aspect ratio ("9:16" or "16:9")

    Returns:
        {"status": "success", "video_path": str, "aspect_ratio": str}
    """
    os.makedirs(output_dir, exist_ok=True)

    tag = "9x16" if aspect_ratio == "9:16" else "16x9"
    output_path = os.path.join(output_dir, f"{listing_id}_{tag}.mp4")

    # Probe source dimensions
    probe_cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "stream=width,height",
        "-of", "json", video_path,
    ]
    probe = subprocess.run(probe_cmd, capture_output=True, text=True)
    src_w, src_h = 1080, 1920  # default assumption
    if probe.returncode == 0:
        streams = json.loads(probe.stdout).get("streams", [{}])
        if streams:
            src_w = streams[0].get("width", 1080)
            src_h = streams[0].get("height", 1920)

    src_vertical = src_h > src_w
    target_vertical = aspect_ratio == "9:16"

    if src_vertical == target_vertical:
        # Same orientation — just copy
        subprocess.run(["cp", video_path, output_path], check=True)
    elif target_vertical:
        # 16:9 source → 9:16 target: blurred background fill
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-filter_complex",
            "[0:v]split=2[bg][fg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bgblur];"
            "[fg]scale=1080:-1:force_original_aspect_ratio=decrease[fgscaled];"
            "[bgblur][fgscaled]overlay=(W-w)/2:(H-h)/2[outv]",
            "-map", "[outv]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "copy", output_path,
        ]
        subprocess.run(cmd, capture_output=True, text=True)
    else:
        # 9:16 source → 16:9 target: blurred background fill
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-filter_complex",
            "[0:v]split=2[bg][fg];"
            "[bg]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,boxblur=20:5[bgblur];"
            "[fg]scale=-1:1080:force_original_aspect_ratio=decrease[fgscaled];"
            "[bgblur][fgscaled]overlay=(W-w)/2:(H-h)/2[outv]",
            "-map", "[outv]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "copy", output_path,
        ]
        subprocess.run(cmd, capture_output=True, text=True)

    return {
        "status": "success",
        "video_path": output_path,
        "aspect_ratio": aspect_ratio,
    }


def create_both_formats(
    video_path: str,
    output_dir: str,
    listing_id: str = "listing",
) -> dict:
    """Legacy wrapper: create both vertical and horizontal versions."""
    v = create_output_format(video_path, output_dir, listing_id, "9:16")
    h = create_output_format(video_path, output_dir, listing_id, "16:9")
    return {
        "status": "success",
        "vertical": v["video_path"],
        "horizontal": h["video_path"],
    }


def get_duration(file_path: str) -> float:
    """Get duration of audio/video file in seconds."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "json",
        file_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        data = json.loads(result.stdout)
        return float(data.get("format", {}).get("duration", 0))
    return 0.0


def _ensure_video_covers_audio(
    video_path: str,
    audio_path: str,
    progress_callback=None,
) -> str:
    """
    If the concatenated video is shorter than the voiceover, slow it down
    proportionally so the visuals cover the full narration.

    Uses ffmpeg setpts to stretch; caps slowdown at 0.6x to avoid jelly motion.
    If the gap is too large (>0.6x), it loops the video instead.

    Returns the (possibly new) video path.
    """
    video_dur = get_duration(video_path)
    audio_dur = get_duration(audio_path)

    if video_dur <= 0 or audio_dur <= 0 or video_dur >= audio_dur:
        return video_path  # no fix needed

    target_dur = audio_dur + 1.0  # 1s breathing room
    ratio = target_dur / video_dur  # >1 means video needs to be longer

    stretched_path = video_path.replace(".mp4", "_stretched.mp4")

    if ratio <= 1.67:
        # Slow down (up to 0.6x speed is acceptable)
        if progress_callback:
            progress_callback(
                f"Video {video_dur:.0f}s < voiceover {audio_dur:.0f}s, "
                f"slowing to {1/ratio:.0%} speed..."
            )
        pts_factor = ratio  # setpts=PTS*ratio stretches duration
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-filter:v", f"setpts={pts_factor:.4f}*PTS",
            "-an",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            stretched_path,
        ]
    else:
        # Gap too large for slowdown alone — loop the video
        if progress_callback:
            progress_callback(
                f"Video {video_dur:.0f}s << voiceover {audio_dur:.0f}s, "
                f"looping video to match..."
            )
        loop_count = int(ratio) + 1
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", str(loop_count - 1),
            "-i", video_path,
            "-t", f"{target_dur:.2f}",
            "-an",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            stretched_path,
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        # Fallback: return original and let audio be truncated
        return video_path

    # Replace original with stretched version
    os.replace(stretched_path, video_path)
    return video_path


def full_assembly(
    storyboard: dict,
    clips_dir: str,
    voiceover_path: str,
    music_path: str,
    output_dir: str,
    listing_id: str = "listing",
    aspect_ratio: str = None,
    channel: str = None,
    progress_callback=None,
) -> dict:
    """
    Full assembly pipeline: concat clips → add audio → create output format.

    Args:
        aspect_ratio: Explicit "9:16" or "16:9". Overrides channel default.
        channel: Publishing channel (reels/tiktok/youtube/...) for auto ratio.
                 If neither aspect_ratio nor channel is set, defaults to "9:16".
    """
    from job_logger import get_logger, log_step_start, log_step_end, log_duration_check, log_job_summary

    logger = get_logger()
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Order clips by sequence
    log_step_start("assembly", {"listing_id": listing_id})
    if progress_callback:
        progress_callback("🔧 [4/5] Assembling clips...")

    clip_files = []
    transitions = []

    for segment in sorted(storyboard["storyboard"], key=lambda s: s["sequence"]):
        seq = segment["sequence"]

        if segment["render_type"] == "ai_video":
            clip_path = os.path.join(clips_dir, f"ai_clip_{seq:02d}.mp4")
        else:
            clip_path = os.path.join(clips_dir, f"slide_{seq:02d}.mp4")

        if os.path.exists(clip_path):
            clip_dur = get_duration(clip_path)
            logger.info("  Clip seq=%02d  dur=%.1fs  path=%s", seq, clip_dur, clip_path)
            clip_files.append(clip_path)

            if segment["render_type"] == "ai_video":
                transitions.append({"type": "cut", "duration": 0})
            else:
                transitions.append({"type": "crossfade", "duration": 0.5})
        else:
            logger.warning("  Clip seq=%02d  MISSING: %s", seq, clip_path)

    # Add CTA frame
    cta_path = os.path.join(clips_dir, "cta.mp4")
    if os.path.exists(cta_path):
        clip_files.append(cta_path)
        transitions.append({"type": "crossfade", "duration": 0.8})

    logger.info("Total clips: %d", len(clip_files))

    # Step 2: Concatenate
    concat_path = os.path.join(output_dir, f"{listing_id}_concat.mp4")
    concat_result = concat_clips(clip_files, concat_path, transitions)

    if concat_result["status"] != "success":
        log_step_end("assembly", concat_result)
        return concat_result

    concat_dur = get_duration(concat_path)
    logger.info("Concat duration: %.1fs", concat_dur)

    # Step 2.5: Ensure video covers voiceover duration
    if voiceover_path and os.path.exists(voiceover_path):
        audio_dur = get_duration(voiceover_path)
        if concat_dur < audio_dur:
            log_duration_check(concat_dur, audio_dur, "stretching")
        else:
            log_duration_check(concat_dur, audio_dur, "ok")
        concat_path = _ensure_video_covers_audio(
            concat_path, voiceover_path, progress_callback
        )

    # Step 3: Add audio
    if progress_callback:
        progress_callback("🎵 [5/5] Adding voiceover and music...")

    final_path = os.path.join(output_dir, f"{listing_id}_final.mp4")
    audio_result = add_audio_layers(
        video_path=concat_path,
        output_path=final_path,
        voiceover_path=voiceover_path,
        music_path=music_path,
        music_volume=0.12,
        duck_under_voice=True,
    )

    if audio_result["status"] != "success":
        log_step_end("assembly", audio_result)
        return audio_result

    # Step 4: Create output format
    target_ratio = resolve_aspect_ratio(aspect_ratio, channel)
    format_result = create_output_format(final_path, output_dir, listing_id, target_ratio)

    # Clean up intermediate files
    for f in [concat_path, final_path]:
        if os.path.exists(f):
            os.remove(f)

    result = {
        "status": "success",
        "video_path": format_result["video_path"],
        "aspect_ratio": target_ratio,
    }
    log_step_end("assembly", result)
    log_job_summary(result)

    return result


def full_assembly_v2(
    scene_plan: list[dict],
    clips_dir: str,
    narrations: list[dict],
    music_path: str,
    output_dir: str,
    listing_id: str = "listing",
    aspect_ratio: str = None,
    channel: str = None,
    progress_callback=None,
) -> dict:
    """
    V2 assembly pipeline with per-scene audio alignment.

    Instead of one monolithic voiceover laid over the full video,
    each scene's clip is matched with its own narration segment.
    This guarantees audio-visual sync regardless of AI clip duration.

    Pipeline:
      1. For each scene: match clip + narration, adjust clip length to fit
      2. Concatenate all scene clips (with per-scene audio baked in)
      3. Add background music
      4. Create both formats

    Args:
        scene_plan: Scene plan with sequence numbers
        clips_dir: Directory containing scene_XX.mp4 clips
        narrations: Per-scene TTS results from generate_scene_voiceovers()
        music_path: Background music file
        output_dir: Output directory
        listing_id: Identifier for output filenames
        progress_callback: Progress callback
    """
    from job_logger import get_logger, log_step_start, log_step_end, log_job_summary

    logger = get_logger()
    os.makedirs(output_dir, exist_ok=True)
    log_step_start("assembly_v2", {"listing_id": listing_id, "mode": "per_scene_audio"})

    if progress_callback:
        progress_callback("Assembling scenes with per-scene audio...")

    # Build narration lookup: sequence -> narration result
    narr_lookup = {n["sequence"]: n for n in narrations if n["status"] == "success"}

    # Step 1: For each scene, create clip with its narration baked in
    scene_clips_with_audio = []

    for scene in sorted(scene_plan, key=lambda s: s["sequence"]):
        seq = scene["sequence"]
        clip_path = os.path.join(clips_dir, f"scene_{seq:02d}.mp4")

        if not os.path.exists(clip_path):
            logger.warning("  Scene %02d clip MISSING: %s", seq, clip_path)
            continue

        clip_dur = get_duration(clip_path)
        narr = narr_lookup.get(seq)

        if narr and narr.get("audio_path") and os.path.exists(narr["audio_path"]):
            narr_dur = narr["duration"]
            merged_path = os.path.join(output_dir, f"merged_{seq:02d}.mp4")

            # If clip is shorter than narration, stretch clip to match
            if clip_dur < narr_dur - 0.5:
                ratio = (narr_dur + 0.3) / clip_dur
                logger.info(
                    "  Scene %02d: clip=%.1fs < narr=%.1fs, stretching %.1fx",
                    seq, clip_dur, narr_dur, ratio,
                )
                stretched_path = os.path.join(output_dir, f"stretched_{seq:02d}.mp4")

                if ratio <= 1.67:
                    cmd = [
                        "ffmpeg", "-y", "-i", clip_path,
                        "-filter:v", f"setpts={ratio:.4f}*PTS",
                        "-an", "-c:v", "libx264", "-preset", "fast",
                        "-crf", "18", "-pix_fmt", "yuv420p",
                        stretched_path,
                    ]
                else:
                    loop_count = int(ratio) + 1
                    cmd = [
                        "ffmpeg", "-y",
                        "-stream_loop", str(loop_count - 1),
                        "-i", clip_path,
                        "-t", f"{narr_dur + 0.3:.2f}",
                        "-an", "-c:v", "libx264", "-preset", "fast",
                        "-crf", "18", "-pix_fmt", "yuv420p",
                        stretched_path,
                    ]

                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    clip_path = stretched_path
            elif clip_dur > narr_dur + 2.0:
                # Clip is much longer than narration — trim to narr + 1s buffer
                logger.info(
                    "  Scene %02d: clip=%.1fs > narr=%.1fs, trimming",
                    seq, clip_dur, narr_dur,
                )
                trimmed_path = os.path.join(output_dir, f"trimmed_{seq:02d}.mp4")
                cmd = [
                    "ffmpeg", "-y", "-i", clip_path,
                    "-t", f"{narr_dur + 1.0:.2f}",
                    "-c:v", "libx264", "-preset", "fast",
                    "-crf", "18", "-pix_fmt", "yuv420p",
                    "-an", trimmed_path,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    clip_path = trimmed_path

            # Merge clip + narration audio
            cmd = [
                "ffmpeg", "-y",
                "-i", clip_path,
                "-i", narr["audio_path"],
                "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                merged_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                merged_dur = get_duration(merged_path)
                logger.info("  Scene %02d: merged %.1fs  %s", seq, merged_dur, merged_path)
                scene_clips_with_audio.append(merged_path)
            else:
                logger.warning("  Scene %02d merge failed, using clip only", seq)
                scene_clips_with_audio.append(clip_path)
        else:
            # No narration for this scene — use clip as-is (silent)
            logger.info("  Scene %02d: no narration, clip=%.1fs", seq, clip_dur)
            scene_clips_with_audio.append(clip_path)

    if not scene_clips_with_audio:
        result = {"status": "error", "message": "No scene clips available for assembly"}
        log_step_end("assembly_v2", result)
        return result

    # Step 2: Concatenate all scene clips
    if progress_callback:
        progress_callback("Concatenating scenes...")

    concat_path = os.path.join(output_dir, f"{listing_id}_concat.mp4")
    # Use cut transitions (scenes already have smooth first→last frame flow)
    transitions = [{"type": "cut", "duration": 0}] * len(scene_clips_with_audio)
    concat_result = concat_clips(scene_clips_with_audio, concat_path, transitions)

    if concat_result["status"] != "success":
        log_step_end("assembly_v2", concat_result)
        return concat_result

    total_dur = get_duration(concat_path)
    logger.info("Total concat duration: %.1fs", total_dur)

    # Step 3: Add background music
    if music_path and os.path.exists(music_path):
        if progress_callback:
            progress_callback("Adding background music...")

        final_path = os.path.join(output_dir, f"{listing_id}_final.mp4")
        music_result = add_audio_layers(
            video_path=concat_path,
            output_path=final_path,
            voiceover_path=None,  # Voice already baked into each clip
            music_path=music_path,
            music_volume=0.10,
            duck_under_voice=False,
        )

        if music_result["status"] == "success":
            concat_path = final_path
    else:
        final_path = concat_path

    # Step 4: Create output format
    target_ratio = resolve_aspect_ratio(aspect_ratio, channel)
    format_result = create_output_format(final_path, output_dir, listing_id, target_ratio)

    # Clean up intermediate files
    import glob
    for pattern in ["merged_*.mp4", "stretched_*.mp4", "trimmed_*.mp4"]:
        for f in glob.glob(os.path.join(output_dir, pattern)):
            os.remove(f)
    for f in [os.path.join(output_dir, f"{listing_id}_concat.mp4"),
              os.path.join(output_dir, f"{listing_id}_final.mp4")]:
        if os.path.exists(f):
            os.remove(f)

    result = {
        "status": "success",
        "video_path": format_result["video_path"],
        "aspect_ratio": target_ratio,
        "total_duration": total_dur,
        "scenes": len(scene_clips_with_audio),
    }
    log_step_end("assembly_v2", result)
    log_job_summary(result)

    return result


if __name__ == "__main__":
    print("Use full_assembly() or full_assembly_v2() from the orchestrator.")
    print("Standalone: ffmpeg must be installed.")
    subprocess.run(["ffmpeg", "-version"], capture_output=True)
