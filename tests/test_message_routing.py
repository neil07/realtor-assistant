import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import _classify_intent

RETURNING_PROFILE = {
    "preferences": {"style": "professional"},
    "content_preferences": {"market_area": "Austin", "language": "en"},
    "city": "Austin",
}


def test_new_user_help_routes_to_welcome() -> None:
    result = _classify_intent("help", False, None, None)
    assert result["intent"] == "first_contact"
    assert result["action"] == "welcome"


def test_returning_user_help_phrase_routes_to_help() -> None:
    result = _classify_intent("what can you do?", False, RETURNING_PROFILE, None)
    assert result["intent"] == "help"
    assert result["action"] == "welcome"


def test_new_user_daily_insight_still_routes_to_daily_insight() -> None:
    result = _classify_intent("daily insight", False, None, None)
    assert result["intent"] == "daily_insight"
    assert result["action"] == "start_daily_insight"


def test_new_user_property_text_routes_to_property_content() -> None:
    result = _classify_intent("123 Main St open house this Sunday 2pm", False, None, None)
    assert result["intent"] == "property_content"
    assert result["action"] == "start_property_content"


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
