from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter

from backend.comfyui_health import check_comfyui_health, invalidate_object_info_cache
from backend.routers._common import ROOT
from scripts.comfyui_ssh_tunnel import ensure_comfyui_tunnel, tunnel_config
from scripts.run_workflow import load_env_file

router = APIRouter(tags=["comfyui"])


def comfyui_base_url() -> str:
    load_env_file()
    try:
        tunnel_url = ensure_comfyui_tunnel()
    except Exception as exc:
        os.environ["COMFYUI_TUNNEL_ERROR"] = str(exc)
        tunnel_url = None
    if tunnel_url:
        return tunnel_url.rstrip("/")
    return os.environ.get("COMFYUI_BASE_URL", "http://127.0.0.1:8188").strip().rstrip("/")


def comfyui_is_local_url() -> bool:
    parsed = urlparse(comfyui_base_url())
    return parsed.hostname in {"127.0.0.1", "localhost", "::1", None}


def read_comfyui_json(path: str, timeout: float = 3.0) -> dict:
    headers = comfyui_auth_headers()
    url = f"{comfyui_base_url()}{path}"
    request = Request(url)
    for key, value in headers.items():
        request.add_header(key, value)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def comfyui_auth_headers() -> dict[str, str]:
    raw = os.environ.get("COMFYUI_AUTH_HEADER", "").strip()
    if raw and ":" in raw:
        key, value = raw.split(":", 1)
        return {key.strip(): value.strip()}
    api_key = os.environ.get("COMFYUI_API_KEY", "").strip()
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def comfyui_model_root() -> Path:
    raw = os.environ.get("COMFYUI_MODEL_ROOT", "").strip()
    if raw:
        return Path(raw)
    input_dir = os.environ.get("COMFYUI_INPUT_DIR", "").strip()
    if input_dir:
        return Path(input_dir).parent / "models"
    return ROOT / "tools" / "ComfyUI" / "ComfyUI_windows_portable" / "ComfyUI" / "models"


def comfyui_model_status() -> dict:
    if tunnel_config() is not None:
        return {
            "root": "",
            "groups": {},
            "missing": [],
            "skipped": True,
            "reason": "remote ComfyUI via SSH tunnel: local filesystem model checks are skipped",
        }
    if not comfyui_is_local_url() and not os.environ.get("COMFYUI_MODEL_ROOT", "").strip():
        return {
            "root": "",
            "groups": {},
            "missing": [],
            "skipped": True,
            "reason": "remote ComfyUI: local filesystem model checks are skipped",
        }
    model_root = comfyui_model_root()
    groups = {
        "checkpoints": ["v1-5-pruned-emaonly-fp16.safetensors"],
        "ipadapter": ["ip-adapter-plus_sd15.safetensors"],
        "clip_vision": ["CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"],
    }
    result = {"root": str(model_root), "groups": {}, "missing": []}
    for group, filenames in groups.items():
        group_dir = model_root / group
        items = []
        for filename in filenames:
            path = group_dir / filename
            exists = path.is_file()
            items.append({"name": filename, "exists": exists, "size": path.stat().st_size if exists else 0})
            if not exists:
                result["missing"].append(f"{group}/{filename}")
        result["groups"][group] = items
    return result


@router.get("/api/comfyui/status")
def comfyui_status() -> dict:
    load_env_file()
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
    workflow_path = Path(os.environ.get("COMFYUI_WORKFLOW_PATH", "workflows/comfyui_keyframe_template.json"))
    if not workflow_path.is_absolute():
        workflow_path = ROOT / workflow_path
    try:
        base_url = comfyui_base_url()
    except Exception as exc:
        base_url = os.environ.get("COMFYUI_BASE_URL", "http://127.0.0.1:8188").strip().rstrip("/")
        comfyui_error = str(exc)
    else:
        comfyui_error = ""
    result = {
        "available": False,
        "base_url": base_url,
        "workflow_path": str(workflow_path),
        "workflow_exists": workflow_path.is_file(),
        "required_nodes": required_nodes,
        "registered_nodes": [],
        "missing_nodes": required_nodes,
        "queue": {},
        "models": comfyui_model_status(),
        "system": {},
        "reference_mode": os.environ.get("COMFYUI_REFERENCE_MODE", "auto"),
        "is_local": comfyui_is_local_url(),
        "error": comfyui_error,
    }
    try:
        object_info = read_comfyui_json("/object_info")
        registered = sorted(node for node in required_nodes if node in object_info)
        missing = [node for node in required_nodes if node not in object_info]
        result["registered_nodes"] = registered
        result["missing_nodes"] = missing
        result["queue"] = read_comfyui_json("/queue", timeout=2.0)
        try:
            result["system"] = read_comfyui_json("/system_stats", timeout=2.0).get("system", {})
        except Exception:
            result["system"] = {}
        result["available"] = not missing and not result["models"]["missing"] and bool(result["workflow_exists"])
    except HTTPError as exc:
        result["error"] = f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}"
    except (URLError, TimeoutError, OSError) as exc:
        result["error"] = str(exc)
    except Exception as exc:
        result["error"] = str(exc)
    return result


@router.get("/api/projects/{project_id}/comfyui-health")
async def project_comfyui_health(project_id: str, refresh: bool = False) -> dict:
    if refresh:
        invalidate_object_info_cache()
    return await asyncio.to_thread(check_comfyui_health)
