#!/usr/bin/env python3
"""
Voice Clone Service — 声音复刻全生命周期管理

流程: 视频 → 提取音频 → 说话人分离 → 选择 → 克隆 → 试听 → 确认/拒绝
"""
from __future__ import annotations

import json
import logging
import os
import random
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

OUTPUT_BASE = Path(__file__).parent.parent / "output" / "voice-clones"

# 试听文案：随机选一条，让经纪人听到"自己的声音"读房产文案的效果
_PREVIEW_TEXTS = [
    (
        "Welcome to this stunning four-bedroom home in the heart of downtown. "
        "With panoramic views and modern finishes, this is where luxury meets comfort. "
        "Schedule your private showing today."
    ),
    (
        "This beautifully renovated property features an open floor plan, "
        "gourmet kitchen, and a private backyard oasis. "
        "Don't miss your chance to make this dream home yours."
    ),
    (
        "Nestled in one of the most sought-after neighborhoods, this charming home "
        "offers the perfect blend of character and modern convenience. "
        "Let me show you what makes this property truly special."
    ),
]

# 说话人最低可用时长（秒），低于此值无法克隆
MIN_SPEAKER_DURATION = 10.0

# 视频最大时长（秒），超过则拒绝
MAX_VIDEO_DURATION = 600.0


# ---------------------------------------------------------------------------
# Session 管理
# ---------------------------------------------------------------------------

def _session_dir(agent_phone: str, session_id: str) -> Path:
    """返回 session 目录路径。"""
    safe_phone = "".join(c for c in agent_phone if c.isdigit() or c == "+")
    return OUTPUT_BASE / safe_phone / session_id


def _save_session(session_dir: Path, data: dict) -> None:
    """持久化 session 状态到 JSON。"""
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False)
    )


def _load_session(session_dir: Path) -> dict | None:
    """加载 session 状态。"""
    path = session_dir / "session.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


# ---------------------------------------------------------------------------
# 音频提取
# ---------------------------------------------------------------------------

def extract_audio(video_path: str, output_dir: str) -> dict:
    """从视频中提取音频（WAV 16kHz mono，pyannote 输入格式）。

    Args:
        video_path: 视频文件路径
        output_dir: 输出目录

    Returns:
        {status, audio_path, duration} 或 {status, message}
    """
    if not os.path.isfile(video_path):
        return {"status": "error", "message": f"Video file not found: {video_path}"}

    os.makedirs(output_dir, exist_ok=True)
    audio_path = os.path.join(output_dir, "extracted.wav")

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn",                    # 去掉视频轨
        "-acodec", "pcm_s16le",   # 16-bit PCM
        "-ar", "16000",           # 16kHz 采样率（pyannote 要求）
        "-ac", "1",               # 单声道
        audio_path,
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return {"status": "error", "message": f"ffmpeg failed: {result.stderr[:300]}"}
    except FileNotFoundError:
        return {"status": "error", "message": "ffmpeg not found on system"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "ffmpeg timed out (>120s)"}

    # 获取时长
    duration = _get_audio_duration(audio_path)
    if duration is None:
        return {"status": "error", "message": "Could not determine audio duration"}

    if duration > MAX_VIDEO_DURATION:
        return {
            "status": "error",
            "message": f"Video too long ({duration:.0f}s). Max {MAX_VIDEO_DURATION:.0f}s.",
        }

    if duration < MIN_SPEAKER_DURATION:
        return {
            "status": "error",
            "message": f"Audio too short ({duration:.1f}s). Need at least {MIN_SPEAKER_DURATION:.0f}s of speech.",
        }

    logger.info("Extracted audio: %.1fs → %s", duration, audio_path)
    return {"status": "success", "audio_path": audio_path, "duration": duration}


def _get_audio_duration(audio_path: str) -> float | None:
    """用 ffprobe 获取音频时长。"""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "json", audio_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 0))
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 说话人分离 (Speaker Diarization)
# ---------------------------------------------------------------------------

