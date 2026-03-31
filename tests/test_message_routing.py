import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import _classify_intent

RETURNING_PROFILE = {
    "preferences": {"style": "professional"},
    "content_preferences": {"market_area": "Austin", "language": "en"},
    "city": "Austin",
}


@pytest.mark.parametrize(
    ("text", "expected_intent", "expected_action"),
    [
        ("help", "first_contact", "welcome"),
        ("what can you do?", "first_contact", "welcome"),
        ("daily insight", "daily_insight", "start_daily_insight"),
        (
            "123 Main St open house this Sunday 2pm",
            "property_content",
            "start_property_content",
        ),
        ("stop push", "stop_push", "disable_daily_push"),
        ("resume push", "resume_push", "enable_daily_push"),
    ],
)
def test_new_user_routes_graduation_inputs(
    text: str, expected_intent: str, expected_action: str
) -> None:
    result = _classify_intent(text, False, None, None)
    assert result["intent"] == expected_intent
    assert result["action"] == expected_action


@pytest.mark.parametrize(
    ("text", "expected_intent", "expected_action"),
    [
        ("help", "help", "welcome"),
        ("what can you do?", "help", "welcome"),
        ("daily insight", "daily_insight", "start_daily_insight"),
        (
            "123 Main St open house this Sunday 2pm",
            "property_content",
            "start_property_content",
        ),
        ("stop push", "stop_push", "disable_daily_push"),
        ("resume push", "resume_push", "enable_daily_push"),
    ],
)
def test_returning_user_routes_graduation_inputs(
    text: str,
    expected_intent: str,
    expected_action: str,
) -> None:
    result = _classify_intent(text, False, RETURNING_PROFILE, None)
    assert result["intent"] == expected_intent
    assert result["action"] == expected_action


def test_returning_user_daily_insight_beats_revision_context() -> None:
    result = _classify_intent(
        "daily insight",
        False,
        RETURNING_PROFILE,
        {"status": "DELIVERED"},
    )
    assert result["intent"] == "daily_insight"
    assert result["action"] == "start_daily_insight"


def test_returning_user_property_text_beats_revision_context() -> None:
    result = _classify_intent(
        "123 Main St open house this Sunday 2pm",
        False,
        RETURNING_PROFILE,
        {"status": "DELIVERED"},
    )
    assert result["intent"] == "property_content"
    assert result["action"] == "start_property_content"


def test_remaining_free_text_after_delivery_is_revision() -> None:
    result = _classify_intent(
        "make the music more upbeat",
        False,
        RETURNING_PROFILE,
        {"status": "DELIVERED"},
    )
    assert result["intent"] == "revision"
    assert result["action"] == "submit_feedback"


def test_daily_insight_publish_uses_recent_bridge_state() -> None:
    result = _classify_intent(
        "publish",
        False,
        RETURNING_PROFILE,
        None,
        {
            "lastDailyInsight": {
                "headline": "Inventory is tightening",
                "updatedAt": "2026-04-01T03:00:00+00:00",
            }
        },
    )
    assert result["intent"] == "publish"
    assert result["action"] == "publish"


def test_daily_insight_skip_uses_recent_bridge_state() -> None:
    result = _classify_intent(
        "skip",
        False,
        RETURNING_PROFILE,
        None,
        {
            "lastDailyInsight": {
                "headline": "Inventory is tightening",
                "updatedAt": "2026-04-01T03:00:00+00:00",
            }
        },
    )
    assert result["intent"] == "skip"
    assert result["action"] == "skip"


def test_recent_daily_insight_beats_older_delivered_job_for_skip() -> None:
    result = _classify_intent(
        "skip",
        False,
        RETURNING_PROFILE,
        {"status": "DELIVERED", "updated_at": "2026-04-01T02:30:00+00:00"},
        {
            "lastDailyInsight": {
                "headline": "Inventory is tightening",
                "updatedAt": "2026-04-01T03:00:00+00:00",
            }
        },
    )
    assert result["intent"] == "skip"
    assert result["action"] == "skip"
