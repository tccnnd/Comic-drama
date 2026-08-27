# SSH AutoAddPolicy — Fix Guide

## Problem
`scripts/comfyui_ssh_tunnel.py` line ~97 uses `paramiko.AutoAddPolicy()`,
which silently accepts any unknown host key. This is vulnerable to
man-in-the-middle (MITM) attacks.

## Recommended Fix (apply manually)

Open `scripts/comfyui_ssh_tunnel.py` and replace:

```python
# BEFORE  (line ~97)
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
```

```python
# AFTER — option A: reject unknown hosts (safest, requires known_hosts pre-populated)
import os
known_hosts_path = os.path.expanduser("~/.ssh/known_hosts")
client.load_host_keys(known_hosts_path)
client.set_missing_host_key_policy(paramiko.RejectPolicy())
```

```python
# AFTER — option B: warn but continue (intermediate; still logs the fingerprint)
client.set_missing_host_key_policy(paramiko.WarningPolicy())
```

## Recommended: switch from password to key-based auth

Add to `.env.example`:
```env
# Prefer SSH key authentication over password
# COMFYUI_SSH_KEY_PATH=~/.ssh/id_rsa
```

In `comfyui_ssh_tunnel.py`, replace the `client.connect(... password=...)` call:
```python
import os
key_path = os.environ.get("COMFYUI_SSH_KEY_PATH", "").strip()
if key_path:
    client.connect(
        hostname=config.host,
        port=config.port,
        username=config.user,
        key_filename=os.path.expanduser(key_path),
        timeout=30,
        auth_timeout=20,
    )
else:
    # Fallback to password only when key is not configured
    client.connect(
        hostname=config.host,
        port=config.port,
        username=config.user,
        password=config.password,
        timeout=30,
        auth_timeout=20,
    )
```

This change cannot be applied as a simple file replacement because the exact
line numbers depend on your current version. Apply it manually after reviewing
the surrounding context.
