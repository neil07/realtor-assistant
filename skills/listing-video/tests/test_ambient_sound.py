#!/usr/bin/env python3
"""Tests for ambient_sound — sound selection logic (no ffmpeg needed)."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from ambient_sound import select_ambient_sounds, AMBIENT_MAP, FEATURE_AMBIENT


# --- select_ambient_sounds ---

def test_indoor_scenes_get_no_ambient():
    scenes = [
        {"sequence": 1, "scene_desc": "Living room with fireplace"},
        {"sequence": 2, "scene_desc": "Modern kitchen"},
    ]
    result = select_ambient_sounds(scenes)
    for r in result:
        assert r["ambient_path"] is None


def test_outdoor_scenes_matched_by_room_type(tmp_path):
    """Pool/backyard/exterior scenes get ambient if sound file exists."""
    # Create fake sound files
    sounds_dir = tmp_path / "sounds"
    sounds_dir.mkdir()
    (sounds_dir / "water_gentle.mp3").write_bytes(b"\x00")
    (sounds_dir / "birds_morning.mp3").write_bytes(b"\x00")

    with patch("ambient_sound.SOUNDS_DIR", sounds_dir):
        scenes = [
            {"sequence": 1, "scene_desc": "Pool area"},
            {"sequence": 2, "scene_desc": "Backyard garden"},
        ]
        result = select_ambient_sounds(scenes)
        assert result[0]["ambient_path"] is not None
        assert "water_gentle" in result[0]["ambient_path"]
        assert result[1]["ambient_path"] is not None
        assert "birds_morning" in result[1]["ambient_path"]


def test_feature_ambient_for_outdoor_scenes(tmp_path):
    """Feature-based ambient applied to outdoor scenes."""
    sounds_dir = tmp_path / "sounds"
    sounds_dir.mkdir()
    (sounds_dir / "waves_distant.mp3").write_bytes(b"\x00")

    with patch("ambient_sound.SOUNDS_DIR", sounds_dir):
        scenes = [
            {"sequence": 1, "scene_desc": "Living room"},
            {"sequence": 2, "scene_desc": "Exterior view"},
        ]
        result = select_ambient_sounds(scenes, property_features=["ocean view"])
        # Indoor scene: no ambient
        assert result[0]["ambient_path"] is None
        # Outdoor scene with ocean feature
        assert result[1]["ambient_path"] is not None
        assert "waves_distant" in result[1]["ambient_path"]


def test_volume_default():
    scenes = [{"sequence": 1, "scene_desc": "test"}]
    result = select_ambient_sounds(scenes)
    assert result[0]["volume"] == 0.08


def test_empty_scene_plan():
    assert select_ambient_sounds([]) == []
