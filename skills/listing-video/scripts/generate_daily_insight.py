#!/usr/bin/env python3
"""
Reel Agent — Daily Market Insight Generator

Uses Claude Haiku to generate daily real estate market insights
for social media posting. Content is tailored to the agent's market area
and branding preferences.

Weekly content calendar:
  Monday    → Market stat / price trends
  Tuesday   → Buyer tip
  Wednesday → Seller tip
  Thursday  → Neighborhood spotlight
  Friday    → Weekend market wrap / open house reminder

Usage (script mode):
  python generate_daily_insight.py --market-area "Lehigh Valley, PA" --language en

Usage (tool mode):
  from generate_daily_insight import generate, build_insight_request
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import anthropic

# Weekly content rotation
CONTENT_CALENDAR = {
    0: "market_stat",       # Monday
    1: "buyer_tip",         # Tuesday
    2: "seller_tip",        # Wednesday
    3: "neighborhood",      # Thursday
    4: "weekend_wrap",      # Friday
    5: "market_stat",       # Saturday (fallback)
    6: "buyer_tip",         # Sunday (fallback)
}

CONTENT_PROMPTS = {
    "market_stat": (
        "Write a market stat or trend post about {market_area} real estate. "
        "Focus on one compelling data point (price trend, days on market, inventory, etc). "
        "Make it feel current and relevant to spring {year}."
    ),
    "buyer_tip": (
        "Write a practical home buying tip for buyers in {market_area}. "
        "Should be actionable and reassuring — buyers are nervous about today's market."
    ),
    "seller_tip": (
        "Write a home selling tip for {market_area} homeowners thinking about listing. "
        "Focus on something they can do this week to prepare."
    ),
    "neighborhood": (
        "Write a neighborhood spotlight post about a real or representative neighborhood "
        "in {market_area}. Highlight lifestyle, community, or school quality."
    ),
    "weekend_wrap": (
        "Write a friendly weekend market update for {market_area}. "
        "Include: what to expect at open houses this weekend, market temperature, "
        "and an encouraging note for buyers or sellers."
    ),
}

SYSTEM_PROMPT = """You are a real estate social media assistant creating daily content for a real estate agent.

Rules:
- Content is for Facebook/Instagram — keep it conversational, not salesy
- Max 150 words for body text
- Write in the specified language
- Use general knowledge about real estate markets — no made-up specific numbers
- End with an engaging question or call to action
- Tone: warm, professional, helpful (not pushy)
- Add disclaimer where needed: "Market insights are for informational purposes."

Output JSON only:
{
  "topic": "one-line topic description",
  "headline": "catchy headline (max 10 words)",
  "body": "main content (max 150 words)",
  "caption": "social media caption with headline + body + CTA (max 200 words)",
  "hashtags": ["list", "of", "5-8", "relevant", "hashtags"],
  "content_type": "market_stat|buyer_tip|seller_tip|neighborhood|weekend_wrap",
  "cta": "call to action line"
}"""


REFINE_SYSTEM_PROMPT = """You are refining an existing daily real estate social post.

Rules:
- Keep the same core market idea unless the feedback clearly asks to change emphasis
- Respect the user's instruction precisely
- If feedback says 'shorter', make headline/body/caption tighter while keeping the meaning
- If feedback says 'more professional', make tone more polished and confident, but not salesy
- Preserve factual caution: do not invent specific numbers or claims
- Write in the same language as the original unless the feedback explicitly asks otherwise

