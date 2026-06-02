from __future__ import annotations

import json
import os
import threading
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.logger import get_logger
from scripts.run_workflow import extract_json_object, load_env_file, post_llm_chat_completion

logger = get_logger(__name__)


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "workspace"

_ASSET_LOCKS: dict[str, threading.Lock] = {}
_ASSET_LOCKS_GUARD = threading.Lock()


class AssetType(str, Enum):
    CHARACTER = "character"
    SCENE_BG = "scene_bg"
    PROP = "prop"


class AssetStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    DONE = "done"
    FAILED = "failed"


class Asset(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    asset_type: AssetType
    name: str
    description: str = ""
    visual_prompt: str = ""
    age: str = ""
    gender: str = ""
    appearance: str = ""
    personality: str = ""
    voice_id: str = ""
    thumbnail: str | None = None
    status: AssetStatus = AssetStatus.PENDING
    error: str = ""
    first_scene: int = 1
    created_at: str = ""
    updated_at: str = ""


class AssetStore(BaseModel):
    characters: list[Asset] = Field(default_factory=list)
    scene_bgs: list[Asset] = Field(default_factory=list)
    props: list[Asset] = Field(default_factory=list)


class AssetCreateRequest(BaseModel):
    asset_type: AssetType
    name: str
    description: str = ""
    visual_prompt: str = ""
    age: str = ""
    gender: str = ""
    appearance: str = ""
    personality: str = ""
    voice_id: str = ""
    thumbnail: str | None = None
    status: AssetStatus = AssetStatus.PENDING
    first_scene: int = 1


class AssetUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    visual_prompt: str | None = None
    age: str | None = None
    gender: str | None = None
    appearance: str | None = None
    personality: str | None = None
    voice_id: str | None = None
    thumbnail: str | None = None
    status: AssetStatus | None = None
    first_scene: int | None = None


ASSET_BUCKETS = {
    AssetType.CHARACTER: "characters",
    AssetType.SCENE_BG: "scene_bgs",
    AssetType.PROP: "props",
}

EXTRACT_PROMPT = """
从以下剧本中提取所有角色、场景背景和重要道具。

对每个角色输出：
- name: 角色名（中文）
- age: 年龄或年龄段（如"20岁"、"中年"）
- gender: 性别
- appearance: 外貌描述（用于 AI 绘图，包含发色、发型、服装、体型等）
- personality: 性格特点（1-2句）
- visual_prompt: 英文绘图 prompt（anime style, 外貌关键词）
- first_scene: 首次出现的场景序号

对每个场景背景输出：
- name: 场景名
- description: 场景描述
- visual_prompt: 英文绘图 prompt

对每个重要道具输出：
- name: 道具名
- description: 道具描述
- visual_prompt: 英文绘图 prompt

剧本内容：
{script_text}

以 JSON 格式输出，结构为：
{{"characters": [...], "scene_bgs": [...], "props": [...]}}
""".strip()


def utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def project_dir(project_id: str) -> Path:
    return WORKSPACE / project_id


def project_file(project_id: str) -> Path:
    return project_dir(project_id) / "project.json"


def assets_file(project_id: str) -> Path:
    return project_dir(project_id) / "assets.json"


def project_lock(project_id: str) -> threading.Lock:
    with _ASSET_LOCKS_GUARD:
        if project_id not in _ASSET_LOCKS:
            _ASSET_LOCKS[project_id] = threading.Lock()
        return _ASSET_LOCKS[project_id]


def ensure_project_exists(project_id: str) -> None:
    if not project_file(project_id).is_file():
        raise FileNotFoundError(project_id)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def empty_asset_store() -> AssetStore:
    return AssetStore(characters=[], scene_bgs=[], props=[])


def asset_bucket(asset_type: AssetType) -> str:
    return ASSET_BUCKETS[asset_type]


def asset_store_schema_example() -> dict[str, list]:
    return empty_asset_store().model_dump(mode="json")


def _coerce_first_scene(value: object) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 1
    return max(1, number)


def _normalize_asset(raw: object, asset_type: AssetType) -> Asset | None:
    payload = raw if isinstance(raw, dict) else {}
    name = str(payload.get("name") or "").strip()
    if not name:
        return None
    now = utc_iso()
    raw_status = payload.get("status")
    status = raw_status if isinstance(raw_status, AssetStatus) else AssetStatus(str(raw_status or AssetStatus.PENDING.value))
    return Asset(
        id=str(payload.get("id") or uuid.uuid4().hex[:8]).strip() or uuid.uuid4().hex[:8],
        asset_type=asset_type,
        name=name,
        description=str(payload.get("description") or "").strip(),
        visual_prompt=str(payload.get("visual_prompt") or "").strip(),
        age=str(payload.get("age") or "").strip(),
        gender=str(payload.get("gender") or "").strip(),
        appearance=str(payload.get("appearance") or "").strip(),
        personality=str(payload.get("personality") or "").strip(),
        voice_id=str(payload.get("voice_id") or "").strip(),
        thumbnail=str(payload.get("thumbnail")).strip() if payload.get("thumbnail") not in (None, "") else None,
        status=status,
        first_scene=_coerce_first_scene(payload.get("first_scene")),
        created_at=str(payload.get("created_at") or now).strip(),
        updated_at=str(payload.get("updated_at") or now).strip(),
    )


def _normalize_store(payload: object) -> AssetStore:
    source = payload if isinstance(payload, dict) else {}
    store = empty_asset_store()
    for asset_type, bucket in ASSET_BUCKETS.items():
        assets: list[Asset] = []
        raw_items = source.get(bucket) if isinstance(source.get(bucket), list) else []
        for raw in raw_items:
            try:
                asset = _normalize_asset(raw, asset_type)
            except ValueError:
                continue
            if asset is not None:
                assets.append(asset)
        setattr(store, bucket, assets)
    return store


def load_asset_store(project_id: str) -> AssetStore:
    ensure_project_exists(project_id)
    path = assets_file(project_id)
    if not path.exists():
        store = empty_asset_store()
        save_asset_store(project_id, store)
        return store
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        store = empty_asset_store()
        save_asset_store(project_id, store)
        return store
    store = _normalize_store(payload)
    if store.model_dump(mode="json") != payload:
        save_asset_store(project_id, store)
    return store


def save_asset_store(project_id: str, store: AssetStore) -> AssetStore:
    ensure_project_exists(project_id)
    atomic_write_json(assets_file(project_id), store.model_dump(mode="json"))
    return store


def _find_asset(store: AssetStore, asset_id: str) -> tuple[str, int, Asset]:
    for bucket in ASSET_BUCKETS.values():
        items = getattr(store, bucket)
        for index, asset in enumerate(items):
            if asset.id == asset_id:
                return bucket, index, asset
    raise KeyError(asset_id)


def list_project_assets(project_id: str) -> AssetStore:
    with project_lock(project_id):
        return load_asset_store(project_id)


def create_project_asset(project_id: str, payload: AssetCreateRequest | dict[str, Any]) -> Asset:
    request = payload if isinstance(payload, AssetCreateRequest) else AssetCreateRequest.model_validate(payload)
    with project_lock(project_id):
        store = load_asset_store(project_id)
        now = utc_iso()
        asset = Asset(
            asset_type=request.asset_type,
            name=request.name.strip(),
            description=request.description.strip(),
            visual_prompt=request.visual_prompt.strip(),
            age=request.age.strip(),
            gender=request.gender.strip(),
            appearance=request.appearance.strip(),
            personality=request.personality.strip(),
            voice_id=request.voice_id.strip(),
            thumbnail=request.thumbnail,
            status=request.status,
            first_scene=_coerce_first_scene(request.first_scene),
            created_at=now,
            updated_at=now,
        )
        getattr(store, asset_bucket(asset.asset_type)).append(asset)
        save_asset_store(project_id, store)
        return asset


def update_project_asset(project_id: str, asset_id: str, payload: AssetUpdateRequest | dict[str, Any]) -> Asset:
    request = payload if isinstance(payload, AssetUpdateRequest) else AssetUpdateRequest.model_validate(payload)
    with project_lock(project_id):
        store = load_asset_store(project_id)
        bucket, index, asset = _find_asset(store, asset_id)
        updated = asset.model_dump(mode="json")
        for key, value in request.model_dump(exclude_none=True, mode="json").items():
            updated[key] = value.strip() if isinstance(value, str) else value
        updated["id"] = asset.id
        updated["asset_type"] = asset.asset_type.value
        updated["created_at"] = asset.created_at
        updated["updated_at"] = utc_iso()
        replacement = _normalize_asset(updated, asset.asset_type)
        if replacement is None:
            raise ValueError("Asset name is required")
        getattr(store, bucket)[index] = replacement
        save_asset_store(project_id, store)
        return replacement


def delete_project_asset(project_id: str, asset_id: str) -> AssetStore:
    with project_lock(project_id):
        store = load_asset_store(project_id)
        bucket, index, _asset = _find_asset(store, asset_id)
        del getattr(store, bucket)[index]
        save_asset_store(project_id, store)
        return store


def update_asset_status(project_id: str, asset_id: str, status: AssetStatus) -> Asset:
    return update_project_asset(project_id, asset_id, {"status": status})


def load_project_story_text(project_id: str) -> str:
    ensure_project_exists(project_id)
    payload = json.loads(project_file(project_id).read_text(encoding="utf-8"))
    story_text = str(payload.get("story_text") or "").strip()
    if story_text:
        return story_text
    scene_lines: list[str] = []
    for scene in payload.get("scenes") if isinstance(payload.get("scenes"), list) else []:
        if not isinstance(scene, dict):
            continue
        title = str(scene.get("title") or "").strip()
        visual = str(scene.get("visual_prompt") or "").strip()
        dialogue = str(scene.get("dialogue") or "").strip()
        scene_lines.append("\n".join(part for part in (title, visual, dialogue) if part).strip())
    return "\n\n".join(line for line in scene_lines if line).strip()


def _call_asset_extract_llm(script_text: str) -> dict[str, Any]:
    load_env_file()
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "").strip().rstrip("/")
    model = os.environ.get("LLM_MODEL", "").strip()
    if not api_key or not base_url or not model:
        raise RuntimeError("Missing LLM_API_KEY, LLM_BASE_URL, or LLM_MODEL. Configure .env before extracting assets.")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是动漫短剧资产拆解助手。只输出 JSON，不要 Markdown，不要解释。"},
            {"role": "user", "content": EXTRACT_PROMPT.format(script_text=script_text)},
        ],
        "temperature": 0.2,
    }
    body = post_llm_chat_completion(base_url, api_key, payload)
    response_json = json.loads(body)
    content = response_json["choices"][0]["message"]["content"]
    parsed = extract_json_object(content)
    return parsed if isinstance(parsed, dict) else {}


