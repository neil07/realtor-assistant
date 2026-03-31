#!/usr/bin/env python3
"""
Operator Console — Memory Schema

Defines the complete set of fields a social media assistant needs to know
about a realtor client. 23 fields across 7 dimensions, with weights,
collection channels, and readiness rules.

The full schema lives here; the H5 form only collects ~7 fields.
Remaining fields accumulate via bot prompts, human chat, and organic extraction.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Field definitions (23 fields, 7 dimensions)
# ---------------------------------------------------------------------------
# collect: "form" = H5 onboarding form (bot sends link)
#          "bot"  = bot-driven flow (auto-ask after video delivery)
#          "human"= operator collects via chat
#          "organic" = auto-extracted from interactions

MEMORY_FIELDS: dict[str, dict] = {
    # ─── 基本信息（who are you）───
    "name": {
        "weight": 10,
        "path": "name",
        "required_for": ["video", "insight"],
        "collect": "form",
        "label": "姓名",
    },
    "phone": {
        "weight": 8,
        "path": "phone",
        "required_for": ["video", "insight"],
        "collect": "form",
        "label": "电话",
    },
    "brokerage": {
        "weight": 3,
        "path": "brokerage",
        "required_for": [],
        "collect": "human",
        "label": "经纪公司",
        "question": "Which brokerage are you with? This helps me add your branding to the videos.",
    },
    "city": {
        "weight": 5,
        "path": "city",
        "required_for": ["insight"],
        "collect": "form",
        "label": "城市",
    },
    # ─── 生意画像（what's your business like）───
    "market_area": {
        "weight": 10,
        "path": "content_preferences.market_area",
        "required_for": ["insight"],
        "collect": "form",
        "label": "服务区域",
    },
    "neighborhoods": {
        "weight": 6,
        "path": "business.neighborhoods",
        "required_for": [],
        "collect": "human",
        "label": "核心社区",
        "question": "What are the top 2-3 neighborhoods you work in most? I'll tailor your market insights to those areas.",
    },
    "price_range": {
        "weight": 5,
        "path": "business.price_range",
        "required_for": [],
        "collect": "organic",
        "label": "价格区间",
    },
    "client_demographic": {
        "weight": 7,
        "path": "business.client_demographic",
        "required_for": [],
        "collect": "form",
        "label": "客户类型",
    },
    "specialty": {
        "weight": 5,
        "path": "business.specialty",
        "required_for": [],
        "collect": "organic",
        "label": "专长",
    },
    "transaction_volume": {
        "weight": 2,
        "path": "business.transaction_volume",
        "required_for": [],
        "collect": "organic",
        "label": "成交量",
    },
    # ─── 视频偏好（how should videos look & sound）───
    "style": {
        "weight": 8,
        "path": "preferences.style",
        "required_for": ["video"],
        "collect": "form",
        "label": "视频风格",
    },
    "music": {
        "weight": 5,
        "path": "preferences.music",
        "required_for": ["video"],
        "collect": "bot",
        "label": "音乐偏好",
    },
    "show_price": {
        "weight": 3,
        "path": "preferences.show_price",
        "required_for": ["video"],
        "collect": "bot",
        "label": "视频显示价格",
    },
    "language": {
        "weight": 7,
        "path": "preferences.language",
        "required_for": ["video", "insight"],
        "collect": "form",
        "label": "语言",
    },
    # ─── 品牌（your personal brand）───
    "brand_tone": {
        "weight": 5,
        "path": "brand.tone",
        "required_for": [],
        "collect": "bot",
        "label": "品牌调性",
    },
    "tagline": {
        "weight": 3,
        "path": "brand.tagline",
        "required_for": [],
        "collect": "organic",
        "label": "标语",
    },
    "logo_available": {
        "weight": 2,
        "path": "brand.logo_available",
        "required_for": [],
        "collect": "organic",
        "label": "有 Logo",
    },
    "branding_colors": {
        "weight": 3,
        "path": "content_preferences.branding_colors",
        "required_for": ["insight"],
        "collect": "organic",
        "label": "品牌色",
    },
    # ─── 社媒现状（your social media today）───
    "platforms": {
        "weight": 6,
        "path": "social_media.platforms",
        "required_for": [],
        "collect": "form",
        "label": "社交平台",
    },
    "posting_frequency": {
        "weight": 3,
        "path": "social_media.posting_frequency",
        "required_for": [],
        "collect": "human",
        "label": "发帖频率",
        "question": "How often do you post on social media right now? (e.g. daily, a few times a week, rarely) This helps me plan your content calendar.",
    },
    "content_goals": {
        "weight": 4,
        "path": "social_media.content_goals",
        "required_for": [],
        "collect": "bot",
        "label": "内容目标",
    },
    "content_dislikes": {
        "weight": 4,
        "path": "social_media.content_dislikes",
        "required_for": [],
        "collect": "organic",
        "label": "内容禁忌",
    },
    # ─── 本地市场（your market knowledge）───
    "market_trends": {
        "weight": 4,
        "path": "market.trends_interest",
        "required_for": ["insight"],
        "collect": "human",
        "label": "关注市场趋势",
        "question": "What market trends are you most interested in? (e.g. price changes, new listings, days on market) I'll send you daily insights on those.",
    },
}

TOTAL_WEIGHT = sum(f["weight"] for f in MEMORY_FIELDS.values())  # 118

# ---------------------------------------------------------------------------
# Dimension grouping (7 dimensions for UI display)
# ---------------------------------------------------------------------------

DIMENSIONS: list[dict] = [
    {"key": "basics", "label": "基本信息", "fields": ["name", "phone", "brokerage", "city"]},
    {"key": "business", "label": "生意画像", "fields": ["market_area", "neighborhoods", "price_range", "client_demographic", "specialty", "transaction_volume"]},
    {"key": "video", "label": "视频偏好", "fields": ["style", "music", "show_price", "language"]},
    {"key": "brand", "label": "品牌", "fields": ["brand_tone", "tagline", "logo_available", "branding_colors"]},
    {"key": "social", "label": "社交媒体", "fields": ["platforms", "posting_frequency", "content_goals", "content_dislikes"]},
    {"key": "market", "label": "本地市场", "fields": ["market_trends"]},
]

# Operator-editable fields (admin can fill any field via console)
EDITABLE_FIELDS = set(MEMORY_FIELDS.keys())

# Backward compat alias
HUMAN_EDITABLE_FIELDS = EDITABLE_FIELDS

# Field name → Chinese label lookup (for templates)
FIELD_LABELS = {name: defn["label"] for name, defn in MEMORY_FIELDS.items()}

# ---------------------------------------------------------------------------
# Readiness rules — two core experiences
# ---------------------------------------------------------------------------

READINESS: dict[str, dict] = {
    "video": {
        "label": "视频就绪",
        "description": "可生成匹配经纪人风格的视频",
        "required": ["name", "phone", "style", "language"],
        "nice_to_have": ["music", "show_price", "brand_tone"],
    },
    "insight": {
        "label": "洞察就绪",
        "description": "可推送相关每日市场洞察",
        "required": ["name", "market_area", "language"],
        "nice_to_have": ["neighborhoods", "market_trends", "branding_colors"],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_path(profile: dict, dot_path: str):
    """Traverse a dot-separated path on a profile dict. Returns the value or None."""
    parts = dot_path.split(".")
    current = profile
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _is_filled(value) -> bool:
    """A field is filled if it's not None, not empty string, not empty list."""
    if value is None:
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    if isinstance(value, list) and len(value) == 0:
        return False
    if isinstance(value, bool):
        return True  # False is a valid answer for show_price, logo_available
    return True


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------

