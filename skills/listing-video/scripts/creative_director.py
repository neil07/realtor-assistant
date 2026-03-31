#!/usr/bin/env python3
"""
Reel Agent — Creative Director

Replaces the 4-step Sonnet chain (analyze → script → plan → prompts) with a single
Opus call that sees all photos at once and produces the complete creative package:
photo analysis + voiceover script + scene sequence + motion prompts.

Advantages over the old chain:
  - Hook references what Claude actually sees (not a text summary)
  - Narrative arc is coherent because it's planned holistically
  - Camera prompts are written with full awareness of scene context
  - One API call instead of 4+ sequential calls

Dual-mode (matches pipeline script conventions):
  build_creative_request() → returns API request dict for orchestrator scheduling
  run()                    → standalone execution, writes 4 JSON artifacts
"""

import json
import os
import sys
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, field_validator

load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

MODEL = "claude-opus-4-6"
FALLBACK_MODEL = "claude-sonnet-4-6"  # Used when Opus is overloaded
MAX_TOKENS = 4096
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "creative_director.md"

# ─── Pydantic Schema ──────────────────────────────────────────────────────────


class PhotoRating(BaseModel):
    """Analysis of a single listing photo."""

    index: int
    filename: str
    room_type: str  # exterior|living|kitchen|dining|bedroom|bathroom|pool|...
    quality_score: int  # 1-10
    ai_video_worthy: bool
    suggested_motion: str  # slow_push|pull_back|crane_down|tilt_up|low_skim|static


class PropertySummary(BaseModel):
    """High-level property intelligence."""

    estimated_tier: str  # luxury|mid_range|starter|investment
    key_selling_points: list[str]
    recommended_style: str  # elegant|energetic|professional


class SceneWithPrompt(BaseModel):
    """A single video scene with narration and camera instruction."""

    sequence: int
    first_frame: str  # exact filename from photo list
    last_frame: str  # exact filename from photo list
    scene_desc: str  # visual description for IMA video model
    text_narration: str  # spoken audio, ≤15 words
    motion_prompt: str  # 50-80 words, ends with quality suffix

    @field_validator("text_narration")
    @classmethod
    def cap_narration(cls, v: str) -> str:
        words = v.split()
        if len(words) <= 15:
            return v
        trimmed = " ".join(words[:15])
        return trimmed if trimmed.endswith(".") else trimmed + "."


class CreativeOutput(BaseModel):
    """
    Complete creative package for one listing video.

    Produced by a single Opus call after seeing all photos.
    """

    # Photo intelligence
    photo_ratings: list[PhotoRating]
    property_summary: PropertySummary

    # Voiceover script
    hook: str  # ≤10 words, first 3 seconds
    walkthrough: str  # ~20 seconds
    closer: str  # ≤8 words + CTA
    caption: str  # Instagram caption + hashtags

    # Scene plan with embedded motion prompts
    scenes: list[SceneWithPrompt]


# ─── Request builder ──────────────────────────────────────────────────────────


def _encode_image(path: str) -> dict:
    """Encode an image file as a base64 Anthropic content block."""
    import base64

    suffix = Path(path).suffix.lower()
    media_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    media_type = media_map.get(suffix, "image/jpeg")
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def build_creative_request(
    photo_paths: list[str],
    address: str,
    price: str,
    agent_name: str = "",
    agent_phone: str = "",
    style: str = "elegant",
    language: str = "en",
    custom_brief: str | None = None,
) -> dict:
    """
    Build the Anthropic API request for creative direction.

    Args:
        photo_paths: Absolute paths to listing photos (order preserved).
        address:     Property address.
        price:       Asking price (e.g. "RM 1,200,000" or "$650,000").
        agent_name:  Agent name for CTA.
        agent_phone: Agent phone for CTA.
        style:       Video style hint (elegant|energetic|professional).
        language:    Narration language (en, zh, ms, ...).

    Returns:
        Dict suitable for client.messages.parse(**request, output_format=CreativeOutput).
    """
    system_prompt = custom_brief if custom_brief else PROMPT_PATH.read_text()

    # List filenames so Claude can reference them by name in scenes
    filenames = [os.path.basename(p) for p in photo_paths]
    filename_list = "\n".join(f"  {i + 1}. {fn}" for i, fn in enumerate(filenames))

    context = (
        f"Address: {address}\n"
        f"Price: {price}\n"
        f"Agent: {agent_name or 'not provided'}\n"
        f"Phone: {agent_phone or 'not provided'}\n"
        f"Style: {style}\n"
        f"Language: {language}\n"
        f"\nAvailable photos (use exact filenames):\n{filename_list}"
    )

    # Build interleaved content: label + image for each photo, then context
    content: list[dict] = []
    for i, path in enumerate(photo_paths):
        content.append({"type": "text", "text": f"Photo {i + 1} — {filenames[i]}:"})
        content.append(_encode_image(path))
    content.append({"type": "text", "text": context})

    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": content}],
    }


