#!/usr/bin/env python3
"""
Listing Video Agent — AI Creative Director
Analyzes a property's "personality" and generates a creative brief
that shapes the entire video pipeline.
"""

import json
from pathlib import Path

CREATIVE_PROMPT = (Path(__file__).parent.parent / "prompts" / "creative_brief.md").read_text()

# Archetype → base template affinity
_ARCHETYPE_TEMPLATE_MAP = {
    "The Paradise": "elegant",
    "The Trophy": "elegant",
    "The Nest": "professional",
    "The Canvas": "energetic",
    "The Gem": "energetic",
    "The Heritage": "elegant",
}


def generate_creative_brief(
    photo_analysis: dict,
    property_info: dict,
    agent_style_preference: str = "professional",
) -> dict:
    """
    Call Claude to generate a creative brief for this property.

    Args:
        photo_analysis: Full analysis dict from analyze_photos_live().
        property_info: Dict with address, price, style, tier, key_points.
        agent_style_preference: Agent's preferred style.

    Returns:
        Creative brief dict.
    """
    from api_client import call_claude_json

    prompt = CREATIVE_PROMPT.format(
        photo_analysis=json.dumps(photo_analysis, indent=2),
        property_info=json.dumps(property_info, indent=2),
        agent_style=agent_style_preference,
    )

    request = {
        "model": "claude-sonnet-4-6-20250514",
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": prompt}],
    }

    brief = call_claude_json(request)

    # Ensure required keys exist with defaults
    brief.setdefault("property_archetype", "The Canvas")
    brief.setdefault("concept_name", "Property Showcase")
    brief.setdefault("emotional_arc", {"hook": "curiosity", "journey": "interest", "close": "urgency"})
    brief.setdefault("visual_strategy", {"pacing": "moderate", "camera_personality": "steady_confident"})
    brief.setdefault("narrative_strategy", "cinematic_tour")
    brief.setdefault("voiceover_tone", "confident_authority")
    brief.setdefault("music_mood", "modern_chill")
    brief.setdefault("hero_scenes", [])
    brief.setdefault("template_overrides", {})

    return brief


def select_base_template(brief: dict) -> str:
    """Pick the best base template for this property archetype."""
    archetype = brief.get("property_archetype", "")
    return _ARCHETYPE_TEMPLATE_MAP.get(archetype, "professional")


def apply_creative_brief(base_template: dict, brief: dict) -> dict:
    """
    Merge creative brief overrides into a template using dot-path notation.

    Example: "video.clip_durations.hero": 5
    → template["video"]["clip_durations"]["hero"] = 5
    """
    import copy
    template = copy.deepcopy(base_template)

    for dot_path, value in brief.get("template_overrides", {}).items():
        keys = dot_path.split(".")
        target = template
        for key in keys[:-1]:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
            target = target[key]
        target[keys[-1]] = value

    return template


def build_enhanced_scene_context(brief: dict) -> str:
    """
    Build a context string for plan_scenes that injects creative direction.
    Appended to the property_info text given to the scene planner.
    """
    parts = [f"Creative concept: {brief.get('concept_name', '')}"]

    strategy = brief.get("narrative_strategy", "")
    if strategy == "hook_first":
        parts.append("IMPORTANT: Start with the most visually stunning scene (pool, view, dramatic space) as the hook.")
    elif strategy == "reveal_build":
        parts.append("Build tension gradually — save the best for the climax scene.")
    elif strategy == "lifestyle_day":
        parts.append("Frame the video as a day in the life: morning light → daytime living → evening ambiance.")

    heroes = brief.get("hero_scenes", [])
    if heroes:
        parts.append(f"Hero scenes (give extra time): {', '.join(heroes)}")

    pacing = brief.get("visual_strategy", {}).get("pacing", "")
    if pacing:
        parts.append(f"Pacing: {pacing}")

    return "\n".join(parts)


def build_enhanced_voiceover_context(brief: dict) -> dict:
    """
    Build a creative context dict for generate_script_live().
    """
    return {
        "narrative_strategy": brief.get("narrative_strategy", ""),
        "voiceover_tone": brief.get("voiceover_tone", ""),
        "emotional_arc": brief.get("emotional_arc", {}),
        "concept_name": brief.get("concept_name", ""),
        "property_archetype": brief.get("property_archetype", ""),
    }


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Generate creative brief for listing video")
    parser.add_argument("--analysis-file", required=True, help="Photo analysis JSON file")
    parser.add_argument("--address", default="", help="Property address")
    parser.add_argument("--price", default="", help="Property price")
    parser.add_argument("--agent-style", default="professional", help="Agent style preference")
    args = parser.parse_args()

    analysis = json.loads(Path(args.analysis_file).read_text())
    property_info = {"address": args.address, "price": args.price}

    brief = generate_creative_brief(analysis, property_info, args.agent_style)
    print(json.dumps(brief, indent=2, default=str))
