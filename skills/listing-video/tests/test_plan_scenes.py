#!/usr/bin/env python3
"""Tests for plan_scenes — scene plan parsing and storyboard conversion."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from plan_scenes import parse_scene_plan, scene_plan_to_storyboard


# --- parse_scene_plan ---

def test_parse_with_output_tags():
    response = """
Here is the scene plan:
<output>
[
    {"first_frame": "exterior.jpg", "last_frame": "living.jpg", "scene_desc": "Approach", "text_narration": "Welcome home"},
    {"first_frame": "living.jpg", "last_frame": "kitchen.jpg", "scene_desc": "Interior", "text_narration": "Step inside"}
]
</output>
"""
    scenes = parse_scene_plan(response)
    assert len(scenes) == 2
    assert scenes[0]["sequence"] == 1
    assert scenes[0]["first_frame"] == "exterior.jpg"
    assert scenes[0]["text_narration"] == "Welcome home"
    assert scenes[1]["sequence"] == 2


def test_parse_raw_json():
    response = json.dumps([
        {"first_frame": "a.jpg", "last_frame": "b.jpg", "scene_desc": "X", "text_narration": "Y"}
    ])
    scenes = parse_scene_plan(response)
    assert len(scenes) == 1
    assert scenes[0]["first_frame"] == "a.jpg"


def test_parse_invalid_json():
    assert parse_scene_plan("not json at all") == []


def test_parse_empty_output_tags():
    assert parse_scene_plan("<output>\nnot valid json\n</output>") == []


def test_parse_missing_fields_get_defaults():
    response = '<output>[{"first_frame": "a.jpg"}]</output>'
    scenes = parse_scene_plan(response)
    assert scenes[0]["last_frame"] == ""
    assert scenes[0]["scene_desc"] == ""
    assert scenes[0]["text_narration"] == ""


# --- scene_plan_to_storyboard ---

def test_storyboard_conversion():
    scenes = [
        {"sequence": 1, "first_frame": "ext.jpg", "last_frame": "liv.jpg",
         "scene_desc": "Approach", "text_narration": "Welcome"},
        {"sequence": 2, "first_frame": "liv.jpg", "last_frame": "kit.jpg",
         "scene_desc": "Living", "text_narration": "Step in"},
    ]
    result = scene_plan_to_storyboard(scenes, "/photos")
    entries = result["storyboard"]
    assert len(entries) == 2

    e = entries[0]
    assert e["render_type"] == "ai_video"
    assert e["first_frame_path"] == "/photos/ext.jpg"
    assert e["last_frame_path"] == "/photos/liv.jpg"
    assert e["motion_prompt"] is None  # filled later by write_video_prompts


def test_storyboard_same_first_last_frame():
    """When first_frame == last_frame, last_frame_path should be None."""
    scenes = [
        {"sequence": 1, "first_frame": "room.jpg", "last_frame": "room.jpg",
         "scene_desc": "Static", "text_narration": "Look here"},
    ]
    result = scene_plan_to_storyboard(scenes, "/photos")
    assert result["storyboard"][0]["last_frame_path"] is None


def test_storyboard_empty():
    result = scene_plan_to_storyboard([], "/photos")
    assert result["storyboard"] == []
