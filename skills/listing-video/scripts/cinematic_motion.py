#!/usr/bin/env python3
"""
Listing Video Agent — Cinematic Motion Planner
Replaces hardcoded motion prompts with composition-aware camera plans.

Uses Claude Vision to analyze photo composition, then generates:
- Intelligent Ken Burns parameters (zoom toward focal point, not center)
- Context-aware AI video motion prompts (reference actual scene content)
"""

import json
import os
from pathlib import Path

COMPOSITION_PROMPT = (Path(__file__).parent.parent / "prompts" / "composition_analysis.md").read_text()


def analyze_photo_composition(image_path: str, room_type: str = "other") -> dict:
    """
    Use Claude Vision to analyze a photo's composition.

    Returns dict with focal_point, depth_layers, leading_lines, etc.
    """
    from api_client import call_claude_json
    from analyze_photos import encode_image

    content = [
        {"type": "text", "text": f"Room type: {room_type}"},
        encode_image(image_path),
        {"type": "text", "text": COMPOSITION_PROMPT},
    ]

    request = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": content}],
    }

    try:
        return call_claude_json(request)
    except Exception:
        # Fallback: centered composition
        return {
            "focal_point": {"x": 0.5, "y": 0.5},
            "depth_layers": [],
            "leading_lines": [],
            "open_space_direction": "center",
            "symmetry": {"type": "none", "axis": None},
            "recommended_motion": "slow_push",
        }


def plan_ken_burns_motion(
    composition: dict,
    duration: float = 3.0,
    zoom_range: list = None,
) -> dict:
    """
    Generate intelligent Ken Burns parameters based on composition analysis.

    Instead of always zooming toward center, zooms toward the focal point
    and pans along leading lines.

    Returns dict with ffmpeg zoompan x/y expressions.
    """
    if zoom_range is None:
        zoom_range = [1.0, 1.15]

    focal = composition.get("focal_point", {"x": 0.5, "y": 0.5})
    fx, fy = focal["x"], focal["y"]
    fps = 30
    total_frames = int(duration * fps)

    zoom_start, zoom_end = zoom_range
    zoom_expr = f"{zoom_start}+({zoom_end}-{zoom_start})*on/{total_frames}"

    # Pan toward focal point: start from center, end at focal
    # x expression: interpolate from center (0.5) to focal point
    cx, cy = 0.5, 0.5
    # Position formula: top-left of the visible window
    x_start = f"iw*{cx}-iw/zoom/2"
    x_end = f"iw*{fx}-iw/zoom/2"
    y_start = f"ih*{cy}-ih/zoom/2"
    y_end = f"ih*{fy}-ih/zoom/2"

    # Interpolate using on/total_frames
    x_expr = f"({x_start})+({x_end}-({x_start}))*on/{total_frames}"
    y_expr = f"({y_start})+({y_end}-({y_start}))*on/{total_frames}"

    # Check for leading lines — drift along them
    lines = composition.get("leading_lines", [])
    open_dir = composition.get("open_space_direction", "center")

    # Determine motion type
    symmetry = composition.get("symmetry", {}).get("type", "none")
    if symmetry != "none":
        # Symmetric: centered zoom, no pan
        x_expr = "iw/2-iw/zoom/2"
        y_expr = "ih/2-ih/zoom/2"
        motion_type = "centered_zoom"
    elif open_dir in ("left", "right"):
        motion_type = f"pan_{open_dir}"
    else:
        motion_type = "focal_zoom"

    return {
        "zoom_expr": zoom_expr,
        "x_expr": x_expr,
        "y_expr": y_expr,
        "total_frames": total_frames,
        "motion_type": motion_type,
        "focal_point": focal,
    }


