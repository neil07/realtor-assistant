#!/usr/bin/env python3
"""Tests for generate_script — voiceover script parsing and validation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from generate_script import parse_script_response, validate_script, extract_city


# --- extract_city ---

def test_extract_city_normal():
    assert extract_city("123 Oak St, Frisco, TX 75034") == "Frisco"


def test_extract_city_short_address():
    assert extract_city("123 Oak St") == "your area"


def test_extract_city_multi_comma():
    assert extract_city("Unit 5, 123 Oak St, Dallas, TX") == "Dallas"


# --- parse_script_response ---

def test_parse_all_sections():
    text = """
[HOOK]
Pool first. Questions later.

[WALK-THROUGH]
Walk in through the double doors and the first thing you notice is space.
The kitchen island is massive.

[CLOSER]
Listings like this in Frisco don't last. Call me.

CAPTION: Just listed in Frisco
PHOTO SEQUENCE: [1, 3, 2, 5, 4]
"""
    result = parse_script_response(text)
    assert "Pool first" in result["hook"]
    assert "kitchen island" in result["walkthrough"]
    assert "don't last" in result["closer"]
    assert result["caption"] == "Just listed in Frisco"
    assert result["photo_sequence"] == [1, 3, 2, 5, 4]
    assert result["word_count"] > 0
    assert result["estimated_duration"] > 0


def test_parse_empty_response():
    result = parse_script_response("")
    assert result["full_script"] == ""
    assert result["word_count"] == 0


def test_parse_no_sections():
    result = parse_script_response("Just some random text without markers")
    assert result["hook"] == ""
    assert result["walkthrough"] == ""
    assert result["closer"] == ""


def test_parse_ignores_matches_line():
    text = "[HOOK]\nGreat hook\n→ matches: photo_1\n[CLOSER]\nEnd"
    result = parse_script_response(text)
    assert "matches" not in result["hook"]


def test_parse_invalid_photo_sequence():
    text = "[HOOK]\nHook\nPHOTO SEQUENCE: not json"
    result = parse_script_response(text)
    assert result["photo_sequence"] == []


def test_estimated_duration_calculation():
    text = "[HOOK]\n" + " ".join(["word"] * 35)  # 35 words
    result = parse_script_response(text)
    assert abs(result["estimated_duration"] - 35 / 3.5) < 0.1


# --- validate_script ---

def _make_script(word_count=110, hook="Here's the thing about this place",
                 walkthrough="The kitchen sold me immediately", closer="Call now"):
    words = " ".join(["word"] * word_count)
    full = f"{hook} {walkthrough} {closer} {words}"
    return {
        "hook": hook,
        "walkthrough": walkthrough,
        "closer": closer,
        "full_script": full,
        "word_count": len(full.split()),
    }


def test_validate_good_script():
    script = _make_script()
    issues = validate_script(script)
    assert issues == []


def test_validate_too_short():
    script = _make_script(word_count=10)
    # Recalculate word_count
    script["word_count"] = len(script["full_script"].split())
    issues = validate_script(script)
    assert any("short" in i.lower() for i in issues)


def test_validate_too_long():
    script = _make_script(word_count=200)
    script["word_count"] = len(script["full_script"].split())
    issues = validate_script(script)
    assert any("long" in i.lower() for i in issues)


def test_validate_bad_opening():
    script = _make_script(hook="hey guys check this out")
    script["word_count"] = len(script["full_script"].split())
    issues = validate_script(script)
    assert any("Bad opening" in i for i in issues)


def test_validate_cliche_detected():
    script = _make_script(walkthrough="This stunning home is amazing and sold me")
    script["word_count"] = len(script["full_script"].split())
    issues = validate_script(script)
    assert any("stunning home" in i for i in issues)


def test_validate_missing_opinion():
    script = {
        "hook": "Great location",
        "walkthrough": "Nice kitchen and big rooms",
        "closer": "Call today",
        "full_script": "Great location Nice kitchen and big rooms Call today " + " ".join(["w"] * 100),
        "word_count": 106,
    }
    issues = validate_script(script)
    assert any("personal opinion" in i.lower() for i in issues)


def test_validate_multiple_issues():
    """A script can have multiple issues at once."""
    script = {
        "hook": "welcome to this beautiful property",
        "walkthrough": "This stunning home boasts great features",
        "closer": "Bye",
        "full_script": "welcome to this beautiful property This stunning home boasts great features Bye",
        "word_count": 12,
    }
    issues = validate_script(script)
    # Should flag: too short, bad opening, clichés, missing opinion
    assert len(issues) >= 3
