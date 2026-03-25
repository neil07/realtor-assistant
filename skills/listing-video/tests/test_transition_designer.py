#!/usr/bin/env python3
"""Tests for transition_designer — pure rule engine."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from transition_designer import (
    design_transitions,
    transitions_to_assembly_format,
    _infer_room_type,
    _pick_avoiding_recent,
    TRANSITION_LIBRARY,
)


# --- _infer_room_type ---

def test_infer_outdoor_types():
    assert _infer_room_type("Beautiful pool area") == "pool"
    assert _infer_room_type("Aerial drone shot") == "aerial"
    assert _infer_room_type("Backyard with trees") == "backyard"
    assert _infer_room_type("Exterior front view") == "exterior"


def test_infer_indoor_types():
    assert _infer_room_type("Living room with fireplace") == "living"
    assert _infer_room_type("Modern kitchen island") == "kitchen"
    # iteration order may vary, both are valid indoor types
    assert _infer_room_type("Master bedroom suite") in ("master_bedroom", "bedroom")
    assert _infer_room_type("Guest bathroom") == "bathroom"


def test_infer_cta():
    assert _infer_room_type("CTA slide") == "cta"
    assert _infer_room_type("Call to action") == "cta"


def test_infer_unknown_returns_other():
    assert _infer_room_type("Some random description") == "other"
    assert _infer_room_type("") == "other"


# --- _pick_avoiding_recent ---

def test_pick_avoids_recent():
    assert _pick_avoiding_recent(["fade", "dissolve"], ["fade"]) == "dissolve"


def test_pick_falls_back_if_all_recent():
    assert _pick_avoiding_recent(["fade"], ["fade", "fade"]) == "fade"


def test_pick_empty_candidates():
    assert _pick_avoiding_recent([], ["fade"]) == "fade"


# --- design_transitions ---

def test_empty_scene_plan():
    assert design_transitions([]) == []


def test_single_scene():
    assert design_transitions([{"sequence": 1, "scene_desc": "Living"}]) == []


def test_last_transition_always_fadeblack():
    """The transition to the final scene is always fadeblack."""
    scenes = [
        {"sequence": 1, "scene_desc": "Living room"},
        {"sequence": 2, "scene_desc": "Kitchen"},
        {"sequence": 3, "scene_desc": "Master bedroom"},
    ]
    transitions = design_transitions(scenes)
    assert transitions[-1]["xfade_name"] == "fadeblack"


def test_to_cta_always_fadeblack():
    scenes = [
        {"sequence": 1, "scene_desc": "Living room"},
        {"sequence": 2, "scene_desc": "CTA slide"},
    ]
    transitions = design_transitions(scenes)
    assert transitions[0]["xfade_name"] == "fadeblack"


def test_indoor_outdoor_uses_dramatic_transition():
    """Indoor→outdoor boundary should use fade/fadeblack/dissolve."""
    scenes = [
        {"sequence": 1, "scene_desc": "Kitchen area"},
        {"sequence": 2, "scene_desc": "Pool area"},
        {"sequence": 3, "scene_desc": "Living room"},  # added so idx 0 isn't last
    ]
    t = design_transitions(scenes, style="professional")
    # First transition is indoor→outdoor
    assert t[0]["xfade_name"] in {"fade", "fadeblack", "dissolve"}


def test_no_three_identical_transitions():
    """Rule: no 3 identical transitions in a row."""
    scenes = [
        {"sequence": i, "scene_desc": f"Room {i}"}
        for i in range(1, 7)
    ]
    transitions = design_transitions(scenes, style="professional")
    names = [t["xfade_name"] for t in transitions]
    for i in range(len(names) - 2):
        if names[i] == names[i + 1] == names[i + 2]:
            # The last one can be fadeblack (CTA rule), so skip that
            if names[i] == "fadeblack" and i + 2 == len(names) - 1:
                continue
            assert False, f"Three identical transitions in a row: {names[i]} at positions {i}-{i+2}"


def test_elegant_style_uses_longer_durations():
    scenes = [
        {"sequence": 1, "scene_desc": "Living room"},
        {"sequence": 2, "scene_desc": "Kitchen"},
        {"sequence": 3, "scene_desc": "Bedroom"},
    ]
    elegant = design_transitions(scenes, style="elegant")
    prof = design_transitions(scenes, style="professional")
    # Elegant should use dur_max, professional should use dur_min
    # Compare first non-fadeblack transition
    assert elegant[0]["duration"] >= prof[0]["duration"]


def test_transition_has_correct_seq_refs():
    scenes = [
        {"sequence": 10, "scene_desc": "A"},
        {"sequence": 20, "scene_desc": "B"},
    ]
    t = design_transitions(scenes)
    assert t[0]["from_seq"] == 10
    assert t[0]["to_seq"] == 20


# --- transitions_to_assembly_format ---

def test_assembly_format():
    transitions = [
        {"from_seq": 1, "to_seq": 2, "xfade_name": "fade", "duration": 0.5},
        {"from_seq": 2, "to_seq": 3, "xfade_name": "smoothleft", "duration": 0.4},
    ]
    result = transitions_to_assembly_format(transitions)
    assert len(result) == 2
    assert result[0] == {"type": "crossfade", "duration": 0.5, "xfade_name": "fade"}
    assert result[1] == {"type": "crossfade", "duration": 0.4, "xfade_name": "smoothleft"}


def test_assembly_format_empty():
    assert transitions_to_assembly_format([]) == []
