from __future__ import annotations

import os
import select
import socketserver
import threading
from dataclasses import dataclass
from typing import Any

try:
    import paramiko
except ImportError:  # pragma: no cover - optional SSH tunnel dependency
    paramiko = None


@dataclass(frozen=True)
class ComfyUITunnelConfig:
    ssh_host: str
    ssh_port: int
    username: str
    password: str
    local_host: str
    local_port: int
    remote_host: str
    remote_port: int


class _ForwardServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
    ssh_transport: paramiko.Transport


class _ForwardHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        channel = self.server.ssh_transport.open_channel(
            "direct-tcpip",
            (self.server.remote_host, self.server.remote_port),
            self.request.getpeername(),
        )
        if channel is None:
            return
        try:
            while True:
                readable, _, _ = select.select([self.request, channel], [], [])
                if self.request in readable:
                    data = self.request.recv(65536)
                    if not data:
                        break
                    channel.sendall(data)
                if channel in readable:
                    data = channel.recv(65536)
                    if not data:
                        break
                    self.request.sendall(data)
        finally:
            channel.close()


_LOCK = threading.Lock()
_SERVER: _ForwardServer | None = None
_CLIENT: Any | None = None
_THREAD: threading.Thread | None = None


def tunnel_config() -> ComfyUITunnelConfig | None:
    ssh_host = os.environ.get("COMFYUI_SSH_HOST", "").strip()
    if not ssh_host:
        return None
    return ComfyUITunnelConfig(
        ssh_host=ssh_host,
        ssh_port=int(os.environ.get("COMFYUI_SSH_PORT", "30887")),
        username=os.environ.get("COMFYUI_SSH_USER", "root").strip() or "root",
        password=os.environ.get("COMFYUI_SSH_PASSWORD", "").strip(),
        local_host=os.environ.get("COMFYUI_SSH_LOCAL_HOST", "127.0.0.1").strip() or "127.0.0.1",
        local_port=int(os.environ.get("COMFYUI_SSH_LOCAL_PORT", "8189")),
        remote_host=os.environ.get("COMFYUI_SSH_REMOTE_HOST", "127.0.0.1").strip() or "127.0.0.1",
        remote_port=int(os.environ.get("COMFYUI_SSH_REMOTE_PORT", "8188")),
    )


def ensure_comfyui_tunnel() -> str | None:
    config = tunnel_config()
    if config is None:
        return None
    if paramiko is None:
        raise RuntimeError("paramiko is required for SSH tunnel mode")
    if not config.password:
        raise RuntimeError("COMFYUI_SSH_PASSWORD is required for SSH tunnel mode")

    global _SERVER, _CLIENT, _THREAD
    with _LOCK:
        if _SERVER is not None and _THREAD is not None and _THREAD.is_alive():
            return f"http://{config.local_host}:{config.local_port}"

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=config.ssh_host,
            port=config.ssh_port,
            username=config.username,
            password=config.password,
            timeout=20,
            banner_timeout=20,
            auth_timeout=20,
        )
        transport = client.get_transport()
        if transport is None:
            client.close()
            raise RuntimeError("SSH tunnel transport was not established")
        transport.set_keepalive(30)

        server = _ForwardServer((config.local_host, config.local_port), _ForwardHandler)
        server.ssh_transport = transport
        server.remote_host = config.remote_host
        server.remote_port = config.remote_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        _SERVER = server
        _CLIENT = client
        _THREAD = thread
        return f"http://{config.local_host}:{config.local_port}"


def tunnel_is_active() -> bool:
    return _SERVER is not None and _THREAD is not None and _THREAD.is_alive()
