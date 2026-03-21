#!/usr/bin/env python3
"""
Listing Video Agent — Slideshow Renderer
Creates Ken Burns effect clips from photos using ffmpeg.
Also handles final assembly of all clips + voiceover + music.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def create_ken_burns_clip(
    image_path: str,
    output_path: str,
    duration: float = 3.0,
    motion: str = "slow_push",
    resolution: tuple = (1080, 1920),  # 9:16 vertical
    focal_point: dict = None,
) -> dict:
    """
    Create a Ken Burns effect clip from a single photo.

    Motions:
        slow_push: Zoom in slowly toward center (or focal_point if given)
        pull_back: Start zoomed, pull back
        slide_left: Pan from right to left
        slide_right: Pan from left to right
        static: No motion, just display

    Args:
        focal_point: Optional {"x": 0.0-1.0, "y": 0.0-1.0} from composition
                     analysis. When provided, zoom targets this point instead
                     of the image center.
    """
    w, h = resolution
    fps = 30
    total_frames = int(duration * fps)

    # Focal point: default to center
    fx = focal_point.get("x", 0.5) if focal_point else 0.5
    fy = focal_point.get("y", 0.5) if focal_point else 0.5

    # Ken Burns zoom parameters — focal-point-aware for push/pull
    focal_x = f"iw*{fx}-(iw/zoom/2)"
    focal_y = f"ih*{fy}-(ih/zoom/2)"
    center_x = "iw/2-(iw/zoom/2)"
    center_y = "ih/2-(ih/zoom/2)"

    zoom_configs = {
        "slow_push": {
            "start": 1.0, "end": 1.15,
            "x": f"({center_x})+({focal_x}-({center_x}))*on/{total_frames}",
            "y": f"({center_y})+({focal_y}-({center_y}))*on/{total_frames}",
        },
        "pull_back": {
            "start": 1.15, "end": 1.0,
            "x": f"({focal_x})+({center_x}-({focal_x}))*on/{total_frames}",
            "y": f"({focal_y})+({center_y}-({focal_y}))*on/{total_frames}",
        },
        "slide_left": {"start": 1.1, "end": 1.1, "x": f"(iw/zoom/2) + ((iw - iw/zoom) * (1 - on/{total_frames}))", "y": "ih/2-(ih/zoom/2)"},
        "slide_right": {"start": 1.1, "end": 1.1, "x": f"(iw - iw/zoom) * on/{total_frames}", "y": "ih/2-(ih/zoom/2)"},
        "static": {"start": 1.05, "end": 1.05, "x": "iw/2-(iw/zoom/2)", "y": "ih/2-(ih/zoom/2)"},
    }

    config = zoom_configs.get(motion, zoom_configs["slow_push"])

    # Build zoompan filter
    zoom_expr = f"{config['start']}+({config['end']}-{config['start']})*on/{total_frames}"

    filter_complex = (
        f"scale={w*2}:{h*2},"  # Scale up for quality
        f"zoompan=z='{zoom_expr}'"
        f":x='{config['x']}'"
        f":y='{config['y']}'"
        f":d={total_frames}"
        f":s={w}x{h}"
        f":fps={fps},"
        f"format=yuv420p"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-i", image_path,
        "-filter_complex", filter_complex,
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        output_path,
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        return {"status": "error", "message": result.stderr[-500:]}
    
    return {"status": "success", "video_path": output_path, "duration": duration}


def add_text_overlay(
    video_path: str,
    output_path: str,
    text: str,
    position: str = "bottom_center",
    font_size: int = 48,
    font_color: str = "white",
    font_file: str = None,
    start_time: float = 0.5,
    end_time: float = None,
) -> dict:
    """Add text overlay to a video clip."""
    if not font_file:
        # Try to find a good font
        font_candidates = [
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/SFNSMono.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        font_file = next((f for f in font_candidates if os.path.exists(f)), "")
    
    positions = {
        "bottom_center": f"x=(w-text_w)/2:y=h-text_h-80",
        "top_center": f"x=(w-text_w)/2:y=60",
        "center": f"x=(w-text_w)/2:y=(h-text_h)/2",
    }
    pos = positions.get(position, positions["bottom_center"])
    
    # Escape text for ffmpeg
    text_escaped = text.replace("'", "'\\''").replace(":", "\\:")
    
    drawtext = (
        f"drawtext=text='{text_escaped}'"
        f":fontsize={font_size}"
        f":fontcolor={font_color}"
        f":borderw=3:bordercolor=black@0.6"
        f":{pos}"
    )
    
    if font_file:
        drawtext += f":fontfile='{font_file}'"
    
    # Add fade in/out
    if start_time > 0:
        drawtext += f":enable='between(t,{start_time},{end_time or 999})'"
    
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", drawtext,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-c:a", "copy",
        output_path,
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        return {"status": "error", "message": result.stderr[-500:]}
    
    return {"status": "success", "video_path": output_path}


def create_cta_frame(
    output_path: str,
    agent_name: str,
    agent_phone: str,
    brokerage: str = "",
    duration: float = 4.0,
    resolution: tuple = (1080, 1920),
    bg_color: str = "black",
    text_color: str = "white",
    tagline: str = "Let's go see it.",
) -> dict:
    """Create a CTA end frame with agent info."""
    w, h = resolution
    
    # Build multi-line drawtext filter
    lines = []
    y_start = h // 2 - 120
    
    if tagline:
        lines.append(f"drawtext=text='{tagline}':fontsize=56:fontcolor={text_color}:x=(w-text_w)/2:y={y_start}")
        y_start += 80
    
    lines.append(f"drawtext=text='{agent_name}':fontsize=48:fontcolor={text_color}:x=(w-text_w)/2:y={y_start}")
    y_start += 64
    
    lines.append(f"drawtext=text='{agent_phone}':fontsize=40:fontcolor={text_color}@0.9:x=(w-text_w)/2:y={y_start}")
    y_start += 56
    
    if brokerage:
        lines.append(f"drawtext=text='{brokerage}':fontsize=32:fontcolor={text_color}@0.7:x=(w-text_w)/2:y={y_start}")
    
    filter_str = ",".join(lines)
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c={bg_color}:s={w}x{h}:d={duration}:r=30",
        "-vf", filter_str,
        "-c:v", "libx264",
        "-preset", "fast",
        "-t", str(duration),
        "-pix_fmt", "yuv420p",
        output_path,
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        return {"status": "error", "message": result.stderr[-500:]}
    
    return {"status": "success", "video_path": output_path, "duration": duration}


def enhance_photo(
    image_path: str,
    output_path: str,
    brightness: float = 1.0,
    contrast: float = 1.0,
    target_resolution: tuple = (1080, 1920),
) -> dict:
    """
    Pre-process a photo: adjust brightness, crop to target aspect ratio.
    """
    w, h = target_resolution
    
    filters = []
    
    # Scale and crop to fill target resolution
    filters.append(f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase")
    filters.append(f"crop={w*2}:{h*2}")
    filters.append(f"scale={w}:{h}")
    
    # Brightness/contrast adjustment
    if brightness != 1.0 or contrast != 1.0:
        filters.append(f"eq=brightness={brightness-1}:contrast={contrast}")
    
    filter_str = ",".join(filters)
    
    cmd = [
        "ffmpeg", "-y",
        "-i", image_path,
        "-vf", filter_str,
        "-q:v", "2",
        output_path,
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        return {"status": "error", "message": result.stderr[-500:]}
    
    return {"status": "success", "image_path": output_path}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Render slideshow clips and CTA frames")
    subparsers = parser.add_subparsers(dest="command")

    # Ken Burns clip
    kb = subparsers.add_parser("ken-burns", help="Create Ken Burns effect clip")
    kb.add_argument("image", help="Input image path")
    kb.add_argument("output", help="Output video path")
    kb.add_argument("--duration", type=float, default=3.0, help="Duration in seconds")
    kb.add_argument("--motion", default="slow_push", help="Motion type")
    kb.add_argument("--resolution", default="1080x1920", help="Resolution WxH")

    # CTA end frame
    cta = subparsers.add_parser("cta", help="Create CTA end frame")
    cta.add_argument("--output", required=True, help="Output video path")
    cta.add_argument("--agent-name", required=True, help="Agent name")
    cta.add_argument("--agent-phone", required=True, help="Agent phone number")
    cta.add_argument("--brokerage", default="", help="Brokerage name")
    cta.add_argument("--template-file", default=None, help="Template JSON for styling")
    cta.add_argument("--duration", type=float, default=4.0, help="Duration in seconds")
    cta.add_argument("--tagline", default="Let's go see it.", help="CTA tagline")

    args = parser.parse_args()

    if args.command == "ken-burns":
        w, h = map(int, args.resolution.split("x"))
        result = create_ken_burns_clip(
            image_path=args.image, output_path=args.output,
            duration=args.duration, motion=args.motion, resolution=(w, h),
        )
        print(json.dumps(result, indent=2))

    elif args.command == "cta":
        result = create_cta_frame(
            output_path=args.output,
            agent_name=args.agent_name,
            agent_phone=args.agent_phone,
            brokerage=args.brokerage,
            duration=args.duration,
            tagline=args.tagline,
        )
        print(json.dumps(result, indent=2))

    else:
        parser.print_help()
        sys.exit(1)
