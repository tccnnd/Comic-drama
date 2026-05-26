from __future__ import annotations

import argparse
import os
import posixpath
import sys
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
RESTORE_SCRIPT = ROOT / "scripts" / "cloud_gpu_restore_comfyui.sh"


def load_env(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def connect() -> paramiko.SSHClient:
    host = os.environ.get("COMFYUI_SSH_HOST", "sc01-ssh.gpuhome.cc")
    port = int(os.environ.get("COMFYUI_SSH_PORT", "30887"))
    user = os.environ.get("COMFYUI_SSH_USER", "root")
    password = os.environ.get("COMFYUI_SSH_PASSWORD", "")
    if not password:
        raise RuntimeError("COMFYUI_SSH_PASSWORD is required. Put it in .env or set the environment variable.")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=port,
        username=user,
        password=password,
        timeout=30,
        banner_timeout=30,
        auth_timeout=30,
    )
    return client


def upload_restore_script(client: paramiko.SSHClient, remote_path: str) -> None:
    with client.open_sftp() as sftp:
        remote_dir = posixpath.dirname(remote_path)
        try:
            sftp.mkdir(remote_dir)
        except OSError:
            pass
        sftp.put(str(RESTORE_SCRIPT), remote_path)
        sftp.chmod(remote_path, 0o755)


def run_remote(client: paramiko.SSHClient, command: str) -> int:
    transport = client.get_transport()
    if transport is None:
        raise RuntimeError("SSH transport is not available")
    channel = transport.open_session()
    channel.get_pty()
    channel.exec_command(command)
    while True:
        if channel.recv_ready():
            sys.stdout.write(channel.recv(8192).decode("utf-8", errors="replace"))
            sys.stdout.flush()
        if channel.recv_stderr_ready():
            sys.stderr.write(channel.recv_stderr(8192).decode("utf-8", errors="replace"))
            sys.stderr.flush()
        if channel.exit_status_ready():
            break
    while channel.recv_ready():
        sys.stdout.write(channel.recv(8192).decode("utf-8", errors="replace"))
    while channel.recv_stderr_ready():
        sys.stderr.write(channel.recv_stderr(8192).decode("utf-8", errors="replace"))
    return channel.recv_exit_status()


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload and run the cloud ComfyUI restore script.")
    parser.add_argument("--remote-script", default="/tmp/comicdrama_restore_comfyui.sh")
    parser.add_argument("--comfyui-root", default=os.environ.get("COMFYUI_REMOTE_ROOT", ""))
    parser.add_argument("--python", default=os.environ.get("COMFYUI_PYTHON", ""))
    args = parser.parse_args()

    load_env()
    client = connect()
    try:
        upload_restore_script(client, args.remote_script)
        env_parts = []
        if args.comfyui_root:
            env_parts.append(f"COMFYUI_REMOTE_ROOT={args.comfyui_root!r}")
        if args.python:
            env_parts.append(f"COMFYUI_PYTHON={args.python!r}")
        command = " ".join(env_parts + [f"bash {args.remote_script}"])
        return run_remote(client, command)
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())