# ─── Artifact writers ─────────────────────────────────────────────────────────


def _to_analysis_json(creative: CreativeOutput) -> dict:
    """
    Convert CreativeOutput to the legacy analyze_photos output format.
    Preserves downstream compatibility with diagnostics and pipeline.
    """
    photos = []
    for pr in creative.photo_ratings:
        # Try to match filename to index; fall back to order
        idx = pr.index
        fn = pr.filename
        photos.append(
            {
                "index": idx,
                "filename": fn,
                "room_type": pr.room_type,
                "description": "",
                "highlights": [],
                "style": creative.property_summary.recommended_style,
                "quality_score": pr.quality_score,
                "quality_issues": [],
                "ai_video_worthy": pr.ai_video_worthy,
                "ai_video_reason": "",
                "suggested_motion": pr.suggested_motion,
                "video_order": idx,
                "duration_suggestion": 4,
            }
        )

    ps = creative.property_summary
    return {
        "photos": photos,
        "property_summary": {
            "estimated_style": ps.recommended_style,
            "estimated_tier": ps.estimated_tier,
            "bedrooms_detected": 0,
            "bathrooms_detected": 0,
            "key_selling_points": ps.key_selling_points,
            "missing_shots": [],
            "overall_quality": "good",
            "recommended_style": ps.recommended_style,
        },
        "video_plan": {
            "recommended_duration": 30,
            "ai_clips_count": sum(1 for pr in creative.photo_ratings if pr.ai_video_worthy),
            "slideshow_clips_count": sum(1 for pr in creative.photo_ratings if not pr.ai_video_worthy),
            "recommended_style": ps.recommended_style,
            "narrative_arc": " → ".join(s.scene_desc[:30] + "..." for s in creative.scenes[:3]),
        },
    }


def _to_script_dict(creative: CreativeOutput) -> dict:
    """Convert CreativeOutput script fields to the legacy generate_script format."""
    full = f"{creative.hook} {creative.walkthrough} {creative.closer}".strip()
    word_count = len(full.split())
    return {
        "hook": creative.hook,
        "walkthrough": creative.walkthrough,
        "closer": creative.closer,
        "full_script": full,
        "caption": creative.caption,
        "word_count": word_count,
        "estimated_duration": word_count / 3.5,
        "photo_sequence": list(range(1, len(creative.photo_ratings) + 1)),
    }


def _to_scenes_list(creative: CreativeOutput) -> list[dict]:
    """Convert CreativeOutput scenes to the legacy plan_scenes format."""
    return [
        {
            "sequence": s.sequence,
            "first_frame": s.first_frame,
            "last_frame": s.last_frame,
            "scene_desc": s.scene_desc,
            "text_narration": s.text_narration,
            "motion_prompt": s.motion_prompt,
        }
        for s in creative.scenes
    ]


def _to_prompts_list(creative: CreativeOutput) -> list[dict]:
    """Convert CreativeOutput scenes to the legacy write_video_prompts format."""
    return [{"sequence": s.sequence, "motion_prompt": s.motion_prompt} for s in creative.scenes]


# ─── Main run function ────────────────────────────────────────────────────────


