from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
SERVER = ROOT / "scripts" / "dev_server.py"
PID_FILE = ROOT / "dev_server.pid"
OUT_LOG = ROOT / "dev_server.out.log"
ERR_LOG = ROOT / "dev_server.err.log"


def main() -> int:
    python = PYTHON if PYTHON.exists() else Path(sys.executable)
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    creationflags = 0
    if os.name == "nt":
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
            | subprocess.DETACHED_PROCESS
            | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        )

    with OUT_LOG.open("ab") as stdout, ERR_LOG.open("ab") as stderr:
        process = subprocess.Popen(
            [str(python), str(SERVER)],
            cwd=str(ROOT),
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            close_fds=False,
            env=env,
            creationflags=creationflags,
        )

    PID_FILE.write_text(str(process.pid), encoding="ascii")
    time.sleep(1.5)
    if process.poll() is not None:
        print(f"{process.pid} exited {process.returncode}")
        return process.returncode or 1
    print(process.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
