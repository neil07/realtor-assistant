#!/usr/bin/env python3
"""
Reel Agent — Redfin Market Data Fetcher

Pulls local market statistics from the Redfin Data Center (free, public TSV).
Provides zip-code or metro-level data:
  - Median sale price + YoY change
  - Active inventory (homes for sale)
  - Median days on market
  - New listings count
  - Sale-to-list price ratio
  - Price drops percentage

Data updates weekly on Redfin; we cache locally with 12-hour TTL.

Usage (script mode):
  python redfin_data_fetcher.py --market-area "Lehigh Valley, PA"

Usage (tool mode):
  from redfin_data_fetcher import fetch_market_data
"""

import csv
import io
import json
import logging
import time
from datetime import datetime
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

# Redfin Data Center TSV download URL pattern
# region_type: 6 = metro/CBSA, 9 = zip code
# time_period: weekly data
REDFIN_BASE_URL = "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker"

# Known metro area name mappings (Redfin uses specific naming conventions)
# Add more as agents onboard from different markets
METRO_ALIASES: dict[str, str] = {
    "lehigh valley": "Allentown, PA metro area",
    "allentown": "Allentown, PA metro area",
    "bethlehem": "Allentown, PA metro area",
    "miami": "Miami, FL metro area",
    "los angeles": "Los Angeles, CA metro area",
    "new york": "New York, NY metro area",
    "chicago": "Chicago, IL metro area",
    "houston": "Houston, TX metro area",
    "phoenix": "Phoenix, AZ metro area",
    "san francisco": "San Francisco, CA metro area",
    "seattle": "Seattle, WA metro area",
    "denver": "Denver, CO metro area",
    "austin": "Austin, TX metro area",
    "dallas": "Dallas, TX metro area",
    "atlanta": "Atlanta, GA metro area",
    "boston": "Boston, MA metro area",
    "tampa": "Tampa, FL metro area",
    "nashville": "Nashville, TN metro area",
    "charlotte": "Charlotte, NC metro area",
    "san diego": "San Diego, CA metro area",
    "portland": "Portland, OR metro area",
    "raleigh": "Raleigh, NC metro area",
    "minneapolis": "Minneapolis, MN metro area",
    "san antonio": "San Antonio, TX metro area",
    "orlando": "Orlando, FL metro area",
}

CACHE_DIR = Path(__file__).parent.parent / "output" / "market_cache"
CACHE_TTL_SECONDS = 12 * 60 * 60  # 12 hours (Redfin updates weekly)

# ─── Cache Helpers ────────────────────────────────────────────────────────────


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
    return CACHE_DIR / f"redfin_{safe_key}.json"


def _read_cache(key: str) -> dict | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if time.time() - data.get("_cached_at", 0) > CACHE_TTL_SECONDS:
            return None
        return data
    except (json.JSONDecodeError, KeyError):
        return None


def _write_cache(key: str, data: dict) -> None:
    data["_cached_at"] = time.time()
    _cache_path(key).write_text(json.dumps(data, indent=2))


# ─── Redfin Data Parsing ─────────────────────────────────────────────────────


def _normalize_market_area(market_area: str) -> str:
    """Normalize market area to Redfin metro name."""
    lower = market_area.lower().strip()

    # Strip state suffixes for alias lookup
    for suffix in [", pa", ", fl", ", ca", ", ny", ", tx", ", il", ", az",
                   ", wa", ", co", ", ga", ", ma", ", nc", ", or", ", mn",
                   ", tn"]:
        lower_stripped = lower.replace(suffix, "").strip()
        if lower_stripped in METRO_ALIASES:
            return METRO_ALIASES[lower_stripped]

    # Direct lookup
    if lower in METRO_ALIASES:
        return METRO_ALIASES[lower]

    # Fallback: try as-is with " metro area" suffix
    # Redfin uses format "City, ST metro area"
    if "metro area" not in lower:
        return f"{market_area} metro area"

    return market_area


