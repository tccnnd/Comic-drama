from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "scripts" / "mock_tts_provider.py"
OUT_LOG = ROOT / "mock_tts_provider.out.log"
ERR_LOG = ROOT / "mock_tts_provider.err.log"
PID_FILE = ROOT / "mock_tts_provider.pid"
HEALTH_URL = "http://127.0.0.1:8010/health"


def provider_running() -> bool:
    try:
        with urlopen(HEALTH_URL, timeout=2) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def main() -> int:
    if provider_running():
        print("mock TTS provider already running")
        return 0

    OUT_LOG.parent.mkdir(parents=True, exist_ok=True)
    command = (
        f"$p = Start-Process -WindowStyle Hidden "
        f"-FilePath '{sys.executable}' "
        f"-ArgumentList @('{SERVER}', '--port', '8010') "
        f"-WorkingDirectory '{ROOT}' "
        f"-RedirectStandardOutput '{OUT_LOG}' "
        f"-RedirectStandardError '{ERR_LOG}' "
        f"-PassThru; $p.Id"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    pid_text = result.stdout.strip()
    if pid_text:
        PID_FILE.write_text(f"{pid_text}\n", encoding="utf-8")
        print(pid_text)
    else:
        print("mock TTS provider started")

    for _ in range(30):
        if provider_running():
            return 0
        time.sleep(0.5)
    raise RuntimeError("mock TTS provider failed to start")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
