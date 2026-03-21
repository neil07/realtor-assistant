#!/usr/bin/env python3
"""
Listing Video Agent — AI Background Music Generation
Primary: Suno API. Fallback: Replicate MusicGen. Final fallback: stock library.

Includes beat detection via librosa for downstream beat-sync assembly.
"""

import json
import os
import time
import requests
from pathlib import Path

ASSETS_DIR = Path(__file__).parent.parent / "assets"
STOCK_MUSIC_DIR = ASSETS_DIR / "music"

# Stock music: pre-categorized royalty-free tracks
_STOCK_MAP = {
    "piano_ambient": "piano_ambient",
    "modern_upbeat": "modern_upbeat",
    "modern_chill": "modern_chill",
    "acoustic_warm": "acoustic_warm",
    "chill_ambient": "piano_ambient",
    "orchestral": "piano_ambient",
    "electronic": "modern_upbeat",
}


def generate_music_suno(
    style_description: str,
    duration: float = 30,
    instrumental: bool = True,
    bpm_target: int = None,
) -> dict:
    """Generate music via Suno API (~$0.08/track)."""
    api_key = os.environ.get("SUNO_API_KEY")
    if not api_key:
        return {"status": "error", "message": "SUNO_API_KEY not set"}

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    prompt = style_description
    if instrumental:
        prompt += " [instrumental]"
    if bpm_target:
        prompt += f" {bpm_target} BPM"

    payload = {
        "prompt": prompt,
        "duration": min(int(duration) + 5, 120),  # pad slightly, max 2min
        "make_instrumental": instrumental,
    }

    try:
        resp = requests.post(
            "https://api.suno.ai/v1/generations",
            headers=headers,
            json=payload,
            timeout=30,
        )
        if resp.status_code not in (200, 201):
            return {"status": "error", "message": f"Suno API error {resp.status_code}: {resp.text[:200]}"}

        task = resp.json()
        task_id = task.get("id") or task.get("task_id")
        if not task_id:
            return {"status": "error", "message": "No task ID returned from Suno"}

        # Poll for completion (max ~3 min)
        for _ in range(36):
            time.sleep(5)
            poll = requests.get(
                f"https://api.suno.ai/v1/generations/{task_id}",
                headers=headers,
                timeout=15,
            )
            if poll.status_code != 200:
                continue

            data = poll.json()
            status = data.get("status", "")

            if status in ("complete", "succeeded"):
                audio_url = data.get("audio_url") or data.get("output", {}).get("audio_url")
                if audio_url:
                    return {"status": "success", "audio_url": audio_url, "engine": "suno"}
            elif status in ("failed", "error"):
                return {"status": "error", "message": f"Suno generation failed: {data}"}

        return {"status": "error", "message": "Timeout waiting for Suno generation"}

    except Exception as e:
        return {"status": "error", "message": str(e)}


def generate_music_musicgen(style_description: str, duration: float = 30) -> dict:
    """Fallback: Generate music via Replicate MusicGen (~$0.02/track)."""
    api_token = os.environ.get("REPLICATE_API_TOKEN")
    if not api_token:
        return {"status": "error", "message": "REPLICATE_API_TOKEN not set"}

    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}

    payload = {
        "version": "b05b1dff1d8c386b65aecda3c1be7f98f8e4c1dae8ef7944b75e4d5e12e26a5e",
        "input": {
            "prompt": style_description,
            "duration": min(int(duration) + 5, 60),
            "model_version": "stereo-melody-large",
        },
    }

    try:
        resp = requests.post(
            "https://api.replicate.com/v1/predictions",
            headers=headers,
            json=payload,
            timeout=30,
        )
        if resp.status_code != 201:
            return {"status": "error", "message": f"Replicate API error {resp.status_code}: {resp.text[:200]}"}

        prediction = resp.json()
        poll_url = prediction.get("urls", {}).get("get")
        if not poll_url:
            return {"status": "error", "message": "No poll URL from Replicate"}

        for _ in range(60):
            time.sleep(3)
            poll = requests.get(poll_url, headers=headers, timeout=15)
            if poll.status_code != 200:
                continue

            data = poll.json()
            status = data.get("status")

            if status == "succeeded":
                output = data.get("output")
                if output:
                    audio_url = output if isinstance(output, str) else output[0]
                    return {"status": "success", "audio_url": audio_url, "engine": "musicgen"}
            elif status == "failed":
                return {"status": "error", "message": f"MusicGen failed: {data.get('error', '')}"}

        return {"status": "error", "message": "Timeout waiting for MusicGen"}

    except Exception as e:
        return {"status": "error", "message": str(e)}


