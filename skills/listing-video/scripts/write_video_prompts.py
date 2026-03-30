#!/usr/bin/env python3
"""
Listing Video Agent — AI Video Prompt Writer
Uses Claude Vision to write per-scene video generation prompts
by analyzing the actual first+last frame images.

Replaces the template-based build_motion_prompt() with context-aware,
image-specific prompts.
"""

import asyncio
import json
import re
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

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
        "model": "claude-sonnet-4-6",
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


def run_single(
    first_frame_path: str,
    scene_desc: str,
    last_frame_path: str = None,
) -> str:
    """
    Run prompt writing for a single scene: build request → call Claude API → parse.

    Returns:
        Video generation prompt string
    """
    request = build_prompt_request(first_frame_path, scene_desc, last_frame_path)
    client = anthropic.Anthropic()
    response = client.messages.create(**request)
    return parse_prompt_response(response.content[0].text)


def run_batch(scenes: list[dict], photo_dir: str) -> list[dict]:
    """
    Run prompt writing for all scenes in a plan.

    Args:
        scenes: Scene plan from plan_scenes.parse_scene_plan()
        photo_dir: Directory containing source photos

    Returns:
        List of dicts: [{"sequence": int, "motion_prompt": str}, ...]
    """
    requests = build_batch_prompt_requests(scenes, photo_dir)
    client = anthropic.Anthropic()
    results = []

    for seq, req in requests:
        response = client.messages.create(**req)
        prompt = parse_prompt_response(response.content[0].text)
        results.append({"sequence": seq, "motion_prompt": prompt})

    return results


async def _write_single_async(
    seq: int,
    request: dict,
    client: anthropic.AsyncAnthropic,
    semaphore: asyncio.Semaphore,
) -> dict | Exception:
    """Write a single scene prompt asynchronously with concurrency control."""
    async with semaphore:
        response = await client.messages.create(**request)
        prompt = parse_prompt_response(response.content[0].text)
        return {"sequence": seq, "motion_prompt": prompt}


async def run_batch_async(scenes: list[dict], photo_dir: str) -> list[dict]:
    """
    Run prompt writing for all scenes concurrently (max 3 parallel).

    Drop-in async replacement for run_batch(). Use with:
        results = await run_batch_async(scenes, photo_dir)
    or from sync code:
        results = asyncio.run(run_batch_async(scenes, photo_dir))

    Failed scenes are skipped (logged to stderr). Successful results are
    returned sorted by sequence number.

    Args:
        scenes: Scene plan from plan_scenes.parse_scene_plan()
        photo_dir: Directory containing source photos

    Returns:
        List of dicts sorted by sequence: [{"sequence": int, "motion_prompt": str}, ...]
    """
    requests = build_batch_prompt_requests(scenes, photo_dir)
    if not requests:
        return []

    async with anthropic.AsyncAnthropic() as async_client:
        semaphore = asyncio.Semaphore(3)
        tasks = [
            _write_single_async(seq, req, async_client, semaphore)
            for seq, req in requests
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    results = []
    for r in raw_results:
        if isinstance(r, Exception):
            print(f"[write_video_prompts] scene failed: {r}", file=sys.stderr)
        else:
            results.append(r)
    return sorted(results, key=lambda x: x["sequence"])


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: write_video_prompts.py <first_frame> <scene_desc> [last_frame]")
        print("  Add --dry-run to only output the API request.")
        sys.exit(1)

    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]

    if dry_run:
        req = build_prompt_request(
            first_frame_path=args[0],
            scene_desc=args[1],
            last_frame_path=args[2] if len(args) > 2 else None,
        )
        print(json.dumps(req, indent=2, default=str))
    else:
        prompt = run_single(
            first_frame_path=args[0],
            scene_desc=args[1],
            last_frame_path=args[2] if len(args) > 2 else None,
        )
        print(f"🎥 Video prompt:\n{prompt}")
