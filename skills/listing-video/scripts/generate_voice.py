#!/usr/bin/env python3
"""
Listing Video Agent — TTS Voice Generation
Generates voiceover audio from script using ElevenLabs or OpenAI TTS.
Supports voice cloning for personalized agent voices.
"""

import asyncio
import json
import os
import subprocess
import sys
import requests
from pathlib import Path

ELEVENLABS_API = "https://api.elevenlabs.io/v1"

# Default voices for different styles
DEFAULT_VOICES = {
    "male_energetic": "pNInz6obpgDQGcFmaJgB",     # Adam
    "male_professional": "ErXwobaYiN019PkySvjV",    # Antoni
    "female_energetic": "EXAVITQu4vr4xnSDxMaL",    # Bella
    "female_professional": "21m00Tcm4TlvDq8ikWAM",  # Rachel
}

# Emotion → ElevenLabs voice_settings overrides
EMOTION_PROFILES = {
    "excitement": {"stability": 0.35, "style_exaggeration": 0.55, "speed_factor": 1.05},
    "warmth":     {"stability": 0.55, "style_exaggeration": 0.30, "speed_factor": 0.95},
    "confidence": {"stability": 0.50, "style_exaggeration": 0.40, "speed_factor": 1.0},
    "urgency":    {"stability": 0.40, "style_exaggeration": 0.50, "speed_factor": 1.10},
    "neutral":    {"stability": 0.50, "style_exaggeration": 0.30, "speed_factor": 1.0},
}

# Property tier + style → default voice selection
_VOICE_MAP = {
    ("luxury", "elegant"): "male_professional",
    ("luxury", "energetic"): "male_energetic",
    ("luxury", "professional"): "male_professional",
    ("mid_range", "elegant"): "female_professional",
    ("mid_range", "energetic"): "male_energetic",
    ("mid_range", "professional"): "male_professional",
    ("starter", "energetic"): "female_energetic",
}


def generate_elevenlabs(
    text: str,
    output_path: str,
    voice_id: str = None,
    style: str = "professional",
    stability: float = 0.5,
    similarity_boost: float = 0.75,
    style_exaggeration: float = 0.3,
    emotion_profile: dict = None,
) -> dict:
    """
    Generate voiceover using ElevenLabs API.

    Args:
        text: Voiceover script
        output_path: Where to save the MP3/WAV
        voice_id: Specific voice (or cloned voice) ID
        style: Agent's preferred style
        stability: Voice stability (lower = more expressive)
        similarity_boost: How close to original voice
        style_exaggeration: Amount of style enhancement
        emotion_profile: Optional dict overriding stability/style_exaggeration
    """
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        return {"status": "error", "message": "ELEVENLABS_API_KEY not set"}

    if not voice_id:
        voice_id = DEFAULT_VOICES.get(f"male_{style}", DEFAULT_VOICES["male_professional"])

    # Apply emotion profile overrides
    if emotion_profile:
        stability = emotion_profile.get("stability", stability)
        style_exaggeration = emotion_profile.get("style_exaggeration", style_exaggeration)

    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }

    payload = {
        "text": text,
        "model_id": "eleven_v3",
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": style_exaggeration,
            "use_speaker_boost": True,
        },
    }
    
    resp = requests.post(
        f"{ELEVENLABS_API}/text-to-speech/{voice_id}",
        headers=headers,
        json=payload,
        timeout=60,
    )
    
    if resp.status_code != 200:
        return {"status": "error", "message": f"ElevenLabs error {resp.status_code}: {resp.text[:200]}"}
    
    Path(output_path).write_bytes(resp.content)
    
    # Estimate cost: ~1 credit per 50 chars
    chars = len(text)
    credits = chars / 50
    
    return {
        "status": "success",
        "audio_path": output_path,
        "characters": chars,
        "estimated_credits": credits,
        "estimated_cost_usd": credits * 0.01,
    }


