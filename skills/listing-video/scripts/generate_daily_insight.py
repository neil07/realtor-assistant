#!/usr/bin/env python3
"""
Reel Agent — Daily Market Insight Generator (v2: Data-Driven Content Pack)

Generates branded, data-backed social media content in the agent's voice.
Replaces the v1 "AI makes up tips" approach with real data from FRED + Redfin.

Output is a Content Pack with 4 layers:
  1. briefing     — agent's private intelligence (talking points for calls/meetings)
  2. social_post  — ready-to-publish caption for Instagram/Facebook/LinkedIn
  3. forward_buyer  — WhatsApp forward for buyer clients
  4. forward_seller — WhatsApp forward for seller clients

Data sources (Phase 1):
  - FRED API: 30yr/15yr mortgage rates + WoW change
  - Redfin Data Center: local median price, inventory, DOM, sale-to-list

Usage (script mode):
  python generate_daily_insight.py --market-area "Lehigh Valley, PA"

Usage (tool mode):
  from generate_daily_insight import generate, build_insight_request
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import anthropic

# ─── Topic Decision Logic ────────────────────────────────────────────────────


def decide_today_topic(
    rate_data: dict | None,
    market_data: dict | None,
) -> tuple[str, dict]:
    """
    Decide today's content topic based on what's most interesting in the data.

    Returns:
        (topic_type, relevant_data)
        topic_type: "rate_move" | "market_update" | "market_steady" | "evergreen"
    """
    # P0: Significant rate movement (>= 10 bps) — most impactful for clients
    if rate_data and rate_data.get("has_data"):
        change = rate_data.get("change_30yr_bps")
        if change is not None and abs(change) >= 10:
            return "rate_move", rate_data

    # P1: Notable local market changes
    if market_data and market_data.get("has_data") and market_data.get("notable_changes"):
        return "market_update", market_data

    # P2: Have market data but no notable changes — stability is also a story
    if market_data and market_data.get("has_data"):
        return "market_steady", market_data

    # P3: Have rate data but no big move — still worth sharing the number
    if rate_data and rate_data.get("has_data"):
        return "rate_update", rate_data

    # Fallback: no data available
    return "evergreen", {}


# ─── Prompt Construction ─────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a social media content assistant for a real estate agent. Your job is to write content in the AGENT'S voice — first person, as if they wrote it themselves.

CRITICAL RULES:
- Write in FIRST PERSON ("I've been tracking...", "Here's what I'm seeing...")
- NEVER use third person ("The agent recommends...", "Buyers should consider...")
- NEVER say "according to data" or "statistics show" — speak as the local expert who KNOWS their market
- Use the EXACT numbers provided in the data — do not round, estimate, or make up any numbers
- Include BOTH buyer and seller perspectives when the data supports it
- End with a soft, personal CTA ("DM me", "happy to chat", "let me know") — never "Contact a real estate agent"
- Keep social_post caption under 200 words
- Keep forward_buyer and forward_seller under 60 words each — these are personal WhatsApp messages
- Tone should match the agent's brand.tone setting (default: warm + professional)
- Add local market name prominently — this builds the "local expert" brand

DO NOT:
- Add disclaimer text about "informational purposes"
- Use cliches: "dream home", "perfect time to buy/sell", "hot market", "don't miss out"
- Use exclamation marks excessively (max 1 per piece)
- Make the content sound like a press release or news article
- Invent or speculate on numbers not in the provided data

Output ONLY valid JSON with this exact structure:
{
  "briefing": {
    "headline": "one-line summary with key number",
    "key_numbers": "compact stats line for quick reference",
    "talking_points_buyers": ["point 1", "point 2"],
    "talking_points_sellers": ["point 1", "point 2"]
  },
  "social_post": {
    "caption": "full social media post in agent's first-person voice, with both buyer/seller angles, ~150-200 words",
    "hashtags": ["relevant", "local", "hashtags", "5-7 total"]
  },
  "forward_buyer": {
    "text": "short WhatsApp message to a buyer client, conversational, ~40-60 words"
  },
  "forward_seller": {
    "text": "short WhatsApp message to a seller client, conversational, ~40-60 words"
  },
  "image_data": {
    "primary_number": "the ONE key number to show biggest on image (e.g. '6.42%')",
    "primary_label": "what the number is (e.g. '30-Year Mortgage Rate')",
    "primary_direction": "up or down or steady",
    "change_label": "the change (e.g. '↓12 bps from last week')",
    "supporting_stats": ["stat 1 (e.g. '412 Active Listings (+8%)')", "stat 2", "stat 3"]
  }
}"""


