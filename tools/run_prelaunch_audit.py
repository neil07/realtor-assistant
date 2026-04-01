#!/usr/bin/env python3
"""Run the prelaunch experience audit evidence collection workflow.

This script is intentionally scoped to Reel Agent surfaces we control:
- baseline pytest evidence
- live /api/message routing evidence
- targeted natural-language probes

It assumes the local Reel Agent server is already running.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "skills" / "listing-video" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import profile_manager

CATALOG_PATH = ROOT / "doc" / "prelaunch-experience" / "scenario-catalog.json"
DEFAULT_OUTPUT_DIR = ROOT / "doc" / "prelaunch-experience" / "evidence" / datetime.now().date().isoformat()

PHONE_MAP = {
    "new_user_referral": "+15550001001",
    "new_user_natural": "+15550001002",
    "returning_user_basic": "+15550001003",
    "returning_user_with_delivered_job": "+15550001004",
    "returning_user_with_insight": "+15550001005",
}

RETURNING_PROFILES = {
    "returning_user_basic": {
        "name": "Natalie Audit",
        "city": "Austin",
        "market_area": "Austin",
        "style": "professional",
        "language": "en",
    },
    "returning_user_with_delivered_job": {
        "name": "Avery Delivery",
        "city": "Austin",
        "market_area": "Austin",
        "style": "professional",
        "language": "en",
    },
    "returning_user_with_insight": {
        "name": "Casey Insight",
        "city": "Austin",
        "market_area": "Austin",
        "style": "professional",
        "language": "en",
    },
}

TARGETED_PROBES = [
    {
        "probe_id": "PROBE-APP-01",
        "phone_key": "new_user_referral",
        "text": "Is this an app? How do I use this?",
        "has_media": False,
        "note": "trust/setup confusion",
    },
    {
        "probe_id": "PROBE-PRICE-01",
        "phone_key": "new_user_natural",
        "text": "How much per month?",
        "has_media": False,
        "note": "pricing sensitivity",
    },
    {
        "probe_id": "PROBE-TRUST-01",
        "phone_key": "new_user_referral",
        "text": "How do I know this is secure and not spam?",
        "has_media": False,
        "note": "security trust question",
    },
    {
        "probe_id": "PROBE-FIRSTSTEP-01",
        "phone_key": "new_user_natural",
        "text": "I do not know these tools, tell me the first step",
        "has_media": False,
        "note": "needs starter task framing",
    },
    {
        "probe_id": "PROBE-INSIGHTFIRST-01",
        "phone_key": "new_user_natural",
        "text": "I do not have a listing today but I want daily content",
        "has_media": False,
        "note": "insight-first natural phrasing",
    },
    {
        "probe_id": "PROBE-INSIGHT-REFINE-01",
        "phone_key": "returning_user_with_insight",
        "text": "shorter",
        "has_media": False,
        "note": "post-insight refinement",
    },
    {
        "probe_id": "PROBE-POST-DELIVERY-01",
        "phone_key": "returning_user_with_delivered_job",
        "text": "more professional",
        "has_media": False,
        "note": "style keyword after delivery",
    },
    {
        "probe_id": "PROBE-POST-DELIVERY-02",
        "phone_key": "returning_user_with_delivered_job",
        "text": "make it more professional",
        "has_media": False,
        "note": "natural revision phrasing after delivery",
    },
]

BASELINE_TESTS = [
    {
        "test_id": "assets",
        "cmd": [".venv/bin/python", "-m", "pytest", "tests/test_experience_assets.py", "-q"],
    },
    {
        "test_id": "routing_and_bridge",
        "cmd": [
            ".venv/bin/python",
            "-m",
            "pytest",
            "tests/test_message_routing.py",
            "tests/test_openclaw_mock_integration.py",
            "-q",
        ],
    },
]


@dataclass
class HttpRow:
    kind: str
    scenario_id: str
    phone_key: str
    phone: str
    profile_state: str
    text: str
    has_media: bool
    status: str
    http_status: int
    intent: str
    action: str
    awaiting: str
    response: str
    text_commands: str
    note: str
    timestamp: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=os.getenv("REEL_AGENT_TOKEN", ""))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    return parser.parse_args()


def ensure_profiles() -> dict[str, str]:
    phone_map = dict(PHONE_MAP)
    for key, payload in RETURNING_PROFILES.items():
        phone = phone_map[key]
        existing = profile_manager.get_profile(phone)
        if existing is None:
            profile_manager.create_profile(
                phone=phone,
                name=payload["name"],
                city=payload["city"],
                market_area=payload["market_area"],
                style=payload["style"],
                language=payload["language"],
            )
    return phone_map


def write_bridge_state(output_dir: Path, phone_map: dict[str, str]) -> Path:
    path = output_dir / "bridge-state.json"
    payload = {
        "agents": {
            phone_map["returning_user_with_delivered_job"]: {
                "agentPhone": phone_map["returning_user_with_delivered_job"],
                "lastDelivery": {
                    "jobId": "audit-delivered-job",
                    "updatedAt": "2026-04-01T03:30:00+00:00",
                },
            },
            phone_map["returning_user_with_insight"]: {
                "agentPhone": phone_map["returning_user_with_insight"],
                "lastDailyInsight": {
                    "headline": "Inventory is tightening",
                    "updatedAt": "2026-04-01T03:00:00+00:00",
                },
            },
        }
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_phone_map(output_dir: Path, phone_map: dict[str, str]) -> Path:
    path = output_dir / "phone-map.json"
    path.write_text(json.dumps(phone_map, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_baseline_tests(output_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for test in BASELINE_TESTS:
        proc = subprocess.run(
            test["cmd"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        row = {
            "test_id": test["test_id"],
            "cmd": test["cmd"],
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        results.append(row)

    path = output_dir / "baseline-tests.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def load_live_scenarios(catalog_path: Path) -> list[dict[str, Any]]:
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    return [s for s in data["scenarios"] if s.get("evaluation_mode") == "live_dialogue"]


def call_api(
    client: httpx.Client,
    base_url: str,
    token: str,
    phone: str,
    text: str,
    has_media: bool,
) -> tuple[int, dict[str, Any]]:
    response = client.post(
        f"{base_url.rstrip('/')}/api/message",
        headers={"Authorization": f"Bearer {token}"},
        json={"agent_phone": phone, "text": text, "has_media": has_media},
    )
    try:
        body = response.json()
    except Exception:
        body = {"raw_text": response.text}
    return response.status_code, body


def normalize_http_row(
    *,
    kind: str,
    scenario_id: str,
    phone_key: str,
    phone: str,
    profile_state: str,
    text: str,
    has_media: bool,
    note: str,
    http_status: int,
    body: dict[str, Any],
) -> HttpRow:
    return HttpRow(
        kind=kind,
        scenario_id=scenario_id,
        phone_key=phone_key,
        phone=phone,
        profile_state=profile_state,
        text=text,
        has_media=has_media,
        status="OK" if 200 <= http_status < 300 else "ERROR",
        http_status=http_status,
        intent=str(body.get("intent", "")),
        action=str(body.get("action", "")),
        awaiting=str(body.get("awaiting", "")),
        response=str(body.get("response", "")),
        text_commands=json.dumps(body.get("text_commands", {}), ensure_ascii=False),
        note=note,
        timestamp=datetime.now(UTC).isoformat(),
    )


def run_http_evidence(
    *,
    base_url: str,
    token: str,
    phone_map: dict[str, str],
    catalog_path: Path,
) -> tuple[list[dict[str, Any]], list[HttpRow]]:
    live_rows: list[dict[str, Any]] = []
    summary_rows: list[HttpRow] = []

    with httpx.Client(timeout=30) as client:
        for scenario in load_live_scenarios(catalog_path):
            phone_key = scenario["phone_key"]
            phone = phone_map[phone_key]
            http_status, body = call_api(
                client=client,
                base_url=base_url,
                token=token,
                phone=phone,
                text=scenario.get("user_message", ""),
                has_media=bool(scenario.get("has_media", False)),
            )
            live_rows.append(
                {
                    "kind": "live_dialogue",
                    "scenario_id": scenario["scenario_id"],
                    "scenario": scenario,
                    "request": {
                        "agent_phone": phone,
                        "text": scenario.get("user_message", ""),
                        "has_media": bool(scenario.get("has_media", False)),
                    },
                    "http_status": http_status,
                    "response": body,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            summary_rows.append(
                normalize_http_row(
                    kind="live_dialogue",
                    scenario_id=scenario["scenario_id"],
                    phone_key=phone_key,
                    phone=phone,
                    profile_state=scenario.get("profile_state", ""),
                    text=scenario.get("user_message", ""),
                    has_media=bool(scenario.get("has_media", False)),
                    note=scenario.get("title", ""),
                    http_status=http_status,
                    body=body,
                )
            )

        for probe in TARGETED_PROBES:
            phone_key = probe["phone_key"]
            phone = phone_map[phone_key]
            http_status, body = call_api(
                client=client,
                base_url=base_url,
                token=token,
                phone=phone,
                text=probe["text"],
                has_media=bool(probe["has_media"]),
            )
            live_rows.append(
                {
                    "kind": "targeted_probe",
                    "scenario_id": probe["probe_id"],
                    "probe": probe,
                    "request": {
                        "agent_phone": phone,
                        "text": probe["text"],
                        "has_media": bool(probe["has_media"]),
                    },
                    "http_status": http_status,
                    "response": body,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            summary_rows.append(
                normalize_http_row(
                    kind="targeted_probe",
                    scenario_id=probe["probe_id"],
                    phone_key=phone_key,
                    phone=phone,
                    profile_state="returning" if phone_key.startswith("returning_") else "new",
                    text=probe["text"],
                    has_media=bool(probe["has_media"]),
                    note=probe["note"],
                    http_status=http_status,
                    body=body,
                )
            )

    return live_rows, summary_rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_summary_csv(path: Path, rows: list[HttpRow]) -> None:
    fieldnames = list(asdict(rows[0]).keys()) if rows else list(HttpRow.__annotations__.keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_summary_markdown(path: Path, rows: list[HttpRow]) -> None:
    lines = [
        "# HTTP Summary",
        "",
        "| kind | scenario_id | intent | action | awaiting | note |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row.kind} | {row.scenario_id} | {row.intent or '-'} | "
            f"{row.action or '-'} | {row.awaiting or '-'} | {row.note} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    if not args.token:
        print("REEL_AGENT_TOKEN is required.", file=sys.stderr)
        return 1

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    phone_map = ensure_profiles()
    write_phone_map(output_dir, phone_map)
    write_bridge_state(output_dir, phone_map)
    run_baseline_tests(output_dir)

    live_rows, summary_rows = run_http_evidence(
        base_url=args.base_url,
        token=args.token,
        phone_map=phone_map,
        catalog_path=args.catalog,
    )

    write_jsonl(output_dir / "http-evidence.jsonl", live_rows)
    write_summary_csv(output_dir / "http-summary.csv", summary_rows)
    write_summary_markdown(output_dir / "http-summary.md", summary_rows)

    print(f"Wrote audit evidence to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
