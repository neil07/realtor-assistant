#!/usr/bin/env python3
"""
IMA Studio API client for Reel Agent pipeline.

Wraps image-to-video (Kling, WAN, etc.) and text-to-speech (MiniMax/ByteDance)
via the IMA Open API.

Flow:
  1. Upload local image → IMA CDN URL  (imapi.liveme.com)
  2. Fetch product list → get model version_id + attribute_id
  3. POST /open/v1/tasks/create
  4. Poll POST /open/v1/tasks/detail until done
  5. Download result file
"""

import hashlib
import logging
import mimetypes
import os
import time
import uuid
from pathlib import Path

import requests

# ─── Constants ────────────────────────────────────────────────────────────────

IMA_BASE_URL = "https://api.imastudio.com"
IMA_UPLOAD_URL = "https://imapi.liveme.com"
APP_ID = "webAgent"
APP_KEY = "32jdskjdk320eew"

VIDEO_MAX_WAIT = 5 * 60    # 5 min — fail fast to Ken Burns fallback
TTS_MAX_WAIT = 5 * 60      # 5 min
POLL_INTERVAL = 8           # seconds

logger = logging.getLogger(__name__)


# ─── Auth & Upload ─────────────────────────────────────────────────────────────

def _make_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "x-app-source": "ima_skills",
        "x_app_language": "en",
    }


def _gen_sign() -> tuple[str, str, str]:
    """Generate (sign, timestamp, nonce) for OSS upload auth."""
    nonce = uuid.uuid4().hex[:21]
    ts = str(int(time.time()))
    raw = f"{APP_ID}|{APP_KEY}|{ts}|{nonce}"
    sign = hashlib.sha1(raw.encode()).hexdigest().upper()
    return sign, ts, nonce


def upload_image(image_path: str, api_key: str) -> str:
    """
    Upload a local image to IMA CDN.

    Args:
        image_path: Local file path to image.
        api_key: IMA API key.

    Returns:
        Public HTTPS CDN URL of the uploaded image.

    Raises:
        RuntimeError: If upload fails.
    """
    ext = Path(image_path).suffix.lstrip(".").lower() or "jpeg"
    content_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"

    sign, ts, nonce = _gen_sign()
    token_resp = requests.get(
        f"{IMA_UPLOAD_URL}/api/rest/oss/getuploadtoken",
        params={
            "appUid": api_key, "appId": APP_ID, "appKey": APP_KEY,
            "cmimToken": api_key, "sign": sign, "timestamp": ts, "nonce": nonce,
            "fService": "privite", "fType": "picture",
            "fSuffix": ext, "fContentType": content_type,
        },
        timeout=30,
    )
    token_resp.raise_for_status()
    token_data = token_resp.json().get("data", {})
    ful = token_data.get("ful")
    fdl = token_data.get("fdl")
    if not ful or not fdl:
        raise RuntimeError(f"Upload token missing ful/fdl: {token_data}")

    image_bytes = Path(image_path).read_bytes()
    put_resp = requests.put(ful, data=image_bytes, headers={"Content-Type": content_type}, timeout=60)
    put_resp.raise_for_status()
    logger.debug("Uploaded %s → %s", image_path, fdl[:60])
    return fdl


# ─── Product List ──────────────────────────────────────────────────────────────

