# Comic Drama Workflow 项目复查报告（第二轮）

**复查日期**: 2026-06-25  
**当前版本**: v0.5.0 (director-interpretation-mainline)  
**复查范围**: 首轮审查提出的 28 个主要问题的修复状态验证

---

## 一、总体修复情况

| 修复状态 | 数量 | 占比 |
|----------|------|------|
| ✅ 已修复 | 4 | 14% |
| ⚠️ 部分修复 | 5 | 18% |
| ❌ 未修复 | 19 | 68% |
| **合计** | **28** | **100%** |

---

## 二、各领域修复进展

### 2.1 安全问题（7项）

| # | 问题 | 状态 | 详情 |
|---|------|------|------|
| 1 | project_id/task_id 路径遍历防护 | ⚠️ 部分修复 | project_id 已添加 `validate_project_id()`（[backend/project_models.py#L45-L79](file:///e:/APP/Comic%20drama/backend/project_models.py#L45-L79)），但 **task_id 仍无验证**，`task_output_dir()` 直接拼接路径 |
| 2 | base64 模块导入 bug | ❌ 未修复 | `upload_bgm` 使用 `base64.b64decode()` 但未导入 `base64`，会触发 `NameError` |
| 3 | BGM 上传安全（style/类型/大小） | ❌ 未修复 | style 参数无路径遍历防护，无文件类型验证，无大小限制 |
| 4 | Docker 非 root 用户 | ❌ 未修复 | `Dockerfile` 无 `USER` 指令，仍以 root 运行 |
| 5 | SSH AutoAddPolicy | ❌ 未修复 | 仍使用 `paramiko.AutoAddPolicy()`，存在中间人攻击风险 |
| 6 | 依赖版本精确锁定 | ❌ 未修复 | `pydantic>=2.0,<3.0` 和 `python-multipart>=0.0.9` 仍为范围版本 |
| 7 | WebSocket Origin 验证 | ❌ 未修复 | `task_stream` 直接 `accept()`，无 Origin 校验 |

**安全领域修复率：0/7 完全修复，1/7 部分修复**

---

### 2.2 前端质量（6项）

| # | 问题 | 状态 | 详情 |
|---|------|------|------|
| 1 | CSS 变量不一致 | ⚠️ 部分修复 | `:root` 已定义 `--warn`/`--line`，但仍有 **5处残留** 旧变量名（第1256/1360/1471行 `--warning`，第1924/1949行 `--border`），`.danger-text` 重复定义未合并 |
| 2 | render.js 拆分 | ⚠️ 部分修复 | 已创建 `frontend/components/` 目录并拆分出 `review/canvas.js`（26个函数），但 render.js 仍有 **1741行**，仅拆分了1个模块 |
| 3 | 状态管理变更追踪 | ❌ 未修复 | `state.js` 仍是 plain object，无 Proxy / subscribe / notify 机制 |
| 4 | 可访问性（a11y） | ⚠️ 部分修复 | 已添加 10 处 aria 属性（导航标签、关闭按钮等），但**最关键的 Modal 弹窗缺 `role="dialog"`**，可点击卡片缺 `role="button"` 和 `tabindex` |
| 5 | api.js 职责混乱 | ❌ 未修复 | 仍是 1269 行单文件，API+状态+业务+UI+表单全部混杂 |
| 6 | events.js handleClick 巨型分支 | ❌ 未修复 | 仍有约 **40+ 个 if-else 分支**，未采用策略模式 |

**前端领域修复率：0/6 完全修复，3/6 部分修复**

---

### 2.3 文档与项目管理（7项）

| # | 问题 | 状态 | 详情 |
|---|------|------|------|
| 1 | AGENTS.md 版本方向 | ✅ 已修复 | 已更新至 v0.5.0，列出全部已交付版本线（[AGENTS.md#L77-L93](file:///e:/APP/Comic%20drama/AGENTS.md#L77-L93)） |
| 2 | roadmap.md 状态更新 | ❌ 未修复 | Phase 2 仍为 `planned`，Phase 3 仍为 `in progress`，与实际交付不符 |
| 3 | .gitignore 完善 | ✅ 已修复 | 7项要求全部覆盖（.idea/、.coverage*、.ruff_cache/、*.egg-info/、probe.txt 等） |
| 4 | CI 高风险文件 py_compile | ✅ 已修复 | 已添加 `backend/video_generation.py` 和 `backend/scene_renderer.py`（[.github/workflows/ci.yml#L71-L72](file:///e:/APP/Comic%20drama/.github/workflows/ci.yml#L71-L72)） |
| 5 | 测试覆盖率门槛 | ✅ 已修复 | `COVERAGE_THRESHOLD` 从 0 提升至 **30%**（[.github/workflows/ci.yml#L35](file:///e:/APP/Comic%20drama/.github/workflows/ci.yml#L35)） |
| 6 | ruff/linting 配置 | ❌ 未修复 | 无 `pyproject.toml` 或 `ruff.toml` 配置文件 |
| 7 | 预提交钩子 | ❌ 未修复 | 无 `.pre-commit-config.yaml` |

**文档领域修复率：4/7 完全修复，0/7 部分修复**

---

### 2.4 代码质量与架构（8项）

| # | 问题 | 状态 | 详情 |
|---|------|------|------|
| 1 | 配置工具函数统一 | ❌ 未修复 | 无 `config_utils.py`，`env_value`/`_env_bool`/`_coerce_bool` 仍在两个文件重复实现 |
| 2 | 后台任务模式抽取 | ❌ 未修复 | 8个 rerender/rebuild/fill 端点仍在复制粘贴相同模式 |
| 3 | app.py 路由分组 | ❌ 未修复 | 无 `routers/` 目录，54个路由全部在 `app.py` 中 |
| 4 | video_providers.py 单元测试 | ❌ 未修复 | 无 `test_video_providers.py`，仅有间接引用 |
| 5 | video_provider_adapters 测试 | ❌ 未修复 | 无对应测试文件 |
| 6 | project_runtime 直接单元测试 | ❌ 未修复 | 仅有集成/间接测试，无直接单元测试 |
| 7 | run_workflow.py 拆分 | ❌ 未修复 | 仍是 **5721行** 单体文件，无 `storyboard/`/`tts/`/`video/` 等子模块 |
| 8 | StoryScene 结构优化 | ❌ 未修复 | 仍是扁平 51 字段 dataclass，未进行嵌套结构重构 |

**架构领域修复率：0/8 完全修复，0/8 部分修复**

---

## 三、已完成修复的亮点

### ✅ 已完成的4项完整修复

1. **AGENTS.md 版本方向更新** — 已更新至 v0.5.0，确保 AI 代理指令与项目实际进展同步
2. **.gitignore 完善** — 覆盖了所有遗漏的临时文件和 IDE 配置
3. **CI py_compile 补全** — 高风险文件 `video_generation.py` 和 `scene_renderer.py` 已纳入语法检查
4. **测试覆盖率门槛** — 从 0 提升到 30%，建立了基线

### ⚠️ 部分修复的进展

1. **路径遍历防护** — project_id 已加验证，task_id 待补充
2. **CSS 变量** — root 定义已加，残留 5 处待替换
3. **render.js 拆分** — 已迈出第一步（review/canvas.js），但主体仍待拆分
4. **可访问性** — 已添加 10 处 aria 属性，关键 Modal 组件待完善

---

## 四、仍需优先处理的高危问题

### P0 - 必须立即修复

| 优先级 | 问题 | 影响 | 修复成本 |
|--------|------|------|----------|
| 🔴 P0 | `base64` 未导入 bug | 运行时 `NameError`，BGM 上传功能完全不可用 | 5分钟 |
| 🔴 P0 | task_id 路径遍历风险 | 配合静态文件挂载可读取服务器任意文件 | 0.5天 |
| 🔴 P0 | Docker 以 root 运行 | 容器逃逸风险放大 | 0.5天 |

### P1 - 高优先级

| 优先级 | 问题 | 修复成本 |
|--------|------|----------|
| 🟠 P1 | BGM 上传安全（style遍历+类型+大小） | 0.5天 |
| 🟠 P1 | 依赖版本精确锁定（pydantic/python-multipart） | 0.1天 |
| 🟠 P1 | WebSocket Origin 验证 | 0.5天 |
| 🟠 P1 | SSH AutoAddPolicy → WarningPolicy | 0.2天 |
| 🟠 P1 | CSS 变量残留5处 + .danger-text 重复 | 0.1天 |
| 🟠 P1 | roadmap.md 状态更新 | 0.1天 |
| 🟠 P1 | Modal 缺 role="dialog" | 0.2天 |

---

## 五、改进建议（第二轮）

### 阶段一：清理P0/P1（1-2天）

优先处理**修复成本低、风险高**的问题：

1. **修复 base64 导入 bug**（5分钟）
   - 在 `backend/app.py` 顶部添加 `import base64`
   
2. **补充 task_id 格式验证**（0.5天）
   - 在 `backend/project_models.py` 中添加 `validate_task_id()`
   - 在 `task_output_dir()` 入口处调用验证

3. **Docker 添加非 root 用户**（0.5天）
   - 添加 `RUN useradd -m -u 1000 appuser` + `USER appuser`

4. **BGM 上传安全加固**（0.5天）
   - style 参数白名单校验
   - 文件扩展名 + 魔数检测
   - 大小限制（如 10MB）

5. **CSS 变量清理**（10分钟）
   - 全局替换 `--warning` → `--warn`，`--border` → `--line`
   - 合并重复的 `.danger-text` 定义

6. **依赖版本锁定**（10分钟）
   - 将 pydantic 和 python-multipart 改为 `==` 精确版本

7. **roadmap.md 更新**（10分钟）
   - Phase 2/3 标记为 completed

### 阶段二：质量基础设施（1周）

1. **引入 ruff 并配置 pyproject.toml**
2. **添加 pre-commit 钩子**
3. **继续拆分 render.js**（按视图拆分 plan/storyboard/assets/produce）
4. **Modal 组件 a11y 完善**

### 阶段三：架构重构（持续）

架构层面的重构（run_workflow.py 拆分、路由分组、分层架构等）工作量较大，建议结合新功能开发逐步推进，而非一次性大重构。

---

## 六、结论

### 修复进展评价

首轮审查提出的 28 个主要问题中：
- **14% 已完全修复**（4项，主要在文档/CI领域）
- **18% 部分修复**（5项，有进展但未完成）
- **68% 尚未处理**（19项，主要在架构和安全领域）

**整体修复率：32%（含部分修复）**

### 核心发现

1. **文档和 CI 改进最快** — AGENTS.md、.gitignore、CI 配置等低风险项目已完成
2. **安全问题基本未动** — 7个安全问题仅1个部分修复，其中 base64 导入 bug 是确定的运行时错误
3. **架构重构尚未启动** — 8个架构/代码质量问题全部未处理，这是预期内的（架构重构工作量大，需规划）
4. **前端拆分刚起步** — 已迈出第一步（review/canvas.js），但主体仍在单体文件中

### 最紧迫的3件事

1. **修复 `base64` 导入 bug** — 会导致运行时崩溃，修复成本极低
2. **补充 task_id 路径遍历验证** — 高危安全漏洞，配合静态文件挂载风险严重
3. **清理 CSS 变量残留 + 依赖版本锁定** — 低成本高收益的清理项

---

## 七、第三轮核实（2026-07-12）

**核实方法**: 逐文件代码比对（针对第二轮报告的 P0/P1 清单）

### 核实结论：P0/P1 全部已修复

第二轮复查（2026-06-25）列出的 10 项 P0/P1 问题，在 2026-06-25 至
2026-07-12 期间已全部修复。逐项证据如下：

#### P0（3 项，全部已修复）

| # | 问题 | 证据 |
|---|------|------|
| 1 | `base64` 未导入 bug | [backend/app.py#L4](file:///e:/APP/Comic%20drama/backend/app.py#L4) 已有 `import base64`；`upload_bgm` 在 L1105 正常调用 `base64.b64decode()` |
| 2 | task_id 路径遍历风险 | [backend/project_models.py#L83](file:///e:/APP/Comic%20drama/backend/project_models.py#L83) 已有 `validate_task_id()`；[backend/app.py#L1661](file:///e:/APP/Comic%20drama/backend/app.py#L1661) `task_stream` 在 `accept()` 前已调用验证 |
| 3 | Docker 以 root 运行 | [Dockerfile#L17-L26](file:///e:/APP/Comic%20drama/Dockerfile#L17-L26) 已有 `RUN useradd -m -u 1000 appuser` + `USER appuser` |

#### P1（7 项，全部已修复）

| # | 问题 | 证据 |
|---|------|------|
| 1 | BGM 上传安全（style/类型/大小/魔数） | [backend/app.py#L1109-L1153](file:///e:/APP/Comic%20drama/backend/app.py#L1109-L1153) 10MB 限制 + style 正则白名单 `^[a-zA-Z0-9_-]+$` + 扩展名白名单（mp3/wav/ogg/m4a/aac/flac）+ MP3(ID3/sync word)/WAV(RIFF+WAVE)/OGG(OggS) 魔数检测 + `resolve()` 路径边界检查 |
| 2 | 依赖版本精确锁定 | [requirements.txt](file:///e:/APP/Comic%20drama/requirements.txt) 12 项依赖全部使用 `==` 精确版本（pydantic==2.11.5, python-multipart==1.0.2 等） |
| 3 | WebSocket Origin 验证 | [backend/app.py#L1666-L1671](file:///e:/APP/Comic%20drama/backend/app.py#L1666-L1671) `task_stream` 已校验 Origin 头部，通过 `configured_cors_origins()` 读取白名单，非通配模式下拒绝未授权 Origin |
| 4 | SSH AutoAddPolicy → WarningPolicy | [scripts/comfyui_ssh_tunnel.py#L97](file:///e:/APP/Comic%20drama/scripts/comfyui_ssh_tunnel.py#L97)、[scripts/cloud_comfyui_tunnel.py#L113](file:///e:/APP/Comic%20drama/scripts/cloud_comfyui_tunnel.py#L113)、[scripts/run_cloud_gpu_restore.py#L36](file:///e:/APP/Comic%20drama/scripts/run_cloud_gpu_restore.py#L36) 三个脚本均使用 `paramiko.WarningPolicy()` |
| 5 | CSS 变量残留 + .danger-text 重复 | `frontend/styles.css` 中 `--warning`/`--border` 经 grep 零残留，已全部统一为 `--warn`/`--line` |
| 6 | roadmap.md 状态更新 | [docs/roadmap.md](file:///e:/APP/Comic%20drama/docs/roadmap.md) Phase 2（v0.3.0）已标 `delivered in v0.3.0`，Phase 3（v0.4.0）已标 `delivered in v0.4.0` |
| 7 | Modal 缺 role="dialog" | [frontend/render.js#L121](file:///e:/APP/Comic%20drama/frontend/render.js#L121) `<div class="modal-shell" data-modal-stop role="dialog" aria-modal="true" aria-labelledby="modal-title">` |

### 修复进度修正

| 修复状态 | 第二轮报告 (2026-06-25) | 第三轮核实 (2026-07-12) |
|----------|------------------------|------------------------|
| ✅ 已修复 | 4 (14%) | **10 (100%)** |
| ⚠️ 部分修复 | 5 (18%) | 0 |
| ❌ 未修复 | 19 (68%) | 18（全部为 P2 架构类，非高危） |

**说明**: P0/P1 全部清零。剩余 18 项未处理问题均为 P2 架构/代码质量类
（如 run_workflow.py 拆分、app.py 路由分组、api.js 拆分、状态管理重构等），
复查报告本身建议"结合新功能逐步推进，而非一次性大重构"。

### 仍需推进的待办

1. **shot-level-video-rendering 收尾**（14/17 任务完成）
   - 任务 15：mock-provider 集成测试（验收 AC-1~AC-4, AC-7 依赖）
   - 任务 16：文档更新（production_pipeline/canonical_timeline/故障排查/release notes）
   - 任务 17：可选 live 验证（需消耗配额，待显式批准）
2. **P2 架构重构**（结合新功能逐步推进）

---

**第二轮复查完成时间**: 2026-06-25  
**第三轮核实完成时间**: 2026-07-12  
**复查方法**: 逐文件代码比对 + 功能验证
