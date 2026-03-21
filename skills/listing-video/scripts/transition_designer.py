#!/usr/bin/env python3
"""
Listing Video Agent — Intelligent Transition Designer
Pure rule engine — no LLM calls, zero cost.

Selects from ffmpeg xfade's 40+ transition types based on:
- Scene type pairs (room→room, indoor→outdoor, any→CTA)
- Template style (elegant=slow fades, energetic=wipes)
- Rhythm (no 3 identical transitions in a row)
"""

# ── Transition Library ──────────────────────────────────────────────────
# Curated subset of ffmpeg xfade transitions that work well for real estate
TRANSITION_LIBRARY = {
    "fade": {"duration_range": (0.5, 1.0), "mood": "elegant", "energy": 1},
    "fadeblack": {"duration_range": (0.6, 1.2), "mood": "dramatic", "energy": 1},
    "fadewhite": {"duration_range": (0.5, 1.0), "mood": "clean", "energy": 1},
    "smoothleft": {"duration_range": (0.4, 0.8), "mood": "flowing", "energy": 2},
    "smoothright": {"duration_range": (0.4, 0.8), "mood": "flowing", "energy": 2},
    "smoothup": {"duration_range": (0.4, 0.8), "mood": "ascending", "energy": 2},
    "smoothdown": {"duration_range": (0.4, 0.8), "mood": "descending", "energy": 2},
    "wipeleft": {"duration_range": (0.3, 0.6), "mood": "energetic", "energy": 3},
    "wiperight": {"duration_range": (0.3, 0.6), "mood": "energetic", "energy": 3},
    "slideleft": {"duration_range": (0.3, 0.6), "mood": "dynamic", "energy": 3},
    "slideright": {"duration_range": (0.3, 0.6), "mood": "dynamic", "energy": 3},
    "dissolve": {"duration_range": (0.5, 1.0), "mood": "elegant", "energy": 1},
}

# Style → preferred transitions
_STYLE_PREFERENCES = {
    "elegant": ["fade", "dissolve", "fadeblack", "smoothleft", "smoothright"],
    "energetic": ["wipeleft", "wiperight", "slideleft", "slideright", "smoothleft", "smoothup"],
    "professional": ["fade", "smoothleft", "smoothright", "dissolve", "wipeleft"],
}

# Special transition rules
_INDOOR_OUTDOOR_TYPES = {"fadeblack", "fade", "dissolve"}
_TO_CTA_TYPES = {"fadeblack", "fade"}
_SAME_ROOM_TYPES = {"smoothleft", "smoothright", "dissolve"}

_INDOOR_ROOMS = {"living", "kitchen", "dining", "master_bedroom", "bedroom",
                 "master_bath", "bathroom", "office", "laundry", "garage", "gym", "lounge"}
_OUTDOOR_ROOMS = {"exterior", "backyard", "pool", "aerial"}


def design_transitions(
    scene_plan: list[dict],
    style: str = "professional",
    template: dict = None,
) -> list[dict]:
    """
    Design transitions between consecutive scenes.

    Returns list of transition dicts (one per scene boundary):
    [
        {"from_seq": 1, "to_seq": 2, "xfade_name": "smoothleft", "duration": 0.5},
        ...
    ]
    """
    if len(scene_plan) < 2:
        return []

    preferred = _STYLE_PREFERENCES.get(style, _STYLE_PREFERENCES["professional"])
    transitions = []
    recent = []  # track last 2 transitions to avoid repetition

    for i in range(len(scene_plan) - 1):
        current = scene_plan[i]
        next_scene = scene_plan[i + 1]

        from_type = _infer_room_type(current.get("scene_desc", ""))
        to_type = _infer_room_type(next_scene.get("scene_desc", ""))
        is_to_cta = to_type == "cta" or i == len(scene_plan) - 2

        # Rule 1: Any → CTA always uses fadeblack
        if is_to_cta:
            xfade = "fadeblack"
        # Rule 2: Indoor → Outdoor (or vice versa) uses dramatic transition
        elif _is_indoor(from_type) != _is_indoor(to_type):
            candidates = list(_INDOOR_OUTDOOR_TYPES & set(preferred))
            xfade = _pick_avoiding_recent(candidates or ["fadeblack"], recent)
        # Rule 3: Same room category uses smooth transitions
        elif from_type == to_type:
            candidates = list(_SAME_ROOM_TYPES & set(preferred))
            xfade = _pick_avoiding_recent(candidates or ["smoothleft"], recent)
        # Rule 4: Default from style preferences
        else:
            xfade = _pick_avoiding_recent(preferred, recent)

        # Get duration from library
        lib = TRANSITION_LIBRARY.get(xfade, TRANSITION_LIBRARY["fade"])
        dur_min, dur_max = lib["duration_range"]
        # Elegant → longer transitions; energetic → shorter
        duration = dur_max if style == "elegant" else dur_min

        transitions.append({
            "from_seq": current.get("sequence", i + 1),
            "to_seq": next_scene.get("sequence", i + 2),
            "xfade_name": xfade,
            "duration": round(duration, 2),
        })

        recent.append(xfade)
        if len(recent) > 2:
            recent.pop(0)

    return transitions


def transitions_to_assembly_format(transitions: list[dict]) -> list[dict]:
    """Convert to the format expected by assemble_final."""
    return [
        {
            "type": "crossfade",
            "duration": t["duration"],
            "xfade_name": t["xfade_name"],
        }
        for t in transitions
    ]


def _is_indoor(room_type: str) -> bool:
    return room_type in _INDOOR_ROOMS


def _pick_avoiding_recent(candidates: list[str], recent: list[str]) -> str:
    """Pick a transition avoiding the last 2 used ones."""
    # Prefer unused
    for c in candidates:
        if c not in recent:
            return c
    # All were recent — just pick the first
    return candidates[0] if candidates else "fade"


def _infer_room_type(scene_desc: str) -> str:
    """Best-effort room type from scene description."""
    desc_lower = scene_desc.lower()
    for room in list(_OUTDOOR_ROOMS) + list(_INDOOR_ROOMS):
        if room.replace("_", " ") in desc_lower or room in desc_lower:
            return room
    if "cta" in desc_lower or "call to action" in desc_lower:
        return "cta"
    return "other"


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Design transitions between scenes")
    parser.add_argument("--scene-plan-file", required=True, help="Scene plan JSON file")
    parser.add_argument("--style", default="professional", help="Video style")
    args = parser.parse_args()

    scene_plan = json.loads(Path(args.scene_plan_file).read_text())
    transitions = design_transitions(scene_plan, args.style)
    assembly_format = transitions_to_assembly_format(transitions)

    print(json.dumps({
        "transitions": transitions,
        "assembly_format": assembly_format,
    }, indent=2))