def _build_data_context(
    rate_data: dict | None,
    market_data: dict | None,
    payment_impact: dict | None,
) -> str:
    """Build the data context string for the prompt."""
    lines = []

    # Always include rate data if available
    if rate_data and rate_data.get("has_data"):
        lines.append("=== MORTGAGE RATES (source: Freddie Mac via FRED) ===")
        lines.append(f"Date: {rate_data['rate_date']}")
        lines.append(f"30-Year Fixed: {rate_data['rate_30yr']:.2f}%")
        if rate_data.get("rate_30yr_prev") is not None:
            lines.append(f"Previous Week: {rate_data['rate_30yr_prev']:.2f}%")
            lines.append(f"Change: {rate_data.get('change_30yr_bps', 0):+d} basis points")
        if rate_data.get("rate_15yr") is not None:
            lines.append(f"15-Year Fixed: {rate_data['rate_15yr']:.2f}%")

    # Payment impact
    if payment_impact and payment_impact.get("has_impact"):
        lines.append("")
        lines.append(f"=== PAYMENT IMPACT (${payment_impact['home_price']:,.0f} home, 20% down) ===")
        lines.append(f"Current monthly payment: ${payment_impact['payment_current']:,.2f}")
        lines.append(f"Previous monthly payment: ${payment_impact['payment_previous']:,.2f}")
        lines.append(f"Difference: {payment_impact['payment_diff_label']}")

    # Local market data if available
    if market_data and market_data.get("has_data"):
        c = market_data["current"]
        lines.append("")
        lines.append(f"=== LOCAL MARKET DATA: {market_data['market_area']} (source: Redfin) ===")
        lines.append(f"Period: {c.get('period_begin', '?')} to {c.get('period_end', '?')}")
        if c.get("median_sale_price") is not None:
            price_str = f"Median Sale Price: ${c['median_sale_price']:,.0f}"
            if c.get("median_sale_price_yoy") is not None:
                price_str += f" ({c['median_sale_price_yoy']:+.1f}% YoY)"
            lines.append(price_str)
        if c.get("inventory") is not None:
            inv_str = f"Active Inventory: {c['inventory']:,} homes"
            chg = market_data.get("changes", {}).get("inventory_change_pct")
            if chg is not None:
                inv_str += f" ({chg:+.0f}% vs prior period)"
            lines.append(inv_str)
        if c.get("median_dom") is not None:
            dom_str = f"Median Days on Market: {c['median_dom']}"
            dom_chg = market_data.get("changes", {}).get("dom_change")
            if dom_chg is not None:
                dom_str += f" ({dom_chg:+d} vs prior period)"
            lines.append(dom_str)
        if c.get("new_listings") is not None:
            lines.append(f"New Listings: {c['new_listings']:,}")
        if c.get("avg_sale_to_list") is not None:
            lines.append(f"Sale-to-List Ratio: {c['avg_sale_to_list']:.1f}%")
        if c.get("price_drops") is not None:
            lines.append(f"Listings with Price Drops: {c['price_drops']:.1f}%")

    if not lines:
        lines.append("No specific market data available for this period.")
        lines.append("Generate a general market awareness post based on current seasonal trends.")

    return "\n".join(lines)


