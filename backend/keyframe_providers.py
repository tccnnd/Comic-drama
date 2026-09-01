"""Cloud keyframe generation providers as fallback when ComfyUI is unavailable.

Supports:
- OpenAI Images API (gpt-image-2 / gpt-image-1*) via /v1/images/generations
- DashScope/Bailian text-to-image (wanx*) via Moyin relay or direct
- Base64 inline image for providers that accept data URIs

This allows keyframe generation without a GPU server.
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.logger import get_logger

logger = get_logger(__name__)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


DEFAULT_OPENAI_IMAGE_MODEL = "gpt-image-2"
DEFAULT_DASHSCOPE_T2I_MODEL = "wanx2.1-t2i-turbo"


def _is_openai_image_model(model: str) -> bool:
    normalized = str(model or "").strip().lower()
    return normalized.startswith("gpt-image") or normalized.startswith("dall-e")


def _nearest_openai_image_size(width: int, height: int) -> str:
    """Map requested WxH onto a size gpt-image-2 accepts."""
    width = max(1, int(width or 1024))
    height = max(1, int(height or 1024))
    ratio = width / height
    if 0.9 <= ratio <= 1.1:
        return "1024x1024"
    if ratio >= 1.0:
        return "1536x1024"
    return "1024x1536"


def _openai_compatible_root(base_url: str) -> str:
    """Normalize a chat/images base URL to the OpenAI-compatible root (…/v1)."""
    root = str(base_url or "").strip().rstrip("/")
    if not root:
        return "https://memefast.top/v1"
    if root.endswith("/v1"):
        return root
    return f"{root}/v1"


def generate_keyframe_openai(
    prompt: str,
    *,
    width: int = 1024,
    height: int = 1536,
    output_path: Path | None = None,
    model: str = "",
    api_key: str = "",
    base_url: str = "",
) -> Path | None:
    """Generate a keyframe via OpenAI Images API (/v1/images/generations).

    Used for gpt-image-2 and other gpt-image-* models on OpenAI-compatible
    relays (including memefast.top).
    """
    api_key = (
        api_key
        or _env("KEYFRAME_T2I_API_KEY")
        or _env("XL_API_KEY")
        or _env("OPENAI_API_KEY")
        or _env("LLM_API_KEY")
    )
    base_url = (
        base_url
        or _env("KEYFRAME_T2I_BASE_URL")
        or _env("XL_BASE_URL")
        or _env("OPENAI_BASE_URL")
        or _env("LLM_BASE_URL")
        or "https://memefast.top"
    )
    model = model or _env("KEYFRAME_T2I_MODEL") or DEFAULT_OPENAI_IMAGE_MODEL
    if not api_key:
        logger.warning("[keyframe-cloud] No API key configured for OpenAI image generation")
        return None

    size = _nearest_openai_image_size(width, height)
    root = _openai_compatible_root(base_url)
    submit_url = f"{root}/images/generations"
    body = {
        "model": model,
        "prompt": prompt[:32000],
        "n": 1,
        "size": size,
        "response_format": "b64_json",
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    logger.info("[keyframe-cloud] Submitting OpenAI image: model=%s, size=%s", model, size)
    try:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = Request(submit_url, data=data, headers=headers, method="POST")
        with urlopen(req, timeout=180) as resp:
            response = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:400]
        except Exception:
            detail = str(exc)
        logger.error("[keyframe-cloud] OpenAI image submit failed: %s %s", exc, detail)
        return None
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.error("[keyframe-cloud] OpenAI image submit failed: %s", exc)
        return None

    items = response.get("data") if isinstance(response, dict) else None
    if not isinstance(items, list) or not items:
        logger.error("[keyframe-cloud] OpenAI image response missing data: %s", response)
        return None
    first = items[0] if isinstance(items[0], dict) else {}
    b64 = str(first.get("b64_json") or "").strip()
    if b64:
        return _write_image_bytes(base64.b64decode(b64), output_path)
    img_url = str(first.get("url") or "").strip()
    if img_url:
        return _download_image(img_url, output_path)
    logger.error("[keyframe-cloud] OpenAI image response had no b64_json or url")
    return None


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
    """Generate a keyframe via the configured cloud T2I backend.

    ``gpt-image-*`` / ``dall-e*`` models go to OpenAI Images API.
    Other models (``wanx*``) stay on DashScope text2image.
    Default model is ``gpt-image-2``.
    """
    api_key = (
        api_key or _env("KEYFRAME_T2I_API_KEY") or _env("XL_API_KEY") or _env("DASHSCOPE_API_KEY")
    )
    base_url = (
        base_url or _env("KEYFRAME_T2I_BASE_URL") or _env("XL_BASE_URL") or "https://memefast.top"
    )
    model = model or _env("KEYFRAME_T2I_MODEL") or DEFAULT_OPENAI_IMAGE_MODEL

    if _is_openai_image_model(model):
        return generate_keyframe_openai(
            prompt,
            width=width,
            height=height,
            output_path=output_path,
            model=model,
            api_key=api_key,
            base_url=base_url,
        )

    if not api_key:
        logger.warning("[keyframe-cloud] No API key configured for cloud keyframe generation")
        return None

    # DashScope text-to-image endpoint
    submit_path = (
        _env("KEYFRAME_T2I_SUBMIT_PATH")
        or "/alibailian/api/v1/services/aigc/text2image/image-synthesis"
    )
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

    logger.info(
        "[keyframe-cloud] Submitting text-to-image: model=%s, size=%dx%d", model, width, height
    )

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
        status = (
            str(poll_output.get("task_status") or "").upper()
            if isinstance(poll_output, dict)
            else ""
        )

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


def _write_image_bytes(payload: bytes, output_path: Path | None) -> Path | None:
    if not output_path or not payload:
        return None
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(payload)
        if output_path.exists() and output_path.stat().st_size > 0:
            logger.info(
                "[keyframe-cloud] Wrote keyframe: %s (%d KB)",
                output_path.name,
                output_path.stat().st_size // 1024,
            )
            return output_path
    except Exception as exc:
        logger.error("[keyframe-cloud] Write failed: %s", exc)
    return None


def _download_image(url: str, output_path: Path | None) -> Path | None:
    """Download an image from URL to the output path."""
    if not output_path:
        return None
    try:
        with urlopen(url, timeout=60) as resp:
            return _write_image_bytes(resp.read(), output_path)
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
