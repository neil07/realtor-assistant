#!/usr/bin/env python3
"""Tests for config — path constants and template loader."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from config import resolution_for_aspect, load_template, TEMPLATES_DIR


# --- resolution_for_aspect ---

def test_vertical_resolution():
    assert resolution_for_aspect("9:16") == (1080, 1920)


def test_horizontal_resolution():
    assert resolution_for_aspect("16:9") == (1920, 1080)


def test_unknown_aspect_defaults_to_vertical():
    assert resolution_for_aspect("4:3") == (1080, 1920)
    assert resolution_for_aspect("") == (1080, 1920)


# --- load_template ---

def test_load_existing_template():
    """Should load the template JSON if the file exists."""
    with tempfile.TemporaryDirectory() as tmp:
        t_dir = Path(tmp)
        (t_dir / "elegant.json").write_text(json.dumps({"name": "elegant", "speed": "slow"}))
        (t_dir / "professional.json").write_text(json.dumps({"name": "professional"}))

        with patch("config.TEMPLATES_DIR", t_dir):
            result = load_template("elegant")
            assert result["name"] == "elegant"
            assert result["speed"] == "slow"


def test_load_template_falls_back_to_professional():
    """Unknown style falls back to professional.json."""
    with tempfile.TemporaryDirectory() as tmp:
        t_dir = Path(tmp)
        (t_dir / "professional.json").write_text(json.dumps({"name": "professional"}))

        with patch("config.TEMPLATES_DIR", t_dir):
            result = load_template("nonexistent_style")
            assert result["name"] == "professional"
