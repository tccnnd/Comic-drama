# Comic Drama Workflow — 审查修复包操作手册

> 生成日期: 2026-06-25  
> 适用版本: v0.5.0 (director-interpretation-mainline)  
> 本包覆盖: 立即修复（P0/P1）全部 8 项

---

## 📦 文件清单

```
comic_drama_fixes/
├── AGENTS.md                              # Fix 1 — 直接替换项目根目录同名文件
├── .gitignore                             # Fix 2 + Fix 7 — 直接替换项目根目录同名文件
├── docs/
│   └── roadmap.md                         # Fix 4 — 直接替换 docs/roadmap.md
├── .github/
│   └── workflows/
│       └── ci.yml                         # Fix 3 — 直接替换 .github/workflows/ci.yml
└── patches/
    ├── project_models_full_snippet.py     # Fix 5 — 手动应用（见下方说明）
    ├── project_models_path_traversal.patch# Fix 5 — unified diff（可选）
    ├── dockerfile_full.txt                # Fix 6 — 内容覆盖 Dockerfile（见下方说明）
    ├── dockerfile_non_root.patch          # Fix 6 — unified diff（可选）
    ├── ci_coverage_note.md                # 覆盖率门槛升级说明
    └── ssh_autoadd_note.md                # SSH AutoAddPolicy 修复指南（手动）
```

---

## 🚀 快速应用（直接覆盖）

以下文件可以**直接覆盖**到项目对应位置，无需手工编辑：

```powershell
# 在项目根目录 E:\APP\Comic drama\ 执行

# Fix 1: AGENTS.md 版本方向更新
Copy-Item comic_drama_fixes\AGENTS.md AGENTS.md -Force

# Fix 2 + 7: .gitignore 补全
Copy-Item comic_drama_fixes\.gitignore .gitignore -Force

# Fix 3: CI 补充 py_compile + 覆盖率门槛 30%
Copy-Item comic_drama_fixes\.github\workflows\ci.yml .github\workflows\ci.yml -Force

# Fix 4: roadmap.md Phase 2-5 状态更新
Copy-Item comic_drama_fixes\docs\roadmap.md docs\roadmap.md -Force
```

---

## 🔧 需手动应用的修复

### Fix 5: `backend/project_models.py` 路径遍历防护

**方式 A — 复制粘贴（推荐）**

1. 打开 `backend/project_models.py`
2. 在文件最顶部 import 区域加入 `import re`（如果已有则跳过）
3. 在所有 import 之后、第一个函数定义之前，插入以下代码块：

```python
# ---------------------------------------------------------------------------
# Project-ID validation – defence against path-traversal via crafted IDs
# ---------------------------------------------------------------------------
_PROJECT_ID_PATTERN = re.compile(r"^proj_[0-9]{8}_[0-9]{6}_[a-f0-9]{6}$")


def _validate_project_id(project_id: str) -> None:
    """Raise ValueError if project_id does not match the expected format."""
    if not _PROJECT_ID_PATTERN.match(project_id):
        raise ValueError(
            f"Invalid project_id format {project_id!r}. "
            "Expected: proj_YYYYMMDD_HHMMSS_xxxxxx"
        )
```

4. 找到 `project_dir()` 函数（约第 78-79 行），修改为：

```python
def project_dir(project_id: str) -> Path:
    _validate_project_id(project_id)          # ← 新增这一行
    return WORKSPACE / project_id
```

5. （可选）在 `backend/app.py` 路由层捕获 ValueError，返回 400：

```python
# 在每个使用 project_id 的路由函数入口处添加
try:
    _validate_project_id(project_id)
except ValueError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
```

**方式 B — 应用 unified diff**

```bash
cd "E:\APP\Comic drama"
git apply patches/project_models_path_traversal.patch
```

---

### Fix 6: `Dockerfile` 添加非 root 用户

将 `patches/dockerfile_full.txt` 的内容完整替换 `Dockerfile`：

```powershell
Copy-Item comic_drama_fixes\patches\dockerfile_full.txt Dockerfile -Force
```

或手动在 `Dockerfile` 中添加（原文件只有约 5 行）：

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 新增：创建非 root 用户
RUN groupadd -r appuser \
 && useradd -r -g appuser -u 1000 -m appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 新增：转让所有权并切换用户
RUN chown -R appuser:appuser /app
USER appuser

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

### Fix 8: 删除 527KB 冗余文件

```powershell
# 从 git 追踪中移除并删除文件
cd "E:\APP\Comic drama"
git rm docs\project_review_report.md
git commit -m "chore: remove 527KB redundant LLM output from docs"
```

---

### Fix 9: SSH AutoAddPolicy（见 `patches/ssh_autoadd_note.md`）

由于涉及 SSH 连接逻辑变动，该修复需人工审查后应用。
详见 `patches/ssh_autoadd_note.md`，内含完整的替换代码块。

---

## ✅ 验证清单

应用所有修复后，运行以下验证：

```powershell
cd "E:\APP\Comic drama"

# 1. Python 编译检查（包含新增的两个高风险文件）
.venv\Scripts\python.exe -m py_compile `
    scripts\run_workflow.py `
    backend\project_runtime.py `
    backend\app.py `
    video_providers.py `
    scripts\video_provider_adapters.py `
    backend\video_generation.py `
    backend\scene_renderer.py

# 2. 前端语法检查（新增 api.js / events.js 等）
node --check frontend\app.js
node --check frontend\render.js
node --check frontend\api.js
node --check frontend\events.js
node --check frontend\utils.js
node --check frontend\state.js
node --check frontend\timeline.js

# 3. 运行测试
.venv\Scripts\python.exe -m pytest tests -v

# 4. 确认 .gitignore 覆盖了 .uploads/ 和大文件
git check-ignore -v .uploads docs/project_review_report.md
```

---

## 📊 修复前后对比

| # | 问题 | 修复前 | 修复后 |
|---|------|--------|--------|
| 1 | AGENTS.md 版本方向 | v0.2.0（落后3个版本） | v0.5.0 + 完整路线图 |
| 2 | .gitignore 缺失 | 缺 `.uploads/`, `.idea/`, `.coverage*`, `.ruff_cache/`, `*.egg-info/` | 全部补全 |
| 3 | CI py_compile | 遗漏 `video_generation.py` + `scene_renderer.py` | 全部高风险文件覆盖 |
| 3 | CI 覆盖率门槛 | 0%（无约束） | 30%（含升级路线图） |
| 3 | CI 前端检查 | 仅 app.js + render.js | 全部7个JS模块 |
| 4 | roadmap.md 状态 | Phase 2/3 标注为 planned/in progress | 准确反映已完成版本 |
| 5 | 路径遍历防护 | `project_dir()` 直接拼接 | 正则验证 + ValueError |
| 6 | Docker root 运行 | 无 USER 指令 | `USER appuser` (uid=1000) |
| 7 | 冗余文件 527KB | 被 git 追踪 | gitignore 排除 + git rm |

---

## ⏳ 后续优先级（本包未覆盖）

以下问题超出"立即修复"范围，建议按序处理：

1. **引入 ruff + pyproject.toml**（质量基础，1天）
2. **添加 .pre-commit-config.yaml**（提交门控，0.5天）
3. **BGM 上传路径遍历防护 + 文件类型验证**（安全，0.5天）
4. **SSH AutoAddPolicy → RejectPolicy + 密钥认证**（安全，1天）
5. **拆分 render.js（1741行）为按视图多模块**（前端，3天）
6. **拆分 run_workflow.py（6410行）**（架构，3周）

详见 `docs/project_review_20260625.md` 第七章改进路线图。
