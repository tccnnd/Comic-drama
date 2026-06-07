from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
    comfyui_base_url,
    download_comfyui_image,
    inject_comfyui_workflow,
    load_json,
    poll_comfyui_history,
    replace_placeholders,
    submit_comfyui_prompt,
    unresolved_placeholders,
)

logger = logging.getLogger(__name__)


ROOT = Path(__file__).resolve().parents[1]
ASSET_WORKFLOW_PATH = ROOT / "workflows" / "comfyui_asset_template.json"

ASSET_PROMPT_SUFFIXES: dict[AssetType, str] = {
    AssetType.CHARACTER: "solo, 1boy or 1girl, upper body portrait, looking at viewer, detailed face, detailed eyes, sharp facial features, clean lines, simple gradient background",
    AssetType.SCENE_BG: "no people, no characters, environment concept art, wide angle, cinematic composition, detailed background, atmospheric perspective",
    AssetType.PROP: "single object, isolated, centered composition, product photography, simple background, studio lighting, no people",
}

ASSET_DIMENSIONS: dict[AssetType, tuple[int, int]] = {
    AssetType.CHARACTER: (832, 1216),
    AssetType.SCENE_BG: (1216, 832),
    AssetType.PROP: (768, 768),
}


def _comfyui_available_checkpoints() -> list[str]:
    """Query ComfyUI for available checkpoint models."""
    try:
        url = f"{comfyui_base_url()}/object_info/CheckpointLoaderSimple"
        request = Request(url)
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        raw = (
            data.get("CheckpointLoaderSimple", {})
            .get("input", {})
            .get("required", {})
            .get("ckpt_name", [])
        )
        if isinstance(raw, list) and raw and isinstance(raw[0], list):
            return [str(item) for item in raw[0]]
        return []
    except Exception as exc:
        logger.warning("Failed to query ComfyUI checkpoints: %s", exc)
        return []


def _comfyui_available_loras() -> list[str]:
    """Query ComfyUI for available LoRA models."""
    try:
        url = f"{comfyui_base_url()}/object_info/LoraLoader"
        request = Request(url)
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        raw = (
            data.get("LoraLoader", {})
            .get("input", {})
            .get("required", {})
            .get("lora_name", [])
        )
        if isinstance(raw, list) and raw and isinstance(raw[0], list):
            return [str(item) for item in raw[0]]
        return []
    except Exception:
        return []


def _check_comfyui_online() -> bool:
    """Check if ComfyUI is reachable."""
    try:
        url = f"{comfyui_base_url()}/system_stats"
        request = Request(url)
        with urlopen(request, timeout=8) as response:
            response.read()
        return True
    except Exception:
        return False


def _resolve_checkpoint(desired: str) -> str:
    """Resolve the checkpoint to use: prefer desired, fallback to first available.

    If the desired checkpoint is available, use it.
    Otherwise, use the first available checkpoint from ComfyUI.
    Raises RuntimeError if no checkpoints are available at all.
    """
    available = _comfyui_available_checkpoints()
    if not available:
        # Cannot query or no checkpoints installed
        logger.warning(
            "Cannot query available checkpoints from ComfyUI; using configured: %s",
            desired,
        )
        return desired

    if desired in available:
        return desired

    # Fallback: use the first available checkpoint
    fallback = available[0]
    logger.warning(
        "Checkpoint '%s' not found in ComfyUI. Available: %s. Using fallback: '%s'",
        desired,
        available,
        fallback,
    )
    return fallback


def _resolve_lora(desired: str) -> str:
    """Resolve the LoRA to use: return desired if available, empty string otherwise."""
    if not desired:
        return ""
    available = _comfyui_available_loras()
    if not available:
        # No LoRAs installed, skip LoRA
        logger.warning("No LoRAs available in ComfyUI; skipping LoRA '%s'", desired)
        return ""
    if desired in available:
        return desired
    logger.warning(
        "LoRA '%s' not found in ComfyUI. Available: %s. Skipping LoRA.",
        desired,
        available,
    )
    return ""


def _asset_title(asset: Asset) -> str:
    if asset.asset_type == AssetType.CHARACTER:
        return "character reference"
    if asset.asset_type == AssetType.SCENE_BG:
        return "background plate"
    return "prop concept"


def _asset_prompt(asset: Asset) -> str:
    """Build a structured, high-quality prompt for asset generation.

    Structure: quality tags → character/scene visual description → composition suffix
    All in English, comma-separated tags optimized for SDXL models.
    Note: Style positive_suffix is injected separately via inject_comfyui_workflow.
    """
    # Quality prefix (always first for maximum weight)
    quality_tags = "masterpiece, best quality, full color, vibrant colors, digital painting, colored, highly detailed"

    # Core description parts (visual attributes only)
    description_parts: list[str] = []
    if asset.appearance:
        description_parts.append(str(asset.appearance).strip())
    if asset.visual_prompt:
        description_parts.append(str(asset.visual_prompt).strip())
    if asset.description and not asset.appearance:
        description_parts.append(str(asset.description).strip())

    # Asset type suffix (composition/framing)
    type_suffix = ASSET_PROMPT_SUFFIXES.get(asset.asset_type, "")

    # Assemble final prompt
    parts = [
        quality_tags,
        ", ".join(part for part in description_parts if part),
        type_suffix,
    ]
    return clean_comfyui_visual_prompt(", ".join(part for part in parts if str(part).strip()))