def _asset_name_key(value: object) -> str:
    return str(value or "").strip().lower()


def _raw_asset_to_create_payload(raw: object, asset_type: AssetType) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    return {
        "asset_type": asset_type,
        "name": name,
        "description": str(raw.get("description") or "").strip(),
        "visual_prompt": str(raw.get("visual_prompt") or "").strip(),
        "age": str(raw.get("age") or "").strip(),
        "gender": str(raw.get("gender") or "").strip(),
        "appearance": str(raw.get("appearance") or "").strip(),
        "personality": str(raw.get("personality") or "").strip(),
        "voice_id": str(raw.get("voice_id") or "").strip(),
        "first_scene": _coerce_first_scene(raw.get("first_scene")),
    }


def _fallback_asset_payloads(project_id: str) -> dict[str, list[dict[str, Any]]]:
    from backend.project_runtime import load_project

    project = load_project(project_id)
    payloads: dict[str, list[dict[str, Any]]] = {"characters": [], "scene_bgs": [], "props": []}

    characters = project.get("characters") if isinstance(project.get("characters"), list) else []
    for raw in characters:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
        payloads["characters"].append(
            {
                "asset_type": AssetType.CHARACTER,
                "name": name,
                "description": str(raw.get("summary") or raw.get("description") or "").strip(),
                "visual_prompt": " ".join(
                    part
                    for part in [
                        str(raw.get("appearance_core") or "").strip(),
                        str(raw.get("clothing_style") or "").strip(),
                        str(raw.get("description") or "").strip(),
                    ]
                    if part
                ).strip(),
                "age": str(meta.get("age") or "").strip(),
                "gender": str(meta.get("gender") or meta.get("sex") or "").strip(),
                "appearance": str(raw.get("appearance_core") or "").strip(),
                "personality": str(raw.get("summary") or "").strip(),
                "voice_id": str(raw.get("voice_id") or raw.get("voice_profile") or "").strip(),
                "first_scene": _coerce_first_scene(raw.get("first_scene")),
            }
        )

    scenes = project.get("scenes") if isinstance(project.get("scenes"), list) else []
    for raw in scenes:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("title") or raw.get("scene_id") or "").strip()
        if not name:
            continue
        payloads["scene_bgs"].append(
            {
                "asset_type": AssetType.SCENE_BG,
                "name": name,
                "description": str(raw.get("visual_prompt") or raw.get("dialogue") or "").strip(),
                "visual_prompt": str(raw.get("visual_prompt") or raw.get("title") or "").strip(),
                "first_scene": _coerce_first_scene(raw.get("order")),
            }
        )

    return payloads