def diarize_speakers(audio_path: str, output_dir: str) -> dict:
    """用 pyannote.audio 做说话人分离，按说话人导出合并音频片段。

    Args:
        audio_path: 提取后的 WAV 音频路径
        output_dir: 输出目录

    Returns:
        {status, speakers: [{speaker_id, audio_path, duration, segments}]}
    """
    try:
        from pyannote.audio import Pipeline
    except ImportError:
        return {
            "status": "error",
            "message": "pyannote.audio not installed. Run: pip install pyannote.audio",
        }

    try:
        from pydub import AudioSegment
    except ImportError:
        return {
            "status": "error",
            "message": "pydub not installed. Run: pip install pydub",
        }

    # 加载 pyannote diarization pipeline
    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
        )
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to load pyannote pipeline: {e}",
        }

    # 运行 diarization
    logger.info("Running speaker diarization on %s ...", audio_path)
    try:
        diarization = pipeline(audio_path)
    except Exception as e:
        return {"status": "error", "message": f"Diarization failed: {e}"}

    # 按说话人分组 segments
    speaker_segments: dict[str, list[tuple[float, float]]] = {}
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        speaker_segments.setdefault(speaker, []).append((turn.start, turn.end))

    if not speaker_segments:
        return {"status": "error", "message": "No speech detected in audio"}

    # 加载完整音频用于切片
    full_audio = AudioSegment.from_wav(audio_path)

    speakers = []
    for idx, (speaker_label, segments) in enumerate(
        sorted(speaker_segments.items(), key=lambda x: -sum(e - s for s, e in x[1]))
    ):
        # 按总时长降序排列，说话最多的人排第一
        speaker_id = f"speaker_{idx}"
        total_duration = sum(end - start for start, end in segments)

        # 过滤掉太短的说话人
        if total_duration < MIN_SPEAKER_DURATION:
            logger.info(
                "Skipping %s (%.1fs < %.0fs minimum)",
                speaker_label, total_duration, MIN_SPEAKER_DURATION,
            )
            continue

        # 拼接该说话人的所有片段
        combined = AudioSegment.empty()
        for start, end in segments:
            start_ms = int(start * 1000)
            end_ms = int(end * 1000)
            combined += full_audio[start_ms:end_ms]

        # 导出
        speaker_path = os.path.join(output_dir, f"{speaker_id}.wav")
        combined.export(speaker_path, format="wav")

        speakers.append({
            "speaker_id": speaker_id,
            "audio_path": speaker_path,
            "duration": round(total_duration, 1),
            "segments": [(round(s, 2), round(e, 2)) for s, e in segments],
        })

    if not speakers:
        return {
            "status": "error",
            "message": f"No speaker with enough speech (min {MIN_SPEAKER_DURATION:.0f}s)",
        }

    logger.info("Diarization complete: %d speaker(s) detected", len(speakers))
    return {"status": "success", "speakers": speakers}


# ---------------------------------------------------------------------------
# 全流程入口：提取 + 分离
# ---------------------------------------------------------------------------

def process_video_for_cloning(video_path: str, agent_phone: str) -> dict:
    """处理视频：提取音频 → 说话人分离 → 返回候选列表。

    Args:
        video_path: 视频文件路径
        agent_phone: 经纪人手机号

    Returns:
        {status, session_id, speakers, single_speaker}
    """
    session_id = str(uuid.uuid4())[:8]
    session = _session_dir(agent_phone, session_id)
    session.mkdir(parents=True, exist_ok=True)

    # Step 1: 提取音频
    extract_result = extract_audio(video_path, str(session))
    if extract_result["status"] != "success":
        return extract_result

    audio_path = extract_result["audio_path"]

    # Step 2: 说话人分离
    diarize_result = diarize_speakers(audio_path, str(session))
    if diarize_result["status"] != "success":
        return diarize_result

    speakers = diarize_result["speakers"]

    # 构建返回的 audio_url（相对路径，通过 /output/ 静态服务访问）
    for sp in speakers:
        rel = os.path.relpath(sp["audio_path"], str(OUTPUT_BASE.parent))
        sp["audio_url"] = f"/output/{rel}"

    # 保存 session 状态
    _save_session(session, {
        "session_id": session_id,
        "agent_phone": agent_phone,
        "video_path": video_path,
        "speakers": speakers,
        "status": "awaiting_selection",
        "created_at": datetime.now().isoformat(),
    })

    return {
        "status": "success",
        "session_id": session_id,
        "speakers": [
            {
                "speaker_id": sp["speaker_id"],
                "audio_url": sp["audio_url"],
                "audio_path": sp["audio_path"],
                "duration": sp["duration"],
            }
            for sp in speakers
        ],
        "single_speaker": len(speakers) == 1,
        # MEDIA: directives for multi-speaker samples (agent includes these in reply)
        "media_directives": "\n".join(
            f"MEDIA:{sp['audio_path']}" for sp in speakers
        ),
    }


# ---------------------------------------------------------------------------
# 选中说话人后：克隆 + 试听
# ---------------------------------------------------------------------------

