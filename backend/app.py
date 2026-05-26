from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.comfyui_health import (
    check_character_consistency,
    check_comfyui_health,
    invalidate_object_info_cache,
)
from backend.assets import asset_router
from backend.event_bus import project_event_bus
from backend.styles import get_default_style_id, get_style, style_router
from backend.project_runtime import (
    ExportAssetReadinessError,
    WORKSPACE,
    build_project,
    create_project,
    delete_project,
    derive_project_title,
    export_project,
    generate_scene_assets,
    load_project,
    merge_scene_with_next,
    project_snapshot,
    project_lock,
    save_project,
    scene_to_dict,
    fallback_scene_clip_path,
    reconstruct_story_text_from_scenes,
    replace_project_storyboard,
    replace_project_storyboard_from_preview,
    rerender_scene_audio,
    rerender_scene_image,
    rerender_scene_video,
    restore_scene_snapshot,
    scene_asset_file_exists,
    scene_latest_path,
    split_scene,
    update_character_fields,
    update_character_reference_image,
    update_project_fields,
    update_scene_fields,
    write_data_url_image,
)
from backend.asset_retention import cleanup_project_versions
from backend.task_store import TaskRecord, TaskStore
from scripts.run_workflow import (
    analyze_script_workflow,
    load_env_file,
    load_voice_presets,
    voice_presets_path,
)
from scripts.comfyui_ssh_tunnel import tunnel_config
from scripts.comfyui_ssh_tunnel import ensure_comfyui_tunnel
from scripts.tts_engines import edge_tts, synthesize_preview, tts_diagnostics
from scripts.tts_engines import load_tts_provider_settings, save_tts_provider_settings, tts_provider_settings_path


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
FRONTEND = ROOT / "frontend"
DEFAULT_STORY = ROOT / "inputs" / "sample_story.txt"
WORKFLOW_SCRIPT = ROOT / "scripts" / "run_workflow.py"
VOICE_CATALOG_CACHE = OUTPUTS / "voice_catalog.json"
DEFAULT_VOICE_CATALOG = [
    {
        "short_name": "zh-CN-XiaoxiaoNeural",
        "friendly_name": "Microsoft Xiaoxiao Online (Natural) - Simplified Chinese (China)",
        "locale": "zh-CN",
        "gender": "Female",
        "status": "GA",
    },
    {
        "short_name": "zh-CN-XiaoyiNeural",
        "friendly_name": "Microsoft Xiaoyi Online (Natural) - Simplified Chinese (China)",
        "locale": "zh-CN",
        "gender": "Female",
        "status": "GA",
    },
    {
        "short_name": "zh-CN-YunjianNeural",
        "friendly_name": "Microsoft Yunjian Online (Natural) - Simplified Chinese (China)",
        "locale": "zh-CN",
        "gender": "Male",
        "status": "GA",
    },
    {
        "short_name": "zh-CN-YunxiNeural",
        "friendly_name": "Microsoft Yunxi Online (Natural) - Simplified Chinese (China)",
        "locale": "zh-CN",
        "gender": "Male",
        "status": "GA",
    },
    {
        "short_name": "zh-CN-YunxiaNeural",
        "friendly_name": "Microsoft Yunxia Online (Natural) - Simplified Chinese (China)",
        "locale": "zh-CN",
        "gender": "Male",
        "status": "GA",
    },
    {
        "short_name": "zh-CN-YunyangNeural",
        "friendly_name": "Microsoft Yunyang Online (Natural) - Simplified Chinese (China)",
        "locale": "zh-CN",
        "gender": "Male",
        "status": "GA",
    },
    {
        "short_name": "zh-CN-liaoning-XiaobeiNeural",
        "friendly_name": "Microsoft Xiaobei Online (Natural) - Mandarin Chinese (Liaoning)",
        "locale": "zh-CN-liaoning",
        "gender": "Female",
        "status": "GA",
    },
    {
        "short_name": "zh-HK-HiuGaaiNeural",
        "friendly_name": "Microsoft HiuGaai Online (Natural) - Cantonese (Hong Kong)",
        "locale": "zh-HK",
        "gender": "Female",
        "status": "GA",
    },
    {
        "short_name": "zh-HK-HiuMaanNeural",
        "friendly_name": "Microsoft HiuMaan Online (Natural) - Cantonese (Hong Kong)",
        "locale": "zh-HK",
        "gender": "Female",
        "status": "GA",
    },
    {
        "short_name": "zh-HK-WanLungNeural",
        "friendly_name": "Microsoft WanLung Online (Natural) - Cantonese (Hong Kong)",
        "locale": "zh-HK",
        "gender": "Male",
        "status": "GA",
    },
    {
        "short_name": "zh-TW-HsiaoChenNeural",
        "friendly_name": "Microsoft HsiaoChen Online (Natural) - Chinese (Taiwan)",
        "locale": "zh-TW",
        "gender": "Female",
        "status": "GA",
    },
    {
        "short_name": "zh-TW-YunJheNeural",
        "friendly_name": "Microsoft YunJhe Online (Natural) - Chinese (Taiwan)",
        "locale": "zh-TW",
        "gender": "Male",
        "status": "GA",
    },
]