def extract_assets_from_script(project_id: str, script_text: str) -> dict[str, Any]:
    clean_script = str(script_text or "").strip()
    if not clean_script:
        raise ValueError("Script text is empty")
    try:
        parsed = _call_asset_extract_llm(clean_script)
    except Exception:
        parsed = _fallback_asset_payloads(project_id)
    added_counts = {"characters": 0, "scene_bgs": 0, "props": 0}
    skipped_counts = {"characters": 0, "scene_bgs": 0, "props": 0}
    with project_lock(project_id):
        store = load_asset_store(project_id)
        for asset_type, bucket in ASSET_BUCKETS.items():
            existing_names = {_asset_name_key(asset.name) for asset in getattr(store, bucket)}
            raw_items = parsed.get(bucket) if isinstance(parsed.get(bucket), list) else []
            for raw in raw_items:
                payload = _raw_asset_to_create_payload(raw, asset_type)
                if payload is None:
                    continue
                name_key = _asset_name_key(payload["name"])
                if name_key in existing_names:
                    skipped_counts[bucket] += 1
                    continue
                now = utc_iso()
                asset = Asset(
                    **payload,
                    status=AssetStatus.PENDING,
                    created_at=now,
                    updated_at=now,
                )
                getattr(store, bucket).append(asset)
                existing_names.add(name_key)
                added_counts[bucket] += 1
        save_asset_store(project_id, store)
    return {
        "project_id": project_id,
        "added_counts": added_counts,
        "skipped_counts": skipped_counts,
        "assets": store.model_dump(mode="json"),
    }


