#!/usr/bin/env python3
"""
Listing Video Agent — Final Assembly
Combines AI video clips + slideshow clips + voiceover + music + text overlays
into the final deliverable video using ffmpeg.
"""

import json
import os
import subprocess


def concat_clips(
    clip_paths: list[str],
    output_path: str,
    transitions: list[dict] = None,
) -> dict:
    """
    Concatenate video clips with optional crossfade transitions.

    Args:
        clip_paths: Ordered list of clip file paths
        output_path: Output video path
        transitions: List of {"type": "crossfade"|"cut", "duration": 0.5}
    """
    if not clip_paths:
        return {"status": "error", "message": "No clips provided"}

    # Create concat file
    concat_file = output_path + ".concat.txt"
    with open(concat_file, "w") as f:
        for path in clip_paths:
            f.write(f"file '{os.path.abspath(path)}'\n")

    if transitions and any(t.get("type") == "crossfade" for t in transitions):
        # Use xfade filter for crossfade transitions
        result = _concat_with_crossfade(clip_paths, output_path, transitions)
    else:
        # Simple concat
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_file,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            return {"status": "error", "message": result.stderr[-500:]}

    # Clean up
    os.remove(concat_file)

    return {"status": "success", "video_path": output_path}


def _probe_resolution(path: str) -> tuple[int, int]:
    """Return (width, height) of the first video stream in a file, or (0, 0)."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "stream=width,height",
        "-of", "json", path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0:
        streams = json.loads(r.stdout).get("streams", [{}])
        if streams:
            return streams[0].get("width", 0) or 0, streams[0].get("height", 0) or 0
    return 0, 0


def _concat_with_crossfade(
    clip_paths: list[str],
    output_path: str,
    transitions: list[dict],
) -> dict:
    """Concatenate with xfade crossfade for video; hard-cut concat for audio.

    xfade requires all inputs to share identical W×H.  When clips come from
    different sources (IMA landscape 1176×780 vs Ken Burns portrait 1080×1920)
    we normalise every stream to the target resolution before chaining xfade.
    """
    if len(clip_paths) < 2:
        return concat_clips(clip_paths, output_path)

    inputs = []
    for p in clip_paths:
        inputs.extend(["-i", p])

    durations = [get_duration(p) for p in clip_paths]
    clips_have_audio = [check_has_audio(p) for p in clip_paths]
    has_any_audio = any(clips_have_audio)

    # Detect resolution mismatches — xfade silently fails when W×H differ.
    resolutions = [_probe_resolution(p) for p in clip_paths]
    # Target resolution priority (for consistent xfade input):
    #   1. 1080×1920 if any clip is already that size (Ken Burns native)
    #   2. Any portrait clip (h > w)
    #   3. First valid resolution
    #   4. Hardcoded 1080×1920 default (safe 9:16 HD)
    valid = [(w, h) for w, h in resolutions if w > 0 and h > 0]
    has_portrait = any(h > w for w, h in valid)
    if (1080, 1920) in valid:
        target_w, target_h = 1080, 1920
    elif has_portrait:
        # Any portrait content → always normalise to standard TikTok 9:16
        target_w, target_h = 1080, 1920
    else:
        target_w, target_h = next(iter(valid), (1080, 1920))
    need_scale = any(r != (target_w, target_h) for r in resolutions)

    # Probe fps to detect mismatches — xfade also requires identical fps.
    def _probe_fps(path: str) -> str:
        cmd = ["ffprobe", "-v", "quiet", "-show_entries", "stream=r_frame_rate",
               "-select_streams", "v:0", "-of", "csv=p=0", path]
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.stdout.strip().split("\n")[0].strip() if r.returncode == 0 else ""

    fps_vals = [_probe_fps(p) for p in clip_paths]
    target_fps = next((f for f in fps_vals if f), "30/1")
    need_fps = any(f != target_fps for f in fps_vals)

    # Always normalise when resolution OR fps is inconsistent across clips.
    # Also normalise pixel format to yuv420p (xfade fails on yuvj420p mix).
    need_norm = need_scale or need_fps

    # Pre-normalise filters: scale → pad → fps → pix_fmt
    scale_filters: list[str] = []
    v_labels: list[str] = []
    if need_norm:
        for i in range(len(clip_paths)):
            lbl = f"[vn{i}]"
            scale_filters.append(
                f"[{i}:v]scale={target_w}:{target_h}"
                f":force_original_aspect_ratio=decrease,"
                f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,"
                f"fps={target_fps},format=yuv420p{lbl}"
            )
            v_labels.append(lbl)
    else:
        v_labels = [f"[{i}:v]" for i in range(len(clip_paths))]

    # Build video xfade chain using (possibly scaled) labels.
    vfilters: list[str] = []
    current_input = v_labels[0]
    offset = durations[0]

    for i in range(1, len(clip_paths)):
        t = transitions[i - 1] if i - 1 < len(transitions) else {"type": "crossfade", "duration": 0.3}
        xfade_dur = t.get("duration", 0.3) if t.get("type") != "cut" else 0.0
        # Clamp: xfade must not exceed 40% of either neighbouring clip
        xfade_dur = min(xfade_dur, durations[i - 1] * 0.4, durations[i] * 0.4)
        xfade_dur = max(0.0, xfade_dur)

        offset_val = max(0.0, offset - xfade_dur)
        out_label = f"[v{i}]" if i < len(clip_paths) - 1 else "[outv]"

        vfilters.append(
            f"{current_input}{v_labels[i]}xfade=transition=fade"
            f":duration={xfade_dur:.4f}:offset={offset_val:.4f}{out_label}"
        )
        current_input = out_label
        offset = offset_val + durations[i]

    all_filters = scale_filters + vfilters
    map_args = ["-map", "[outv]"]
    codec_args = ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p"]

    if has_any_audio:
        # Hard-cut audio concat alongside smooth video xfade.
        # Clips without audio get silence so timing stays aligned.
        afilter_inputs = []
        for i, (has_a, dur) in enumerate(zip(clips_have_audio, durations, strict=True)):
            if has_a:
                afilter_inputs.append(f"[{i}:a]")
            else:
                # Use explicit stereo silence (0|0 = two channels both zero)
                all_filters.append(f"aevalsrc=0|0:c=stereo:d={dur:.4f}[sil{i}]")
                afilter_inputs.append(f"[sil{i}]")
        n = len(afilter_inputs)
        all_filters.append("".join(afilter_inputs) + f"concat=n={n}:v=0:a=1[outa]")
        map_args += ["-map", "[outa]"]
        codec_args += ["-c:a", "aac", "-b:a", "192k"]

    filter_complex = ";".join(all_filters)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        *map_args,
        *codec_args,
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        return {"status": "error", "message": result.stderr[-500:]}

    return {"status": "success", "video_path": output_path}


def add_audio_layers(
    video_path: str,
    output_path: str,
    voiceover_path: str = None,
    music_path: str = None,
    music_volume: float = 0.15,
    duck_under_voice: bool = True,
) -> dict:
    """
    Add voiceover and background music to the assembled video.

    Args:
        video_path: Input video (no audio or existing audio)
        output_path: Output video with audio
        voiceover_path: Path to voiceover audio file
        music_path: Path to background music file
        music_volume: Background music volume (0.0-1.0)
        duck_under_voice: Lower music volume when voice is playing
    """
    inputs = ["-i", video_path]

    audio_inputs = []

    if voiceover_path:
        inputs.extend(["-i", voiceover_path])
        audio_inputs.append("voice")

    if music_path:
        inputs.extend(["-i", music_path])
        audio_inputs.append("music")

    if not audio_inputs:
        return {"status": "error", "message": "No audio provided"}

    video_duration = get_duration(video_path)

    if voiceover_path and music_path:
        voice_idx = 1
        music_idx = 2

        if duck_under_voice:
            # Sidechain compression: duck music under voice
            filter_complex = (
                f"[{music_idx}:a]volume={music_volume},atrim=0:{video_duration},apad=whole_dur={video_duration}[music];"
                f"[{voice_idx}:a]apad=whole_dur={video_duration}[voice];"
                f"[music][voice]sidechaincompress=threshold=0.02:ratio=6:attack=200:release=1000[ducked];"
                f"[ducked][voice]amix=inputs=2:duration=longest[outa]"
            )
        else:
            filter_complex = (
                f"[{music_idx}:a]volume={music_volume},atrim=0:{video_duration},apad=whole_dur={video_duration}[music];"
                f"[{voice_idx}:a]apad=whole_dur={video_duration}[voice];"
                f"[music][voice]amix=inputs=2:duration=longest[outa]"
            )

        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[outa]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_path,
        ]

    elif voiceover_path:
        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_path,
        ]

    elif music_path:
        music_idx = 1
        fade_out_st = max(0.0, video_duration - 2)
        src_has_audio = check_has_audio(video_path)
        if src_has_audio:
            # Narration already baked into the video — mix with BGM at low volume
            filter_complex = (
                f"[0:a]apad=whole_dur={video_duration:.4f}[voice];"
                f"[{music_idx}:a]volume={music_volume},atrim=0:{video_duration:.4f},"
                f"apad=whole_dur={video_duration:.4f},"
                f"afade=t=in:d=1,afade=t=out:st={fade_out_st:.4f}:d=2[music];"
                f"[voice][music]amix=inputs=2:duration=longest[outa]"
            )
        else:
            # No narration in video — use BGM only
            filter_complex = (
                f"[{music_idx}:a]volume={music_volume},"
                f"afade=t=in:d=1,afade=t=out:st={fade_out_st:.4f}:d=2[outa]"
            )
        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[outa]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_path,
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        return {"status": "error", "message": result.stderr[-500:]}

    return {"status": "success", "video_path": output_path}


# Default aspect ratio per publishing channel
CHANNEL_DEFAULTS = {
    "reels": "9:16",
    "tiktok": "9:16",
    "shorts": "9:16",
    "instagram": "9:16",
    "xiaohongshu": "9:16",
    "douyin": "9:16",
    "youtube": "16:9",
    "website": "16:9",
    "mls": "16:9",
    "zillow": "16:9",
}


def resolve_aspect_ratio(
    aspect_ratio: str = None,
    channel: str = None,
) -> str:
    """
    Determine the output aspect ratio.

    Priority: explicit aspect_ratio > channel default > "9:16".
    """
    if aspect_ratio:
        return aspect_ratio
    if channel:
        return CHANNEL_DEFAULTS.get(channel.lower(), "9:16")
    return "9:16"


def create_output_format(
    video_path: str,
    output_dir: str,
    listing_id: str = "listing",
    aspect_ratio: str = "9:16",
) -> dict:
    """
    Create a single output format. Converts between aspect ratios if needed.

    If the source matches the target ratio, it's a simple copy.
    If converting 9:16 → 16:9 (or vice versa), uses blurred background fill.

    Args:
        video_path: Input video path
        output_dir: Output directory
        listing_id: Identifier for filename
        aspect_ratio: Target aspect ratio ("9:16" or "16:9")

    Returns:
        {"status": "success", "video_path": str, "aspect_ratio": str}
    """
    os.makedirs(output_dir, exist_ok=True)

    tag = "9x16" if aspect_ratio == "9:16" else "16x9"
    output_path = os.path.join(output_dir, f"{listing_id}_{tag}.mp4")

    # Probe source dimensions
    probe_cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "stream=width,height",
        "-of", "json", video_path,
    ]
    probe = subprocess.run(probe_cmd, capture_output=True, text=True)
    src_w, src_h = 1080, 1920  # default assumption
    if probe.returncode == 0:
        streams = json.loads(probe.stdout).get("streams", [{}])
        if streams:
            src_w = streams[0].get("width", 1080)
            src_h = streams[0].get("height", 1920)

    src_vertical = src_h > src_w
    target_vertical = aspect_ratio == "9:16"

    if src_vertical == target_vertical:
        # Same orientation — just copy
        subprocess.run(["cp", video_path, output_path], check=True)
    elif target_vertical:
        # 16:9 source → 9:16 target: blurred background fill
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-filter_complex",
            "[0:v]split=2[bg][fg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bgblur];"
            "[fg]scale=1080:-1:force_original_aspect_ratio=decrease[fgscaled];"
            "[bgblur][fgscaled]overlay=(W-w)/2:(H-h)/2[outv]",
            "-map", "[outv]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "copy", output_path,
        ]
        subprocess.run(cmd, capture_output=True, text=True)
    else:
        # 9:16 source → 16:9 target: blurred background fill
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-filter_complex",
            "[0:v]split=2[bg][fg];"
            "[bg]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,boxblur=20:5[bgblur];"
            "[fg]scale=-1:1080:force_original_aspect_ratio=decrease[fgscaled];"
            "[bgblur][fgscaled]overlay=(W-w)/2:(H-h)/2[outv]",
            "-map", "[outv]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "copy", output_path,
        ]
        subprocess.run(cmd, capture_output=True, text=True)

    return {
        "status": "success",
        "video_path": output_path,
        "aspect_ratio": aspect_ratio,
    }


def create_both_formats(
    video_path: str,
    output_dir: str,
    listing_id: str = "listing",
) -> dict:
    """Legacy wrapper: create both vertical and horizontal versions."""
    v = create_output_format(video_path, output_dir, listing_id, "9:16")
    h = create_output_format(video_path, output_dir, listing_id, "16:9")
    return {
        "status": "success",
        "vertical": v["video_path"],
        "horizontal": h["video_path"],
    }


def check_has_audio(file_path: str) -> bool:
    """Return True if the file has at least one audio stream."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "stream=codec_type",
        "-of", "json", file_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return False
    streams = json.loads(result.stdout).get("streams", [])
    return any(s.get("codec_type") == "audio" for s in streams)


