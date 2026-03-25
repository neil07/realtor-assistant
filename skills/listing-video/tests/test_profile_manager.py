#!/usr/bin/env python3
"""Tests for profile_manager — agent profile CRUD."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import profile_manager


def _with_tmp_profiles(func):
    """Decorator to redirect PROFILES_DIR to a temp directory."""
    def wrapper(*args, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(profile_manager, "PROFILES_DIR", Path(tmp)):
                return func(tmp, *args, **kwargs)
    return wrapper


# --- create & get ---

@_with_tmp_profiles
def test_create_and_get(tmp):
    p = profile_manager.create_profile("+1234567890", "Alice", brokerage="KW", city="Frisco")
    assert p["name"] == "Alice"
    assert p["brokerage"] == "KW"
    assert p["preferences"]["style"] == "professional"
    assert p["stats"]["videos_created"] == 0

    loaded = profile_manager.get_profile("+1234567890")
    assert loaded["name"] == "Alice"


@_with_tmp_profiles
def test_get_nonexistent_returns_none(tmp):
    assert profile_manager.get_profile("+9999999999") is None


@_with_tmp_profiles
def test_phone_sanitization(tmp):
    profile_manager.create_profile("+1 (234) 567-8901", "Bob")
    # Should be retrievable with sanitized phone
    loaded = profile_manager.get_profile("+12345678901")
    assert loaded["name"] == "Bob"


# --- update ---

@_with_tmp_profiles
def test_update_profile(tmp):
    profile_manager.create_profile("+111", "Carol")
    updated = profile_manager.update_profile("+111", {"name": "Carol Jr."})
    assert updated["name"] == "Carol Jr."


@_with_tmp_profiles
def test_update_deep_merge(tmp):
    profile_manager.create_profile("+222", "Dave")
    updated = profile_manager.update_profile("+222", {"preferences": {"style": "elegant"}})
    # style changed but music should remain
    assert updated["preferences"]["style"] == "elegant"
    assert updated["preferences"]["music"] == "modern"


@_with_tmp_profiles
def test_update_nonexistent(tmp):
    result = profile_manager.update_profile("+999", {"name": "Ghost"})
    assert result["status"] == "error"


# --- increment_video_count ---

@_with_tmp_profiles
def test_increment_video_count(tmp):
    profile_manager.create_profile("+333", "Eve")
    assert profile_manager.increment_video_count("+333") == 1
    assert profile_manager.increment_video_count("+333") == 2
    assert profile_manager.increment_video_count("+333") == 3


@_with_tmp_profiles
def test_increment_nonexistent(tmp):
    assert profile_manager.increment_video_count("+999") == 0


# --- voice clone helpers ---

@_with_tmp_profiles
def test_set_voice_clone(tmp):
    profile_manager.create_profile("+444", "Frank")
    result = profile_manager.set_voice_clone("+444", "voice_abc123")
    assert result["voice_clone_id"] == "voice_abc123"


@_with_tmp_profiles
def test_should_offer_voice_clone(tmp):
    profile_manager.create_profile("+555", "Grace")
    # No videos yet
    assert profile_manager.should_offer_voice_clone("+555") is False
    # After first video
    profile_manager.increment_video_count("+555")
    assert profile_manager.should_offer_voice_clone("+555") is True
    # After marking offered
    profile_manager.mark_voice_clone_offered("+555")
    assert profile_manager.should_offer_voice_clone("+555") is False


@_with_tmp_profiles
def test_should_not_offer_if_already_cloned(tmp):
    profile_manager.create_profile("+666", "Hank")
    profile_manager.increment_video_count("+666")
    profile_manager.set_voice_clone("+666", "voice_xyz")
    assert profile_manager.should_offer_voice_clone("+666") is False


# --- is_first_time ---

@_with_tmp_profiles
def test_is_first_time(tmp):
    assert profile_manager.is_first_time("+777") is True
    profile_manager.create_profile("+777", "Ivy")
    assert profile_manager.is_first_time("+777") is False


# --- set_logo & add_market_knowledge ---

@_with_tmp_profiles
def test_set_logo(tmp):
    profile_manager.create_profile("+888", "Jack")
    result = profile_manager.set_logo("+888", "/path/to/logo.png")
    assert result["logo_path"] == "/path/to/logo.png"


@_with_tmp_profiles
def test_add_market_knowledge(tmp):
    profile_manager.create_profile("+101", "Kate")
    result = profile_manager.add_market_knowledge("+101", "avg_price", "$500k")
    assert result["market_knowledge"]["avg_price"] == "$500k"


@_with_tmp_profiles
def test_add_market_knowledge_nonexistent(tmp):
    result = profile_manager.add_market_knowledge("+999", "x", "y")
    assert result["status"] == "error"


# --- normalize_profile ---

def test_normalize_old_format():
    old = {
        "phone": "+100",
        "name": "Legacy",
        "style": "elegant",
        "music_preference": "piano",
        "show_price": False,
        "videos_created": 5,
        "voice_clone": "vc_old",
    }
    result = profile_manager.normalize_profile(old)
    assert result["preferences"]["style"] == "elegant"
    assert result["preferences"]["music"] == "piano"
    assert result["preferences"]["show_price"] is False
    assert result["stats"]["videos_created"] == 5
    assert result["voice_clone_id"] == "vc_old"
    assert result["voice_clone_offered"] is False
    assert result["logo_path"] is None


def test_normalize_already_current():
    current = {
        "phone": "+200",
        "name": "Modern",
        "preferences": {"style": "professional", "music": "modern", "format": "both",
                        "show_price": True, "language": "en"},
        "stats": {"videos_created": 2, "first_use": "2025-01-01", "last_use": "2025-06-01"},
        "voice_clone_id": None,
        "voice_clone_offered": False,
        "logo_path": None,
        "brokerage": "",
        "city": "",
        "market_knowledge": {},
    }
    result = profile_manager.normalize_profile(current.copy())
    assert result["preferences"]["style"] == "professional"
    assert result["stats"]["videos_created"] == 2