def _build_agent_context(agent_profile: dict) -> str:
    """Build agent personalization context."""
    lines = []

    name = agent_profile.get("name", "")
    if name:
        lines.append(f"Agent name: {name}")

    market = (
        agent_profile.get("content_preferences", {}).get("market_area")
        or agent_profile.get("city", "")
    )
    if market:
        lines.append(f"Market area: {market}")

    tone = agent_profile.get("brand", {}).get("tone", "warm + professional")
    lines.append(f"Brand tone: {tone or 'warm + professional'}")

    tagline = agent_profile.get("brand", {}).get("tagline", "")
    if tagline:
        lines.append(f"Tagline: {tagline}")

    specialty = agent_profile.get("business", {}).get("specialty", "")
    if specialty:
        lines.append(f"Specialty: {specialty}")

    demographic = agent_profile.get("business", {}).get("client_demographic", "")
    if demographic:
        lines.append(f"Primary client type: {demographic}")
    else:
        lines.append("Primary client type: both buyers and sellers")

    language = agent_profile.get("content_preferences", {}).get("language", "en")
    if language != "en":
        lines.append(f"Write ALL content in language: {language}")

    return "\n".join(lines)


# ─── Public API ───────────────────────────────────────────────────────────────


def build_insight_request(
    rate_data: dict | None = None,
    market_data: dict | None = None,
    payment_impact: dict | None = None,
    agent_profile: dict | None = None,
) -> dict:
    """
    Tool mode: return Claude API request dict for dispatcher.

    Args:
        rate_data: Output from market_data_fetcher.fetch_rates()
        market_data: Output from redfin_data_fetcher.fetch_market_data()
        payment_impact: Output from market_data_fetcher.compute_payment_impact()
        agent_profile: Agent profile dict from profile_manager
    """
    if agent_profile is None:
        agent_profile = {}

    topic_type, topic_data = decide_today_topic(rate_data, market_data)

    data_context = _build_data_context(rate_data, market_data, payment_impact)
    agent_context = _build_agent_context(agent_profile)

    market_area = (
        agent_profile.get("content_preferences", {}).get("market_area")
        or agent_profile.get("city", "your area")
    )

    user_prompt = f"""Generate today's Content Pack for this agent.

=== AGENT PROFILE ===
{agent_context}

=== TODAY'S TOPIC: {topic_type.upper()} ===
{data_context}

=== INSTRUCTIONS ===
- Topic type is "{topic_type}" — lead with the most newsworthy data point
- Market area for local branding: {market_area}
- Write in first person as this agent
- Include both buyer and seller angles
- The image_data.primary_number should be the single most impactful number from the data"""

    return {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
        "_meta": {
            "topic_type": topic_type,
            "market_area": market_area,
        },
    }