OUTPUTS.mkdir(parents=True, exist_ok=True)
WORKSPACE.mkdir(parents=True, exist_ok=True)


app = FastAPI(title="Comic Drama Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/outputs", StaticFiles(directory=OUTPUTS), name="outputs")
app.mount("/workspace", StaticFiles(directory=WORKSPACE), name="workspace")
app.mount("/frontend", StaticFiles(directory=FRONTEND), name="frontend")
app.include_router(style_router)
app.include_router(asset_router)

store = TaskStore()


@app.on_event("startup")
async def _startup() -> None:
    project_event_bus.set_event_loop(asyncio.get_running_loop())
    app.state.event_bus = project_event_bus


def _format_sse(event: str, data: object, event_id: str | None = None) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    for line in payload.splitlines() or [""]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


class CreateTaskRequest(BaseModel):
    story_text: str | None = None
    planner: Literal["auto", "rule", "llm"] = "auto"
    scene_count: int = Field(default=5, ge=1, le=12)
    keyframe_provider: Literal["auto", "local", "comfyui"] = "auto"
    video_provider: Literal["auto", "local", "comfyui"] = "auto"
    voice_provider: Literal["auto", "edge", "local", "silent"] = "auto"


class CreateTaskResponse(BaseModel):
    task_id: str
    status: str
    progress: int
    output_dir: str
    detail_url: str


class CreateProjectRequest(BaseModel):
    title: str = ""
    story_text: str | None = None
    planner: Literal["auto", "rule", "llm"] = "auto"
    scene_count: int = Field(default=5, ge=1, le=12)
    keyframe_provider: Literal["auto", "local", "comfyui"] = "auto"
    video_provider: Literal["auto", "local", "comfyui"] = "auto"
    voice_provider: Literal["auto", "edge", "local", "silent"] = "auto"


class UpdateProjectRequest(BaseModel):
    title: str | None = None
    story_text: str | None = None
    settings: dict | None = None
    characters: list | None = None


class UpdateProjectStyleRequest(BaseModel):
    style_id: str = Field(min_length=1)


class UpdateSceneRequest(BaseModel):
    title: str | None = None
    visual_prompt: str | None = None
    dialogue: str | None = None
    speaker: str | None = None
    voice_profile: str | None = None
    voice_engine: str | None = None
    voice_id: str | None = None
    reference_audio_path: str | None = None
    reference_text: str | None = None
    emotion: str | None = None
    voice_rate: float | None = None
    voice_pitch: float | None = None
    voice_volume: float | None = None
    camera_movement: str | None = None
    duration_seconds: float | None = None
    characters: list[str] | None = None
    crop_box: dict | None = None
    rhythm_preset: str | None = None
    sfx_type: str | None = None
    audio_manifest: dict | None = None
    subtitle_preset: str | None = None
    camera_intensity: float | None = None
    camera_speed: float | None = None
    episode_rhythm: Literal["classic_four_act", "fast_hook", "slow_burn"] | None = None
    episode_phase: Literal["opening", "setup", "reversal", "finale"] | None = None
    episode_phase_index: int | None = Field(default=None, ge=1, le=100)
    episode_phase_total: int | None = Field(default=None, ge=1, le=100)
    enhancement_mode: str | None = None
    enhancement_provider: str | None = None
    enhancement_prompt: str | None = None
    enhancement_workflow_path: str | None = None


class FillMissingAssetsRequest(BaseModel):
    kinds: list[Literal["image", "audio", "video"]] | None = None


class CharacterPatchRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    meta: dict | None = None
    appearance_core: str | None = None
    clothing_style: str | None = None
    negative_constraints: str | None = None
    voice_profile: str | None = None
    voice_engine: str | None = None
    voice_id: str | None = None
    reference_audio_path: str | None = None
    reference_text: str | None = None
    emotion: str | None = None
    voice_rate: float | None = None
    voice_pitch: float | None = None
    voice_volume: float | None = None


