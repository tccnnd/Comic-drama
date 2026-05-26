from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any

from backend.assets import (
    Asset,
    AssetStatus,
    AssetType,
    load_asset_store,
    project_dir,
    update_project_asset,
)
from backend.event_bus import project_event_bus
from backend.project_runtime import load_project, project_snapshot, workspace_url
from backend.styles import get_default_style_id, get_style
from scripts.run_workflow import (
    clean_comfyui_visual_prompt,
    download_comfyui_image,
    inject_comfyui_workflow,
    load_json,
    poll_comfyui_history,
    replace_placeholders,
    submit_comfyui_prompt,
    unresolved_placeholders,
)


ROOT = Path(__file__).resolve().parents[1]
ASSET_WORKFLOW_PATH = ROOT / "workflows" / "comfyui_asset_template.json"

ASSET_PROMPT_SUFFIXES: dict[AssetType, str] = {
    AssetType.CHARACTER: "full body character reference, centered composition, clean silhouette, simple background",
    AssetType.SCENE_BG: "environment background plate, no characters, cinematic composition, wide scene detail",
    AssetType.PROP: "single prop concept art, isolated object, centered composition, simple background",
}

ASSET_DIMENSIONS: dict[AssetType, tuple[int, int]] = {
    AssetType.CHARACTER: (768, 1024),
    AssetType.SCENE_BG: (1024, 768),
    AssetType.PROP: (768, 768),
}


def _asset_title(asset: Asset) -> str:
    if asset.asset_type == AssetType.CHARACTER:
        return "character reference"
    if asset.asset_type == AssetType.SCENE_BG:
        return "background plate"
    return "prop concept"


def _asset_prompt(asset: Asset) -> str:
    parts = [
        _asset_title(asset),
        asset.name,
        asset.description,
        asset.appearance,
        asset.visual_prompt,
        asset.personality,
        ASSET_PROMPT_SUFFIXES.get(asset.asset_type, ""),
    ]
    return clean_comfyui_visual_prompt(", ".join(part for part in parts if str(part).strip()))


def _asset_negative_prompt(asset: Asset) -> str:
    base = [
        "low quality",
        "blurry",
        "noisy",
        "watermark",
        "text",
        "logo",
        "cropped",
        "out of frame",
        "bad anatomy",
        "bad hands",
    ]
    if asset.asset_type == AssetType.SCENE_BG:
        base.extend(["people", "characters", "faces"])
    return ", ".join(base)


def _project_style(project_id: str) -> dict[str, str]:
    project = load_project(project_id)
    style_id = str(project.get("style_id") or get_default_style_id()).strip()
    try:
        style = get_style(style_id)
    except KeyError:
        style_id = get_default_style_id()
        style = get_style(style_id)
    return {
        "id": style.id,
        "name": style.name,
        "checkpoint_hint": style.checkpoint_hint,
        "positive_suffix": style.positive_suffix,
        "negative_suffix": style.negative_suffix,
    }


def _asset_workflow_replacements(asset: Asset) -> dict[str, Any]:
    width, height = ASSET_DIMENSIONS.get(asset.asset_type, (768, 1024))
    return {
        "__PROMPT__": _asset_prompt(asset),
        "__NEGATIVE__": _asset_negative_prompt(asset),
        "__SEED__": int(time.time() * 1000) % 2_147_483_647,
        "__WIDTH__": width,
        "__HEIGHT__": height,
        "__STEPS__": 22,
        "__CFG__": 7.0,
    }


def _asset_output_relative_path(asset_id: str) -> Path:
    return Path("assets") / f"{asset_id}.png"


def _asset_output_path(project_id: str, asset_id: str) -> Path:
    return project_dir(project_id) / _asset_output_relative_path(asset_id)


def _load_asset_record(project_id: str, asset_id: str) -> Asset:
    store = load_asset_store(project_id)
    for bucket in ("characters", "scene_bgs", "props"):
        for asset in getattr(store, bucket):
            if asset.id == asset_id:
                return asset
    raise KeyError(asset_id)


