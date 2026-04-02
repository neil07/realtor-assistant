#!/usr/bin/env python3
"""
Reel Agent — Admin Skill Brief Routes

Extracted from server.py for maintainability.
Provides admin UI for viewing/editing per-agent Skill briefs.
"""

import asyncio
import hmac
import json
import os
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

# Scripts path (needed for profile_manager import)
SCRIPTS_DIR = Path(__file__).parent.parent / "skills" / "listing-video" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

router = APIRouter(tags=["admin"])


# ---------------------------------------------------------------------------
# Structured logging (imported lazily from server to avoid circular dep)
# ---------------------------------------------------------------------------

def _structured_log(event: str, **kw) -> None:
    import logging
    logging.getLogger("reel_agent.admin").info(
        json.dumps({"event": event, **kw}, default=str)
    )


def _require_admin(request: Request) -> None:
    """Token auth for admin routes. Blocks access when ADMIN_TOKEN is not set."""
    token = os.environ.get("ADMIN_TOKEN", "")
    if not token:
        raise HTTPException(
            503, "Admin access disabled — set ADMIN_TOKEN env var to enable"
        )
    auth = request.headers.get("Authorization", "")
    if not hmac.compare_digest(auth, f"Bearer {token}"):
        _structured_log("admin_auth_fail", path=str(request.url.path))
        raise HTTPException(403, "Invalid or missing admin token")


# ---------------------------------------------------------------------------
# Admin HTML shell
# ---------------------------------------------------------------------------

