"""Tests for voice clone trigger layer (agent/voice_clone_handler.py + server.py integration)."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SCRIPTS_DIR = str(
    Path(__file__).resolve().parents[1] / "skills" / "listing-video" / "scripts"
)
sys.path.insert(0, SCRIPTS_DIR)

from agent.voice_clone_handler import (
    build_proactive_offer,
    classify_voice_clone_intent,
    download_media_to_temp,
    get_active_clone_session,
    should_route_media_to_voice_clone,
)
from server import _classify_intent


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def tmp_clone_dir(tmp_path, monkeypatch):
    """Redirect _OUTPUT_BASE to a temp dir."""
    import agent.voice_clone_handler as handler

    monkeypatch.setattr(handler, "_OUTPUT_BASE", tmp_path)
    return tmp_path


@pytest.fixture
def awaiting_selection_session(tmp_clone_dir):
    """Create an active session in awaiting_selection state."""
    phone = "+15551234567"
    sid = "sess-001"
    sdir = tmp_clone_dir / phone / sid
    sdir.mkdir(parents=True)

    data = {
        "session_id": sid,
        "agent_phone": phone,
        "speakers": [
            {"speaker_id": "speaker_0", "audio_path": "/tmp/sp0.wav", "duration": 20.0},
            {"speaker_id": "speaker_1", "audio_path": "/tmp/sp1.wav", "duration": 12.5},
        ],
        "status": "awaiting_selection",
    }
    (sdir / "session.json").write_text(json.dumps(data))
    return phone, sid, data


@pytest.fixture
def awaiting_confirmation_session(tmp_clone_dir):
    """Create an active session in awaiting_confirmation state."""
    phone = "+15559876543"
    sid = "sess-002"
    sdir = tmp_clone_dir / phone / sid
    sdir.mkdir(parents=True)

    data = {
        "session_id": sid,
        "agent_phone": phone,
        "speakers": [
            {"speaker_id": "speaker_0", "audio_path": "/tmp/sp0.wav", "duration": 25.0},
        ],
        "status": "awaiting_confirmation",
        "voice_id": "voice_abc123",
        "selected_speaker": "speaker_0",
    }
    (sdir / "session.json").write_text(json.dumps(data))
    return phone, sid, data


# ═══════════════════════════════════════════════════════════════════════════
# get_active_clone_session
# ═══════════════════════════════════════════════════════════════════════════


class TestGetActiveCloneSession:

    def test_no_session_dir(self, tmp_clone_dir):
        assert get_active_clone_session("+1999") is None

    def test_finds_awaiting_selection(self, awaiting_selection_session):
        phone, sid, _ = awaiting_selection_session
        session = get_active_clone_session(phone)
        assert session is not None
        assert session["session_id"] == sid
        assert session["status"] == "awaiting_selection"

    def test_finds_awaiting_confirmation(self, awaiting_confirmation_session):
        phone, sid, _ = awaiting_confirmation_session
        session = get_active_clone_session(phone)
        assert session is not None
        assert session["status"] == "awaiting_confirmation"
        assert session["voice_id"] == "voice_abc123"

    def test_ignores_completed_sessions(self, tmp_clone_dir):
        phone = "+15550000"
        sdir = tmp_clone_dir / phone / "sess-done"
        sdir.mkdir(parents=True)
        data = {"session_id": "sess-done", "status": "confirmed"}
        (sdir / "session.json").write_text(json.dumps(data))
        assert get_active_clone_session(phone) is None


# ═══════════════════════════════════════════════════════════════════════════
# classify_voice_clone_intent
# ═══════════════════════════════════════════════════════════════════════════


class TestClassifyVoiceCloneIntent:

    def test_no_session_no_keyword_returns_none(self):
        result = classify_voice_clone_intent("hello", False, "+1555")
        assert result is None

    @pytest.mark.parametrize("text", [
        "clone my voice",
        "I want to use my own voice",
        "voice clone",
        "克隆声音",
        "用我自己的声音",
    ])
    def test_keyword_triggers_request(self, text):
        result = classify_voice_clone_intent(text, False, "+1555")
        assert result is not None
        assert result["intent"] == "voice_clone"
        assert result["action"] == "request_voice_clone"

    def test_awaiting_selection_with_number(self, awaiting_selection_session):
        phone, _, data = awaiting_selection_session
        result = classify_voice_clone_intent("1", False, phone, data)
        assert result is not None
        assert result["intent"] == "voice_clone_select"
        assert result["speaker_id"] == "speaker_0"

    def test_awaiting_selection_with_number_2(self, awaiting_selection_session):
        phone, _, data = awaiting_selection_session
        result = classify_voice_clone_intent("2", False, phone, data)
        assert result["speaker_id"] == "speaker_1"

    def test_awaiting_selection_invalid_text(self, awaiting_selection_session):
        phone, _, data = awaiting_selection_session
        result = classify_voice_clone_intent("what?", False, phone, data)
        assert result["intent"] == "voice_clone_pending"
        assert result["action"] == "prompt_select"

    def test_awaiting_confirmation_confirm(self, awaiting_confirmation_session):
        phone, _, data = awaiting_confirmation_session
        for text in ["yes", "confirm", "ok", "好的", "确认", "use this voice"]:
            result = classify_voice_clone_intent(text, False, phone, data)
            assert result is not None, f"Failed for: {text}"
            assert result["intent"] == "voice_clone_confirm"
            assert result["voice_id"] == "voice_abc123"

    def test_awaiting_confirmation_reject(self, awaiting_confirmation_session):
        phone, _, data = awaiting_confirmation_session
        for text in ["no", "no thanks", "reject", "不要", "cancel"]:
            result = classify_voice_clone_intent(text, False, phone, data)
            assert result is not None, f"Failed for: {text}"
            assert result["intent"] == "voice_clone_reject"
            assert result["voice_id"] == "voice_abc123"

    def test_awaiting_confirmation_ambiguous(self, awaiting_confirmation_session):
        phone, _, data = awaiting_confirmation_session
        result = classify_voice_clone_intent("maybe", False, phone, data)
        assert result["intent"] == "voice_clone_pending"
        assert result["action"] == "prompt_confirm"


# ═══════════════════════════════════════════════════════════════════════════
# should_route_media_to_voice_clone
# ═══════════════════════════════════════════════════════════════════════════


class TestShouldRouteMediaToVoiceClone:

    def test_no_media_returns_false(self):
        assert not should_route_media_to_voice_clone("clone my voice", [], "+1")

    def test_voice_keyword_with_media(self):
        assert should_route_media_to_voice_clone(
            "clone my voice", ["/tmp/video.mp4"], "+1"
        )

    def test_voice_hint_with_media(self):
        assert should_route_media_to_voice_clone(
            "here's my voice sample", ["/tmp/audio.ogg"], "+1"
        )

    def test_no_voice_context_returns_false(self):
        assert not should_route_media_to_voice_clone(
            "here are my listing photos", ["/tmp/photo.jpg"], "+1"
        )


# ═══════════════════════════════════════════════════════════════════════════
# download_media_to_temp
# ═══════════════════════════════════════════════════════════════════════════


class TestDownloadMediaToTemp:

    def test_local_file_exists(self, tmp_path):
        f = tmp_path / "video.mp4"
        f.write_bytes(b"\x00" * 100)
        result = download_media_to_temp(str(f))
        assert result == str(f)

    def test_local_file_missing(self):
        result = download_media_to_temp("/nonexistent/file.mp4")
        assert result is None

    def test_invalid_path(self):
        result = download_media_to_temp("not-a-url-or-path")
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# _classify_intent integration — voice clone in multi-turn flow
# ═══════════════════════════════════════════════════════════════════════════


class TestClassifyIntentVoiceCloneIntegration:

    def test_voice_clone_keyword_detected(self):
        result = _classify_intent(
            "clone my voice", False, None, None, agent_phone="+1555",
        )
        assert result["intent"] == "voice_clone"

    def test_voice_clone_chinese_keyword(self):
        result = _classify_intent(
            "我想用自己的声音录", False, None, None, agent_phone="+1555",
        )
        assert result["intent"] == "voice_clone"

    def test_media_with_voice_context_routes_to_clone(self):
        result = _classify_intent(
            "here's my voice recording",
            True,
            None,
            None,
            media_paths=["/tmp/video.mp4"],
            agent_phone="+1555",
        )
        assert result["intent"] == "voice_clone_media"

    def test_media_without_voice_context_routes_to_listing(self):
        result = _classify_intent(
            "", True, None, None,
            media_paths=["/tmp/photo.jpg"],
            agent_phone="+1555",
        )
        assert result["intent"] == "listing_video"

    def test_awaiting_confirmation_confirm_via_classify(self):
        session = {
            "session_id": "s1",
            "status": "awaiting_confirmation",
            "voice_id": "v123",
            "speakers": [],
        }
        result = _classify_intent(
            "yes", False, None, None,
            active_clone_session=session,
            agent_phone="+1555",
        )
        assert result["intent"] == "voice_clone_confirm"

    def test_awaiting_selection_number_via_classify(self):
        session = {
            "session_id": "s1",
            "status": "awaiting_selection",
            "speakers": [
                {"speaker_id": "speaker_0"},
                {"speaker_id": "speaker_1"},
            ],
        }
        result = _classify_intent(
            "2", False, None, None,
            active_clone_session=session,
            agent_phone="+1555",
        )
        assert result["intent"] == "voice_clone_select"
        assert result["speaker_id"] == "speaker_1"

    def test_normal_intent_unaffected_without_session(self):
        """Voice clone trigger doesn't interfere with normal routing."""
        result = _classify_intent("help", False, None, None, agent_phone="+1555")
        assert result["intent"] == "first_contact"

    def test_daily_insight_unaffected(self):
        result = _classify_intent(
            "daily insight", False, None, None, agent_phone="+1555",
        )
        assert result["intent"] == "daily_insight"


# ═══════════════════════════════════════════════════════════════════════════
# build_proactive_offer
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildProactiveOffer:

    def test_not_eligible_returns_none(self):
        with patch("profile_manager.should_offer_voice_clone", return_value=False):
            result = build_proactive_offer("+1555")
            assert result is None

    def test_eligible_returns_offer(self):
        with (
            patch("profile_manager.should_offer_voice_clone", return_value=True),
            patch("profile_manager.get_profile", return_value={
                "content_preferences": {"language": "en"},
                "preferences": {},
            }),
            patch("profile_manager.mark_voice_clone_offered"),
        ):
            result = build_proactive_offer("+1555")
            assert result is not None
            assert result["intent"] == "voice_clone_offer"
            assert "clone my voice" in result["response"].lower()

    def test_eligible_zh_returns_chinese_offer(self):
        with (
            patch("profile_manager.should_offer_voice_clone", return_value=True),
            patch("profile_manager.get_profile", return_value={
                "content_preferences": {"language": "zh"},
                "preferences": {},
            }),
            patch("profile_manager.mark_voice_clone_offered"),
        ):
            result = build_proactive_offer("+1555")
            assert result is not None
            assert "克隆声音" in result["response"]
