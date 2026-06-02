"""Cloud keyframe generation providers as fallback when ComfyUI is unavailable.

Supports:
- DashScope/Bailian text-to-image (via Moyin relay or direct)
- Base64 inline image for providers that accept data URIs

This allows keyframe generation without a GPU server.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def generate_keyframe_dashscope(
    prompt: str,
    negative_prompt: str = "",
    *,
    width: int = 832,
    height: int = 1216,
    output_path: Path | None = None,
    model: str = "",
    api_key: str = "",
    base_url: str = "",
) -> Path | None:
    """Generate a keyframe image using DashScope text-to-image API.

    Uses the same Moyin relay as video generation, or direct DashScope endpoint.
    Returns the output path on success, None on failure.
    """
    api_key = api_key or _env("KEYFRAME_T2I_API_KEY") or _env("XL_API_KEY") or _env("DASHSCOPE_API_KEY")
    base_url = base_url or _env("KEYFRAME_T2I_BASE_URL") or _env("XL_BASE_URL") or "https://memefast.top"
    model = model or _env("KEYFRAME_T2I_MODEL") or "wanx2.1-t2i-turbo"

    if not api_key:
        logger.warning("[keyframe-cloud] No API key configured for cloud keyframe generation")
        return None

    # DashScope text-to-image endpoint
    submit_path = _env("KEYFRAME_T2I_SUBMIT_PATH") or "/alibailian/api/v1/services/aigc/text2image/image-synthesis"
    poll_path = _env("KEYFRAME_T2I_POLL_PATH") or "/alibailian/api/v1/tasks/{task_id}"
    timeout_s = int(_env("KEYFRAME_T2I_TIMEOUT") or "120")

    # Build request
    body: dict[str, Any] = {
        "model": model,
        "input": {
            "prompt": prompt[:1500],
        },
        "parameters": {
            "size": f"{width}*{height}",
            "n": 1,
        },
    }
    if negative_prompt:
        body["input"]["negative_prompt"] = negative_prompt[:500]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }

    root = base_url.rstrip("/")
    submit_url = f"{root}{submit_path}"

    logger.info("[keyframe-cloud] Submitting text-to-image: model=%s, size=%dx%d", model, width, height)

    try:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = Request(submit_url, data=data, headers=headers, method="POST")
        with urlopen(req, timeout=30) as resp:
            response = json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        logger.error("[keyframe-cloud] Submit failed: %s", exc)
        return None
    except json.JSONDecodeError:
        logger.error("[keyframe-cloud] Submit returned non-JSON response")
        return None

    # Extract task_id
    output = response.get("output", {})
    task_id = ""
    if isinstance(output, dict):
        task_id = str(output.get("task_id") or "").strip()
    if not task_id:
        # Maybe direct response with image
        results = output.get("results", []) if isinstance(output, dict) else []
        if results and isinstance(results[0], dict):
            img_url = results[0].get("url", "")
            if img_url:
                return _download_image(img_url, output_path)
        logger.error("[keyframe-cloud] No task_id in response: %s", response)
        return None

    # Poll for result
    poll_url = f"{root}{poll_path.replace('{task_id}', task_id)}"
    poll_headers = {"Authorization": f"Bearer {api_key}"}
    deadline = time.time() + timeout_s

    while time.time() < deadline:
        time.sleep(5)
        try:
            req = Request(poll_url, headers=poll_headers, method="GET")
            with urlopen(req, timeout=30) as resp:
                poll_result = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.warning("[keyframe-cloud] Poll error: %s", exc)
            continue

        poll_output = poll_result.get("output", {})
        status = str(poll_output.get("task_status") or "").upper() if isinstance(poll_output, dict) else ""

        if status == "SUCCEEDED":
            results = poll_output.get("results", []) if isinstance(poll_output, dict) else []
            if results and isinstance(results[0], dict):
                img_url = str(results[0].get("url") or "").strip()
                if img_url:
                    return _download_image(img_url, output_path)
            logger.error("[keyframe-cloud] SUCCEEDED but no image URL in results")
            return None

        if status in {"FAILED", "CANCELED"}:
            logger.error("[keyframe-cloud] Task %s failed: %s", task_id, poll_result)
            return None

    logger.error("[keyframe-cloud] Task %s timed out after %ds", task_id, timeout_s)
    return None


def _download_image(url: str, output_path: Path | None) -> Path | None:
    """Download an image from URL to the output path."""
    if not output_path:
        return None
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(url, timeout=60) as resp:
            output_path.write_bytes(resp.read())
        if output_path.exists() and output_path.stat().st_size > 0:
            logger.info("[keyframe-cloud] Downloaded keyframe: %s (%d KB)", output_path.name, output_path.stat().st_size // 1024)
            return output_path
    except Exception as exc:
        logger.error("[keyframe-cloud] Download failed: %s", exc)
    return None


def build_keyframe_prompt(
    scene_visual: str,
    characters: list[dict[str, Any]],
    style_suffix: str = "",
) -> tuple[str, str]:
    """Build a clean English prompt for keyframe generation.

    Returns (positive_prompt, negative_prompt).
    """
    parts: list[str] = ["masterpiece, best quality, highly detailed, anime style"]

    # Scene description (clean Chinese to keep it, model handles bilingual)
    if scene_visual:
        parts.append(scene_visual.strip())

    # Character descriptions in English
    for char in characters[:3]:
        char_parts: list[str] = []
        gender = str(char.get("meta", {}).get("gender") or char.get("gender") or "").strip()
        age = str(char.get("meta", {}).get("age") or char.get("age") or "").strip()
        appearance = str(char.get("appearance_core") or char.get("appearance") or "").strip()
        clothing = str(char.get("clothing_style") or char.get("visual_prompt") or "").strip()

        if gender:
            char_parts.append(gender)
        if age:
            char_parts.append(age)
        if appearance:
            char_parts.append(appearance)
        if clothing:
            char_parts.append(clothing)
        if char_parts:
            parts.append(", ".join(char_parts))

    if style_suffix:
        parts.append(style_suffix)

    positive = ", ".join(p for p in parts if p.strip())
    negative = "low quality, blurry, deformed, bad anatomy, extra limbs, watermark, text, signature"

    return positive, negative
