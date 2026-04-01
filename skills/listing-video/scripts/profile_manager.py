#!/usr/bin/env python3
"""
Listing Video Agent — Agent Profile Manager
Stores and retrieves per-agent preferences, voice clones, and usage stats.
"""

import json
from datetime import datetime
from pathlib import Path

PROFILES_DIR = Path(__file__).parent.parent / "profiles"

_DEFAULT_LEARNED_PATTERNS: dict = {
    "style_confirmed": [],
    "music_rejected": [],
    "always_include": [],
    "frequently_requested": [],
}

_DEFAULT_ACTIVATION: dict = {
    "last_successful_path": "",
    "last_recommended_path": "",
    "first_value_seen": False,
}


def _profile_path(phone: str) -> Path:
    """Sanitize phone number and return profile file path."""
    safe_phone = "".join(c for c in phone if c.isdigit() or c == "+")
    return PROFILES_DIR / f"{safe_phone}.json"


def get_profile(phone: str) -> dict | None:
    """Load an agent's profile. Returns None if not found."""
    path = _profile_path(phone)
    if path.exists():
        profile = json.loads(path.read_text())
        _ensure_profile_defaults(profile)
        return profile
    return None


def _ensure_profile_defaults(profile: dict) -> dict:
    """Backfill newer profile fields for older JSON records."""
    profile.setdefault("learned_patterns", {**_DEFAULT_LEARNED_PATTERNS})
    profile.setdefault("revision_history", [])
    profile.setdefault("stats", {})
    profile["stats"].setdefault("videos_created", 0)
    profile["stats"].setdefault("first_use", datetime.now().isoformat())
    profile["stats"].setdefault("last_use", datetime.now().isoformat())
    profile.setdefault("activation", {**_DEFAULT_ACTIVATION})
    profile["activation"].setdefault("last_successful_path", "")
    profile["activation"].setdefault("last_recommended_path", "")
    profile["activation"].setdefault("first_value_seen", False)
    return profile


def create_profile(
    phone: str,
    name: str,
    brokerage: str = "",
    city: str = "",
    style: str = "professional",
    music: str = "modern",
    show_price: bool = True,
    format_pref: str = "both",
    market_area: str = "",
    language: str = "en",
    branding_colors: list[str] | None = None,
) -> dict:
    """Create a new agent profile."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    profile = {
        "phone": phone,
        "name": name,
        "brokerage": brokerage,
        "city": city,
        "logo_path": None,
        "voice_clone_id": None,
        "preferences": {
            "style": style,
            "music": music,
            "format": format_pref,
            "show_price": show_price,
            "language": language,
        },
        # 2.0: branding + market context
        "content_preferences": {
            "market_area": market_area or city,
            "branding_colors": branding_colors or ["#1B2A4A", "#C9A96E"],
            "language": language,
            "daily_push_enabled": True,  # opt-out via "停止每日推送"
        },
        # 2.0: business profile
        "business": {
            "neighborhoods": [],
            "price_range": "",
            "client_demographic": "",
            "specialty": "",
            "transaction_volume": "",
        },
        # 2.0: personal brand (consumed by daily insight Content Pack)
        "brand": {
            "tone": "warm + professional",  # warm/professional/casual/authoritative
            "tagline": "",  # e.g. "Your Lehigh Valley Real Estate Expert"
            "logo_available": False,
        },
        "headshot_path": None,  # path to agent headshot for branded images
        # 2.0: social media presence
        "social_media": {
            "platforms": [],
            "posting_frequency": "",
            "content_goals": "",
            "content_dislikes": [],
        },
        # 2.0: local market knowledge
        "market": {
            "trends_interest": [],
        },
        # 2.0: learned from feedback over time
        "learned_patterns": {**_DEFAULT_LEARNED_PATTERNS},
        # 2.0: per-job revision history
        "revision_history": [],
        "market_knowledge": {},
        "stats": {
            "videos_created": 0,
            "first_use": datetime.now().isoformat(),
            "last_use": datetime.now().isoformat(),
        },
        "activation": {**_DEFAULT_ACTIVATION},
        "voice_clone_offered": False,
    }

    _ensure_profile_defaults(profile)
    _profile_path(phone).write_text(json.dumps(profile, indent=2))
    return profile


def update_profile(phone: str, updates: dict) -> dict:
    """Update specific fields in an agent's profile."""
    profile = get_profile(phone)
    if not profile:
        return {"status": "error", "message": "Profile not found"}

    def deep_update(base, new):
        for k, v in new.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                deep_update(base[k], v)
            else:
                base[k] = v

    deep_update(profile, updates)
    _ensure_profile_defaults(profile)
    profile["stats"]["last_use"] = datetime.now().isoformat()

    _profile_path(phone).write_text(json.dumps(profile, indent=2))
    return profile


