@echo off
setlocal
cd /d "%~dp0"

if "%CLOUD_COMFYUI_SSH_HOST%"=="" set CLOUD_COMFYUI_SSH_HOST=sc01-ssh.gpuhome.cc
if "%CLOUD_COMFYUI_SSH_PORT%"=="" set CLOUD_COMFYUI_SSH_PORT=30935
if "%CLOUD_COMFYUI_SSH_USER%"=="" set CLOUD_COMFYUI_SSH_USER=root
if "%CLOUD_COMFYUI_TUNNEL_PORT%"=="" set CLOUD_COMFYUI_TUNNEL_PORT=8189

start "" /b ".venv\Scripts\python.exe" "scripts\cloud_comfyui_tunnel.py"
