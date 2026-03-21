#!/usr/bin/env python3
"""
Listing Video Agent — Photo Analysis
Analyzes listing photos using Claude Vision API.
Outputs structured JSON for downstream pipeline.
"""

import json
import sys
import base64
import os
from pathlib import Path

# Will use anthropic SDK or call via OpenClaw's built-in
# For now, this is the interface definition

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


def analyze_photos(photo_paths: list[str]) -> dict:
    """
    Analyze a batch of listing photos.
    
    Args:
        photo_paths: List of file paths to property photos
        
    Returns:
        Structured analysis dict (see photo_analysis.md for schema)
    """
    # Build message content with all images
    content = []
    for i, path in enumerate(photo_paths, 1):
        content.append({"type": "text", "text": f"Photo {i}:"})
        content.append(encode_image(path))

    content.append({
        "type": "text",
        "text": ANALYSIS_PROMPT + "\n\nAnalyze these listing photos and return the JSON structure as specified.",
    })

    # TODO: Call Claude API via anthropic SDK or subprocess
    # For now, return the message structure for OpenClaw to use
    return {
        "model": "claude-sonnet-4-6-20250514",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": content}],
    }


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
    # Sort by video order, take top N
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


def analyze_photos_live(photo_paths: list[str]) -> dict:
    """
    Call Claude Vision to analyze listing photos. Returns parsed analysis dict.

    This is the live version that actually calls the API, as opposed to
    analyze_photos() which only builds the request dict.
    """
    from api_client import call_claude_json

    request = analyze_photos(photo_paths)
    return call_claude_json(request)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Analyze listing photos using Claude Vision")
    parser.add_argument("photos", nargs="+", help="Photo file paths")
    parser.add_argument("--live", action="store_true", help="Call Claude API (not just build request)")
    args = parser.parse_args()

    if args.live:
        result = analyze_photos_live(args.photos)
    else:
        result = analyze_photos(args.photos)

    print(json.dumps(result, indent=2, default=str))