def clone_selected_speaker(
    agent_phone: str,
    session_id: str,
    speaker_id: str,
    agent_name: str = "",
) -> dict:
    """用选中说话人的音频克隆声音，并生成试听。

    克隆成功后 voice_id 暂存在 session.json，不写 profile。
    等经纪人确认后才写。

    Returns:
        {status, voice_id, preview_audio_url, message}
    """
    import generate_voice

    session = _session_dir(agent_phone, session_id)
    session_data = _load_session(session)
    if not session_data:
        return {"status": "error", "message": f"Session {session_id} not found"}

    # 找到选中的说话人音频
    speaker_audio = None
    for sp in session_data.get("speakers", []):
        if sp["speaker_id"] == speaker_id:
            speaker_audio = sp["audio_path"]
            break

    if not speaker_audio or not os.path.isfile(speaker_audio):
        return {"status": "error", "message": f"Speaker {speaker_id} audio not found"}

    # 克隆
    name = agent_name or agent_phone
    clone_result = generate_voice.clone_voice(speaker_audio, name)
    if clone_result["status"] != "success":
        return clone_result

    voice_id = clone_result["voice_id"]

    # 生成试听
    preview_path = str(session / "preview.mp3")
    preview_result = generate_preview(voice_id, preview_path)

    # 更新 session
    session_data["status"] = "awaiting_confirmation"
    session_data["selected_speaker"] = speaker_id
    session_data["voice_id"] = voice_id
    _save_session(session, session_data)

    preview_url = None
    if preview_result["status"] == "success":
        rel = os.path.relpath(preview_path, str(OUTPUT_BASE.parent))
        preview_url = f"/output/{rel}"

    return {
        "status": "success",
        "voice_id": voice_id,
        "preview_audio_url": preview_url,
        "preview_audio_path": preview_path,
        "preview_text": preview_result.get("text_used", ""),
        "message": (
            "Voice cloned successfully. Listen to the preview and confirm.\n\n"
            f"MEDIA:{preview_path}"
        ),
    }


# ---------------------------------------------------------------------------
# 试听生成
# ---------------------------------------------------------------------------

def generate_preview(voice_id: str, output_path: str) -> dict:
    """用克隆声音生成试听音频（~10s 房产文案）。

    Returns:
        {status, audio_path, text_used}
    """
    import generate_voice

    text = random.choice(_PREVIEW_TEXTS)

    result = generate_voice.generate_elevenlabs(
        text=text,
        output_path=output_path,
        voice_id=voice_id,
    )

    if result["status"] == "success":
        return {
            "status": "success",
            "audio_path": output_path,
            "text_used": text,
        }

    return {
        "status": "error",
        "message": f"Preview generation failed: {result.get('message', '')}",
        "text_used": text,
    }


# ---------------------------------------------------------------------------
# 确认 / 拒绝
# ---------------------------------------------------------------------------

def confirm_clone(agent_phone: str, voice_id: str) -> dict:
    """经纪人确认使用克隆声音，存入 profile。"""
    import profile_manager

    # Auto-create profile if it doesn't exist
    if not profile_manager.get_profile(agent_phone):
        profile_manager.create_profile(phone=agent_phone, name=agent_phone)
        logger.info("Auto-created profile for %s", agent_phone)

    profile_manager.set_voice_clone(agent_phone, voice_id)

    # 记录元数据
    profile_manager.update_profile(agent_phone, {
        "voice_clone_created_at": datetime.now().isoformat(),
    })

    logger.info("Voice clone confirmed for %s: %s", agent_phone, voice_id)
    return {
        "status": "confirmed",
        "voice_id": voice_id,
        "message": "Your voice will be used in all future videos.",
    }


def reject_clone(agent_phone: str, voice_id: str) -> dict:
    """经纪人拒绝克隆声音，删除 ElevenLabs 上的声音。"""
    import generate_voice

    delete_result = generate_voice.delete_voice(voice_id)

    if delete_result["status"] != "success":
        logger.warning(
            "Failed to delete voice %s from ElevenLabs: %s",
            voice_id, delete_result.get("message"),
        )

    logger.info("Voice clone rejected for %s: %s", agent_phone, voice_id)
    return {
        "status": "rejected",
        "message": "No problem, we'll keep using the default voice.",
    }


# ---------------------------------------------------------------------------
# 查询状态
# ---------------------------------------------------------------------------

def get_clone_status(agent_phone: str) -> dict:
    """查询经纪人的声音克隆状态。"""
    import profile_manager

    profile = profile_manager.get_profile(agent_phone)
    if not profile:
        return {"has_clone": False, "voice_id": None, "offered": False}

    return {
        "has_clone": bool(profile.get("voice_clone_id")),
        "voice_id": profile.get("voice_clone_id"),
        "offered": profile.get("voice_clone_offered", False),
        "created_at": profile.get("voice_clone_created_at"),
    }