def increment_video_count(phone: str) -> int:
    """Increment the videos_created counter. Returns new count."""
    profile = get_profile(phone)
    if not profile:
        return 0

    _ensure_profile_defaults(profile)
    profile["stats"]["videos_created"] = profile["stats"].get("videos_created", 0) + 1
    profile["stats"]["last_use"] = datetime.now().isoformat()
    profile["activation"]["first_value_seen"] = True
    profile["activation"]["last_successful_path"] = "video_first"

    _profile_path(phone).write_text(json.dumps(profile, indent=2))
    return profile["stats"]["videos_created"]


def record_feedback(
    phone: str,
    job_id: str,
    feedback_text: str,
    classified: dict,
    revision_round: int = 1,
) -> dict:
    """
    Record a revision feedback event and update learned patterns.

    Args:
        phone: Agent phone number
        job_id: The job that received feedback
        feedback_text: Raw feedback from agent
        classified: Output from feedback_classifier, e.g.
            {"category": "music", "change": "upbeat", "old_value": "calm",
             "new_value": "upbeat", "severity": "minor"}
        revision_round: Which revision round this is (1-based)

    Returns:
        Updated profile dict
    """
    profile = get_profile(phone)
    if not profile:
        return {"status": "error", "message": "Profile not found"}

    # Ensure 2.0 fields exist (backward-compat for older profiles)
    _ensure_profile_defaults(profile)

    # Append to revision history (keep last 20)
    profile["revision_history"].append({
        "job_id": job_id,
        "round": revision_round,
        "feedback_text": feedback_text,
        "classified": classified,
        "timestamp": datetime.now().isoformat(),
    })
    if len(profile["revision_history"]) > 20:
        profile["revision_history"] = profile["revision_history"][-20:]

    # Update learned patterns based on classification
    category = classified.get("category", "")
    old_value = classified.get("old_value", "")
    new_value = classified.get("new_value", "")

    if category == "music" and old_value:
        rejected = profile["learned_patterns"].setdefault("music_rejected", [])
        if old_value not in rejected:
            rejected.append(old_value)
        # Also update the preference to the new value if provided
        if new_value:
            profile["preferences"]["music"] = new_value

    elif category == "style" and new_value:
        profile["preferences"]["style"] = new_value
        confirmed = profile["learned_patterns"].setdefault("style_confirmed", [])
        if new_value not in confirmed:
            confirmed.append(new_value)

    elif category == "include" and new_value:
        always = profile["learned_patterns"].setdefault("always_include", [])
        if new_value not in always:
            always.append(new_value)

    elif category == "general" and feedback_text:
        frequent = profile["learned_patterns"].setdefault("frequently_requested", [])
        # Keep last 10 free-form requests
        frequent.append(feedback_text[:100])
        profile["learned_patterns"]["frequently_requested"] = frequent[-10:]

    profile["stats"]["last_use"] = datetime.now().isoformat()
    _profile_path(phone).write_text(json.dumps(profile, indent=2))
    return profile


def record_positive_signal(phone: str, style: str) -> None:
    """Record that a video was accepted without revision — reinforce preferences.

    Called when a non-retry job reaches DELIVERED status. The absence of
    feedback is itself a signal: the agent was happy with this combination.

    Args:
        phone: Agent phone number.
        style: Video style used (e.g. "elegant", "professional").
    """
    profile = get_profile(phone)
    if not profile:
        return

    _ensure_profile_defaults(profile)
    patterns = profile.setdefault("learned_patterns", {**_DEFAULT_LEARNED_PATTERNS})

    confirmed = patterns.setdefault("style_confirmed", [])
    if style and style not in confirmed:
        confirmed.append(style)

    profile.setdefault("stats", {})["last_use"] = datetime.now().isoformat()
    _profile_path(phone).write_text(json.dumps(profile, indent=2))


def get_active_agents(days: int = 7) -> list[dict]:
    """
    Return profiles of agents who have interacted within the last N days.
    Used by daily scheduler to know who to push content to.
    """
    from datetime import timedelta

    cutoff = datetime.now() - timedelta(days=days)
    active = []

    if not PROFILES_DIR.exists():
        return []

    for path in PROFILES_DIR.glob("*.json"):
        try:
            profile = json.loads(path.read_text())
            _ensure_profile_defaults(profile)
            last_use_str = profile.get("stats", {}).get("last_use", "")
            if not last_use_str:
                continue
            # Handle both timezone-aware and naive datetimes
            last_use_str = last_use_str.split("+")[0].split("Z")[0]
            last_use = datetime.fromisoformat(last_use_str)
            if last_use >= cutoff:
                active.append(profile)
        except Exception:
            continue

    return active


