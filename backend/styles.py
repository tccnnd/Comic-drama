from __future__ import annotations

import json
import re
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
STYLES_PATH = DATA_DIR / "styles.json"

StyleCategory = Literal["system", "user"]

_STYLE_LOCK = threading.Lock()


class StyleRecord(BaseModel):
    id: str
    name: str
    category: StyleCategory = "user"
    positive_suffix: str = ""
    negative_suffix: str = ""
    thumbnail: str = ""
    checkpoint_hint: str = ""
    lora_hint: str = ""


class StyleStore(BaseModel):
    default_style_id: str = ""
    styles: list[StyleRecord] = Field(default_factory=list)


class StyleCreateRequest(BaseModel):
    id: str | None = None
    name: str
    positive_suffix: str = ""
    negative_suffix: str = ""
    thumbnail: str = ""
    checkpoint_hint: str = ""
    lora_hint: str = ""


class StyleUpdateRequest(BaseModel):
    name: str | None = None
    positive_suffix: str | None = None
    negative_suffix: str | None = None
    thumbnail: str | None = None
    checkpoint_hint: str | None = None
    lora_hint: str | None = None


def utc_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "style"


def _style_defaults() -> list[dict[str, str]]:
    return [
        {
            "id": "anime_standard",
            "name": "日系动画",
            "category": "system",
            "positive_suffix": "anime key visual, studio anime style, cel shading, clean thin lines, flat colors, cinematic lighting, detailed background",
            "negative_suffix": "photorealistic, realistic skin, 3d render, photograph, noisy, blurry, low quality",
            "thumbnail": "styles/anime_standard.png",
            "checkpoint_hint": "Anything-v5.0-PRT.safetensors",
            "lora_hint": "anime-character-lora_v1.5.safetensors",
        },
        {
            "id": "manhwa_soft",
            "name": "韩漫唯美",
            "category": "system",
            "positive_suffix": "manhwa style, soft shading, pastel colors, elegant faces, glossy eyes, warm rim light, romantic atmosphere",
            "negative_suffix": "photorealistic, harsh contrast, muddy colors, distorted hands, low detail, 3d render",
            "thumbnail": "styles/manhwa_soft.png",
            "checkpoint_hint": "manhwa-soft-v1.safetensors",
            "lora_hint": "manhwa-aesthetic-lora.safetensors",
        },
        {
            "id": "gongfeng",
            "name": "纯正国风",
            "category": "system",
            "positive_suffix": "chinese ink painting, traditional chinese art, hanfu, elegant composition, brush texture, misty atmosphere, classical beauty",
            "negative_suffix": "photorealistic, western comic, neon colors, 3d render, plastic skin, blurry brushwork",
            "thumbnail": "styles/gongfeng.png",
            "checkpoint_hint": "guofeng-illustration.safetensors",
            "lora_hint": "hanfu-ink-lora.safetensors",
        },
        {
            "id": "neon_action",
            "name": "激燃极光",
            "category": "system",
            "positive_suffix": "dynamic lighting, neon glow, action scene, dramatic shadows, motion energy, sharp contrast, explosive composition",
            "negative_suffix": "static pose, soft pastel, dull lighting, low energy, flat composition, blurry motion",
            "thumbnail": "styles/neon_action.png",
            "checkpoint_hint": "action-neon-v2.safetensors",
            "lora_hint": "combat-intensity-lora.safetensors",
        },
        {
            "id": "western_comic",
            "name": "美漫硬朗",
            "category": "system",
            "positive_suffix": "western comic style, bold lines, strong shadows, heroic composition, high contrast, graphic storytelling",
            "negative_suffix": "anime style, watercolor, soft pastel, photorealistic, blurry outlines, low contrast",
            "thumbnail": "styles/western_comic.png",
            "checkpoint_hint": "western-comic-v1.safetensors",
            "lora_hint": "bold-ink-lora.safetensors",
        },
        {
            "id": "semi_realistic",
            "name": "写实画报",
            "category": "system",
            "positive_suffix": "semi-realistic, detailed illustration, magazine quality, clean skin texture, cinematic portrait, refined lighting",
            "negative_suffix": "cartoonish, exaggerated proportions, low detail, flat face, blurry background, toy-like",
            "thumbnail": "styles/semi_realistic.png",
            "checkpoint_hint": "realistic-illustration-v1.safetensors",
            "lora_hint": "editorial-portrait-lora.safetensors",
        },
        {
            "id": "picture_book",
            "name": "治愈绘本",
            "category": "system",
            "positive_suffix": "children book illustration, warm colors, soft edges, watercolor texture, friendly atmosphere, comforting composition",
            "negative_suffix": "dark horror, harsh shadows, photorealistic, metallic texture, noisy details, cold palette",
            "thumbnail": "styles/picture_book.png",
            "checkpoint_hint": "picture-book-v1.safetensors",
            "lora_hint": "watercolor-soft-lora.safetensors",
        },
        {
            "id": "claymation",
            "name": "趣味黏土",
            "category": "system",
            "positive_suffix": "claymation style, 3d clay figure, soft lighting, miniature set, handcrafted texture, playful charm",
            "negative_suffix": "photorealistic, metallic shine, flat cartoon, noisy surface, high detail skin pores",
            "thumbnail": "styles/claymation.png",
            "checkpoint_hint": "claymation-toy-v1.safetensors",
            "lora_hint": "miniature-clay-lora.safetensors",
        },
        {
            "id": "blindbox_3d",
            "name": "3D盲盒",
            "category": "system",
            "positive_suffix": "3d chibi figure, blind box toy, studio lighting, simple background, collectible figure, glossy finish",
            "negative_suffix": "photorealistic, realistic adult proportions, dark background, complex clutter, flat illustration",
            "thumbnail": "styles/blindbox_3d.png",
            "checkpoint_hint": "blindbox-figure-v1.safetensors",
            "lora_hint": "chibi-collectible-lora.safetensors",
        },
        {
            "id": "one_piece_style",
            "name": "海贼王风格",
            "category": "system",
            "positive_suffix": "one piece anime style, bold outlines, exaggerated proportions, energetic expressions, adventurous mood, colorful action",
            "negative_suffix": "photorealistic, subdued colors, realistic anatomy, thin outlines, flat emotion, dark realism",
            "thumbnail": "styles/one_piece_style.png",
            "checkpoint_hint": "shonen-adventure-v1.safetensors",
            "lora_hint": "shonen-exaggeration-lora.safetensors",
        },
    ]