def _asset_negative_prompt(asset: Asset) -> str:
    """Build a comprehensive negative prompt for asset generation.

    Covers common SDXL quality issues plus asset-type-specific exclusions.
    Note: Style negative_suffix is injected separately via inject_comfyui_workflow.
    """
    base = [
        "sketch",
        "lineart",
        "monochrome",
        "greyscale",
        "black and white",
        "uncolored",
        "pencil drawing",
        "rough sketch",
        "worst quality",
        "low quality",
        "normal quality",
        "blurry",
        "noisy",
        "jpeg artifacts",
        "watermark",
        "text",
        "logo",
        "signature",
        "username",
        "cropped",
        "out of frame",
        "bad anatomy",
        "bad hands",
        "extra fingers",
        "fewer fingers",
        "extra limbs",
        "missing limbs",
        "deformed",
        "disfigured",
        "mutation",
        "ugly",
        "duplicate",
    ]
    if asset.asset_type == AssetType.CHARACTER:
        base.extend([
            "multiple people",
            "multiple views",
            "reference sheet",
            "turnaround",
            "character sheet",
            "crowd",
            "complex background",
            "busy background",
            "extra heads",
            "wrong eye color",
            "inconsistent clothing",
            "exaggerated muscles",
            "disproportionate body",
            "chibi",
        ])
    elif asset.asset_type == AssetType.SCENE_BG:
        base.extend(["people", "characters", "faces", "person", "human figure"])
    elif asset.asset_type == AssetType.PROP:
        base.extend(["people", "characters", "hands holding", "complex background"])

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
    # Pre-check: ensure ComfyUI is reachable
    if not _check_comfyui_online():
        raise RuntimeError(
            "ComfyUI 服务不可达。请确认 ComfyUI 已启动，或 SSH 隧道已连接到远程 GPU 服务器。"
            f" 当前目标地址: {comfyui_base_url()}"
        )

    asset = _load_asset_record(project_id, asset_id)
    style = _project_style(project_id)
    workflow_template = load_json(ASSET_WORKFLOW_PATH)

    # Resolve checkpoint: use style hint, fallback to whatever is available
    desired_checkpoint = style.get("checkpoint_hint") or ""
    if not desired_checkpoint:
        raise RuntimeError(f"Style {style['id']} does not define a checkpoint hint")
    checkpoint_name = _resolve_checkpoint(desired_checkpoint)

    # Resolve LoRA: skip if not available
    desired_lora = style.get("lora_hint") or ""
    lora_name = _resolve_lora(desired_lora)

    filled = replace_placeholders(
        inject_comfyui_workflow(
            workflow_template,
            checkpoint_name=checkpoint_name,
            lora_name=lora_name,
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

    # Check for immediate validation errors from ComfyUI
    if "error" in submit_response:
        error_info = submit_response["error"]
        error_msg = error_info.get("message", str(error_info)) if isinstance(error_info, dict) else str(error_info)
        node_errors = submit_response.get("node_errors", {})
        if node_errors:
            details = []
            for node_id, node_err in node_errors.items():
                errors = node_err.get("errors", []) if isinstance(node_err, dict) else []
                for err in errors:
                    details.append(str(err.get("message", err)) if isinstance(err, dict) else str(err))
            if details:
                error_msg += " | " + "; ".join(details)
        raise RuntimeError(f"ComfyUI 拒绝了工作流: {error_msg}")

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
    asset = update_project_asset(project_id, asset_id, {"status": AssetStatus.GENERATING, "error": ""})
    _publish_project_update(project_id)
    try:
        result = _render_asset_image(project_id, asset_id)
    except Exception as exc:
        logger.error("Asset generation failed for %s: %s", asset_id, exc)
        update_project_asset(project_id, asset_id, {"status": AssetStatus.FAILED, "error": str(exc)})
        _publish_project_update(project_id)
        raise
    _publish_project_update(project_id)
    return result


def generate_all_assets(project_id: str) -> dict[str, Any]:
    # Pre-check ComfyUI availability before starting batch
    if not _check_comfyui_online():
        raise RuntimeError(
            "ComfyUI 服务不可达。请确认 ComfyUI 已启动，或 SSH 隧道已连接到远程 GPU 服务器。"
            f" 当前目标地址: {comfyui_base_url()}"
        )

    store = load_asset_store(project_id)
    asset_ids = [asset.id for bucket in ("characters", "scene_bgs", "props") for asset in getattr(store, bucket)]
    for asset_id in asset_ids:
        update_project_asset(project_id, asset_id, {"status": AssetStatus.GENERATING, "error": ""})
    _publish_project_update(project_id)
    results: list[dict[str, Any]] = []
    for asset_id in asset_ids:
        try:
            asset = _render_asset_image(project_id, asset_id)
            results.append(asset.model_dump(mode="json"))
            _publish_project_update(project_id)
        except Exception as exc:
            logger.error("Asset generation failed for %s: %s", asset_id, exc)
            update_project_asset(project_id, asset_id, {"status": AssetStatus.FAILED, "error": str(exc)})
            _publish_project_update(project_id)
            results.append({"id": asset_id, "status": AssetStatus.FAILED.value, "error": str(exc)})
    store = load_asset_store(project_id)
    return {
        "status": "done",
        "assets": store.model_dump(mode="json"),
        "results": results,
    }
