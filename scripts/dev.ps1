# Comic Drama Workflow — 本地开发服务器启动器（T1.9 快速启动）
# 用法:
#   .\scripts\dev.ps1                       # 默认 127.0.0.1:8000
#   .\scripts\dev.ps1 -BindHost 0.0.0.0     # 绑定所有网卡
#   .\scripts\dev.ps1 -BindHost 127.0.0.1 -Port 9000
# 说明：后台启动 uvicorn，轮询 /api/health 直到 status=ok（<=30s），PID 写入 dev_server.pid
param(
    [string]$BindHost = '127.0.0.1',
    [int]$Port = 8000
)
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPy = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Error "venv 不存在，请先运行: .\scripts\setup.ps1"
    exit 1
}

$env:PYTHONUNBUFFERED = '1'
$env:PYTHONIOENCODING = 'utf-8'

# 后台启动 uvicorn（独立进程，避免阻塞当前终端）
$proc = Start-Process -WindowStyle Hidden -FilePath $venvPy `
    -ArgumentList @('-m', 'uvicorn', 'backend.app:app', '--host', $BindHost, '--port', "$Port") `
    -WorkingDirectory $root -PassThru
Set-Content -Path "$root\dev_server.pid" -Value $proc.Id

# 轮询 /api/health（<=30s），返回 ok 即成功
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $resp = Invoke-RestMethod -Uri "http://${BindHost}:${Port}/api/health" -TimeoutSec 2
        if ($resp.status -eq 'ok') { $ok = $true; break }
    } catch {
        # 服务未就绪，继续等待
    }
}

if ($ok) {
    Write-Host "[OK] /api/health -> status=ok (PID $($proc.Id), http://${BindHost}:${Port})"
} else {
    Write-Warning "后端进程已启动（PID $($proc.Id)），但 /api/health 30 秒内未就绪"
    Write-Warning "请检查: $root\dev_server.pid 指向的进程状态"
    exit 1
}
