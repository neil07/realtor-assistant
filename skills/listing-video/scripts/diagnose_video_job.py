#!/usr/bin/env python3
"""
Diagnose one generated video job without reading raw logs.

Usage:
    python diagnose_video_job.py /path/to/job_output
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import video_diagnostics


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python diagnose_video_job.py <job_output_dir>")
        return 1

    job_dir = Path(sys.argv[1]).resolve()
    if not job_dir.exists():
        print(f"Job directory not found: {job_dir}")
        return 1

    doc = video_diagnostics.rebuild_report(str(job_dir))
    summary = doc.get("summary", {})

    print("Video Diagnostics")
    print(f"Job dir: {job_dir}")
    print(f"Scenes: {summary.get('scene_count', 0)}")
    print(f"Final audio present: {summary.get('final_has_audio')}")
    print("")
    print("Suspected causes:")
    for cause in summary.get("suspected_causes") or ["No issues detected"]:
        print(f"- {cause}")

    print("")
    print("Per-scene status:")
    for key in sorted(doc.get("scenes", {}).keys()):
        scene = doc["scenes"][key]
        render = scene.get("render", {})
        tts = scene.get("tts", {})
        assembly = scene.get("assembly", {})
        print(
            f"- Scene {key}: "
            f"render={render.get('status')}/{render.get('engine')} "
            f"fallback={render.get('fallback_used', False)} | "
            f"tts={tts.get('status')}/{tts.get('engine')} | "
            f"assembly={assembly.get('adjustment')}/{assembly.get('merge_status')}"
        )

    print("")
    print(f"Artifacts: {job_dir / 'diagnostics.json'}")
    print(f"Report: {job_dir / 'diagnostics_report.md'}")
    print("")
    print(json.dumps(doc.get("final", {}), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
