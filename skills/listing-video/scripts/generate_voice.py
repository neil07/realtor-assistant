#!/usr/bin/env python3
"""
Listing Video Agent — TTS Voice Generation
Primary: ElevenLabs (stateless, instant).
Fallback: OpenAI TTS → IMA Studio TTS.
"""

import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

ELEVENLABS_API = "https://api.elevenlabs.io/v1"

# Default voices for different styles (ElevenLabs)
# Override via env: ELEVENLABS_VOICE_ID (applies to all styles)
DEFAULT_VOICES = {
    "male_energetic": os.environ.get("ELEVENLABS_VOICE_ENERGETIC", "pNInz6obpgDQGcFmaJgB"),
    "male_professional": os.environ.get("ELEVENLABS_VOICE_PROFESSIONAL", "ErXwobaYiN019PkySvjV"),
    "female_energetic": os.environ.get("ELEVENLABS_VOICE_F_ENERGETIC", "EXAVITQu4vr4xnSDxMaL"),
    "female_professional": os.environ.get("ELEVENLABS_VOICE_F_PROFESSIONAL", "21m00Tcm4TlvDq8ikWAM"),
}
# Single override: if set, always use this voice regardless of style
_VOICE_OVERRIDE = os.environ.get("ELEVENLABS_VOICE_ID", "")

# Max parallel TTS calls
TTS_MAX_WORKERS = int(os.environ.get("TTS_MAX_WORKERS", "4"))

# Circuit breaker: skip an engine after this many consecutive failures
_CB_THRESHOLD = 2


class _EngineCircuitBreaker:
    """Thread-safe circuit breaker for TTS engine fallback chain."""

    def __init__(self, threshold: int = _CB_THRESHOLD):
        self._threshold = threshold
        self._failures: dict[str, int] = {}
        self._lock = threading.Lock()

    def is_open(self, engine: str) -> bool:
        with self._lock:
            return self._failures.get(engine, 0) >= self._threshold

    def record_success(self, engine: str) -> None:
        with self._lock:
            self._failures[engine] = 0

    def record_failure(self, engine: str) -> None:
        with self._lock:
            self._failures[engine] = self._failures.get(engine, 0) + 1


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
        voice_id = _VOICE_OVERRIDE or DEFAULT_VOICES.get(f"male_{style}", DEFAULT_VOICES["male_professional"])

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
        "credit": 0,
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
        "credit": 0,
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
    circuit_breaker: _EngineCircuitBreaker | None = None,
) -> dict:
    """
    Main entry point: generate voiceover with fallback chain.

    ElevenLabs (primary) → OpenAI TTS → IMA Studio.
    If a circuit_breaker is provided, engines with repeated failures are skipped.
    """
    import video_diagnostics
    from job_logger import get_logger, log_step_end, log_step_start

    cb = circuit_breaker
    logger = get_logger()
    attempts = []
    log_step_start("tts_voiceover", {
        "text_length": len(text),
        "voice_id": voice_id or "default",
        "style": style,
        "engine": "elevenlabs",
    })

    # Primary: ElevenLabs �� stateless single HTTP call, fastest and most reliable
    if not (cb and cb.is_open("elevenlabs")):
        result = generate_elevenlabs(text, output_path, voice_id=voice_id, style=style)
        attempts.append(video_diagnostics.build_attempt_record(
            engine="elevenlabs",
            status=result.get("status", "error"),
            result=result,
            characters=len(text),
        ))
        if result["status"] == "success":
            if cb:
                cb.record_success("elevenlabs")
            result["engine"] = "elevenlabs"
            result["attempts"] = attempts
            log_step_end("tts_voiceover", result)
            return result
        if cb:
            cb.record_failure("elevenlabs")
        logger.warning("ElevenLabs failed: %s, trying OpenAI TTS...", result["message"])

    # Fallback 1: OpenAI TTS — stateless single HTTP call
    if not (cb and cb.is_open("openai_tts")):
        result = generate_openai_tts(text, output_path)
        attempts.append(video_diagnostics.build_attempt_record(
            engine="openai_tts",
            status=result.get("status", "error"),
            result=result,
            characters=len(text),
        ))
        if result["status"] == "success":
            if cb:
                cb.record_success("openai_tts")
            result["engine"] = "openai_tts"
            result["attempts"] = attempts
            log_step_end("tts_voiceover", result)
            return result
        if cb:
            cb.record_failure("openai_tts")
        logger.warning("OpenAI TTS failed: %s, trying IMA TTS...", result["message"])

    # Fallback 2: IMA TTS — task queue, slower, but covers the case where
    # both ElevenLabs and OpenAI keys are absent
    result = generate_ima_tts(text, output_path)
    attempts.append(video_diagnostics.build_attempt_record(
        engine="ima",
        status=result.get("status", "error"),
        result=result,
        characters=len(text),
    ))
    if cb:
        if result["status"] == "success":
            cb.record_success("ima")
        else:
            cb.record_failure("ima")
    result["engine"] = "ima" if result["status"] == "success" else None
    result["attempts"] = attempts
    log_step_end("tts_voiceover", result)
    return result


