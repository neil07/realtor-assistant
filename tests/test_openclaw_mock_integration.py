import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import server
from agent.callback_client import CallbackClient
from orchestrator.progress_notifier import ProgressNotifier


class FakeJobManager:
    def __init__(self, jobs_by_phone=None, job=None):
        self.jobs_by_phone = jobs_by_phone or {}
        self.created_jobs = []
        self.job = job or {
            "job_id": "job-prev",
            "photo_dir": "/tmp/photos",
            "params": "{}",
            "callback_url": "https://openclaw.example/events",
        }

    async def list_jobs_by_phone(self, phone: str, limit: int = 1):
        return self.jobs_by_phone.get(phone, [])[:limit]

    async def create_job(self, **kwargs):
        self.created_jobs.append(kwargs)
        return "job-new"

    async def get_job(self, job_id: str):
        return self.job


class FakeDispatcher:
    def __init__(self):
        self.submitted = []

    async def submit(self, job_id: str):
        self.submitted.append(job_id)


class RecordingCallbackClient(CallbackClient):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def send(self, url: str, payload: dict) -> bool:
        self.calls.append({"url": url, "payload": payload})
        return True


def test_api_message_routes_new_user_daily_insight(monkeypatch) -> None:
    import profile_manager

    monkeypatch.setattr(profile_manager, "get_profile", lambda phone: None)
    server._job_mgr = FakeJobManager()

    client = TestClient(server.app)
    response = client.post(
        "/api/message",
        json={"agent_phone": "+10000000000", "text": "daily insight", "has_media": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "daily_insight"
    assert body["action"] == "start_daily_insight"
    assert body["has_profile"] is False


def test_api_message_routes_returning_user_property_content_before_revision(monkeypatch) -> None:
    import profile_manager

    monkeypatch.setattr(
        profile_manager,
        "get_profile",
        lambda phone: {
            "preferences": {"style": "professional"},
            "content_preferences": {"market_area": "Austin", "language": "en"},
            "city": "Austin",
        },
    )
    server._job_mgr = FakeJobManager(
        jobs_by_phone={
            "+10000000000": [{"status": "DELIVERED", "job_id": "job-prev"}],
        }
    )

    client = TestClient(server.app)
    response = client.post(
        "/api/message",
        json={
            "agent_phone": "+10000000000",
            "text": "123 Main St open house this Sunday 2pm",
            "has_media": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "property_content"
    assert body["action"] == "start_property_content"


def test_webhook_in_daily_push_control_updates_profile(monkeypatch) -> None:
    import profile_manager

    update_calls = []

    def fake_update_profile(phone: str, updates: dict):
        update_calls.append((phone, updates))
        return {"phone": phone, **updates}

    monkeypatch.setattr(profile_manager, "update_profile", fake_update_profile)
    server._job_mgr = FakeJobManager()
    server._dispatcher = FakeDispatcher()

    client = TestClient(server.app)
    response = client.post(
        "/webhook/in",
        json={
            "agent_phone": "+10000000000",
            "photo_paths": [],
            "params": {"action": "disable_daily_push"},
        },
    )

    assert response.status_code == 200
    assert response.json() == {"action": "disable_daily_push", "daily_push_enabled": False}
    assert update_calls == [
        (
            "+10000000000",
            {"content_preferences": {"daily_push_enabled": False}},
        )
    ]


def test_webhook_in_generation_path_creates_job_and_submits() -> None:
    fake_job_mgr = FakeJobManager()
    fake_dispatcher = FakeDispatcher()
    server._job_mgr = fake_job_mgr
    server._dispatcher = fake_dispatcher

    client = TestClient(server.app)
    response = client.post(
        "/webhook/in",
        json={
            "agent_phone": "+10000000000",
            "photo_paths": ["/tmp/job-1/photos/front.jpg"],
            "callback_url": "https://openclaw.example/events",
            "openclaw_msg_id": "msg-123",
            "params": {"style": "professional", "language": "en"},
        },
    )

    assert response.status_code == 200
    assert response.json() == {"job_id": "job-new", "status": "QUEUED"}
    assert fake_job_mgr.created_jobs == [
        {
            "agent_phone": "+10000000000",
            "photo_dir": "/tmp/job-1/photos",
            "params": {"style": "professional", "language": "en"},
            "callback_url": "https://openclaw.example/events",
            "openclaw_msg_id": "msg-123",
        }
    ]
    assert fake_dispatcher.submitted == ["job-new"]


def test_progress_notifier_uses_openclaw_events_contract(monkeypatch) -> None:
    monkeypatch.setenv("OPENCLAW_CALLBACK_BASE_URL", "https://openclaw.example")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://reel-agent.example")
    client = RecordingCallbackClient()
    notifier = ProgressNotifier(client)

    import asyncio

    asyncio.run(
        notifier.notify_delivered(
            "job-123",
            {
                "video_path": "/tmp/output/job-123/final.mp4",
                "caption": "Caption",
                "scene_count": 6,
                "word_count": 88,
                "aspect_ratio": "9:16",
            },
            {
                "agent_phone": "+10000000000",
                "openclaw_msg_id": "msg-123",
                "callback_url": "https://openclaw.example/events",
            },
        )
    )

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["url"] == "https://openclaw.example/events"
    assert call["payload"]["type"] == "delivered"
    assert call["payload"]["job_id"] == "job-123"
    assert call["payload"]["openclaw_msg_id"] == "msg-123"
    assert call["payload"]["agent_phone"] == "+10000000000"
    assert call["payload"]["video_url"] == "https://reel-agent.example/output/job-123/final.mp4"
