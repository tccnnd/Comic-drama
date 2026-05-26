from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
TUNNEL_SCRIPT = ROOT / "scripts" / "cloud_comfyui_tunnel.py"
PID_FILE = ROOT / "cloud_tunnel.pid"
OUT_LOG = ROOT / "cloud_tunnel.out.log"
ERR_LOG = ROOT / "cloud_tunnel.err.log"


def load_env_file(path: Path = ENV_FILE) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    load_env_file()
    if not TUNNEL_SCRIPT.exists():
        raise FileNotFoundError(f"Missing tunnel script: {TUNNEL_SCRIPT}")

    creationflags = 0
    if os.name == "nt":
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
            | subprocess.DETACHED_PROCESS
            | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        )

    python_exe = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python_exe.exists():
        raise FileNotFoundError(f"Missing Python executable: {python_exe}")

    cmd = [
        str(python_exe),
        str(TUNNEL_SCRIPT),
    ]

    with OUT_LOG.open("ab") as stdout, ERR_LOG.open("ab") as stderr:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            close_fds=False,
            creationflags=creationflags,
        )

    PID_FILE.write_text(str(proc.pid), encoding="ascii")
    time.sleep(1.5)
    if proc.poll() is not None:
        print(f"{proc.pid} exited {proc.returncode}")
        return proc.returncode or 1

    print(proc.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
