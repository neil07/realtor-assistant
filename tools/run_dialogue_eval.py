#!/usr/bin/env python3
"""Run live dialogue-evaluation scenarios against Reel Agent's /api/message route.

This script is intentionally narrow:
- It loads the prelaunch scenario catalog
- It selects only scenarios marked `live_dialogue`
- It posts them to a real Reel Agent server
- It records the raw request/response pairs for later scoring

It does not score the results. Human review still decides whether a response
feels trustworthy, clear, and low-friction.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "doc" / "prelaunch-experience" / "scenario-catalog.json"


def load_catalog(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_phone_map(path: Path | None) -> dict[str, str]:
    if not path:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def select_scenarios(
    catalog: dict[str, Any],
    scenario_ids: set[str],
    tracks: set[str],
    live_only: bool,
    limit: int | None,
) -> list[dict[str, Any]]:
    scenarios = catalog.get("scenarios", [])
    selected: list[dict[str, Any]] = []

    for scenario in scenarios:
        if live_only and scenario.get("evaluation_mode") != "live_dialogue":
            continue
        if scenario_ids and scenario.get("scenario_id") not in scenario_ids:
            continue
        if tracks and scenario.get("track") not in tracks:
            continue
        selected.append(scenario)
        if limit is not None and len(selected) >= limit:
            break

    return selected


def generate_phone(index: int) -> str:
    suffix = str(index).zfill(7)
    return f"+1999{suffix}"


def resolve_phone(
    scenario: dict[str, Any],
    phone_map: dict[str, str],
    generated_index: int,
) -> str | None:
    phone_key = scenario.get("phone_key")
    profile_state = scenario.get("profile_state", "new")

    if phone_key and phone_key in phone_map:
        return phone_map[phone_key]
    if profile_state == "new":
        return generate_phone(generated_index)
    return None


def parse_response(response: httpx.Response) -> dict[str, Any]:
    try:
        return response.json()
    except Exception:
        return {"raw_text": response.text}


def build_payload(scenario: dict[str, Any], phone: str) -> dict[str, Any]:
    return {
        "agent_phone": phone,
        "text": scenario.get("user_message", ""),
        "has_media": bool(scenario.get("has_media", False)),
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def print_summary(results: list[dict[str, Any]]) -> None:
    for row in results:
        scenario_id = row["scenario_id"]
        status = row["status"]
        summary = row.get("summary", "")
        print(f"{scenario_id:18} {status:8} {summary}")


def run_live_eval(
    base_url: str,
    token: str,
    scenarios: list[dict[str, Any]],
    phone_map: dict[str, str],
    dry_run: bool,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    with httpx.Client(timeout=30) as client:
        for index, scenario in enumerate(scenarios, start=1):
            phone = resolve_phone(scenario, phone_map, index)
            if not phone:
                results.append(
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "scenario_id": scenario["scenario_id"],
                        "status": "SKIPPED",
                        "summary": "No phone available for non-new-user scenario",
                        "scenario": scenario,
                    }
                )
                continue

            payload = build_payload(scenario, phone)
            if dry_run:
                results.append(
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "scenario_id": scenario["scenario_id"],
                        "status": "DRY_RUN",
                        "summary": f"{payload['text'] or '[media only]'}",
                        "request": payload,
                        "scenario": scenario,
                    }
                )
                continue

            response = client.post(
                f"{base_url.rstrip('/')}/api/message",
                headers=headers,
                json=payload,
            )
            body = parse_response(response)
            summary = ""
            if isinstance(body, dict):
                intent = body.get("intent")
                action = body.get("action")
                if intent or action:
                    summary = f"{intent or '-'} / {action or '-'}"

            results.append(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "scenario_id": scenario["scenario_id"],
                    "status": "OK" if response.is_success else "ERROR",
                    "summary": summary or str(response.status_code),
                    "http_status": response.status_code,
                    "request": payload,
                    "response": body,
                    "scenario": scenario,
                }
            )

    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--token", default="", help="Bearer token for REEL_AGENT_TOKEN-protected routes")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--phone-map", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None, help="Write results as JSONL")
    parser.add_argument("--scenario", action="append", default=[], help="Scenario ID to run (repeatable)")
    parser.add_argument("--track", action="append", default=[], help="Track to run (repeatable)")
    parser.add_argument("--include-manual", action="store_true", help="Include manual_review scenarios in selection output")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Do not make HTTP requests")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    catalog = load_catalog(args.catalog)
    phone_map = load_phone_map(args.phone_map)
    scenario_ids = set(args.scenario)
    tracks = set(args.track)
    scenarios = select_scenarios(
        catalog,
        scenario_ids=scenario_ids,
        tracks=tracks,
        live_only=not args.include_manual,
        limit=args.limit,
    )

    if not scenarios:
        print("No scenarios selected.", file=sys.stderr)
        return 1

    results = run_live_eval(
        base_url=args.base_url,
        token=args.token,
        scenarios=scenarios,
        phone_map=phone_map,
        dry_run=args.dry_run,
    )

    if args.output:
        write_jsonl(args.output, results)

    print_summary(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