class CharacterImageUploadRequest(BaseModel):
    filename: str = "reference.png"
    data_url: str


class ScriptRecognitionRequest(BaseModel):
    script_text: str = Field(default="", min_length=1)
    title: str | None = None
    script_hint: str | None = None
    planner: Literal["auto", "rule", "llm"] = "auto"
    max_scenes: int = Field(default=12, ge=1, le=24)


class ScriptPreviewApplyRequest(BaseModel):
    story_text: str = Field(default="", min_length=1)
    title: str | None = None
    planner: Literal["auto", "rule", "llm"] = "auto"
    planner_used: str | None = None
    max_scenes: int = Field(default=12, ge=1, le=24)
    analysis: dict | None = None
    scenes: list[dict] = Field(default_factory=list)


class ScriptPreviewResponse(BaseModel):
    title: str
    planner_used: str
    analysis: dict
    scenes: list[dict]


class VoicePresetItem(BaseModel):
    profile: str = ""
    voice: str = ""


class VoicePresetSaveRequest(BaseModel):
    default: str | None = None
    items: list[VoicePresetItem] = Field(default_factory=list)


class VoicePreviewRequest(BaseModel):
    voice: str
    text: str = Field(default="这是一次漫剧配音试听。", min_length=1, max_length=120)
    engine: Literal["auto", "edge", "local", "silent", "cosyvoice", "gpt_sovits", "fish", "indextts"] = "auto"
    rate: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch: float = Field(default=0.0, ge=-24.0, le=24.0)
    volume: float = Field(default=1.0, ge=0.0, le=2.0)
    voice_id: str = ""
    reference_audio_path: str = ""
    reference_text: str = ""
    emotion: str = ""


class TTSProviderSettingsRequest(BaseModel):
    cosyvoice: str = ""
    gpt_sovits: str = ""
    fish: str = ""
    indextts: str = ""

def default_story_text() -> str:
    return DEFAULT_STORY.read_text(encoding="utf-8")


def spawn_background_job(target, *args) -> None:
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()


def project_or_404(project_id: str) -> dict:
    try:
        return project_snapshot(load_project(project_id))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


def scene_missing_asset_kinds(project_id: str, scene: dict) -> list[str]:
    missing: list[str] = []
    if not scene_asset_file_exists(project_id, scene, "image"):
        missing.append("image")
    if str(scene.get("dialogue") or "").strip() and not scene_asset_file_exists(project_id, scene, "audio"):
        missing.append("audio")
    try:
        video_path = scene_latest_path(project_id, scene, "video")
    except ValueError:
        video_path = None
    if not (video_path and video_path.is_file()) and not fallback_scene_clip_path(project_id, scene).is_file():
        missing.append("video")
    return missing


def fill_missing_assets(project_id: str, requested_kinds: set[str] | None = None) -> dict:
    requested = requested_kinds or {"image", "audio", "video"}
    with project_lock(project_id):
        project = load_project(project_id)
        scenes = sorted(project.get("scenes", []), key=lambda item: int(item.get("order", 0)))
    for scene in scenes:
        missing = scene_missing_asset_kinds(project_id, scene)
        order = int(scene.get("order") or 0)
        if "video" in requested and "video" in missing:
            rerender_scene_video(project_id, order)
            continue
        if "image" in requested and "image" in missing:
            rerender_scene_image(project_id, order)
        if "audio" in requested and "audio" in missing:
            rerender_scene_audio(project_id, order)
    return project_or_404(project_id)


def task_output_dir(task_id: str) -> Path:
    return OUTPUTS / task_id


def parse_progress(line: str) -> tuple[int, int, str] | None:
    match = re.match(r"^\[(\d+)/(\d+)\]\s*(.*)$", line.strip())
    if not match:
        return None
    step = int(match.group(1))
    total = int(match.group(2))
    message = match.group(3).strip()
    return step, total, message


def derive_progress(step: int, total: int) -> int:
    if total <= 0:
        return 0
    return max(0, min(100, int(step * 100 / total)))


def read_manifest(task_id: str) -> dict:
    manifest_path = task_output_dir(task_id) / "manifest.json"
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def format_voice_presets(presets: dict) -> dict:
    voice_map = presets.get("voice_map", {})
    if not isinstance(voice_map, dict):
        voice_map = {}
    items = [
        {"profile": str(profile), "voice": str(voice)}
        for profile, voice in sorted(voice_map.items(), key=lambda item: str(item[0]).lower())
        if str(profile).strip() and str(voice).strip()
    ]
    return {
        "default": str(presets.get("default", "")),
        "items": items,
    }


