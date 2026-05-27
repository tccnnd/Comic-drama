from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from video_providers import get_video_provider_spec


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "workflows" / "comfyui_keyframe_template.json"
OBJECT_INFO_TTL_SECONDS = 60.0

_object_info_cache: dict[str, Any] | None = None
_object_info_cached_at = 0.0


def _load_env_file(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env_value(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def _comfyui_base_url() -> str:
    _load_env_file()
    if _env_value("COMFYUI_SSH_HOST", default=""):
        host = _env_value("COMFYUI_SSH_LOCAL_HOST", default="127.0.0.1") or "127.0.0.1"
        port = _env_value("COMFYUI_SSH_LOCAL_PORT", default="8189") or "8189"
        return f"http://{host}:{port}"
    return _env_value("COMFYUI_BASE_URL", "COMFYUI_URL", default="http://127.0.0.1:8188").rstrip("/")


def _comfyui_auth_headers() -> dict[str, str]:
    raw = _env_value("COMFYUI_AUTH_HEADER", default="")
    if raw and ":" in raw:
        key, value = raw.split(":", 1)
        return {key.strip(): value.strip()}
    api_key = _env_value("COMFYUI_API_KEY", default="")
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _read_comfyui_json(path: str, timeout: float) -> dict[str, Any]:
    request = Request(f"{_comfyui_base_url()}{path}", headers=_comfyui_auth_headers())
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_object_info() -> dict[str, Any] | None:
    global _object_info_cache, _object_info_cached_at

    now = time.monotonic()
    if _object_info_cache is not None and (now - _object_info_cached_at) < OBJECT_INFO_TTL_SECONDS:
        return _object_info_cache

    try:
        object_info = _read_comfyui_json("/object_info", timeout=8.0)
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None

    _object_info_cache = object_info
    _object_info_cached_at = now
    return object_info


def invalidate_object_info_cache() -> None:
    global _object_info_cache, _object_info_cached_at
    _object_info_cache = None
    _object_info_cached_at = 0.0


def _resolve_template_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    replacements = {
        "__LORA_NAME__": _env_value("COMFYUI_LORA_NAME", "COMFYUI_VIDEO_LORA_NAME", default=""),
        "__CHECKPOINT_NAME__": _env_value("COMFYUI_CHECKPOINT_NAME", "COMFYUI_VIDEO_CHECKPOINT_NAME", default=""),
    }
    return replacements.get(value, value)


def _parse_template_requirements() -> dict[str, list[str]]:
    requirements: dict[str, list[str]] = {"checkpoints": [], "loras": []}
    try:
        template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return requirements

    for node in template.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        class_type = node.get("class_type")
        if class_type == "CheckpointLoaderSimple":
            checkpoint = _resolve_template_value(inputs.get("ckpt_name"))
            if checkpoint and checkpoint not in requirements["checkpoints"]:
                requirements["checkpoints"].append(checkpoint)
        elif class_type == "LoraLoader":
            lora = _resolve_template_value(inputs.get("lora_name"))
            if lora and lora not in requirements["loras"]:
                requirements["loras"].append(lora)
    return requirements


def _extract_combo_values(object_info: dict[str, Any], node: str, input_name: str) -> list[str]:
    raw = (
        object_info.get(node, {})
        .get("input", {})
        .get("required", {})
        .get(input_name, [])
    )
    if not isinstance(raw, list) or not raw:
        return []
    values = raw[0]
    if not isinstance(values, list):
        return []
    return [str(item) for item in values]


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def check_comfyui_health() -> dict[str, Any]:
    _load_env_file()
    base_url = _comfyui_base_url()
    provider_spec = get_video_provider_spec(_env_value("VIDEO_PROVIDER", default="local"))
    video_provider = provider_spec.id
    video_backend = provider_spec.backend
    requires_comfyui = video_backend == "comfyui"
    raw_video_template = _env_value("COMFYUI_VIDEO_WORKFLOW_PATH", "VIDEO_WORKFLOW_PATH", default="workflows/comfyui_video_template.json")
    video_template_path = Path(raw_video_template)
    if not video_template_path.is_absolute():
        video_template_path = ROOT / video_template_path
    via_ssh_tunnel = bool(_env_value("COMFYUI_SSH_HOST", default=""))
    paramiko_available = importlib.util.find_spec("paramiko") is not None
    blockers: list[str] = []
    warnings: list[str] = []

    if requires_comfyui and via_ssh_tunnel and not paramiko_available:
        blockers.append("SSH tunnel configured (COMFYUI_SSH_HOST is set) but paramiko is not installed")
    if requires_comfyui and not video_template_path.is_file():
        blockers.append(f"ComfyUI video workflow template not found: {video_template_path}")

    try:
        _read_comfyui_json("/system_stats", timeout=5.0)
        comfyui_online = True
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        comfyui_online = False

    if requires_comfyui and not comfyui_online:
        if via_ssh_tunnel and paramiko_available:
            blockers.append("ComfyUI unreachable; SSH tunnel may be down")
        else:
            blockers.append(f"ComfyUI offline at {base_url}")

    requirements = _parse_template_requirements() if requires_comfyui else {"checkpoints": [], "loras": []}
    checkpoint_required = requirements["checkpoints"]
    loras_required = requirements["loras"]
    if requires_comfyui and not checkpoint_required:
        blockers.append("COMFYUI_CHECKPOINT_NAME / COMFYUI_VIDEO_CHECKPOINT_NAME is required")
    checkpoint_available: list[str] = []
    loras_available: list[str] = []
    missing_nodes: list[str] = []
    known_nodes = False
    ipadapter_loader_available = False
    ipadapter_node_available = False

    if comfyui_online:
        object_info = _get_object_info()
        if object_info is None:
            blockers.append("Could not fetch ComfyUI /object_info")
        else:
            known_nodes = True
            checkpoint_available = _extract_combo_values(object_info, "CheckpointLoaderSimple", "ckpt_name")
            loras_available = _extract_combo_values(object_info, "LoraLoader", "lora_name")
            ipadapter_loader_available = "IPAdapterUnifiedLoader" in object_info
            ipadapter_node_available = "IPAdapter" in object_info
            required_nodes = [
                "CheckpointLoaderSimple",
                "LoadImage",
                "CLIPTextEncode",
                "EmptyLatentImage",
                "IPAdapterUnifiedLoader",
                "IPAdapter",
                "KSampler",
                "VAEDecode",
                "SaveImage",
            ]
            missing_nodes = [node for node in required_nodes if node not in object_info]

            if requires_comfyui:
                for checkpoint in checkpoint_required:
                    if checkpoint not in checkpoint_available:
                        blockers.append(f"Checkpoint not found in ComfyUI: {checkpoint}")
                for lora in loras_required:
                    if lora not in loras_available:
                        blockers.append(f"LoRA not found in ComfyUI: {lora}")
                if missing_nodes:
                    blockers.append(f"Missing ComfyUI nodes: {', '.join(missing_nodes)}")

    return {
        "comfyui": {
            "online": comfyui_online,
            "url": base_url,
            "via_ssh_tunnel": via_ssh_tunnel,
            "paramiko_available": paramiko_available,
        },
        "video": {
            "provider": video_provider,
            "backend": video_backend,
            "workflow_path": str(video_template_path),
            "workflow_exists": video_template_path.is_file(),
        },
        "models": {
            "checkpoint_required": checkpoint_required,
            "checkpoint_available": checkpoint_available,
            "checkpoint_match": all(item in checkpoint_available for item in checkpoint_required),
            "loras_required": loras_required,
            "loras_available": loras_available,
            "loras_match": all(item in loras_available for item in loras_required),
        },
        "nodes": {
            "ipadapter_loader_available": ipadapter_loader_available,
            "ipadapter_node_available": ipadapter_node_available,
            "loadimage_available": known_nodes and "LoadImage" not in missing_nodes,
            "missing": missing_nodes,
        },
        "nodes_checked": known_nodes,
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
    }


def _scene_mentions_character(scene: dict[str, Any], aliases: set[str]) -> bool:
    if str(scene.get("speaker") or "") in aliases:
        return True
    characters = scene.get("characters")
    if isinstance(characters, list) and any(str(item) in aliases for item in characters):
        return True
    return False


def check_character_consistency(project_data: dict[str, Any], project_dir: Path, char_name: str) -> dict[str, Any]:
    warnings: list[str] = []
    character = next(
        (item for item in project_data.get("characters", []) if item.get("name") == char_name or item.get("char_id") == char_name),
        None,
    )
    if character is None:
        return {
            "character": char_name,
            "reference": None,
            "last_generation": None,
            "ready": False,
            "warnings": [f"Character not found: {char_name}"],
        }

    aliases = {
        str(value).strip()
        for value in (char_name, character.get("name"), character.get("char_id"))
        if str(value or "").strip()
    }
    reference_path = str(character.get("reference_image_path") or "").strip()
    reference_meta = character.get("reference_meta") if isinstance(character.get("reference_meta"), dict) else {}
    crop_method = reference_meta.get("crop_method")
    reference_uploaded = bool(reference_path and (project_dir / reference_path).is_file())

    if crop_method == "failed":
        reference_uploaded = False
        warnings.append("Reference image preprocessing failed; IPAdapter will use placeholder")
    elif not reference_uploaded:
        warnings.append("No processed reference image found; IPAdapter will use placeholder")
    elif crop_method == "center_fallback":
        warnings.append("Reference image uses center crop fallback; front-facing head-and-shoulders images work best")

    reference = {
        "uploaded": reference_uploaded,
        "processed_path": reference_path or None,
        "crop_method": crop_method,
        "output_size": reference_meta.get("output_size"),
        "warnings": _as_string_list(reference_meta.get("warnings")),
    }

    last_meta: dict[str, Any] | None = None
    last_scene_order: Any = None
    latest_injected_at = -1.0
    for scene in project_data.get("scenes", []):
        if not isinstance(scene, dict) or not _scene_mentions_character(scene, aliases):
            continue
        meta = scene.get("consistency_meta")
        if not isinstance(meta, dict):
            continue
        try:
            injected_at = float(meta.get("injected_at") or 0.0)
        except (TypeError, ValueError):
            injected_at = 0.0
        if injected_at > latest_injected_at:
            latest_injected_at = injected_at
            last_meta = meta
            last_scene_order = scene.get("order") or scene.get("scene")

    last_generation = None
    if last_meta is not None:
        errors = _as_string_list(last_meta.get("errors"))
        last_generation = {
            "scene_order": last_scene_order,
            "placeholder_used": bool(last_meta.get("placeholder")),
            "ip_adapter_weight": last_meta.get("ip_adapter_weight"),
            "succeeded": not errors,
            "errors": errors,
            "injected_at": last_meta.get("injected_at"),
        }
        if errors:
            warnings.append("Last generation failed; check project-level ComfyUI health")

    return {
        "character": character.get("name") or char_name,
        "reference": reference,
        "last_generation": last_generation,
        "ready": reference_uploaded,
        "warnings": warnings,
    }
