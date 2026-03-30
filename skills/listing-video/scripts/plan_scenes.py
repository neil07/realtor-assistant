#!/usr/bin/env python3
"""
Listing Video Agent — AI Scene Planner

Uses Claude to plan the video scene sequence: which photos, in what order,
with first+last frame chains for seamless transitions.

Replaces static room-type sorting with creative, AI-driven scene planning.

Optimisations:
  - Prompt caching: PLANNER_PROMPT is placed in the system block with
    cache_control=ephemeral, so repeated calls within the same 5-minute
    window share the cached prompt tokens (~90% cost reduction on input).
  - Files API: pass file_ids to reference pre-uploaded photos instead of
    re-encoding base64 on every call.
"""

import json
import re
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

PLANNER_PROMPT = (Path(__file__).parent.parent / "prompts" / "refer" / "video_planner").read_text()


def build_scene_plan_request(
    photo_filenames: list[str],
    property_info: str,
    language: str = "en",
    photo_images: list[dict] | None = None,
    file_ids: list[str] | None = None,
) -> dict:
    """
    Build a Claude API request for AI scene planning.

    The PLANNER_PROMPT is placed in the system block with cache_control=ephemeral
    so it is cached for 5 minutes. Repeated calls within the same job hit the
    cache and pay only a fraction of the input token cost.

    Args:
        photo_filenames: List of photo filenames (e.g. ["01_exterior.jpg", ...]).
        property_info: Property description text (address, price, features…).
        language: Language for scene_desc and narration ("en", "zh", etc.).
        photo_images: Optional list of base64-encoded image dicts (Claude Vision).
                      Each dict: {"type": "image", "source": {"type": "base64", ...}}
        file_ids: Optional Anthropic Files API file_ids. When provided, images are
                  referenced by ID. file_ids and photo_images are mutually exclusive;
                  file_ids takes precedence.

    Returns:
        Claude API request dict.
        - Use client.messages.create(**request) for base64 / text-only mode.
        - Use client.beta.messages.create(**request, betas=["files-api-2025-04-14"])
          when file_ids are provided.
    """
    prompt_with_lang = PLANNER_PROMPT.replace("${language}", language)

    # System block: large static prompt cached for 5 minutes
    system = [
        {
            "type": "text",
            "text": prompt_with_lang,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    # User message: only the variable parts (filenames / images + property info)
    content: list[dict] = []

    if file_ids is not None:
        # Files API mode: reference pre-uploaded images
        for filename, fid in zip(photo_filenames, file_ids):
            content.append({"type": "text", "text": f"Image: {filename}"})
            content.append({
                "type": "image",
                "source": {"type": "file", "file_id": fid},
            })
    elif photo_images:
        # Base64 Vision mode
        for filename, img in zip(photo_filenames, photo_images):
            content.append({"type": "text", "text": f"Image: {filename}"})
            content.append(img)
    else:
        # Text-only mode: just list the filenames
        image_list = "\n".join(f"- {f}" for f in photo_filenames)
        content.append({"type": "text", "text": f"Available images:\n{image_list}"})

    content.append({
        "type": "text",
        "text": f"<property_info>\n{property_info}\n</property_info>",
    })

    return {
        "model": "claude-sonnet-4-6",
        "max_tokens": 4096,
        "system": system,
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
        List of scene dicts with keys: sequence, first_frame, last_frame,
        scene_desc, text_narration.
    """
    match = re.search(r"<output>\s*(.*?)\s*</output>", response_text, re.DOTALL)
    if not match:
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            return []

    raw = match.group(1).strip()
    try:
        scenes = json.loads(raw)
    except json.JSONDecodeError:
        return []

    # Deduplicate by first_frame: keep first occurrence of each photo.
    # Prevents Claude from reusing the same photo twice (e.g. 6 scenes from 5 photos).
    # last_frame can repeat (transition chain), only first_frame is deduplicated.
    seen_first_frames: set[str] = set()
    validated = []
    _MAX_NARRATION_WORDS = 15  # ~4s TTS @ 3.75 wps; keeps total video ≤ 30s
    for scene in scenes:
        first = scene.get("first_frame", "")
        if not first or first in seen_first_frames:
            continue
        seen_first_frames.add(first)

        # Cap narration to avoid per-scene TTS exceeding ~4s
        narr = scene.get("text_narration", "")
        words = narr.split()
        if len(words) > _MAX_NARRATION_WORDS:
            narr = " ".join(words[:_MAX_NARRATION_WORDS]).rstrip(".,!?") + "."

        validated.append({
            "sequence": len(validated) + 1,
            "first_frame": first,
            "last_frame": scene.get("last_frame", ""),
            "scene_desc": scene.get("scene_desc", ""),
            "text_narration": narr,
        })

    return validated


def scene_plan_to_storyboard(scenes: list[dict], photo_dir: str) -> dict:
    """
    Convert an AI scene plan into the storyboard format used by downstream scripts.

    Each scene becomes an "ai_video" render_type entry with resolved paths.

    Args:
        scenes: Output from parse_scene_plan().
        photo_dir: Directory containing the source photos.

    Returns:
        Storyboard dict compatible with generate_all_clips() and full_assembly().
    """
    import os

    storyboard_entries = []

    for scene in scenes:
        first_frame = scene["first_frame"]
        last_frame = scene["last_frame"]

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
            "motion_prompt": None,  # filled by write_video_prompts
        }
        storyboard_entries.append(entry)

    return {"storyboard": storyboard_entries}


def run(
    photo_dir: str,
    property_info: str = "",
    language: str = "en",
    with_images: bool = True,
    file_ids: list[str] | None = None,
) -> list[dict]:
    """
    Run scene planning end-to-end: build request → call Claude API → parse result.

    Args:
        photo_dir: Directory containing listing photos.
        property_info: Property description text.
        language: Language for narration ("en", "zh").
        with_images: Whether to include actual images for Claude Vision (base64).
                     Ignored when file_ids is provided.
        file_ids: Optional pre-uploaded Anthropic file_ids. When provided,
                  references files by ID instead of base64.

    Returns:
        List of scene dicts from parse_scene_plan().
    """
    import os

    photos = sorted(
        f for f in os.listdir(photo_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    )

    photo_images = None
    if file_ids is not None:
        # File IDs provided — skip base64 encoding entirely
        request = build_scene_plan_request(photos, property_info, language, file_ids=file_ids)
        client = anthropic.Anthropic()
        response = client.beta.messages.create(
            **request, betas=["files-api-2025-04-14"]
        )
    else:
        if with_images:
            from analyze_photos import encode_image
            photo_images = [encode_image(os.path.join(photo_dir, f)) for f in photos]
        request = build_scene_plan_request(photos, property_info, language, photo_images)
        client = anthropic.Anthropic()
        response = client.messages.create(**request)

    return parse_scene_plan(response.content[0].text)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: plan_scenes.py <photo_dir> [property_info_file] [language]")
        print("  Add --dry-run to only output the API request.")
        sys.exit(1)

    import os

    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]

    photo_dir = args[0]
    photos = sorted(
        f for f in os.listdir(photo_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    )

    prop_info = ""
    if len(args) > 1 and os.path.isfile(args[1]):
        prop_info = Path(args[1]).read_text()

    language = args[2] if len(args) > 2 else "en"

    if dry_run:
        request = build_scene_plan_request(photos, prop_info, language)
        print(json.dumps(request, indent=2, default=str))
    else:
        scenes = run(photo_dir, prop_info, language)
        print(f"🎬 Planned {len(scenes)} scenes:\n")
        for s in scenes:
            print(f"  [{s['sequence']}] {s['first_frame']} → {s['last_frame']}")
            print(f"      {s['scene_desc']}")
            print(f"      🎤 {s['text_narration']}\n")
