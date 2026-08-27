from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.logger import get_logger
from backend.routers._common import OUTPUTS
from scripts.run_workflow import load_voice_presets, voice_presets_path
from scripts.tts_engines import (
    edge_tts,
    load_tts_provider_settings,
    save_tts_provider_settings,
    synthesize_preview,
    tts_diagnostics,
    tts_provider_settings_path,
)

logger = get_logger(__name__)

router = APIRouter(tags=["voice"])

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


class VoicePresetItem(BaseModel):
    profile: str = ""
    voice: str = ""


class VoicePresetSaveRequest(BaseModel):
    default: str | None = None
    items: list[VoicePresetItem] = Field(default_factory=list)


class VoicePreviewRequest(BaseModel):
    voice: str
    text: str = Field(default="这是一次漫剧配音试听。", min_length=1, max_length=120)
    engine: Literal[
        "auto", "edge", "local", "silent", "cosyvoice", "gpt_sovits", "fish", "indextts"
    ] = "auto"
    rate: float = Field(default=1.0, ge=0.1, le=5.0)
    pitch: float = Field(default=0.0, ge=-24.0, le=24.0)
    volume: float = Field(default=1.0, ge=0.0, le=5.0)
    voice_id: str = ""
    reference_audio_path: str = ""
    reference_text: str = ""
    emotion: str = ""


class TTSProviderSettingsRequest(BaseModel):
    cosyvoice: str = ""
    gpt_sovits: str = ""
    fish: str = ""
    indextts: str = ""


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
                VOICE_CATALOG_CACHE.write_text(
                    json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                return catalog
        except Exception as exc:
            logger.error("Failed to load live voice catalog: %s", exc)

    return DEFAULT_VOICE_CATALOG


@router.get("/api/voice-presets")
def voice_presets() -> dict:
    return format_voice_presets(load_voice_presets())


@router.get("/api/voice-catalog")
async def voice_catalog() -> dict:
    return {"items": await load_voice_catalog_data()}


@router.get("/api/tts-diagnostics")
def tts_diagnostics_endpoint() -> dict:
    return tts_diagnostics()


@router.get("/api/tts-providers")
def tts_providers_endpoint() -> dict:
    return {
        "providers": load_tts_provider_settings(),
        "config_path": str(tts_provider_settings_path()),
    }


@router.put("/api/voice-presets")
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


@router.put("/api/tts-providers")
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


@router.post("/api/voice-preview")
def create_voice_preview(payload: VoicePreviewRequest) -> dict:
    voice = payload.voice.strip()
    text = payload.text.strip()
    if not voice:
        raise HTTPException(status_code=400, detail="Voice is required")
    if payload.engine == "edge" and not re.match(r"^[A-Za-z0-9-]+Neural$", voice):
        raise HTTPException(status_code=400, detail="Invalid Edge TTS voice name")

    logger.info(
        "[voice-preview] engine=%s voice=%s voice_id=%s ref_audio=%s emotion=%s",
        payload.engine,
        voice,
        payload.voice_id,
        payload.reference_audio_path,
        payload.emotion,
    )

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
