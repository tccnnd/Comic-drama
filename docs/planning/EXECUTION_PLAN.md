# Comic Drama Workflow - 优化执行计划

**制定日期**: 2026-08-24  
**计划周期**: 4 个阶段，共 3 个月  
**负责人**: 待定  
**状态**: 📋 待开始

---

## 📊 计划概览

| 阶段 | 时间 | 任务数 | 优先级 | 状态 |
|------|------|--------|--------|------|
| Phase 0 | 立即-3天 | 6 | 🔴 紧急 | ⏳ 待开始 |
| Phase 1 | 1-2周 | 8 | ⚡ 高 | ⏳ 待开始 |
| Phase 2 | 3-6周 | 7 | 🎯 中 | ⏳ 待开始 |
| Phase 3 | 7-12周 | 5 | 🚀 长期 | ⏳ 待开始 |

**总计**: 26 个任务

---

## Phase 0: 紧急清理（立即-3天）

### 目标
清理技术债务、确保项目健康和开源合规性。

### 任务清单

#### Task 0.1: 清理 pytest 临时目录 🔴

**描述**: 清理所有未被清理的 pytest 临时目录和测试残留。

**执行步骤**:
```powershell
# 1. 列出所有 pytest 临时目录
Get-ChildItem -Path "E:\APP\Comic drama" -Recurse -Directory -Filter "pytest_*" -ErrorAction SilentlyContinue | 
    Select-Object FullName | Out-File pytest_dirs.txt

Get-ChildItem -Path "E:\APP\Comic drama" -Recurse -Directory -Filter "tmp_pytest*" -ErrorAction SilentlyContinue | 
    Select-Object FullName | Out-File -Append pytest_dirs.txt

# 2. 审查列表（确保没有重要文件）
notepad pytest_dirs.txt

# 3. 确认后删除
Get-Content pytest_dirs.txt | ForEach-Object {
    if (Test-Path $_) {
        Remove-Item $_ -Recurse -Force -ErrorAction Continue
        Write-Host "Deleted: $_"
    }
}

# 4. 清理列表文件
Remove-Item pytest_dirs.txt
```

**验收标准**:
- [ ] 所有 `pytest_*` 和 `tmp_pytest*` 目录已删除
- [ ] `find . -name "pytest_*" -type d` 返回 0 结果
- [ ] 磁盘空间释放（预计 500MB+）
- [ ] 无权限拒绝错误

**预估时间**: 30 分钟  
**风险**: 低（临时目录可安全删除）

---

#### Task 0.2: 清理根目录日志和进程文件 🔴

**描述**: 清理项目根目录的日志、PID、job 文件。

**执行步骤**:
```powershell
cd "E:\APP\Comic drama"

# 1. 列出待清理文件
Get-ChildItem -File | Where-Object { 
    $_.Extension -in @('.log', '.pid', '.job', '.txt') -and
    $_.Name -match '(cloud_tunnel|dev_server|comfyui)'
} | Select-Object Name, Length | Format-Table

# 2. 确认后删除
Remove-Item cloud_tunnel.* -ErrorAction SilentlyContinue
Remove-Item dev_server*.* -ErrorAction SilentlyContinue
Remove-Item comfyui*.log -ErrorAction SilentlyContinue
Remove-Item launcher_env_probe.txt -ErrorAction SilentlyContinue
```

**验收标准**:
- [ ] 所有 `.log`、`.pid`、`.job` 文件已删除
- [ ] 根目录只保留版本控制文件和配置文件
- [ ] `git status` 不显示已删除文件（已在 .gitignore 中）

**预估时间**: 15 分钟  
**风险**: 低

---

#### Task 0.3: 完善 .gitignore 🔴

**描述**: 完善 .gitignore，防止运行时文件和临时文件被版本控制。

**执行步骤**:
```powershell
# 备份现有 .gitignore
Copy-Item .gitignore .gitignore.backup

# 追加新规则（参考 PROJECT_ANALYSIS.md）
```

**新增内容**:
```gitignore
# ─── Runtime & Process Files ───────────────────────────────────────────────
*.log
*.pid
*.job
*.err.log
*.out.log
cloud_tunnel.*
dev_server*.*
comfyui*.log
launcher_env_probe.txt

# ─── Pytest & Test Artifacts ───────────────────────────────────────────────
.pytest_cache/
.tmp/pytest_*/
.tmp/tmp_pytest*/
data/tmp_pytest*/
tmp/pytest_*/
*.pyc
*.pyo
*.pyd
__pycache__/

# ─── Workspace & Outputs ───────────────────────────────────────────────────
workspace/
outputs/
tools/
tmp/
.tmp/

# ─── Environment ───────────────────────────────────────────────────────────
.env
.env.local
.venv/
venv/
*.env.backup

# ─── IDE & Editors ─────────────────────────────────────────────────────────
.vscode/
.idea/
*.swp
*.swo
*~
.DS_Store

# ─── Build Artifacts ───────────────────────────────────────────────────────
dist/
build/
*.egg-info/
.eggs/

# ─── Coverage & Reports ────────────────────────────────────────────────────
.coverage
htmlcov/
.pytest_cache/
coverage.xml
*.cover

# ─── Backup Files ──────────────────────────────────────────────────────────
*.bak
*.backup
*~
```

**验收标准**:
- [ ] .gitignore 包含所有运行时文件模式
- [ ] `git status` 不再显示日志、PID、临时文件
- [ ] 新的测试运行不会产生未跟踪文件
- [ ] 备份文件已保存为 `.gitignore.backup`

**预估时间**: 20 分钟  
**风险**: 低（已备份）

---

#### Task 0.4: 审查 _external/ 目录 🔴

**描述**: 审查 _external/ 目录内容，确定许可证状态和必要性。

**执行步骤**:
```powershell
cd "E:\APP\Comic drama\_external"

# 1. 列出顶层目录
Get-ChildItem -Directory | Select-Object Name, @{N='Size';E={(Get-ChildItem $_.FullName -Recurse | Measure-Object -Property Length -Sum).Sum / 1GB}}

# 2. 查找许可证文件
Get-ChildItem -Recurse -Include LICENSE*,COPYING*,README* | Select-Object FullName

# 3. 检查是否为 Git submodule
git submodule status
```