def normalize_voice_catalog_entry(item: dict) -> dict:
    short_name = str(item.get("ShortName") or item.get("short_name") or "").strip()
    friendly_name = str(item.get("FriendlyName") or item.get("friendly_name") or short_name).strip()
    locale = str(item.get("Locale") or item.get("locale") or "").strip()
    gender = str(item.get("Gender") or item.get("gender") or "").strip()
    status = str(item.get("Status") or item.get("status") or "").strip()
    if not short_name:
        raise ValueError("Voice catalog entry is missing ShortName")
    return {
        "short_name": short_name,
        "friendly_name": friendly_name or short_name,
        "locale": locale,
        "gender": gender,
        "status": status,
        "label": f"{short_name} · {gender or 'Unknown'} · {locale or 'n/a'}",
    }


def filter_voice_catalog(items: list[dict], locale_prefix: str = "zh") -> list[dict]:
    normalized: list[dict] = []
    seen: set[str] = set()
    for item in items:
        try:
            entry = normalize_voice_catalog_entry(item)
        except ValueError:
            continue
        if locale_prefix and not entry["locale"].startswith(locale_prefix):
            continue
        key = entry["short_name"].lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(entry)
    normalized.sort(key=lambda entry: (entry["locale"], entry["gender"], entry["short_name"]))
    return normalized


async def load_voice_catalog_data() -> list[dict]:
    if VOICE_CATALOG_CACHE.exists():
        try:
            cached = json.loads(VOICE_CATALOG_CACHE.read_text(encoding="utf-8"))
            if isinstance(cached, list) and cached:
                return cached
        except Exception:
            pass

    if edge_tts is not None:
        try:
            voices = await edge_tts.list_voices()
            catalog = filter_voice_catalog(voices)
            if catalog:
                VOICE_CATALOG_CACHE.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                return catalog
        except Exception as exc:
            print(f"[tts] Failed to load live voice catalog: {exc}")

    return DEFAULT_VOICE_CATALOG


def run_workflow_task(task: TaskRecord, story_text: str) -> None:
    task_dir = task_output_dir(task.id)
    task_dir.mkdir(parents=True, exist_ok=True)
    story_path = task_dir / "story.txt"
    story_path.write_text(story_text, encoding="utf-8")
    store.update(task.id, stage="starting", message="Preparing workflow")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    cmd = [
        sys.executable,
        str(WORKFLOW_SCRIPT),
        "--story",
        str(story_path),
        "--run-id",
        task.id,
        "--planner",
        task.planner,
        "--scene-count",
        str(task.scene_count),
        "--keyframe-provider",
        task.keyframe_provider,
        "--video-provider",
        task.video_provider,
        "--voice-provider",
        task.voice_provider,
    ]

    store.update(task.id, status="running", stage="running", progress=1, message="Workflow started")
    process = subprocess.Popen(
        cmd,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )

    assert process.stdout is not None
    try:
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            if not line:
                continue
            store.append_log(task.id, line)
            progress_info = parse_progress(line)
            if progress_info:
                step, total, message = progress_info
                store.update(
                    task.id,
                    progress=derive_progress(step, total),
                    stage=message or "running",
                    message=message or "running",
                )
            elif line.startswith("[planner]"):
                store.update(task.id, stage="planning", message=line)
            elif "Rendering scene" in line:
                store.update(task.id, stage="rendering", message=line)
            elif "Concatenating clips" in line:
                store.update(task.id, stage="assembling", message=line)

        code = process.wait()
        if code != 0:
            raise RuntimeError(f"Workflow exited with code {code}")

        manifest = read_manifest(task.id)
        final_video = manifest.get("final_video")
        store.update(
            task.id,
            status="succeeded",
            progress=100,
            stage="done",
            message="Completed",
            final_video=final_video,
        )
    except Exception as exc:
        store.update(task.id, status="failed", stage="failed", message="Failed", error=str(exc))


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
    request = Request(f"{comfyui_base_url()}{path}", headers=headers)
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


@app.get("/api/comfyui/status")
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


@app.get("/api/projects/{project_id}/comfyui-health")
async def project_comfyui_health(project_id: str, refresh: bool = False) -> dict:
    if refresh:
        invalidate_object_info_cache()
    return await asyncio.to_thread(check_comfyui_health)


