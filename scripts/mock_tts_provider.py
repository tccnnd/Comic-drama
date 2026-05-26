from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import tts_engines


PROVIDER_VOICE_HINTS = {
    "cosyvoice": "Xiaoxiao",
    "gpt_sovits": "Yunxi",
    "fish": "Yunjian",
    "indextts": "Yunyang",
}

PROVIDER_RATE_HINTS = {
    "cosyvoice": 1.00,
    "gpt_sovits": 0.96,
    "fish": 1.05,
    "indextts": 0.92,
}

PROVIDER_VOLUME_HINTS = {
    "cosyvoice": 1.00,
    "gpt_sovits": 0.98,
    "fish": 1.02,
    "indextts": 1.00,
}


class MockTTSRequest(BaseModel):
    text: str = Field(default="", min_length=1)
    voice: str = ""
    provider: str = ""
    engine: str = ""
    voice_id: str = ""
    reference_audio_path: str = ""
    reference_text: str = ""
    emotion: str = ""
    rate: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch: float = Field(default=0.0, ge=-24.0, le=24.0)
    volume: float = Field(default=1.0, ge=0.0, le=2.0)


app = FastAPI(title="Comic Drama Mock TTS Provider", version="0.1.0")
OUTPUTS = ROOT / "outputs"
OUTPUTS.mkdir(parents=True, exist_ok=True)


def normalize_provider(value: str) -> str:
    provider = (value or "").strip().lower()
    return provider if provider in PROVIDER_VOICE_HINTS else "cosyvoice"


def resolve_voice_hint(provider: str, payload: MockTTSRequest) -> str:
    if payload.voice_id.strip():
        return payload.voice_id.strip()
    if payload.voice.strip():
        return payload.voice.strip()
    return PROVIDER_VOICE_HINTS.get(provider, "Xiaoxiao")


def resolve_rate(provider: str, requested: float) -> float:
    return max(0.5, min(2.0, float(requested) * PROVIDER_RATE_HINTS.get(provider, 1.0)))


def resolve_volume(provider: str, requested: float) -> float:
    return max(0.0, min(2.0, float(requested) * PROVIDER_VOLUME_HINTS.get(provider, 1.0)))


def synthesize_mock_audio(provider: str, payload: MockTTSRequest) -> tuple[bytes, str]:
    text = payload.text.strip()
    preferred_voice = resolve_voice_hint(provider, payload)
    rate_scale = resolve_rate(provider, payload.rate)
    volume_scale = resolve_volume(provider, payload.volume)

    with tempfile.TemporaryDirectory(prefix=f"comic_drama_{provider}_", dir=str(OUTPUTS)) as tmpdir:
        out_path = Path(tmpdir) / "tts.wav"
        used_mode = "local"
        try:
            tts_engines.synthesize_local_tts(
                text,
                out_path,
                preferred_voice=preferred_voice,
                rate_scale=rate_scale,
                volume_scale=volume_scale,
            )
            if not tts_engines.valid_audio_file(out_path):
                raise RuntimeError("local synthesis produced an empty audio file")
        except Exception as exc:
            used_mode = "silent"
            duration = max(0.5, min(4.0, len(text) / 6))
            print(f"[mock-tts] {provider} local synthesis failed, using silence: {exc}")
            tts_engines.write_silent_wav(out_path, duration)
        return out_path.read_bytes(), used_mode


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/meta")
def meta() -> dict[str, object]:
    return {
        "name": "comic-drama-mock-tts",
        "supported_providers": sorted(PROVIDER_VOICE_HINTS),
        "request_fields": [
            "text",
            "voice",
            "provider",
            "engine",
            "voice_id",
            "reference_audio_path",
            "reference_text",
            "emotion",
            "rate",
            "pitch",
            "volume",
        ],
        "response": "audio/wav",
    }


@app.post("/tts")
def tts(request: Request, payload: MockTTSRequest) -> Response:
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    provider_header = request.headers.get("x-comic-drama-provider", "")
    provider = normalize_provider(provider_header or payload.provider or payload.engine)
    audio_bytes, mode = synthesize_mock_audio(provider, payload)
    headers = {
        "X-TTS-Provider": provider,
        "X-TTS-Mode": mode,
        "X-TTS-Voice": resolve_voice_hint(provider, payload),
    }
    return Response(content=audio_bytes, media_type="audio/wav", headers=headers)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Comic Drama mock TTS provider.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