def _normalize_style_record(raw: object) -> StyleRecord:
    payload = raw if isinstance(raw, dict) else {}
    name = str(payload.get("name") or "").strip()
    record_id = str(payload.get("id") or "").strip() or utc_slug(name)
    return StyleRecord(
        id=record_id,
        name=name or record_id,
        category="system" if str(payload.get("category") or "").strip() == "system" else "user",
        positive_suffix=str(payload.get("positive_suffix") or "").strip(),
        negative_suffix=str(payload.get("negative_suffix") or "").strip(),
        thumbnail=str(payload.get("thumbnail") or "").strip(),
        checkpoint_hint=str(payload.get("checkpoint_hint") or "").strip(),
        lora_hint=str(payload.get("lora_hint") or "").strip(),
    )


def _default_store() -> StyleStore:
    styles = [_normalize_style_record(item) for item in _style_defaults()]
    return StyleStore(default_style_id=styles[0].id if styles else "", styles=styles)


def _load_raw_store() -> dict[str, Any]:
    if not STYLES_PATH.exists():
        store = _default_store()
        save_style_store(store)
        return store.model_dump()
    try:
        payload = json.loads(STYLES_PATH.read_text(encoding="utf-8"))
    except Exception:
        store = _default_store()
        save_style_store(store)
        return store.model_dump()
    if not isinstance(payload, dict):
        store = _default_store()
        save_style_store(store)
        return store.model_dump()
    return payload


def load_style_store() -> StyleStore:
    payload = _load_raw_store()
    styles = payload.get("styles") if isinstance(payload.get("styles"), list) else []
    normalized_styles = [_normalize_style_record(item) for item in styles]
    if not normalized_styles:
        return _default_store()
    default_style_id = str(payload.get("default_style_id") or payload.get("selected_style_id") or "").strip()
    if default_style_id not in {style.id for style in normalized_styles}:
        default_style_id = normalized_styles[0].id
    store = StyleStore(default_style_id=default_style_id, styles=normalized_styles)
    if store.model_dump() != payload:
        save_style_store(store)
    return store


