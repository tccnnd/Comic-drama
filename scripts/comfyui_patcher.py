from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def find_node(workflow: dict[str, Any], title: str) -> dict[str, Any] | None:
    for node in workflow.values():
        if isinstance(node, dict) and node.get("_meta", {}).get("title") == title:
            return node
    return None


def upload_reference_image(comfyui_url: str, image_path: str | Path) -> str:
    path = Path(image_path)
    boundary = f"----comicdrama{random.randint(100000000, 999999999)}"
    suffix = path.suffix.lower()
    content_type = "image/png"
    if suffix in {".jpg", ".jpeg"}:
        content_type = "image/jpeg"
    elif suffix == ".webp":
        content_type = "image/webp"

    body = bytearray()
    body.extend(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    body.extend(path.read_bytes())
    body.extend(b"\r\n")
    body.extend(
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="overwrite"\r\n\r\n'
            "true\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
    )

    request = Request(
        f"{comfyui_url.rstrip('/')}/upload/image",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ComfyUI image upload failed with HTTP {exc.code}: {body_text}") from exc
    name = str(payload.get("name") or "").strip()
    if not name:
        raise RuntimeError("ComfyUI upload did not return a file name")
    return name


def patch_workflow(
    template: dict[str, Any],
    positive_prompt: str,
    negative_prompt: str = "low quality, blurry, deformed",
    reference_image_filename: str | None = None,
    ipadapter_weight: float = 0.7,
) -> dict[str, Any]:
    wf = copy.deepcopy(template)

    node = find_node(wf, "SCENE_PROMPT_POSITIVE")
    if node:
        node.setdefault("inputs", {})["text"] = positive_prompt

    node = find_node(wf, "SCENE_PROMPT_NEGATIVE")
    if node:
        node.setdefault("inputs", {})["text"] = negative_prompt

    node = find_node(wf, "CHARACTER_REF_IMAGE")
    if node and reference_image_filename:
        node.setdefault("inputs", {})["image"] = reference_image_filename

    node = find_node(wf, "IPADAPTER_MAIN")
    if node:
        node.setdefault("inputs", {})["weight"] = float(ipadapter_weight if reference_image_filename else 0.0)

    return wf
