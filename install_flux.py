"""Install Flux.1 Dev on remote 4090 server."""
import paramiko
import time

HOST = "hn01-ssh.gpuhome.cc"
PORT = 30560
USER = "root"
PASS = "tcc000000"

def ssh_exec(client, cmd, timeout=1800):
    print(f"  $ {cmd.strip()[:150]}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    combined = (out + "\n" + err).strip()
    for line in combined.split("\n")[-10:]:
        if line.strip():
            print(f"    {line.strip()[:150]}")
    return out.strip()

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, port=PORT, username=USER, password=PASS, timeout=15)
print("Connected!\n")

HF = "https://hf-mirror.com"

# 1. Check disk space
print("1. Disk space check:")
ssh_exec(client, "df -h / | tail -1")

# 2. Download Flux.1 Dev (GGUF quantized version for 24GB VRAM)
# Full Flux.1 Dev is ~24GB which won't fit in VRAM alongside ComfyUI
# Use the fp8 version (~12GB) which fits perfectly on 4090
print("\n2. Downloading Flux.1 Dev fp8 (~12GB)...")
print("   This will take 5-10 minutes...")
ssh_exec(client, f"""
mkdir -p /ComfyUI/models/unet && \
cd /ComfyUI/models/unet && \
wget -c -O flux1-dev-fp8.safetensors \
  '{HF}/Kijai/flux-fp8/resolve/main/flux1-dev-fp8.safetensors' \
  2>&1 | tail -5
""")
ssh_exec(client, "ls -lh /ComfyUI/models/unet/flux1-dev-fp8.safetensors 2>/dev/null")

# 3. Download Flux VAE
print("\n3. Downloading Flux VAE (~335MB)...")
ssh_exec(client, f"""
mkdir -p /ComfyUI/models/vae && \
cd /ComfyUI/models/vae && \
wget -c -O ae.safetensors \
  '{HF}/black-forest-labs/FLUX.1-dev/resolve/main/ae.safetensors' \
  2>&1 | tail -5
""")
ssh_exec(client, "ls -lh /ComfyUI/models/vae/ae.safetensors 2>/dev/null")

# 4. Download Flux CLIP (T5-XXL fp8 + CLIP-L)
print("\n4. Downloading T5-XXL fp8 text encoder (~5GB)...")
ssh_exec(client, f"""
mkdir -p /ComfyUI/models/clip && \
cd /ComfyUI/models/clip && \
wget -c -O t5xxl_fp8_e4m3fn.safetensors \
  '{HF}/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn.safetensors' \
  2>&1 | tail -5
""")
ssh_exec(client, "ls -lh /ComfyUI/models/clip/t5xxl_fp8_e4m3fn.safetensors 2>/dev/null")

print("\n5. Downloading CLIP-L (~250MB)...")
ssh_exec(client, f"""
cd /ComfyUI/models/clip && \
wget -c -O clip_l.safetensors \
  '{HF}/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors' \
  2>&1 | tail -5
""")
ssh_exec(client, "ls -lh /ComfyUI/models/clip/clip_l.safetensors 2>/dev/null")

# 5. Restart ComfyUI
print("\n6. Restarting ComfyUI...")
ssh_exec(client, "pkill -f 'main.py' 2>/dev/null; sleep 3")
ssh_exec(client, """
cd /ComfyUI && nohup /venv/bin/python main.py --listen 0.0.0.0 --port 8088 > /tmp/comfyui.log 2>&1 &
echo "Starting..."
""")
time.sleep(25)

# 6. Verify Flux nodes available
print("\n7. Verifying Flux support...")
ssh_exec(client, """
curl -s http://127.0.0.1:8088/object_info | /venv/bin/python -c '
import sys, json
data = json.load(sys.stdin)
flux_nodes = ["UNETLoader", "DualCLIPLoader", "VAELoader", "CLIPTextEncode", "KSampler", "VAEDecode", "SaveImage", "EmptySD3LatentImage"]
for n in flux_nodes:
    print(f"  {n}: {\"OK\" if n in data else \"MISSING\"}")
' 2>/dev/null || echo "ComfyUI not ready"
""")

# 7. Check all model files
print("\n8. All model files:")
ssh_exec(client, """
echo "=== Checkpoints ===" && ls -lh /ComfyUI/models/checkpoints/*.safetensors 2>/dev/null
echo "=== UNET ===" && ls -lh /ComfyUI/models/unet/*.safetensors 2>/dev/null
echo "=== VAE ===" && ls -lh /ComfyUI/models/vae/*.safetensors 2>/dev/null
echo "=== CLIP ===" && ls -lh /ComfyUI/models/clip/*.safetensors 2>/dev/null
""")

client.close()
print("\nDone!")
