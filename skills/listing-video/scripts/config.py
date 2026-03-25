#!/usr/bin/env python3
"""
Listing Video Agent — Path Constants & Template Loader

Note: API keys are injected as env vars by OpenClaw at runtime.
No .env loading needed — OpenClaw handles secret management.
"""

import json
from pathlib import Path

# ── Path constants ──────────────────────────────────────────────────────
SKILL_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"
TEMPLATES_DIR = SKILL_ROOT / "templates"
PROMPTS_DIR = SKILL_ROOT / "prompts"
PROFILES_DIR = SKILL_ROOT / "profiles"
ASSETS_DIR = SKILL_ROOT / "assets"


def load_template(style: str) -> dict:
    """Load a template JSON by style name."""
    path = TEMPLATES_DIR / f"{style}.json"
    if not path.exists():
        path = TEMPLATES_DIR / "professional.json"
    return json.loads(path.read_text())


# ── Aspect ratio helpers ──────────────────────────────────────────────
ASPECT_RESOLUTIONS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}


def resolution_for_aspect(aspect_ratio: str) -> tuple[int, int]:
    """Convert aspect ratio string to (width, height) tuple."""
    return ASPECT_RESOLUTIONS.get(aspect_ratio, (1920, 1080))
