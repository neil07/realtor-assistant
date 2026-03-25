#!/usr/bin/env python3
"""Tests for write_video_prompts — concurrent prompt generation."""

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add scripts dir to path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


# --- parse_prompt_response ---

from write_video_prompts import parse_prompt_response


def test_parse_with_output_tags():
    text = "<output>\nSlow pan across the living room\n</output>"
    assert parse_prompt_response(text) == "Slow pan across the living room"


def test_parse_with_surrounding_text():
    text = "Here is the prompt:\n<output>\nZoom into kitchen island\n</output>\nDone."
    assert parse_prompt_response(text) == "Zoom into kitchen island"


def test_parse_fallback_no_tags():
    text = "  Aerial view of the backyard  "
    assert parse_prompt_response(text) == "Aerial view of the backyard"


def test_parse_multiline_output():
    text = "<output>\nLine one.\nLine two.\n</output>"
    assert parse_prompt_response(text) == "Line one.\nLine two."


# --- build_batch_prompt_requests ---

from write_video_prompts import build_batch_prompt_requests


def _make_photo(tmp_dir: str, name: str) -> str:
    """Create a tiny dummy JPEG file."""
    path = os.path.join(tmp_dir, name)
    # Minimal JPEG: SOI + EOI markers
    with open(path, "wb") as f:
        f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 20 + b"\xff\xd9")
    return path


def test_build_batch_skips_missing_photos():
    with tempfile.TemporaryDirectory() as tmp:
        _make_photo(tmp, "living.jpg")
        scenes = [
            {"sequence": 1, "first_frame": "living.jpg", "scene_desc": "Living room"},
            {"sequence": 2, "first_frame": "missing.jpg", "scene_desc": "Kitchen"},
        ]
        batch = build_batch_prompt_requests(scenes, tmp)
        assert len(batch) == 1
        assert batch[0][0] == 1


def test_build_batch_with_last_frame():
    with tempfile.TemporaryDirectory() as tmp:
        _make_photo(tmp, "a.jpg")
        _make_photo(tmp, "b.jpg")
        scenes = [
            {"sequence": 1, "first_frame": "a.jpg", "last_frame": "b.jpg", "scene_desc": "Transition"},
        ]
        batch = build_batch_prompt_requests(scenes, tmp)
        assert len(batch) == 1
        # Request should contain both images
        msg_content = batch[0][1]["messages"][0]["content"]
        image_blocks = [b for b in msg_content if b.get("type") == "image"]
        assert len(image_blocks) == 2


def test_build_batch_ignores_missing_last_frame():
    with tempfile.TemporaryDirectory() as tmp:
        _make_photo(tmp, "a.jpg")
        scenes = [
            {"sequence": 1, "first_frame": "a.jpg", "last_frame": "gone.jpg", "scene_desc": "Solo"},
        ]
        batch = build_batch_prompt_requests(scenes, tmp)
        msg_content = batch[0][1]["messages"][0]["content"]
        image_blocks = [b for b in msg_content if b.get("type") == "image"]
        assert len(image_blocks) == 1


# --- Concurrency: _write_prompts_concurrent ---

from write_video_prompts import _write_prompts_concurrent, MAX_CONCURRENCY


def test_concurrent_populates_all_scenes():
    """All scenes get motion_prompt from concurrent API calls."""

    async def _run():
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(5):
                _make_photo(tmp, f"photo_{i}.jpg")

            scenes = [
                {"sequence": i, "first_frame": f"photo_{i}.jpg", "scene_desc": f"Scene {i}"}
                for i in range(5)
            ]

            async def mock_call(req, max_retries=3):
                return "<output>Prompt for scene</output>"

            with patch.dict("sys.modules", {"api_client": MagicMock(call_claude_async=mock_call)}):
                result = await _write_prompts_concurrent(scenes, tmp)

            for scene in result:
                assert "motion_prompt" in scene
                assert scene["motion_prompt"] == "Prompt for scene"

    asyncio.run(_run())


