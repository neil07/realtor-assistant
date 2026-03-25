#!/usr/bin/env python3
"""Tests for analyze_photos — sorting, selection, and formatting."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from analyze_photos import sort_photos, select_ai_clips, format_analysis_message, encode_image


# --- sort_photos ---

def test_sort_by_walkthrough_order():
    photos = [
        {"room_type": "kitchen", "quality_score": 8},
        {"room_type": "exterior", "quality_score": 7},
        {"room_type": "pool", "quality_score": 9},
        {"room_type": "living", "quality_score": 6},
    ]
    analysis = {"photos": photos}
    sorted_p = sort_photos(analysis)
    types = [p["room_type"] for p in sorted_p]
    assert types.index("exterior") < types.index("living")
    assert types.index("living") < types.index("kitchen")
    assert types.index("kitchen") < types.index("pool")


def test_sort_same_room_by_quality():
    photos = [
        {"room_type": "bedroom", "quality_score": 5},
        {"room_type": "bedroom", "quality_score": 9},
    ]
    sorted_p = sort_photos({"photos": photos})
    assert sorted_p[0]["quality_score"] == 9


def test_sort_unknown_room_last():
    photos = [
        {"room_type": "other", "quality_score": 8},
        {"room_type": "exterior", "quality_score": 7},
    ]
    sorted_p = sort_photos({"photos": photos})
    assert sorted_p[0]["room_type"] == "exterior"
    assert sorted_p[1]["room_type"] == "other"


def test_sort_empty():
    assert sort_photos({"photos": []}) == []
    assert sort_photos({}) == []


# --- select_ai_clips ---

def test_select_ai_worthy():
    photos = [
        {"index": 1, "ai_video_worthy": True, "video_order": 2},
        {"index": 2, "ai_video_worthy": False, "video_order": 1},
        {"index": 3, "ai_video_worthy": True, "video_order": 1},
        {"index": 4, "ai_video_worthy": True, "video_order": 3},
    ]
    result = select_ai_clips(photos, max_clips=2)
    assert len(result) == 2
    assert result == [3, 1]  # sorted by video_order


def test_select_ai_clips_max():
    photos = [
        {"index": i, "ai_video_worthy": True, "video_order": i}
        for i in range(10)
    ]
    result = select_ai_clips(photos, max_clips=4)
    assert len(result) == 4


def test_select_ai_clips_none_worthy():
    photos = [{"index": 1, "ai_video_worthy": False, "video_order": 1}]
    assert select_ai_clips(photos) == []


# --- format_analysis_message ---

def test_format_basic_message():
    analysis = {
        "photos": [
            {"index": 1, "room_type": "exterior", "highlights": ["curb appeal", "nice lawn"],
             "quality_issues": []},
            {"index": 2, "room_type": "kitchen", "highlights": ["granite counters"],
             "quality_issues": ["slightly dark"]},
        ],
        "property_summary": {
            "missing_shots": ["backyard"],
            "estimated_style": "modern",
            "estimated_tier": "mid_range",
        },
    }
    msg = format_analysis_message(analysis)
    assert "🏠" in msg  # exterior emoji
    assert "🍳" in msg  # kitchen emoji
    assert "curb appeal" in msg
    assert "slightly dark" in msg
    assert "backyard" in msg
    assert "modern" in msg


def test_format_empty_analysis():
    msg = format_analysis_message({"photos": [], "property_summary": {}})
    assert "📸" in msg


# --- encode_image ---

def test_encode_jpeg():
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 10 + b"\xff\xd9")
        f.flush()
        result = encode_image(f.name)
        assert result["type"] == "image"
        assert result["source"]["media_type"] == "image/jpeg"
        assert result["source"]["type"] == "base64"
        assert len(result["source"]["data"]) > 0


def test_encode_png():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG" + b"\x00" * 10)
        f.flush()
        result = encode_image(f.name)
        assert result["source"]["media_type"] == "image/png"
