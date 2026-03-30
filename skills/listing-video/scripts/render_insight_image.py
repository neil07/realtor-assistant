#!/usr/bin/env python3
"""
Reel Agent — Daily Insight Image Renderer

Uses Pillow to render branded image cards for social media.
Supports three formats:
  - Instagram Story:  1080 x 1920 (9:16)
  - Instagram Feed:   1080 x 1080 (1:1)

Colors and agent name are pulled from agent profile.
Fonts fall back to system defaults if custom fonts are unavailable.

Usage (script mode):
  python render_insight_image.py --headline "Spring Tips" --body "..." --output ./out/

Usage (tool mode):
  from render_insight_image import render_all_formats
"""

import os
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Default brand colors (used when agent has no custom colors)
DEFAULT_COLORS = {
    "primary": "#2C3E50",
    "accent": "#E74C3C",
    "background": "#FAFAFA",
    "text_dark": "#2C3E50",
    "text_light": "#FFFFFF",
    "text_muted": "#7F8C8D",
}

FONTS_DIR = Path(__file__).parent.parent / "assets" / "fonts"


def _load_font(size: int, bold: bool = False) -> "ImageFont.FreeTypeFont | ImageFont.ImageFont":
    """Load font with graceful fallback to PIL default."""
    if not PIL_AVAILABLE:
        raise ImportError("Pillow is required: pip install Pillow")

    font_names = ["Helvetica-Bold.ttf", "Arial-Bold.ttf", "DejaVuSans-Bold.ttf"] if bold \
        else ["Helvetica.ttf", "Arial.ttf", "DejaVuSans.ttf"]

    # Try fonts dir first
    for name in font_names:
        candidate = FONTS_DIR / name
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except Exception:
                continue

    # Try system fonts
    system_paths = [
        "/System/Library/Fonts/Helvetica.ttc",          # macOS
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
        "C:/Windows/Fonts/arial.ttf",                   # Windows
    ]
    for path in system_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue

    return ImageFont.load_default()


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert hex color string to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _wrap_text(text: str, font, draw: "ImageDraw.Draw", max_width: int) -> list[str]:
    """Wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current = []

    for word in words:
        test = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]

    if current:
        lines.append(" ".join(current))
    return lines


def render_card(
    headline: str,
    body: str,
    agent_name: str,
    width: int,
    height: int,
    branding_colors: list[str] | None = None,
    output_path: str | None = None,
) -> bytes | None:
    """
    Render a single image card.

    Args:
        headline: Bold headline text
        body: Body paragraph text
        agent_name: Agent name for footer
        width, height: Image dimensions in pixels
        branding_colors: [primary_color, accent_color] hex strings
        output_path: If provided, save to this path and return None

    Returns:
        PNG bytes if output_path is None, else None (file saved)
    """
    if not PIL_AVAILABLE:
        raise ImportError("Pillow is required: pip install Pillow")

    # Colors
    colors = dict(DEFAULT_COLORS)
    if branding_colors and len(branding_colors) >= 1:
        colors["primary"] = branding_colors[0]
    if branding_colors and len(branding_colors) >= 2:
        colors["accent"] = branding_colors[1]

    primary_rgb = _hex_to_rgb(colors["primary"])
    accent_rgb = _hex_to_rgb(colors["accent"])

    # Canvas
    img = Image.new("RGB", (width, height), color=_hex_to_rgb(colors["background"]))
    draw = ImageDraw.Draw(img)

    # Top color bar (8% of height)
    bar_height = int(height * 0.08)
    draw.rectangle([(0, 0), (width, bar_height)], fill=primary_rgb)

    # Accent strip below bar
    accent_strip = max(4, int(height * 0.004))
    draw.rectangle([(0, bar_height), (width, bar_height + accent_strip)], fill=accent_rgb)

    # Fonts (scale with image size)
    base = width // 20
    font_headline = _load_font(int(base * 1.4), bold=True)
    font_body = _load_font(int(base * 0.85))
    font_label = _load_font(int(base * 0.7))
    font_agent = _load_font(int(base * 0.75), bold=True)

    padding = int(width * 0.07)
    y = bar_height + accent_strip + padding

    # "MARKET INSIGHT" label
    label = "MARKET INSIGHT"
    draw.text((padding, y), label, font=font_label, fill=accent_rgb)
    label_bbox = draw.textbbox((padding, y), label, font=font_label)
    y += (label_bbox[3] - label_bbox[1]) + int(height * 0.02)

    # Headline (wrapped)
    max_text_width = width - padding * 2
    headline_lines = _wrap_text(headline.upper(), font_headline, draw, max_text_width)
    for line in headline_lines:
        draw.text((padding, y), line, font=font_headline, fill=primary_rgb)
        bbox = draw.textbbox((padding, y), line, font=font_headline)
        y += (bbox[3] - bbox[1]) + int(height * 0.01)
    y += int(height * 0.015)

    # Divider line
    line_y = y
    draw.rectangle([(padding, line_y), (width - padding, line_y + 2)], fill=accent_rgb)
    y += int(height * 0.03)

    # Body text (wrapped)
    body_lines = _wrap_text(body, font_body, draw, max_text_width)
    for line in body_lines:
        draw.text((padding, y), line, font=font_body, fill=_hex_to_rgb(colors["text_dark"]))
        bbox = draw.textbbox((padding, y), line, font=font_body)
        y += (bbox[3] - bbox[1]) + int(height * 0.008)

    # Bottom footer bar
    footer_height = int(height * 0.1)
    footer_y = height - footer_height
    draw.rectangle([(0, footer_y), (width, height)], fill=primary_rgb)

    # Agent name in footer
    agent_label = f"— {agent_name}" if agent_name else "Reel Agent"
    draw.text(
        (padding, footer_y + footer_height // 4),
        agent_label,
        font=font_agent,
        fill=_hex_to_rgb(colors["text_light"]),
    )

    # Save or return bytes
    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        img.save(output_path, "JPEG", quality=92)
        return None
    else:
        import io
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=92)
        return buf.getvalue()


def render_all_formats(
    headline: str,
    body: str,
    agent_name: str,
    output_dir: str,
    branding_colors: list[str] | None = None,
) -> dict[str, str]:
    """
    Render all required image formats for one insight piece.

    Args:
        headline: Post headline
        body: Post body text
        agent_name: Agent name for branding
        output_dir: Directory to save images
        branding_colors: [primary, accent] hex colors from agent profile

    Returns:
        Dict mapping format_name → file_path
    """
    os.makedirs(output_dir, exist_ok=True)
    outputs = {}

    formats = {
        "story_1080x1920": (1080, 1920),   # Instagram Story
        "feed_1080x1080": (1080, 1080),    # Instagram Feed
    }

    for fmt_name, (w, h) in formats.items():
        path = os.path.join(output_dir, f"{fmt_name}.jpg")
        render_card(
            headline=headline,
            body=body,
            agent_name=agent_name,
            width=w,
            height=h,
            branding_colors=branding_colors,
            output_path=path,
        )
        outputs[fmt_name] = path

    return outputs


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Render insight image card")
    parser.add_argument("--headline", default="Spring Buying Tips for Lehigh Valley")
    parser.add_argument("--body", default=(
        "Spring is the busiest season for real estate. "
        "Get pre-approved before you start touring homes — "
        "it signals to sellers you're serious and ready to move fast. "
        "In today's market, being prepared is your biggest competitive advantage."
    ))
    parser.add_argument("--agent-name", default="Your Agent")
    parser.add_argument("--output", default="./test_output/insight")
    parser.add_argument("--colors", nargs="+", default=["#2C3E50", "#E74C3C"])
    args = parser.parse_args()

    print(f"Rendering insight images to {args.output}/...")
    results = render_all_formats(
        headline=args.headline,
        body=args.body,
        agent_name=args.agent_name,
        output_dir=args.output,
        branding_colors=args.colors,
    )
    for fmt, path in results.items():
        print(f"  {fmt}: {path}")