Output JSON only:
{
  "topic": "one-line topic description",
  "headline": "catchy headline (max 10 words)",
  "body": "main content (max 150 words)",
  "caption": "social media caption with headline + body + CTA (max 200 words)",
  "hashtags": ["list", "of", "5-8", "relevant", "hashtags"],
  "content_type": "market_stat|buyer_tip|seller_tip|neighborhood|weekend_wrap",
  "cta": "call to action line"
}"""


def build_insight_request(
    market_area: str,
    agent_name: str = "",
    language: str = "en",
    content_type: str | None = None,
) -> dict:
    """Tool mode: return request dict for dispatcher."""
    if content_type is None:
        dow = datetime.now().weekday()
        content_type = CONTENT_CALENDAR[dow]

    template = CONTENT_PROMPTS.get(content_type, CONTENT_PROMPTS["market_stat"])
    user_prompt = template.format(
        market_area=market_area,
        year=datetime.now().year,
    )

    if agent_name:
        user_prompt += f"\n\nThe agent's name is {agent_name}. You can mention them naturally."

    if language != "en":
        user_prompt += f"\n\nWrite all content in {language}."

    return {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 512,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }


def generate(
    market_area: str,
    agent_name: str = "",
    language: str = "en",
    content_type: str | None = None,
) -> dict:
    """
    Generate a daily market insight post.

    Args:
        market_area: Geographic area (e.g. "Lehigh Valley, PA")
        agent_name: Agent's name for personalization
        language: Output language code ("en", "zh", "ms")
        content_type: Override content type; if None, uses weekly calendar

    Returns:
        Dict with: topic, headline, body, caption, hashtags, content_type, cta
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    request = build_insight_request(market_area, agent_name, language, content_type)

    response = client.messages.create(**request)
    raw = response.content[0].text.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback structure
        result = {
            "topic": f"{market_area} Real Estate Update",
            "headline": f"What's Happening in {market_area} Real Estate",
            "body": raw[:300],
            "caption": raw[:400],
            "hashtags": ["realestate", market_area.split(",")[0].replace(" ", "").lower()],
            "content_type": content_type or "market_stat",
            "cta": "Comment below or DM me with questions!",
        }

    result.setdefault("content_type", content_type or CONTENT_CALENDAR[datetime.now().weekday()])
    result.setdefault("cta", "Comment below or DM me with questions!")

    return result


def build_refine_insight_request(
    current_insight: dict,
    feedback_text: str,
    agent_name: str = "",
) -> dict:
    """Build a Claude request that refines an existing insight."""
    original = {
        "topic": current_insight.get("topic", ""),
        "headline": current_insight.get("headline", ""),
        "body": current_insight.get("body", ""),
        "caption": current_insight.get("caption", ""),
        "hashtags": current_insight.get("hashtags", []),
        "content_type": current_insight.get("content_type", "market_stat"),
        "cta": current_insight.get("cta", ""),
    }
    user_prompt = (
        "Refine this existing daily insight based on the feedback.\n\n"
        f"Feedback: {feedback_text}\n\n"
        f"Current insight JSON:\n{json.dumps(original, ensure_ascii=False, indent=2)}"
    )
    if agent_name:
        user_prompt += f"\n\nAgent name: {agent_name}"

    return {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 512,
        "system": REFINE_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }


def refine(current_insight: dict, feedback_text: str, agent_name: str = "") -> dict:
    """Refine an existing daily insight post based on user feedback."""
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    request = build_refine_insight_request(current_insight, feedback_text, agent_name)

    response = client.messages.create(**request)
    raw = response.content[0].text.strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {
            "topic": current_insight.get("topic", "Daily Market Insight"),
            "headline": current_insight.get("headline", "Market Insight"),
            "body": current_insight.get("body", "")[:300],
            "caption": raw[:400] or current_insight.get("caption", ""),
            "hashtags": current_insight.get("hashtags", []),
            "content_type": current_insight.get("content_type", "market_stat"),
            "cta": current_insight.get("cta", "Comment below or DM me with questions!"),
        }

    result.setdefault("topic", current_insight.get("topic", "Daily Market Insight"))
    result.setdefault("content_type", current_insight.get("content_type", "market_stat"))
    result.setdefault("hashtags", current_insight.get("hashtags", []))
    result.setdefault("cta", current_insight.get("cta", "Comment below or DM me with questions!"))
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate daily real estate insight")
    parser.add_argument("--market-area", default="Lehigh Valley, PA")
    parser.add_argument("--agent-name", default="")
    parser.add_argument("--language", default="en")
    parser.add_argument("--content-type", default=None,
                        choices=list(CONTENT_PROMPTS.keys()))
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

    print(f"Generating insight for {args.market_area}...")
    result = generate(
        market_area=args.market_area,
        agent_name=args.agent_name,
        language=args.language,
        content_type=args.content_type,
    )

    print(f"\nTopic: {result['topic']}")
    print(f"Headline: {result['headline']}")
    print(f"\nBody:\n{result['body']}")
    print(f"\nCaption:\n{result['caption']}")
    print(f"\nHashtags: {' '.join('#' + t for t in result['hashtags'])}")
    print(f"CTA: {result['cta']}")
