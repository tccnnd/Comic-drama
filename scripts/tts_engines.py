from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import wave
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

try:
    import edge_tts
except ImportError:  # optional dependency
    edge_tts = None

try:
    import pyttsx3
except ImportError:  # optional dependency
    pyttsx3 = None


SUPPORTED_ENGINES = {"auto", "edge", "local", "silent", "cosyvoice", "gpt_sovits", "fish", "indextts"}
EXTERNAL_PROVIDER_ENV = {
    "cosyvoice": "COSYVOICE_TTS_URL",
    "gpt_sovits": "GPT_SOVITS_TTS_URL",
    "fish": "FISH_TTS_URL",
    "indextts": "INDEXTTS_TTS_URL",
}
ROOT = Path(__file__).resolve().parents[1]
TTS_PROVIDER_SETTINGS_FILE = ROOT / "workspace" / "tts_provider_settings.json"


@dataclass
class TTSResult:
    path: Path
    engine: str
    requested_engine: str
    fallback: bool = False
    warnings: list[str] = field(default_factory=list)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def env_value(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def valid_audio_file(path: Path, min_bytes: int = 1024) -> bool:
    return path.exists() and path.stat().st_size > min_bytes


def tts_provider_settings_path() -> Path:
    return TTS_PROVIDER_SETTINGS_FILE


def load_tts_provider_settings() -> dict[str, str]:
    path = tts_provider_settings_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    settings: dict[str, str] = {}
    for engine in EXTERNAL_PROVIDER_ENV:
        value = str(data.get(engine) or "").strip()
        if value:
            settings[engine] = value
    return settings


def save_tts_provider_settings(settings: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for engine in EXTERNAL_PROVIDER_ENV:
        value = str(settings.get(engine) or "").strip()
        if value:
            normalized[engine] = value
    path = tts_provider_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return normalized


def normalize_engine_name(engine: str) -> str:
    value = (engine or "auto").strip().lower()
    if value in SUPPORTED_ENGINES:
        return value
    return "auto"


def is_external_engine(engine: str) -> bool:
    return normalize_engine_name(engine) in EXTERNAL_PROVIDER_ENV


def is_local_provider_endpoint(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    return parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def mock_external_voice_hint(engine: str, voice: str, voice_id: str = "") -> str:
    normalized = normalize_engine_name(engine)
    explicit = (voice_id or voice).strip()
    if explicit:
        return explicit
    return {
        "cosyvoice": "Xiaoxiao",
        "gpt_sovits": "Yunxi",
        "fish": "Yunjian",
        "indextts": "Yunyang",
    }.get(normalized, "")


def provider_url(engine: str) -> str:
    normalized = normalize_engine_name(engine)
    env_name = EXTERNAL_PROVIDER_ENV.get(normalized, "")
    configured = load_tts_provider_settings().get(normalized, "").strip()
    if configured:
        return configured
    return env_value(env_name, default="")


def configured_external_providers() -> dict[str, str]:
    return {
        engine: provider_url(engine)
        for engine in EXTERNAL_PROVIDER_ENV
        if provider_url(engine)
    }


def write_silent_wav(path: Path, duration: float, sample_rate: int = 44100) -> None:
    duration = max(0.25, float(duration))
    frame_count = int(math.ceil(duration * sample_rate))
    ensure_parent(path)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        silent = b"\x00\x00" * 2 * frame_count
        handle.writeframes(silent)


def format_edge_rate(rate: float) -> str:
    delta = int(round((float(rate) - 1.0) * 100))
    return f"{delta:+d}%"


def format_edge_volume(volume: float) -> str:
    delta = int(round((float(volume) - 1.0) * 100))
    return f"{delta:+d}%"


def format_edge_pitch(pitch: float) -> str:
    delta = float(pitch)
    sign = "+" if delta >= 0 else ""
    if float(delta).is_integer():
        return f"{sign}{int(delta)}Hz"
    return f"{sign}{delta}Hz"


async def synthesize_edge_tts_async(
    text: str,
    out_path: Path,
    voice: str,
    rate: float = 1.0,
    volume: float = 1.0,
    pitch: float = 0.0,
) -> None:
    if edge_tts is None:
        raise RuntimeError("edge-tts is not installed")
    ensure_parent(out_path)
    communicator = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=format_edge_rate(rate),
        volume=format_edge_volume(volume),
        pitch=format_edge_pitch(pitch),
    )
    await communicator.save(str(out_path))
    if not valid_audio_file(out_path):
        raise RuntimeError("Edge TTS produced an empty or unusable audio file")


def synthesize_edge_tts(
    text: str,
    out_path: Path,
    voice: str,
    rate: float = 1.0,
    volume: float = 1.0,
    pitch: float = 0.0,
) -> None:
    asyncio.run(synthesize_edge_tts_async(text, out_path, voice, rate=rate, volume=volume, pitch=pitch))


def local_tts_engine(preferred_voice: str = "", rate_scale: float = 1.0, volume_scale: float = 1.0):
    if pyttsx3 is None:
        raise RuntimeError("pyttsx3 is not installed")
    driver = env_value("TTS_DRIVER", default="sapi5" if os.name == "nt" else "")
    engine = pyttsx3.init(driverName=driver or None)
    rate = int(env_value("TTS_RATE", default="185"))
    engine.setProperty("rate", max(60, int(rate * max(0.25, float(rate_scale)))))
    volume = float(env_value("TTS_VOLUME", default="1.0"))
    engine.setProperty("volume", max(0.0, min(1.0, volume * max(0.0, float(volume_scale)))))
    preferred = preferred_voice or env_value("TTS_VOICE", default="")
    if preferred:
        for voice in engine.getProperty("voices"):
            if preferred.lower() in f"{voice.id} {voice.name}".lower():
                engine.setProperty("voice", voice.id)
                break
    return engine


def synthesize_windows_sapi_tts(
    text: str,
    out_path: Path,
    preferred_voice: str = "",
    rate_scale: float = 1.0,
    volume_scale: float = 1.0,
) -> None:
    try:
        import win32com.client
    except ImportError as exc:
        raise RuntimeError("pywin32 is required for Windows SAPI fallback") from exc

    ensure_parent(out_path)
    if out_path.exists():
        out_path.unlink()
    speaker = win32com.client.Dispatch("SAPI.SpVoice")
    voices = speaker.GetVoices()
    preferred = str(preferred_voice or "").lower()
    if preferred:
        for index in range(voices.Count):
            voice = voices.Item(index)
            description = str(voice.GetDescription())
            voice_id = str(voice.Id)
            if preferred in f"{description} {voice_id}".lower():
                speaker.Voice = voice
                break

    speaker.Rate = max(-10, min(10, int(round((float(rate_scale) - 1.0) * 10))))
    speaker.Volume = max(0, min(100, int(round(float(volume_scale) * 100))))
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    stream.Open(str(out_path.resolve()), 3, False)
    try:
        speaker.AudioOutputStream = stream
        speaker.Speak(text, 0)
    finally:
        stream.Close()


def synthesize_local_tts(
    text: str,
    out_path: Path,
    preferred_voice: str = "",
    rate_scale: float = 1.0,
    volume_scale: float = 1.0,
) -> None:
    ensure_parent(out_path)
    try:
        engine = local_tts_engine(preferred_voice, rate_scale=rate_scale, volume_scale=volume_scale)
        engine.save_to_file(text, str(out_path))
        engine.runAndWait()
        engine.stop()
        if valid_audio_file(out_path):
            return
        raise RuntimeError("pyttsx3 produced an empty or unusable audio file")
    except Exception as exc:
        if os.name != "nt":
            raise
        print(f"[tts] pyttsx3 unavailable, trying Windows SAPI fallback: {exc}")

    if os.name != "nt":
        raise RuntimeError("Local TTS failed and no platform fallback is available")
    synthesize_windows_sapi_tts(text, out_path, preferred_voice=preferred_voice, rate_scale=rate_scale, volume_scale=volume_scale)
    if not valid_audio_file(out_path):
        raise RuntimeError("Windows SAPI produced an empty or unusable audio file")


def synthesize_external_tts(
    engine: str,
    text: str,
    out_path: Path,
    voice: str,
    *,
    voice_id: str = "",
    reference_audio_path: str = "",
    reference_text: str = "",
    emotion: str = "",
    rate: float = 1.0,
    pitch: float = 0.0,
    volume: float = 1.0,
) -> None:
    normalized = normalize_engine_name(engine)
    endpoint = provider_url(normalized)
    if not endpoint:
        raise RuntimeError(f"{normalized} is not configured")

    ensure_parent(out_path)
    payload = {
        "text": text,
        "voice": voice,
        "provider": normalized,
        "voice_id": voice_id,
        "reference_audio_path": reference_audio_path,
        "reference_text": reference_text,
        "emotion": emotion,
        "rate": rate,
        "pitch": pitch,
        "volume": volume,
    }
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-Comic-Drama-Provider": normalized,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            body = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        if is_local_provider_endpoint(endpoint) and os.name == "nt":
            print(f"[tts] {normalized} local provider unreachable, using direct SAPI fallback: {exc}")
            synthesize_windows_sapi_tts(
                text,
                out_path,
                preferred_voice=mock_external_voice_hint(normalized, voice, voice_id),
                rate_scale=rate,
                volume_scale=volume,
            )
            if valid_audio_file(out_path):
                return
        raise RuntimeError(f"{normalized} request failed: {exc}") from exc

    if not body:
        if is_local_provider_endpoint(endpoint) and os.name == "nt":
            print(f"[tts] {normalized} local provider returned an empty body, using direct SAPI fallback")
            synthesize_windows_sapi_tts(
                text,
                out_path,
                preferred_voice=mock_external_voice_hint(normalized, voice, voice_id),
                rate_scale=rate,
                volume_scale=volume,
            )
            if valid_audio_file(out_path):
                return
        raise RuntimeError(f"{normalized} returned an empty response")

    if content_type.startswith("audio/") or content_type == "application/octet-stream":
        out_path.write_bytes(body)
    else:
        try:
            parsed = json.loads(body.decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"{normalized} returned unsupported content type: {content_type or 'unknown'}") from exc

        audio_base64 = str(parsed.get("audio_base64") or parsed.get("audio") or "").strip()
        if audio_base64:
            out_path.write_bytes(base64.b64decode(audio_base64))
        else:
            if is_local_provider_endpoint(endpoint) and os.name == "nt":
                print(f"[tts] {normalized} local provider returned JSON without audio, using direct SAPI fallback")
                synthesize_windows_sapi_tts(
                    text,
                    out_path,
                    preferred_voice=mock_external_voice_hint(normalized, voice, voice_id),
                    rate_scale=rate,
                    volume_scale=volume,
                )
                if valid_audio_file(out_path):
                    return
            raise RuntimeError(f"{normalized} returned JSON without audio payload")

    if not valid_audio_file(out_path):
        raise RuntimeError(f"{normalized} produced an empty or unusable audio file")


def engine_chain(engine: str) -> list[str]:
    requested = normalize_engine_name(engine)
    if requested == "auto":
        return ["edge", "local", "silent"]
    if requested == "silent":
        return ["silent"]
    if requested in {"edge", "local"}:
        return [requested, "local", "silent"] if requested == "edge" else ["local", "silent"]
    if is_external_engine(requested):
        return [requested, "edge", "local", "silent"]
    return ["edge", "local", "silent"]


def synthesize_preview(
    output_dir: Path,
    stem: str,
    text: str,
    voice: str,
    engine: str = "auto",
    voice_id: str = "",
    reference_audio_path: str = "",
    reference_text: str = "",
    emotion: str = "",
    rate: float = 1.0,
    pitch: float = 0.0,
    volume: float = 1.0,
) -> TTSResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    requested = normalize_engine_name(engine)
    warnings: list[str] = []

    for candidate in engine_chain(requested):
        if is_external_engine(candidate):
            ext_path = output_dir / f"{stem}.wav"
            try:
                synthesize_external_tts(
                    candidate,
                    text,
                    ext_path,
                    voice,
                    voice_id=voice_id,
                    reference_audio_path=reference_audio_path,
                    reference_text=reference_text,
                    emotion=emotion,
                    rate=rate,
                    pitch=pitch,
                    volume=volume,
                )
                return TTSResult(ext_path, candidate, requested, fallback=bool(warnings), warnings=warnings)
            except Exception as exc:
                warnings.append(f"{candidate}: {exc}")
                if ext_path.exists():
                    ext_path.unlink()
                continue
        if candidate == "edge":
            edge_path = output_dir / f"{stem}.mp3"
            try:
                synthesize_edge_tts(text, edge_path, voice, rate=rate, volume=volume, pitch=pitch)
                return TTSResult(edge_path, "edge", requested, fallback=bool(warnings), warnings=warnings)
            except Exception as exc:
                warnings.append(f"edge: {exc}")
                if edge_path.exists():
                    edge_path.unlink()
                continue
        if candidate == "local":
            local_path = output_dir / f"{stem}.wav"
            try:
                synthesize_local_tts(text, local_path, preferred_voice=voice, rate_scale=rate, volume_scale=volume)
                return TTSResult(local_path, "local", requested, fallback=bool(warnings), warnings=warnings)
            except Exception as exc:
                warnings.append(f"local: {exc}")
                if local_path.exists():
                    local_path.unlink()
                continue
        if candidate == "silent":
            silent_path = output_dir / f"{stem}.wav"
            duration = max(0.8, min(4.0, len(text) / 6))
            write_silent_wav(silent_path, duration)
            return TTSResult(silent_path, "silent", requested, fallback=True, warnings=warnings)

    silent_path = output_dir / f"{stem}.wav"
    write_silent_wav(silent_path, max(0.8, min(4.0, len(text) / 6)))
    return TTSResult(silent_path, "silent", requested, fallback=True, warnings=warnings)


def tts_diagnostics() -> dict:
    pyttsx3_status = "installed" if pyttsx3 is not None else "missing"
    sapi_status = "not_applicable"
    if os.name == "nt":
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            try:
                win32com.client.Dispatch("SAPI.SpVoice")
                sapi_status = "available"
            finally:
                pythoncom.CoUninitialize()
        except Exception as exc:
            sapi_status = f"unavailable: {exc}"
    return {
        "edge_tts": "installed" if edge_tts is not None else "missing",
        "pyttsx3": pyttsx3_status,
        "windows_sapi": sapi_status,
        "default_chain": ["edge", "local", "silent"],
        "provider_config_path": str(tts_provider_settings_path()),
        "external_providers": {
            engine: ("configured" if provider_url(engine) else "missing_config")
            for engine in EXTERNAL_PROVIDER_ENV
        },
    }