**决策树**:
```
_external/ 内容是什么？
├─ 参考项目（Toonflow-app 等）
│  └─ 选项 A: 转换为 Git submodule
│  └─ 选项 B: 删除并在文档中链接
│  └─ 选项 C: 保留但添加 LICENSE_NOTICE.md
│
└─ 依赖库或工具
   └─ 选项 D: 移到 tools/ 并版本锁定
   └─ 选项 E: 删除并通过包管理器安装
```

**验收标准**:
- [ ] 每个子目录的用途已明确
- [ ] 许可证状态已记录（创建 `_external/LICENSE_NOTICE.md`）
- [ ] 决定保留/删除/转换的方案
- [ ] 如需保留，已更新 AGENTS.md 和 README.md 说明
- [ ] 如需删除，已备份到项目外路径

**预估时间**: 1-2 小时  
**风险**: 中（需要仔细审查许可证）

---

#### Task 0.5: 创建 _external/LICENSE_NOTICE.md（如保留）

**描述**: 如果决定保留 _external/，创建许可证声明文件。

**模板**:
```markdown
# External References License Notice

This directory contains external reference projects for development and research purposes.

## Projects Included

### Toonflow-app
- **Source**: https://github.com/xxx/Toonflow-app
- **License**: MIT / Apache 2.0 / GPL (specify)
- **Purpose**: Reference implementation for video generation workflow
- **Version**: (commit hash or tag)
- **Modifications**: None / Listed below

### (其他项目)
- **Source**: 
- **License**: 
- **Purpose**: 
- **Version**: 
- **Modifications**: 

## Usage Restrictions

These external projects are:
- ✅ For reference and learning purposes only
- ✅ Not distributed with production releases
- ❌ Not incorporated into the main codebase
- ❌ Not relicensed or claimed as original work

## Compliance

All external projects are used in compliance with their respective licenses. If you believe there is a license violation, please contact: (email)
```

**验收标准**:
- [ ] LICENSE_NOTICE.md 已创建
- [ ] 所有子项目已列出
- [ ] 许可证已确认
- [ ] README.md 已更新，说明 _external/ 的性质

**预估时间**: 30 分钟  
**风险**: 中

---

#### Task 0.6: 验证 Git 清洁状态

**描述**: 确认 Git 状态清洁，无未跟踪的运行时文件。

**执行步骤**:
```powershell
cd "E:\APP\Comic drama"

# 1. 检查状态
git status

# 2. 检查未跟踪文件
git status --short | Where-Object { $_ -match '^\?\?' }

# 3. 验证 .gitignore 生效
# 创建测试日志文件
"test" | Out-File test.log
git status  # 应该看不到 test.log
Remove-Item test.log
```

**验收标准**:
- [ ] `git status` 只显示有意义的变更
- [ ] 无日志、PID、临时文件显示
- [ ] .gitignore 测试通过

**预估时间**: 10 分钟  
**风险**: 低

---

### Phase 0 总体验收

**必须满足**:
- [ ] 所有 pytest 临时目录已清理
- [ ] 根目录无运行时文件
- [ ] .gitignore 已完善
- [ ] _external/ 许可证状态已明确
- [ ] Git 状态清洁

**可选**:
- [ ] 提交 Phase 0 变更到独立分支 `cleanup/phase-0`

---

## Phase 1: 高优先级优化（1-2周）

### 目标
现代化依赖管理、加固测试基础设施、继续代码重构。

---

#### Task 1.1: 依赖管理现代化 ⚡

**描述**: 引入依赖锁定和生产/开发依赖分离。

**方案选择**:

**选项 A: 继续使用 pip + pip-tools（推荐，成本低）**
```powershell
# 1. 安装 pip-tools
pip install pip-tools

# 2. 创建 requirements.in
```

**requirements.in**:
```txt
# Production dependencies
fastapi>=0.136.1,<0.200
uvicorn[standard]>=0.47.0,<1.0
pillow>=12.2.0,<13.0
imageio-ffmpeg>=0.6.0,<1.0
edge-tts>=7.2.8,<8.0
httpx>=0.28.1,<1.0
websockets>=16.0,<17.0
pydantic>=2.0,<3.0
python-multipart>=0.0.9
```

**requirements-dev.in**:
```txt
-r requirements.txt

# Development dependencies
pytest>=8.3.4,<9.0
pytest-cov>=6.0.0,<7.0
pytest-asyncio>=0.24.0
black>=24.0.0
isort>=5.13.0
mypy>=1.0.0
bandit>=1.7.0
safety>=3.0.0
```

```powershell
# 3. 编译锁定文件
pip-compile requirements.in
pip-compile requirements-dev.in

# 4. 安装
pip-sync requirements-dev.txt  # 开发环境
pip-sync requirements.txt      # 生产环境
```

**选项 B: 迁移到 Poetry（推荐，长期优势）**
```powershell
# 1. 安装 Poetry
pip install poetry

# 2. 初始化
poetry init --no-interaction

# 3. 迁移依赖
poetry add fastapi uvicorn pillow imageio-ffmpeg edge-tts httpx websockets pydantic python-multipart
poetry add --group dev pytest pytest-cov black isort mypy bandit safety

# 4. 生成锁文件
poetry lock

# 5. 安装
poetry install
```

**验收标准**:
- [ ] 存在 `requirements.txt` + `requirements-dev.txt`（选项 A）
  或 `pyproject.toml` + `poetry.lock`（选项 B）
- [ ] 所有依赖版本已锁定
- [ ] 生产/开发依赖已分离
- [ ] `pip install -r requirements.txt` 或 `poetry install` 成功
- [ ] 运行 `python -m scripts.run_workflow --input inputs\sample_story.txt --keyframe-provider local` 成功

**预估时间**: 2-3 小时  
**风险**: 中（可能发现依赖冲突）

---

