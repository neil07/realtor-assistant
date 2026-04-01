#!/usr/bin/env python3
"""
Reel Agent — Market Data Fetcher

Pulls real-time market data from free public APIs:
  - FRED API: 30-year and 15-year mortgage rates (weekly, Thursday)
  - Designed for daily_scheduler to call before generating insights

Data is cached locally (JSON) to avoid redundant API calls.
Cache TTL: 6 hours (rates update weekly, but we check daily).

Usage (script mode):
  python market_data_fetcher.py --market-area "Lehigh Valley, PA"

Usage (tool mode):
  from market_data_fetcher import fetch_rates, fetch_all
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")  # Free at https://fred.stlouisfed.org/docs/api/api_key.html

# FRED series IDs
SERIES_30YR = "MORTGAGE30US"  # 30-Year Fixed Rate Mortgage Average
SERIES_15YR = "MORTGAGE15US"  # 15-Year Fixed Rate Mortgage Average

CACHE_DIR = Path(__file__).parent.parent / "output" / "market_cache"
CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours

# ─── Cache Helpers ────────────────────────────────────────────────────────────


def _cache_path(key: str) -> Path:
    """Return path for a cached data file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.json"


def _read_cache(key: str) -> dict | None:
    """Read cached data if it exists and hasn't expired."""
    path = _cache_path(key)
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text())
        cached_at = data.get("_cached_at", 0)
        if time.time() - cached_at > CACHE_TTL_SECONDS:
            logger.debug("Cache expired for %s", key)
            return None
        return data
    except (json.JSONDecodeError, KeyError):
        return None


def _write_cache(key: str, data: dict) -> None:
    """Write data to cache with timestamp."""
    data["_cached_at"] = time.time()
    _cache_path(key).write_text(json.dumps(data, indent=2))


# ─── FRED API ─────────────────────────────────────────────────────────────────


def _fetch_fred_series(series_id: str, limit: int = 4) -> list[dict]:
    """
    Fetch recent observations from FRED.

    Args:
        series_id: FRED series ID (e.g. MORTGAGE30US)
        limit: Number of recent observations to fetch

    Returns:
        List of {date, value} dicts, most recent first.
    """
    if not FRED_API_KEY:
        logger.warning("FRED_API_KEY not set — cannot fetch rate data")
        return []

    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }

    try:
        resp = httpx.get(FRED_BASE_URL, params=params, timeout=15)
        resp.raise_for_status()
        observations = resp.json().get("observations", [])

        results = []
        for obs in observations:
            if obs.get("value", ".") == ".":
                continue  # FRED uses "." for missing data
            results.append({
                "date": obs["date"],
                "value": float(obs["value"]),
            })
        return results

    except httpx.HTTPError as e:
        logger.error("FRED API error for %s: %s", series_id, e)
        return []
    except (KeyError, ValueError) as e:
        logger.error("FRED parse error for %s: %s", series_id, e)
        return []


def fetch_rates() -> dict:
    """
    Fetch current mortgage rates with week-over-week change.

    Returns:
        {
            "rate_30yr": 6.42,
            "rate_15yr": 5.68,
            "rate_30yr_prev": 6.54,
            "rate_15yr_prev": 5.73,
            "change_30yr_bps": -12,   # basis points
            "change_15yr_bps": -5,
            "rate_date": "2026-03-27",
            "has_data": True,
            "source": "FRED"
        }
    """
    # Check cache first
    cached = _read_cache("mortgage_rates")
    if cached:
        logger.debug("Using cached mortgage rate data")
        return cached

    data_30 = _fetch_fred_series(SERIES_30YR, limit=4)
    data_15 = _fetch_fred_series(SERIES_15YR, limit=4)

    if not data_30:
        return {"has_data": False, "source": "FRED", "error": "no_data"}

    result = {
        "has_data": True,
        "source": "FRED",
        "rate_date": data_30[0]["date"],
        "fetched_at": datetime.now().isoformat(),
        # 30-year rates
        "rate_30yr": data_30[0]["value"],
        "rate_30yr_prev": data_30[1]["value"] if len(data_30) > 1 else None,
        "change_30yr_bps": None,
        # 15-year rates
        "rate_15yr": data_15[0]["value"] if data_15 else None,
        "rate_15yr_prev": data_15[1]["value"] if len(data_15) > 1 else None,
        "change_15yr_bps": None,
    }

    # Calculate basis point changes
    if result["rate_30yr_prev"] is not None:
        result["change_30yr_bps"] = round(
            (result["rate_30yr"] - result["rate_30yr_prev"]) * 100
        )

    if result["rate_15yr"] is not None and result["rate_15yr_prev"] is not None:
        result["change_15yr_bps"] = round(
            (result["rate_15yr"] - result["rate_15yr_prev"]) * 100
        )

    _write_cache("mortgage_rates", result)
    logger.info(
        "Fetched mortgage rates: 30yr=%.2f%% (%+dbps), date=%s",
        result["rate_30yr"],
        result.get("change_30yr_bps", 0) or 0,
        result["rate_date"],
    )
    return result


