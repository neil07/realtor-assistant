#!/usr/bin/env python3
"""
Lightweight video motion metrics using OpenCV optical flow.

Replaces VBench's dynamic_degree + motion_smoothness with a CPU-only
implementation that requires only opencv-python + numpy (~50MB vs ~4GB).

Core logic mirrors VBench:
  - dynamic_degree: Farneback optical flow → top-5% magnitude > threshold
  - motion_smoothness: Linear frame interpolation error → normalized 0-1
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def compute_motion_metrics(
    video_path: str,
    target_fps: float = 8.0,
    max_dimension: int = 512,
) -> dict:
    """Compute dynamic_degree and motion_smoothness for a single video.

    Args:
        video_path: Path to .mp4 video file.
        target_fps: Subsample to this FPS before analysis.
        max_dimension: Resize frames to this max side length for speed.

    Returns:
        Dict with keys:
            dynamic_degree: float 0-1 (1 = lots of motion, 0 = static/PPT)
            motion_smoothness: float 0-1 (1 = perfectly smooth, 0 = jerky)
            mean_flow_magnitude: float (raw average optical flow)
            flow_variance: float (variance across frames)
            frame_count: int (frames analyzed)
    """
    if not Path(video_path).exists():
        logger.warning("Video not found: %s", video_path)
        return _empty_result()

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.warning("Cannot open video: %s", video_path)
        return _empty_result()

    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    interval = max(1, round(fps / target_fps))

    # Extract grayscale frames at target FPS
    frames_gray = []
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % interval == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape
            if max(h, w) > max_dimension:
                scale = max_dimension / max(h, w)
                gray = cv2.resize(gray, (int(w * scale), int(h * scale)))
            frames_gray.append(gray)
        frame_idx += 1
    cap.release()

    if len(frames_gray) < 2:
        return _empty_result(frame_count=len(frames_gray))

    # Dense optical flow (Farneback) between consecutive frames
    flow_magnitudes = []
    for i in range(len(frames_gray) - 1):
        flow = cv2.calcOpticalFlowFarneback(
            frames_gray[i], frames_gray[i + 1],
            None,
            pyr_scale=0.5,
            levels=3,
            winsize=15,
            iterations=3,
            poly_n=5,
            poly_sigma=1.2,
            flags=0,
        )
        mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
        # Top 5% mean magnitude (same as VBench dynamic_degree)
        flat = mag.flatten()
        top_k = max(1, int(len(flat) * 0.05))
        top5_mean = float(np.mean(np.partition(flat, -top_k)[-top_k:]))
        flow_magnitudes.append(top5_mean)

    flow_magnitudes = np.array(flow_magnitudes)

    # --- Dynamic Degree ---
    # VBench logic: threshold scaled by resolution, count frames exceeding it
    h, w = frames_gray[0].shape
    scale = min(h, w)
    threshold = 6.0 * (scale / 256.0)
    count_threshold = max(1, round(4 * (len(frames_gray) / 16.0)))
    dynamic_count = int(np.sum(flow_magnitudes > threshold))
    dynamic_degree = float(np.clip(dynamic_count / max(1, len(flow_magnitudes)), 0, 1))

    # --- Motion Smoothness ---
    # Low variance in flow magnitude changes = smooth motion
    if len(flow_magnitudes) >= 2:
        diffs = np.abs(np.diff(flow_magnitudes))
        mean_diff = float(np.mean(diffs))
        # Map to 0-1 (empirical: diff > 10 is very jerky)
        motion_smoothness = float(np.clip(1.0 - (mean_diff / 10.0), 0, 1))
    else:
        motion_smoothness = 1.0

    return {
        "dynamic_degree": round(dynamic_degree, 3),
        "motion_smoothness": round(motion_smoothness, 3),
        "mean_flow_magnitude": round(float(np.mean(flow_magnitudes)), 3),
        "flow_variance": round(float(np.var(flow_magnitudes)), 3),
        "frame_count": len(frames_gray),
    }


def _empty_result(frame_count: int = 0) -> dict:
    return {
        "dynamic_degree": 0.0,
        "motion_smoothness": 1.0,
        "mean_flow_magnitude": 0.0,
        "flow_variance": 0.0,
        "frame_count": frame_count,
    }


def interpret_motion(metrics: dict) -> dict:
    """Produce human-readable labels from raw motion metrics.

    Returns:
        Dict with keys:
            dynamic_label: str ("static"/"low"/"moderate"/"high")
            smoothness_label: str ("jerky"/"rough"/"smooth"/"very_smooth")
            issues: list[str] (PM-friendly issue descriptions)
    """
    dd = metrics.get("dynamic_degree", 0)
    ms = metrics.get("motion_smoothness", 1)

    if dd < 0.15:
        dynamic_label = "static"
    elif dd < 0.35:
        dynamic_label = "low"
    elif dd < 0.65:
        dynamic_label = "moderate"
    else:
        dynamic_label = "high"

    if ms < 0.4:
        smoothness_label = "jerky"
    elif ms < 0.65:
        smoothness_label = "rough"
    elif ms < 0.85:
        smoothness_label = "smooth"
    else:
        smoothness_label = "very_smooth"

    issues = []
    if dd < 0.15:
        issues.append("Almost no motion detected — video looks like a slideshow")
    elif dd < 0.35:
        issues.append("Low motion — camera movement is barely noticeable")
    if ms < 0.4:
        issues.append("Jerky motion — transitions feel abrupt and unnatural")
    elif ms < 0.65:
        issues.append("Rough motion — some frames have inconsistent movement")

    return {
        "dynamic_label": dynamic_label,
        "smoothness_label": smoothness_label,
        "issues": issues,
    }


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: motion_metrics.py <video_path>")
        sys.exit(1)

    result = compute_motion_metrics(sys.argv[1])
    interpretation = interpret_motion(result)
    print(json.dumps({**result, **interpretation}, indent=2))
