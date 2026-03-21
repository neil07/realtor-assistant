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
    creative_context: dict = None,
) -> dict:
    """
    Build a Claude API request for voiceover script generation.

    Args:
        creative_context: Optional creative director guidance dict.

    Returns:
        API request dict
    """
    # Build creative direction block if provided
    creative_direction = ""
    if creative_context:
        parts = []
        if creative_context.get("narrative_strategy"):
            parts.append(f"Narrative strategy: {creative_context['narrative_strategy']}")
        if creative_context.get("voiceover_tone"):
            parts.append(f"Voiceover tone: {creative_context['voiceover_tone']}")
        if creative_context.get("emotional_arc"):
            arc = creative_context["emotional_arc"]
            parts.append(f"Emotional arc: hook={arc.get('hook','')}, journey={arc.get('journey','')}, close={arc.get('close','')}")
        if creative_context.get("concept_name"):
            parts.append(f"Creative concept: {creative_context['concept_name']}")
        if creative_context.get("property_archetype"):
            parts.append(f"Property archetype: {creative_context['property_archetype']}")
        if parts:
            creative_direction = "\n## Creative Direction\n\n" + "\n".join(f"- {p}" for p in parts) + "\n"

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
        creative_direction=creative_direction,
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


def generate_script_live(
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
    creative_context: dict = None,
    max_attempts: int = 2,
) -> dict:
    """
    Call Claude to generate a voiceover script, with auto-validation and retry.

    Args:
        creative_context: Optional dict from creative director with keys:
            "narrative_strategy", "voiceover_tone", "emotional_arc", etc.
            Injected into the prompt as {creative_direction}.
        max_attempts: Retry count if validation fails.

    Returns:
        Parsed script dict from parse_script_response().
    """
    from api_client import call_claude

    request = build_script_request(
        photo_analysis=photo_analysis,
        address=address,
        price=price,
        bed_bath=bed_bath,
        sqft=sqft,
        agent_name=agent_name,
        agent_phone=agent_phone,
        agent_notes=agent_notes,
        market_context=market_context,
        city=city,
        creative_context=creative_context,
    )

    best = None
    best_issues = None

    for attempt in range(max_attempts):
        text = call_claude(request)
        parsed = parse_script_response(text)
        issues = validate_script(parsed)

        if not issues:
            return parsed

        # Keep the best attempt (fewest issues)
        if best_issues is None or len(issues) < len(best_issues):
            best = parsed
            best_issues = issues

    # Return best attempt even if imperfect
    return best


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate voiceover script")
    parser.add_argument("--live", action="store_true", help="Call Claude API")
    parser.add_argument("--analysis-file", required=True, help="Photo analysis JSON file")
    parser.add_argument("--address", required=True, help="Property address")
    parser.add_argument("--price", required=True, help="Property price")
    parser.add_argument("--bed-bath", default="", help="Bed/bath info")
    parser.add_argument("--sqft", default="", help="Square footage")
    parser.add_argument("--agent-name", default="", help="Agent name")
    parser.add_argument("--agent-phone", default="", help="Agent phone")
    parser.add_argument("--creative-context-file", default=None, help="Creative brief JSON file")
    args = parser.parse_args()

    analysis = json.loads(Path(args.analysis_file).read_text())
    creative_context = None
    if args.creative_context_file:
        creative_context = json.loads(Path(args.creative_context_file).read_text())

    if args.live:
        result = generate_script_live(
            photo_analysis=analysis, address=args.address, price=args.price,
            bed_bath=args.bed_bath, sqft=args.sqft,
            agent_name=args.agent_name, agent_phone=args.agent_phone,
            creative_context=creative_context,
        )
    else:
        result = build_script_request(
            photo_analysis=analysis, address=args.address, price=args.price,
            bed_bath=args.bed_bath, sqft=args.sqft,
            agent_name=args.agent_name, agent_phone=args.agent_phone,
            creative_context=creative_context,
        )

    print(json.dumps(result, indent=2, default=str))