_ADMIN_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8"><title>Reel Agent Admin</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background: #f8fafc; margin: 0; }}
  .nav {{ background: #1e293b; color: #fff; padding: 12px 24px; font-size: 15px; }}
  .nav a {{ color: #94a3b8; text-decoration: none; margin-left: 16px; }}
  .container {{ max-width: 900px; margin: 24px auto; padding: 0 16px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #e2e8f0; font-size: 14px; }}
  th {{ background: #f1f5f9; font-weight: 600; }}
  .badge {{ padding: 2px 8px; border-radius: 4px; font-size: 12px; }}
  .badge-custom {{ background: #dbeafe; color: #1d4ed8; }}
  .badge-default {{ background: #f1f5f9; color: #64748b; }}
  .btn {{ display: inline-block; padding: 6px 14px; background: #3b82f6; color: #fff;
          text-decoration: none; border-radius: 6px; font-size: 13px; border: none; cursor: pointer; }}
  .btn:hover {{ background: #2563eb; }}
  .editor-wrap {{ background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  textarea#editor {{ width: 100%; min-height: 500px; font-family: 'Menlo', monospace; font-size: 13px;
                     border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; resize: vertical; }}
  .actions {{ margin-top: 12px; display: flex; gap: 10px; align-items: center; }}
  .btn-save {{ background: #10b981; padding: 8px 20px; font-size: 14px; }}
  .btn-save:hover {{ background: #059669; }}
  .btn-reset {{ background: #ef4444; padding: 8px 16px; font-size: 14px; }}
  .btn-reset:hover {{ background: #dc2626; }}
  .toast {{ display:none; padding: 8px 16px; border-radius: 6px; font-size: 13px;
            background: #d1fae5; color: #065f46; }}
</style>
</head>
<body>
<div class="nav">🎬 Reel Agent Admin
  <a href="/admin">经纪人列表</a>
  <a href="/">测试界面</a>
</div>
{body}
<script>
async function saveSkill(phone, skillType) {{
  const content = document.getElementById('editor').value;
  const res = await fetch(`/admin/agents/${{phone}}/skills/${{skillType}}`, {{
    method: 'PUT',
    headers: {{'Content-Type': 'text/plain'}},
    body: content,
  }});
  const toast = document.getElementById('toast');
  if (res.ok) {{
    toast.style.display = 'inline';
    toast.textContent = '✅ 已保存';
    setTimeout(() => toast.style.display = 'none', 2500);
  }} else {{
    toast.style.background = '#fee2e2'; toast.style.color = '#991b1b';
    toast.style.display = 'inline';
    toast.textContent = '❌ 保存失败';
  }}
}}
async function resetSkill(phone, skillType) {{
  if (!confirm('确定恢复为全局默认 Brief？当前内容会丢失。')) return;
  const res = await fetch(`/admin/agents/${{phone}}/skills/${{skillType}}/reset`, {{method: 'POST'}});
  if (res.ok) location.reload();
}}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/admin", response_class=HTMLResponse)
async def admin_list_agents(request: Request):
    """Admin UI: list all agents and their Skill brief status."""
    _require_admin(request)
    import profile_manager

    briefs = await asyncio.to_thread(profile_manager.list_skill_briefs)
    all_profiles = []
    profiles_dir = Path(__file__).parent.parent / "skills" / "listing-video" / "profiles"
    for p in sorted(profiles_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text())
            all_profiles.append(data.get("phone", p.stem))
        except Exception:
            pass

    brief_index = {b["phone"]: b for b in briefs}
    rows = ""
    for phone in all_profiles:
        safe = profile_manager._safe_phone(phone)
        b = brief_index.get(safe, {})
        is_custom = b.get("is_customized", False)
        badge = (
            '<span class="badge badge-custom">已定制</span>'
            if is_custom
            else '<span class="badge badge-default">使用默认</span>'
        )
        edit_url = f"/admin/agents/{phone}/skills/video/edit"
        rows += f"<tr><td>{phone}</td><td>video</td><td>{badge}</td><td><a class='btn' href='{edit_url}'>编辑 Brief</a></td></tr>"

    body = f"""
    <div class="container">
      <h2>经纪人 Skill Brief 管理</h2>
      <table>
        <thead><tr><th>手机号</th><th>Skill</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""
    return _ADMIN_HTML.format(body=body)


@router.get("/admin/agents/{phone}/skills/{skill_type}/edit", response_class=HTMLResponse)
async def admin_edit_skill_ui(phone: str, skill_type: str, request: Request):
    """Admin UI: edit a specific agent's Skill brief in the browser."""
    _require_admin(request)
    import profile_manager

    content = await asyncio.to_thread(profile_manager.get_skill_brief, phone, skill_type)
    escaped = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    body = f"""
    <div class="container">
      <h2>编辑 Skill Brief — {phone} / {skill_type}</h2>
      <div class="editor-wrap">
        <textarea id="editor">{escaped}</textarea>
        <div class="actions">
          <button class="btn btn-save" onclick="saveSkill('{phone}','{skill_type}')">保存</button>
          <button class="btn btn-reset" onclick="resetSkill('{phone}','{skill_type}')">恢复默认</button>
          <span id="toast" class="toast"></span>
        </div>
      </div>
    </div>"""
    return _ADMIN_HTML.format(body=body)


@router.get("/admin/agents/{phone}/skills/{skill_type}")
async def admin_get_skill(phone: str, skill_type: str, request: Request):
    """API: return the raw Markdown content of an agent's Skill brief."""
    _require_admin(request)
    import profile_manager

    content = await asyncio.to_thread(profile_manager.get_skill_brief, phone, skill_type)
    return {"phone": phone, "skill_type": skill_type, "content": content}


@router.put("/admin/agents/{phone}/skills/{skill_type}", status_code=204)
async def admin_update_skill(phone: str, skill_type: str, request: Request):
    """API: overwrite an agent's Skill brief with plain-text Markdown body."""
    _require_admin(request)
    import profile_manager

    content = (await request.body()).decode("utf-8")
    if not content.strip():
        raise HTTPException(400, "Brief content cannot be empty")
    await asyncio.to_thread(profile_manager.update_skill_brief, phone, content, skill_type)


@router.post("/admin/agents/{phone}/skills/{skill_type}/reset", status_code=204)
async def admin_reset_skill(phone: str, skill_type: str, request: Request):
    """API: reset an agent's Skill brief to the global default."""
    _require_admin(request)
    import profile_manager

    default_path = (
        Path(__file__).parent.parent / "skills" / "listing-video" / "prompts" / "creative_director.md"
    )
    if not default_path.exists():
        raise HTTPException(404, "Global default brief not found")
    content = default_path.read_text()
    await asyncio.to_thread(profile_manager.update_skill_brief, phone, content, skill_type)
