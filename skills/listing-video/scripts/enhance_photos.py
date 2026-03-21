#!/usr/bin/env python3
"""
Listing Video Agent — Photo Enhancement Pipeline
Upscale, HDR, color grading, and optional sky replacement.

Cost-conscious: ffmpeg for free ops, Stability AI only when needed.
"""

import os
import subprocess
from pathlib import Path

# ── Color grade profiles ────────────────────────────────────────────────
COLOR_PROFILES = {
    "warm_luxury": {
        "curves": "curves=m='0/0 0.25/0.30 0.5/0.55 0.75/0.82 1/1'",
        "colorbalance": "colorbalance=rs=0.05:gs=-0.02:bs=-0.08:rh=0.08:gh=0.02:bh=-0.05",
        "vignette": "vignette=PI/4",
    },
    "cool_modern": {
        "curves": "curves=m='0/0 0.25/0.20 0.5/0.50 0.75/0.80 1/1'",
        "colorbalance": "colorbalance=rs=-0.05:gs=-0.02:bs=0.06:rh=-0.03:gh=0.0:bh=0.08",
        "vignette": "",
    },
    "bright_family": {
        "curves": "curves=m='0/0.05 0.25/0.32 0.5/0.58 0.75/0.82 1/1'",
        "colorbalance": "colorbalance=rs=0.04:gs=0.02:bs=-0.02:rm=0.03:gm=0.02",
        "vignette": "",
    },
    "neutral": {
        "curves": "curves=m='0/0 0.25/0.27 0.5/0.52 0.75/0.78 1/1'",
        "colorbalance": "",
        "vignette": "",
    },
}

# Property style → color profile mapping
_STYLE_COLOR_MAP = {
    "Mediterranean": "warm_luxury",
    "traditional": "warm_luxury",
    "colonial": "warm_luxury",
    "farmhouse": "warm_luxury",
    "contemporary": "cool_modern",
    "modern": "cool_modern",
    "mid_century": "cool_modern",
    "craftsman": "neutral",
}


def analyze_enhancement_needs(
    photo_path: str,
    room_type: str,
    quality_score: int,
    quality_issues: list[str] = None,
) -> dict:
    """Decide which enhancements this photo needs."""
    needs = {
        "upscale": False,
        "hdr": False,
        "color_grade": True,  # always apply subtle grading
        "sky_replace": False,
    }

    # Check resolution — upscale if under 2160px wide
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "stream=width,height", "-of", "json", photo_path],
        capture_output=True, text=True,
    )
    if probe.returncode == 0:
        import json
        streams = json.loads(probe.stdout).get("streams", [{}])
        width = streams[0].get("width", 0) if streams else 0
        if width < 2160:
            needs["upscale"] = True

    issues = quality_issues or []

    # HDR for dark photos
    if quality_score < 7 or any("dark" in i.lower() for i in issues):
        needs["hdr"] = True

    # Sky replacement only for exterior with overcast
    if room_type in ("exterior", "aerial", "backyard"):
        if any("overcast" in i.lower() or "grey" in i.lower() or "gray" in i.lower() for i in issues):
            needs["sky_replace"] = True

    return needs