def _burn_subtitle_on_clip(
    clip_path: str,
    text: str,
    output_path: str,
    font_path: str = None,
) -> bool:
    """Burn subtitle text onto a clip using PIL PNG + ffmpeg overlay.

    Renders text_narration as a subtitle strip at the bottom of the clip.
    Returns True on success, False on any failure (non-fatal — clip used as-is).
    """
    import tempfile
    import textwrap

    if not text:
        return False

    # Probe clip dimensions
    w, h = _probe_resolution(clip_path)
    if w <= 0 or h <= 0:
        w, h = 1080, 1920

    # Word-wrap: ~32 chars per line at 1080px width
    scale = w / 1080.0
    chars_per_line = max(20, int(32 / scale * (w / 1080.0))) if scale > 0 else 32
    lines = textwrap.wrap(text, width=chars_per_line)
    if not lines:
        return False

    fontsize = max(28, int(38 * scale))
    line_height = fontsize + 14
    bottom_margin = max(60, int(80 * scale))
    total_h = len(lines) * line_height
    start_y = h - bottom_margin - total_h

    texts = [
        {"text": line, "y": start_y + i * line_height, "fontsize": fontsize}
        for i, line in enumerate(lines)
    ]

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        sub_png = f.name

    try:
        ok = _create_text_overlay_png(w, h, texts, sub_png, font_path)
        if not ok:
            return False

        cmd = [
            "ffmpeg", "-y",
            "-i", clip_path,
            "-i", sub_png,
            "-filter_complex", "[0:v][1:v]overlay=0:0[outv]",
            "-map", "[outv]",
            "-map", "0:a?" ,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            output_path,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.returncode == 0
    finally:
        if os.path.exists(sub_png):
            os.remove(sub_png)


def _create_text_overlay_png(
    width: int,
    height: int,
    texts: list[dict],
    output_path: str,
    font_path: str = None,
) -> bool:
    """
    Render text onto a transparent RGBA PNG using Pillow.

    Uses PIL instead of ffmpeg drawtext to avoid libfreetype dependency.
    texts: list of {"text": str, "y": int, "fontsize": int}
    Returns True on success.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False

    # Font candidates (prefer bold for readability on video)
    font_candidates = [fp for fp in [
        font_path,
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Geneva.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ] if fp and os.path.exists(fp)]

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    for item in texts:
        text = item["text"]
        fontsize = item.get("fontsize", 38)
        y = item.get("y", 100)

        font = None
        for fp in font_candidates:
            try:
                font = ImageFont.truetype(fp, fontsize)
                break
            except Exception:
                continue
        if font is None:
            # PIL default is tiny — scale up with load_default if truetype unavailable
            font = ImageFont.load_default()

        # Measure text dimensions for centering
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = max(20, (width - text_w) // 2)

        # Draw full-width semi-transparent background strip for readability
        pad = 10
        draw.rectangle([0, y - pad, width, y + text_h + pad], fill=(0, 0, 0, 160))

        # Draw shadow (8-direction offset in semi-transparent black)
        for dx, dy in [(-2, -2), (-2, 2), (2, -2), (2, 2), (0, -2), (0, 2), (-2, 0), (2, 0)]:
            draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 200))
        # Draw main text in white
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    img.save(output_path, "PNG")
    return True


def add_text_overlays(
    video_path: str,
    output_path: str,
    address: str = None,
    price: str = None,
    agent_name: str = None,
    agent_phone: str = None,
    font_path: str = None,
) -> dict:
    """
    Burn text overlays onto the video.

    Uses Pillow to render text onto transparent PNGs, then composites
    them with ffmpeg's overlay filter (no libfreetype/drawtext needed).

    Layout:
      - Top (0 to min(5s, 30% of video)): address line + price line
      - Bottom (last 4s): agent name + phone (CTA)
    """
    import tempfile

    duration = get_duration(video_path)
    if duration <= 0:
        return {"status": "error", "message": "Cannot probe video duration"}

    has_title = bool(address or price)
    has_cta = bool(agent_name or agent_phone)

    if not has_title and not has_cta:
        subprocess.run(["cp", video_path, output_path], check=True)
        return {"status": "success", "video_path": output_path}

    # Probe video dimensions
    probe_cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "stream=width,height",
        "-of", "json", video_path,
    ]
    probe = subprocess.run(probe_cmd, capture_output=True, text=True)
    vid_w, vid_h = 1080, 1920  # default 9:16
    if probe.returncode == 0:
        streams = json.loads(probe.stdout).get("streams", [{}])
        if streams:
            vid_w = streams[0].get("width", 1080) or 1080
            vid_h = streams[0].get("height", 1920) or 1920

    title_end = min(5.0, duration * 0.3)
    cta_start = max(0.0, duration - 4.0)

    tmp_dir = tempfile.mkdtemp(prefix="overlay_")
    overlay_inputs = []   # (png_path, enable_expr)

    if has_title:
        title_texts = []
        if address:
            title_texts.append({"text": address, "y": 100, "fontsize": 38})
        if price:
            title_texts.append({"text": price, "y": 155, "fontsize": 44})
        title_png = os.path.join(tmp_dir, "title.png")
        if _create_text_overlay_png(vid_w, vid_h, title_texts, title_png, font_path):
            overlay_inputs.append((title_png, f"between(t,0,{title_end:.1f})"))

    if has_cta:
        cta_texts = []
        if agent_name:
            cta_texts.append({"text": agent_name, "y": vid_h - 180, "fontsize": 36})
        if agent_phone:
            cta_texts.append({"text": agent_phone, "y": vid_h - 130, "fontsize": 40})
        cta_png = os.path.join(tmp_dir, "cta.png")
        if _create_text_overlay_png(vid_w, vid_h, cta_texts, cta_png, font_path):
            overlay_inputs.append((cta_png, f"between(t,{cta_start:.1f},{duration:.1f})"))

    if not overlay_inputs:
        subprocess.run(["cp", video_path, output_path], check=True)
        return {"status": "success", "video_path": output_path}

    # Build ffmpeg command: video + PNG inputs → overlay filter chain
    cmd = ["ffmpeg", "-y", "-i", video_path]
    for png_path, _ in overlay_inputs:
        cmd += ["-i", png_path]

    # Build filter_complex: chain overlay filters sequentially
    filter_parts = []
    in_label = "0:v"
    for i, (_, enable_expr) in enumerate(overlay_inputs):
        png_idx = i + 1
        out_label = f"v{i + 1}" if i < len(overlay_inputs) - 1 else "outv"
        filter_parts.append(
            f"[{in_label}][{png_idx}:v]overlay=0:0:enable='{enable_expr}'[{out_label}]"
        )
        in_label = out_label

    cmd += [
        "-filter_complex", ";".join(filter_parts),
        "-map", "[outv]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "copy",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    # Cleanup temp PNGs
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)

    if result.returncode != 0:
        return {"status": "error", "message": result.stderr[-500:]}

    return {"status": "success", "video_path": output_path}


def get_duration(file_path: str) -> float:
    """Get duration of audio/video file in seconds."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "json",
        file_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        data = json.loads(result.stdout)
        return float(data.get("format", {}).get("duration", 0))
    return 0.0


def _ensure_video_covers_audio(
    video_path: str,
    audio_path: str,
    progress_callback=None,
) -> str:
    """
    If the concatenated video is shorter than the voiceover, slow it down
    proportionally so the visuals cover the full narration.

    Uses ffmpeg setpts to stretch; caps slowdown at 0.6x to avoid jelly motion.
    If the gap is too large (>0.6x), it loops the video instead.

    Returns the (possibly new) video path.
    """
    video_dur = get_duration(video_path)
    audio_dur = get_duration(audio_path)

    if video_dur <= 0 or audio_dur <= 0 or video_dur >= audio_dur:
        return video_path  # no fix needed

    target_dur = audio_dur + 1.0  # 1s breathing room
    ratio = target_dur / video_dur  # >1 means video needs to be longer

    stretched_path = video_path.replace(".mp4", "_stretched.mp4")

    if ratio <= 1.67:
        # Slow down (up to 0.6x speed is acceptable)
        if progress_callback:
            progress_callback(
                f"Video {video_dur:.0f}s < voiceover {audio_dur:.0f}s, "
                f"slowing to {1/ratio:.0%} speed..."
            )
        pts_factor = ratio  # setpts=PTS*ratio stretches duration
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-filter:v", f"setpts={pts_factor:.4f}*PTS",
            "-an",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            stretched_path,
        ]
    else:
        # Gap too large for slowdown alone — loop the video
        if progress_callback:
            progress_callback(
                f"Video {video_dur:.0f}s << voiceover {audio_dur:.0f}s, "
                f"looping video to match..."
            )
        loop_count = int(ratio) + 1
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", str(loop_count - 1),
            "-i", video_path,
            "-t", f"{target_dur:.2f}",
            "-an",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            stretched_path,
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        # Fallback: return original and let audio be truncated
        return video_path

    # Replace original with stretched version
    os.replace(stretched_path, video_path)
    return video_path


