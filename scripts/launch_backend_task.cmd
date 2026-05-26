@echo off
cd /d X:\
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"
set "CLOUD_COMFYUI_SSH_PASSWORD=replace-with-your-password"
start "" /b X:\.venv\Scripts\python.exe X:\scripts\dev_server.py
