"""/api/health/detailed 详细健康检查端点测试（T2.2）。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import app


def test_health_detailed_ok_components_shape():
    """默认（local provider、无 comfyui blocker、目录可写）→ status=ok，三组件齐全。"""
    with TestClient(app) as client:
        resp = client.get("/api/health/detailed")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert "timestamp" in data
    comps = data["components"]
    assert set(comps) == {"video_provider", "comfyui", "storage"}
    # video_provider
    vp = comps["video_provider"]
    assert "provider" in vp and "readiness" in vp and "configured_count" in vp
    assert isinstance(vp.get("missing_env"), list)
    # comfyui
    assert isinstance(comps["comfyui"].get("blockers"), list)
    assert isinstance(comps["comfyui"].get("warnings"), list)
    # storage
    st = comps["storage"]
    assert "writable" in st and isinstance(st.get("dirs"), dict)
    assert "data" in st["dirs"] and "outputs" in st["dirs"]


def test_health_detailed_storage_marks_unwritable(monkeypatch):
    """storage 目录不可写时 → 该目录 writable=false，总体 status 降级为 degraded。"""
    # 纯逻辑模拟：不触碰真实文件系统（避免 basetemp 与沙箱 tmp 判定不匹配的 teardown 问题）
    fake_root = Path("F:/fake_root")
    monkeypatch.setattr("backend.routers.system.ROOT", fake_root)
    for name in ("data", "outputs", "workspace"):
        monkeypatch.setattr(f"backend.routers.system.Path.is_dir", lambda self: True)
    with (patch("backend.routers.system.Path.write_text", side_effect=OSError("read-only fs")),):
        from backend.routers.system import _check_storage

        result = _check_storage()
    assert result["writable"] is False
    assert all(d["writable"] is False for d in result["dirs"].values())


def test_health_detailed_comfyui_blocker_degrades(monkeypatch):
    """comfyui 存在 blocker → 总体 status=degraded。"""
    monkeypatch.setattr(
        "backend.routers.system.check_comfyui_health",
        lambda: {"ready": False, "blockers": ["ComfyUI offline"], "warnings": []},
    )
    with TestClient(app) as client:
        resp = client.get("/api/health/detailed")
    assert resp.status_code == 200
    data = resp.json()
    assert data["components"]["comfyui"]["blockers"] == ["ComfyUI offline"]
    assert data["status"] == "degraded"


def test_health_basic_unchanged():
    """原有 /api/health 保持不变。"""
    with TestClient(app) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
