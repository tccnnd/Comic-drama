from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

try:
    import imageio_ffmpeg
except ImportError:  # pragma: no cover - optional runtime dependency
    imageio_ffmpeg = None

from scripts.rw_config import DEFAULT_SUBPROCESS_TIMEOUTS


def get_ffmpeg_exe() -> str:
    if imageio_ffmpeg is not None:
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    raise RuntimeError("FFmpeg executable not found. Install imageio-ffmpeg or add ffmpeg to PATH.")


def render_timeout(duration_seconds: float) -> int:
    return max(60, min(600, int(float(duration_seconds) * 8 + 30)))


def concat_timeout(item_count: int) -> int:
    return max(DEFAULT_SUBPROCESS_TIMEOUTS["ffmpeg_concat"], min(900, DEFAULT_SUBPROCESS_TIMEOUTS["ffmpeg_concat"] + max(0, item_count) * 10))


def _stderr_excerpt(stderr: str | None, limit: int = 4000) -> str:
    text = str(stderr or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def run_guarded(
    cmd: list[str],
    *,
    cwd: Path | str | None = None,
    timeout: int | float | None = None,
    stage: str = "command",
) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
        raise RuntimeError(f"{stage} timed out after {timeout}s: {' '.join(str(item) for item in cmd[:6])}")
    if proc.returncode != 0:
        raise RuntimeError(f"{stage} failed with exit code {proc.returncode}:\n{_stderr_excerpt(stderr)}")
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
