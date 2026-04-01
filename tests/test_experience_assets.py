import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "doc" / "prelaunch-experience" / "scenario-catalog.json"
PACKS_PATH = ROOT / "doc" / "prelaunch-experience" / "mock-output-packs.json"
CSV_PATH = ROOT / "doc" / "prelaunch-experience" / "scoring-template.csv"
SCRIPT_PATH = ROOT / "tools" / "run_dialogue_eval.py"


def test_scenario_catalog_has_required_coverage() -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    scenarios = data["scenarios"]

    assert len(data["personas"]) >= 5
    assert len(scenarios) >= 20

    init_scenarios = [s for s in scenarios if s["track"] == "initialization"]
    assert len(init_scenarios) >= 10

    live_scenarios = [s for s in scenarios if s["evaluation_mode"] == "live_dialogue"]
    assert live_scenarios, "Need live dialogue scenarios for real-service evaluation"

    activation_paths = {s["activation_path"] for s in scenarios}
    assert {"video_first", "insight_first", "interview_first"} <= activation_paths

    for scenario in live_scenarios:
        assert "user_message" in scenario
        assert "has_media" in scenario
        assert scenario["profile_state"] in {"new", "returning", "returning_with_delivered_job"}


def test_mock_output_packs_are_present_and_unique() -> None:
    data = json.loads(PACKS_PATH.read_text(encoding="utf-8"))
    all_ids = []

    for section in ("video_packs", "insight_packs", "task_plan_packs"):
        assert data[section], f"{section} should not be empty"
        all_ids.extend(pack["pack_id"] for pack in data[section])

    assert len(all_ids) == len(set(all_ids)), "Pack IDs must be unique"
    assert len(data["video_packs"]) >= 8
    assert len(data["insight_packs"]) >= 6
    assert len(data["task_plan_packs"]) >= 5


def test_scoring_template_has_new_initialization_fields() -> None:
    with CSV_PATH.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)

    required = {
        "entry_point",
        "first_action",
        "activation_path",
        "task_plan_type",
        "score_entry_clarity",
        "score_activation_fit",
        "score_trust_ramp",
        "score_task_framing",
    }
    assert required <= set(header)


def test_dialogue_eval_script_supports_dry_run() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--dry-run",
            "--limit",
            "2",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "DRY_RUN" in result.stdout
