from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import requests


def find_node(workflow: dict[str, Any], title: str) -> dict[str, Any] | None:
    for node in workflow.values():
        if isinstance(node, dict) and node.get("_meta", {}).get("title") == title:
            return node
    return None


def upload_reference_image(comfyui_url: str, image_path: str | Path) -> str:
    path = Path(image_path)
    with path.open("rb") as handle:
        response = requests.post(
            f"{comfyui_url.rstrip('/')}/upload/image",
            files={"image": (path.name, handle, "image/png")},
            data={"overwrite": "true"},
            timeout=30,
        )
    response.raise_for_status()
    payload = response.json()
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
