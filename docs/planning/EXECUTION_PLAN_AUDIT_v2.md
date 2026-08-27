# 执行计划审核报告 v2（第二轮深度审核）

**审核日期**: 2026-08-27  
**审核对象**: `EXECUTION_PLAN.md` + `EXECUTION_PLAN_AUDIT.md` v1  
**审核方法**: 多维度交叉验证（开发活动、安全、运维、文档一致性）

---

## 执行摘要

**第一轮审核发现**: 3 处事实性错误、5 处遗漏、8 处验收标准问题  
**第二轮审核发现**: **4 处新遗漏、3 处风险未评估、2 处基线错误**

总体结论：计划框架合理，但**运维成熟度、安全治理、分支管理**三个维度存在系统性盲区。

---

## 一、第二轮发现的新遗漏 🟠

### 遗漏 6: 分支管理混乱未纳入治理

**实际情况**:
```bash
git branch -vv 显示:
- main: 4caa6c3 (Clean open source assets)
- codex/director-interpretation-mainline-impl: 48d1f64 [ahead 3] (P2 rw_* 重构)
- 7 个其他 codex/* 分支（v0.2/v0.3/v0.4 feature 分支）
- main 最后提交在 7 月 14 日，此后无新提交（说明：主分支已停滞 1.5 月）
```

**问题**:
1. **P2 重构分支（48d1f64）已 ahead 3 commits 但未合入 main**，计划完全未提及合入策略
2. 7 个 feature 分支处于未知状态（已合入？废弃？待合入？）
3. main 停滞 1.5 月，说明开发活动都在分支上，但**计划未包含分支整合任务**

**影响**: 
- Phase 1 的所有重构任务可能与未合入分支冲突
- 无法判断哪些功能已交付、哪些仍在分支上