#### Task 1.2: 测试覆盖率基线建立 ⚡

**描述**: 建立测试覆盖率报告和 CI 集成。

**执行步骤**:
```powershell
# 1. 安装覆盖率工具（如未安装）
pip install pytest-cov

# 2. 运行覆盖率测试
pytest --cov=backend --cov=scripts --cov-report=html --cov-report=term --cov-report=xml

# 3. 查看报告
# HTML: htmlcov/index.html
# Terminal: 直接输出
# XML: coverage.xml（供 CI 使用）
```

**配置 pytest.ini**:
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = 
    --cov=backend
    --cov=scripts
    --cov-report=html
    --cov-report=term-missing
    --cov-fail-under=60
    -v
```

**验收标准**:
- [ ] 覆盖率基线已建立（当前 X%）
- [ ] HTML 报告可正常查看
- [ ] 覆盖率低于 60% 时测试失败
- [ ] coverage.xml 已生成（供 CI 使用）
- [ ] 已添加到 .gitignore: `htmlcov/`, `.coverage`, `coverage.xml`

**预估时间**: 1 小时  
**风险**: 低

---

#### Task 1.3: 代码重构 - backend/app.py 拆分 ⚡

**描述**: 将 backend/app.py（60KB）拆分为模块化路由。

**目标结构**:
```
backend/
  ├── app.py              # 主应用（只做初始化和路由注册）
  ├── routers/
  │   ├── __init__.py
  │   ├── projects.py     # 项目 CRUD
  │   ├── scenes.py       # 场景操作
  │   ├── characters.py   # 角色管理
  │   ├── assets.py       # 资产管理
  │   ├── exports.py      # 导出和构建
  │   ├── health.py       # 健康检查
  │   └── websocket.py    # WebSocket 连接
```

**执行步骤**:
```powershell
# 1. 创建路由目录
mkdir backend/routers
New-Item backend/routers/__init__.py

# 2. 逐个拆分路由（示例：projects.py）
```

**backend/routers/projects.py**:
```python
from fastapi import APIRouter, HTTPException
from backend.project_runtime import create_project, load_project, delete_project
# ... 其他导入

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])

@router.post("/")
async def api_create_project(request: CreateProjectRequest):
    # 迁移现有逻辑
    pass

@router.get("/{project_id}")
async def api_get_project(project_id: str):
    pass

# ... 其他端点
```

**backend/app.py（重构后）**:
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.routers import projects, scenes, characters, assets, exports, health, websocket

app = FastAPI(title="Comic Drama Workflow API")

# CORS
app.add_middleware(CORSMiddleware, ...)

# 注册路由
app.include_router(projects.router)
app.include_router(scenes.router)
app.include_router(characters.router)
app.include_router(assets.router)
app.include_router(exports.router)
app.include_router(health.router)
app.include_router(websocket.router)

# 静态文件
app.mount("/", StaticFiles(...), name="frontend")
```

**验收标准**:
- [ ] backend/app.py 从 60KB 降至 <5KB
- [ ] 所有端点功能保持不变
- [ ] 路由按模块清晰组织
- [ ] `python -m py_compile backend/app.py backend/routers/*.py` 通过
- [ ] API 文档（/docs）正常访问
- [ ] 现有测试通过

**预估时间**: 4-6 小时  
**风险**: 中（需仔细迁移，避免遗漏）

---

#### Task 1.4: 前端包管理初始化 ⚡

**描述**: 为前端添加 package.json 和基础工具链。

**执行步骤**:
```powershell
cd "E:\APP\Comic drama\frontend"

# 1. 初始化 package.json
npm init -y

# 2. 安装开发依赖
npm install -D vite eslint prettier
```

**package.json**:
```json
{
  "name": "comic-drama-frontend",
  "version": "0.4.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "lint": "eslint *.js",
    "format": "prettier --write *.js *.css *.html"
  },
  "devDependencies": {
    "vite": "^5.0.0",
    "eslint": "^8.0.0",
    "prettier": "^3.0.0"
  }
}
```

**vite.config.js**:
```javascript
import { defineConfig } from 'vite'

export default defineConfig({
  root: '.',
  publicDir: '../assets',
  build: {
    outDir: '../dist/frontend',
    emptyOutDir: true
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000'
    }
  }
})
```

**.eslintrc.json**:
```json
{
  "env": {
    "browser": true,
    "es2021": true
  },
  "extends": "eslint:recommended",
  "parserOptions": {
    "ecmaVersion": "latest",
    "sourceType": "module"
  }
}
```

**验收标准**:
- [ ] package.json 已创建
- [ ] `npm install` 成功
- [ ] `npm run lint` 通过
- [ ] `npm run dev` 可启动开发服务器
- [ ] Vite 代理配置正确（/api 转发到 FastAPI）
- [ ] node_modules/ 已添加到 .gitignore

**预估时间**: 1-2 小时  
**风险**: 低

---

#### Task 1.5: 添加代码格式化工具 ⚡

**描述**: 统一 Python 和 JavaScript 代码风格。

**Python: Black + isort**
```powershell
# 1. 安装
pip install black isort

# 2. 配置 pyproject.toml
```

**pyproject.toml**:
```toml
[tool.black]
line-length = 100
target-version = ['py39', 'py310', 'py311']
include = '\.pyi?$'
extend-exclude = '''
/(
  # 默认排除
  \.git
  | \.venv
  | _external
)/
'''

[tool.isort]
profile = "black"
line_length = 100
skip_gitignore = true
extend_skip_glob = ["_external/*"]
```

```powershell
# 3. 运行格式化
black backend/ scripts/ tests/
isort backend/ scripts/ tests/
```

**JavaScript: Prettier**
```powershell
cd frontend

# 1. 配置 .prettierrc
```

**.prettierrc**:
```json
{
  "semi": true,
  "singleQuote": false,
  "tabWidth": 2,
  "trailingComma": "es5",
  "printWidth": 100
}
```

```powershell
# 2. 运行格式化
npm run format
```