def compute_completeness(profile: dict) -> dict:
    """
    Compute memory completeness based on all 23 fields (total weight 127).

    Returns:
        score: 0.0-1.0
        percentage: 0-100
        filled: list of filled field names
        missing: list of missing field names
        missing_by_channel: { "bot": [...], "human": [...], "organic": [...] }
        readiness: { video: {ready, missing}, insight: {ready, missing} }
    """
    filled = []
    missing = []
    filled_weight = 0

    for field_name, field_def in MEMORY_FIELDS.items():
        value = _resolve_path(profile, field_def["path"])
        if _is_filled(value):
            filled.append(field_name)
            filled_weight += field_def["weight"]
        else:
            missing.append(field_name)

    # Group missing fields by collection channel
    missing_by_channel: dict[str, list[str]] = {}
    for field_name in missing:
        channel = MEMORY_FIELDS[field_name]["collect"]
        missing_by_channel.setdefault(channel, []).append(field_name)

    # Readiness check
    readiness = {}
    for service_name, rules in READINESS.items():
        svc_missing = [
            f for f in rules["required"]
            if f not in filled
        ]
        readiness[service_name] = {
            "ready": len(svc_missing) == 0,
            "missing": svc_missing,
        }

    score = filled_weight / TOTAL_WEIGHT if TOTAL_WEIGHT > 0 else 0.0

    return {
        "score": round(score, 3),
        "percentage": round(score * 100),
        "filled": filled,
        "missing": missing,
        "missing_by_channel": missing_by_channel,
        "readiness": readiness,
    }


def get_readiness(profile: dict) -> dict[str, bool]:
    """Quick readiness check. Returns {"video": True/False, "insight": True/False}."""
    result = compute_completeness(profile)
    return {
        svc: info["ready"]
        for svc, info in result["readiness"].items()
    }


def get_field_details(profile: dict) -> list[dict]:
    """Return fields grouped by dimension with current values.

    Each dimension dict contains:
        key, label, fields: list of {name, label, value, filled, collect, weight, required_for, editable}
    """
    result = []
    for dim in DIMENSIONS:
        fields = []
        for field_name in dim["fields"]:
            field_def = MEMORY_FIELDS[field_name]
            value = _resolve_path(profile, field_def["path"])
            # Format list values for display
            display_value = value
            if isinstance(value, list):
                display_value = ", ".join(str(v) for v in value) if value else None
            fields.append({
                "name": field_name,
                "label": field_def["label"],
                "value": display_value,
                "raw_value": value,
                "filled": _is_filled(value),
                "collect": field_def["collect"],
                "weight": field_def["weight"],
                "required_for": field_def["required_for"],
                "editable": field_name in HUMAN_EDITABLE_FIELDS,
                "path": field_def["path"],
                "question": field_def.get("question", ""),
            })
        result.append({
            "key": dim["key"],
            "label": dim["label"],
            "fields": fields,
        })
    return result


def set_field_value(field_name: str, value: str) -> dict:
    """Build a partial update dict for a given field name and string value.

    Only works for human-editable fields. Returns the nested dict structure
    expected by profile_manager.update_profile().
    """
    if field_name not in EDITABLE_FIELDS:
        raise ValueError(f"Field '{field_name}' is not editable")

    field_def = MEMORY_FIELDS[field_name]
    path = field_def["path"]
    parts = path.split(".")

    if len(parts) == 1:
        return {parts[0]: value}
    # Nested path: build nested dict
    result: dict = {}
    current = result
    for part in parts[:-1]:
        current[part] = {}
        current = current[part]
    current[parts[-1]] = value
    return result