# ---------------------------------------------------------------------------
# Per-scene voiceover generation
# ---------------------------------------------------------------------------

def _get_audio_duration(audio_path: str) -> float:
    """Get audio duration via mutagen (fast) or ffprobe (fallback)."""
    try:
        from mutagen.mp3 import MP3

        return float(getattr(MP3(audio_path).info, "length", 0.0) or 0.0)
    except Exception:
        pass
    import subprocess

    try:
        dur_result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "json", audio_path],
            capture_output=True, text=True, timeout=10,
        )
        if dur_result.returncode == 0:
            dur_data = json.loads(dur_result.stdout)
            return float(dur_data.get("format", {}).get("duration", 0))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return 0.0


def _tts_one_scene(
    scene: dict,
    output_dir: str,
    voice_id: str | None,
    style: str,
    circuit_breaker: _EngineCircuitBreaker,
) -> dict:
    """Generate TTS for a single scene. Called inside ThreadPoolExecutor."""
    seq = scene["sequence"]
    text = scene["text_narration"].strip()
    audio_path = os.path.join(output_dir, f"narration_{seq:02d}.mp3")

    result = generate_voiceover(
        text=text,
        output_path=audio_path,
        voice_id=voice_id,
        style=style,
        circuit_breaker=circuit_breaker,
    )

    if result["status"] == "success":
        duration = _get_audio_duration(audio_path)
        return {
            "sequence": seq,
            "audio_path": audio_path,
            "duration": duration,
            "text": text,
            "status": "success",
            "engine": result.get("engine"),
            "model": result.get("model"),
            "credit": result.get("credit", 0),
            "attempts": result.get("attempts", []),
        }
    else:
        return {
            "sequence": seq,
            "audio_path": None,
            "duration": 0,
            "text": text,
            "status": "error",
            "message": result.get("message", ""),
            "attempts": result.get("attempts", []),
        }


def generate_scene_voiceovers(
    scenes: list[dict],
    output_dir: str,
    voice_id: str = None,
    style: str = "professional",
) -> list[dict]:
    """
    Generate individual TTS audio for each scene's narration.

    Runs up to TTS_MAX_WORKERS scenes in parallel with a shared circuit breaker
    that skips engines after consecutive failures.
    """
    import video_diagnostics
    from job_logger import get_logger, log_step_end, log_step_start

    logger = get_logger()
    os.makedirs(output_dir, exist_ok=True)
    job_dir = str(Path(output_dir).parent)
    video_diagnostics.record_scene_plan(job_dir, scenes)

    narrated = [s for s in scenes if s.get("text_narration", "").strip()]

    log_step_start("per_scene_tts", {
        "total_scenes": len(narrated),
        "voice_id": voice_id or "default",
        "style": style,
        "max_workers": TTS_MAX_WORKERS,
    })

    cb = _EngineCircuitBreaker()
    results: list[dict] = []
    workers = min(len(narrated), TTS_MAX_WORKERS)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _tts_one_scene, scene, output_dir, voice_id, style, cb,
            ): scene["sequence"]
            for scene in narrated
        }
        for future in as_completed(futures):
            seq = futures[future]
            try:
                r = future.result()
            except Exception as exc:
                logger.warning("TTS scene %02d exception: %s", seq, exc)
                r = {
                    "sequence": seq, "audio_path": None, "duration": 0,
                    "text": "", "status": "error", "message": str(exc),
                    "attempts": [],
                }
            results.append(r)

            if r["status"] == "success":
                logger.info("  TTS scene %02d: %.1fs  %s", seq, r["duration"], r.get("engine"))
                video_diagnostics.record_tts_diagnostics(
                    job_dir=job_dir, sequence=seq, text=r["text"],
                    attempts=r.get("attempts", []),
                    final_result={**r, "audio_path": r["audio_path"]},
                )
            else:
                logger.warning("  TTS scene %02d FAILED: %s", seq, r.get("message", ""))
                video_diagnostics.record_tts_diagnostics(
                    job_dir=job_dir, sequence=seq, text=r.get("text", ""),
                    attempts=r.get("attempts", []),
                    final_result=r,
                )

    # Sort by sequence for deterministic output
    results.sort(key=lambda x: x["sequence"])

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