**验收标准**:
- [ ] Black 和 isort 配置完成
- [ ] Prettier 配置完成
- [ ] 所有代码已格式化
- [ ] 格式化不影响功能（测试通过）

**预估时间**: 1 小时  
**风险**: 低

---

#### Task 1.6: 类型检查初始化 ⚡

**描述**: 为 Python 代码添加类型检查。

**执行步骤**:
```powershell
# 1. 安装 mypy
pip install mypy

# 2. 配置
```

**pyproject.toml**:
```toml
[tool.mypy]
python_version = "3.9"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = false  # 初期宽松，逐步严格
ignore_missing_imports = true
exclude = [
    '_external/',
    '.venv/',
]

# 严格检查特定模块
[[tool.mypy.overrides]]
module = "backend.project_models"
disallow_untyped_defs = true
```

```powershell
# 3. 运行类型检查
mypy backend/ scripts/
```

**验收标准**:
- [ ] mypy 配置完成
- [ ] 当前代码通过类型检查（或记录已知问题）
- [ ] 关键模块（project_models）类型覆盖 >80%

**预估时间**: 2 小时  
**风险**: 中（可能发现现有类型错误）

---

#### Task 1.7: CI/CD 增强 - Lint 和测试 ⚡

**描述**: 增强 GitHub Actions CI 流程。

**.github/workflows/ci.yml**:
```yaml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  lint-python:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install black isort mypy
      
      - name: Check formatting
        run: |
          black --check backend/ scripts/ tests/
          isort --check backend/ scripts/ tests/
      
      - name: Type check
        run: |
          mypy backend/ scripts/

  lint-javascript:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: '20'
      
      - name: Install dependencies
        working-directory: frontend
        run: npm ci
      
      - name: Lint
        working-directory: frontend
        run: npm run lint
      
      - name: Check syntax
        run: node --check frontend/app.js

  test:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements-dev.txt
      
      - name: Run tests
        run: |
          pytest --cov --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml

  security:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install security tools
        run: |
          pip install bandit safety
      
      - name: Run Bandit
        run: |
          bandit -r backend/ scripts/ -f json -o bandit-report.json
      
      - name: Check dependencies
        run: |
          safety check --json
```

**验收标准**:
- [ ] CI 工作流包含 lint、test、security 作业
- [ ] 所有作业在 main 分支通过
- [ ] PR 自动触发 CI
- [ ] 覆盖率报告上传到 Codecov（可选）

**预估时间**: 2 小时  
**风险**: 低

---

#### Task 1.8: 文档更新 ⚡

**描述**: 更新 README 和相关文档，反映新的工具链。

**更新内容**:

**README.md - Setup 部分**:
```markdown
## Setup

### Backend

```powershell
# 使用 pip-tools（推荐）
pip install pip-tools
pip-sync requirements-dev.txt

# 或使用 Poetry
poetry install
```

### Frontend

```powershell
cd frontend
npm install
```

### 开发工具

```powershell
# 代码格式化
black backend/ scripts/
isort backend/ scripts/
cd frontend && npm run format

# 类型检查
mypy backend/ scripts/

# 测试
pytest --cov

# Lint
cd frontend && npm run lint
```
```

**CONTRIBUTING.md - 新增开发规范**:
```markdown
## Development Standards

### Code Style

- **Python**: Follow Black style (line length: 100)
- **JavaScript**: Follow Prettier config
- **Imports**: Use isort for Python import ordering

### Pre-commit Checks

Before committing:
```powershell
# Format code
black backend/ scripts/
isort backend/ scripts/
cd frontend && npm run format

# Run tests
pytest

# Check types
mypy backend/ scripts/
```

### Type Hints

New code should include type hints. Use mypy to verify.
```

**验收标准**:
- [ ] README.md 已更新
- [ ] CONTRIBUTING.md 已更新
- [ ] docs/development.md 已创建（开发指南）
- [ ] 所有命令已验证

**预估时间**: 1 小时  
**风险**: 低

---

### Phase 1 总体验收

**必须满足**:
- [ ] 依赖管理现代化完成
- [ ] 测试覆盖率基线建立（>60%）
- [ ] backend/app.py 已拆分
- [ ] 前端包管理已初始化
- [ ] CI/CD 流程增强
- [ ] 所有测试通过
- [ ] 文档已更新

**可选**:
- [ ] 覆盖率达到 80%+
- [ ] 类型覆盖率达到 70%+
- [ ] 提交到独立分支 `refactor/phase-1`

---

## Phase 2: 中优先级优化（3-6周）

### 目标
环境解耦、数据治理、AI 工具协作自动化。

---

#### Task 2.1: Docker Compose 环境 🎯

**描述**: 创建 Docker Compose 配置，简化开发环境搭建。

**docker-compose.yml**:
```yaml
version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    volumes:
      - ./workspace:/app/workspace
      - ./outputs:/app/outputs
      - ./data/fixtures:/app/data/fixtures:ro
    environment:
      - VIDEO_PROVIDER=${VIDEO_PROVIDER:-local}
      - VIDEO_FALLBACK_MODE=${VIDEO_FALLBACK_MODE:-report}
      - KEYFRAME_PROVIDER=${KEYFRAME_PROVIDER:-local}
    ports:
      - "8000:8000"
    depends_on:
      - redis
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data

  comfyui:
    image: comfyui/comfyui:latest
    ports:
      - "8188:8188"
    volumes:
      - ./workflows:/app/workflows:ro
      - comfyui-models:/app/models
    profiles:
      - full  # 只在 --profile full 时启动

volumes:
  redis-data:
  comfyui-models:
```

**Dockerfile**:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY frontend/ ./frontend/
COPY video_providers.py .

# 健康检查端点
HEALTHCHECK CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

**验收标准**:
- [ ] `docker-compose up` 成功启动
- [ ] 应用可通过 http://localhost:8000 访问
- [ ] 健康检查通过
- [ ] workspace/ 和 outputs/ 正确挂载
- [ ] 环境变量正确传递

**预估时间**: 3-4 小时  
**风险**: 中

---

#### Task 2.2: 数据目录治理 🎯

**描述**: 规范 data/ 目录，区分版本控制和运行时数据。

**目标结构**:
```
data/
  ├── fixtures/          # 测试夹具（版本控制）
  │   ├── sample_project.json
  │   ├── test_characters.json
  │   └── test_scenes.json
  ├── templates/         # 模板（版本控制）
  │   ├── default_style.json
  │   ├── default_audio_style.json
  │   └── comfyui_workflow_template.json
  ├── schemas/           # JSON Schema（版本控制）
  │   ├── project.schema.json
  │   ├── scene.schema.json
  │   └── character.schema.json
  ├── .gitignore         # 忽略运行时数据
  └── README.md          # 说明文档
```

**data/.gitignore**:
```gitignore
# 忽略所有内容，除了明确需要版本控制的
*
!fixtures/
!templates/
!schemas/
!.gitignore
!README.md
```

**执行步骤**:
```powershell
cd "E:\APP\Comic drama\data"

# 1. 创建目录
mkdir fixtures, templates, schemas

# 2. 迁移现有数据
# 识别哪些是测试夹具，哪些是运行时数据
Get-ChildItem -File -Filter "*.json" | ForEach-Object {
    if ($_.Name -match "test_|sample_") {
        Move-Item $_ fixtures/
    } elseif ($_.Name -match "template_|default_") {
        Move-Item $_ templates/
    }
}

# 3. 清理运行时数据
# （需要人工审查）
```

**验收标准**:
- [ ] data/ 目录结构清晰
- [ ] fixtures/ 包含所有测试夹具
- [ ] templates/ 包含所有模板
- [ ] 运行时数据不被版本控制
- [ ] README.md 说明各目录用途
- [ ] 测试仍然通过

**预估时间**: 2-3 小时  
**风险**: 中（需仔细分类）

---

#### Task 2.3: 健康检查端点完善 🎯

**描述**: 完善 `/health` 端点，提供详细的系统状态。

**backend/routers/health.py**:
```python
from fastapi import APIRouter
from backend.comfyui_health import check_comfyui_health
from video_providers import get_video_provider_status
import sys
import platform

router = APIRouter(tags=["health"])

@router.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "version": "0.4.0",
        "python": sys.version,
        "platform": platform.system(),
    }

@router.get("/health/detailed")
async def detailed_health():
    """详细健康检查"""
    video_provider = get_video_provider_status()
    comfyui_status = check_comfyui_health()
    
    return {
        "status": "healthy" if all([
            comfyui_status.get("available", False),
            video_provider.get("configured_count", 0) > 0
        ]) else "degraded",
        "components": {
            "video_provider": {
                "status": "ok" if video_provider.get("configured_count", 0) > 0 else "warning",
                "provider": video_provider.get("provider", {}).get("id"),
                "configured_count": video_provider.get("configured_count", 0),
                "missing_env": video_provider.get("missing_env", [])
            },
            "comfyui": {
                "status": "ok" if comfyui_status.get("available") else "unavailable",
                "available": comfyui_status.get("available", False),
                "message": comfyui_status.get("message", "")
            },
            "storage": {
                "status": "ok",
                "workspace": "mounted",
                "outputs": "mounted"
            }
        }
    }
```

**验收标准**:
- [ ] `/health` 返回基础状态
- [ ] `/health/detailed` 返回详细状态
- [ ] Docker 健康检查使用该端点
- [ ] 状态准确反映系统可用性

**预估时间**: 1-2 小时  
**风险**: 低

---

#### Task 2.4: AI 工具协作 pre-commit hook 🎯

**描述**: 创建 pre-commit hook 验证 AI 工具协作规则。

**scripts/check_file_ownership.py**:
```python
#!/usr/bin/env python3
"""
检查高风险文件的修改是否符合协作规则
"""
import sys
import subprocess
from pathlib import Path

HIGH_RISK_FILES = {
    "scripts/run_workflow.py": "Codex",
    "backend/project_runtime.py": "Codex",
    "video_providers.py": "Codex",
    "scripts/video_provider_adapters.py": "Codex",
    "backend/video_generation.py": "Codex",
    "backend/scene_renderer.py": "Codex",
}

def get_staged_files():
    """获取暂存的文件"""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True
    )
    return result.stdout.strip().split('\n')

def get_commit_message():
    """获取提交消息"""
    result = subprocess.run(
        ["git", "log", "-1", "--pretty=%B"],
        capture_output=True,
        text=True
    )
    return result.stdout.strip()

def check_ownership():
    """检查文件所有权"""
    staged_files = get_staged_files()
    commit_msg = get_commit_message()
    
    violations = []
    
    for file_path in staged_files:
        if file_path in HIGH_RISK_FILES:
            owner = HIGH_RISK_FILES[file_path]
            # 检查提交消息是否包含所有者标记
            if f"[{owner.lower()}]" not in commit_msg.lower():
                violations.append(
                    f"⚠️  {file_path} is owned by {owner}\n"
                    f"   Please include [{owner}] in commit message or\n"
                    f"   coordinate with the {owner} agent."
                )
    
    if violations:
        print("\n🚨 File Ownership Violation Detected:\n")
        for v in violations:
            print(v)
        print("\nHigh-risk files modified:")
        for f in staged_files:
            if f in HIGH_RISK_FILES:
                print(f"  - {f} (owner: {HIGH_RISK_FILES[f]})")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(check_ownership())
```

**.pre-commit-config.yaml**:
```yaml
repos:
  - repo: local
    hooks:
      - id: check-file-ownership
        name: Check file ownership
        entry: python scripts/check_file_ownership.py
        language: system
        pass_filenames: false
        stages: [commit]
      
      - id: format-python
        name: Format Python code
        entry: black
        language: system
        types: [python]
        exclude: '^_external/'
      
      - id: sort-imports
        name: Sort Python imports
        entry: isort
        language: system
        types: [python]
        exclude: '^_external/'
      
      - id: type-check
        name: Type check Python
        entry: mypy
        language: system
        types: [python]
        pass_filenames: false
        exclude: '^_external/'
```

**安装**:
```powershell
# 1. 安装 pre-commit
pip install pre-commit

# 2. 安装 hooks
pre-commit install

# 3. 测试
pre-commit run --all-files
```

**验收标准**:
- [ ] pre-commit hook 已安装
- [ ] 修改高风险文件时触发检查
- [ ] 格式化和类型检查自动运行
- [ ] 违规时提交被阻止
- [ ] 文档已更新（CONTRIBUTING.md）

**预估时间**: 2-3 小时  
**风险**: 低

---

#### Task 2.5: 日志规范化 🎯

**描述**: 统一日志格式，引入结构化日志。

**backend/logger.py（增强）**:
```python
import logging
import sys
from pathlib import Path

def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    """设置结构化日志"""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    
    # 格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    
    logger.addHandler(console_handler)
    
    # 可选：文件处理器（只记录 WARNING 以上）
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    file_handler = logging.FileHandler(log_dir / f"{name}.log")
    file_handler.setLevel("WARNING")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger
```

**使用示例**:
```python
from backend.logger import setup_logger

logger = setup_logger(__name__)

logger.info("Processing scene", extra={
    "scene_id": scene.id,
    "provider": provider.id,
    "duration": duration
})
```

**验收标准**:
- [ ] 所有模块使用统一的日志配置
- [ ] 日志包含时间戳、模块名、级别
- [ ] WARNING 以上日志写入文件
- [ ] logs/ 目录已添加到 .gitignore

**预估时间**: 2 小时  
**风险**: 低

---

#### Task 2.6: 性能基准测试 🎯

**描述**: 建立性能基准，跟踪关键操作耗时。

**tests/benchmark/test_performance.py**:
```python
import pytest
import time
from pathlib import Path
from scripts.run_workflow import analyze_script_workflow, build_storyboard

@pytest.mark.benchmark
def test_script_analysis_performance(tmp_path):
    """测试脚本分析性能"""
    script = "测试脚本内容..." * 100
    
    start = time.time()
    result = analyze_script_workflow(script)
    duration = time.time() - start
    
    assert duration < 5.0, f"Script analysis too slow: {duration:.2f}s"
    assert len(result.scenes) > 0

@pytest.mark.benchmark
def test_storyboard_build_performance(tmp_path):
    """测试分镜构建性能"""
    # ... 性能测试
    pass
```

**pytest.ini（添加）**:
```ini
markers =
    benchmark: Performance benchmark tests
    slow: Slow running tests
```

**验收标准**:
- [ ] 关键操作有性能测试
- [ ] 基准阈值已设定
- [ ] 可通过 `pytest -m benchmark` 单独运行
- [ ] CI 中记录性能趋势（可选）

**预估时间**: 3-4 小时  
**风险**: 低

---

#### Task 2.7: 安全扫描集成 🎯

**描述**: 集成安全扫描工具。

**执行步骤**:
```powershell
# 1. 安装工具
pip install bandit safety

# 2. 运行 Bandit（代码安全扫描）
bandit -r backend/ scripts/ -f json -o bandit-report.json

# 3. 运行 Safety（依赖漏洞扫描）
safety check --json --output safety-report.json
```

**bandit.yaml**:
```yaml
exclude_dirs:
  - _external
  - .venv
  - tests

tests:
  - B201  # flask_debug_true
  - B301  # pickle
  - B401  # import_telnetlib
  - B501  # request_with_no_cert_validation
  - B601  # paramiko_calls
  - B602  # subprocess_popen_with_shell_equals_true
```

**CI 集成**（已在 Task 1.7 中添加）

**验收标准**:
- [ ] Bandit 扫描无高危问题
- [ ] Safety 检查无已知漏洞
- [ ] 扫描集成到 CI
- [ ] 报告可查看

**预估时间**: 1-2 小时  
**风险**: 低（可能发现现有安全问题）

---

### Phase 2 总体验收

**必须满足**:
- [ ] Docker Compose 环境可用
- [ ] 数据目录治理完成
- [ ] 健康检查端点完善
- [ ] AI 协作 hook 已安装
- [ ] 日志规范化完成
- [ ] 安全扫描无高危问题

**可选**:
- [ ] 性能基准测试覆盖所有关键操作
- [ ] 提交到独立分支 `infra/phase-2`

---

## Phase 3: 长期优化（7-12周）

### 目标
性能优化、可观测性、插件系统扩展。

---

#### Task 3.1: 任务队列引入（Celery + Redis）🚀

**描述**: 将耗时的视频渲染任务迁移到异步任务队列。

**问题现状**:
- 视频渲染在主线程同步执行，阻塞 API 响应
- 无法并行处理多个场景
- 长时间任务容易被超时中断

**执行步骤**:

```powershell
# 1. 安装依赖
pip install celery redis

# 2. 启动 Redis（如未运行）
docker-compose up -d redis
```

**backend/tasks.py**:
```python
from celery import Celery
import os

celery_app = Celery(
    'comic_drama',
    broker=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    backend=os.getenv('REDIS_URL', 'redis://localhost:6379/0')
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Shanghai',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1小时超时
    task_soft_time_limit=3300,
)

@celery_app.task(bind=True)
def render_scene_task(self, project_id: str, scene_id: int, provider: str):
    """异步渲染场景视频"""
    from backend.project_runtime import rerender_scene_video
    
    try:
        self.update_state(state='PROGRESS', meta={'progress': 0})
        
        result = rerender_scene_video(project_id, scene_id, provider)
        
        self.update_state(state='SUCCESS', meta={'result': result})
        return result
    except Exception as exc:
        self.update_state(state='FAILURE', meta={'error': str(exc)})
        raise

@celery_app.task(bind=True)
def render_scene_image_task(self, project_id: str, scene_id: int, provider: str):
    """异步渲染场景关键帧"""
    from backend.project_runtime import rerender_scene_image
    # ... 类似实现
```

**backend/routers/scenes.py（使用任务）**:
```python
from backend.tasks import render_scene_task

@router.post("/{project_id}/scenes/{scene_id}/rerender/video")
async def api_rerender_video(project_id: str, scene_id: int, request: RerenderRequest):
    """异步触发场景视频重渲染"""
    
    # 提交任务
    task = render_scene_task.delay(project_id, scene_id, request.provider)
    
    return {
        "task_id": task.id,
        "status": "pending",
        "message": "Video rendering queued"
    }

@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """查询任务状态"""
    from backend.tasks import celery_app
    
    task = celery_app.AsyncResult(task_id)
    
    return {
        "task_id": task.id,
        "state": task.state,
        "progress": task.info.get('progress', 0) if task.state == 'PROGRESS' else None,
        "result": task.info if task.state == 'SUCCESS' else None,
        "error": task.info.get('error') if task.state == 'FAILURE' else None
    }
```

**验收标准**:
- [ ] Celery 和 Redis 已配置
- [ ] 视频渲染任务可通过 API 异步提交
- [ ] 任务状态可查询（PENDING/PROGRESS/SUCCESS/FAILURE）
- [ ] 任务支持超时限制
- [ ] 前端轮询任务状态并显示进度
- [ ] 现有测试通过

**预估时间**: 6-8 小时  
**风险**: 中（需要仔细处理异步状态）

---

#### Task 3.2: 数据库持久化（SQLite → PostgreSQL）🚀

**描述**: 将项目元数据从文件系统迁移到数据库。

**问题现状**:
- 项目数据存储在 `workspace/<project_id>/project.json`
- 无法高效查询（例如：查找所有使用某提供商的项目）
- 并发写入风险
- 无事务支持

**方案**:

**Phase 3.1: SQLite（过渡方案，快速实现）**
```python
# backend/database.py
from sqlalchemy import create_engine, Column, String, Integer, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./comic_drama.db')

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Project(Base):
    __tablename__ = "projects"
    
    id = Column(String, primary_key=True)
    title = Column(String)
    status = Column(String)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    metadata = Column(JSON)

class Scene(Base):
    __tablename__ = "scenes"
    
    id = Column(Integer, primary_key=True)
    project_id = Column(String, index=True)
    scene_index = Column(Integer)
    duration = Column(Integer)
    governance_status = Column(String)
    metadata = Column(JSON)

# 创建表
Base.metadata.create_all(bind=engine)
```

**Phase 3.2: PostgreSQL（生产方案）**
```powershell
# 1. 安装 PostgreSQL 客户端
pip install psycopg2-binary

# 2. 更新 DATABASE_URL
DATABASE_URL=postgresql://user:password@localhost/comic_drama
```

**迁移脚本**:
```python
# scripts/migrate_to_db.py
from backend.database import SessionLocal, Project
from backend.project_runtime import load_project
import os

def migrate_projects():
    """迁移现有项目到数据库"""
    db = SessionLocal()
    
    for project_dir in os.listdir("workspace"):
        project_id = project_dir
        project_data = load_project(project_id)
        
        project = Project(
            id=project_id,
            title=project_data.get("title"),
            status=project_data.get("status"),
            metadata=project_data
        )
        
        db.add(project)
    
    db.commit()
```

**验收标准**:
- [ ] 数据库 schema 已定义
- [ ] 项目元数据可从数据库查询
- [ ] 场景数据关联正确
- [ ] 支持事务操作
- [ ] 现有文件系统数据已迁移
- [ ] 向后兼容（可从数据库或文件加载）

**预估时间**: 8-10 小时  
**风险**: 高（需要仔细处理数据迁移）

---

#### Task 3.3: 指标收集（Prometheus）🚀

**描述**: 引入 Prometheus 指标收集，监控系统性能。

**执行步骤**:

```powershell
# 1. 安装
pip install prometheus-client
```

**backend/metrics.py**:
```python
from prometheus_client import Counter, Histogram, Gauge
import time

# 定义指标
video_generation_duration = Histogram(
    'video_generation_seconds',
    'Time spent generating video',
    ['provider', 'status']
)

scene_render_total = Counter(
    'scene_render_total',
    'Total scene renders',
    ['provider', 'status']
)

active_tasks = Gauge(
    'active_tasks',
    'Number of active rendering tasks'
)

# 使用示例
def track_video_generation(provider: str):
    """装饰器：跟踪视频生成"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                video_generation_duration.labels(
                    provider=provider, 
                    status='success'
                ).observe(time.time() - start)
                scene_render_total.labels(
                    provider=provider,
                    status='success'
                ).inc()
                return result
            except Exception as e:
                video_generation_duration.labels(
                    provider=provider,
                    status='failure'
                ).observe(time.time() - start)
                scene_render_total.labels(
                    provider=provider,
                    status='failure'
                ).inc()
                raise
        return wrapper
    return decorator
```

**backend/routers/health.py（添加指标端点）**:
```python
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response

@router.get("/metrics")
async def metrics():
    """Prometheus 指标端点"""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )
```

**验收标准**:
- [ ] Prometheus 指标已定义
- [ ] `/metrics` 端点可访问
- [ ] 视频生成耗时被记录
- [ ] 渲染成功率可查询
- [ ] 任务数量实时监控

**预估时间**: 4-5 小时  
**风险**: 低

---

#### Task 3.4: 分布式追踪（OpenTelemetry）🚀

**描述**: 引入 OpenTelemetry 追踪请求生命周期。

**执行步骤**:

```powershell
# 1. 安装
pip install opentelemetry-api opentelemetry-sdk opentelemetry-instrumentation-fastapi
```

**backend/tracing.py**:
```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# 配置 Tracer
trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer(__name__)

# 导出到控制台（开发）
span_processor = BatchSpanProcessor(ConsoleSpanExporter())
trace.get_tracer_provider().add_span_processor(span_processor)

def instrument_app(app):
    """为 FastAPI 应用添加追踪"""
    FastAPIInstrumentor.instrument_app(app)
```

**backend/app.py（集成）**:
```python
from backend.tracing import instrument_app

app = FastAPI(...)
instrument_app(app)
```

**手动添加 span**:
```python
from backend.tracing import tracer

async def render_scene(project_id: str, scene_id: int):
    with tracer.start_as_current_span("render_scene") as span:
        span.set_attribute("project_id", project_id)
        span.set_attribute("scene_id", scene_id)
        
        # 渲染逻辑
        result = await do_render(...)
        
        span.set_attribute("duration", result.duration)
        return result
```

**验收标准**:
- [ ] OpenTelemetry 已配置
- [ ] FastAPI 请求自动追踪
- [ ] 关键操作手动追踪
- [ ] Trace 可导出到控制台或 Jaeger
- [ ] 性能瓶颈可识别

**预估时间**: 4-6 小时  
**风险**: 低

---

#### Task 3.5: 插件系统扩展 🚀

**描述**: 将视频提供商系统扩展为通用插件框架。

**目标**:
- 允许第三方开发者添加新的提供商
- 支持热加载插件
- 插件隔离（错误不影响主系统）

**架构**:

```python
# backend/plugin_system.py
from abc import ABC, abstractmethod
from typing import Dict, Type
import importlib
import os

class ProviderPlugin(ABC):
    """视频提供商插件基类"""
    
    @abstractmethod
    def get_spec(self) -> 'VideoProviderSpec':
        """返回提供商规格"""
        pass
    
    @abstractmethod
    async def render(self, request: 'VideoRenderRequest') -> 'VideoGenerationResult':
        """渲染视频"""
        pass
    
    @abstractmethod
    def validate_config(self) -> bool:
        """验证配置"""
        pass

class PluginRegistry:
    """插件注册中心"""
    
    def __init__(self):
        self._plugins: Dict[str, Type[ProviderPlugin]] = {}
    
    def register(self, name: str, plugin_class: Type[ProviderPlugin]):
        """注册插件"""
        if not issubclass(plugin_class, ProviderPlugin):
            raise TypeError(f"{plugin_class} must inherit from ProviderPlugin")
        self._plugins[name] = plugin_class
    
    def get(self, name: str) -> Type[ProviderPlugin]:
        """获取插件"""
        if name not in self._plugins:
            raise KeyError(f"Plugin {name} not found")
        return self._plugins[name]
    
    def load_from_directory(self, plugin_dir: str):
        """从目录加载插件"""
        for filename in os.listdir(plugin_dir):
            if filename.startswith('_') or not filename.endswith('.py'):
                continue
            
            module_name = filename[:-3]
            module = importlib.import_module(f"plugins.{module_name}")
            
            # 查找插件类
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, ProviderPlugin) and 
                    attr != ProviderPlugin):
                    self.register(module_name, attr)

# 全局注册中心
plugin_registry = PluginRegistry()
```

**示例插件**:
```python
# plugins/my_custom_provider.py
from backend.plugin_system import ProviderPlugin
from video_providers import VideoProviderSpec
from backend.video_generation import VideoGenerationResult

class MyCustomProvider(ProviderPlugin):
    """自定义视频提供商"""
    
    def get_spec(self) -> VideoProviderSpec:
        return VideoProviderSpec(
            id="my_custom",
            label="My Custom Provider",
            backend="remote",
            supports=("text", "image"),
        )
    
    async def render(self, request) -> VideoGenerationResult:
        # 实现渲染逻辑
        pass
    
    def validate_config(self) -> bool:
        # 验证配置
        return True
```

**加载插件**:
```python
# backend/app.py
from backend.plugin_system import plugin_registry

# 加载插件目录
plugin_registry.load_from_directory("plugins")

# 注册到视频提供商系统
for name, plugin_class in plugin_registry._plugins.items():
    plugin = plugin_class()
    spec = plugin.get_spec()
    register_video_provider(spec)
```

**验收标准**:
- [ ] 插件基类已定义
- [ ] 插件注册中心已实现
- [ ] 支持从目录热加载插件
- [ ] 插件错误不影响主系统
- [ ] 文档说明如何创建自定义插件

**预估时间**: 6-8 小时  
**风险**: 中

---

### Phase 3 总体验收

**必须满足**:
- [ ] 任务队列可用，视频渲染异步执行
- [ ] 数据库持久化完成
- [ ] Prometheus 指标可查看
- [ ] 分布式追踪可用
- [ ] 插件系统可扩展
- [ ] 所有现有功能保持兼容

**可选**:
- [ ] 性能提升 >50%
- [ ] 系统可用性 >99%
- [ ] 提交到独立分支 `optimization/phase-3`

---

## 附录

### A. 验收检查清单

在每个 Phase 完成后，运行以下检查：

```powershell
# 1. 代码质量
black --check backend/ scripts/
isort --check backend/ scripts/
mypy backend/ scripts/

# 2. 测试
pytest --cov --cov-fail-under=60

# 3. 安全
bandit -r backend/ scripts/
safety check

# 4. 构建
python -m py_compile backend/app.py
node --check frontend/app.js

# 5. 功能
python -m scripts.run_workflow --input inputs\sample_story.txt --keyframe-provider local
```

### B. 回滚计划

每个 Phase 完成后：
1. 创建 Git 标签：`git tag phase-N-complete`
2. 如果出现问题，回滚：`git reset --hard phase-(N-1)-complete`

### C. 风险缓解

| 风险 | 缓解措施 |
|------|----------|
| 依赖冲突 | 使用虚拟环境，锁定版本 |
| 测试失败 | 每个任务后运行测试 |
| 性能退化 | 运行基准测试 |
| 安全问题 | 定期扫描，及时修复 |
| 协作冲突 | pre-commit hook 检查 |

---

## 总结

本执行计划共 **26 个任务**，分 **4 个阶段**，预计 **3 个月** 完成。

**关键里程碑**:
- Phase 0（3天）：清理技术债务
- Phase 1（2周）：现代化基础设施
- Phase 2（4周）：环境和工具完善
- Phase 3（8周）：长期优化

**成功指标**:
- 测试覆盖率 >80%
- CI 通过率 >95%
- 代码复杂度降低 50%
- 新贡献者上手时间 <1天

---

**文档版本**: 1.0  
**最后更新**: 2026-08-24
