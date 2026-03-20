#!/usr/bin/env python3
"""
Listing Video Agent — AI Scene Planner
Uses Claude to plan the video scene sequence: which photos, in what order,
with first+last frame chains for seamless transitions.

Replaces the static room-type sorting with creative, AI-driven scene planning.
"""

import json
import re
import sys
from pathlib import Path

PLANNER_PROMPT = (Path(__file__).parent.parent / "prompts" / "refer" / "video_planner").read_text()


def build_scene_plan_request(
    photo_filenames: list[str],
    property_info: str,
    language: str = "en",
    photo_images: list[dict] = None,
) -> dict:
    """
    Build a Claude API request for AI scene planning.

    Args:
        photo_filenames: List of photo filenames (e.g. ["01_exterior.jpg", ...])
        property_info: Property description text (address, price, features...)
        language: Language for scene_desc and narration ("en", "zh", etc.)
        photo_images: Optional list of base64-encoded image dicts for Claude Vision.
                      Each dict: {"type": "image", "source": {"type": "base64", ...}}

    Returns:
        Claude API request dict
    """
    # Build the prompt with photo list and property context
    prompt = PLANNER_PROMPT.replace("${language}", language)

    content = []

    # If we have actual images, include them for visual understanding
    if photo_images:
        for i, (filename, img) in enumerate(zip(photo_filenames, photo_images)):
            content.append({"type": "text", "text": f"Image: {filename}"})
            content.append(img)
    else:
        # Text-only: just list the filenames
        image_list = "\n".join(f"- {f}" for f in photo_filenames)
        content.append({"type": "text", "text": f"Available images:\n{image_list}"})

    content.append({
        "type": "text",
        "text": f"<property_info>\n{property_info}\n</property_info>\n\n{prompt}",
    })

    return {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": content}],
    }


def parse_scene_plan(response_text: str) -> list[dict]:
    """
    Parse the video_planner response into a structured scene list.

    Expected format from LLM:
    <output>
    [
        {
            "first_frame": "image_name",
            "last_frame": "image_name",
            "scene_desc": "description",
            "text_narration": "narration text"
        },
        ...
    ]
    </output>

    Returns:
        List of scene dicts with keys: first_frame, last_frame, scene_desc, text_narration
    """
    # Extract content between <output> tags
    match = re.search(r"<output>\s*(.*?)\s*</output>", response_text, re.DOTALL)
    if not match:
        # Try parsing the whole response as JSON
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            return []

    raw = match.group(1).strip()
    try:
        scenes = json.loads(raw)
    except json.JSONDecodeError:
        return []

    # Validate structure
    validated = []
    for i, scene in enumerate(scenes):
        validated.append({
            "sequence": i + 1,
            "first_frame": scene.get("first_frame", ""),
            "last_frame": scene.get("last_frame", ""),
            "scene_desc": scene.get("scene_desc", ""),
            "text_narration": scene.get("text_narration", ""),
        })

    return validated


def scene_plan_to_storyboard(scenes: list[dict], photo_dir: str) -> dict:
    """
    Convert an AI scene plan into the storyboard format used by downstream scripts.

    This bridges the new AI planner output with the existing pipeline.
    Each scene becomes an "ai_video" render_type entry.

    Args:
        scenes: Output from parse_scene_plan()
        photo_dir: Directory containing the source photos

    Returns:
        Storyboard dict compatible with generate_all_clips() and full_assembly()
    """
    import os

    storyboard_entries = []

    for scene in scenes:
        first_frame = scene["first_frame"]
        last_frame = scene["last_frame"]

        # Resolve photo paths
        first_path = os.path.join(photo_dir, first_frame)
        last_path = os.path.join(photo_dir, last_frame)

        entry = {
            "sequence": scene["sequence"],
            "render_type": "ai_video",
            "first_frame": first_frame,
            "last_frame": last_frame,
            "first_frame_path": first_path,
            "last_frame_path": last_path if last_frame != first_frame else None,
            "scene_desc": scene["scene_desc"],
            "text_narration": scene["text_narration"],
            # These will be filled by write_video_prompts
            "motion_prompt": None,
        }
        storyboard_entries.append(entry)

    return {"storyboard": storyboard_entries}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: plan_scenes.py <photo_dir> [property_info_file] [language]")
        print("Returns a Claude API request dict for scene planning.")
        sys.exit(1)

    import os

    photo_dir = sys.argv[1]
    photos = sorted(f for f in os.listdir(photo_dir) if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")))

    prop_info = ""
    if len(sys.argv) > 2 and os.path.isfile(sys.argv[2]):
        prop_info = Path(sys.argv[2]).read_text()

    language = sys.argv[3] if len(sys.argv) > 3 else "en"

    request = build_scene_plan_request(photos, prop_info, language)
    print(json.dumps(request, indent=2, default=str))
