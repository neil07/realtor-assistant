#!/usr/bin/env python3
"""
Reel Agent — Branded Insight Image Renderer (v2: Agent Identity + Key Numbers)

Renders branded image cards for social media that look like the AGENT'S content,
not a tool's output. Key design principles:

  1. Primary number is LARGEST — buyer/seller sees the key data in 2 seconds
  2. Agent identity is prominent — headshot/initials + name + tagline at bottom
  3. Market area is bold — builds "local expert" brand
  4. NO product branding — Reel Agent logo never appears on the image
  5. Brand colors are the agent's — their identity, their content

Formats:
  - Instagram Feed:   1080 x 1080 (1:1)
  - Instagram Story:  1080 x 1920 (9:16)

Usage (script mode):
  python render_insight_image.py --primary-number "6.42%" --primary-label "30-Year Rate"

Usage (tool mode):
  from render_insight_image import render_all_formats
"""

import os
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# ─── Constants ────────────────────────────────────────────────────────────────

DEFAULT_COLORS = {
    "primary": "#1B2A4A",      # Deep navy — professional, trustworthy
    "accent": "#C9A96E",       # Warm gold — premium feel
    "background": "#FAFAFA",   # Near-white
    "text_dark": "#1B2A4A",
    "text_light": "#FFFFFF",
    "text_muted": "#6B7280",
    "number_up": "#059669",    # Green for positive changes
    "number_down": "#DC2626",  # Red for negative changes
}

FONTS_DIR = Path(__file__).parent.parent / "assets" / "fonts"


# ─── Font Loading ─────────────────────────────────────────────────────────────


def _load_font(size: int, bold: bool = False) -> "ImageFont.FreeTypeFont | ImageFont.ImageFont":
    """Load font with graceful fallback."""
    if not PIL_AVAILABLE:
        raise ImportError("Pillow is required: pip install Pillow")

    font_names = (
        ["Helvetica-Bold.ttf", "Arial-Bold.ttf", "DejaVuSans-Bold.ttf"]
        if bold else
        ["Helvetica.ttf", "Arial.ttf", "DejaVuSans.ttf"]
    )

    for name in font_names:
        candidate = FONTS_DIR / name
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except Exception:
                continue

    system_paths = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in system_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue

    return ImageFont.load_default()


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _wrap_text(text: str, font, draw: "ImageDraw.Draw", max_width: int) -> list[str]:
    words = text.split()
    lines, current = [], []
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


