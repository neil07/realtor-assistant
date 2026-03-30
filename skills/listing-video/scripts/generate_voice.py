#!/usr/bin/env python3
"""
Listing Video Agent — TTS Voice Generation
Primary: IMA Studio API (MiniMax Speech-02-HD / ByteDance Seed-TTS).
Fallback: ElevenLabs → OpenAI TTS.
"""

import json
import os
import sys
from pathlib import Path

import requests

ELEVENLABS_API = "https://api.elevenlabs.io/v1"

# Default voices for different styles (ElevenLabs fallback)
DEFAULT_VOICES = {
    "male_energetic": "pNInz6obpgDQGcFmaJgB",     # Adam
    "male_professional": "ErXwobaYiN019PkySvjV",    # Antoni
    "female_energetic": "EXAVITQu4vr4xnSDxMaL",    # Bella
    "female_professional": "21m00Tcm4TlvDq8ikWAM",  # Rachel
}


# ---------------------------------------------------------------------------
# Primary: IMA Studio TTS
# ---------------------------------------------------------------------------

def generate_ima_tts(
    text: str,
    output_path: str,
    model_id: str = None,
) -> dict:
    """
    Generate voiceover using IMA Studio text-to-speech API.

    Args:
        text: Voiceover script
        output_path: Where to save the audio file
        model_id: IMA TTS model (e.g. "speech-02-hd", "seed-tts")
    """
    from ima_client import generate_tts

    if not model_id:
        model_id = os.environ.get("IMA_TTS_MODEL", "seed-tts-1.1")

    return generate_tts(
        text=text,
        output_path=output_path,
        model_id=model_id,
    )


# ---------------------------------------------------------------------------
# Fallback 1: ElevenLabs
# ---------------------------------------------------------------------------

def generate_elevenlabs(
    text: str,
    output_path: str,
    voice_id: str = None,
    style: str = "professional",
    stability: float = 0.5,
    similarity_boost: float = 0.75,
    style_exaggeration: float = 0.3,
) -> dict:
    """Generate voiceover using ElevenLabs API."""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        return {"status": "error", "message": "ELEVENLABS_API_KEY not set"}

    if not voice_id:
        voice_id = DEFAULT_VOICES.get(f"male_{style}", DEFAULT_VOICES["male_professional"])

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
    )

    if resp.status_code != 200:
        return {"status": "error", "message": f"ElevenLabs error {resp.status_code}: {resp.text[:200]}"}

    Path(output_path).write_bytes(resp.content)

    return {
        "status": "success",
        "audio_path": output_path,
        "characters": len(text),
    }


# ---------------------------------------------------------------------------
# Fallback 2: OpenAI TTS
# ---------------------------------------------------------------------------

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
    )

    if resp.status_code != 200:
        return {"status": "error", "message": f"OpenAI TTS error {resp.status_code}: {resp.text[:200]}"}

    Path(output_path).write_bytes(resp.content)

    return {
        "status": "success",
        "audio_path": output_path,
        "characters": len(text),
    }


# ---------------------------------------------------------------------------
# Voice Cloning (ElevenLabs)
# ---------------------------------------------------------------------------

def clone_voice(
    audio_sample_path: str,
    agent_name: str,
    description: str = "Real estate agent voiceover",
) -> dict:
    """Clone an agent's voice from a sample recording."""
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
        )

    if resp.status_code != 200:
        return {"status": "error", "message": f"Voice clone error: {resp.text[:200]}"}

    voice_id = resp.json().get("voice_id")
    return {
        "status": "success",
        "voice_id": voice_id,
        "message": f"Voice cloned! ID: {voice_id}",
    }


# ---------------------------------------------------------------------------
# Main entry: IMA → ElevenLabs → OpenAI
# ---------------------------------------------------------------------------

