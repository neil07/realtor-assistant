#!/usr/bin/env python3
"""
Operator Console — FastAPI Router

Serves the operator dashboard, onboarding flow, and H5 agent form.
All routes are prefixed with /console by server.py.
"""

import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# Add scripts to path for profile_manager access
SCRIPTS_DIR = Path(__file__).parent.parent / "skills" / "listing-video" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import profile_manager

from console.memory_schema import (
    EDITABLE_FIELDS,
    FIELD_LABELS,
    compute_completeness,
    get_field_details,
    get_recommended_experience,
    set_field_value,
)

router = APIRouter(prefix="/console", tags=["console"])

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_all_profiles() -> list[dict]:
    """Load all profiles with completeness data."""
    profiles_dir = profile_manager.PROFILES_DIR
    if not profiles_dir.exists():
        return []

    results = []
    for path in sorted(profiles_dir.glob("*.json")):
        try:
            import json
            profile = json.loads(path.read_text())
            completeness = compute_completeness(profile)
            guidance = get_recommended_experience(profile, completeness)
            results.append({
                "profile": profile,
                "completeness": completeness,
                "guidance": guidance,
            })
        except Exception:
            continue
    return results


def _find_profile_by_token(token: str) -> dict | None:
    """Find a profile that has the given form token."""
    profiles_dir = profile_manager.PROFILES_DIR
    if not profiles_dir.exists():
        return None

    import json
    for path in profiles_dir.glob("*.json"):
        try:
            profile = json.loads(path.read_text())
            if profile.get("_form_token") == token:
                return profile
        except Exception:
            continue
    return None


def _get_public_base_url() -> str:
    """Get public base URL for form links."""
    return os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    clients = _get_all_profiles()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "clients": clients,
    })


# ---------------------------------------------------------------------------
# Onboarding: create new client
# ---------------------------------------------------------------------------

@router.get("/onboard", response_class=HTMLResponse)
async def onboard_page(request: Request):
    return templates.TemplateResponse("onboarding.html", {
        "request": request,
    })


@router.post("/api/create-client")
async def create_client(
    request: Request,
    phone: str = Form(...),
    name: str = Form(...),
):
    """Create profile + generate form token + notify bot."""
    # Check if profile already exists
    existing = profile_manager.get_profile(phone)
    if existing:
        # Profile exists — just generate a new token if needed
        token = existing.get("_form_token") or uuid.uuid4().hex
        profile_manager.update_profile(phone, {"_form_token": token})
    else:
        # Create new profile with minimal info
        profile_manager.create_profile(phone=phone, name=name)
        token = uuid.uuid4().hex
        profile_manager.update_profile(phone, {"_form_token": token})

    form_url = f"{_get_public_base_url()}/console/form/{token}"

    # Notify OpenClaw bot to send the form link
    bot_sent = False
    try:
        from agent.callback_client import CallbackClient

        base_url = os.getenv("OPENCLAW_CALLBACK_BASE_URL", "")
        if base_url:
            client = CallbackClient()
            bot_sent = await client.send(
                f"{base_url.rstrip('/')}/events",
                {
                    "type": "onboarding_form",
                    "agent_phone": phone,
                    "agent_name": name,
                    "form_url": form_url,
                    "message": (
                        f"Hi {name}! I'm your content assistant.\n\n"
                        "You can try Reel Agent right away by sending 6-10 listing photos "
                        "or replying 'daily insight'.\n\n"
                        "If you want faster, more personalized results, fill this quick setup form:\n"
                        f"{form_url}"
                    ),
                },
            )
    except Exception:
        bot_sent = False

    return templates.TemplateResponse("onboarding.html", {
        "request": request,
        "created": True,
        "name": name,
        "phone": phone,
        "form_url": form_url,
        "bot_sent": bot_sent,
    })


# ---------------------------------------------------------------------------
# H5 Onboarding Form (agent-facing, English)
# ---------------------------------------------------------------------------

@router.get("/form/{token}", response_class=HTMLResponse)
async def onboarding_form(request: Request, token: str):
    profile = _find_profile_by_token(token)
    if not profile:
        raise HTTPException(404, "Form not found or expired")

    # Check if already submitted
    if profile.get("_form_submitted"):
        return templates.TemplateResponse("form_done.html", {
            "request": request,
            "name": profile.get("name", ""),
            "already_submitted": True,
        })

    # Track form open (first open only)
    if not profile.get("_form_opened_at"):
        profile_manager.update_profile(
            profile["phone"],
            {"_form_opened_at": datetime.now(UTC).isoformat()},
        )

    return templates.TemplateResponse("onboarding_form.html", {
        "request": request,
        "token": token,
        "name": profile.get("name", ""),
    })


