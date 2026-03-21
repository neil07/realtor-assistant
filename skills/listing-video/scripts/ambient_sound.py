#!/usr/bin/env python3
"""
Listing Video Agent — Ambient Sound Design
Adds subtle environmental audio to individual scenes.

Pure ffmpeg mixing — uses royalty-free sound loops from assets/sounds/.
"""

import os
import subprocess
from pathlib import Path

SOUNDS_DIR = Path(__file__).parent.parent / "assets" / "sounds"

# Room type → ambient sound file(s)
AMBIENT_MAP = {
    "pool": ["water_gentle.mp3"],
    "backyard": ["birds_morning.mp3"],
    "exterior": ["birds_distant.mp3"],
    "aerial": ["wind_gentle.mp3"],
    "patio": ["birds_morning.mp3"],
    "balcony": ["wind_gentle.mp3"],
    "garden": ["birds_morning.mp3"],
}

# Feature keywords → ambient sound (searched in property features)
FEATURE_AMBIENT = {
    "beach": "waves_soft.mp3",
    "ocean view": "waves_distant.mp3",
    "ocean": "waves_distant.mp3",
    "waterfront": "waves_distant.mp3",
    "lake": "water_gentle.mp3",
    "fireplace": "fire_crackle.mp3",
    "fire pit": "fire_crackle.mp3",
    "creek": "water_stream.mp3",
    "fountain": "water_fountain.mp3",
    "downtown": "city_ambient.mp3",
    "urban": "city_ambient.mp3",
}


def select_ambient_sounds(
    scene_plan: list[dict],
    property_features: list[str] = None,
) -> list[dict]:
    """
    Select ambient sounds for each scene based on room type and property features.

    Rules:
    - Max 1 ambient sound per scene
    - Only outdoor/feature-relevant scenes get ambient
    - Feature-based sounds override room-type defaults

    Returns list of:
        {"sequence": int, "ambient_path": str | None, "volume": float}
    """
    features = property_features or []
    features_lower = " ".join(features).lower()

    # Check for feature-based ambient that applies to the whole property
    feature_ambient = None
    for keyword, sound_file in FEATURE_AMBIENT.items():
        if keyword in features_lower:
            sound_path = SOUNDS_DIR / sound_file
            if sound_path.exists():
                feature_ambient = str(sound_path)
                break

    result = []
    for scene in scene_plan:
        seq = scene.get("sequence", 0)
        desc = scene.get("scene_desc", "").lower()
        ambient_path = None

        # Try room-type ambient
        for room_type, sounds in AMBIENT_MAP.items():
            if room_type in desc:
                for sound_file in sounds:
                    path = SOUNDS_DIR / sound_file
                    if path.exists():
                        ambient_path = str(path)
                        break
                break

        # Feature ambient for outdoor scenes
        if not ambient_path and feature_ambient:
            if any(word in desc for word in ["exterior", "outdoor", "backyard", "pool", "view", "aerial", "patio"]):
                ambient_path = feature_ambient

        result.append({
            "sequence": seq,
            "ambient_path": ambient_path,
            "volume": 0.08,
        })

    return result


def mix_ambient_into_scene(
    video_path: str,
    ambient_path: str,
    output_path: str,
    volume: float = 0.08,
    fade_duration: float = 0.5,
) -> dict:
    """
    Mix ambient sound into a scene clip.
    Auto-loops the ambient if shorter than the video.
    Adds fade-in and fade-out.
    """
    import json

    # Get video duration
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "json", video_path],
        capture_output=True, text=True,
    )
    video_dur = 5.0
    if probe.returncode == 0:
        video_dur = float(json.loads(probe.stdout).get("format", {}).get("duration", 5))

    # Build filter: loop ambient, set volume, fade in/out, mix with existing audio
    fade_out_start = max(0, video_dur - fade_duration)
    ambient_filter = (
        f"[1:a]aloop=loop=-1:size=2e+09,atrim=0:{video_dur:.2f},"
        f"volume={volume},"
        f"afade=t=in:d={fade_duration},"
        f"afade=t=out:st={fade_out_start:.2f}:d={fade_duration}[amb]"
    )

    # Check if video has audio
    probe_audio = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "a", "-show_entries", "stream=codec_type", "-of", "json", video_path],
        capture_output=True, text=True,
    )
    has_audio = "audio" in probe_audio.stdout if probe_audio.returncode == 0 else False

    if has_audio:
        filter_complex = f"{ambient_filter};[0:a][amb]amix=inputs=2:duration=first[outa]"
        cmd = [
            "ffmpeg", "-y", "-i", video_path, "-i", ambient_path,
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[outa]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", output_path,
        ]
    else:
        filter_complex = ambient_filter.replace("[amb]", "[outa]")
        cmd = [
            "ffmpeg", "-y", "-i", video_path, "-i", ambient_path,
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[outa]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", output_path,
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {"status": "error", "message": result.stderr[-300:]}

    return {"status": "success", "video_path": output_path}


def apply_ambient_to_scenes(
    scene_clips: list[str],
    ambient_plan: list[dict],
    output_dir: str,
) -> list[str]:
    """
    Apply ambient sounds to scene clips that need them.
    Returns updated list of clip paths (ambient-mixed where applicable).
    """
    os.makedirs(output_dir, exist_ok=True)
    result_clips = []

    for clip_path, amb in zip(scene_clips, ambient_plan):
        if amb.get("ambient_path"):
            out = os.path.join(output_dir, f"amb_{Path(clip_path).name}")
            mix_result = mix_ambient_into_scene(
                video_path=clip_path,
                ambient_path=amb["ambient_path"],
                output_path=out,
                volume=amb.get("volume", 0.08),
            )
            if mix_result.get("status") == "success":
                result_clips.append(out)
            else:
                result_clips.append(clip_path)
        else:
            result_clips.append(clip_path)

    return result_clips


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Select ambient sounds for scenes")
    parser.add_argument("--scene-plan-file", required=True, help="Scene plan JSON file")
    parser.add_argument("--features", default="", help="Comma-separated property features")
    args = parser.parse_args()

    scene_plan = json.loads(Path(args.scene_plan_file).read_text())
    features = [f.strip() for f in args.features.split(",") if f.strip()] if args.features else []

    result = select_ambient_sounds(scene_plan, features)
    print(json.dumps(result, indent=2))