def _download_metro_tsv() -> str | None:
    """
    Download the latest Redfin metro-level weekly TSV.

    Returns TSV content as string, or None on failure.
    """
    # Check if we have a recent download cached
    cached_path = CACHE_DIR / "redfin_metro_weekly.tsv"
    if cached_path.exists():
        age = time.time() - cached_path.stat().st_mtime
        if age < CACHE_TTL_SECONDS:
            logger.debug("Using cached Redfin TSV (age: %.0f min)", age / 60)
            return cached_path.read_text()

    # Redfin public S3 bucket — metro-level weekly data
    url = f"{REDFIN_BASE_URL}/redfin_metro_market_tracker.tsv000.gz"

    try:
        resp = httpx.get(url, timeout=30, follow_redirects=True)
        resp.raise_for_status()

        # The file is gzipped
        import gzip
        content = gzip.decompress(resp.content).decode("utf-8")

        # Cache to disk
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cached_path.write_text(content)
        logger.info("Downloaded Redfin metro TSV (%d bytes)", len(content))
        return content

    except httpx.HTTPError as e:
        logger.error("Redfin download error: %s", e)
        return None
    except Exception as e:
        logger.error("Redfin parse error: %s", e)
        return None


def _parse_market_row(row: dict) -> dict:
    """Extract key metrics from a single Redfin TSV row."""

    def safe_float(val: str) -> float | None:
        try:
            return float(val) if val and val != "" else None
        except ValueError:
            return None

    def safe_int(val: str) -> int | None:
        try:
            return int(float(val)) if val and val != "" else None
        except ValueError:
            return None

    def safe_pct(val: str) -> float | None:
        """Parse percentage value (Redfin stores as decimal, e.g. 0.05 = 5%)."""
        v = safe_float(val)
        return round(v * 100, 1) if v is not None else None

    return {
        "period_begin": row.get("period_begin", ""),
        "period_end": row.get("period_end", ""),
        "region": row.get("region", ""),
        "median_sale_price": safe_float(row.get("median_sale_price", "")),
        "median_sale_price_yoy": safe_pct(row.get("median_sale_price_yoy", "")),
        "homes_sold": safe_int(row.get("homes_sold", "")),
        "inventory": safe_int(row.get("inventory", "")),
        "months_of_supply": safe_float(row.get("months_of_supply", "")),
        "new_listings": safe_int(row.get("new_listings", "")),
        "median_dom": safe_int(row.get("median_dom", "")),
        "avg_sale_to_list": safe_pct(row.get("avg_sale_to_list", "")),
        "price_drops": safe_pct(row.get("price_drops", "")),
        "median_ppsf": safe_float(row.get("median_ppsf", "")),
    }


# ─── Public API ───────────────────────────────────────────────────────────────