@app.get("/api/projects/{project_id}/characters/{char_name}/consistency-status")
def character_consistency_status(project_id: str, char_name: str) -> dict:
    try:
        project = load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return check_character_consistency(project, WORKSPACE / project_id, char_name)


@app.get("/api/voice-presets")
def voice_presets() -> dict:
    return format_voice_presets(load_voice_presets())


@app.get("/api/voice-catalog")
async def voice_catalog() -> dict:
    return {"items": await load_voice_catalog_data()}


@app.get("/api/tts-diagnostics")
def tts_diagnostics_endpoint() -> dict:
    return tts_diagnostics()


@app.get("/api/tts-providers")
def tts_providers_endpoint() -> dict:
    return {
        "providers": load_tts_provider_settings(),
        "config_path": str(tts_provider_settings_path()),
    }


@app.put("/api/voice-presets")
def save_voice_presets(payload: VoicePresetSaveRequest) -> dict:
    voice_map: dict[str, str] = {}
    for item in payload.items:
        profile = item.profile.strip()
        voice = item.voice.strip()
        if not profile or not voice:
            continue
        voice_map[profile] = voice

    default_voice = (payload.default or "").strip()
    if not default_voice and voice_map:
        default_voice = next(iter(voice_map.values()))

    data = {
        "default": default_voice,
        "voice_map": voice_map,
    }
    path = voice_presets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return format_voice_presets(data)


@app.put("/api/tts-providers")
def save_tts_providers_endpoint(payload: TTSProviderSettingsRequest) -> dict:
    data = {
        "cosyvoice": payload.cosyvoice.strip(),
        "gpt_sovits": payload.gpt_sovits.strip(),
        "fish": payload.fish.strip(),
        "indextts": payload.indextts.strip(),
    }
    saved = save_tts_provider_settings(data)
    return {
        "providers": saved,
        "config_path": str(tts_provider_settings_path()),
    }


@app.post("/api/voice-preview")
def create_voice_preview(payload: VoicePreviewRequest) -> dict:
    voice = payload.voice.strip()
    text = payload.text.strip()
    if not voice:
        raise HTTPException(status_code=400, detail="Voice is required")
    if payload.engine == "edge" and not re.match(r"^[A-Za-z0-9-]+Neural$", voice):
        raise HTTPException(status_code=400, detail="Invalid Edge TTS voice name")

    preview_dir = OUTPUTS / "voice_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_id = uuid.uuid4().hex[:12]
    result = synthesize_preview(
        preview_dir,
        preview_id,
        text,
        voice,
        engine=payload.engine,
        rate=payload.rate,
        pitch=payload.pitch,
        volume=payload.volume,
        voice_id=payload.voice_id,
        reference_audio_path=payload.reference_audio_path,
        reference_text=payload.reference_text,
        emotion=payload.emotion,
    )

    return {
        "url": f"/outputs/voice_previews/{result.path.name}",
        "voice": voice,
        "text": text,
        "requested_engine": result.requested_engine,
        "engine": result.engine,
        "fallback": result.fallback,
        "warnings": result.warnings[-2:],
    }


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/api/projects")
def list_projects() -> list[dict]:
    from backend.project_runtime import list_projects as load_projects

    return [project_snapshot(project) for project in load_projects()]


@app.post("/api/projects")
def create_project_endpoint(payload: CreateProjectRequest) -> dict:
    story_text = payload.story_text or default_story_text()
    project = create_project(
        title=payload.title,
        story_text=story_text,
        planner=payload.planner,
        scene_count=payload.scene_count,
        keyframe_provider=payload.keyframe_provider,
        video_provider=payload.video_provider,
        voice_provider=payload.voice_provider,
    )
    return project_snapshot(project)


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict:
    return project_or_404(project_id)


@app.get("/api/projects/{project_id}/style")
def get_project_style(project_id: str) -> dict:
    project = project_or_404(project_id)
    style_id = str(project.get("style_id") or get_default_style_id()).strip()
    try:
        style = get_style(style_id)
    except KeyError:
        style_id = get_default_style_id()
        style = get_style(style_id)
    return {"project_id": project_id, "style_id": style_id, "style": style.model_dump()}


@app.post("/api/projects/{project_id}/style")
def set_project_style(project_id: str, payload: UpdateProjectStyleRequest) -> dict:
    style_id = str(payload.style_id or "").strip()
    try:
        style = get_style(style_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Style not found")
    try:
        project = update_project_fields(project_id, {"style_id": style.id})
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project_id": project_id, "style_id": style.id, "style": style.model_dump(), "project": project_snapshot(project)}


@app.get("/api/projects/{project_id}/events")
async def project_events(project_id: str, request: Request):
    project_or_404(project_id)
    queue = await project_event_bus.subscribe(project_id)

    async def event_generator():
        try:
            yield _format_sse("connected", {"project_id": project_id, "message": "SSE connected"})
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield _format_sse(event["type"], event, event["id"])
        finally:
            await project_event_bus.unsubscribe(project_id, queue)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)