def estimate_monthly_payment(
    home_price: float,
    rate_pct: float,
    down_payment_pct: float = 20.0,
    term_years: int = 30,
) -> float:
    """
    Estimate monthly mortgage payment (principal + interest only).

    Args:
        home_price: Home price in dollars
        rate_pct: Annual interest rate as percentage (e.g. 6.42)
        down_payment_pct: Down payment percentage (default 20%)
        term_years: Loan term in years (default 30)

    Returns:
        Monthly payment in dollars.
    """
    loan = home_price * (1 - down_payment_pct / 100)
    monthly_rate = rate_pct / 100 / 12
    n_payments = term_years * 12

    if monthly_rate == 0:
        return loan / n_payments

    payment = loan * (monthly_rate * (1 + monthly_rate) ** n_payments) / (
        (1 + monthly_rate) ** n_payments - 1
    )
    return round(payment, 2)


def compute_payment_impact(
    rate_data: dict,
    home_price: float = 400_000,
) -> dict:
    """
    Compute the monthly payment impact of a rate change.

    Returns:
        {
            "home_price": 400000,
            "payment_current": 1987.42,
            "payment_previous": 2034.56,
            "payment_diff": -47.14,
            "payment_diff_label": "$47/month less"
        }
    """
    if not rate_data.get("has_data") or rate_data.get("rate_30yr_prev") is None:
        return {"home_price": home_price, "has_impact": False}

    current = estimate_monthly_payment(home_price, rate_data["rate_30yr"])
    previous = estimate_monthly_payment(home_price, rate_data["rate_30yr_prev"])
    diff = round(current - previous, 2)

    abs_diff = abs(diff)
    if diff < 0:
        label = f"${abs_diff:.0f}/month less"
    elif diff > 0:
        label = f"${abs_diff:.0f}/month more"
    else:
        label = "no change"

    return {
        "home_price": home_price,
        "has_impact": True,
        "payment_current": current,
        "payment_previous": previous,
        "payment_diff": diff,
        "payment_diff_label": label,
    }


# ─── Aggregate Fetch ──────────────────────────────────────────────────────────


def fetch_all(market_area: str = "") -> dict:
    """
    Fetch all available market data for a given area.

    Args:
        market_area: Geographic area (used for Redfin in Phase 2)

    Returns:
        {
            "rates": { ... },           # from fetch_rates()
            "payment_impact": { ... },  # from compute_payment_impact()
            "market_area": "...",
            "fetched_at": "..."
        }
    """
    rates = fetch_rates()
    impact = compute_payment_impact(rates) if rates.get("has_data") else {}

    return {
        "rates": rates,
        "payment_impact": impact,
        "market_area": market_area,
        "fetched_at": datetime.now().isoformat(),
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

    parser = argparse.ArgumentParser(description="Fetch market data")
    parser.add_argument("--market-area", default="Lehigh Valley, PA")
    parser.add_argument("--home-price", type=float, default=400_000)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    data = fetch_all(market_area=args.market_area)
    rates = data["rates"]

    if rates.get("has_data"):
        print(f"\nMortgage Rates (as of {rates['rate_date']}):")
        print(f"  30-year: {rates['rate_30yr']:.2f}%", end="")
        if rates.get("change_30yr_bps") is not None:
            print(f"  ({rates['change_30yr_bps']:+d} bps WoW)")
        else:
            print()

        if rates.get("rate_15yr"):
            print(f"  15-year: {rates['rate_15yr']:.2f}%", end="")
            if rates.get("change_15yr_bps") is not None:
                print(f"  ({rates['change_15yr_bps']:+d} bps WoW)")
            else:
                print()

        impact = data["payment_impact"]
        if impact.get("has_impact"):
            print(f"\n  Payment Impact (${args.home_price:,.0f} home, 20% down):")
            print(f"    Current: ${impact['payment_current']:,.2f}/mo")
            print(f"    Previous: ${impact['payment_previous']:,.2f}/mo")
            print(f"    Change: {impact['payment_diff_label']}")
    else:
        print("No rate data available. Check FRED_API_KEY in .env")