def generate_voiceover(
    text: str,
    output_path: str,
    voice_id: str = None,
    style: str = "professional",
) -> dict:
    """
    Main entry point: generate voiceover with fallback chain.

    IMA Studio (primary) → ElevenLabs → OpenAI TTS.
    """
    import video_diagnostics
    from job_logger import get_logger, log_step_end, log_step_start

    logger = get_logger()
    attempts = []
    log_step_start("tts_voiceover", {
        "text_length": len(text),
        "voice_id": voice_id or "default",
        "style": style,
        "engine": "ima",
    })

    # Primary: IMA Studio TTS
    result = generate_ima_tts(text, output_path)
    attempts.append(video_diagnostics.build_attempt_record(
        engine="ima",
        status=result.get("status", "error"),
        result=result,
        characters=len(text),
    ))
    if result["status"] == "success":
        result["engine"] = "ima"
        result["attempts"] = attempts
        log_step_end("tts_voiceover", result)
        return result
    logger.warning("IMA TTS failed: %s, trying ElevenLabs...", result["message"])

    # Fallback 1: ElevenLabs
    result = generate_elevenlabs(text, output_path, voice_id=voice_id, style=style)
    attempts.append(video_diagnostics.build_attempt_record(
        engine="elevenlabs",
        status=result.get("status", "error"),
        result=result,
        characters=len(text),
    ))
    if result["status"] == "success":
        result["engine"] = "elevenlabs"
        result["attempts"] = attempts
        log_step_end("tts_voiceover", result)
        return result
    logger.warning("ElevenLabs failed: %s, trying OpenAI...", result["message"])

    # Fallback 2: OpenAI TTS
    result = generate_openai_tts(text, output_path)
    attempts.append(video_diagnostics.build_attempt_record(
        engine="openai_tts",
        status=result.get("status", "error"),
        result=result,
        characters=len(text),
    ))
    result["engine"] = "openai_tts" if result["status"] == "success" else None
    result["attempts"] = attempts
    log_step_end("tts_voiceover", result)
    return result


# ---------------------------------------------------------------------------
# Per-scene voiceover generation
# ---------------------------------------------------------------------------

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
    """
    import video_diagnostics
    from job_logger import get_logger, log_step_end, log_step_start

    logger = get_logger()
    os.makedirs(output_dir, exist_ok=True)
    job_dir = str(Path(output_dir).parent)
    video_diagnostics.record_scene_plan(job_dir, scenes)

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
            import subprocess
            dur_cmd = [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "json", audio_path,
            ]
            dur_result = subprocess.run(dur_cmd, capture_output=True, text=True)
            duration = 0.0
            if dur_result.returncode == 0:
                dur_data = json.loads(dur_result.stdout)
                duration = float(dur_data.get("format", {}).get("duration", 0))

            results.append({
                "sequence": seq,
                "audio_path": audio_path,
                "duration": duration,
                "text": text,
                "status": "success",
                "engine": result.get("engine"),
                "model": result.get("model"),
                "attempts": result.get("attempts", []),
            })
            logger.info("    -> %.1fs  %s", duration, audio_path)
            video_diagnostics.record_tts_diagnostics(
                job_dir=job_dir,
                sequence=seq,
                text=text,
                attempts=result.get("attempts", []),
                final_result={
                    **result,
                    "audio_path": audio_path,
                },
            )
        else:
            results.append({
                "sequence": seq,
                "audio_path": None,
                "duration": 0,
                "text": text,
                "status": "error",
                "message": result.get("message", ""),
                "attempts": result.get("attempts", []),
            })
            logger.warning("    -> FAILED: %s", result.get("message", ""))
            video_diagnostics.record_tts_diagnostics(
                job_dir=job_dir,
                sequence=seq,
                text=text,
                attempts=result.get("attempts", []),
                final_result=result,
            )

    log_step_end("per_scene_tts", {
        "status": "success",
        "succeeded": sum(1 for r in results if r["status"] == "success"),
        "total_duration": sum(r["duration"] for r in results),
    })

    return results


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: generate_voice.py <script_text_or_file> <output_path> [voice_id]")
        sys.exit(1)

    text_input = sys.argv[1]
    text = Path(text_input).read_text() if os.path.isfile(text_input) else text_input

    result = generate_voiceover(
        text=text,
        output_path=sys.argv[2],
        voice_id=sys.argv[3] if len(sys.argv) > 3 else None,
    )
    print(json.dumps(result, indent=2))
