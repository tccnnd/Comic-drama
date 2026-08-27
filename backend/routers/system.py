from __future__ import annotations

import datetime as _dt
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse

from backend.comfyui_health import check_comfyui_health
from backend.routers._common import FRONTEND
from video_providers import get_video_provider_status

router = APIRouter(tags=["system"])

ROOT = Path(__file__).resolve().parents[2]

# storage 检查的目标目录（相对 ROOT）；不存在时跳过（视为不可用）
_STORAGE_DIRS = ("data", "outputs", "workspace")


def _check_storage() -> dict[str, Any]:
    """检查关键运行时目录的可写性（写入探测文件；清理失败不致命）。"""
    results: dict[str, Any] = {}
    all_writable = True
    for name in _STORAGE_DIRS:
        target = ROOT / name
        if not target.is_dir():
            results[name] = {"exists": False, "writable": None, "detail": "directory missing"}
            all_writable = False
            continue
        probe = target / f".health_probe_{os.getpid()}.tmp"
        try:
            probe.write_text("ok", encoding="utf-8")
            writable = True
        except OSError as exc:
            writable = False
            results[name] = {"exists": True, "writable": False, "detail": str(exc)}
            all_writable = False
            continue
        # 清理尽力而为：沙箱/守卫可能拦截删除，不影响可写性结论
        try:
            probe.unlink(missing_ok=True)
        except Exception:
            pass
        results[name] = {"exists": True, "writable": True}
    return {"writable": all_writable, "dirs": results}


@router.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/health/detailed")
def health_detailed() -> dict[str, Any]:
    """详细健康检查：video provider / comfyui / storage 三组件状态。

    与 /api/health 不同，此端点会探测真实外部依赖（ComfyUI 可达性、
    provider 环境变量配置、数据目录可写性），供运维与 Docker healthcheck 复用。
    """
    provider = get_video_provider_status()
    comfyui = check_comfyui_health()
    storage = _check_storage()

    # 总体状态：comfyui 有 blocker 或 storage 不可写则降级为 degraded
    comfyui_blockers = comfyui.get("blockers") or []
    status = "ok" if (not comfyui_blockers and storage["writable"]) else "degraded"

    return {
        "status": status,
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "components": {
            "video_provider": {
                "provider": provider.get("provider"),
                "readiness": provider.get("readiness"),
                "configured_count": provider.get("configured_count"),
                "missing_env": provider.get("missing_env"),
            },
            "comfyui": {
                "ready": comfyui.get("ready"),
                "blockers": comfyui_blockers,
                "warnings": comfyui.get("warnings") or [],
            },
            "storage": storage,
        },
    }


@router.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")