@router.post("/form/{token}/submit")
async def submit_form(
    request: Request,
    token: str,
    name: str = Form(""),
    market_area: str = Form(""),
    city: str = Form(""),
    client_demographic: str = Form(""),
    style: str = Form("professional"),
    platforms: list[str] = Form([]),
    language: str = Form("en"),
):
    """Process H5 form submission → update profile."""
    profile = _find_profile_by_token(token)
    if not profile:
        raise HTTPException(404, "Form not found or expired")

    if profile.get("_form_submitted"):
        return templates.TemplateResponse("form_done.html", {
            "request": request,
            "name": profile.get("name", ""),
            "already_submitted": True,
        })

    phone = profile["phone"]

    # Build updates from form data
    now = datetime.now(UTC).isoformat()
    updates: dict = {"_form_submitted": True, "_form_submitted_at": now}
    if name.strip():
        updates["name"] = name.strip()
    if city.strip():
        updates["city"] = city.strip()
    if market_area.strip():
        updates["content_preferences"] = {"market_area": market_area.strip()}
    if client_demographic:
        updates["business"] = {"client_demographic": client_demographic}
    if style:
        updates["preferences"] = {"style": style}
    if platforms:
        updates["social_media"] = {"platforms": platforms}
    if language:
        if "preferences" not in updates:
            updates["preferences"] = {}
        updates["preferences"]["language"] = language

    profile_manager.update_profile(phone, updates)

    # Notify bot that form is completed (so operator gets notified)
    agent_name = name.strip() or profile.get("name", "")
    try:
        from agent.callback_client import CallbackClient

        base_url = os.getenv("OPENCLAW_CALLBACK_BASE_URL", "")
        if base_url:
            import asyncio
            client = CallbackClient()
            asyncio.create_task(client.send(
                f"{base_url.rstrip('/')}/events",
                {
                    "type": "form_completed",
                    "agent_phone": phone,
                    "agent_name": agent_name,
                    "message": f"{agent_name} just completed the onboarding form! "
                               f"They can now send listing photos or reply 'daily insight'.",
                },
            ))
    except Exception:
        pass  # Best-effort

    return templates.TemplateResponse("form_done.html", {
        "request": request,
        "name": agent_name,
        "already_submitted": False,
    })


# ---------------------------------------------------------------------------
# Client Detail Page
# ---------------------------------------------------------------------------

@router.get("/client/{phone}", response_class=HTMLResponse)
async def client_detail(request: Request, phone: str):
    """Show 23-field detail view for a single client."""
    profile = profile_manager.get_profile(phone)
    if not profile:
        raise HTTPException(404, "Client not found")

    completeness = compute_completeness(profile)
    guidance = get_recommended_experience(profile, completeness)
    dimensions = get_field_details(profile)

    # Load Skill briefs for this agent
    skills = []
    for skill_type, label in [("video", "视频 Skill"), ("insight", "资讯 Skill")]:
        brief_path = profile_manager.get_skill_brief_path(phone, skill_type)
        if skill_type == "video":
            # Auto-initialize video brief if it doesn't exist
            brief_path = profile_manager.init_skill_brief(phone, skill_type)
            content = brief_path.read_text()
        else:
            content = brief_path.read_text() if brief_path.exists() else None

        if content is not None:
            default_content = profile_manager.DEFAULT_BRIEF_PATH.read_text() if profile_manager.DEFAULT_BRIEF_PATH.exists() else ""
            is_customized = content != default_content if skill_type == "video" else True
            skills.append({
                "type": skill_type,
                "label": label,
                "content": content,
                "is_customized": is_customized,
                "size_bytes": len(content.encode()),
            })
        else:
            skills.append({
                "type": skill_type,
                "label": label,
                "content": None,
                "is_customized": False,
                "size_bytes": 0,
            })

    return templates.TemplateResponse("client_detail.html", {
        "request": request,
        "profile": profile,
        "completeness": completeness,
        "dimensions": dimensions,
        "phone": phone,
        "skills": skills,
        "field_labels": FIELD_LABELS,
        "guidance": guidance,
    })


@router.put("/client/{phone}/skills/{skill_type}")
async def update_skill_brief(phone: str, skill_type: str, request: Request):
    """Save an agent's Skill brief (called by inline editor)."""
    profile = profile_manager.get_profile(phone)
    if not profile:
        raise HTTPException(404, "Client not found")
    content = (await request.body()).decode("utf-8")
    profile_manager.update_skill_brief(phone, content, skill_type)
    return HTMLResponse("ok", status_code=200)


@router.post("/client/{phone}/skills/{skill_type}/reset")
async def reset_skill_brief(phone: str, skill_type: str):
    """Reset an agent's Skill brief to the global default."""
    profile = profile_manager.get_profile(phone)
    if not profile:
        raise HTTPException(404, "Client not found")
    if not profile_manager.DEFAULT_BRIEF_PATH.exists():
        raise HTTPException(404, "Default brief not found")
    default = profile_manager.DEFAULT_BRIEF_PATH.read_text()
    profile_manager.update_skill_brief(phone, default, skill_type)
    return HTMLResponse("ok", status_code=200)


@router.post("/api/update-field")
async def update_field(
    request: Request,
    phone: str = Form(...),
    field: str = Form(...),
    value: str = Form(""),
):
    """HTMX inline edit — operator can edit any field."""
    if field not in EDITABLE_FIELDS:
        raise HTTPException(403, f"Field '{field}' is not editable")

    profile = profile_manager.get_profile(phone)
    if not profile:
        raise HTTPException(404, "Client not found")

    updates = set_field_value(field, value.strip())
    profile_manager.update_profile(phone, updates)

    # Return minimal success response for HTMX
    return HTMLResponse('<span class="save-ok">已保存</span>', status_code=200)
