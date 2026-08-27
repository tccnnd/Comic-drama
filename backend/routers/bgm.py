from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.routers._common import ROOT

router = APIRouter(tags=["bgm"])


class BgmUploadRequest(BaseModel):
    filename: str
    style: str = "neutral"
    data_url: str


@router.get("/api/bgm-library")
def bgm_library() -> dict:
    """List available BGM files organized by style."""
    bgm_root = ROOT / "assets" / "audio" / "bgm"
    library: dict[str, list[dict]] = {}
    if bgm_root.exists():
        for style_dir in sorted(bgm_root.iterdir()):
            if style_dir.is_dir() and not style_dir.name.startswith("_"):
                files = []
                for f in sorted(style_dir.iterdir()):
                    if f.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}:
                        files.append({
                            "name": f.stem,
                            "path": f"assets/audio/bgm/{style_dir.name}/{f.name}",
                            "size_kb": round(f.stat().st_size / 1024, 1),
                        })
                if files:
                    library[style_dir.name] = files
    return {"library": library, "root": str(bgm_root)}


@router.post("/api/bgm-upload")
def upload_bgm(payload: BgmUploadRequest) -> dict:
    """Upload a BGM file to the library."""
    if "," not in payload.data_url:
        raise HTTPException(status_code=400, detail="Invalid data URL")
    _, encoded = payload.data_url.split(",", 1)
    import binascii
    try:
        raw = base64.b64decode(encoded)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid base64") from exc

    # File size limit (10 MB)
    MAX_BGM_SIZE = 10 * 1024 * 1024
    if len(raw) > MAX_BGM_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    # Validate style parameter against allowed values (path traversal prevention)
    ALLOWED_BGM_STYLES = {
        "neutral", "happy", "sad", "tense", "epic", "romantic",
        "mysterious", "comedic", "dramatic", "action",
    }
    style = (payload.style or "neutral").strip().lower()
    if not style:
        style = "neutral"
    # Allow only known styles plus alphanumeric underscore names (for custom styles)
    if not re.match(r"^[a-zA-Z0-9_-]+$", style) or style in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid style name")
    # If style is not in allowed list, still accept but enforce directory depth of 1
    bgm_dir = ROOT / "assets" / "audio" / "bgm" / style
    # Double-check the resolved path stays within bgm directory
    bgm_root = (ROOT / "assets" / "audio" / "bgm").resolve()
    resolved_dir = bgm_dir.resolve()
    if resolved_dir != bgm_root and bgm_root not in resolved_dir.parents:
        raise HTTPException(status_code=400, detail="Invalid style path")
    bgm_dir.mkdir(parents=True, exist_ok=True)

    # Validate file type by extension + magic bytes
    ALLOWED_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}
    safe_name = re.sub(r"[^a-zA-Z0-9_\-.]", "_", payload.filename.strip())
    if not safe_name:
        safe_name = f"bgm_{uuid.uuid4().hex[:8]}.mp3"
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

    # Quick magic byte check for common audio formats
    if ext == ".mp3" and len(raw) >= 3:
        # ID3v2 header or MP3 sync word
        if not (raw[:3] == b"ID3" or (raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0)):
            raise HTTPException(status_code=400, detail="File does not appear to be a valid MP3")
    elif ext == ".wav" and len(raw) >= 12:
        if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
            raise HTTPException(status_code=400, detail="File does not appear to be a valid WAV")
    elif ext == ".ogg" and len(raw) >= 4:
        if raw[:4] != b"OggS":
            raise HTTPException(status_code=400, detail="File does not appear to be a valid OGG")

    out_path = bgm_dir / safe_name
    out_path.write_bytes(raw)

    return {
        "path": f"assets/audio/bgm/{style}/{safe_name}",
        "style": style,
        "size_kb": round(out_path.stat().st_size / 1024, 1),
    }
