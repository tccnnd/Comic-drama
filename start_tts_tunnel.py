"""Start SSH tunnel for OmniVoice TTS (port 9880 -> local 9880)."""
import paramiko
import threading
import time
import socket

HOST = "hn01-ssh.gpuhome.cc"
PORT = 30560
USER = "root"
PASS = "tcc000000"
REMOTE_PORT = 9880
LOCAL_PORT = 9880

def forward_tunnel(local_port, remote_host, remote_port, transport):
    """Forward local_port to remote_host:remote_port via SSH transport."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", local_port))
    server.listen(5)
    print(f"  Tunnel listening on 127.0.0.1:{local_port} -> remote:{remote_port}")
    
    while True:
        client_socket, addr = server.accept()
        channel = transport.open_channel("direct-tcpip", (remote_host, remote_port), addr)
        if channel is None:
            client_socket.close()
            continue
        # Bidirectional forwarding
        t1 = threading.Thread(target=_pipe, args=(client_socket, channel), daemon=True)
        t2 = threading.Thread(target=_pipe, args=(channel, client_socket), daemon=True)
        t1.start()
        t2.start()

def _pipe(src, dst):
    try:
        while True:
            data = src.recv(4096)
            if not data:
                break
            dst.sendall(data)
    except:
        pass
    finally:
        try: src.close()
        except: pass
        try: dst.close()
        except: pass

# Check if tunnel already exists
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    s.connect(("127.0.0.1", LOCAL_PORT))
    s.close()
    print(f"Port {LOCAL_PORT} already in use - tunnel may already be active")
    # Test if it's actually the TTS service
    from urllib.request import urlopen
    import json
    d = json.loads(urlopen(f"http://127.0.0.1:{LOCAL_PORT}/health", timeout=3).read())
    print(f"  ✓ OmniVoice TTS already accessible: {d}")
    exit(0)
except:
    pass

print(f"Starting SSH tunnel: 127.0.0.1:{LOCAL_PORT} -> remote:{REMOTE_PORT}")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, port=PORT, username=USER, password=PASS, timeout=10)
transport = client.get_transport()

tunnel_thread = threading.Thread(
    target=forward_tunnel,
    args=(LOCAL_PORT, "127.0.0.1", REMOTE_PORT, transport),
    daemon=True,
)
tunnel_thread.start()

# Wait and verify
time.sleep(2)
try:
    from urllib.request import urlopen
    import json
    d = json.loads(urlopen(f"http://127.0.0.1:{LOCAL_PORT}/health", timeout=5).read())
    print(f"  ✓ Tunnel active! OmniVoice TTS: {d}")
except Exception as e:
    print(f"  ✗ Tunnel test failed: {e}")

print("\nTunnel running. Press Ctrl+C to stop.")
try:
    while True:
        time.sleep(60)
except KeyboardInterrupt:
    print("\nStopping tunnel.")
    client.close()
