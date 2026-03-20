#!/usr/bin/env python3
"""
Listing Video Agent — Voiceover Script Generator
Generates walk-through style voiceover scripts for listing videos.
"""

import json
import sys
from pathlib import Path

SCRIPT_PROMPT = (Path(__file__).parent.parent / "prompts" / "voiceover_script.md").read_text()


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
) -> dict:
    """
    Build a Claude API request for voiceover script generation.
    
    Returns:
        API request dict
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

    return {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": prompt}],
    }


def extract_city(address: str) -> str:
    """Extract city name from address string."""
    parts = address.split(",")
    if len(parts) >= 2:
        return parts[-2].strip()
    return "your area"


def parse_script_response(response_text: str) -> dict:
    """
    Parse the generated script into structured segments.
    
    Returns:
        {
            "hook": str,
            "walkthrough": str,
            "closer": str,
            "full_script": str,
            "caption": str,
            "word_count": int,
            "estimated_duration": float,
            "photo_sequence": list[int]
        }
    """
    sections = {"hook": "", "walkthrough": "", "closer": ""}
    current = None
    caption = ""
    photo_sequence = []
    
    for line in response_text.split("\n"):
        line_stripped = line.strip()
        
        if "[HOOK]" in line_stripped:
            current = "hook"
            continue
        elif "[WALK-THROUGH]" in line_stripped:
            current = "walkthrough"
            continue
        elif "[CLOSER]" in line_stripped:
            current = "closer"
            continue
        elif line_stripped.startswith("CAPTION:"):
            caption = line_stripped.replace("CAPTION:", "").strip()
            current = None
            continue
        elif line_stripped.startswith("PHOTO SEQUENCE:"):
            try:
                seq_str = line_stripped.replace("PHOTO SEQUENCE:", "").strip()
                photo_sequence = json.loads(seq_str)
            except (json.JSONDecodeError, ValueError):
                pass
            continue
        elif line_stripped.startswith("→ matches:"):
            continue
        
        if current and line_stripped:
            sections[current] += line_stripped + " "
    
    # Clean up
    for k in sections:
        sections[k] = sections[k].strip()
    
    full = f"{sections['hook']} {sections['walkthrough']} {sections['closer']}".strip()
    word_count = len(full.split())
    
    return {
        "hook": sections["hook"],
        "walkthrough": sections["walkthrough"],
        "closer": sections["closer"],
        "full_script": full,
        "caption": caption,
        "word_count": word_count,
        "estimated_duration": word_count / 3.5,  # ~3.5 words per second for natural speech
        "photo_sequence": photo_sequence,
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


if __name__ == "__main__":
    # Test with sample input
    sample = {
        "address": "123 Oak St, Frisco, TX",
        "price": "$625,000",
        "photo_analysis": {"photos": [], "property_summary": {}},
    }
    request = build_script_request(**sample)
    print(json.dumps(request, indent=2))