def full_assembly(
    storyboard: dict,
    clips_dir: str,
    voiceover_path: str,
    music_path: str,
    output_dir: str,
    listing_id: str = "listing",
    aspect_ratio: str = None,
    channel: str = None,
    progress_callback=None,
) -> dict:
    """
    Full assembly pipeline: concat clips → add audio → create output format.

    Args:
        aspect_ratio: Explicit "9:16" or "16:9". Overrides channel default.
        channel: Publishing channel (reels/tiktok/youtube/...) for auto ratio.
                 If neither aspect_ratio nor channel is set, defaults to "9:16".
    """
    from job_logger import (
        get_logger,
        log_duration_check,
        log_job_summary,
        log_step_end,
        log_step_start,
    )

    logger = get_logger()
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Order clips by sequence
    log_step_start("assembly", {"listing_id": listing_id})
    if progress_callback:
        progress_callback("🔧 [4/5] Assembling clips...")

    clip_files = []
    transitions = []

    for segment in sorted(storyboard["storyboard"], key=lambda s: s["sequence"]):
        seq = segment["sequence"]

        if segment["render_type"] == "ai_video":
            clip_path = os.path.join(clips_dir, f"ai_clip_{seq:02d}.mp4")
        else:
            clip_path = os.path.join(clips_dir, f"slide_{seq:02d}.mp4")

        if os.path.exists(clip_path):
            clip_dur = get_duration(clip_path)
            logger.info("  Clip seq=%02d  dur=%.1fs  path=%s", seq, clip_dur, clip_path)
            clip_files.append(clip_path)

            if segment["render_type"] == "ai_video":
                transitions.append({"type": "cut", "duration": 0})
            else:
                transitions.append({"type": "crossfade", "duration": 0.5})
        else:
            logger.warning("  Clip seq=%02d  MISSING: %s", seq, clip_path)

    # Add CTA frame
    cta_path = os.path.join(clips_dir, "cta.mp4")
    if os.path.exists(cta_path):
        clip_files.append(cta_path)
        transitions.append({"type": "crossfade", "duration": 0.8})

    logger.info("Total clips: %d", len(clip_files))

    # Step 2: Concatenate
    concat_path = os.path.join(output_dir, f"{listing_id}_concat.mp4")
    concat_result = concat_clips(clip_files, concat_path, transitions)

    if concat_result["status"] != "success":
        log_step_end("assembly", concat_result)
        return concat_result

    concat_dur = get_duration(concat_path)
    logger.info("Concat duration: %.1fs", concat_dur)

    # Step 2.5: Ensure video covers voiceover duration
    if voiceover_path and os.path.exists(voiceover_path):
        audio_dur = get_duration(voiceover_path)
        if concat_dur < audio_dur:
            log_duration_check(concat_dur, audio_dur, "stretching")
        else:
            log_duration_check(concat_dur, audio_dur, "ok")
        concat_path = _ensure_video_covers_audio(
            concat_path, voiceover_path, progress_callback
        )

    # Step 3: Add audio
    if progress_callback:
        progress_callback("🎵 [5/5] Adding voiceover and music...")

    final_path = os.path.join(output_dir, f"{listing_id}_final.mp4")
    audio_result = add_audio_layers(
        video_path=concat_path,
        output_path=final_path,
        voiceover_path=voiceover_path,
        music_path=music_path,
        music_volume=0.12,
        duck_under_voice=True,
    )

    if audio_result["status"] != "success":
        log_step_end("assembly", audio_result)
        return audio_result

    # Step 4: Create output format
    target_ratio = resolve_aspect_ratio(aspect_ratio, channel)
    format_result = create_output_format(final_path, output_dir, listing_id, target_ratio)

    # Clean up intermediate files
    for f in [concat_path, final_path]:
        if os.path.exists(f):
            os.remove(f)

    result = {
        "status": "success",
        "video_path": format_result["video_path"],
        "aspect_ratio": target_ratio,
    }
    log_step_end("assembly", result)
    log_job_summary(result)

    return result