def select_stock_music(style: str, duration: float = 30) -> dict:
    """
    Select from pre-bundled royalty-free music library.
    Zero cost, zero latency.
    """
    category = _STOCK_MAP.get(style, "modern_chill")
    category_dir = STOCK_MUSIC_DIR / category

    if not category_dir.exists():
        # Try any available category
        if STOCK_MUSIC_DIR.exists():
            for d in STOCK_MUSIC_DIR.iterdir():
                if d.is_dir():
                    category_dir = d
                    break

    if not category_dir.exists():
        return {"status": "error", "message": "No stock music available"}

    # Pick first available track
    tracks = list(category_dir.glob("*.mp3")) + list(category_dir.glob("*.wav"))
    if not tracks:
        return {"status": "error", "message": f"No tracks in {category_dir}"}

    return {
        "status": "success",
        "music_path": str(tracks[0]),
        "engine": "stock",
        "category": category,
    }


def detect_beats(audio_path: str) -> dict:
    """
    Detect BPM and beat timestamps using librosa.

    Returns:
        {
            "bpm": float,
            "beat_timestamps": [float],     # all beat positions in seconds
            "downbeat_timestamps": [float],  # strong beats (every 4th)
        }
    """
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(audio_path, sr=22050, mono=True)
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()

        # Downbeats: every 4th beat (approximate)
        downbeats = beat_times[::4]

        bpm = float(tempo) if not hasattr(tempo, '__len__') else float(tempo[0])

        return {
            "bpm": round(bpm, 1),
            "beat_timestamps": [round(t, 3) for t in beat_times],
            "downbeat_timestamps": [round(t, 3) for t in downbeats],
        }
    except ImportError:
        return {"bpm": 0, "beat_timestamps": [], "downbeat_timestamps": []}
    except Exception:
        return {"bpm": 0, "beat_timestamps": [], "downbeat_timestamps": []}


def build_music_prompt(
    property_style: str,
    property_tier: str,
    template_style: str = "professional",
    bpm_range: tuple = None,
) -> str:
    """Map property personality → music description."""
    style_prompts = {
        ("elegant", "luxury"): "Sophisticated solo piano with subtle strings, warm and spacious, 70-80 BPM",
        ("elegant", "mid_range"): "Gentle piano with soft ambient pads, refined and calming, 75-85 BPM",
        ("energetic", "luxury"): "Modern upbeat electronic with clean synths, confident energy, 110-120 BPM",
        ("energetic", "mid_range"): "Upbeat indie pop feel, acoustic guitar and light drums, 105-115 BPM",
        ("professional", "luxury"): "Modern cinematic ambient, piano and atmospheric textures, 85-95 BPM",
        ("professional", "mid_range"): "Clean modern chill, subtle beats and warm pads, 90-100 BPM",
    }

    key = (template_style, property_tier)
    prompt = style_prompts.get(key, "Modern cinematic background music, instrumental, smooth and professional, 90 BPM")

    if bpm_range:
        prompt += f", {bpm_range[0]}-{bpm_range[1]} BPM"

    return prompt + ", high quality production, suitable for real estate video"


def generate_background_music(
    property_style: str,
    property_tier: str,
    template: dict,
    duration: float,
    output_path: str,
) -> dict:
    """
    Main entry: generate (or select) background music.
    Cascade: Suno → MusicGen → stock. Always includes beat detection.
    """
    template_style = template.get("name", "professional")
    bpm_range = template.get("music", {}).get("bpm_range", [85, 110])
    music_mood = template.get("music", {}).get("style", "modern_chill")

    prompt = build_music_prompt(property_style, property_tier, template_style, tuple(bpm_range))

    # Try Suno first
    result = generate_music_suno(prompt, duration, bpm_target=sum(bpm_range) // 2)
    if result.get("status") == "success" and result.get("audio_url"):
        audio_resp = requests.get(result["audio_url"], timeout=60)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(audio_resp.content)
        beats = detect_beats(output_path)
        return {"status": "success", "music_path": output_path, "engine": "suno", "beats": beats}

    # Try MusicGen
    result = generate_music_musicgen(prompt, duration)
    if result.get("status") == "success" and result.get("audio_url"):
        audio_resp = requests.get(result["audio_url"], timeout=60)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(audio_resp.content)
        beats = detect_beats(output_path)
        return {"status": "success", "music_path": output_path, "engine": "musicgen", "beats": beats}

    # Fallback: stock library
    stock = select_stock_music(music_mood, duration)
    if stock.get("status") == "success":
        beats = detect_beats(stock["music_path"])
        return {
            "status": "success",
            "music_path": stock["music_path"],
            "engine": "stock",
            "beats": beats,
        }

    return {"status": "error", "message": "No music source available"}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate background music")
    parser.add_argument("--property-style", default="modern", help="Property style")
    parser.add_argument("--property-tier", default="mid_range", help="Property tier")
    parser.add_argument("--template-file", required=True, help="Template JSON file")
    parser.add_argument("--duration", type=float, default=30, help="Duration in seconds")
    parser.add_argument("--output", required=True, help="Output music file path")
    args = parser.parse_args()

    template = json.loads(Path(args.template_file).read_text())
    result = generate_background_music(
        property_style=args.property_style,
        property_tier=args.property_tier,
        template=template,
        duration=args.duration,
        output_path=args.output,
    )
    print(json.dumps(result, indent=2, default=str))
