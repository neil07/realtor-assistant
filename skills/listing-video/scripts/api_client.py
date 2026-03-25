#!/usr/bin/env python3
"""
Listing Video Agent — Claude API Unified Client
All Claude calls go through here: lazy singleton, retries, JSON parsing.
"""

import asyncio
import json
import re
import time
import logging

_client = None
_async_client = None
logger = logging.getLogger(__name__)


def get_client():
    """Lazy-load a singleton Anthropic client."""
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


def call_claude(request: dict, max_retries: int = 3) -> str:
    """
    Send a request dict to Claude and return the text response.

    Args:
        request: Dict with "model", "max_tokens", "messages" (standard format
                 used by all stubbed modules).
        max_retries: Exponential backoff retries on transient errors.

    Returns:
        Response text content.
    """
    client = get_client()
    last_error = None

    for attempt in range(max_retries):
        try:
            resp = client.messages.create(
                model=request["model"],
                max_tokens=request["max_tokens"],
                messages=request["messages"],
            )
            # Extract text from response content blocks
            text_parts = [
                block.text for block in resp.content
                if hasattr(block, "text")
            ]
            return "\n".join(text_parts)

        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)  # 2s, 4s, 8s
                logger.warning(
                    "Claude API attempt %d/%d failed: %s — retrying in %ds",
                    attempt + 1, max_retries, e, wait,
                )
                time.sleep(wait)

    raise RuntimeError(f"Claude API failed after {max_retries} retries: {last_error}")


def get_async_client():
    """Lazy-load a singleton async Anthropic client."""
    global _async_client
    if _async_client is None:
        import anthropic
        _async_client = anthropic.AsyncAnthropic()
    return _async_client


async def call_claude_async(request: dict, max_retries: int = 3) -> str:
    """Async version of call_claude for concurrent API calls."""
    client = get_async_client()
    last_error = None

    for attempt in range(max_retries):
        try:
            resp = await client.messages.create(
                model=request["model"],
                max_tokens=request["max_tokens"],
                messages=request["messages"],
            )
            text_parts = [
                block.text for block in resp.content
                if hasattr(block, "text")
            ]
            return "\n".join(text_parts)

        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                logger.warning(
                    "Claude async API attempt %d/%d failed: %s — retrying in %ds",
                    attempt + 1, max_retries, e, wait,
                )
                await asyncio.sleep(wait)

    raise RuntimeError(f"Claude API failed after {max_retries} retries: {last_error}")


def call_claude_json(request: dict, max_retries: int = 3) -> dict:
    """
    Send a request and parse the JSON response.
    Handles ```json code-block wrapping automatically.
    """
    text = call_claude(request, max_retries=max_retries)
    return _parse_json_response(text)


def _parse_json_response(text: str) -> dict:
    """Extract JSON from a response that might be wrapped in ```json blocks."""
    # Try to extract from code block first
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find first { to last }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        # Try array
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise
