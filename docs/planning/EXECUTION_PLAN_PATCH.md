# 执行计划修正补丁（基于元审核结果）

**修正日期**: 2026-08-27  
**基于**: `EXECUTION_PLAN.md` + `EXECUTION_PLAN_AUDIT_v2.md` + `EXECUTION_PLAN_META_AUDIT.md`  
**修正原因**: 适应 Windows 环境、细化验收标准、提升可执行性

---

## 使用说明

本文档包含对原 `EXECUTION_PLAN.md` 的 **3 处关键修正**。执行时请按本文档的修正版本执行。

---

## 修正 1: Phase 0 新增 Task 0.9（分支清理与整合）

### 原计划状态
- Phase 0 只有 Task 0.1-0.6（6个任务）
- 完全未包含分支管理任务

### 修正后

#### Task 0.9: 分支清理与整合决策 🔴

**描述**: 理清 Git 分支状态，做出合入/废弃/保留决策，为后续重构扫清障碍。

**背景**:
```bash
当前分支状态（git branch -vv）:
- main: 4caa6c3 (7月14日，停滞1.5月)
- codex/director-interpretation-mainline-impl: 48d1f64 [ahead 3]
  └─ P2 重构：+22760/-8139 行，包含 13 个 rw_* 模块
- 其他 6 个 codex/* 分支（v0.2/v0.3/v0.4 feature 分支）
```

**问题**: P2 重构分支包含 13 个 rw_* 模块（run_workflow.py 拆分），但未合入 main，工作区不存在这些文件。任何新重构前必须理清这个分支的去向。

---

### 执行步骤

#### Step 1: 生成分支状态表

```powershell
# 1. 列出所有分支及其状态
git branch -vv | Out-File branch_status_raw.txt

# 2. 检查每个分支与 main 的差异
$branches = @(
    "codex/consolidate-production-docs",
    "codex/director-interpretation-mainline",
    "codex/director-interpretation-mainline-impl",
    "codex/director-review-console",
    "codex/director-review-console-impl",
    "codex/global-consistency-governance",
    "codex/video-provider-mainline"
)

foreach ($branch in $branches) {
    Write-Host "`n=== $branch ===" -ForegroundColor Cyan
    
    # 检查是否已合入 main
    $mergeBase = git merge-base main $branch
    $mainHead = git rev-parse main
    
    if ($mergeBase -eq $mainHead) {
        Write-Host "状态: 已合入 main" -ForegroundColor Green
    } else {
        # 统计差异
        $stats = git diff --shortstat main...$branch
        Write-Host "状态: 未合入" -ForegroundColor Yellow
        Write-Host "差异: $stats"
        
        # 检查最后提交时间
        $lastCommit = git log -1 --format="%ci" $branch
        Write-Host "最后提交: $lastCommit"
    }
}
```

#### Step 2: 创建分支决策表

创建 `branch_decision_table.md`：

```markdown
| 分支名 | 最后提交 | 与main差异 | 合入状态 | 决策 | 原因 |
|--------|---------|-----------|---------|------|------|
| consolidate-production-docs | 2026-07-XX | +X-Y | 已合入 | 删除 | PR #12 已合入 |
| director-interpretation-mainline | 2026-XX-XX | +X-Y | 已合入 | 删除 | v0.5 已合入 |
| **director-interpretation-mainline-impl** | **2026-07-XX** | **+22760-8139** | **未合入** | **待Task 1.0决策** | **P2重构：13个rw_*模块** |
| director-review-console | 2026-XX-XX | +X-Y | 已合入 | 删除 | v0.4 已合入 |
| director-review-console-impl | 2026-XX-XX | +X-Y | 已合入 | 删除 | 实现已合入 |
| global-consistency-governance | 2026-XX-XX | +X-Y | 已合入 | 删除 | v0.3 已合入 |
| video-provider-mainline | 2026-XX-XX | +X-Y | 已合入 | 删除 | v0.2 已合入 |
```

#### Step 3: 执行分支整合

```powershell
# 删除已合入 main 的本地分支
git branch -d codex/consolidate-production-docs
git branch -d codex/director-interpretation-mainline
git branch -d codex/director-review-console
git branch -d codex/director-review-console-impl
git branch -d codex/global-consistency-governance
git branch -d codex/video-provider-mainline

# P2 重构分支保留，等待 Task 1.0 决策
# 不删除 codex/director-interpretation-mainline-impl
```

**注意**: 如果某个分支删除失败（`-d` 报错"未完全合入"），说明该分支可能包含未合入的提交，需人工审查后使用 `-D` 强制删除或保留。

---

### 验收标准

**Step 1: 状态表已生成** ✅
- [ ] `branch_status_raw.txt` 包含所有分支的 git branch -vv 输出
- [ ] `branch_decision_table.md` 表格包含 8 个分支的决策
- [ ] 每个分支的合入状态已确认（通过 merge-base 或 git log 查找 merge commit）

**Step 2: 分支整合已执行** ✅
- [ ] 已合入 main 的 6 个分支已删除（本地）
- [ ] P2 重构分支（director-interpretation-mainline-impl）保留，状态已标注"待 Task 1.0 决策"
- [ ] `git branch` 输出只显示 ≤3 个本地分支（main + 最多 2 个活跃分支）

**Step 3: 用途明确** ✅
- [ ] 保留的每个分支都有明确的用途说明
- [ ] 分支决策表已提交到仓库（`git add branch_decision_table.md && git commit`）

**预估时间**: 2-3 小时  
**风险**: 中（需要仔细判断分支合入状态）

---

## 修正 2: Phase 1 新增 Task 1.0（澄清 rw_* 重构去向）

### 原计划状态
- Phase 1 从 Task 1.1（依赖管理）开始
- 未包含 rw_* 重构分支处理

### 修正后

#### Task 1.0: 澄清 rw_* 重构分支去向 🔴

**描述**: 决定 P2 重构分支（13 个 rw_* 模块）的合入策略，确保不与新重构冲突。

**背景**:
- Commit `48d1f64` 已将 run_workflow.py（6204行）拆分为 13 个 rw_* 模块
- 该提交在分支 `codex/director-interpretation-mainline-impl` 上
- 工作区 main 分支不包含这些模块（run_workflow.py 仍是 6204 行）
- 变更量：+22760/-8139 行（净增 14621 行）

**问题**: 在执行 Phase 1 的任何重构前，必须决定这个分支的命运，否则会产生冲突。

---

### 执行步骤

#### Step 1: 验证 P2 重构分支状态

```powershell
# 切换到 P2 重构分支
git checkout codex/director-interpretation-mainline-impl

# 确认 rw_* 模块存在
ls scripts/rw_*.py
# 应输出 13 个文件：
# rw_audio.py, rw_comfyui.py, rw_config.py, rw_ffmpeg.py,
# rw_image.py, rw_models.py, rw_planning.py, rw_prompts.py,
# rw_render.py, rw_storyboard.py, rw_styles.py, rw_utils.py, rw_voice.py

# 确认测试通过
pytest
# 期望输出：509 tests pass（根据 commit message）
```

#### Step 2: 评估合入影响

```powershell
# 检查与 main 的差异
git diff --stat main...codex/director-interpretation-mainline-impl
# 输出应显示：106 files changed, 22760 insertions(+), 8139 deletions(-)

# 检查是否有冲突
git checkout main
git merge --no-commit --no-ff codex/director-interpretation-mainline-impl

# 如果有冲突，查看冲突文件
git diff --name-only --diff-filter=U

# 取消合并（不提交）
git merge --abort
```

#### Step 3: 制定合入策略（三选一）

**选项 A: 直接合入到 main** 🔴 **风险高**
```powershell
git checkout main
git merge codex/director-interpretation-mainline-impl -m "Merge P2 refactor: split run_workflow.py into 13 rw_* modules"
pytest  # 必须全量测试通过
```

**优点**: 一次性完成  
**缺点**: 
- 变更量巨大（+22760/-8139）
- 如果测试失败，回退困难
- 可能与近期 main 分支的提交冲突

---

**选项 B: 先合 main 到 P2 分支，验证后再反向合入** ⚡ **推荐**
```powershell
# 1. 更新 P2 分支到最新 main
git checkout codex/director-interpretation-mainline-impl
git merge main -m "Merge latest main into P2 refactor branch"
# 解决冲突（如有）

# 2. 在 P2 分支上验证
pytest  # 必须全量通过

# 3. 确认后合入 main
git checkout main
git merge codex/director-interpretation-mainline-impl -m "Merge P2 refactor after validation"
```

**优点**: 
- 冲突在 P2 分支上解决，main 保持稳定
- 可以充分测试后再合入

**缺点**: 需要两次合并

---

**选项 C: 保持独立，逐步 cherry-pick 关键模块** 🟡 **保守**
```powershell
# 不合入整个分支，只挑选关键提交
git checkout main
git cherry-pick <commit-hash-of-rw_audio>
git cherry-pick <commit-hash-of-rw_config>
# ... 逐个挑选
pytest  # 每次 cherry-pick 后测试
```

**优点**: 风险可控，渐进式  
**缺点**: 
- 耗时长
- 可能破坏原有模块间的依赖关系

---

#### Step 4: 执行选定策略并验证

以**选项 B（推荐）**为例：

```powershell
# 1. 合并 main 到 P2 分支
git checkout codex/director-interpretation-mainline-impl
git merge main

# 2. 解决冲突（如有）
# 查看冲突文件
git status
# 手动编辑冲突文件
# 标记已解决
git add <resolved-files>
git merge --continue

# 3. 全量测试
pytest --cov
# 必须通过（至少 509 tests pass）

# 4. 确认后合入 main
git checkout main
git merge codex/director-interpretation-mainline-impl

# 5. 再次全量测试（main 分支）
pytest --cov
# 必须通过

# 6. 删除 P2 分支（已合入）
git branch -d codex/director-interpretation-mainline-impl
```

---

### 验收标准

**Step 1: P2 分支状态已验证** ✅
- [ ] 切换到 P2 分支后，`ls scripts/rw_*.py` 输出 13 个文件
- [ ] 在 P2 分支上 `pytest` 通过（至少 509 tests pass）

**Step 2: 合入影响已评估** ✅
- [ ] `git diff --stat main...P2分支` 输出已记录
- [ ] 冲突文件（如有）已列出

**Step 3: 合入策略已选定** ✅
- [ ] 在 `branch_decision_table.md` 中记录选定的策略（A/B/C）
- [ ] 记录选定原因

**Step 4: 合入已执行并验证** ✅
- [ ] 选定策略已执行完成
- [ ] main 分支包含 rw_* 模块（`ls scripts/rw_*.py` 输出 13 个文件）
- [ ] main 分支全量测试通过（`pytest --cov`）
- [ ] run_workflow.py 从 6204 行降至 <1000 行（或已删除，逻辑迁移至 rw_*）
- [ ] P2 分支已删除（或已标注"已合入"）

**预估时间**: 4-6 小时（含冲突解决和测试验证）  
**风险**: 高（变更量巨大，需要仔细验证）

---

## 修正 3: Phase 1 Task 1.9 改为 PowerShell 脚本 + Docker Compose（可选）

### 原计划（Phase 2 Task 2.1）
- 标题：Docker Compose 环境
- 位置：Phase 2（3-6周后）
- 内容：只有 Docker Compose，无快速启动脚本

### 修正后（提前到 Phase 1 Task 1.9）

#### Task 1.9: 快速启动脚本（PowerShell + Docker Compose 可选）⚡

**描述**: 提供快速启动脚本，改善新人上手体验。支持 Windows 原生（PowerShell）和 Docker 两种方式。

**背景**:
- 当前环境：Windows 10/11，无 GNU make，无 Docker Desktop
- 现有启动方式：手动 3 步（venv → pip install → uvicorn 长命令）
- 目标："新人上手 <1天"需要配套快速启动方案

---

### 执行步骤

#### 方式 A: PowerShell 脚本（必做，Level 1）

##### Step 1: 创建 scripts/setup.ps1

```powershell
# scripts/setup.ps1
<#
.SYNOPSIS
    Setup Comic Drama Workflow development environment
.DESCRIPTION
    Creates virtual environment and installs dependencies
#>

param(
    [switch]$Force  # Force recreate venv
)

$ErrorActionPreference = "Stop"

Write-Host "=== Comic Drama Workflow Setup ===" -ForegroundColor Cyan

# Check Python version
$pythonVersion = & python --version 2>&1
if ($pythonVersion -notmatch "Python 3\.(11|12|13|14)") {
    Write-Error "Python 3.11+ required. Found: $pythonVersion"
    exit 1
}
Write-Host "✓ Python version: $pythonVersion" -ForegroundColor Green

# Create venv
if ((Test-Path ".venv") -and -not $Force) {
    Write-Host "✓ Virtual environment exists (use -Force to recreate)" -ForegroundColor Yellow
} else {
    if (Test-Path ".venv") {
        Write-Host "Removing existing venv..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force .venv
    }
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
    Write-Host "✓ Virtual environment created" -ForegroundColor Green
}

# Upgrade pip
Write-Host "Upgrading pip..." -ForegroundColor Cyan
& .\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet

# Install dependencies
Write-Host "Installing dependencies..." -ForegroundColor Cyan
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
Write-Host "✓ Dependencies installed" -ForegroundColor Green

# Copy .env.example if .env doesn't exist
if (-not (Test-Path ".env")) {
    Write-Host "Creating .env from .env.example..." -ForegroundColor Cyan
    Copy-Item .env.example .env
    Write-Host "✓ .env created (please edit with your API keys)" -ForegroundColor Yellow
}

Write-Host "`n=== Setup Complete ===" -ForegroundColor Green
Write-Host "Run '.\scripts\dev.ps1' to start the server" -ForegroundColor Cyan
```

##### Step 2: 创建 scripts/dev.ps1

```powershell
# scripts/dev.ps1
<#
.SYNOPSIS
    Start Comic Drama Workflow development server
.DESCRIPTION
    Runs uvicorn with auto-reload for development
#>

param(
    [string]$Host = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

# Check venv exists
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Error "Virtual environment not found. Run '.\scripts\setup.ps1' first."
    exit 1
}

Write-Host "Starting backend server on http://${Host}:${Port}" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop" -ForegroundColor Yellow
Write-Host ""

# Start uvicorn
& .\.venv\Scripts\python.exe -m uvicorn backend.app:app `
    --reload `
    --host $Host `
    --port $Port
```

##### Step 3: 创建 scripts/test.ps1

```powershell
# scripts/test.ps1
<#
.SYNOPSIS
    Run tests for Comic Drama Workflow
.DESCRIPTION
    Runs pytest with coverage reporting
#>

param(
    [switch]$Cov,       # Generate coverage report
    [switch]$Verbose,   # Verbose output
    [string]$Filter     # Test filter (e.g., "test_project")
)

$ErrorActionPreference = "Stop"

# Check venv exists
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Error "Virtual environment not found. Run '.\scripts\setup.ps1' first."
    exit 1
}

$args = @()
if ($Cov) {
    $args += "--cov=backend", "--cov=scripts", "--cov-report=term-missing", "--cov-report=html"
}
if ($Verbose) {
    $args += "-v"
}
if ($Filter) {
    $args += "-k", $Filter
}

Write-Host "Running tests..." -ForegroundColor Cyan
& .\.venv\Scripts\python.exe -m pytest @args

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✓ Tests passed" -ForegroundColor Green
    if ($Cov) {
        Write-Host "Coverage report: htmlcov/index.html" -ForegroundColor Cyan
    }
} else {
    Write-Host "`n✗ Tests failed" -ForegroundColor Red
    exit $LASTEXITCODE
}
```

##### Step 4: 更新 README.md

```markdown
## Quick Start

### Setup (First Time)

```powershell
.\scripts\setup.ps1
```

### Start Development Server

```powershell
.\scripts\dev.ps1
```

Open browser: http://127.0.0.1:8000

### Run Tests

```powershell
# Basic tests
.\scripts\test.ps1

# With coverage
.\scripts\test.ps1 -Cov

# Filter by name
.\scripts\test.ps1 -Filter "test_project"
```

### Environment Configuration

Edit `.env` file with your API keys:
```ini
LLM_API_KEY=your-api-key-here
```

See `.env.example` for all available options.
```

---

#### 方式 B: Docker Compose（可选，Level 2）

**前置条件检查**:
```powershell
# 检查 Docker 是否可用
try {
    docker --version
    Write-Host "✓ Docker is available" -ForegroundColor Green
} catch {
    Write-Host "✗ Docker not found. Install Docker Desktop first:" -ForegroundColor Yellow
    Write-Host "  https://www.docker.com/products/docker-desktop" -ForegroundColor Cyan
    Write-Host "`nContinuing with PowerShell scripts only (Level 1)" -ForegroundColor Yellow
    # 跳过 Docker 配置
}
```

**如果 Docker 可用，创建 docker-compose.yml**:

```yaml
version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ./workspace:/app/workspace
      - ./outputs:/app/outputs
      - ./data/fixtures:/app/data/fixtures:ro
    environment:
      - VIDEO_PROVIDER=${VIDEO_PROVIDER:-local}
      - VIDEO_FALLBACK_MODE=${VIDEO_FALLBACK_MODE:-report}
      - KEYFRAME_PROVIDER=${KEYFRAME_PROVIDER:-local}
      - LLM_API_KEY=${LLM_API_KEY}
      - LLM_BASE_URL=${LLM_BASE_URL}
      - LLM_MODEL=${LLM_MODEL}
    env_file:
      - .env
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    profiles:
      - full  # 只在 --profile full 时启动

volumes:
  redis-data:
```

**启动命令**:
```powershell
# 基础启动（只启动 app）
docker-compose up

# 完整启动（包含 Redis）
docker-compose --profile full up

# 后台运行
docker-compose up -d
```

---

### 验收标准

#### Level 1: PowerShell 脚本（必做）✅

- [ ] `scripts/setup.ps1` 已创建并可执行
  - `.\scripts\setup.ps1` 成功创建 venv 并安装依赖
  - 输出 "Setup Complete"
  
- [ ] `scripts/dev.ps1` 已创建并可启动服务
  - `.\scripts\dev.ps1` 启动 uvicorn
  - 访问 http://127.0.0.1:8000/api/health 返回 `{"status":"ok"}`
  
- [ ] `scripts/test.ps1` 已创建并可运行测试
  - `.\scripts\test.ps1` 运行 pytest
  - `.\scripts\test.ps1 -Cov` 生成覆盖率报告
  
- [ ] README.md 已更新，包含 PowerShell 脚本使用说明

#### Level 2: Docker Compose（可选）✅

**前提**: `docker --version` 命令可用

- [ ] docker-compose.yml 已创建
- [ ] `docker-compose up` 可启动服务
- [ ] 健康检查通过（`docker-compose ps` 显示 healthy）
- [ ] README.md 包含 Docker 启动说明

**如果 Docker 不可用**: 此级别跳过，不影响整体验收

---

### 验收方式：新人测试

**场景**: 新人克隆代码后的体验

**Level 1 测试**:
```powershell
# 1. 克隆代码
git clone <repo-url>
cd "Comic drama"

# 2. 一条命令完成 setup
.\scripts\setup.ps1
# 预期：3-5 分钟完成，输出 "Setup Complete"

# 3. 一条命令启动服务
.\scripts\dev.ps1
# 预期：服务启动，访问 http://127.0.0.1:8000 可用

# 4. 一条命令运行测试
.\scripts\test.ps1
# 预期：测试通过
```

**Level 2 测试**（如果 Docker 可用）:
```powershell
# 1. 一条命令启动（无需 setup.ps1）
docker-compose up
# 预期：服务启动，访问 http://127.0.0.1:8000 可用
```

**通过标准**: 新人从克隆到启动 ≤ 10 分钟（Level 1）或 ≤ 5 分钟（Level 2）

**预估时间**: 3-4 小时  
**风险**: 低（PowerShell 原生支持，Docker 为可选）

---

## 修正 4: Phase 0 Task 0.4 验收标准强化（二选一强制执行）

### 原验收标准
- [ ] 每个子目录的用途已明确
- [ ] 许可证状态已记录
- [ ] 决定保留/删除/转换的方案

**问题**: "决定方案"不可度量，可能导致拖延或模糊处理

### 修正后验收标准

**必须二选一强制执行（不允许"保持现状+README"）**：

#### 选项 A: 转 Git Submodule ✅

```powershell
cd _external/

# 对每个参考项目（假设 Toonflow-app 是其中之一）
git submodule add <Toonflow-app-repo-url> Toonflow-app

# 删除原有文件（已被 submodule 替代）
Remove-Item -Recurse -Force Toonflow-app/* -Exclude .git

cd ..
git add .gitmodules _external/
git commit -m "Convert _external/ to git submodules"
```

**创建 _external/LICENSE_NOTICE.md**:
```markdown
# External References License Notice

This directory contains external reference projects as git submodules.

## Submodules

### Toonflow-app
- **Source**: https://github.com/xxx/Toonflow-app
- **License**: MIT
- **Purpose**: Reference implementation for video generation workflow
- **Version**: commit abc1234
- **Usage**: For development reference only, not incorporated into main codebase

## Compliance

All submodules are used in compliance with their respective licenses.
```

**验收**:
- [ ] `git submodule status` 显示所有子模块
- [ ] `_external/LICENSE_NOTICE.md` 列出每个子模块的许可证和用途
- [ ] `du -sh _external/` 显著下降（submodule 只存 commit ref，不存文件）
- [ ] 文档已提交：`git add _external/LICENSE_NOTICE.md && git commit`

---

#### 选项 B: 移出仓库 ✅

```powershell
# 创建备份目录（在仓库外）
mkdir ..\Comic-drama-references
Move-Item _external\* ..\Comic-drama-references\

# 删除 _external/ 目录
Remove-Item -Recurse -Force _external\

# 添加到 .gitignore（避免误提交）
Add-Content .gitignore "`n_external/"

git add .gitignore
git commit -m "Move _external/ out of repository"
```

**更新 README.md**:
```markdown
## External References

Reference projects are stored outside the repository:
- Location: `../Comic-drama-references/`
- To obtain: (optional, only needed for development reference)

These are not required to run the application.
```

**验收**:
- [ ] `du -sh _external/` → 0（目录不存在或为空）
- [ ] README.md 包含参考项目获取说明
- [ ] .gitignore 包含 `_external/`
- [ ] `git status` 不再显示 _external/ 相关文件

---

**不允许的选项**: "保持现状并添加 README"  
**原因**: 4.2GB 的含糊归属风险太高，不符合开源合规要求

---

## 修正 5: Phase 1 Task 1.2 验收标准（先测量再定阶梯）

### 原验收标准
- [ ] 覆盖率基线已建立（当前 X%）
- [ ] 覆盖率低于 60% 时测试失败

**问题**: 当前覆盖率未知，盲目设定 60% 可能过高或过低

### 修正后验收标准

#### Step 1: 首次测量覆盖率基线

```powershell
# 运行覆盖率测试
.\scripts\test.ps1 -Cov

# 查看覆盖率数值
# 从输出中提取覆盖率百分比，记录为 X%
```

#### Step 2: 根据 X 设定阶梯

| 当前覆盖率 X | Phase 1 目标 | Phase 2 目标 | Phase 3 目标 |
|-------------|-------------|-------------|-------------|
| X < 30% | 30% | 50% | 70% |
| 30% ≤ X < 60% | X + 10% | X + 20% | 80% |
| X ≥ 60% | 保持 X | X + 10% | 80% |

#### Step 3: 配置阈值

```yaml
# .github/workflows/ci.yml
env:
  COVERAGE_THRESHOLD: "30"  # 根据 Step 2 表格设定
```

**验收**:
- [ ] 首次运行 `pytest --cov` 已完成，当前覆盖率 X% 已记录
- [ ] 根据 X 值设定的阶梯目标已写入 `branch_decision_table.md` 或单独文档
- [ ] CI 配置的 `COVERAGE_THRESHOLD` 已更新为 Phase 1 目标值
- [ ] 本地运行 `pytest --cov --cov-fail-under=<Phase1目标>` 通过

**预估时间**: 1 小时  
**风险**: 低

---

## 使用建议

1. **Phase 0 执行顺序**:
   - Task 0.1-0.3（清理临时文件、.gitignore）
   - Task 0.4（_external/ 二选一强制执行）
   - Task 0.5-0.8
   - **Task 0.9（分支整合）** ← 新增，关键
   
2. **Phase 1 执行顺序**:
   - **Task 1.0（rw_* 重构去向）** ← 新增，最高优先
   - Task 1.1（依赖管理）
   - **Task 1.2（覆盖率基线）** ← 修正，先测量
   - Task 1.3-1.8
   - **Task 1.9（PowerShell 脚本 + Docker 可选）** ← 修正，从 Phase 2 提前

3. **Phase 2 调整**:
   - 原 Task 2.1（Docker Compose）已移至 Phase 1 Task 1.9
   - 其余任务保持

---

## 修正摘要

| 修正项 | 原状态 | 修正后 | 影响 |
|--------|--------|--------|------|
| Task 0.9 | 不存在 | 新增分支整合任务 | Phase 0: 6→9 任务 |
| Task 1.0 | 不存在 | 新增 rw_* 去向决策 | Phase 1: 9→10 任务 |
| Task 1.9 | Phase 2 Docker | PowerShell脚本（必做）+ Docker（可选） | 适应 Windows 环境 |
| Task 0.4 验收 | 模糊 | 二选一强制执行 | 提升可执行性 |
| Task 1.2 验收 | 盲目设定 60% | 先测量再定阶梯 | 基于实际情况 |

**总任务数**: 26 → **29 必做 + 2 评估**（Task 1.9 Level 2 为可选）

---

**修正文档完成时间**: 2026-08-27 02:15  
**建议**: 优先执行 Task 0.9 和 Task 1.0，这是所有重构的前提