def _get_model_params(api_key: str, task_type: str, model_id: str) -> dict:
    """
    Fetch IMA product list and extract params for creating a task.

    Returns dict with: attribute_id, credit, model_id, model_name,
                       model_version (version_id), form_params.
    """
    resp = requests.get(
        f"{IMA_BASE_URL}/open/v1/product/list",
        params={"app": "ima", "platform": "web", "category": task_type},
        headers=_make_headers(api_key),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") not in (0, 200):
        raise RuntimeError(f"Product list error: code={data.get('code')} msg={data.get('message')}")

    tree = data.get("data") or []

    # Walk V2 tree: type=3 are leaf nodes (model versions)
    def walk(nodes):
        for node in nodes:
            if node.get("type") == "3":
                raw_mid = node.get("model_id", "").lower().strip()
                if raw_mid == model_id.lower().strip():
                    return node
            found = walk(node.get("children") or [])
            if found:
                return found
        return None

    node = walk(tree)
    if not node:
        available = _list_model_ids(tree)
        raise RuntimeError(
            f"Model '{model_id}' not found for task_type={task_type}. "
            f"Available: {available[:10]}"
        )

    credit_rules = node.get("credit_rules") or []
    if not credit_rules:
        raise RuntimeError(f"No credit_rules for model {model_id}")

    # Extract form_config defaults (non-virtual fields only)
    form_params: dict = {}
    for field in node.get("form_config") or []:
        fname = field.get("field")
        if not fname or field.get("is_ui_virtual", False):
            continue
        fval = field.get("value")
        if fval is not None:
            form_params[fname] = fval

    # Find the credit rule whose attributes match the form_params defaults.
    # Rules have an "attributes" dict (e.g. {"duration": "5", "sound": "off"}).
    # A rule matches if ALL its attribute values are consistent with form_params.
    # Fall back to credit_rules[0] if nothing matches.
    def _rule_matches(rule: dict) -> bool:
        attrs = rule.get("attributes") or {}
        return all(str(form_params.get(k, v)) == str(v) for k, v in attrs.items())

    rule = next((r for r in credit_rules if _rule_matches(r)), credit_rules[0])

    return {
        "attribute_id": rule.get("attribute_id", 0),
        "credit": rule.get("points", 0),
        "model_id": node.get("model_id", model_id),
        "model_name": node.get("name", model_id),
        "model_version": node.get("id", ""),
        "form_params": form_params,
    }


def _list_model_ids(tree: list) -> list[str]:
    """Flatten tree to list of model_ids (for error messages)."""
    result = []

    def walk(nodes):
        for node in nodes:
            if node.get("type") == "3":
                mid = node.get("model_id", "")
                if mid and mid not in result:
                    result.append(mid)
            walk(node.get("children") or [])

    walk(tree)
    return result


# ─── Task Create & Poll ────────────────────────────────────────────────────────

def _create_task(
    api_key: str,
    task_type: str,
    model_params: dict,
    prompt: str,
    input_images: list[str],
    extra_params: dict | None = None,
) -> str:
    """
    POST /open/v1/tasks/create  →  returns task_id.

    extra_params override form_config defaults (e.g. duration, aspect_ratio).
    """
    attribute_id = model_params["attribute_id"]
    credit = model_params["credit"]

    inner: dict = dict(model_params["form_params"])
    if extra_params:
        inner.update(extra_params)

    inner["prompt"] = prompt
    inner["n"] = int(inner.get("n", 1))
    inner["input_images"] = input_images
    inner["cast"] = {"points": credit, "attribute_id": attribute_id}

    payload = {
        "task_type": task_type,
        "enable_multi_model": False,
        "src_img_url": input_images,
        "parameters": [{
            "attribute_id": attribute_id,
            "model_id": model_params["model_id"],
            "model_name": model_params["model_name"],
            "model_version": model_params["model_version"],
            "app": "ima",
            "platform": "web",
            "category": task_type,
            "credit": credit,
            "parameters": inner,
        }],
    }

    resp = requests.post(
        f"{IMA_BASE_URL}/open/v1/tasks/create",
        json=payload,
        headers=_make_headers(api_key),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") not in (0, 200):
        raise RuntimeError(
            f"Task create failed: code={data.get('code')} msg={data.get('message')}"
        )

    task_id = (data.get("data") or {}).get("id")
    if not task_id:
        raise RuntimeError(f"No task_id in response: {data}")
    return task_id


def _poll_task(
    api_key: str,
    task_id: str,
    max_wait: int = VIDEO_MAX_WAIT,
    poll_interval: int = POLL_INTERVAL,
) -> str:
    """
    Poll POST /open/v1/tasks/detail until done.

    Returns the result media URL (video or audio).

    resource_status: 0=processing, 1=done, 2=failed, 3=deleted
    """
    url = f"{IMA_BASE_URL}/open/v1/tasks/detail"
    headers = _make_headers(api_key)
    start = time.time()

    while True:
        elapsed = time.time() - start
        if elapsed > max_wait:
            raise TimeoutError(f"Task {task_id} timed out after {max_wait}s")

        resp = requests.post(url, json={"task_id": task_id}, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") not in (0, 200):
            raise RuntimeError(f"Poll error: code={data.get('code')} msg={data.get('message')}")

        task = data.get("data") or {}
        medias = task.get("medias") or []

        def _rs(m):
            v = m.get("resource_status")
            return 0 if (v is None or v == "") else int(v)

        for media in medias:
            if _rs(media) == 2:
                raise RuntimeError(f"Task failed: {media.get('error_msg') or 'unknown'}")
            if _rs(media) == 3:
                raise RuntimeError("Task was deleted")

        if medias and all(_rs(m) == 1 for m in medias):
            first = medias[0]
            result_url = first.get("url") or first.get("watermark_url")
            if result_url:
                logger.info("Task %s done in %.0fs: %s", task_id, elapsed, result_url[:60])
                return result_url

        logger.debug("Task %s: %.0fs elapsed, still processing...", task_id, elapsed)
        time.sleep(poll_interval)


# ─── Public API ────────────────────────────────────────────────────────────────

def generate_video_clip(
    image_path: str,
    motion_prompt: str,
    output_path: str,
    duration: int = 5,
    aspect_ratio: str = "9:16",
    model_id: str = "wan2.6-i2v",
    api_key: str = None,
) -> dict:
    """
    Generate a video clip from a photo using IMA image-to-video.

    Args:
        image_path: Source frame image path.
        motion_prompt: Cinematic motion description for the clip.
        output_path: Where to save the resulting .mp4.
        duration: Clip duration in seconds (5 or 10 for Kling).
        aspect_ratio: "9:16" (vertical) or "16:9" (horizontal).
        model_id: IMA model ID (e.g. "kling-v2-6", "wan2.6-i2v", "ima-pro").
        api_key: IMA API key (falls back to IMA_API_KEY env var).

    Returns:
        {"status": "success", "video_path": str, "engine": "ima", "model": str, "task_id": str}
        or {"status": "error", "message": str}
    """
    if not api_key:
        api_key = os.environ.get("IMA_API_KEY")
    if not api_key:
        return {"status": "error", "message": "IMA_API_KEY not set"}

    def _run(task_type: str, input_images: list[str]) -> dict:
        """Inner: fetch params, create task, poll, download."""
        model_params = _get_model_params(api_key, task_type, model_id)
        extra = {"duration": duration, "aspect_ratio": aspect_ratio}
        task_id = _create_task(api_key, task_type, model_params, motion_prompt, input_images, extra)
        logger.info("IMA task created: %s (model=%s, task=%s)", task_id, model_id, task_type)
        result_url = _poll_task(api_key, task_id, max_wait=VIDEO_MAX_WAIT)
        video_resp = requests.get(result_url, timeout=120)
        video_resp.raise_for_status()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(video_resp.content)
        return {
            "status": "success",
            "video_path": output_path,
            "engine": "ima",
            "model": model_id,
            "task_id": task_id,
        }

    try:
        # Upload first frame only — single-frame image_to_video is the reliable path.
        # first_last_frame_to_video has consistent 500s on kling-v2-6; skip it to
        # avoid wasting credits on a retry that always fails.
        first_url = upload_image(image_path, api_key)
        return _run("image_to_video", [first_url])

    except Exception as e:
        logger.error("IMA video generation failed: %s", e)
        return {"status": "error", "message": str(e)}


def generate_tts(
    text: str,
    output_path: str,
    model_id: str = "seed-tts-1.1",
    api_key: str = None,
) -> dict:
    """
    Generate TTS audio using IMA text-to-speech.

    Args:
        text: Voiceover script text.
        output_path: Where to save the resulting audio file.
        model_id: IMA TTS model ID (e.g. "seed-tts-1.1", "seed-tts-2.0").
        api_key: IMA API key (falls back to IMA_API_KEY env var).

    Returns:
        {"status": "success", "audio_path": str, "characters": int}
        or {"status": "error", "message": str}
    """
    if not api_key:
        api_key = os.environ.get("IMA_API_KEY")
    if not api_key:
        return {"status": "error", "message": "IMA_API_KEY not set"}

    try:
        model_params = _get_model_params(api_key, "text_to_speech", model_id)

        task_id = _create_task(
            api_key, "text_to_speech", model_params, text, [],
        )
        logger.info("IMA TTS task created: %s (model=%s)", task_id, model_id)

        result_url = _poll_task(api_key, task_id, max_wait=TTS_MAX_WAIT, poll_interval=3)

        audio_resp = requests.get(result_url, timeout=60)
        audio_resp.raise_for_status()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(audio_resp.content)

        return {
            "status": "success",
            "audio_path": output_path,
            "characters": len(text),
            "model": model_id,
        }

    except Exception as e:
        logger.error("IMA TTS generation failed: %s", e)
        return {"status": "error", "message": str(e)}


MUSIC_MAX_WAIT = 10 * 60  # 10 min


def generate_music(
    prompt: str,
    output_path: str,
    duration: int = 30,
    model_id: str = "GenBGM",
    api_key: str = None,
) -> dict:
    """
    Generate background music using IMA text-to-music.

    Args:
        prompt: Music style description (e.g. "upbeat modern real estate tour BGM").
        output_path: Where to save the resulting audio file.
        duration: Desired duration in seconds.
        model_id: IMA music model ID (e.g. "GenBGM", "sonic", "GenSong").
        api_key: IMA API key (falls back to IMA_API_KEY env var).

    Returns:
        {"status": "success", "audio_path": str, "model": str}
        or {"status": "error", "message": str}
    """
    if not api_key:
        api_key = os.environ.get("IMA_API_KEY")
    if not api_key:
        return {"status": "error", "message": "IMA_API_KEY not set"}

    try:
        model_params = _get_model_params(api_key, "text_to_music", model_id)

        extra = {"duration": duration}
        task_id = _create_task(
            api_key, "text_to_music", model_params, prompt, [], extra,
        )
        logger.info("IMA music task created: %s (model=%s)", task_id, model_id)

        result_url = _poll_task(api_key, task_id, max_wait=MUSIC_MAX_WAIT, poll_interval=5)

        audio_resp = requests.get(result_url, timeout=60)
        audio_resp.raise_for_status()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(audio_resp.content)

        return {
            "status": "success",
            "audio_path": output_path,
            "model": model_id,
        }

    except Exception as e:
        logger.error("IMA music generation failed: %s", e)
        return {"status": "error", "message": str(e)}
