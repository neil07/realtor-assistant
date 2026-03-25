#!/usr/bin/env python3
"""Tests for creative_director — template selection and brief application."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from creative_director import (
    select_base_template,
    apply_creative_brief,
    build_enhanced_scene_context,
    build_enhanced_voiceover_context,
)


# --- select_base_template ---

def test_select_paradise():
    assert select_base_template({"property_archetype": "The Paradise"}) == "elegant"


def test_select_canvas():
    assert select_base_template({"property_archetype": "The Canvas"}) == "energetic"


def test_select_nest():
    assert select_base_template({"property_archetype": "The Nest"}) == "professional"


def test_select_unknown_archetype():
    assert select_base_template({"property_archetype": "Unknown"}) == "professional"


def test_select_missing_archetype():
    assert select_base_template({}) == "professional"


# --- apply_creative_brief ---

def test_apply_simple_override():
    base = {"video": {"speed": 1.0}, "music": {"volume": 0.15}}
    brief = {"template_overrides": {"music.volume": 0.2}}
    result = apply_creative_brief(base, brief)
    assert result["music"]["volume"] == 0.2
    assert result["video"]["speed"] == 1.0  # untouched


def test_apply_nested_override():
    base = {"video": {"clip_durations": {"normal": 3, "hero": 4}}}
    brief = {"template_overrides": {"video.clip_durations.hero": 6}}
    result = apply_creative_brief(base, brief)
    assert result["video"]["clip_durations"]["hero"] == 6
    assert result["video"]["clip_durations"]["normal"] == 3


def test_apply_creates_missing_path():
    base = {}
    brief = {"template_overrides": {"new.nested.key": "value"}}
    result = apply_creative_brief(base, brief)
    assert result["new"]["nested"]["key"] == "value"


def test_apply_no_overrides():
    base = {"a": 1}
    result = apply_creative_brief(base, {})
    assert result == {"a": 1}


def test_apply_does_not_mutate_original():
    base = {"video": {"speed": 1.0}}
    brief = {"template_overrides": {"video.speed": 2.0}}
    apply_creative_brief(base, brief)
    assert base["video"]["speed"] == 1.0


# --- build_enhanced_scene_context ---

def test_scene_context_hook_first():
    brief = {"concept_name": "Tropical Escape", "narrative_strategy": "hook_first"}
    ctx = build_enhanced_scene_context(brief)
    assert "Tropical Escape" in ctx
    assert "most visually stunning" in ctx


def test_scene_context_reveal_build():
    brief = {"concept_name": "Hidden Gem", "narrative_strategy": "reveal_build"}
    ctx = build_enhanced_scene_context(brief)
    assert "tension" in ctx


def test_scene_context_lifestyle():
    brief = {"concept_name": "Home Sweet Home", "narrative_strategy": "lifestyle_day"}
    ctx = build_enhanced_scene_context(brief)
    assert "morning" in ctx.lower()


def test_scene_context_hero_scenes():
    brief = {"concept_name": "Test", "hero_scenes": ["pool", "kitchen"]}
    ctx = build_enhanced_scene_context(brief)
    assert "pool" in ctx
    assert "kitchen" in ctx


def test_scene_context_pacing():
    brief = {"concept_name": "Test", "visual_strategy": {"pacing": "slow"}}
    ctx = build_enhanced_scene_context(brief)
    assert "slow" in ctx


# --- build_enhanced_voiceover_context ---

def test_voiceover_context():
    brief = {
        "narrative_strategy": "hook_first",
        "voiceover_tone": "warm_inviting",
        "emotional_arc": {"hook": "wow", "journey": "comfort", "close": "urgency"},
        "concept_name": "Dream Home",
        "property_archetype": "The Nest",
    }
    result = build_enhanced_voiceover_context(brief)
    assert result["narrative_strategy"] == "hook_first"
    assert result["voiceover_tone"] == "warm_inviting"
    assert result["concept_name"] == "Dream Home"
    assert result["emotional_arc"]["hook"] == "wow"


def test_voiceover_context_empty_brief():
    result = build_enhanced_voiceover_context({})
    assert result["narrative_strategy"] == ""
    assert result["emotional_arc"] == {}