def generate(
    rate_data: dict | None = None,
    market_data: dict | None = None,
    payment_impact: dict | None = None,
    agent_profile: dict | None = None,
) -> dict:
    """
    Generate a daily Content Pack.

    Args:
        rate_data: From market_data_fetcher.fetch_rates()
        market_data: From redfin_data_fetcher.fetch_market_data()
        payment_impact: From market_data_fetcher.compute_payment_impact()
        agent_profile: Agent profile dict

    Returns:
        Content Pack dict with: briefing, social_post, forward_buyer, forward_seller, image_data
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    request = build_insight_request(rate_data, market_data, payment_impact, agent_profile)

    # Extract meta before sending to API
    meta = request.pop("_meta", {})

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
        # Fallback structure if JSON parsing fails
        market_area = meta.get("market_area", "your area")
        result = {
            "briefing": {
                "headline": f"{market_area} Market Update",
                "key_numbers": "",
                "talking_points_buyers": [],
                "talking_points_sellers": [],
            },
            "social_post": {
                "caption": raw[:400],
                "hashtags": ["realestate", market_area.split(",")[0].replace(" ", "").lower()],
            },
            "forward_buyer": {"text": ""},
            "forward_seller": {"text": ""},
            "image_data": {
                "primary_number": "",
                "primary_label": "Market Update",
                "primary_direction": "steady",
                "change_label": "",
                "supporting_stats": [],
            },
        }

    # Attach metadata
    result["_meta"] = {
        "topic_type": meta.get("topic_type", "unknown"),
        "market_area": meta.get("market_area", ""),
        "generated_at": datetime.now().isoformat(),
        "model": "claude-haiku-4-5-20251001",
    }

    return result


# ─── Backward Compatibility ──────────────────────────────────────────────────
# These maintain the v1 API surface so daily_scheduler doesn't break during migration.


def build_insight_request_v1(
    market_area: str,
    agent_name: str = "",
    language: str = "en",
    **_kwargs,
) -> dict:
    """Backward-compatible v1 request builder (no data sources)."""
    profile = {
        "name": agent_name,
        "content_preferences": {"market_area": market_area, "language": language},
    }
    return build_insight_request(agent_profile=profile)


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

    # Add scripts dir to path for sibling imports
    sys.path.insert(0, str(Path(__file__).parent))

    parser = argparse.ArgumentParser(description="Generate daily Content Pack")
    parser.add_argument("--market-area", default="Lehigh Valley, PA")
    parser.add_argument("--agent-name", default="")
    parser.add_argument("--home-price", type=float, default=400_000)
    parser.add_argument("--no-data", action="store_true", help="Skip data fetching (test evergreen mode)")
    args = parser.parse_args()

    import logging
    logging.basicConfig(level=logging.INFO)

    rate_data = None
    market_data_result = None
    impact = None

    if not args.no_data:
        import market_data_fetcher
        import redfin_data_fetcher

        print(f"Fetching data for {args.market_area}...")
        rate_data = market_data_fetcher.fetch_rates()
        if rate_data.get("has_data"):
            impact = market_data_fetcher.compute_payment_impact(rate_data, args.home_price)
        market_data_result = redfin_data_fetcher.fetch_market_data(args.market_area)

    profile = {
        "name": args.agent_name or "Your Name",
        "content_preferences": {"market_area": args.market_area, "language": "en"},
        "brand": {"tone": "warm + professional", "tagline": ""},
        "business": {"client_demographic": "both buyers and sellers"},
    }

    print("\nGenerating Content Pack...")
    pack = generate(
        rate_data=rate_data,
        market_data=market_data_result,
        payment_impact=impact,
        agent_profile=profile,
    )

    print(f"\n{'='*60}")
    print(f"Topic: {pack.get('_meta', {}).get('topic_type', 'unknown')}")
    print(f"{'='*60}")

    b = pack.get("briefing", {})
    print("\n--- BRIEFING (for agent only) ---")
    print(f"Headline: {b.get('headline', '')}")
    print(f"Key Numbers: {b.get('key_numbers', '')}")
    print(f"Buyer Points: {b.get('talking_points_buyers', [])}")
    print(f"Seller Points: {b.get('talking_points_sellers', [])}")

    sp = pack.get("social_post", {})
    print("\n--- SOCIAL POST (publish to Instagram/Facebook) ---")
    print(sp.get("caption", ""))
    print(f"\nHashtags: {' '.join('#' + t for t in sp.get('hashtags', []))}")

    fb = pack.get("forward_buyer", {})
    print("\n--- FORWARD: BUYER CLIENT ---")
    print(fb.get("text", ""))

    fs = pack.get("forward_seller", {})
    print("\n--- FORWARD: SELLER CLIENT ---")
    print(fs.get("text", ""))

    img = pack.get("image_data", {})
    print("\n--- IMAGE DATA ---")
    print(f"Primary: {img.get('primary_number', '')} ({img.get('primary_label', '')})")
    print(f"Direction: {img.get('primary_direction', '')}")
    print(f"Change: {img.get('change_label', '')}")
    print(f"Supporting: {img.get('supporting_stats', [])}")
