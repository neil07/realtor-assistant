#!/usr/bin/env python3
"""
Listing Video Agent — Voiceover Script Generator

Generates walk-through style voiceover scripts for listing videos.
Uses Structured Outputs (Pydantic) for reliable, schema-enforced parsing.
"""

import json
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

SCRIPT_PROMPT = (Path(__file__).parent.parent / "prompts" / "voiceover_script.md").read_text()


class ScriptOutput(BaseModel):
    """Structured output schema for voiceover script generation."""

    hook: str
    walkthrough: str
    closer: str
    caption: str
    photo_sequence: list[int]


def build_script_request(
    photo_analysis: dict,
    address: str,
    price: str,
    bed_bath: str = "",
    sqft: str = "",
    agent_name: str = "",
    agent_phone: str = "",
    agent_notes: str = "",
    market_context: str = "",
    city: str = "",
    years: str = "10",
    photo_images: list[dict] | None = None,
    preference_context: str = "",
) -> dict:
    """
    Build a Claude API request for voiceover script generation.

    Args:
        photo_images: Optional list of base64 image dicts from encode_image().
                      When provided, Claude sees the actual photos alongside the
                      structured analysis — producing more specific, vivid scripts.

    Returns:
        API request dict (pass to client.messages.parse() with output_format=ScriptOutput)
    """
    prompt = SCRIPT_PROMPT.format(
        city=city or extract_city(address),
        years=years,
        photo_analysis=json.dumps(photo_analysis, indent=2),
        address=address,
        price=price,
        bed_bath=bed_bath,
        sqft=sqft,
        agent_name=agent_name,
        agent_phone=agent_phone,
        agent_notes=agent_notes,
        market_context=market_context,
    )

    if preference_context:
        prompt += f"\n\n<agent_preferences>\n{preference_context}\n</agent_preferences>"

    # Build content: interleave labelled images then append the text prompt.
    # Claude reads images left-to-right before the instruction text, giving it
    # visual context when writing the hook, walkthrough, and closer.
    if photo_images:
        content: list[dict] = []
        for i, img in enumerate(photo_images):
            content.append({"type": "text", "text": f"Photo {i + 1}:"})
            content.append(img)
        content.append({"type": "text", "text": prompt})
    else:
        content = prompt

    return {
        "model": "claude-sonnet-4-6",
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": content}],
    }


def extract_city(address: str) -> str:
    """Extract city name from address string."""
    parts = address.split(",")
    if len(parts) >= 2:
        return parts[-2].strip()
    return "your area"


def _to_script_dict(parsed: ScriptOutput) -> dict:
    """Convert a ScriptOutput Pydantic instance to the pipeline script dict format."""
    full = f"{parsed.hook} {parsed.walkthrough} {parsed.closer}".strip()
    word_count = len(full.split())
    return {
        "hook": parsed.hook,
        "walkthrough": parsed.walkthrough,
        "closer": parsed.closer,
        "full_script": full,
        "caption": parsed.caption,
        "word_count": word_count,
        "estimated_duration": word_count / 3.5,  # ~3.5 words/second natural speech
        "photo_sequence": parsed.photo_sequence,
    }


def validate_script(parsed: dict) -> list[str]:
    """Check script quality against rules. Returns list of issues."""
    issues = []
    wc = parsed["word_count"]

    if wc < 80:
        issues.append(f"Too short ({wc} words, min 100)")
    if wc > 150:
        issues.append(f"Too long ({wc} words, max 130)")

    hook = parsed["hook"].lower()
    bad_openings = ["hey guys", "welcome to", "check out this beautiful", "hello everyone"]
    for bad in bad_openings:
        if hook.startswith(bad):
            issues.append(f"Bad opening: starts with '{bad}'")

    full = parsed["full_script"].lower()
    cliches = ["stunning home", "beautiful property", "boasts", "nestled in"]
    for c in cliches:
        if c in full:
            issues.append(f"Cliché detected: '{c}'")

    opinion_markers = ["sold me", "honest", "here's the thing", "what got me", "i'll tell you"]
    if not any(m in full for m in opinion_markers):
        issues.append("Missing personal opinion (add 'what sold me' or similar)")

    return issues


def run(
    photo_analysis: dict,
    address: str,
    price: str,
    photo_paths: list[str] | None = None,
    **kwargs,
) -> dict:
    """
    Run script generation end-to-end using Structured Outputs.

    Calls Claude with output_format=ScriptOutput to guarantee valid JSON.
    No fragile text parsing — schema is enforced by the API.

    Args:
        photo_paths: Optional list of image file paths. When provided, images are
                     base64-encoded and sent to Claude Vision so it writes the script
                     from direct visual observation, not just the text analysis.

    Returns:
        Script dict with hook/walkthrough/closer/full_script/caption/word_count/
        estimated_duration/photo_sequence, plus optional validation_issues.
    """
    photo_images = None
    if photo_paths:
        from analyze_photos import encode_image
        photo_images = [encode_image(p) for p in photo_paths]

    request = build_script_request(
        photo_analysis, address, price, photo_images=photo_images, **kwargs
    )
    client = anthropic.Anthropic()
    response = client.messages.parse(**request, output_format=ScriptOutput)
    result = _to_script_dict(response.parsed_output)
    issues = validate_script(result)
    if issues:
        result["validation_issues"] = issues
    return result


if __name__ == "__main__":
    sample = {
        "photo_analysis": {"photos": [], "property_summary": {}},
        "address": "123 Oak St, Frisco, TX",
        "price": "$625,000",
    }
    if "--dry-run" in sys.argv:
        request = build_script_request(**sample)
        print(json.dumps(request, indent=2))
    else:
        result = run(**sample)
        print(f"📝 Script ({result['word_count']} words, ~{result['estimated_duration']:.0f}s):\n")
        print(f"[HOOK] {result['hook']}")
        print(f"[WALK] {result['walkthrough']}")
        print(f"[CLOSE] {result['closer']}")
        if result.get("validation_issues"):
            print(f"\n⚠️ Issues: {result['validation_issues']}")