def _publish_project_update(project_id: str) -> None:
    project = project_snapshot(load_project(project_id))
    project_event_bus.publish_project_updated(project_id, project)


def _render_asset_image(project_id: str, asset_id: str) -> Asset:
    asset = _load_asset_record(project_id, asset_id)
    style = _project_style(project_id)
    workflow_template = load_json(ASSET_WORKFLOW_PATH)
    checkpoint_name = style.get("checkpoint_hint") or ""
    if not checkpoint_name:
        raise RuntimeError(f"Style {style['id']} does not define a checkpoint hint")
    filled = replace_placeholders(
        inject_comfyui_workflow(
            workflow_template,
            checkpoint_name=checkpoint_name,
            lora_name="",
            style_preset={
                "positive_suffix": style.get("positive_suffix", ""),
                "negative_suffix": style.get("negative_suffix", ""),
            },
        ),
        {
            **_asset_workflow_replacements(asset),
            "__CHECKPOINT_NAME__": checkpoint_name,
        },
    )
    unresolved = unresolved_placeholders(filled)
    if unresolved:
        raise RuntimeError(f"ComfyUI workflow has unresolved placeholders: {', '.join(unresolved[:5])}")

    prompt_id = f"asset-{asset_id}-{int(time.time() * 1000)}"
    client_id = f"client-{uuid.uuid4().hex[:8]}"
    submit_response = submit_comfyui_prompt(filled, prompt_id, client_id)
    prompt_id = str(submit_response.get("prompt_id", prompt_id))
    history = poll_comfyui_history(prompt_id)
    status = history.get("status", {})
    status_str = str(status.get("status_str") or "").lower()
    completed = status.get("completed")
    if completed is False or status_str in {"error", "failed", "failure"}:
        raise RuntimeError(f"ComfyUI workflow failed: {status}")

    outputs = history.get("outputs", {})
    save_node_ids = [
        node_id
        for node_id, node in filled.items()
        if isinstance(node, dict) and node.get("class_type") == "SaveImage"
    ]
    ordered_node_ids = save_node_ids + [node_id for node_id in outputs.keys() if node_id not in save_node_ids]
    output_path = _asset_output_path(project_id, asset_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for node_id in ordered_node_ids:
        node_output = outputs.get(node_id, {})
        images = node_output.get("images") or []
        if images:
            download_comfyui_image(images[0], output_path)
            thumbnail = workspace_url(project_id, _asset_output_relative_path(asset_id))
            return update_project_asset(
                project_id,
                asset_id,
                {
                    "status": AssetStatus.DONE,
                    "thumbnail": thumbnail,
                },
            )
    raise RuntimeError("ComfyUI workflow completed but returned no images")


def generate_asset_image(project_id: str, asset_id: str) -> Asset:
    asset = update_project_asset(project_id, asset_id, {"status": AssetStatus.GENERATING})
    _publish_project_update(project_id)
    try:
        result = _render_asset_image(project_id, asset_id)
    except Exception:
        update_project_asset(project_id, asset_id, {"status": AssetStatus.FAILED})
        _publish_project_update(project_id)
        raise
    _publish_project_update(project_id)
    return result


def generate_all_assets(project_id: str) -> dict[str, Any]:
    store = load_asset_store(project_id)
    asset_ids = [asset.id for bucket in ("characters", "scene_bgs", "props") for asset in getattr(store, bucket)]
    for asset_id in asset_ids:
        update_project_asset(project_id, asset_id, {"status": AssetStatus.GENERATING})
    _publish_project_update(project_id)
    results: list[dict[str, Any]] = []
    for asset_id in asset_ids:
        try:
            asset = _render_asset_image(project_id, asset_id)
            results.append(asset.model_dump(mode="json"))
            _publish_project_update(project_id)
        except Exception as exc:
            update_project_asset(project_id, asset_id, {"status": AssetStatus.FAILED})
            _publish_project_update(project_id)
            results.append({"id": asset_id, "status": AssetStatus.FAILED.value, "error": str(exc)})
    store = load_asset_store(project_id)
    return {
        "status": "done",
        "assets": store.model_dump(mode="json"),
        "results": results,
    }