def generate_openai_tts(
    text: str,
    output_path: str,
    voice: str = "onyx",
    model: str = "tts-1-hd",
    speed: float = 1.0,
) -> dict:
    """
    Fallback: Generate voiceover using OpenAI TTS API.
    
    Voices: alloy, echo, fable, onyx, nova, shimmer
    - onyx: Deep male, good for professional RE
    - nova: Female, warm and natural
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"status": "error", "message": "OPENAI_API_KEY not set"}
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": model,
        "input": text,
        "voice": voice,
        "speed": speed,
        "response_format": "mp3",
    }
    
    resp = requests.post(
        "https://api.openai.com/v1/audio/speech",
        headers=headers,
        json=payload,
        timeout=60,
    )
    
    if resp.status_code != 200:
        return {"status": "error", "message": f"OpenAI TTS error {resp.status_code}: {resp.text[:200]}"}
    
    Path(output_path).write_bytes(resp.content)
    
    # Cost: $0.030 per 1K chars for tts-1-hd
    cost = len(text) / 1000 * 0.030
    
    return {
        "status": "success",
        "audio_path": output_path,
        "characters": len(text),
        "estimated_cost_usd": cost,
    }


def clone_voice(
    audio_sample_path: str,
    agent_name: str,
    description: str = "Real estate agent voiceover",
) -> dict:
    """
    Clone an agent's voice from a sample recording.
    
    Args:
        audio_sample_path: Path to 30s+ audio sample
        agent_name: Name for the cloned voice
        description: Voice description
        
    Returns:
        {"status": "success", "voice_id": str}
    """
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        return {"status": "error", "message": "ELEVENLABS_API_KEY not set"}
    
    headers = {"xi-api-key": api_key}
    
    with open(audio_sample_path, "rb") as f:
        files = {"files": (Path(audio_sample_path).name, f, "audio/mpeg")}
        data = {
            "name": f"RE_Agent_{agent_name}",
            "description": description,
        }
        
        resp = requests.post(
            f"{ELEVENLABS_API}/voices/add",
            headers=headers,
            data=data,
            files=files,
            timeout=60,
        )
    
    if resp.status_code != 200:
        return {"status": "error", "message": f"Voice clone error: {resp.text[:200]}"}
    
    voice_id = resp.json().get("voice_id")
    return {
        "status": "success",
        "voice_id": voice_id,
        "message": f"Voice cloned! ID: {voice_id}",
    }


def generate_voiceover(
    text: str,
    output_path: str,
    voice_id: str = None,
    style: str = "professional",
    use_elevenlabs: bool = True,
) -> dict:
    """
    Main entry point: generate voiceover with fallback logic.
    
    Tries ElevenLabs first, falls back to OpenAI TTS.
    """
    from job_logger import get_logger, log_step_start, log_step_end

    logger = get_logger()
    log_step_start("tts_voiceover", {
        "text_length": len(text),
        "voice_id": voice_id or "default",
        "style": style,
        "engine": "elevenlabs" if use_elevenlabs else "openai",
    })

    if use_elevenlabs:
        result = generate_elevenlabs(text, output_path, voice_id=voice_id, style=style)
        if result["status"] == "success":
            log_step_end("tts_voiceover", result)
            return result
        # Fallback
        logger.warning("ElevenLabs failed: %s, trying OpenAI...", result["message"])

    result = generate_openai_tts(text, output_path)
    log_step_end("tts_voiceover", result)
    return result


def generate_scene_voiceovers(
    scenes: list[dict],
    output_dir: str,
    voice_id: str = None,
    style: str = "professional",
) -> list[dict]:
    """
    Generate individual TTS audio for each scene's narration.

    This enables precise audio-visual sync: each clip gets its own
    narration segment, and clip duration can be matched to audio length.

    Args:
        scenes: Scene plan list, each with "text_narration" and "sequence"
        output_dir: Directory to save individual audio files
        voice_id: ElevenLabs voice ID (or cloned voice)
        style: Voice style preference

    Returns:
        List of dicts per scene:
        {
            "sequence": int,
            "audio_path": str,
            "duration": float,
            "text": str,
            "status": "success"|"error"
        }
    """
    from job_logger import get_logger, log_step_start, log_step_end

    logger = get_logger()
    os.makedirs(output_dir, exist_ok=True)

    results = []
    narrated = [s for s in scenes if s.get("text_narration", "").strip()]

    log_step_start("per_scene_tts", {
        "total_scenes": len(narrated),
        "voice_id": voice_id or "default",
        "style": style,
    })

    for scene in narrated:
        seq = scene["sequence"]
        text = scene["text_narration"].strip()
        audio_path = os.path.join(output_dir, f"narration_{seq:02d}.mp3")

        logger.info("  TTS scene %02d: %d chars  %.40s...", seq, len(text), text)

        result = generate_voiceover(
            text=text,
            output_path=audio_path,
            voice_id=voice_id,
            style=style,
        )

        if result["status"] == "success":
            # Get actual audio duration
            duration = 0.0
            try:
                dur_cmd = [
                    "ffprobe", "-v", "quiet",
                    "-show_entries", "format=duration",
                    "-of", "json", audio_path,
                ]
                dur_result = subprocess.run(dur_cmd, capture_output=True, text=True, timeout=15)
                if dur_result.returncode == 0:
                    dur_data = json.loads(dur_result.stdout)
                    duration = float(dur_data.get("format", {}).get("duration", 0))
            except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, TypeError):
                pass

            results.append({
                "sequence": seq,
                "audio_path": audio_path,
                "duration": duration,
                "text": text,
                "status": "success",
            })
            logger.info("    -> %.1fs  %s", duration, audio_path)
        else:
            results.append({
                "sequence": seq,
                "audio_path": None,
                "duration": 0,
                "text": text,
                "status": "error",
                "message": result.get("message", ""),
            })
            logger.warning("    -> FAILED: %s", result.get("message", ""))

    log_step_end("per_scene_tts", {
        "status": "success",
        "succeeded": sum(1 for r in results if r["status"] == "success"),
        "total_duration": sum(r["duration"] for r in results),
    })

    return results


TTS_MAX_CONCURRENCY = 3


def _get_audio_duration(audio_path: str) -> float:
    """Get audio duration via ffprobe. Returns 0.0 on failure."""
    try:
        dur_cmd = [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "json", audio_path,
        ]
        dur_result = subprocess.run(dur_cmd, capture_output=True, text=True, timeout=15)
        if dur_result.returncode == 0:
            dur_data = json.loads(dur_result.stdout)
            return float(dur_data.get("format", {}).get("duration", 0))
    except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, TypeError):
        pass
    return 0.0


async def _tts_one_scene(
    sem: asyncio.Semaphore,
    seq: int,
    text: str,
    audio_path: str,
    voice_id: str,
    style: str,
) -> dict:
    """Generate TTS for a single scene, respecting concurrency limit."""
    async with sem:
        # Run blocking TTS + ffprobe in thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: generate_voiceover(text, audio_path, voice_id, style)
        )
        if result["status"] == "success":
            duration = await loop.run_in_executor(None, _get_audio_duration, audio_path)
            return {
                "sequence": seq, "audio_path": audio_path,
                "duration": duration, "text": text, "status": "success",
            }
        return {
            "sequence": seq, "audio_path": None,
            "duration": 0, "text": text, "status": "error",
            "message": result.get("message", ""),
        }


async def _generate_scene_voiceovers_async(
    scenes: list[dict],
    output_dir: str,
    voice_id: str = None,
    style: str = "professional",
) -> list[dict]:
    """Concurrently generate per-scene TTS with semaphore throttle."""
    os.makedirs(output_dir, exist_ok=True)
    narrated = [s for s in scenes if s.get("text_narration", "").strip()]
    sem = asyncio.Semaphore(TTS_MAX_CONCURRENCY)

    tasks = []
    for scene in narrated:
        seq = scene["sequence"]
        text = scene["text_narration"].strip()
        audio_path = os.path.join(output_dir, f"narration_{seq:02d}.mp3")
        tasks.append(_tts_one_scene(sem, seq, text, audio_path, voice_id, style))

    results = await asyncio.gather(*tasks)
    return sorted(results, key=lambda r: r["sequence"])


def generate_scene_voiceovers_concurrent(
    scenes: list[dict],
    output_dir: str,
    voice_id: str = None,
    style: str = "professional",
) -> list[dict]:
    """
    Generate per-scene TTS concurrently (up to TTS_MAX_CONCURRENCY in parallel).

    Drop-in replacement for generate_scene_voiceovers with ~3x speedup.
    """
    from job_logger import get_logger, log_step_start, log_step_end

    logger = get_logger()
    narrated = [s for s in scenes if s.get("text_narration", "").strip()]
    log_step_start("per_scene_tts_concurrent", {
        "total_scenes": len(narrated),
        "voice_id": voice_id or "default",
        "style": style,
        "max_concurrency": TTS_MAX_CONCURRENCY,
    })

    results = asyncio.run(
        _generate_scene_voiceovers_async(scenes, output_dir, voice_id, style)
    )

    log_step_end("per_scene_tts_concurrent", {
        "status": "success",
        "succeeded": sum(1 for r in results if r["status"] == "success"),
        "total_duration": sum(r["duration"] for r in results),
    })
    return results


def determine_scene_emotion(
    scene_desc: str,
    text_narration: str,
    room_type: str = "",
    sequence: int = 1,
    total_scenes: int = 1,
) -> str:
    """
    Rule-based emotion assignment per scene.
    No LLM needed — uses scene position, room type, and keywords.
    """
    desc_lower = (scene_desc + " " + text_narration).lower()

    # Position-based
    if sequence == 1:
        return "excitement"
    if sequence >= total_scenes:
        return "urgency"

    # Room-type heuristics
    if any(kw in desc_lower for kw in ["pool", "view", "ocean", "sunset", "wow", "stunning"]):
        return "excitement"
    if any(kw in desc_lower for kw in ["bedroom", "master", "suite", "cozy", "retreat"]):
        return "warmth"
    if any(kw in desc_lower for kw in ["kitchen", "granite", "appliance", "island"]):
        return "confidence"
    if any(kw in desc_lower for kw in ["price", "won't last", "weekend", "call"]):
        return "urgency"

    return "neutral"


def select_voice_for_property(
    property_tier: str = "mid_range",
    property_style: str = "professional",
    agent_gender: str = None,
) -> str:
    """Select an appropriate default voice based on property personality."""
    if agent_gender:
        gender = agent_gender
    else:
        gender = "male"  # default

    key = (property_tier, property_style)
    voice_key = _VOICE_MAP.get(key, f"{gender}_professional")
    return DEFAULT_VOICES.get(voice_key, DEFAULT_VOICES["male_professional"])


def generate_scene_voiceovers_v2(
    scenes: list[dict],
    output_dir: str,
    voice_id: str = None,
    style: str = "professional",
    property_tier: str = "mid_range",
) -> list[dict]:
    """
    Generate emotion-aware per-scene TTS.

    Each scene gets an emotion profile that adjusts voice stability,
    style exaggeration, and speed for appropriate emotional delivery.
    """
    from job_logger import get_logger, log_step_start, log_step_end

    logger = get_logger()
    os.makedirs(output_dir, exist_ok=True)

    # Auto-select voice if not provided
    if not voice_id:
        voice_id = select_voice_for_property(property_tier, style)

    results = []
    narrated = [s for s in scenes if s.get("text_narration", "").strip()]
    total = len(narrated)

    log_step_start("per_scene_tts_v2", {
        "total_scenes": total,
        "voice_id": voice_id,
        "style": style,
        "emotion_aware": True,
    })

    for scene in narrated:
        seq = scene["sequence"]
        text = scene["text_narration"].strip()
        audio_path = os.path.join(output_dir, f"narration_{seq:02d}.mp3")

        # Determine emotion
        emotion = determine_scene_emotion(
            scene_desc=scene.get("scene_desc", ""),
            text_narration=text,
            sequence=seq,
            total_scenes=total,
        )
        emo_profile = EMOTION_PROFILES.get(emotion, EMOTION_PROFILES["neutral"])

        logger.info("  TTS scene %02d: emotion=%s  %d chars", seq, emotion, len(text))

        # Try ElevenLabs with emotion profile
        result = generate_elevenlabs(
            text=text,
            output_path=audio_path,
            voice_id=voice_id,
            style=style,
            emotion_profile=emo_profile,
        )

        # Fallback to OpenAI with speed adjustment
        if result["status"] != "success":
            logger.warning("  ElevenLabs failed for scene %d, trying OpenAI", seq)
            result = generate_openai_tts(
                text=text,
                output_path=audio_path,
                speed=emo_profile.get("speed_factor", 1.0),
            )

        if result["status"] == "success":
            duration = 0.0
            try:
                dur_cmd = [
                    "ffprobe", "-v", "quiet",
                    "-show_entries", "format=duration",
                    "-of", "json", audio_path,
                ]
                dur_result = subprocess.run(dur_cmd, capture_output=True, text=True, timeout=15)
                if dur_result.returncode == 0:
                    dur_data = json.loads(dur_result.stdout)
                    duration = float(dur_data.get("format", {}).get("duration", 0))
            except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, TypeError):
                pass

            results.append({
                "sequence": seq,
                "audio_path": audio_path,
                "duration": duration,
                "text": text,
                "emotion": emotion,
                "status": "success",
            })
        else:
            results.append({
                "sequence": seq,
                "audio_path": None,
                "duration": 0,
                "text": text,
                "emotion": emotion,
                "status": "error",
                "message": result.get("message", ""),
            })

    log_step_end("per_scene_tts_v2", {
        "status": "success",
        "succeeded": sum(1 for r in results if r["status"] == "success"),
        "total_duration": sum(r["duration"] for r in results),
    })

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate TTS voiceover")
    subparsers = parser.add_subparsers(dest="command")

    # Single text TTS
    single = subparsers.add_parser("single", help="Generate TTS for a single text")
    single.add_argument("text", help="Text string or file path")
    single.add_argument("output", help="Output audio path")
    single.add_argument("--voice-id", default=None, help="ElevenLabs voice ID")
    single.add_argument("--style", default="professional", help="Voice style")

    # Batch per-scene TTS
    batch = subparsers.add_parser("batch", help="Generate per-scene TTS from scene plan")
    batch.add_argument("--scene-plan-file", required=True, help="Scene plan JSON file")
    batch.add_argument("--output-dir", required=True, help="Output directory for narration files")
    batch.add_argument("--voice-id", default=None, help="ElevenLabs voice ID")
    batch.add_argument("--style", default="professional", help="Voice style")
    batch.add_argument("--emotion-aware", action="store_true", help="Use emotion-aware TTS (V2)")
    batch.add_argument("--property-tier", default="mid_range", help="Property tier for voice selection")

    args = parser.parse_args()

    if args.command == "single":
        text = args.text
        if os.path.isfile(text):
            text = Path(text).read_text()
        result = generate_voiceover(text=text, output_path=args.output,
                                    voice_id=args.voice_id, style=args.style)
        print(json.dumps(result, indent=2))

    elif args.command == "batch":
        scenes = json.loads(Path(args.scene_plan_file).read_text())
        if args.emotion_aware:
            results = generate_scene_voiceovers_v2(
                scenes=scenes, output_dir=args.output_dir,
                voice_id=args.voice_id, style=args.style,
                property_tier=args.property_tier,
            )
        else:
            results = generate_scene_voiceovers(
                scenes=scenes, output_dir=args.output_dir,
                voice_id=args.voice_id, style=args.style,
            )
        print(json.dumps(results, indent=2))

    else:
        parser.print_help()
        sys.exit(1)
