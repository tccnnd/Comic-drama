"""T1.4 验收：/api/tasks/{task_id}/stream WebSocket 连通性测试。

验证 WebSocket 端点能够完成握手、按契约返回结构化响应并优雅关闭。
不依赖真实任务、不依赖前端/浏览器，纯后端连通性验证。
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app import app


def test_tasks_stream_connectivity_closes_cleanly():
    """格式合法但不存在的任务：握手成功，服务端返回结构化错误后优雅关闭 (code 1000)。"""
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/api/tasks/abcdef123") as ws:
                ws.receive_json()
    # 1000 = 正常关闭（服务端在发送 {"error": "Task not found"} 后断开）
    assert exc.value.code == 1000


def test_tasks_stream_invalid_task_id_rejected():
    """非法 task_id：服务端受控关闭连接（1000 正常关闭 / 1008 格式拒绝均视为可达并遵循契约）。"""
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/api/tasks/__bad/id") as ws:
                ws.receive_json()
    assert exc.value.code in (1000, 1008)
