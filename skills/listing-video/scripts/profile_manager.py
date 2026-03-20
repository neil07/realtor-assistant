#!/usr/bin/env python3
"""
Listing Video Agent — Agent Profile Manager
Stores and retrieves per-agent preferences, voice clones, and usage stats.
"""

import json
import os
from datetime import datetime
from pathlib import Path

PROFILES_DIR = Path(__file__).parent.parent / "profiles"


def _profile_path(phone: str) -> Path:
    """Sanitize phone number and return profile file path."""
    safe_phone = "".join(c for c in phone if c.isdigit() or c == "+")
    return PROFILES_DIR / f"{safe_phone}.json"


def get_profile(phone: str) -> dict | None:
    """Load an agent's profile. Returns None if not found."""
    path = _profile_path(phone)
    if path.exists():
        return json.loads(path.read_text())
    return None


def create_profile(
    phone: str,
    name: str,
    brokerage: str = "",
    city: str = "",
    style: str = "professional",
    music: str = "modern",
    show_price: bool = True,
    format_pref: str = "both",
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
            "language": "en",
        },
        "market_knowledge": {},
        "stats": {
            "videos_created": 0,
            "first_use": datetime.now().isoformat(),
            "last_use": datetime.now().isoformat(),
        },
        "voice_clone_offered": False,
    }
    
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
    profile["stats"]["last_use"] = datetime.now().isoformat()
    
    _profile_path(phone).write_text(json.dumps(profile, indent=2))
    return profile


def increment_video_count(phone: str) -> int:
    """Increment the videos_created counter. Returns new count."""
    profile = get_profile(phone)
    if not profile:
        return 0
    
    profile["stats"]["videos_created"] = profile["stats"].get("videos_created", 0) + 1
    profile["stats"]["last_use"] = datetime.now().isoformat()
    
    _profile_path(phone).write_text(json.dumps(profile, indent=2))
    return profile["stats"]["videos_created"]


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


def mark_voice_clone_offered(phone: str):
    """Mark that we've offered voice cloning to this agent."""
    update_profile(phone, {"voice_clone_offered": True})