def test_concurrency_limit_respected():
    """At most MAX_CONCURRENCY API calls run simultaneously."""

    async def _run():
        concurrent_count = 0
        max_observed = 0
        lock = asyncio.Lock()

        async def mock_call(req, max_retries=3):
            nonlocal concurrent_count, max_observed
            async with lock:
                concurrent_count += 1
                if concurrent_count > max_observed:
                    max_observed = concurrent_count
            # Simulate API latency
            await asyncio.sleep(0.05)
            async with lock:
                concurrent_count -= 1
            return "<output>test prompt</output>"

        with tempfile.TemporaryDirectory() as tmp:
            for i in range(6):
                _make_photo(tmp, f"p{i}.jpg")

            scenes = [
                {"sequence": i, "first_frame": f"p{i}.jpg", "scene_desc": f"S{i}"}
                for i in range(6)
            ]

            with patch.dict("sys.modules", {"api_client": MagicMock(call_claude_async=mock_call)}):
                await _write_prompts_concurrent(scenes, tmp)

        assert max_observed <= MAX_CONCURRENCY, (
            f"Concurrency {max_observed} exceeded limit {MAX_CONCURRENCY}"
        )
        assert max_observed > 1, "Should run multiple calls concurrently"

    asyncio.run(_run())


# --- write_prompts_live (sync wrapper) ---

def test_write_prompts_live_sync_interface():
    """write_prompts_live returns results through sync interface."""
    from write_video_prompts import write_prompts_live

    with tempfile.TemporaryDirectory() as tmp:
        for i in range(3):
            _make_photo(tmp, f"img{i}.jpg")

        scenes = [
            {"sequence": i, "first_frame": f"img{i}.jpg", "scene_desc": f"Scene {i}"}
            for i in range(3)
        ]

        async def mock_call(req, max_retries=3):
            return "<output>sync test prompt</output>"

        with patch.dict("sys.modules", {"api_client": MagicMock(call_claude_async=mock_call)}):
            result = write_prompts_live(scenes, tmp)

        assert len(result) == 3
        for scene in result:
            assert scene["motion_prompt"] == "sync test prompt"


# --- api_client async ---

def test_call_claude_async_success():
    """call_claude_async returns text on success."""
    # Mock the anthropic module
    mock_block = MagicMock()
    mock_block.text = "response text"
    mock_resp = MagicMock()
    mock_resp.content = [mock_block]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_resp)

    with patch.dict("sys.modules", {"anthropic": MagicMock(AsyncAnthropic=lambda: mock_client)}):
        import importlib
        import api_client
        # Reset singleton
        api_client._async_client = None
        api_client._async_client = mock_client

        result = asyncio.run(api_client.call_claude_async(
            {"model": "test", "max_tokens": 100, "messages": []}
        ))
        assert result == "response text"

        # Cleanup
        api_client._async_client = None


def test_call_claude_async_retries_on_failure():
    """call_claude_async retries with backoff on transient errors."""
    mock_block = MagicMock()
    mock_block.text = "ok"
    mock_resp = MagicMock()
    mock_resp.content = [mock_block]

    mock_client = AsyncMock()
    # Fail first, succeed second
    mock_client.messages.create = AsyncMock(
        side_effect=[Exception("transient"), mock_resp]
    )

    import api_client
    api_client._async_client = mock_client

    result = asyncio.run(api_client.call_claude_async(
        {"model": "test", "max_tokens": 100, "messages": []},
        max_retries=2,
    ))
    assert result == "ok"
    assert mock_client.messages.create.call_count == 2

    api_client._async_client = None


def test_call_claude_async_raises_after_max_retries():
    """call_claude_async raises RuntimeError after exhausting retries."""
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(side_effect=Exception("permanent"))

    import api_client
    api_client._async_client = mock_client

    with pytest.raises(RuntimeError, match="permanent"):
        asyncio.run(api_client.call_claude_async(
            {"model": "test", "max_tokens": 100, "messages": []},
            max_retries=2,
        ))

    api_client._async_client = None
