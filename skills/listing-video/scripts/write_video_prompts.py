#!/usr/bin/env python3
"""
Listing Video Agent — AI Video Prompt Writer
Uses Claude Vision to write per-scene video generation prompts
by analyzing the actual first+last frame images.

Replaces the template-based build_motion_prompt() with context-aware,
image-specific prompts.
"""

import json
import re
import sys
from pathlib import Path

WRITER_PROMPT = (Path(__file__).parent.parent / "prompts" / "refer" / "video_prompt_writer").read_text()


def _encode_image(image_path: str) -> dict:
    """Encode an image file as a Claude Vision content block."""
    import base64

    with open(image_path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")

    ext = Path(image_path).suffix.lower()
    media_types = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
    }
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_types.get(ext, "image/jpeg"),
            "data": data,
        },
    }


def build_prompt_request(
    first_frame_path: str,
    scene_desc: str,
    last_frame_path: str = None,
) -> dict:
    """
    Build a Claude API request to write a video generation prompt for one scene.

    Args:
        first_frame_path: Path to the first frame image
        scene_desc: Scene description from the planner
        last_frame_path: Optional path to the last frame image

    Returns:
        Claude API request dict
    """
    content = []

    # First frame
    content.append({"type": "text", "text": "First frame:"})
    content.append(_encode_image(first_frame_path))

    # Last frame (if different from first)
    if last_frame_path and last_frame_path != first_frame_path:
        content.append({"type": "text", "text": "Last frame:"})
        content.append(_encode_image(last_frame_path))

    # Scene description + prompt writer instructions
    content.append({
        "type": "text",
        "text": f"<scene_description>\n{scene_desc}\n</scene_description>\n\n{WRITER_PROMPT}",
    })

    return {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": content}],
    }


def parse_prompt_response(response_text: str) -> str:
    """
    Extract the video generation prompt from the LLM response.

    Expected format:
    <output>
    Your prompt here...
    </output>
    """
    match = re.search(r"<output>\s*(.*?)\s*</output>", response_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback: return the whole response stripped
    return response_text.strip()


def build_batch_prompt_requests(scenes: list[dict], photo_dir: str) -> list[dict]:
    """
    Build Claude API requests for all scenes in the plan.

    Args:
        scenes: Scene plan from plan_scenes.parse_scene_plan()
        photo_dir: Directory containing the source photos

    Returns:
        List of (scene_index, api_request) tuples
    """
    import os

    requests = []
    for scene in scenes:
        first_path = os.path.join(photo_dir, scene["first_frame"])
        last_frame = scene.get("last_frame", "")
        last_path = os.path.join(photo_dir, last_frame) if last_frame and last_frame != scene["first_frame"] else None

        if not os.path.exists(first_path):
            continue

        if last_path and not os.path.exists(last_path):
            last_path = None

        req = build_prompt_request(
            first_frame_path=first_path,
            scene_desc=scene.get("scene_desc", ""),
            last_frame_path=last_path,
        )
        requests.append((scene["sequence"], req))

    return requests


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: write_video_prompts.py <first_frame> <scene_desc> [last_frame]")
        sys.exit(1)

    req = build_prompt_request(
        first_frame_path=sys.argv[1],
        scene_desc=sys.argv[2],
        last_frame_path=sys.argv[3] if len(sys.argv) > 3 else None,
    )
    print(json.dumps(req, indent=2, default=str))
