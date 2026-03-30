#!/usr/bin/env python3
"""
Listing Video Agent — Photo Analysis

Analyzes listing photos using Claude Vision API.
Outputs structured JSON for downstream pipeline.

Supports two image delivery modes:
  - base64 (default): encode images locally, no pre-upload needed
  - Files API: upload once, pass file_ids for reuse across pipeline steps
"""

import base64
import json
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

ANALYSIS_PROMPT = (Path(__file__).parent.parent / "prompts" / "photo_analysis.md").read_text()


def encode_image(image_path: str) -> dict:
    """Encode image to base64 for API call."""
    with open(image_path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    ext = Path(image_path).suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_types.get(ext, "image/jpeg"),
            "data": data,
        },
    }


def upload_photos_to_files_api(photo_paths: list[str]) -> list[str]:
    """
    Upload listing photos to Anthropic Files API.

    Upload once per pipeline job and pass the returned file_ids to
    analyze_photos(), plan_scenes(), and write_video_prompts() to avoid
    re-encoding base64 on every call.

    Args:
        photo_paths: Local file paths to upload.

    Returns:
        List of Anthropic file_ids in the same order as photo_paths.
    """
    client = anthropic.Anthropic()
    file_ids = []
    ext_to_mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    for path in photo_paths:
        ext = Path(path).suffix.lower()
        mime = ext_to_mime.get(ext, "image/jpeg")
        with open(path, "rb") as f:
            uploaded = client.beta.files.upload(
                file=(Path(path).name, f, mime),
            )
        file_ids.append(uploaded.id)
    return file_ids


def analyze_photos(
    photo_paths: list[str],
    file_ids: list[str] | None = None,
) -> dict:
    """
    Build a Claude API request to analyze a batch of listing photos.

    Args:
        photo_paths: List of file paths (used for base64 when file_ids is None,
                     or just for labelling when file_ids is provided).
        file_ids: Optional Anthropic Files API file_ids. When provided, images
                  are referenced by ID instead of inline base64.

    Returns:
        Claude API request dict. Pass to client.messages.create() (base64 mode)
        or client.beta.messages.create(..., betas=["files-api-2025-04-14"])
        (Files API mode).
    """
    content = []

    if file_ids is not None:
        # Files API mode: reference uploaded images by ID
        for i, (path, fid) in enumerate(zip(photo_paths, file_ids), 1):
            content.append({"type": "text", "text": f"Photo {i}:"})
            content.append({
                "type": "image",
                "source": {"type": "file", "file_id": fid},
            })
    else:
        # Default: inline base64 encoding
        for i, path in enumerate(photo_paths, 1):
            content.append({"type": "text", "text": f"Photo {i}:"})
            content.append(encode_image(path))

    content.append({
        "type": "text",
        "text": ANALYSIS_PROMPT + "\n\nAnalyze these listing photos and return the JSON structure as specified.",
    })

    return {
        "model": "claude-sonnet-4-6",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": content}],
    }


def run(
    photo_paths: list[str],
    file_ids: list[str] | None = None,
) -> dict:
    """
    Run photo analysis end-to-end: build request → call Claude API → parse result.

    Args:
        photo_paths: List of file paths to property photos.
        file_ids: Optional pre-uploaded Anthropic file_ids. When provided,
                  uses Files API instead of base64 (faster on repeat calls).

    Returns:
        Parsed analysis dict (see photo_analysis.md for schema).
    """
    import time

    request = analyze_photos(photo_paths, file_ids=file_ids)
    # max_retries=4 covers 408/429/500/502/503/504; 529 handled manually below
    client = anthropic.Anthropic(max_retries=4)

    for attempt in range(5):
        try:
            if file_ids is not None:
                response = client.beta.messages.create(
                    **request, betas=["files-api-2025-04-14"]
                )
            else:
                response = client.messages.create(**request)
            break  # success
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < 4:
                wait = 10 * (attempt + 1)  # 10s, 20s, 30s, 40s
                print(f"[analyze_photos] API overloaded (529), retrying in {wait}s... (attempt {attempt+1}/5)")
                time.sleep(wait)
            else:
                raise

    raw = response.content[0].text

    # Extract JSON from response (may be wrapped in markdown code block)
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]  # remove first ```json line
        text = text.rsplit("```", 1)[0]  # remove closing ```

    return json.loads(text)


def sort_photos(analysis: dict) -> list[dict]:
    """Sort analyzed photos into walk-through order."""
    order = [
        "aerial", "exterior", "living", "dining", "kitchen",
        "master_bedroom", "bedroom", "master_bath", "bathroom",
        "office", "laundry", "garage", "backyard", "pool", "other",
    ]
    photos = analysis.get("photos", [])
    return sorted(photos, key=lambda p: (
        order.index(p["room_type"]) if p["room_type"] in order else 99,
        -p.get("quality_score", 5),
    ))


def select_ai_clips(photos: list[dict], max_clips: int = 4) -> list[int]:
    """Select which photos should get AI video treatment."""
    ai_worthy = [p for p in photos if p.get("ai_video_worthy", False)]
    ai_worthy.sort(key=lambda p: p.get("video_order", 99))
    return [p["index"] for p in ai_worthy[:max_clips]]


def format_analysis_message(analysis: dict) -> str:
    """Format analysis into a human-readable WhatsApp message."""
    photos = analysis.get("photos", [])
    summary = analysis.get("property_summary", {})

    lines = ["📸 Got your photos! Here's what I see:\n"]

    for p in photos:
        emoji = {
            "exterior": "🏠", "living": "🛋️", "kitchen": "🍳",
            "dining": "🍽️", "master_bedroom": "🛏️", "bedroom": "🛏️",
            "master_bath": "🚿", "bathroom": "🚿", "backyard": "🌳",
            "pool": "🏊", "garage": "🚗", "aerial": "🚁",
            "office": "💻", "laundry": "👕",
        }.get(p["room_type"], "📷")

        line = f"{p['index']}. {emoji} {p['room_type'].replace('_', ' ').title()}"
        if p.get("highlights"):
            line += f" — {', '.join(p['highlights'][:2])}"
        if p.get("quality_issues"):
            line += f"\n   ⚠️ {p['quality_issues'][0]}"
        lines.append(line)

    if summary.get("missing_shots"):
        lines.append(f"\n📝 Could use: {', '.join(summary['missing_shots'])}")

    lines.append(f"\n🏷️ Looks like a {summary.get('estimated_style', 'nice')} "
                 f"{summary.get('estimated_tier', '').replace('_', ' ')} property")

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: analyze_photos.py <photo1> [photo2] ...")
        print("  Add --dry-run to only output the API request.")
        print("  Add --files-api to upload and use Anthropic Files API.")
        sys.exit(1)

    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in sys.argv
    use_files_api = "--files-api" in sys.argv

    if dry_run:
        request = analyze_photos(paths)
        print(json.dumps(request, indent=2, default=str))
    else:
        fids = None
        if use_files_api:
            print(f"📤 Uploading {len(paths)} photos to Files API...")
            fids = upload_photos_to_files_api(paths)
            print(f"   file_ids: {fids}")

        result = run(paths, file_ids=fids)
        sorted_photos = sort_photos(result)
        ai_clips = select_ai_clips(sorted_photos)
        print(format_analysis_message(result))
        print(f"\n🎥 AI video candidates: photos {ai_clips}")
        print(f"\n📋 Raw JSON:\n{json.dumps(result, indent=2)}")