def get_preference_context(phone: str) -> str:
    """
    Build a human-readable preference summary for use in prompts.
    Helps Claude understand this agent's known preferences without sending full JSON.
    """
    profile = get_profile(phone)
    if not profile:
        return ""

    prefs = profile.get("preferences", {})
    patterns = profile.get("learned_patterns", {})
    content_prefs = profile.get("content_preferences", {})

    lines = []
    if prefs.get("style"):
        lines.append(f"Preferred style: {prefs['style']}")
    if prefs.get("music"):
        lines.append(f"Preferred music: {prefs['music']}")
    if patterns.get("music_rejected"):
        lines.append(f"Music to avoid: {', '.join(patterns['music_rejected'])}")
    if patterns.get("always_include"):
        lines.append(f"Always include: {', '.join(patterns['always_include'])}")
    if patterns.get("frequently_requested"):
        lines.append(f"Often requests: {patterns['frequently_requested'][-1]}")
    if content_prefs.get("market_area"):
        lines.append(f"Market area: {content_prefs['market_area']}")

    return "\n".join(lines)


def set_voice_clone(phone: str, voice_id: str) -> dict:
    """Store the cloned voice ID for an agent."""
    return update_profile(phone, {"voice_clone_id": voice_id})


def set_logo(phone: str, logo_path: str) -> dict:
    """Store the logo image path for an agent."""
    return update_profile(phone, {"logo_path": logo_path})


def add_market_knowledge(phone: str, key: str, value: str) -> dict:
    """Add a piece of local market knowledge for better scripts."""
    profile = get_profile(phone)
    if not profile:
        return {"status": "error", "message": "Profile not found"}

    profile.setdefault("market_knowledge", {})[key] = value
    _profile_path(phone).write_text(json.dumps(profile, indent=2))
    return profile


def is_first_time(phone: str) -> bool:
    """Check if this is a first-time user."""
    return get_profile(phone) is None


def should_offer_voice_clone(phone: str) -> bool:
    """Check if we should offer voice cloning (only once)."""
    profile = get_profile(phone)
    if not profile:
        return False
    return (
        not profile.get("voice_clone_offered", False)
        and not profile.get("voice_clone_id")
        and profile["stats"].get("videos_created", 0) >= 1
    )


def mark_voice_clone_offered(phone: str) -> None:
    """Mark that we've offered voice cloning to this agent."""
    update_profile(phone, {"voice_clone_offered": True})


# ---------------------------------------------------------------------------
# Skill Brief Management
# ---------------------------------------------------------------------------

BRIEFS_DIR = PROFILES_DIR / "briefs"
DEFAULT_BRIEF_PATH = Path(__file__).parent.parent / "prompts" / "creative_director.md"


def _safe_phone(phone: str) -> str:
    """Sanitize phone for use as directory name (strips +, spaces)."""
    return "".join(c for c in phone if c.isdigit() or c == "+").lstrip("+") or phone


def get_skill_brief_path(phone: str, skill_type: str = "video") -> Path:
    """Return the path for an agent's Skill brief (file may not exist yet)."""
    return BRIEFS_DIR / _safe_phone(phone) / f"{skill_type}.md"


def init_skill_brief(phone: str, skill_type: str = "video") -> Path:
    """
    Ensure an agent has a personal Skill brief file.

    On first call: copies the global default brief for this agent.
    Subsequent calls: returns the existing path unchanged.

    Returns:
        Path to the agent's brief file.
    """
    brief_path = get_skill_brief_path(phone, skill_type)
    if not brief_path.exists():
        brief_path.parent.mkdir(parents=True, exist_ok=True)
        brief_path.write_text(DEFAULT_BRIEF_PATH.read_text())
    return brief_path


def get_skill_brief(phone: str, skill_type: str = "video") -> str:
    """
    Load an agent's Skill brief content (auto-initializes on first call).

    Returns:
        Markdown string of the agent's creative brief.
    """
    return init_skill_brief(phone, skill_type).read_text()


def update_skill_brief(phone: str, content: str, skill_type: str = "video") -> Path:
    """
    Overwrite an agent's Skill brief with new content.

    Called by the admin backend when an operator edits a brief.

    Returns:
        Path to the updated brief file.
    """
    brief_path = get_skill_brief_path(phone, skill_type)
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(content)
    return brief_path


def list_skill_briefs() -> list[dict]:
    """
    List all agents that have at least one customized Skill brief.

    Returns:
        List of dicts: [{phone, skill_type, path, size_bytes, is_customized}]
    """
    result = []
    if not BRIEFS_DIR.exists():
        return result

    for agent_dir in sorted(BRIEFS_DIR.iterdir()):
        if not agent_dir.is_dir():
            continue
        phone = agent_dir.name
        for brief_file in agent_dir.glob("*.md"):
            skill_type = brief_file.stem
            default_content = DEFAULT_BRIEF_PATH.read_text() if DEFAULT_BRIEF_PATH.exists() else ""
            is_customized = brief_file.read_text() != default_content
            result.append({
                "phone": phone,
                "skill_type": skill_type,
                "path": str(brief_file),
                "size_bytes": brief_file.stat().st_size,
                "is_customized": is_customized,
            })
    return result
