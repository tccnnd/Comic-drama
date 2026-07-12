from __future__ import annotations

import json
import math
import os
import re
import subprocess
import textwrap
import wave
from pathlib import Path

from scripts.rw_config import ROOT


def wrap_cn(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=True, replace_whitespace=False))


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def load_env_file(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() <= 0:
            return 0.0
        return handle.getnframes() / float(handle.getframerate())


def media_duration(ffmpeg: str, path: Path) -> float:
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr or "")
    if not match:
        raise RuntimeError(f"Unable to probe media duration: {path}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


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


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def replace_placeholders(obj: object, replacements: dict[str, object]) -> object:
    if isinstance(obj, dict):
        return {key: replace_placeholders(value, replacements) for key, value in obj.items()}
    if isinstance(obj, list):
        return [replace_placeholders(item, replacements) for item in obj]
    if isinstance(obj, str):
        result = obj
        for key, value in replacements.items():
            result = result.replace(key, str(value))
        return result
    return obj


def unresolved_placeholders(obj: object, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            found.extend(unresolved_placeholders(value, f"{path}.{key}"))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            found.extend(unresolved_placeholders(value, f"{path}[{index}]"))
    elif isinstance(obj, str) and "__" in obj:
        found.append(f"{path}: {obj}")
    return found


def write_debug_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
