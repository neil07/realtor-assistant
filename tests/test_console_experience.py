import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import console.router as console_router
import server
from console.memory_schema import (
    compute_completeness,
    get_recommended_experience,
    get_recommended_path,
)


def _profile(
    *,
    form_submitted: bool = False,
    style: str = "",
    market_area: str = "",
    city: str = "",
    language: str = "en",
    videos_created: int = 0,
    activation: dict | None = None,
) -> dict:
    profile = {
        "phone": "+15550000000",
        "name": "Natalie",
        "city": city,
        "_form_submitted": form_submitted,
        "preferences": {
            "style": style,
            "language": language,
            "music": "modern",
            "show_price": True,
        },
        "content_preferences": {
            "market_area": market_area,
            "language": language,
            "daily_push_enabled": True,
            "branding_colors": ["#1B2A4A"],
        },
        "business": {"client_demographic": "luxury", "neighborhoods": []},
        "social_media": {"platforms": ["instagram"]},
        "brand": {"tone": "", "tagline": "", "logo_available": False},
        "market": {"trends_interest": []},
        "stats": {"videos_created": videos_created, "first_use": "2026-04-01T00:00:00"},
        "activation": activation or {
            "last_successful_path": "",
            "last_recommended_path": "",
            "first_value_seen": False,
        },
    }
    return profile


def test_recommended_path_uses_last_successful_path() -> None:
    profile = _profile(
        activation={
            "last_successful_path": "insight_first",
            "last_recommended_path": "",
            "first_value_seen": True,
        }
    )
    assert get_recommended_path(profile) == "insight_first"


def test_recommended_path_defaults_to_interview_first_before_first_value() -> None:
    profile = _profile(style="", market_area="", city="")
    assert get_recommended_path(profile) == "interview_first"


def test_recommended_path_prefers_video_when_only_video_ready() -> None:
    profile = _profile(style="professional", city="", market_area="")
    assert get_recommended_path(profile) == "video_first"


def test_recommended_path_prefers_insight_when_only_insight_ready() -> None:
    profile = _profile(style="", market_area="Austin", city="Austin")
    assert get_recommended_path(profile) == "insight_first"


def test_recommended_path_prefers_video_when_both_ready_and_has_history() -> None:
    profile = _profile(
        style="professional",
        market_area="Austin",
        city="Austin",
        videos_created=3,
        activation={
            "last_successful_path": "",
            "last_recommended_path": "",
            "first_value_seen": True,
        },
    )
    assert get_recommended_path(profile) == "video_first"


def test_dashboard_renders_recommended_path_and_next_best_action(monkeypatch) -> None:
    profile = _profile(style="professional", market_area="Austin", city="Austin")
    completeness = compute_completeness(profile)
    guidance = get_recommended_experience(profile, completeness)
    monkeypatch.setattr(
        console_router,
        "_get_all_profiles",
        lambda: [{"profile": profile, "completeness": completeness, "guidance": guidance}],
    )

    client = TestClient(server.app)
    response = client.get("/console/")

    assert response.status_code == 200
    assert "推荐路径" in response.text
    assert "建议下一步" in response.text
    assert guidance["recommended_path_label"] in response.text
    assert guidance["next_best_action"] in response.text


def test_client_detail_renders_next_step_panel(monkeypatch, tmp_path) -> None:
    profile = _profile(style="", market_area="", city="")
    brief_path = tmp_path / "video.md"
    brief_path.write_text("Default video brief", encoding="utf-8")
    default_brief = tmp_path / "default.md"
    default_brief.write_text("Default video brief", encoding="utf-8")

    monkeypatch.setattr(console_router.profile_manager, "get_profile", lambda phone: profile)
    monkeypatch.setattr(console_router.profile_manager, "get_skill_brief_path", lambda phone, skill_type="video": brief_path)
    monkeypatch.setattr(console_router.profile_manager, "init_skill_brief", lambda phone, skill_type="video": brief_path)
    monkeypatch.setattr(console_router.profile_manager, "DEFAULT_BRIEF_PATH", default_brief)

    client = TestClient(server.app)
    response = client.get(f"/console/client/{profile['phone']}")

    assert response.status_code == 200
    assert "建议下一步" in response.text
    assert "recommended_path: interview_first" in response.text


def test_form_done_page_shows_video_and_insight_next_steps(monkeypatch) -> None:
    token = "token-123"
    profile = _profile(form_submitted=False, style="professional", market_area="Austin", city="Austin")
    profile["_form_token"] = token

    monkeypatch.setattr(console_router, "_find_profile_by_token", lambda value: profile if value == token else None)
    monkeypatch.setattr(console_router.profile_manager, "update_profile", lambda phone, updates: {**profile, **updates})

    client = TestClient(server.app)
    response = client.post(
        f"/console/form/{token}/submit",
        data={
            "name": "Natalie",
            "market_area": "Austin",
            "city": "Austin",
            "client_demographic": "luxury",
            "style": "professional",
            "platforms": ["instagram"],
            "language": "en",
        },
    )

    assert response.status_code == 200
    assert "Send 6-10 listing photos" in response.text
    assert 'Reply "daily insight"' in response.text