def upscale_photo(image_path: str, output_path: str, target_min_width: int = 2160) -> dict:
    """
    Upscale photo. Tries Stability AI ESRGAN, falls back to ffmpeg lanczos.
    """
    api_key = os.environ.get("STABILITY_API_KEY")

    if api_key:
        result = _upscale_stability(image_path, output_path, api_key)
        if result.get("status") == "success":
            return result

    # Fallback: ffmpeg lanczos upscale
    cmd = [
        "ffmpeg", "-y", "-i", image_path,
        "-vf", f"scale={target_min_width}:-1:flags=lanczos",
        "-q:v", "2", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {"status": "error", "message": result.stderr[-300:]}
    return {"status": "success", "image_path": output_path, "method": "ffmpeg_lanczos"}


def _upscale_stability(image_path: str, output_path: str, api_key: str) -> dict:
    """Upscale via Stability AI ESRGAN."""
    import requests

    with open(image_path, "rb") as f:
        resp = requests.post(
            "https://api.stability.ai/v1/generation/esrgan-v1-x2plus/image-to-image/upscale",
            headers={"Authorization": f"Bearer {api_key}", "Accept": "image/png"},
            files={"image": f},
            data={"width": 2160},
            timeout=60,
        )

    if resp.status_code == 200:
        Path(output_path).write_bytes(resp.content)
        return {"status": "success", "image_path": output_path, "method": "stability_esrgan"}

    return {"status": "error", "message": f"Stability API error {resp.status_code}"}


def enhance_hdr(image_path: str, output_path: str, strength: str = "medium") -> dict:
    """
    HDR-like enhancement via ffmpeg.
    Large-radius unsharp for local contrast + curves for shadow recovery.
    """
    strengths = {
        "light":  {"unsharp": "23:23:0.8:23:23:0.0", "curves": "m='0/0 0.15/0.20 0.5/0.52 1/1'"},
        "medium": {"unsharp": "23:23:1.2:23:23:0.0", "curves": "m='0/0 0.12/0.22 0.5/0.55 1/1'"},
        "strong": {"unsharp": "23:23:1.8:23:23:0.0", "curves": "m='0/0 0.10/0.25 0.5/0.58 1/1'"},
    }
    s = strengths.get(strength, strengths["medium"])

    vf = f"unsharp={s['unsharp']},curves={s['curves']}"
    cmd = ["ffmpeg", "-y", "-i", image_path, "-vf", vf, "-q:v", "2", output_path]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        return {"status": "error", "message": result.stderr[-300:]}
    return {"status": "success", "image_path": output_path}


def apply_color_grade(
    image_path: str,
    output_path: str,
    profile: str = "neutral",
    property_style: str = "",
) -> dict:
    """Apply a color grading profile."""
    # Auto-select profile from property style if not specified
    if profile == "neutral" and property_style:
        profile = _STYLE_COLOR_MAP.get(property_style, "neutral")

    grade = COLOR_PROFILES.get(profile, COLOR_PROFILES["neutral"])

    filters = []
    if grade["curves"]:
        filters.append(grade["curves"])
    if grade["colorbalance"]:
        filters.append(grade["colorbalance"])
    if grade["vignette"]:
        filters.append(grade["vignette"])

    if not filters:
        # No-op: just copy
        subprocess.run(["cp", image_path, output_path], check=True)
        return {"status": "success", "image_path": output_path}

    vf = ",".join(filters)
    cmd = ["ffmpeg", "-y", "-i", image_path, "-vf", vf, "-q:v", "2", output_path]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        return {"status": "error", "message": result.stderr[-300:]}
    return {"status": "success", "image_path": output_path, "profile": profile}


def replace_sky(image_path: str, output_path: str, target_sky: str = "golden_hour") -> dict:
    """
    Replace overcast sky using Stability AI inpainting.
    Only modifies the sky region, preserving architecture and foliage.
    Falls back to no-op if API unavailable.
    """
    import requests

    api_key = os.environ.get("STABILITY_API_KEY")
    if not api_key:
        subprocess.run(["cp", image_path, output_path], check=True)
        return {"status": "skipped", "message": "STABILITY_API_KEY not set", "image_path": output_path}

    sky_prompts = {
        "golden_hour": "Beautiful golden hour sky with warm orange and pink clouds, dramatic sunset lighting",
        "clear_blue": "Crystal clear blue sky with a few wispy white clouds, bright daylight",
        "dramatic": "Dramatic sky with volumetric clouds and sun rays breaking through",
    }
    prompt = sky_prompts.get(target_sky, sky_prompts["golden_hour"])

    try:
        with open(image_path, "rb") as f:
            resp = requests.post(
                "https://api.stability.ai/v2beta/stable-image/edit/search-and-replace",
                headers={"Authorization": f"Bearer {api_key}", "Accept": "image/png"},
                files={"image": f},
                data={
                    "prompt": prompt,
                    "search_prompt": "overcast gray sky, cloudy sky, white sky",
                },
                timeout=60,
            )

        if resp.status_code == 200:
            Path(output_path).write_bytes(resp.content)
            return {"status": "success", "image_path": output_path, "sky": target_sky}
    except Exception:
        pass

    # Fallback: no change
    subprocess.run(["cp", image_path, output_path], check=True)
    return {"status": "skipped", "image_path": output_path}


def enhance_photo_pipeline(
    image_path: str,
    output_path: str,
    room_type: str = "other",
    quality_score: int = 7,
    quality_issues: list[str] = None,
    property_style: str = "",
    sky_condition: str = "",
) -> dict:
    """
    Main entry: run the full enhancement pipeline on one photo.

    Order: upscale → sky_replace → HDR → color_grade → crop
    Each step writes to a temp file; only the final result is kept.
    """
    import tempfile

    needs = analyze_enhancement_needs(image_path, room_type, quality_score, quality_issues)
    current = image_path
    steps = []
    tmpdir = tempfile.mkdtemp(prefix="enhance_")

    try:
        # 1. Upscale
        if needs["upscale"]:
            tmp = os.path.join(tmpdir, "upscaled.jpg")
            result = upscale_photo(current, tmp)
            if result.get("status") == "success":
                current = tmp
                steps.append("upscale")

        # 2. Sky replacement (exterior + overcast only)
        if needs["sky_replace"] or sky_condition == "overcast":
            tmp = os.path.join(tmpdir, "sky.jpg")
            result = replace_sky(current, tmp)
            if result.get("status") == "success":
                current = tmp
                steps.append("sky_replace")

        # 3. HDR
        if needs["hdr"]:
            tmp = os.path.join(tmpdir, "hdr.jpg")
            result = enhance_hdr(current, tmp, strength="medium")
            if result.get("status") == "success":
                current = tmp
                steps.append("hdr")

        # 4. Color grade (always)
        if needs["color_grade"]:
            tmp = os.path.join(tmpdir, "graded.jpg")
            result = apply_color_grade(current, tmp, property_style=property_style)
            if result.get("status") == "success":
                current = tmp
                steps.append("color_grade")

        # Copy final result to output
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["cp", current, output_path], check=True)

    finally:
        # Cleanup temp files
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    return {
        "status": "success",
        "image_path": output_path,
        "enhancements": steps,
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Enhance a listing photo")
    parser.add_argument("--input", required=True, dest="input_path", help="Input photo path")
    parser.add_argument("--output", required=True, dest="output_path", help="Output photo path")
    parser.add_argument("--room-type", default="other", help="Room type")
    parser.add_argument("--quality-score", type=int, default=7, help="Quality score 1-10")
    parser.add_argument("--quality-issues", nargs="*", default=[], help="Quality issues")
    parser.add_argument("--property-style", default="", help="Property architectural style")
    parser.add_argument("--sky-condition", default="", help="Sky condition (clear/overcast/sunset)")
    args = parser.parse_args()

    result = enhance_photo_pipeline(
        image_path=args.input_path,
        output_path=args.output_path,
        room_type=args.room_type,
        quality_score=args.quality_score,
        quality_issues=args.quality_issues,
        property_style=args.property_style,
        sky_condition=args.sky_condition,
    )
    print(json.dumps(result, indent=2))
