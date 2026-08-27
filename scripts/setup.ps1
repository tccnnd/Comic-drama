# Comic Drama Workflow — 本地开发环境一键初始化（T1.9 快速启动）
# 用法:
#   .\scripts\setup.ps1                # 创建 venv + 安装 requirements-dev.txt
#   .\scripts\setup.ps1 -SkipInstall   # 仅创建 venv，跳过依赖安装
param(
    [switch]$SkipInstall
)
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 1) 检测系统 python（用于创建 venv，要求 3.11+）
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Error "未找到 python，请先安装 Python 3.11+ 并加入 PATH"
    exit 1
}

# 2) 创建 venv（如不存在）
$venvPy = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "[1/3] 创建 venv ..."
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Write-Error "venv 创建失败"; exit 1 }
} else {
    Write-Host "[1/3] venv 已存在，跳过创建"
}

# 3) 安装依赖（默认安装；-SkipInstall 时跳过）
if (-not $SkipInstall) {
    Write-Host "[2/3] 安装 requirements-dev.txt（含运行时+开发依赖）..."
    & $venvPy -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { Write-Error "依赖安装失败，请检查网络后重试"; exit 1 }
} else {
    Write-Host "[2/3] 跳过依赖安装 (-SkipInstall)"
}

# 4) 验证 venv 可用
Write-Host "[3/3] 验证 venv ..."
& $venvPy --version
& $venvPy -c "import fastapi, uvicorn, pytest; print('  核心依赖 import OK')"
if ($LASTEXITCODE -ne 0) { Write-Error "venv 依赖验证失败"; exit 1 }

Write-Host "[OK] 初始化完成。启动开发服务器: .\scripts\dev.ps1"
