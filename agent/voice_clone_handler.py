#!/usr/bin/env python3
"""
Voice Clone Trigger Layer — 对话状态管理 + 意图路由

连接用户消息（WhatsApp/Telegram）和 voice_clone_service.py。
管理多轮对话状态：发起 → 接收媒体 → 选择说话人 → 确认/拒绝。

Session 状态由 voice_clone_service 管理（文件系统），
本模块只负责读取状态做路由决策。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# voice_clone_service 的 OUTPUT_BASE，用于查找 session
_OUTPUT_BASE = (
    Path(__file__).parent.parent / "skills" / "listing-video" / "output" / "voice-clones"
)

# 确认/拒绝关键词
_CONFIRM_KEYWORDS = {
    "use this voice", "confirm", "yes", "ok", "好的", "确认",
    "用这个声音", "可以", "就这个", "对", "嗯", "use it",
}
_REJECT_KEYWORDS = {
    "no thanks", "no", "reject", "不", "不要", "重来", "换一个",
    "不好", "算了", "cancel", "取消", "retry", "重新",
}
# 说话人选择：数字或 "speaker_0" 格式
_SPEAKER_SELECT_PATTERNS = {"1", "2", "3", "speaker_0", "speaker_1", "speaker_2"}

# 声音克隆请求关键词（同 server.py 保持一致，但更完整）
VOICE_CLONE_KEYWORDS = {
    "clone my voice", "use my voice", "voice clone",
    "克隆声音", "用我的声音", "克隆我的声音",
    "用我自己的声音", "我想用自己的声音录", "我想用自己的声音",
    "i want to use my own voice", "record with my voice",
}


def get_active_clone_session(agent_phone: str) -> dict | None:
    """查找经纪人当前活跃的声音克隆 session。

    扫描该用户的所有 session 目录，返回最新的未完成 session。
    状态为 awaiting_selection 或 awaiting_confirmation 视为活跃。

    Args:
        agent_phone: 经纪人手机号

    Returns:
        Session dict（含 session_id, status, speakers 等），或 None
    """
    safe_phone = "".join(c for c in agent_phone if c.isdigit() or c == "+")
    user_dir = _OUTPUT_BASE / safe_phone

    if not user_dir.exists():
        return None

    # 按修改时间降序扫描，找最新活跃 session
    sessions = []
    for session_dir in user_dir.iterdir():
        if not session_dir.is_dir():
            continue
        session_file = session_dir / "session.json"
        if not session_file.exists():
            continue
        try:
            data = json.loads(session_file.read_text())
            status = data.get("status", "")
            if status in ("awaiting_selection", "awaiting_confirmation"):
                data["_mtime"] = session_file.stat().st_mtime
                sessions.append(data)
        except (json.JSONDecodeError, OSError):
            continue

    if not sessions:
        return None

    # 返回最新的活跃 session
    sessions.sort(key=lambda s: s.get("_mtime", 0), reverse=True)
    result = sessions[0]
    result.pop("_mtime", None)
    return result


def classify_voice_clone_intent(
    text: str,
    has_media: bool,
    agent_phone: str,
    active_session: dict | None = None,
) -> dict | None:
    """判断消息是否属于声音克隆对话流。

    按优先级检查：
    1. 用户在 awaiting_confirmation 状态 → 检查确认/拒绝
    2. 用户在 awaiting_selection 状态 + 文本是数字 → 选择说话人
    3. 用户在任何活跃 session + 发送媒体 → 不应该发生（已处理过），忽略
    4. 无活跃 session + 发送媒体 + 之前表达过意图 → 处理视频（需上层判断）

    Args:
        text: 消息文本
        has_media: 是否包含媒体
        agent_phone: 经纪人手机号
        active_session: 预查询的活跃 session（避免重复 IO）

    Returns:
        路由 dict（含 intent, action 等），或 None（不属于声音克隆流）
    """
    t = text.strip().lower()

    # 先检查是否有活跃 session
    if active_session:
        session_status = active_session.get("status", "")
        session_id = active_session.get("session_id", "")
        voice_id = active_session.get("voice_id")

        # 状态 1: 等待确认/拒绝试听结果
        if session_status == "awaiting_confirmation" and voice_id:
            if any(kw in t for kw in _CONFIRM_KEYWORDS):
                return {
                    "intent": "voice_clone_confirm",
                    "action": "confirm_clone",
                    "voice_id": voice_id,
                    "session_id": session_id,
                    "response": (
                        "Your voice has been saved! All future listing videos "
                        "will use your cloned voice. 🎙️"
                    ),
                }
            if any(kw in t for kw in _REJECT_KEYWORDS):
                return {
                    "intent": "voice_clone_reject",
                    "action": "reject_clone",
                    "voice_id": voice_id,
                    "session_id": session_id,
                    "response": (
                        "No problem — we'll keep using the default voice. "
                        "You can try again anytime by saying 'clone my voice'."
                    ),
                }
            # 任何其他文本在确认等待中 → 提示用户确认或拒绝
            return {
                "intent": "voice_clone_pending",
                "action": "prompt_confirm",
                "voice_id": voice_id,
                "session_id": session_id,
                "response": (
                    "Did you listen to the preview? Reply 'yes' to use this voice, "
                    "or 'no' to keep the default."
                ),
            }

        # 状态 2: 等待选择说话人
        if session_status == "awaiting_selection":
            speakers = active_session.get("speakers", [])
            selected = _parse_speaker_selection(t, speakers)
            if selected:
                return {
                    "intent": "voice_clone_select",
                    "action": "select_speaker",
                    "session_id": session_id,
                    "speaker_id": selected,
                    "response": f"Got it — cloning voice from {selected}... 🎙️",
                }
            # 文本不是有效选择 → 提示用户
            speaker_count = len(speakers)
            return {
                "intent": "voice_clone_pending",
                "action": "prompt_select",
                "session_id": session_id,
                "speakers": speakers,
                "response": (
                    f"Which speaker is you? Reply with a number (1-{speaker_count})."
                ),
            }

    # 无活跃 session：检查是否是新的声音克隆请求关键词
    if any(kw in t for kw in VOICE_CLONE_KEYWORDS):
        return {
            "intent": "voice_clone",
            "action": "request_voice_clone",
            "response": (
                "I can clone your voice! Send me a short video or audio of yourself "
                "talking (30+ seconds) and I'll create a voice that sounds like you "
                "for all your listing videos. 🎙️"
            ),
            "awaiting": "voice_sample_media",
        }

    return None


def _parse_speaker_selection(text: str, speakers: list[dict]) -> str | None:
    """从文本中解析说话人选择。

    支持格式：
    - 数字: "1", "2" → speaker_0, speaker_1
    - 直接 ID: "speaker_0"

    Returns:
        speaker_id 字符串，或 None
    """
    t = text.strip()

    # 数字选择：1-based → 0-based
    if t.isdigit():
        idx = int(t) - 1
        if 0 <= idx < len(speakers):
            return speakers[idx].get("speaker_id", f"speaker_{idx}")
        return None

    # 直接 speaker_id
    for sp in speakers:
        if t == sp.get("speaker_id"):
            return sp["speaker_id"]

    return None


def download_media_to_temp(media_path_or_url: str) -> str | None:
    """将媒体文件复制或下载到临时目录。

    OpenClaw webhook 通常已将媒体保存到本地路径（media_paths）。
    如果路径已存在则直接返回，否则尝试作为 URL 下载。

    Args:
        media_path_or_url: 本地路径或 HTTP(S) URL

    Returns:
        本地文件路径，或 None（失败时）
    """
    # 本地文件：直接返回
    if os.path.isfile(media_path_or_url):
        return media_path_or_url

    # URL 下载
    if media_path_or_url.startswith(("http://", "https://")):
        try:
            import httpx

            suffix = _guess_suffix(media_path_or_url)
            tmp = tempfile.NamedTemporaryFile(
                delete=False, suffix=suffix, prefix="vc_media_"
            )
            with httpx.stream("GET", media_path_or_url, timeout=120, follow_redirects=True) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_bytes(chunk_size=65536):
                    tmp.write(chunk)
            tmp.close()
            logger.info("Downloaded media: %s → %s", media_path_or_url, tmp.name)
            return tmp.name
        except Exception as e:
            logger.error("Media download failed: %s — %s", media_path_or_url, e)
            return None

    logger.warning("Media not found and not a URL: %s", media_path_or_url)
    return None


def _guess_suffix(url: str) -> str:
    """从 URL 猜测文件后缀。"""
    path = url.split("?")[0].split("#")[0]
    for ext in (".mp4", ".mov", ".webm", ".ogg", ".oga", ".wav", ".mp3", ".m4a"):
        if path.lower().endswith(ext):
            return ext
    return ".mp4"  # 默认假设视频


def should_route_media_to_voice_clone(
    text: str,
    media_paths: list[str],
    agent_phone: str,
) -> bool:
    """判断带媒体的消息是否应路由到声音克隆（而非 listing video）。

    条件：有媒体 + （文本含声音克隆关键词 OR 该用户有活跃声音克隆 session）

    Args:
        text: 消息文本
        media_paths: 媒体文件路径列表
        agent_phone: 经纪人手机号

    Returns:
        True 表示应路由到声音克隆
    """
    if not media_paths:
        return False

    t = text.strip().lower()

    # 文本明确提到声音克隆
    if any(kw in t for kw in VOICE_CLONE_KEYWORDS):
        return True

    # 检查是否有 "voice" / "audio" / "声音" 等暗示
    _VOICE_HINTS = {"voice", "audio", "声音", "录音", "语音", "speaking", "talking"}
    if any(h in t for h in _VOICE_HINTS):
        return True

    return False


def build_proactive_offer(agent_phone: str) -> dict | None:
    """检查是否应主动推荐声音克隆，返回推荐消息。

    调用 profile_manager.should_offer_voice_clone() 判断。
    调用后需要调用 mark_voice_clone_offered() 标记已推荐。

    Args:
        agent_phone: 经纪人手机号

    Returns:
        推荐 dict 或 None
    """
    import profile_manager

    if not profile_manager.should_offer_voice_clone(agent_phone):
        return None

    profile = profile_manager.get_profile(agent_phone)
    lang = "en"
    if profile:
        lang = (
            profile.get("content_preferences", {}).get("language")
            or profile.get("preferences", {}).get("language")
            or "en"
        )

    if lang.startswith("zh"):
        msg = (
            "你已经成功制作了视频！想让视频用你自己的声音配音吗？"
            "发一段 30 秒以上的自我介绍视频或语音，我就能克隆你的声音。\n\n"
            "回复「克隆声音」开始，或忽略此消息。"
        )
    else:
        msg = (
            "Great job on your listing video! Want to use your own voice "
            "for narration? Send a 30+ second video or audio of yourself talking "
            "and I'll clone your voice for all future videos.\n\n"
            "Reply 'clone my voice' to get started, or just ignore this message."
        )

    # 标记为已推荐
    profile_manager.mark_voice_clone_offered(agent_phone)

    return {
        "intent": "voice_clone_offer",
        "action": "offer_voice_clone",
        "response": msg,
        "proactive": True,
    }
