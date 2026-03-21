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


def normalize_profile(profile: dict) -> dict:
    """
    Upgrade old-format profiles to current schema.

    Old format stored style/music/show_price at the top level;
    current schema nests them under "preferences" and "stats".
    """
    if "preferences" not in profile:
        profile["preferences"] = {
            "style": profile.pop("style", "professional"),
            "music": profile.pop("music_preference", profile.pop("music", "modern")),
            "format": profile.pop("format_pref", "both"),
            "show_price": profile.pop("show_price", True),
            "language": profile.pop("language", "en"),
        }

    if "stats" not in profile:
        profile["stats"] = {
            "videos_created": profile.pop("videos_created", 0),
            "first_use": profile.get("created_at", datetime.now().isoformat()),
            "last_use": datetime.now().isoformat(),
        }

    # Ensure voice_clone_id exists (old profiles may use "voice_clone")
    if "voice_clone_id" not in profile:
        profile["voice_clone_id"] = profile.pop("voice_clone", None)

    profile.setdefault("voice_clone_offered", False)
    profile.setdefault("logo_path", None)
    profile.setdefault("brokerage", "")
    profile.setdefault("city", "")
    profile.setdefault("market_knowledge", {})

    return profile


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Manage agent profiles")
    subparsers = parser.add_subparsers(dest="command")

    # Get profile
    get_cmd = subparsers.add_parser("get", help="Get agent profile")
    get_cmd.add_argument("--phone", required=True, help="Agent phone number")

    # Create profile
    create_cmd = subparsers.add_parser("create", help="Create new agent profile")
    create_cmd.add_argument("--phone", required=True, help="Agent phone number")
    create_cmd.add_argument("--name", required=True, help="Agent name")
    create_cmd.add_argument("--brokerage", default="", help="Brokerage name")
    create_cmd.add_argument("--city", default="", help="City")
    create_cmd.add_argument("--style", default="professional", help="Preferred style")
    create_cmd.add_argument("--music", default="modern", help="Music preference")

    # Update profile
    update_cmd = subparsers.add_parser("update", help="Update agent profile fields")
    update_cmd.add_argument("--phone", required=True, help="Agent phone number")
    update_cmd.add_argument("--updates-json", required=True, help="JSON string of updates")

    args = parser.parse_args()

    if args.command == "get":
        profile = get_profile(args.phone)
        if profile:
            profile = normalize_profile(profile)
        print(json.dumps(profile, indent=2))

    elif args.command == "create":
        profile = create_profile(
            phone=args.phone, name=args.name,
            brokerage=args.brokerage, city=args.city,
            style=args.style, music=args.music,
        )
        print(json.dumps(profile, indent=2))

    elif args.command == "update":
        updates = json.loads(args.updates_json)
        profile = update_profile(args.phone, updates)
        print(json.dumps(profile, indent=2))

    else:
        parser.print_help()
        sys.exit(1)
