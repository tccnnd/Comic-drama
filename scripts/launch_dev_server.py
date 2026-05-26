from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "scripts" / "dev_server.py"
OUT_LOG = ROOT / "dev_server.out.log"
ERR_LOG = ROOT / "dev_server.err.log"
PID_FILE = ROOT / "dev_server.pid"


def main() -> int:
    OUT_LOG.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    with OUT_LOG.open("a", encoding="utf-8") as stdout, ERR_LOG.open("a", encoding="utf-8") as stderr:
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        )
        proc = subprocess.Popen(
            [sys.executable, str(SERVER)],
            cwd=ROOT,
            stdout=stdout,
            stderr=stderr,
            env=env,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )

    PID_FILE.write_text(f"{proc.pid}\n", encoding="utf-8")
    print(proc.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
