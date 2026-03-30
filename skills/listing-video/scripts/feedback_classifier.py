#!/usr/bin/env python3
"""
Reel Agent — Feedback Classifier

Uses Claude Haiku to classify agent revision feedback into structured
preference updates. Designed to be fast and cheap (~$0.002/call).

Categories:
  - music:   change background music mood/style
  - style:   change overall video style (energetic/elegant/professional)
  - include: add/emphasize something (personal photo, specific room)
  - exclude: remove something
  - pacing:  change video speed or duration
  - general: anything else (stored as free-form note)

Usage (script mode):
  python feedback_classifier.py "换个更活泼的音乐"

Usage (tool mode):
  from feedback_classifier import classify, build_classify_request
"""

import json
import os
import sys

import anthropic

SYSTEM_PROMPT = """You are a real estate video assistant analyzing agent feedback.
Classify the feedback into a structured format.

Output JSON only, no explanation:
{
  "category": "music|style|include|exclude|pacing|general",
  "old_value": "what they disliked (if clear)",
  "new_value": "what they want instead (if clear)",
  "severity": "minor|major",
  "re_run_from": "PRODUCING|SCRIPTING|ANALYZING",
  "summary": "one-line English summary"
}

Re-run rules:
- music/voice/pacing changes → re_run_from: PRODUCING
- style/script/content changes → re_run_from: SCRIPTING
- photo selection/property info changes → re_run_from: ANALYZING

Examples:
- "换个更活泼的音乐" → category: music, old_value: current, new_value: upbeat, re_run_from: PRODUCING
- "风格换成优雅一点" → category: style, new_value: elegant, re_run_from: SCRIPTING
- "加上我的个人照片" → category: include, new_value: personal_photo, re_run_from: PRODUCING
- "节奏太慢了" → category: pacing, new_value: faster, re_run_from: PRODUCING
- "文案重写" → category: general, re_run_from: SCRIPTING"""


def build_classify_request(feedback_text: str) -> dict:
    """Tool mode: return request dict for dispatcher."""
    return {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 256,
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": f"Feedback: {feedback_text}"}
        ],
    }


def classify(feedback_text: str) -> dict:
    """
    Classify agent feedback into structured preference update.

    Args:
        feedback_text: Raw text from agent (any language)

    Returns:
        Dict with keys: category, old_value, new_value, severity,
                        re_run_from, summary
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    request = build_classify_request(feedback_text)

    response = client.messages.create(**request)
    raw = response.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: treat as general feedback
        result = {
            "category": "general",
            "old_value": "",
            "new_value": "",
            "severity": "minor",
            "re_run_from": "SCRIPTING",
            "summary": feedback_text[:100],
        }

    # Ensure all required keys are present
    result.setdefault("category", "general")
    result.setdefault("old_value", "")
    result.setdefault("new_value", "")
    result.setdefault("severity", "minor")
    result.setdefault("re_run_from", "SCRIPTING")
    result.setdefault("summary", feedback_text[:100])

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python feedback_classifier.py '<feedback text>'")
        sys.exit(1)

    feedback = " ".join(sys.argv[1:])
    print(f"Feedback: {feedback}")
    print("\nClassifying...")

    result = classify(feedback)
    print(json.dumps(result, indent=2, ensure_ascii=False))