**补充**: Phase 0 增加 **Task 0.9: 分支清理与整合决策**
- 审查全部 codex/* 分支状态
- 决策：合入/废弃/保持分离
- 特别处理 P2 重构分支（rw_* 模块）的合入路径
- 验收：分支数 ≤3，main 与活跃分支差异明确

---

### 遗漏 7: 安全扫描配置空白，Phase 2 任务实操性差

**实际情况**:
- 代码中存在 29 处 subprocess/eval/exec 相关调用（虽然初步检查未发现 `shell=True` 或明文密码）
- .env.example 示例包含 `replace-with-your-api-key`，但计划未提及 secrets 管理
- 无 .bandit、.safety-policy.yml 配置文件
- 计划 Task 2.7 只说"安装 bandit/safety"，但未指定扫描范围、排除规则、CI 失败阈值

**补充**: Task 2.7 改写为详细可执行方案：
1. 创建 `.bandit`：排除 tests/、_external/，指定检查规则
2. 创建 `.safety-policy.yml`：设定漏洞阈值（HIGH/CRITICAL 阻塞）
3. 补充 pre-commit hook: `bandit -ll -r backend/ scripts/`
4. CI 增加 security 作业，失败时阻塞 PR
5. **Secrets 管理**: 文档说明如何使用环境变量而非硬编码

验收：
- [ ] Bandit 无 HIGH/CRITICAL 问题
- [ ] Safety 无 CRITICAL CVE
- [ ] .env.example 所有密钥都通过环境变量引用

---

### 遗漏 8: 快速启动体验缺失，新人上手目标不可达

**实际情况**:
- 无 Makefile、无 docker-compose.yml
- README Setup 需手动 3 步（venv → pip install → copy .env）
- 启动 backend 需手动 uvicorn 命令（路径长且易错）
- 计划"新人上手 <1 天"的目标缺少配套措施

**问题**: Phase 2 Docker Compose（Task 2.1）放在 3-6 周后，但新人体验应该是**立即改善的高优先级**。

**调整**: 
1. 将 Task 2.1（Docker Compose）提前到 **Phase 1** 作为 Task 1.9
2. 同时增加 **Makefile** 快速命令（即使不用 Docker）：
   ```makefile
   setup:
       python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
   
   dev:
       .venv/Scripts/uvicorn backend.app:app --reload
   
   test:
       .venv/Scripts/pytest --cov
   ```
3. 验收："新人拉取代码后，运行 `make setup && make dev` 或 `docker-compose up` 即可启动"

---

### 遗漏 9: .kiro/specs/ 规范目录存在但计划未利用

**实际情况**:
```
.kiro/specs/
  ├── alibaba-video-provider/
  ├── ci-cd-pipeline/
  ├── director-review-console/
  ├── global-consistency-governance/
  ├── video-provider-mainline/
  └── README.md
```

**价值**: 这些规范是 Kiro 产出的设计文档（requirements.md / design.md / tasks.md），是理解架构和验证实现的**一手资料**。

**问题**: 计划中多次提到"需要 Kiro spec"，但从未建议**先阅读现有 specs/ 避免重复设计**。

**补充**: Phase 1 增加前置步骤：
- Task 1.0 执行时，同步阅读 `.kiro/specs/video-provider-mainline/` 理解已有设计
- 任何涉及视频提供商、CI、review console 的任务前，先检查对应 spec 是否存在

---

## 二、未评估的风险 ⚠️

### 风险 1: 代码复杂度基线完全错误

**第一轮审核结论**: "12 万行含 .venv/_external"  
**实际测量**: 
```
纯项目代码（backend/ + scripts/ + tests/ + frontend/）：
  27,766 行（Python + JS）

最大文件：
  6,204 行  scripts/run_workflow.py
  2,030 行  frontend/render.js
  1,497 行  backend/app.py
  1,259 行  frontend/api.js
```

**影响**: 
- 计划目标"降低 50%（<8 万行）"基于错误基线，实际已是 2.8 万行
- 正确目标应该是"核心文件降至合理行数"：
  - run_workflow.py: 6204 → <1000（已有 rw_* 重构方案）
  - backend/app.py: 1497 → <500（路由拆分）
  - frontend/render.js: 2030 → 保持或拆分为组件

**修正**: 将"代码复杂度降低 50%"改为：
- run_workflow.py ≤ 1000 行（通过 rw_* 重构）
- backend/app.py ≤ 500 行（通过路由拆分）
- 单文件不超过 1500 行（作为长期目标）

---

### 风险 2: 覆盖率基线未知，阈值阶梯无依据

**实际情况**: 
- CI 中 `COVERAGE_THRESHOLD=0`（即不阻塞）
- 计划建议"先 40% → 60% → 80%"，但**不知道当前覆盖率是多少**

**问题**: 如果当前覆盖率已达 70%，设 40% 无意义；如果只有 20%，跳 40% 仍然困难。

**补充**: Phase 1.2（测试覆盖率基线）验收标准改为：
1. 首次运行 pytest --cov，**记录当前覆盖率 X%**
2. 根据 X 设定阶梯：
   - 若 X < 30%: 阶梯 30% → 50% → 70%
   - 若 30% ≤ X < 60%: 阶梯 X+10% → X+20% → 80%
   - 若 X ≥ 60%: 保持 X，逐步提升至 80%
3. 每个阶梯稳定两周再上调

---

### 风险 3: WebSocket 任务流依赖未测试，破坏性风险高

**实际情况**:
- `/api/tasks/{task_id}/stream` WebSocket 端点存在
- frontend/api.js（1259 行）包含大量 API 调用逻辑
- 现有测试只有 `test_review_console_helpers.mjs`（前端 helper 函数）

**问题**: Phase 1.3 拆分 app.py 路由时，若破坏 WebSocket 契约或 API 路径，**前端会静默失效**（因为无端到端测试覆盖）。

**补充**: Task 1.3 验收标准追加：
- [ ] 编写 WebSocket 连通性测试（Python ws client 或 curl ws://）
- [ ] 验证任务流推送格式不变（JSON schema 一致）
- [ ] 手动浏览器冒烟：创建项目 → 触发任务 → 查看实时日志

---

## 三、验收标准补充修正

### Task 0.4 "_external/ 处理"（第一轮已指出，再次强化）

**原标准**: "决定方案"（不可度量）  
**修正标准**（二选一强制执行）:

**选项 A: 转 Git Submodule**
```bash
cd _external/
git submodule add <Toonflow-app-repo-url> Toonflow-app
# 对每个子项目执行
cd ..
echo "# _external/ LICENSE NOTICE" > _external/LICENSE_NOTICE.md
# 列出每个 submodule 的许可证
```
验收：
- [ ] `git submodule status` 显示所有子项目
- [ ] LICENSE_NOTICE.md 列出每个项目的许可证和用途
- [ ] `du -sh _external/` 显著下降（因为 submodule 只存 commit ref）

**选项 B: 移出仓库**
```bash
mkdir ../Comic-drama-references
mv _external/* ../Comic-drama-references/
rm -rf _external/
echo "_external/" >> .gitignore
```
验收：
- [ ] `du -sh _external/` → 0（目录不存在或为空）
- [ ] README.md 记录："参考项目存放在仓库外 ../Comic-drama-references/"
- [ ] CONTRIBUTING.md 说明如何获取参考项目（可选）

**不允许**: "保持现状并添加 README"——4.2GB 的含糊归属风险太高。

---

### Task 1.4 "前端包管理"（第一轮已指出，进一步细化）

**原验收**: "npm run dev 可启动 Vite"  
**问题**: 前端是原生 ES module 直连 FastAPI 静态托管，引入 Vite dev server 会改变加载路径（/frontend/app.js → /@fs/...）

**修正验收**:
- [ ] package.json 已创建，包含基础 scripts
- [ ] `npm install` 成功
- [ ] `npm run lint` 通过（ESLint 检查）
- [ ] `npm run format` 格式化代码（Prettier）
- [ ] **Vite 仅作为可选开发辅助**：
  - `npm run dev` 启动 Vite（代理 /api 到 FastAPI）
  - 默认部署路径仍走 `uvicorn backend.app:app`（静态服务 frontend/）
  - 文档说明两种启动方式的差异
- [ ] 现有浏览器访问方式不受影响

---

### Task 2.7 "安全扫描"（新增详细步骤，已在遗漏 7 中说明）

**补充**: 创建配置文件并集成到 CI/pre-commit。

**.bandit**:
```yaml
exclude_dirs:
  - _external
  - .venv
  - tests
  - data

tests:
  - B201  # flask_debug_true
  - B301  # pickle
  - B401  # import_telnetlib
  - B501  # request_with_no_cert_validation
  - B601  # paramiko_calls
  - B602  # subprocess_popen_with_shell_equals_true
```

**.safety-policy.yml**:
```yaml
security:
  ignore-cvss-severity-below: 7.0  # HIGH/CRITICAL only
  ignore-cvss-unknown-severity: false
  continue-on-vulnerability-error: false
```

---

## 四、Phase 任务调整汇总

### Phase 0（紧急清理）

| 任务 | 状态 | 备注 |
|------|------|------|
| 0.1-0.6 | 保持 | 第一轮审核已修正 |
| 0.7 | 新增 | pytest basetemp 根因治理 |
| 0.8 | 新增 | 游离文件归档 |
| **0.9** | **新增** | **分支清理与整合决策** |

**Phase 0 新总计**: 9 个任务（原 6 → 9）

---

### Phase 1（高优先级）

| 任务 | 状态 | 调整 |
|------|------|------|
| 1.0 | 保持 | 澄清 rw_* 重构（最高优先） |
| 1.1-1.6 | 保持 | 依赖/重构/前端/格式化/类型检查 |
| 1.7 | 修正 | CI 改为增量增强（非重写） |
| 1.8 | 保持 | 文档更新 |
| **1.9** | **新增** | **Makefile + Docker Compose**（从 Phase 2 提前） |

**Phase 1 新总计**: 10 个任务（原 9 → 10）

---

### Phase 2（中优先级）

| 任务 | 状态 | 调整 |
|------|------|------|
| 2.1 | **移至 Phase 1.9** | Docker Compose 提前 |
| 2.2 | 扩展 | 数据治理增加 outputs/ |
| 2.3-2.6 | 保持 | 健康检查/协作 hook/日志/基准 |
| 2.7 | **重写** | 安全扫描增加详细配置 |

**Phase 2 新总计**: 6 个任务（原 7 → 6，但 2.7 工作量增加）

---

### Phase 3（长期优化）

保持 v1 审核结论：
- 3.1 Celery、3.2 DB 迁移降级为**评估项**
- 3.3 Prometheus、3.4 OTel、3.5 插件保留

**Phase 3 总计**: 3 必做 + 2 评估项

---

## 五、新增关键验收指标

| 维度 | 指标 | 当前 | 目标 | 验收方法 |
|------|------|------|------|----------|
| 代码行数 | run_workflow.py | 6204 | ≤1000 | rw_* 重构合入 |
| 代码行数 | backend/app.py | 1497 | ≤500 | 路由拆分 |
| 分支数 | codex/* 活跃分支 | 7 | ≤3 | 分支整合 |
| 覆盖率 | pytest --cov | **待测** | 阶梯提升 | 先测基线再定目标 |
| 安全扫描 | Bandit HIGH+ | **待测** | 0 | CI 阻塞 |
| 安全扫描 | Safety CRITICAL | **待测** | 0 | CI 阻塞 |
| 启动时间 | 新人首次运行 | 3 步手动 | 1 条命令 | Makefile / Compose |
| 磁盘占用 | _external/ | 4.2GB | 0 或转 submodule | du -sh 验证 |
| 磁盘占用 | outputs/ | 1.8GB | <500MB | 清理脚本 |

---

## 六、最终建议执行顺序（修订版）

### 第一周（Phase 0 全部 + Phase 1.0）

```bash
# Phase 0
Task 0.1-0.3: 清理临时文件、完善 .gitignore
Task 0.4-0.5: 处理 _external/（选项 A 或 B 强制二选一）
Task 0.6: Git 清洁验证
Task 0.7: pytest basetemp 根因治理
Task 0.8: 游离文件归档
Task 0.9: 分支清理（重点：搞清 P2 rw_* 分支去向）

# Phase 1.0
Task 1.0: 澄清 rw_* 重构状态并决定合入路径
```

**里程碑**: 工作区干净、分支状态明确、可开始代码重构。

---

### 第二周（Phase 1.1-1.5）

```bash
Task 1.1: 依赖管理现代化
Task 1.2: 测试覆盖率基线（先测量再定阶梯）
Task 1.3: backend/app.py 路由拆分
Task 1.4: 前端包管理（Vite 作为可选）
Task 1.5: 代码格式化工具
```

---

### 第三周（Phase 1.6-1.9）

```bash
Task 1.6: 类型检查（mypy）
Task 1.7: CI 增量增强（lint + security）
Task 1.8: 文档更新
Task 1.9: Makefile + Docker Compose（新人体验改善）
```

**里程碑**: 基础设施现代化完成，CI 稳定，新人可快速启动。

---

### 第四-六周（Phase 2）

按原计划执行，重点关注：
- Task 2.7 安全扫描的详细配置
- Task 2.2 数据治理（含 outputs/）

---

### 第七周后（Phase 3 评估）

先评估是否需要 Celery/DB 迁移，再决定是否执行。

---

## 七、审核结论

**第一轮 + 第二轮合计发现**:
- **事实性错误**: 3 处（rw_* 重构、CI 状态、app.py 复杂度）
- **重要遗漏**: 9 处（basetemp、outputs/、WebSocket、Python 版本、游离文件、**分支管理、安全配置、快速启动、Kiro specs**）
- **风险未评估**: 3 处（代码基线错误、覆盖率基线未知、E2E 测试缺失）
- **验收标准问题**: 8+ 处

**修订结果**:
- Phase 0: 6 → **9 任务**
- Phase 1: 9 → **10 任务**（Docker Compose 提前）
- Phase 2: 7 → **6 任务**（Docker 移走，2.7 增强）
- Phase 3: 保持 3+2

**总计**: 26 → **28 必做任务 + 2 评估项**

**强烈建议**:
1. **先执行 Task 0.9（分支整合）+ Task 1.0（rw_* 去向）**，这是开始任何重构的前提
2. **Task 0.4（_external/）必须二选一强制执行**，不允许"保持现状+README"
3. **Task 1.2（覆盖率基线）先测量再定阶梯**，避免盲目设定目标

修订后的计划可执行。
