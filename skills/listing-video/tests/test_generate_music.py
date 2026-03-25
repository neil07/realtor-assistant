#!/usr/bin/env python3
"""Tests for generate_music — prompt building and stock selection."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from generate_music import build_music_prompt, select_stock_music, _STOCK_MAP


# --- build_music_prompt ---

def test_prompt_elegant_luxury():
    prompt = build_music_prompt("elegant", "luxury", "elegant")
    assert "piano" in prompt.lower()
    assert "real estate" in prompt.lower()


def test_prompt_energetic_mid():
    prompt = build_music_prompt("modern", "mid_range", "energetic")
    assert "upbeat" in prompt.lower()


def test_prompt_default_fallback():
    prompt = build_music_prompt("unknown", "unknown", "unknown")
    assert "cinematic" in prompt.lower()


def test_prompt_with_bpm_range():
    prompt = build_music_prompt("modern", "luxury", "professional", bpm_range=(85, 95))
    assert "85-95 BPM" in prompt


def test_prompt_without_bpm():
    prompt = build_music_prompt("modern", "luxury", "professional")
    # Should not have extra BPM appended beyond what's in the style prompt
    assert "real estate" in prompt


# --- select_stock_music ---

def test_select_stock_existing_category(tmp_path):
    music_dir = tmp_path / "music"
    cat_dir = music_dir / "modern_chill"
    cat_dir.mkdir(parents=True)
    (cat_dir / "track1.mp3").write_bytes(b"\x00")

    with patch("generate_music.STOCK_MUSIC_DIR", music_dir):
        result = select_stock_music("modern_chill")
        assert result["status"] == "success"
        assert result["engine"] == "stock"
        assert "track1.mp3" in result["music_path"]


def test_select_stock_maps_style(tmp_path):
    music_dir = tmp_path / "music"
    cat_dir = music_dir / "piano_ambient"
    cat_dir.mkdir(parents=True)
    (cat_dir / "soft.mp3").write_bytes(b"\x00")

    with patch("generate_music.STOCK_MUSIC_DIR", music_dir):
        # "chill_ambient" maps to "piano_ambient"
        result = select_stock_music("chill_ambient")
        assert result["status"] == "success"


def test_select_stock_no_music_dir(tmp_path):
    with patch("generate_music.STOCK_MUSIC_DIR", tmp_path / "nonexistent"):
        result = select_stock_music("modern_chill")
        assert result["status"] == "error"


def test_select_stock_empty_category(tmp_path):
    music_dir = tmp_path / "music"
    cat_dir = music_dir / "modern_chill"
    cat_dir.mkdir(parents=True)
    # No tracks in directory

    with patch("generate_music.STOCK_MUSIC_DIR", music_dir):
        result = select_stock_music("modern_chill")
        assert result["status"] == "error"


def test_select_stock_fallback_to_any_category(tmp_path):
    """When requested category doesn't exist, falls back to any available."""
    music_dir = tmp_path / "music"
    other_dir = music_dir / "acoustic_warm"
    other_dir.mkdir(parents=True)
    (other_dir / "guitar.wav").write_bytes(b"\x00")

    with patch("generate_music.STOCK_MUSIC_DIR", music_dir):
        result = select_stock_music("modern_chill")  # no modern_chill dir
        assert result["status"] == "success"
