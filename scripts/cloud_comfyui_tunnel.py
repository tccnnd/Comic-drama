from __future__ import annotations

import argparse
import getpass
import os
import select
import socketserver
import sys
import threading
from dataclasses import dataclass

import paramiko


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(ROOT, ".env")


@dataclass(frozen=True)
class TunnelConfig:
    local_host: str
    local_port: int
    remote_host: str
    remote_port: int
    ssh_host: str
    ssh_port: int
    username: str


class ForwardServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class ForwardHandler(socketserver.BaseRequestHandler):
    ssh_transport: paramiko.Transport
    config: TunnelConfig

    def handle(self) -> None:
        channel = self.ssh_transport.open_channel(
            "direct-tcpip",
            (self.config.remote_host, self.config.remote_port),
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


def load_env_file(path: str = ENV_FILE) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env_value(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Open a local SSH tunnel to cloud ComfyUI.")
    parser.add_argument("--ssh-host", default=env_value("CLOUD_COMFYUI_SSH_HOST", "COMFYUI_SSH_HOST", default="sc01-ssh.gpuhome.cc"))
    parser.add_argument("--ssh-port", type=int, default=int(env_value("CLOUD_COMFYUI_SSH_PORT", "COMFYUI_SSH_PORT", default="30935")))
    parser.add_argument("--username", default=env_value("CLOUD_COMFYUI_SSH_USER", "COMFYUI_SSH_USER", default="root"))
    parser.add_argument("--password", default=env_value("CLOUD_COMFYUI_SSH_PASSWORD", "COMFYUI_SSH_PASSWORD", default=""))
    parser.add_argument("--local-host", default=env_value("CLOUD_COMFYUI_TUNNEL_HOST", "COMFYUI_SSH_LOCAL_HOST", default="127.0.0.1"))
    parser.add_argument("--local-port", type=int, default=int(env_value("CLOUD_COMFYUI_TUNNEL_PORT", "COMFYUI_SSH_LOCAL_PORT", default="8189")))
    parser.add_argument("--remote-host", default=env_value("CLOUD_COMFYUI_REMOTE_HOST", "COMFYUI_SSH_REMOTE_HOST", default="127.0.0.1"))
    parser.add_argument("--remote-port", type=int, default=int(env_value("CLOUD_COMFYUI_REMOTE_PORT", "COMFYUI_SSH_REMOTE_PORT", default="8188")))
    return parser


def main() -> int:
    load_env_file()
    args = build_parser().parse_args()
    password = args.password or getpass.getpass("SSH password: ")
    config = TunnelConfig(
        local_host=args.local_host,
        local_port=args.local_port,
        remote_host=args.remote_host,
        remote_port=args.remote_port,
        ssh_host=args.ssh_host,
        ssh_port=args.ssh_port,
        username=args.username,
    )

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=config.ssh_host,
        port=config.ssh_port,
        username=config.username,
        password=password,
        timeout=20,
        banner_timeout=20,
        auth_timeout=20,
    )
    transport = client.get_transport()
    if transport is None:
        raise RuntimeError("SSH transport was not created")

    handler = type(
        "CloudComfyUIForwardHandler",
        (ForwardHandler,),
        {"ssh_transport": transport, "config": config},
    )
    server = ForwardServer((config.local_host, config.local_port), handler)
    print(
        f"Cloud ComfyUI tunnel: http://{config.local_host}:{config.local_port} "
        f"-> {config.remote_host}:{config.remote_port} via {config.username}@{config.ssh_host}:{config.ssh_port}",
        flush=True,
    )

    stop = threading.Event()
    try:
        while not stop.is_set():
            server.handle_request()
    except KeyboardInterrupt:
        print("Stopping tunnel.", flush=True)
    finally:
        server.server_close()
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
