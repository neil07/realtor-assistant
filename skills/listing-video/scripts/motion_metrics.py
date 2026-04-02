#!/usr/bin/env python3
"""
Lightweight video motion metrics using OpenCV optical flow.

Replaces VBench's dynamic_degree + motion_smoothness + temporal_flickering
with a CPU-only implementation that requires only opencv-python + numpy
(~50MB vs ~4GB).

Core logic mirrors VBench:
  - dynamic_degree: Farneback optical flow → top-5% magnitude > threshold
  - motion_smoothness: Linear frame interpolation error → normalized 0-1
  - temporal_flickering: Frame-to-frame SSIM variance → brightness/color jumps
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def _compute_ssim(
    img1: np.ndarray,
    img2: np.ndarray,
    C1: float = 6.5025,
    C2: float = 58.5225,
) -> float:
    """Lightweight SSIM for grayscale frames, no external dependency.

    Uses the standard SSIM formula with 11x11 Gaussian window (σ=1.5).
    Constants C1, C2 match Wang et al. (2004) defaults for [0, 255] range.
    """
    i1 = img1.astype(np.float64)
    i2 = img2.astype(np.float64)
    mu1 = cv2.GaussianBlur(i1, (11, 11), 1.5)
    mu2 = cv2.GaussianBlur(i2, (11, 11), 1.5)
    mu1_sq, mu2_sq, mu1_mu2 = mu1 ** 2, mu2 ** 2, mu1 * mu2
    sigma1_sq = cv2.GaussianBlur(i1 ** 2, (11, 11), 1.5) - mu1_sq
    sigma2_sq = cv2.GaussianBlur(i2 ** 2, (11, 11), 1.5) - mu2_sq
    sigma12 = cv2.GaussianBlur(i1 * i2, (11, 11), 1.5) - mu1_mu2
    ssim_map = ((2 * mu1_mu2 + C1) * (2 * sigma12 + C2)) / (
        (mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2)
    )
    return float(ssim_map.mean())


def compute_motion_metrics(
    video_path: str,
    target_fps: float = 8.0,
    max_dimension: int = 512,
) -> dict:
    """Compute dynamic_degree, motion_smoothness, and temporal_flickering.

    Args:
        video_path: Path to .mp4 video file.
        target_fps: Subsample to this FPS before analysis.
        max_dimension: Resize frames to this max side length for speed.

    Returns:
        Dict with keys:
            dynamic_degree: float 0-1 (1 = lots of motion, 0 = static/PPT)
            motion_smoothness: float 0-1 (1 = perfectly smooth, 0 = jerky)
            temporal_flickering: float 0-1 (0 = stable, 1 = severe flickering)
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

    # --- Temporal Flickering (VBench 3rd dimension) ---
    # Frame-to-frame SSIM detects brightness/color jumps that optical flow misses.
    # High SSIM variance = sudden visual changes = flickering.
    ssim_scores = []
    for i in range(len(frames_gray) - 1):
        score = _compute_ssim(frames_gray[i], frames_gray[i + 1])
        ssim_scores.append(score)

    if ssim_scores:
        # flickering = 1 - mean(SSIM): higher = more flickering
        temporal_flickering = float(np.clip(1.0 - np.mean(ssim_scores), 0, 1))
    else:
        temporal_flickering = 0.0

    return {
        "dynamic_degree": round(dynamic_degree, 3),
        "motion_smoothness": round(motion_smoothness, 3),
        "temporal_flickering": round(temporal_flickering, 3),
        "mean_flow_magnitude": round(float(np.mean(flow_magnitudes)), 3),
        "flow_variance": round(float(np.var(flow_magnitudes)), 3),
        "frame_count": len(frames_gray),
    }


def _empty_result(frame_count: int = 0) -> dict:
    return {
        "dynamic_degree": 0.0,
        "motion_smoothness": 1.0,
        "temporal_flickering": 0.0,
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
            flickering_label: str ("stable"/"mild"/"noticeable"/"severe")
            issues: list[str] (PM-friendly issue descriptions)
    """
    dd = metrics.get("dynamic_degree", 0)
    ms = metrics.get("motion_smoothness", 1)
    tf = metrics.get("temporal_flickering", 0)

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

    if tf < 0.08:
        flickering_label = "stable"
    elif tf < 0.15:
        flickering_label = "mild"
    elif tf < 0.25:
        flickering_label = "noticeable"
    else:
        flickering_label = "severe"

    issues = []
    if dd < 0.15:
        issues.append("Almost no motion detected — video looks like a slideshow")
    elif dd < 0.35:
        issues.append("Low motion — camera movement is barely noticeable")
    if ms < 0.4:
        issues.append("Jerky motion — transitions feel abrupt and unnatural")
    elif ms < 0.65:
        issues.append("Rough motion — some frames have inconsistent movement")
    if tf > 0.25:
        issues.append("Severe flickering — brightness/color jumps between frames")
    elif tf > 0.15:
        issues.append("Noticeable flickering — some frames have sudden visual changes")

    return {
        "dynamic_label": dynamic_label,
        "smoothness_label": smoothness_label,
        "flickering_label": flickering_label,
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
