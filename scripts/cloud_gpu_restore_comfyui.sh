#!/usr/bin/env bash
set -euo pipefail

# Rebuild the cloud ComfyUI runtime after an ephemeral GPU instance restarts.
# Override these through environment variables when your provider uses different paths.
COMFYUI_ROOT="${COMFYUI_REMOTE_ROOT:-/root/rivermind-data/comfyui-cloud/ComfyUI}"
PYTHON_BIN="${COMFYUI_PYTHON:-/opt/conda/bin/python3.11}"
HOST="${COMFYUI_LISTEN_HOST:-0.0.0.0}"
PORT="${COMFYUI_LISTEN_PORT:-8188}"
LOG_DIR="${COMFYUI_LOG_DIR:-/root/rivermind-data/comfyui-cloud/logs}"
PID_FILE="${COMFYUI_PID_FILE:-/root/rivermind-data/comfyui-cloud/comfyui.pid}"

ANIME_LORA_NAME="${COMFYUI_LORA_NAME:-anime-character-lora_v1.5.safetensors}"
CHECKPOINT_NAME="${COMFYUI_CHECKPOINT_NAME:-v1-5-pruned-emaonly-fp16.safetensors}"

mkdir -p "$LOG_DIR"

echo "[restore] ComfyUI root: $COMFYUI_ROOT"
if [ ! -f "$COMFYUI_ROOT/main.py" ]; then
  echo "[restore] ERROR: ComfyUI main.py not found."
  echo "[restore] Expected: $COMFYUI_ROOT/main.py"
  echo "[restore] Install or mount ComfyUI there, or set COMFYUI_REMOTE_ROOT."
  exit 2
fi

cd "$COMFYUI_ROOT"

echo "[restore] Python: $PYTHON_BIN"
"$PYTHON_BIN" -m pip install --upgrade pip >/dev/null
"$PYTHON_BIN" -m pip install -r requirements.txt

mkdir -p models/checkpoints models/loras models/vae models/clip_vision models/ipadapter input output custom_nodes

echo "[restore] Checking model files"
if [ ! -s "models/checkpoints/$CHECKPOINT_NAME" ]; then
  echo "[restore] WARNING: checkpoint missing: models/checkpoints/$CHECKPOINT_NAME"
  echo "[restore] Put an anime/manhua SD1.5 checkpoint here and update workflows/comfyui_keyframe_template.json ckpt_name."
fi

if [ ! -s "models/loras/$ANIME_LORA_NAME" ]; then
  echo "[restore] WARNING: LoRA missing: models/loras/$ANIME_LORA_NAME"
fi

if [ -f "models/loras/$ANIME_LORA_NAME" ]; then
  size="$(stat -c '%s' "models/loras/$ANIME_LORA_NAME")"
  echo "[restore] LoRA size: $size bytes"
  if [ "$size" -lt 1000000 ]; then
    echo "[restore] WARNING: LoRA is suspiciously small. It may be an HTML/LFS pointer, not a real safetensors model."
  fi
fi

if [ -f "models/checkpoints/$CHECKPOINT_NAME" ]; then
  size="$(stat -c '%s' "models/checkpoints/$CHECKPOINT_NAME")"
  echo "[restore] checkpoint size: $size bytes"
  if [ "$size" -lt 100000000 ]; then
    echo "[restore] WARNING: checkpoint is suspiciously small. It may not be a real model."
  fi
fi

if [ ! -d custom_nodes/ComfyUI_IPAdapter_plus ]; then
  echo "[restore] WARNING: custom_nodes/ComfyUI_IPAdapter_plus is missing."
  echo "[restore] IPAdapter workflows will fail until the node and its models are installed."
fi

if [ -f "$PID_FILE" ]; then
  old_pid="$(cat "$PID_FILE" || true)"
  if [ -n "${old_pid:-}" ] && kill -0 "$old_pid" 2>/dev/null; then
    echo "[restore] Stopping previous ComfyUI pid $old_pid"
    kill "$old_pid" || true
    sleep 2
  fi
fi

echo "[restore] Starting ComfyUI on $HOST:$PORT"
nohup "$PYTHON_BIN" main.py --listen "$HOST" --port "$PORT" \
  > "$LOG_DIR/comfyui.stdout.log" \
  2> "$LOG_DIR/comfyui.stderr.log" &
echo "$!" > "$PID_FILE"

sleep 5
if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "[restore] ERROR: ComfyUI process exited. Recent stderr:"
  tail -80 "$LOG_DIR/comfyui.stderr.log" || true
  exit 3
fi

echo "[restore] ComfyUI pid: $(cat "$PID_FILE")"
echo "[restore] Health check:"
curl -fsS "http://127.0.0.1:$PORT/system_stats" >/dev/null && echo "[restore] OK"