@app.delete("/api/projects/{project_id}")
def delete_project_endpoint(project_id: str) -> dict:
    try:
        return delete_project(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.patch("/api/projects/{project_id}")
def patch_project(project_id: str, payload: UpdateProjectRequest) -> dict:
    updates = payload.model_dump(exclude_none=True)
    try:
        project = update_project_fields(project_id, updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return project_snapshot(project)


@app.patch("/api/projects/{project_id}/scenes/{scene_order}")
def patch_scene(project_id: str, scene_order: int, payload: UpdateSceneRequest) -> dict:
    updates = payload.model_dump(exclude_none=True)
    project = update_scene_fields(project_id, scene_order, updates)
    return project_snapshot(project)


@app.post("/api/projects/{project_id}/scenes/{scene_order}/split")
def split_scene_endpoint(project_id: str, scene_order: int) -> dict:
    try:
        project = split_scene(project_id, scene_order)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except KeyError:
        raise HTTPException(status_code=404, detail="Scene not found")
    return project_snapshot(project)


@app.post("/api/projects/{project_id}/scenes/{scene_order}/merge-next")
def merge_scene_endpoint(project_id: str, scene_order: int) -> dict:
    try:
        project = merge_scene_with_next(project_id, scene_order)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except KeyError:
        raise HTTPException(status_code=404, detail="Next scene not found")
    return project_snapshot(project)


@app.post("/api/projects/{project_id}/recognize-script")
def recognize_script(project_id: str, payload: ScriptRecognitionRequest) -> dict:
    try:
        project = replace_project_storyboard(
            project_id=project_id,
            story_text=payload.script_text,
            planner=payload.planner,
            title=payload.title or "",
            max_scenes=payload.max_scenes,
            script_hint=payload.script_hint or "",
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return project_snapshot(project)


@app.post("/api/projects/{project_id}/recognize-script/preview")
def preview_recognize_script(project_id: str, payload: ScriptRecognitionRequest) -> dict:
    project_or_404(project_id)
    try:
        analysis, scenes, planner_used = analyze_script_workflow(
            payload.script_text,
            payload.planner,
            max_scenes=payload.max_scenes,
            script_hint=payload.script_hint or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    title = payload.title.strip() if payload.title else ""
    if not title:
        title = derive_project_title(payload.script_text)
    return {
        "title": title,
        "script_text": payload.script_text,
        "planner_used": planner_used,
        "analysis": analysis,
        "scenes": [scene_to_dict(scene, order) for order, scene in enumerate(scenes, start=1)],
    }


@app.post("/api/projects/{project_id}/apply-script-preview")
def apply_script_preview(project_id: str, payload: ScriptPreviewApplyRequest) -> dict:
    try:
        project = replace_project_storyboard_from_preview(
            project_id=project_id,
            draft=payload.model_dump(),
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return project_snapshot(project)


@app.post("/api/projects/{project_id}/repair-story-text")
def repair_story_text(project_id: str) -> dict:
    try:
        with project_lock(project_id):
            project = load_project(project_id)
            repaired = reconstruct_story_text_from_scenes(project)
            if not repaired:
                raise HTTPException(status_code=409, detail="No scenes available to rebuild story text")
            project["story_text"] = repaired
            save_project(project)
        return project_or_404(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


@app.patch("/api/projects/{project_id}/characters/{char_index}")
def patch_character(project_id: str, char_index: int, payload: CharacterPatchRequest) -> dict:
    updates = payload.model_dump(exclude_none=True)
    project = update_character_fields(project_id, char_index, updates)
    return project_snapshot(project)


@app.post("/api/projects/{project_id}/characters/{char_index}/reference-image")
def upload_character_reference_image(project_id: str, char_index: int, payload: CharacterImageUploadRequest) -> dict:
    try:
        source_path = write_data_url_image(project_id, payload.filename, payload.data_url)
        project = update_character_reference_image(project_id, char_index, source_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return project_snapshot(project)


@app.post("/api/projects/{project_id}/build")
def build_project_endpoint(project_id: str) -> dict:
    project_or_404(project_id)
    from backend.project_runtime import update_runtime

    update_runtime(project_id, status="running", stage="queued", message="Queued", progress=1)

    def _run() -> None:
        try:
            build_project(project_id)
        except Exception as exc:
            from backend.project_runtime import update_runtime

            update_runtime(project_id, status="failed", stage="failed", message="Failed")
            print(f"[project] build failed for {project_id}: {exc}")

    spawn_background_job(_run)
    return project_or_404(project_id)


@app.post("/api/projects/{project_id}/export")
def export_project_endpoint(project_id: str) -> dict:
    try:
        project = export_project(project_id)
    except FileNotFoundError as exc:
        message = str(exc)
        if message == "Project not found":
            raise HTTPException(status_code=404, detail="Project not found")
        raise HTTPException(status_code=409, detail={"code": "EXPORT_ASSET_NOT_READY", "message": message})
    except ExportAssetReadinessError as exc:
        raise HTTPException(status_code=409, detail=exc.detail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return project_snapshot(project)


@app.post("/api/projects/{project_id}/scenes/{scene_order}/rerender-image")
def rerender_scene_image_endpoint(project_id: str, scene_order: int) -> dict:
    project_or_404(project_id)
    from backend.project_runtime import update_runtime

    update_runtime(project_id, status="running", stage=f"scene_{scene_order:03d}_image", message="Rerendering image", progress=1)

    def _run() -> None:
        try:
            rerender_scene_image(project_id, scene_order)
            from backend.project_runtime import update_runtime

            update_runtime(project_id, status="ready", stage="done", message="Completed", progress=100)
        except Exception as exc:
            from backend.project_runtime import update_runtime

            update_runtime(project_id, status="failed", stage="failed", message="Image rerender failed")
            print(f"[project] image rerender failed for {project_id} scene {scene_order}: {exc}")

    spawn_background_job(_run)
    return project_or_404(project_id)


@app.post("/api/projects/{project_id}/scenes/{scene_order}/rerender-audio")
def rerender_scene_audio_endpoint(project_id: str, scene_order: int) -> dict:
    project_or_404(project_id)
    from backend.project_runtime import update_runtime

    update_runtime(project_id, status="running", stage=f"scene_{scene_order:03d}_audio", message="Rerendering audio", progress=1)

    def _run() -> None:
        try:
            rerender_scene_audio(project_id, scene_order)
            from backend.project_runtime import update_runtime

            update_runtime(project_id, status="ready", stage="done", message="Completed", progress=100)
        except Exception as exc:
            from backend.project_runtime import update_runtime

            update_runtime(project_id, status="failed", stage="failed", message="Audio rerender failed")
            print(f"[project] audio rerender failed for {project_id} scene {scene_order}: {exc}")

    spawn_background_job(_run)
    return project_or_404(project_id)


@app.post("/api/projects/{project_id}/scenes/{scene_order}/rerender-video")
def rerender_scene_video_endpoint(project_id: str, scene_order: int) -> dict:
    project_or_404(project_id)
    from backend.project_runtime import update_runtime

    update_runtime(project_id, status="running", stage=f"scene_{scene_order:03d}_video", message="Rerendering video", progress=1)

    def _run() -> None:
        try:
            rerender_scene_video(project_id, scene_order)
            from backend.project_runtime import update_runtime

            update_runtime(project_id, status="ready", stage="done", message="Completed", progress=100)
        except Exception as exc:
            from backend.project_runtime import update_runtime

            update_runtime(project_id, status="failed", stage="failed", message="Video rerender failed")
            print(f"[project] video rerender failed for {project_id} scene {scene_order}: {exc}")

    spawn_background_job(_run)
    return project_or_404(project_id)


@app.post("/api/projects/{project_id}/scenes/{scene_order}/rebuild")
def rebuild_scene_endpoint(project_id: str, scene_order: int) -> dict:
    project_or_404(project_id)
    from backend.project_runtime import update_runtime

    update_runtime(
        project_id,
        status="running",
        stage=f"scene_{scene_order:03d}_rebuild",
        message="Rebuilding scene",
        progress=1,
    )

    def _run() -> None:
        try:
            generate_scene_assets(project_id, scene_order)
            from backend.project_runtime import update_runtime

            update_runtime(project_id, status="ready", stage="done", message="Completed", progress=100)
        except Exception as exc:
            from backend.project_runtime import update_runtime

            update_runtime(project_id, status="failed", stage="failed", message="Scene rebuild failed")
            print(f"[project] rebuild failed for {project_id} scene {scene_order}: {exc}")

    spawn_background_job(_run)
    return project_or_404(project_id)


@app.post("/api/projects/{project_id}/fill-missing-assets")
def fill_missing_assets_endpoint(project_id: str, payload: FillMissingAssetsRequest | None = None) -> dict:
    project_or_404(project_id)
    requested = set(payload.kinds) if payload and payload.kinds else {"image", "audio", "video"}
    from backend.project_runtime import update_runtime

    update_runtime(project_id, status="running", stage="repairing", message="Filling missing assets", progress=1)

    def _run() -> None:
        try:
            fill_missing_assets(project_id, requested)
            from backend.project_runtime import update_runtime

            update_runtime(project_id, status="ready", stage="done", message="Completed", progress=100)
        except Exception as exc:
            from backend.project_runtime import update_runtime

            update_runtime(project_id, status="failed", stage="failed", message="Asset repair failed")
            print(f"[project] asset repair failed for {project_id}: {exc}")

    spawn_background_job(_run)
    return project_or_404(project_id)


@app.post("/api/projects/{project_id}/scenes/{scene_order}/restore")
def restore_scene_endpoint(project_id: str, scene_order: int) -> dict:
    try:
        project = restore_scene_snapshot(project_id, scene_order)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="No snapshot available")
    except KeyError:
        raise HTTPException(status_code=404, detail="Scene not found")
    return project_snapshot(project)


@app.post("/api/projects/{project_id}/cleanup")
def cleanup_project_endpoint(project_id: str, keep: int = 1) -> dict:
    if keep < 1 or keep > 10:
        raise HTTPException(status_code=400, detail="keep must be between 1 and 10")
    try:
        with project_lock(project_id):
            project = load_project(project_id)
            result = cleanup_project_versions(WORKSPACE / project_id, project, keep=keep)
            snapshot = project_snapshot(load_project(project_id))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"ok": True, **result, "project": snapshot}


@app.post("/api/tasks", response_model=CreateTaskResponse)
def create_task(payload: CreateTaskRequest) -> CreateTaskResponse:
    story_text = payload.story_text or default_story_text()
    task_id = uuid.uuid4().hex[:12]
    task_output_dir(task_id).mkdir(parents=True, exist_ok=True)
    task = TaskRecord(
        id=task_id,
        status="queued",
        progress=0,
        stage="queued",
        message="Queued",
        planner=payload.planner,
        keyframe_provider=payload.keyframe_provider,
        video_provider=payload.video_provider,
        voice_provider=payload.voice_provider,
        scene_count=payload.scene_count,
        output_dir=str(task_output_dir(task_id)),
        story_path=str(task_output_dir(task_id) / "story.txt"),
    )
    store.create(task)
    thread = threading.Thread(target=run_workflow_task, args=(task, story_text), daemon=True)
    thread.start()
    return CreateTaskResponse(
        task_id=task_id,
        status=task.status,
        progress=task.progress,
        output_dir=task.output_dir,
        detail_url=f"/api/tasks/{task_id}",
    )


@app.get("/api/tasks")
def list_tasks() -> list[dict]:
    return [task.snapshot() for task in store.list()]


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    task = store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    snapshot = task.snapshot()
    if snapshot.get("final_video") and not snapshot["final_video"].startswith("/"):
        snapshot["final_video_url"] = f"/outputs/{task_id}/comic_drama_demo.mp4"
    return snapshot


@app.get("/api/tasks/{task_id}/files")
def task_files(task_id: str) -> dict:
    task_dir = task_output_dir(task_id)
    if not task_dir.exists():
        raise HTTPException(status_code=404, detail="Task not found")

    files = []
    for path in sorted(task_dir.iterdir()):
        if path.is_file():
            files.append(
                {
                    "name": path.name,
                    "size": path.stat().st_size,
                    "url": f"/outputs/{task_id}/{path.name}",
                }
            )
    return {"task_id": task_id, "files": files}


@app.get("/api/tasks/{task_id}/video")
def task_video(task_id: str):
    path = task_output_dir(task_id) / "comic_drama_demo.mp4"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Video not ready")
    return FileResponse(path)


@app.websocket("/api/tasks/{task_id}/stream")
async def task_stream(websocket: WebSocket, task_id: str) -> None:
    await websocket.accept()
    try:
        while True:
            task = store.get(task_id)
            if task is None:
                await websocket.send_json({"error": "Task not found"})
                break
            snapshot = task.snapshot()
            await websocket.send_json(snapshot)
            if snapshot["status"] in {"succeeded", "failed"}:
                break
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json({"error": str(exc)})