def full_assembly_v2(
    scene_plan: list[dict],
    clips_dir: str,
    narrations: list[dict],
    music_path: str,
    output_dir: str,
    listing_id: str = "listing",
    aspect_ratio: str = None,
    channel: str = None,
    progress_callback=None,
    address: str = None,
    price: str = None,
    agent_name: str = None,
    agent_phone: str = None,
    font_path: str = None,
) -> dict:
    """
    V2 assembly pipeline with per-scene audio alignment + text overlays.

    Instead of one monolithic voiceover laid over the full video,
    each scene's clip is matched with its own narration segment.
    This guarantees audio-visual sync regardless of AI clip duration.

    Pipeline:
      1. For each scene: match clip + narration, adjust clip length to fit
      2. Concatenate all scene clips (with per-scene audio baked in)
      3. Add background music
      4. Burn text overlays (address, price, agent CTA)
      5. Create output format
      6. Audio quality gate

    Args:
        scene_plan: Scene plan with sequence numbers
        clips_dir: Directory containing scene_XX.mp4 clips
        narrations: Per-scene TTS results from generate_scene_voiceovers()
        music_path: Background music file
        output_dir: Output directory
        listing_id: Identifier for output filenames
        progress_callback: Progress callback
        address: Property address for title overlay
        price: Listing price for title overlay
        agent_name: Agent name for CTA overlay
        agent_phone: Agent phone for CTA overlay
        font_path: Optional custom font path
    """
    import video_diagnostics
    from job_logger import get_logger, log_job_summary, log_step_end, log_step_start

    logger = get_logger()
    os.makedirs(output_dir, exist_ok=True)
    log_step_start("assembly_v2", {"listing_id": listing_id, "mode": "per_scene_audio"})
    video_diagnostics.record_scene_plan(output_dir, scene_plan)

    if progress_callback:
        progress_callback("Assembling scenes with per-scene audio...")

    # Build narration lookup: sequence -> narration result
    narr_lookup = {n["sequence"]: n for n in narrations if n["status"] == "success"}

    # Warn early if all TTS failed
    if narrations and not narr_lookup:
        failed_msgs = [n.get("message", "unknown") for n in narrations if n["status"] != "success"]
        logger.warning(
            "ALL %d narrations failed — video will be silent unless music is available. "
            "First error: %s", len(narrations), failed_msgs[0] if failed_msgs else "?"
        )

    # Step 1: For each scene, create clip with its narration baked in
    scene_clips_with_audio = []

    for scene in sorted(scene_plan, key=lambda s: s["sequence"]):
        seq = scene["sequence"]
        clip_path = os.path.join(clips_dir, f"scene_{seq:02d}.mp4")
        adjustment = "none"
        adjustment_ratio = None
        assembly_note = None

        if not os.path.exists(clip_path):
            logger.warning("  Scene %02d clip MISSING: %s", seq, clip_path)
            video_diagnostics.record_assembly_diagnostics(
                job_dir=output_dir,
                sequence=seq,
                clip_duration_before=0.0,
                narration_duration=None,
                adjustment="missing_clip",
                merge_status="missing_clip",
                output_path=clip_path,
                note="scene clip missing before assembly",
            )
            continue

        clip_dur = get_duration(clip_path)
        narr = narr_lookup.get(seq)

        if narr and narr.get("audio_path") and os.path.exists(narr["audio_path"]):
            narr_dur = narr["duration"]
            merged_path = os.path.join(output_dir, f"merged_{seq:02d}.mp4")

            # If clip is shorter than narration, stretch clip to match
            if clip_dur < narr_dur - 0.5:
                ratio = (narr_dur + 0.3) / clip_dur
                adjustment = "stretch" if ratio <= 1.67 else "loop"
                adjustment_ratio = ratio
                logger.info(
                    "  Scene %02d: clip=%.1fs < narr=%.1fs, stretching %.1fx",
                    seq, clip_dur, narr_dur, ratio,
                )
                stretched_path = os.path.join(output_dir, f"stretched_{seq:02d}.mp4")

                if ratio <= 1.67:
                    cmd = [
                        "ffmpeg", "-y", "-i", clip_path,
                        "-filter:v", f"setpts={ratio:.4f}*PTS",
                        "-an", "-c:v", "libx264", "-preset", "fast",
                        "-crf", "18", "-pix_fmt", "yuv420p",
                        stretched_path,
                    ]
                else:
                    loop_count = int(ratio) + 1
                    cmd = [
                        "ffmpeg", "-y",
                        "-stream_loop", str(loop_count - 1),
                        "-i", clip_path,
                        "-t", f"{narr_dur + 0.3:.2f}",
                        "-an", "-c:v", "libx264", "-preset", "fast",
                        "-crf", "18", "-pix_fmt", "yuv420p",
                        stretched_path,
                    ]

                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    clip_path = stretched_path
                else:
                    assembly_note = result.stderr[-300:]
            elif clip_dur > narr_dur + 2.0:
                # Clip is much longer than narration — trim to narr + 1s buffer
                adjustment = "trim"
                logger.info(
                    "  Scene %02d: clip=%.1fs > narr=%.1fs, trimming",
                    seq, clip_dur, narr_dur,
                )
                trimmed_path = os.path.join(output_dir, f"trimmed_{seq:02d}.mp4")
                cmd = [
                    "ffmpeg", "-y", "-i", clip_path,
                    "-t", f"{narr_dur + 1.0:.2f}",
                    "-c:v", "libx264", "-preset", "fast",
                    "-crf", "18", "-pix_fmt", "yuv420p",
                    "-an", trimmed_path,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    clip_path = trimmed_path
                else:
                    assembly_note = result.stderr[-300:]

            # Merge clip + narration audio
            cmd = [
                "ffmpeg", "-y",
                "-i", clip_path,
                "-i", narr["audio_path"],
                "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                merged_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                # Burn subtitle text onto merged clip (non-fatal if it fails)
                subtitle_text = scene.get("text_narration", "").strip()
                if subtitle_text:
                    sub_path = merged_path.replace(".mp4", "_sub.mp4")
                    if _burn_subtitle_on_clip(merged_path, subtitle_text, sub_path, font_path):
                        os.replace(sub_path, merged_path)
                    elif os.path.exists(sub_path):
                        os.remove(sub_path)

                merged_dur = get_duration(merged_path)
                logger.info("  Scene %02d: merged %.1fs  %s", seq, merged_dur, merged_path)
                scene_clips_with_audio.append(merged_path)
                video_diagnostics.record_assembly_diagnostics(
                    job_dir=output_dir,
                    sequence=seq,
                    clip_duration_before=clip_dur,
                    narration_duration=narr_dur,
                    adjustment=adjustment,
                    adjustment_ratio=adjustment_ratio,
                    merge_status="success",
                    output_path=merged_path,
                    note=assembly_note,
                )
            else:
                logger.warning("  Scene %02d merge failed, using clip only", seq)
                scene_clips_with_audio.append(clip_path)
                video_diagnostics.record_assembly_diagnostics(
                    job_dir=output_dir,
                    sequence=seq,
                    clip_duration_before=clip_dur,
                    narration_duration=narr_dur,
                    adjustment=adjustment,
                    adjustment_ratio=adjustment_ratio,
                    merge_status="merge_failed",
                    output_path=clip_path,
                    note=result.stderr[-300:],
                )
        else:
            # No narration for this scene — use clip as-is (silent)
            logger.info("  Scene %02d: no narration, clip=%.1fs", seq, clip_dur)
            scene_clips_with_audio.append(clip_path)
            video_diagnostics.record_assembly_diagnostics(
                job_dir=output_dir,
                sequence=seq,
                clip_duration_before=clip_dur,
                narration_duration=None,
                adjustment="no_narration",
                merge_status="clip_only",
                output_path=clip_path,
                note="scene has no narration",
            )

    if not scene_clips_with_audio:
        result = {"status": "error", "message": "No scene clips available for assembly"}
        video_diagnostics.record_final_diagnostics(output_dir, result)
        log_step_end("assembly_v2", result)
        return result

    # Step 2: Concatenate all scene clips
    if progress_callback:
        progress_callback("Concatenating scenes...")

    concat_path = os.path.join(output_dir, f"{listing_id}_concat.mp4")
    # 0.3s crossfade between scenes to avoid hard-cut "slideshow" feel
    transitions = [{"type": "crossfade", "duration": 0.3}] * len(scene_clips_with_audio)
    concat_result = concat_clips(scene_clips_with_audio, concat_path, transitions)

    if concat_result["status"] != "success":
        video_diagnostics.record_final_diagnostics(output_dir, concat_result)
        log_step_end("assembly_v2", concat_result)
        return concat_result

    total_dur = get_duration(concat_path)
    logger.info("Total concat duration: %.1fs", total_dur)

    # Step 3: Add background music
    final_path = concat_path
    if music_path and os.path.exists(music_path):
        if progress_callback:
            progress_callback("Adding background music...")

        music_mix_path = os.path.join(output_dir, f"{listing_id}_final.mp4")
        music_result = add_audio_layers(
            video_path=concat_path,
            output_path=music_mix_path,
            voiceover_path=None,  # Voice already baked into each clip
            music_path=music_path,
            music_volume=0.10,
            duck_under_voice=False,
        )

        if music_result["status"] == "success":
            final_path = music_mix_path
        else:
            logger.warning("Background music mix failed, continuing without music: %s", music_result.get("message"))

    # Step 4: Create output format
    target_ratio = resolve_aspect_ratio(aspect_ratio, channel)
    format_result = create_output_format(final_path, output_dir, listing_id, target_ratio)

    # Step 5: Burn text overlays (address, price, agent CTA)
    has_any_overlay = any([address, price, agent_name, agent_phone])
    overlay_applied = False
    if has_any_overlay:
        if progress_callback:
            progress_callback("Burning text overlays...")
        overlay_path = os.path.join(output_dir, f"{listing_id}_overlay.mp4")
        overlay_result = add_text_overlays(
            video_path=format_result["video_path"],
            output_path=overlay_path,
            address=address,
            price=price,
            agent_name=agent_name,
            agent_phone=agent_phone,
            font_path=font_path,
        )
        if overlay_result["status"] == "success":
            os.replace(overlay_path, format_result["video_path"])
            overlay_applied = True
            logger.info("Text overlays burned: address=%s price=%s agent=%s", address, price, agent_name)
        else:
            logger.warning("Text overlay failed (non-fatal): %s", overlay_result.get("message"))

    # Clean up intermediate files
    import glob
    for pattern in ["merged_*.mp4", "stretched_*.mp4", "trimmed_*.mp4"]:
        for f in glob.glob(os.path.join(output_dir, pattern)):
            os.remove(f)
    for f in [os.path.join(output_dir, f"{listing_id}_concat.mp4"),
              os.path.join(output_dir, f"{listing_id}_final.mp4")]:
        if os.path.exists(f):
            os.remove(f)

    # Step 6: Audio quality gate
    final_video = format_result["video_path"]
    has_audio = check_has_audio(final_video)
    if not has_audio:
        logger.warning(
            "AUDIO QUALITY GATE FAILED: final video has no audio stream. "
            "TTS narrations: %d succeeded / %d total. music_path: %s",
            len(narr_lookup), len(narrations), music_path,
        )

    result = {
        "status": "success",
        "video_path": final_video,
        "aspect_ratio": target_ratio,
        "total_duration": total_dur,
        "scenes": len(scene_clips_with_audio),
        "has_audio": has_audio,
        "narrations_succeeded": len(narr_lookup),
        "audio_warning": None if has_audio else "No audio stream in final video — check TTS and music pipeline",
        "overlay_requested": has_any_overlay,
        "overlay_applied": overlay_applied,
    }
    video_diagnostics.record_final_diagnostics(output_dir, result)
    log_step_end("assembly_v2", result)
    log_job_summary(result)

    return result


if __name__ == "__main__":
    print("Use full_assembly() or full_assembly_v2() from the orchestrator.")
    print("Standalone: ffmpeg must be installed.")
    subprocess.run(["ffmpeg", "-version"], capture_output=True)
