#!/usr/bin/env python3
"""
Reel Agent — Daily Content Scheduler

Runs as a background asyncio task inside FastAPI's lifespan.
Every day at the configured UTC hour, generates and pushes
market insight content to all active agents.

Usage (started automatically by server.py lifespan):
  scheduler = DailyScheduler(notifier, scripts_dir)
  asyncio.create_task(scheduler.run_forever())

Usage (manual trigger via API):
  await scheduler.run_once()
"""

import asyncio
import logging
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestrator.progress_notifier import ProgressNotifier

logger = logging.getLogger(__name__)

# Default: 13:00 UTC = 8:00 AM US Eastern (EST) / 9:00 AM EDT
DEFAULT_TRIGGER_HOUR_UTC = int(os.environ.get("DAILY_INSIGHT_HOUR_UTC", "13"))

SCRIPTS_DIR = Path(__file__).parent.parent / "skills" / "listing-video" / "scripts"


class DailyScheduler:
    """
    Manages the daily content generation cycle.

    Each cycle:
    1. Load all active agents (last interaction within 7 days)
    2. For each agent: generate insight + render images
    3. Push via notifier (OpenClaw callback → WhatsApp)
    """

    def __init__(
        self,
        notifier: "ProgressNotifier",
        trigger_hour_utc: int = DEFAULT_TRIGGER_HOUR_UTC,
    ):
        self.notifier = notifier
        self.trigger_hour_utc = trigger_hour_utc
        self._last_run_date: str | None = None  # "YYYY-MM-DD" of last run

        # Add scripts to path for local imports
        sys.path.insert(0, str(SCRIPTS_DIR))

    async def run_forever(self) -> None:
        """
        Long-running loop. Sleeps until the next trigger time,
        then calls run_once(). Restarts automatically after errors.
        """
        logger.info("DailyScheduler started (trigger hour UTC: %d)", self.trigger_hour_utc)

        while True:
            try:
                seconds_until = self._seconds_until_next_trigger()
                logger.info(
                    "DailyScheduler: next run in %.0f minutes",
                    seconds_until / 60,
                )
                await asyncio.sleep(seconds_until)
                await self.run_once()
            except asyncio.CancelledError:
                logger.info("DailyScheduler cancelled, stopping.")
                return
            except Exception as exc:
                logger.error("DailyScheduler error: %s", exc, exc_info=True)
                # Wait 10 minutes before retrying on unexpected error
                await asyncio.sleep(600)

    async def run_once(self) -> dict:
        """
        Execute one daily content cycle for all active agents.

        Returns:
            Summary dict: {agents_processed, success, failed, skipped}
        """
        today = datetime.now(UTC).strftime("%Y-%m-%d")

        # Guard against duplicate runs on the same day
        if self._last_run_date == today:
            logger.info("DailyScheduler: already ran today (%s), skipping.", today)
            return {"agents_processed": 0, "success": 0, "failed": 0, "skipped": 1}

        logger.info("DailyScheduler: starting daily run for %s", today)
        self._last_run_date = today

        import profile_manager

        active_agents = await asyncio.to_thread(profile_manager.get_active_agents, 7)
        logger.info("DailyScheduler: %d active agents", len(active_agents))

        # Filter eligible agents
        eligible = []
        results = {"agents_processed": len(active_agents), "success": 0, "failed": 0, "skipped": 0}

        for agent in active_agents:
            phone = agent.get("phone", "")
            if not phone:
                results["skipped"] += 1
                continue
            if not agent.get("content_preferences", {}).get("daily_push_enabled", True):
                results["skipped"] += 1
                continue
            eligible.append(agent)

        if not eligible:
            logger.info("DailyScheduler: no eligible agents, done.")
            return results

        # Fetch shared data once (rates + Redfin per unique market area)
        market_areas = [
            a.get("content_preferences", {}).get("market_area")
            or a.get("city", "your area")
            for a in eligible
        ]
        try:
            shared_data = await self._fetch_shared_data(market_areas)
            logger.info(
                "DailyScheduler: data fetched — rates=%s, markets=%d",
                "yes" if shared_data["rates"].get("has_data") else "no",
                sum(1 for v in shared_data["market"].values() if v.get("has_data")),
            )
        except Exception as exc:
            logger.error("DailyScheduler: data fetch failed: %s", exc)
            shared_data = {"rates": {"has_data": False}, "payment_impact": {}, "market": {}}

        # Generate and push for each agent
        for agent in eligible:
            phone = agent["phone"]
            try:
                await self._generate_and_push(agent, shared_data)
                results["success"] += 1
                logger.info("DailyScheduler: pushed Content Pack to %s", phone)
            except Exception as exc:
                results["failed"] += 1
                logger.error("DailyScheduler: failed for %s: %s", phone, exc)

        logger.info("DailyScheduler: run complete %s", results)
        return results

    async def _fetch_shared_data(self, market_areas: list[str]) -> dict:
        """
        Fetch market data shared across all agents (rates are global,
        Redfin data is per-market). Called once per daily cycle.

        Returns:
            {
                "rates": { ... },
                "payment_impact": { ... },
                "market": { "area_name": { ... }, ... }
            }
        """
        import market_data_fetcher
        import redfin_data_fetcher

        # Rates are global — fetch once
        rate_data = await asyncio.to_thread(market_data_fetcher.fetch_rates)
        payment_impact = {}
        if rate_data.get("has_data"):
            payment_impact = market_data_fetcher.compute_payment_impact(rate_data)

        # Redfin data is per-market — deduplicate across agents
        unique_areas = list(set(market_areas))
        market_cache: dict[str, dict] = {}
        for area in unique_areas:
            try:
                data = await asyncio.to_thread(
                    redfin_data_fetcher.fetch_market_data, area,
                )
                market_cache[area] = data
            except Exception as exc:
                logger.warning("Failed to fetch Redfin data for %s: %s", area, exc)
                market_cache[area] = {"has_data": False, "error": str(exc)}

        return {
            "rates": rate_data,
            "payment_impact": payment_impact,
            "market": market_cache,
        }

    async def _generate_and_push(self, agent: dict, shared_data: dict) -> None:
        """Generate Content Pack + render branded images + push to agent."""
        import generate_daily_insight
        import render_insight_image

        phone = agent["phone"]
        name = agent.get("name", "")
        content_prefs = agent.get("content_preferences", {})
        market_area = content_prefs.get("market_area") or agent.get("city", "your area")
        branding_colors = content_prefs.get("branding_colors")
        brand = agent.get("brand", {})
        agent_tagline = brand.get("tagline", "")
        headshot_path = agent.get("headshot_path")

        # Get this agent's market data from shared cache
        market_data = shared_data.get("market", {}).get(market_area, {})

        # 1. Generate Content Pack (data-driven, agent's voice)
        content_pack = await asyncio.to_thread(
            generate_daily_insight.generate,
            rate_data=shared_data.get("rates"),
            market_data=market_data,
            payment_impact=shared_data.get("payment_impact"),
            agent_profile=agent,
        )

        # 2. Render branded image cards from Content Pack's image_data
        output_dir = str(
            Path(__file__).parent.parent
            / "skills" / "listing-video" / "output"
            / f"daily_{phone.replace('+', '')}_{date.today().isoformat()}"
        )
        image_data = content_pack.get("image_data", {})
        image_paths = await asyncio.to_thread(
            render_insight_image.render_all_formats,
            image_data=image_data,
            market_area=market_area,
            agent_name=name,
            output_dir=output_dir,
            agent_tagline=agent_tagline,
            branding_colors=branding_colors,
            headshot_path=headshot_path,
        )

        # 3. Push full Content Pack via notifier
        await self.notifier.notify_daily_insight(
            agent_phone=phone,
            insight=content_pack,
            image_paths=image_paths,
            agent=agent,
        )

    def _seconds_until_next_trigger(self) -> float:
        """Calculate seconds until next trigger time (same or next day)."""
        now = datetime.now(UTC)
        target = now.replace(
            hour=self.trigger_hour_utc, minute=0, second=0, microsecond=0
        )
        if target <= now:
            # Already past today's trigger time → aim for tomorrow
            target += timedelta(days=1)
        return (target - now).total_seconds()