def save_style_store(store: StyleStore | dict[str, Any]) -> StyleStore:
    normalized = store if isinstance(store, StyleStore) else StyleStore.model_validate(store)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = STYLES_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(normalized.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(STYLES_PATH)
    return normalized


def list_styles() -> StyleStore:
    with _STYLE_LOCK:
        return load_style_store()


def get_style(style_id: str) -> StyleRecord:
    style_id = str(style_id or "").strip()
    if not style_id:
        raise KeyError("Style id is required")
    store = list_styles()
    for style in store.styles:
        if style.id == style_id:
            return style
    raise KeyError(style_id)


def get_default_style_id() -> str:
    store = list_styles()
    if store.default_style_id:
        try:
            get_style(store.default_style_id)
            return store.default_style_id
        except KeyError:
            pass
    if not store.styles:
        raise KeyError("No styles available")
    return store.styles[0].id


def create_style(payload: StyleCreateRequest | dict[str, Any]) -> StyleRecord:
    request = payload if isinstance(payload, StyleCreateRequest) else StyleCreateRequest.model_validate(payload)
    with _STYLE_LOCK:
        store = load_style_store()
        style_id = str(request.id or "").strip() or utc_slug(request.name)
        if any(style.id == style_id for style in store.styles):
            raise ValueError(f"Style already exists: {style_id}")
        record = StyleRecord(
            id=style_id,
            name=request.name.strip(),
            category="user",
            positive_suffix=request.positive_suffix.strip(),
            negative_suffix=request.negative_suffix.strip(),
            thumbnail=request.thumbnail.strip(),
            checkpoint_hint=request.checkpoint_hint.strip(),
            lora_hint=request.lora_hint.strip(),
        )
        store.styles.append(record)
        save_style_store(store)
        return record


def update_style(style_id: str, payload: StyleUpdateRequest | dict[str, Any]) -> StyleRecord:
    request = payload if isinstance(payload, StyleUpdateRequest) else StyleUpdateRequest.model_validate(payload)
    with _STYLE_LOCK:
        store = load_style_store()
        for index, style in enumerate(store.styles):
            if style.id != style_id:
                continue
            updated = style.model_dump()
            for key, value in request.model_dump(exclude_none=True).items():
                updated[key] = str(value).strip()
            updated["id"] = style.id
            updated["category"] = style.category
            record = _normalize_style_record(updated)
            record.category = style.category
            store.styles[index] = record
            save_style_store(store)
            return record
    raise KeyError(style_id)


def delete_style(style_id: str) -> StyleStore:
    style_id = str(style_id or "").strip()
    if not style_id:
        raise KeyError("Style id is required")
    with _STYLE_LOCK:
        store = load_style_store()
        target = next((style for style in store.styles if style.id == style_id), None)
        if target is None:
            raise KeyError(style_id)
        if target.category != "user":
            raise ValueError("System styles cannot be deleted")
        store.styles = [style for style in store.styles if style.id != style_id]
        if store.default_style_id == style_id:
            store.default_style_id = store.styles[0].id if store.styles else ""
        save_style_store(store)
        return store


def _style_response(style: StyleRecord, store: StyleStore | None = None) -> dict[str, Any]:
    payload = style.model_dump()
    if store is not None:
        payload["default_style_id"] = store.default_style_id
    return payload


style_router = APIRouter(prefix="/api/styles", tags=["styles"])


@style_router.get("")
def list_styles_endpoint() -> dict[str, Any]:
    store = list_styles()
    return store.model_dump()


@style_router.post("")
def create_style_endpoint(payload: StyleCreateRequest) -> dict[str, Any]:
    try:
        style = create_style(payload)
        store = list_styles()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _style_response(style, store)


@style_router.put("/{style_id}")
def update_style_endpoint(style_id: str, payload: StyleUpdateRequest) -> dict[str, Any]:
    try:
        style = update_style(style_id, payload)
        store = list_styles()
    except KeyError:
        raise HTTPException(status_code=404, detail="Style not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _style_response(style, store)


@style_router.delete("/{style_id}")
def delete_style_endpoint(style_id: str) -> dict[str, Any]:
    try:
        store = delete_style(style_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Style not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return store.model_dump()


DATA_DIR.mkdir(parents=True, exist_ok=True)
if not STYLES_PATH.exists():
    save_style_store(_default_store())