def _draw_initials_circle(
    draw: "ImageDraw.Draw",
    center_x: int,
    center_y: int,
    radius: int,
    initials: str,
    bg_color: tuple,
    text_color: tuple,
) -> None:
    """Draw a circle with initials (used when no headshot available)."""
    draw.ellipse(
        [center_x - radius, center_y - radius, center_x + radius, center_y + radius],
        fill=bg_color,
    )
    font = _load_font(int(radius * 0.9), bold=True)
    bbox = draw.textbbox((0, 0), initials, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(
        (center_x - tw // 2, center_y - th // 2 - bbox[1]),
        initials,
        font=font,
        fill=text_color,
    )


def _get_initials(name: str) -> str:
    """Extract up to 2 initials from a name."""
    parts = name.strip().split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    elif parts:
        return parts[0][0].upper()
    return "?"


# ─── Core Rendering ──────────────────────────────────────────────────────────


def render_card(
    primary_number: str,
    primary_label: str,
    primary_direction: str,
    change_label: str,
    supporting_stats: list[str],
    market_area: str,
    agent_name: str,
    agent_tagline: str = "",
    width: int = 1080,
    height: int = 1080,
    branding_colors: list[str] | None = None,
    headshot_path: str | None = None,
    output_path: str | None = None,
) -> bytes | None:
    """
    Render a branded market insight card.

    Args:
        primary_number: The ONE key number shown largest (e.g. "6.42%")
        primary_label: What the number is (e.g. "30-Year Mortgage Rate")
        primary_direction: "up", "down", or "steady"
        change_label: Change description (e.g. "down 12 bps from last week")
        supporting_stats: List of 2-3 supporting stats
        market_area: Local market name for branding
        agent_name: Agent's full name
        agent_tagline: Agent's tagline (e.g. "Your Lehigh Valley Expert")
        width, height: Image dimensions
        branding_colors: [primary, accent] hex colors
        headshot_path: Path to agent headshot image (optional)
        output_path: Save path (returns bytes if None)

    Returns:
        JPEG bytes if output_path is None, else None (file saved).
    """
    if not PIL_AVAILABLE:
        raise ImportError("Pillow is required: pip install Pillow")

    # ── Colors ──
    colors = dict(DEFAULT_COLORS)
    if branding_colors and len(branding_colors) >= 1:
        colors["primary"] = branding_colors[0]
    if branding_colors and len(branding_colors) >= 2:
        colors["accent"] = branding_colors[1]

    primary_rgb = _hex_to_rgb(colors["primary"])
    accent_rgb = _hex_to_rgb(colors["accent"])
    bg_rgb = _hex_to_rgb(colors["background"])

    # Direction color for the primary number
    if primary_direction == "down":
        direction_rgb = _hex_to_rgb(colors["number_down"])
        arrow = "↓"
    elif primary_direction == "up":
        direction_rgb = _hex_to_rgb(colors["number_up"])
        arrow = "↑"
    else:
        direction_rgb = primary_rgb
        arrow = "→"

    # ── Canvas ──
    img = Image.new("RGB", (width, height), color=bg_rgb)
    draw = ImageDraw.Draw(img)

    # ── Dimensions ──
    padding = int(width * 0.07)
    is_story = height > width * 1.5  # 9:16 ratio

    # ── Fonts (scale with image) ──
    base = width // 18
    font_market_area = _load_font(int(base * 1.1), bold=True)
    font_update_label = _load_font(int(base * 0.7))
    font_primary_number = _load_font(int(base * 3.2), bold=True)
    font_primary_label = _load_font(int(base * 0.75))
    font_change = _load_font(int(base * 0.8), bold=True)
    font_stat = _load_font(int(base * 0.8))
    font_agent_name = _load_font(int(base * 0.85), bold=True)
    font_tagline = _load_font(int(base * 0.65))

    # ── Top Bar (agent brand color) ──
    bar_height = int(height * 0.06)
    draw.rectangle([(0, 0), (width, bar_height)], fill=primary_rgb)

    # Thin accent line below bar
    accent_h = max(3, int(height * 0.004))
    draw.rectangle([(0, bar_height), (width, bar_height + accent_h)], fill=accent_rgb)

    y = bar_height + accent_h + int(height * 0.04)

    if is_story:
        y += int(height * 0.06)  # Extra top space for story format

    # ── Market Area Label ──
    market_display = market_area.upper() if market_area else "MARKET UPDATE"
    draw.text((padding, y), market_display, font=font_market_area, fill=primary_rgb)
    bbox = draw.textbbox((padding, y), market_display, font=font_market_area)
    y += (bbox[3] - bbox[1]) + int(height * 0.005)

    # "WEEKLY UPDATE" sublabel
    sublabel = "WEEKLY MARKET UPDATE"
    draw.text((padding, y), sublabel, font=font_update_label, fill=_hex_to_rgb(colors["text_muted"]))
    bbox = draw.textbbox((padding, y), sublabel, font=font_update_label)
    y += (bbox[3] - bbox[1]) + int(height * 0.04)

    # ── Primary Number (the hero) ──
    if primary_number:
        draw.text((padding, y), primary_number, font=font_primary_number, fill=primary_rgb)
        bbox = draw.textbbox((padding, y), primary_number, font=font_primary_number)
        y += (bbox[3] - bbox[1]) + int(height * 0.005)

    # Primary label
    if primary_label:
        draw.text((padding, y), primary_label, font=font_primary_label, fill=_hex_to_rgb(colors["text_muted"]))
        bbox = draw.textbbox((padding, y), primary_label, font=font_primary_label)
        y += (bbox[3] - bbox[1]) + int(height * 0.01)

    # Change label with direction arrow
    if change_label:
        change_text = f"{arrow} {change_label}"
        draw.text((padding, y), change_text, font=font_change, fill=direction_rgb)
        bbox = draw.textbbox((padding, y), change_text, font=font_change)
        y += (bbox[3] - bbox[1]) + int(height * 0.03)

    # ── Divider ──
    draw.rectangle(
        [(padding, y), (width - padding, y + 2)],
        fill=accent_rgb,
    )
    y += int(height * 0.03)

    # ── Supporting Stats ──
    max_text_w = width - padding * 2
    for stat in (supporting_stats or [])[:4]:
        stat_lines = _wrap_text(stat, font_stat, draw, max_text_w)
        for line in stat_lines:
            draw.text((padding, y), line, font=font_stat, fill=_hex_to_rgb(colors["text_dark"]))
            bbox = draw.textbbox((padding, y), line, font=font_stat)
            y += (bbox[3] - bbox[1]) + int(height * 0.008)
        y += int(height * 0.01)

    # ── Bottom: Agent Identity Bar ──
    footer_h = int(height * 0.14)
    footer_y = height - footer_h
    draw.rectangle([(0, footer_y), (width, height)], fill=primary_rgb)

    # Thin accent line on top of footer
    draw.rectangle([(0, footer_y), (width, footer_y + accent_h)], fill=accent_rgb)

    # Agent initials circle (or headshot)
    circle_radius = int(footer_h * 0.3)
    circle_x = padding + circle_radius
    circle_y = footer_y + footer_h // 2

    if headshot_path and os.path.exists(headshot_path):
        try:
            headshot = Image.open(headshot_path).convert("RGB")
            hs_size = circle_radius * 2
            headshot = headshot.resize((hs_size, hs_size), Image.LANCZOS)

            # Create circular mask
            mask = Image.new("L", (hs_size, hs_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse([0, 0, hs_size, hs_size], fill=255)

            img.paste(headshot, (circle_x - circle_radius, circle_y - circle_radius), mask)
        except Exception:
            _draw_initials_circle(
                draw, circle_x, circle_y, circle_radius,
                _get_initials(agent_name), accent_rgb, _hex_to_rgb(colors["text_light"]),
            )
    else:
        _draw_initials_circle(
            draw, circle_x, circle_y, circle_radius,
            _get_initials(agent_name), accent_rgb, _hex_to_rgb(colors["text_light"]),
        )

    # Agent name + tagline (right of circle)
    text_x = circle_x + circle_radius + int(padding * 0.6)
    name_y = circle_y - int(circle_radius * 0.6)

    draw.text(
        (text_x, name_y),
        agent_name or "Your Agent",
        font=font_agent_name,
        fill=_hex_to_rgb(colors["text_light"]),
    )

    if agent_tagline:
        bbox = draw.textbbox((text_x, name_y), agent_name, font=font_agent_name)
        tagline_y = bbox[3] + int(height * 0.005)
        draw.text(
            (text_x, tagline_y),
            agent_tagline,
            font=font_tagline,
            fill=accent_rgb,
        )

    # ── Save / Return ──
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
    image_data: dict,
    market_area: str,
    agent_name: str,
    output_dir: str,
    agent_tagline: str = "",
    branding_colors: list[str] | None = None,
    headshot_path: str | None = None,
) -> dict[str, str]:
    """
    Render all image formats from a Content Pack's image_data.

    Args:
        image_data: The image_data dict from generate_daily_insight output
        market_area: Agent's market area
        agent_name: Agent's display name
        output_dir: Directory to save images
        agent_tagline: From profile brand.tagline
        branding_colors: [primary, accent] hex colors
        headshot_path: Path to agent headshot image

    Returns:
        Dict mapping format_name -> file_path
    """
    os.makedirs(output_dir, exist_ok=True)
    outputs = {}

    formats = {
        "feed_1080x1080": (1080, 1080),
        "story_1080x1920": (1080, 1920),
    }

    for fmt_name, (w, h) in formats.items():
        path = os.path.join(output_dir, f"{fmt_name}.jpg")
        render_card(
            primary_number=image_data.get("primary_number", ""),
            primary_label=image_data.get("primary_label", "Market Update"),
            primary_direction=image_data.get("primary_direction", "steady"),
            change_label=image_data.get("change_label", ""),
            supporting_stats=image_data.get("supporting_stats", []),
            market_area=market_area,
            agent_name=agent_name,
            agent_tagline=agent_tagline,
            width=w,
            height=h,
            branding_colors=branding_colors,
            headshot_path=headshot_path,
            output_path=path,
        )
        outputs[fmt_name] = path

    return outputs


# ─── Backward Compatibility ──────────────────────────────────────────────────
# v1 API: render_all_formats(headline, body, agent_name, output_dir, branding_colors)
# v2 uses image_data dict instead. This adapter maintains the old interface.


def render_all_formats_v1(
    headline: str,
    body: str,
    agent_name: str,
    output_dir: str,
    branding_colors: list[str] | None = None,
) -> dict[str, str]:
    """Backward-compatible v1 renderer."""
    image_data = {
        "primary_number": "",
        "primary_label": headline,
        "primary_direction": "steady",
        "change_label": "",
        "supporting_stats": [body] if body else [],
    }
    return render_all_formats(
        image_data=image_data,
        market_area="",
        agent_name=agent_name,
        output_dir=output_dir,
        branding_colors=branding_colors,
    )


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Render branded insight image")
    parser.add_argument("--primary-number", default="6.42%")
    parser.add_argument("--primary-label", default="30-Year Mortgage Rate")
    parser.add_argument("--direction", default="down", choices=["up", "down", "steady"])
    parser.add_argument("--change-label", default="down 12 bps from last week")
    parser.add_argument("--stats", nargs="+", default=[
        "412 Active Listings (+8%)",
        "Median Price: $385,000",
        "Avg Days on Market: 23",
    ])
    parser.add_argument("--market-area", default="Lehigh Valley, PA")
    parser.add_argument("--agent-name", default="Prita Chen")
    parser.add_argument("--agent-tagline", default="Your Lehigh Valley Real Estate Expert")
    parser.add_argument("--output", default="./test_output/insight_v2")
    parser.add_argument("--colors", nargs="+", default=["#1B2A4A", "#C9A96E"])
    parser.add_argument("--headshot", default=None)
    args = parser.parse_args()

    image_data = {
        "primary_number": args.primary_number,
        "primary_label": args.primary_label,
        "primary_direction": args.direction,
        "change_label": args.change_label,
        "supporting_stats": args.stats,
    }

    print(f"Rendering branded insight images to {args.output}/...")
    results = render_all_formats(
        image_data=image_data,
        market_area=args.market_area,
        agent_name=args.agent_name,
        output_dir=args.output,
        agent_tagline=args.agent_tagline,
        branding_colors=args.colors,
        headshot_path=args.headshot,
    )
    for fmt, path in results.items():
        print(f"  {fmt}: {path}")
