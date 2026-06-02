@echo off
setlocal

cd /d "E:\APP\Comic drama"
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"
set "CLOUD_COMFYUI_SSH_PASSWORD=replace-with-your-password"

".venv\Scripts\python.exe" "scripts\dev_server.py" >> "dev_server_window.out.log" 2>> "dev_server_window.err.log"

endlocal