def run(
    photo_paths: list[str],
    address: str,
    price: str,
    output_dir: str = "output",
    agent_name: str = "",
    agent_phone: str = "",
    style: str = "elegant",
    language: str = "en",
    custom_brief: str | None = None,
) -> dict:
    """
    Run creative direction end-to-end.

    Calls Opus with all photos, returns the complete creative package and
    writes 4 JSON artifacts (analysis.json, script.json, scenes.json, prompts.json)
    to output_dir for diagnostics compatibility.

    Returns:
        Dict with keys: analysis, script, scenes, prompts, model,
        input_tokens, output_tokens, elapsed_seconds.
    """
    os.makedirs(output_dir, exist_ok=True)
    t0 = time.time()

    request = build_creative_request(
        photo_paths=photo_paths,
        address=address,
        price=price,
        agent_name=agent_name,
        agent_phone=agent_phone,
        custom_brief=custom_brief,
        style=style,
        language=language,
    )

    client = anthropic.Anthropic()

    # Retry up to 4 times on transient errors (529 overload, 500).
    # Attempt 4 falls back to Sonnet so we always produce output even during
    # Opus high-traffic periods (quality slightly lower, but pipeline completes).
    last_err = None
    _wait_schedule = [30, 60, 120]  # seconds between retries
    for attempt in range(4):
        current_model = MODEL if attempt < 3 else FALLBACK_MODEL
        if attempt == 3:
            print(f"  [creative] Opus still overloaded — falling back to {FALLBACK_MODEL}...")
            request = {**request, "model": FALLBACK_MODEL}
        try:
            response = client.messages.parse(**request, output_format=CreativeOutput)
            if current_model != MODEL:
                print(f"  [creative] Used fallback model: {current_model}")
            break
        except anthropic.APIStatusError as e:
            last_err = e
            if attempt < 3 and e.status_code in (429, 529):
                wait = _wait_schedule[attempt]
                print(f"  [creative] API overload, retry {attempt + 1}/3 in {wait}s...")
                time.sleep(wait)
            elif attempt < 3 and e.status_code >= 500:
                wait = _wait_schedule[attempt] // 2
                print(f"  [creative] Server error {e.status_code}, retry {attempt + 1}/3 in {wait}s...")
                time.sleep(wait)
            else:
                raise
    else:
        raise RuntimeError(f"Creative director failed after 4 attempts: {last_err}") from last_err

    creative: CreativeOutput = response.parsed_output

    # Build legacy-compatible dicts
    analysis = _to_analysis_json(creative)
    script = _to_script_dict(creative)
    scenes = _to_scenes_list(creative)
    prompts = _to_prompts_list(creative)

    # Write artifacts
    with open(os.path.join(output_dir, "analysis.json"), "w") as f:
        json.dump(analysis, f, indent=2)
    with open(os.path.join(output_dir, "script.json"), "w") as f:
        json.dump(script, f, indent=2)
    with open(os.path.join(output_dir, "scenes.json"), "w") as f:
        json.dump(scenes, f, indent=2)
    with open(os.path.join(output_dir, "prompts.json"), "w") as f:
        json.dump(prompts, f, indent=2)

    elapsed = time.time() - t0
    usage = response.usage

    return {
        "analysis": analysis,
        "script": script,
        "scenes": scenes,
        "prompts": prompts,
        "model": MODEL,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "elapsed_seconds": elapsed,
    }


# ─── Standalone test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Creative Director — standalone test")
    parser.add_argument("photo_dir", nargs="?", help="Directory with listing photos")
    parser.add_argument("--address", default="123 Test St, Kuala Lumpur, MY")
    parser.add_argument("--price", default="RM 1,200,000")
    parser.add_argument("--agent", default="Neo")
    parser.add_argument("--phone", default="+60175029017")
    parser.add_argument("--style", default="elegant", choices=["elegant", "energetic", "professional"])
    parser.add_argument("--language", default="en")
    parser.add_argument("--output", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Print request without calling API")
    args = parser.parse_args()

    # Default to sample photos dir
    if not args.photo_dir:
        default = Path(__file__).parent.parent.parent.parent / "sample_photos"
        if not default.exists():
            print("❌ No photo_dir provided and no sample_photos/ directory found.")
            sys.exit(1)
        args.photo_dir = str(default)

    photo_paths = sorted(
        str(p)
        for p in Path(args.photo_dir).iterdir()
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
    )

    if not photo_paths:
        print(f"❌ No photos found in {args.photo_dir}")
        sys.exit(1)

    print(f"🎬 Creative Director — {len(photo_paths)} photos")

    if args.dry_run:
        req = build_creative_request(
            photo_paths=photo_paths,
            address=args.address,
            price=args.price,
            agent_name=args.agent,
            agent_phone=args.phone,
            style=args.style,
            language=args.language,
        )
        # Strip base64 data for readability
        for msg in req["messages"]:
            for block in msg.get("content", []):
                if block.get("type") == "image":
                    block["source"]["data"] = "<base64_truncated>"
        print(json.dumps(req, indent=2))
        sys.exit(0)

    output_dir = args.output or str(Path(args.photo_dir).parent / "output" / "creative_test")

    result = run(
        photo_paths=photo_paths,
        address=args.address,
        price=args.price,
        output_dir=output_dir,
        agent_name=args.agent,
        agent_phone=args.phone,
        style=args.style,
        language=args.language,
    )

    script = result["script"]
    scenes = result["scenes"]

    print(f"\n✅ Creative package ready ({result['elapsed_seconds']:.1f}s)")
    print(f"   Model: {result['model']} | tokens: {result['input_tokens']} in / {result['output_tokens']} out")
    print(f"\n[HOOK]  {script['hook']}")
    print(f"[WALK]  {script['walkthrough'][:80]}...")
    print(f"[CLOSE] {script['closer']}")
    print(f"\n{len(scenes)} scenes:")
    for s in scenes:
        print(f"  {s['sequence']}. {s['first_frame']} → {s['last_frame']} | \"{s['text_narration']}\"")
    print(f"\n📁 Artifacts: {output_dir}/{{analysis,script,scenes,prompts}}.json")