def plan_ai_video_motion(
    composition: dict,
    room_type: str,
    scene_desc: str,
    highlights: list = None,
) -> str:
    """
    Generate a context-aware motion prompt for AI video generation.

    References actual photo content ("along the marble countertop")
    instead of generic prompts ("dolly forward").
    """
    focal = composition.get("focal_point", {"x": 0.5, "y": 0.5})
    layers = composition.get("depth_layers", [])
    lines = composition.get("leading_lines", [])
    recommended = composition.get("recommended_motion", "slow dolly forward")

    # Build content-aware prompt
    parts = []

    # Camera motion based on composition
    parts.append(f"Cinematic {recommended}")

    # Reference actual depth layers
    if layers:
        fg = next((l for l in layers if l["layer"] == "foreground"), None)
        bg = next((l for l in layers if l["layer"] == "background"), None)
        if fg and bg:
            parts.append(f"moving from {fg['content']} toward {bg['content']}")
        elif fg:
            parts.append(f"revealing {fg['content']}")

    # Reference leading lines for tracking direction
    if lines:
        line = lines[0]
        parts.append(f"tracking along the {line['element']}")

    # Scene description
    if scene_desc:
        parts.append(scene_desc)

    # Highlights
    if highlights:
        parts.append(f"highlighting {', '.join(highlights[:2])}")

    # Quality anchors
    parts.append("photorealistic, cinematic lighting, smooth motion, no artifacts")

    return ", ".join(parts)


def plan_scene_motions(
    scene_plan: list[dict],
    photo_dir: str,
    style: str = "professional",
    template: dict = None,
) -> list[dict]:
    """
    Plan cinematic motion for all scenes.

    Analyzes each scene's first frame composition, then generates
    Ken Burns parameters and AI video motion prompts.

    Ensures consecutive scenes don't repeat the same motion type.
    """
    zoom_range = [1.0, 1.12]
    if template:
        kb = template.get("video", {}).get("ken_burns", {})
        zoom_range = kb.get("zoom_range", zoom_range)

    prev_motion = None

    for scene in scene_plan:
        first_frame = scene.get("first_frame", "")
        first_path = os.path.join(photo_dir, first_frame)

        if not os.path.exists(first_path):
            continue

        # Infer room type from scene description
        room_type = _infer_room_type(scene.get("scene_desc", ""))

        # Analyze composition
        composition = analyze_photo_composition(first_path, room_type)
        scene["composition"] = composition

        # Plan Ken Burns
        duration = template.get("video", {}).get("clip_durations", {}).get("standard", 3) if template else 3
        kb_plan = plan_ken_burns_motion(composition, duration, zoom_range)

        # Avoid repeating same motion type consecutively
        if kb_plan["motion_type"] == prev_motion:
            # Flip to alternate motion
            if kb_plan["motion_type"] == "focal_zoom":
                kb_plan["motion_type"] = "pan_right"
            else:
                kb_plan["motion_type"] = "focal_zoom"

        scene["ken_burns_plan"] = kb_plan
        prev_motion = kb_plan["motion_type"]

        # Plan AI video motion prompt (if not already set by write_prompts)
        if not scene.get("ai_motion_prompt"):
            scene["ai_motion_prompt"] = plan_ai_video_motion(
                composition=composition,
                room_type=room_type,
                scene_desc=scene.get("scene_desc", ""),
                highlights=scene.get("highlights", []),
            )

    return scene_plan


def _infer_room_type(scene_desc: str) -> str:
    """Best-effort room type inference from scene description text."""
    desc_lower = scene_desc.lower()
    keywords = {
        "exterior": ["exterior", "facade", "front", "curb"],
        "living": ["living", "lounge", "family room"],
        "kitchen": ["kitchen", "cooking"],
        "dining": ["dining"],
        "bedroom": ["bedroom", "master bed", "suite"],
        "bathroom": ["bathroom", "bath", "shower"],
        "pool": ["pool", "swim"],
        "backyard": ["backyard", "garden", "patio", "outdoor"],
        "aerial": ["aerial", "drone"],
        "garage": ["garage"],
        "office": ["office", "study"],
    }
    for room_type, kws in keywords.items():
        if any(kw in desc_lower for kw in kws):
            return room_type
    return "other"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Plan cinematic motion for scenes")
    parser.add_argument("--scene-plan-file", required=True, help="Scene plan JSON file")
    parser.add_argument("--photo-dir", required=True, help="Directory containing photos")
    parser.add_argument("--style", default="professional", help="Video style")
    parser.add_argument("--template-file", default=None, help="Template JSON file")
    args = parser.parse_args()

    scene_plan = json.loads(Path(args.scene_plan_file).read_text())
    template = None
    if args.template_file:
        template = json.loads(Path(args.template_file).read_text())

    result = plan_scene_motions(scene_plan, args.photo_dir, args.style, template)
    print(json.dumps(result, indent=2, default=str))
