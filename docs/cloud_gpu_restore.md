# Cloud GPU Restore Notes

This project treats the cloud GPU as disposable. Local project code, workflows, prompts, and JSON assets live on this machine. The cloud machine only needs a repeatable ComfyUI runtime.

## When The Cloud Instance Restarts

1. Start the cloud GPU instance in the provider console.
2. Confirm the SSH host, port, user, and password in `.env`.
3. Run from the project root:

```powershell
.\.venv\Scripts\python.exe scripts\run_cloud_gpu_restore.py
```

4. Start the local tunnel:

```powershell
$env:CLOUD_COMFYUI_SSH_PASSWORD="your-password"
.\.venv\Scripts\python.exe scripts\start_cloud_comfyui_tunnel_detached.py
```

5. Verify:

```powershell
Invoke-RestMethod http://127.0.0.1:8189/system_stats
```

## Persistent Files To Keep On The Cloud Disk

Keep these under the provider's persistent volume when possible:

- `ComfyUI/models/checkpoints/*.safetensors`
- `ComfyUI/models/loras/*.safetensors`
- `ComfyUI/models/ipadapter/*`
- `ComfyUI/models/clip_vision/*`
- `ComfyUI/custom_nodes/*`

If those paths are not persistent, the restore script will warn, but it cannot recreate commercial or manually downloaded model files by itself.

## Current ComfyUI Defaults

- Remote ComfyUI root: `/root/rivermind-data/comfyui-cloud/ComfyUI`
- Remote Python: `/opt/conda/bin/python3.11`
- Remote ComfyUI port: `8188`
- Local tunnel port: `8189`
- Local workflow file: `workflows/comfyui_keyframe_template.json`

The workflow currently points at `v1-5-pruned-emaonly-fp16.safetensors`, which is only a baseline SD1.5 checkpoint. For real anime/manhua output, replace it with a dedicated anime checkpoint and update the `ckpt_name` in the workflow.

