#!/usr/bin/env python3
"""
Listing Video Agent — Google Cloud Storage Upload

Uploads final video files to GCS and returns public URLs.
"""

import json
import os
import sys
from pathlib import Path

try:
    from google.cloud import storage
except ImportError:
    storage = None

GCS_BUCKET = os.environ.get("GCS_BUCKET", "openclaw-videos")


def upload_video(
    local_path: str,
    listing_id: str,
    content_type: str = "video/mp4",
) -> dict:
    """
    Upload a video file to GCS.

    Args:
        local_path: Path to the local video file
        listing_id: Listing identifier (used in blob path)
        content_type: MIME type

    Returns:
        {"status": "success", "url": str, "blob_path": str}
    """
    if storage is None:
        return {"status": "error", "message": "google-cloud-storage not installed. Run: pip install google-cloud-storage"}

    if not os.path.exists(local_path):
        return {"status": "error", "message": f"File not found: {local_path}"}

    filename = os.path.basename(local_path)
    blob_path = f"videos/{listing_id}/{filename}"

    try:
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(blob_path)
        blob.upload_from_filename(local_path, content_type=content_type)

        # Try to make public (requires fine-grained access control on bucket).
        # If bucket uses uniform access, fall back to constructing the URL manually.
        try:
            blob.make_public()
            url = blob.public_url
        except Exception:
            url = f"https://storage.googleapis.com/{GCS_BUCKET}/{blob_path}"

        return {
            "status": "success",
            "url": url,
            "blob_path": blob_path,
            "bucket": GCS_BUCKET,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def upload_listing_videos(
    output_dir: str,
    listing_id: str,
) -> dict:
    """
    Upload all final video files from a listing output directory.

    Looks for *_9x16.mp4 and *_16x9.mp4 files in the output directory.

    Args:
        output_dir: Directory containing final video files
        listing_id: Listing identifier

    Returns:
        {"status": "success", "videos": [{"aspect": str, "url": str}, ...]}
    """
    videos = []

    for mp4 in sorted(Path(output_dir).glob("*.mp4")):
        result = upload_video(str(mp4), listing_id)
        if result["status"] == "success":
            aspect = "9:16" if "9x16" in mp4.name else "16:9"
            videos.append({
                "filename": mp4.name,
                "aspect": aspect,
                "url": result["url"],
                "blob_path": result["blob_path"],
            })
        else:
            videos.append({
                "filename": mp4.name,
                "status": "error",
                "message": result["message"],
            })

    succeeded = sum(1 for v in videos if "url" in v)
    return {
        "status": "success" if succeeded > 0 else "error",
        "listing_id": listing_id,
        "videos": videos,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Upload videos to GCS")
    subparsers = parser.add_subparsers(dest="command")

    # Single file
    single = subparsers.add_parser("single", help="Upload a single video")
    single.add_argument("file", help="Local video file path")
    single.add_argument("--listing-id", required=True, help="Listing identifier")

    # All videos from output dir
    batch = subparsers.add_parser("batch", help="Upload all videos from output dir")
    batch.add_argument("--output-dir", required=True, help="Output directory")
    batch.add_argument("--listing-id", required=True, help="Listing identifier")

    args = parser.parse_args()

    if args.command == "single":
        result = upload_video(args.file, args.listing_id)
        print(json.dumps(result, indent=2))

    elif args.command == "batch":
        result = upload_listing_videos(args.output_dir, args.listing_id)
        print(json.dumps(result, indent=2))

    else:
        parser.print_help()
        sys.exit(1)