asset_router = APIRouter(prefix="/api/projects/{project_id}/assets", tags=["assets"])


@asset_router.get("")
def list_assets_endpoint(project_id: str) -> dict[str, Any]:
    try:
        return list_project_assets(project_id).model_dump(mode="json")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


@asset_router.post("")
def create_asset_endpoint(project_id: str, payload: AssetCreateRequest) -> dict[str, Any]:
    try:
        asset = create_project_asset(project_id, payload)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return asset.model_dump(mode="json")


@asset_router.put("/{asset_id}")
def update_asset_endpoint(project_id: str, asset_id: str, payload: AssetUpdateRequest) -> dict[str, Any]:
    try:
        asset = update_project_asset(project_id, asset_id, payload)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except KeyError:
        raise HTTPException(status_code=404, detail="Asset not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return asset.model_dump(mode="json")


@asset_router.delete("/{asset_id}")
def delete_asset_endpoint(project_id: str, asset_id: str) -> dict[str, Any]:
    try:
        store = delete_project_asset(project_id, asset_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except KeyError:
        raise HTTPException(status_code=404, detail="Asset not found")
    return store.model_dump(mode="json")


@asset_router.post("/extract")
def extract_assets_endpoint(project_id: str) -> dict[str, Any]:
    try:
        script_text = load_project_story_text(project_id)
        return extract_assets_from_script(project_id, script_text)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@asset_router.post("/{asset_id}/generate")
def generate_asset_endpoint(project_id: str, asset_id: str) -> dict[str, Any]:
    from backend.asset_generation import _check_comfyui_online

    if not _check_comfyui_online():
        raise HTTPException(
            status_code=503,
            detail="ComfyUI 服务不可达。请确认 ComfyUI 已启动，或 SSH 隧道已连接到远程 GPU 服务器。",
        )
    try:
        asset = update_asset_status(project_id, asset_id, AssetStatus.GENERATING)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except KeyError:
        raise HTTPException(status_code=404, detail="Asset not found")
    from backend.asset_generation import generate_asset_image

    def _run() -> None:
        try:
            generate_asset_image(project_id, asset_id)
        except Exception as exc:
            logger.error("generation failed for %s/%s: %s", project_id, asset_id, exc)

    threading.Thread(target=_run, daemon=True).start()
    return {
        "status": asset.status.value,
        "asset": asset.model_dump(mode="json"),
        "message": "生成任务已提交",
    }


@asset_router.post("/generate-all")
def generate_all_assets_endpoint(project_id: str) -> dict[str, Any]:
    from backend.asset_generation import _check_comfyui_online

    if not _check_comfyui_online():
        raise HTTPException(
            status_code=503,
            detail="ComfyUI 服务不可达。请确认 ComfyUI 已启动，或 SSH 隧道已连接到远程 GPU 服务器。",
        )
    try:
        with project_lock(project_id):
            store = load_asset_store(project_id)
            for bucket in ASSET_BUCKETS.values():
                items = getattr(store, bucket)
                for index, asset in enumerate(items):
                    replacement = asset.model_copy(update={"status": AssetStatus.GENERATING, "updated_at": utc_iso()})
                    items[index] = replacement
            save_asset_store(project_id, store)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    from backend.asset_generation import generate_all_assets

    def _run() -> None:
        try:
            generate_all_assets(project_id)
        except Exception as exc:
            logger.error("batch generation failed for %s: %s", project_id, exc)

    threading.Thread(target=_run, daemon=True).start()
    return {
        "status": "queued",
        "assets": store.model_dump(mode="json"),
        "message": "批量生成任务已提交",
    }