def fetch_market_data(market_area: str) -> dict:
    """
    Fetch local market statistics for a given area.

    Args:
        market_area: Agent's market area (e.g. "Lehigh Valley, PA")

    Returns:
        {
            "has_data": True,
            "source": "Redfin",
            "market_area": "Lehigh Valley, PA",
            "redfin_region": "Allentown, PA metro area",
            "current": { ...metrics... },
            "previous": { ...metrics... },
            "changes": {
                "inventory_change_pct": 8.2,
                "dom_change": -8,
                "median_price_change_pct": 3.1,
                ...
            },
            "notable_changes": ["inventory_up", "dom_down"],
            "summary_line": "412 active listings (+8%), $385K median, 23 days avg"
        }
    """
    cache_key = market_area.lower().replace(" ", "_").replace(",", "")
    cached = _read_cache(cache_key)
    if cached:
        logger.debug("Using cached Redfin data for %s", market_area)
        return cached

    redfin_name = _normalize_market_area(market_area)
    tsv_content = _download_metro_tsv()

    if not tsv_content:
        return {
            "has_data": False,
            "source": "Redfin",
            "market_area": market_area,
            "error": "download_failed",
        }

    # Parse TSV and find matching metro
    reader = csv.DictReader(io.StringIO(tsv_content), delimiter="\t")

    matching_rows = []
    for row in reader:
        region = row.get("region", "")
        if region.lower() == redfin_name.lower():
            matching_rows.append(row)

    if not matching_rows:
        logger.warning("No Redfin data found for '%s' (tried '%s')", market_area, redfin_name)
        return {
            "has_data": False,
            "source": "Redfin",
            "market_area": market_area,
            "redfin_region": redfin_name,
            "error": "region_not_found",
        }

    # Sort by period_end descending to get most recent first
    matching_rows.sort(key=lambda r: r.get("period_end", ""), reverse=True)

    current_row = _parse_market_row(matching_rows[0])
    previous_row = _parse_market_row(matching_rows[1]) if len(matching_rows) > 1 else None

    # Compute changes
    changes = {}
    notable = []

    if previous_row:
        # Inventory change
        if current_row["inventory"] and previous_row["inventory"] and previous_row["inventory"] > 0:
            inv_change = round(
                (current_row["inventory"] - previous_row["inventory"])
                / previous_row["inventory"] * 100, 1
            )
            changes["inventory_change_pct"] = inv_change
            if abs(inv_change) >= 5:
                notable.append("inventory_up" if inv_change > 0 else "inventory_down")

        # DOM change
        if current_row["median_dom"] is not None and previous_row["median_dom"] is not None:
            dom_diff = current_row["median_dom"] - previous_row["median_dom"]
            changes["dom_change"] = dom_diff
            if abs(dom_diff) >= 3:
                notable.append("dom_down" if dom_diff < 0 else "dom_up")

        # Median price change (already have YoY from Redfin, but compute WoW too)
        if current_row["median_sale_price"] and previous_row["median_sale_price"] and previous_row["median_sale_price"] > 0:
            price_change = round(
                (current_row["median_sale_price"] - previous_row["median_sale_price"])
                / previous_row["median_sale_price"] * 100, 1
            )
            changes["median_price_change_pct"] = price_change
            if abs(price_change) >= 2:
                notable.append("price_up" if price_change > 0 else "price_down")

    # Build summary line
    parts = []
    if current_row["inventory"] is not None:
        inv_str = f"{current_row['inventory']:,} active listings"
        if "inventory_change_pct" in changes:
            inv_str += f" ({changes['inventory_change_pct']:+.0f}%)"
        parts.append(inv_str)
    if current_row["median_sale_price"] is not None:
        parts.append(f"${current_row['median_sale_price']:,.0f} median")
    if current_row["median_dom"] is not None:
        parts.append(f"{current_row['median_dom']} days avg DOM")

    result = {
        "has_data": True,
        "source": "Redfin",
        "market_area": market_area,
        "redfin_region": redfin_name,
        "current": current_row,
        "previous": previous_row,
        "changes": changes,
        "notable_changes": notable,
        "summary_line": ", ".join(parts) if parts else "",
        "fetched_at": datetime.now().isoformat(),
    }

    _write_cache(cache_key, result)
    logger.info("Fetched Redfin data for %s: %s", market_area, result["summary_line"])
    return result


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fetch Redfin market data")
    parser.add_argument("--market-area", default="Lehigh Valley, PA")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    data = fetch_market_data(args.market_area)

    if data.get("has_data"):
        print(f"\nMarket Data: {data['market_area']} (via {data['redfin_region']})")
        print(f"  Period: {data['current']['period_begin']} to {data['current']['period_end']}")
        print(f"  Summary: {data['summary_line']}")

        c = data["current"]
        print(f"\n  Median Sale Price: ${c['median_sale_price']:,.0f}" if c["median_sale_price"] else "")
        if c.get("median_sale_price_yoy") is not None:
            print(f"    YoY Change: {c['median_sale_price_yoy']:+.1f}%")
        print(f"  Active Inventory: {c['inventory']:,}" if c["inventory"] else "")
        print(f"  Median DOM: {c['median_dom']} days" if c["median_dom"] is not None else "")
        print(f"  New Listings: {c['new_listings']:,}" if c["new_listings"] else "")
        if c.get("avg_sale_to_list") is not None:
            print(f"  Sale-to-List: {c['avg_sale_to_list']:.1f}%")
        if c.get("price_drops") is not None:
            print(f"  Price Drops: {c['price_drops']:.1f}%")

        if data["notable_changes"]:
            print(f"\n  Notable Changes: {', '.join(data['notable_changes'])}")
    else:
        print(f"No data available for {data['market_area']}")
        if data.get("error") == "region_not_found":
            print(f"  Tried Redfin region: {data.get('redfin_region', 'unknown')}")
            print("  Try a major metro area name (e.g. 'Miami', 'Los Angeles')")
