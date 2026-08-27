# 执行计划审核报告（EXECUTION_PLAN_AUDIT）

**审核日期**: 2026-08-24  
**审核对象**: `EXECUTION_PLAN.md` v1.0  
**审核方法**: 对照项目实际状态逐项核实

---

## 一、总体结论

计划整体框架合理，优先级排序正确，验收标准大体可执行。但对照项目实际代码库核实后，发现 **3 处事实性错误、5 处重要遗漏、若干验收标准不合理之处**。修订后计划可用。

---

## 二、事实性错误（必须修正）🔴

### 错误 1: backend/app.py 的"60KB 单文件"描述已部分过时

**实际情况**: app.py 有 49 个端点 + WebSocket 流式任务接口（`/api/tasks/{task_id}/stream`），且已有 `backend/task_store.py`、`backend/event_bus.py` 等配套模块。Task 1.3 计划中的 `routers/websocket.py` 拆分是合理的，但计划低估了现有拆分程度——project_runtime 已拆为 project_models / character_manager / scene_graph / scene_renderer / project_export 五个子模块并 re-export。

**修正**: Task 1.3 验收标准从"app.py 从 60KB 降至 <5KB"改为"app.py 仅保留应用初始化与路由注册，端点逻辑迁入 routers/，行数减少 ≥70%"。同时补充：**拆分必须保持 import 路径向后兼容**（现有测试直接 import backend.app）。

### 错误 2: run_workflow.py 重构状态描述错误

**实际情况**: Git 历史显示 commit `48d1f64` 已将 run_workflow.py 拆分为 13 个 rw_* 模块（509 tests pass），但**当前工作区磁盘上不存在 rw_*.py 文件，run_workflow.py 仍是 6204 行**——即 P2 重构提交存在于某个分支但未合入 main 工作区，或被回退。这是计划完全遗漏的关键状态。

**修正**: 在 Phase 1 新增前置任务 **Task 1.0**: 澄清 P2 重构分支（rw_* 模块）的去向——确认在哪个分支、是否合入 main、工作区为何缺失。在澄清前，任何对 run_workflow.py 的新重构都不得启动，避免与已有重构冲突。

### 错误 3: "无 CI"假设不成立，CI 增强方案需重写

**实际情况**: `.github/workflows/ci.yml` 已存在且相当完善：
- backend job: py_compile 高风险文件 + pytest 全量 + coverage 上传 artifact
- frontend job: node --check + mjs helper 测试
- docker job: workflow_dispatch 可选构建
- concurrency 取消旧运行、权限收敛 contents:read
- CI 已使用 `--basetemp data/tmp_pytest_ci`（这正是 data/ 下 tmp_pytest 目录泛滥的来源之一）

计划 Task 1.7 给出的 ci.yml 示例与现状大量重复甚至倒退（如 windows-latest 更慢更贵、丢失 concurrency 配置）。

**修正**: Task 1.7 改为**增量增强**而非重写：在现有 ci.yml 基础上增加 lint（black/isort/mypy）、bandit/safety 安全扫描作业；保留 ubuntu-latest、concurrency、coverage artifact 等既有设计。覆盖率阈值从环境变量 `COVERAGE_THRESHOLD=0` 逐步调高（先设 40%，稳定后 60%）。

---

## 三、重要遗漏（应补充）🟡

### 遗漏 1: data/tmp_pytest* 目录的根因未治理

data/ 下有约 20 个 tmp_pytest* 目录（118MB）。根因：pytest basetemp 配置指向 data/ 且历史运行未清理。仅靠 Phase 0 手动清理会复发。

**补充**: Phase 0 增加 Task 0.7 —— 将 pytest basetemp 统一配置到系统临时目录或 .gitignore 已覆盖的单一目录，并在 conftest.py 或 pytest.ini 中固化；CI 中已有 `--basetemp data/tmp_pytest_ci`，本地运行也应统一。验收：连续两次本地全量测试后，data/ 无新增残留目录。

### 遗漏 2: outputs/ 目录治理（1.8GB、81 个运行产物）

计划只提了 workspace/ 和 data/，漏掉了最大的 outputs/（1.8GB、81 个历史运行输出）。虽已在 .gitignore，但磁盘占用和检索混乱问题仍在。

**补充**: Phase 2 数据目录治理（Task 2.2）范围扩大到 outputs/：增加保留策略（如保留最近 N 次运行）、提供 `scripts/cleanup_outputs.py` 清理脚本（dry-run 默认）。验收：outputs/ 占用降至可配置阈值内。

### 遗漏 3: WebSocket 任务流接口的兼容性约束未声明

app.py 存在 `/api/tasks/{task_id}/stream` WebSocket 端点和前端 api.js（1259 行）对接。Phase 1.3 拆分路由时若破坏该契约，前端实时日志功能会静默失效，而现有测试可能覆盖不到。

**补充**: Task 1.3 验收标准追加：WebSocket 端点路径与消息格式不变；手动验证任务流推送正常；node --check 通过之外增加一次真实浏览器冒烟（或至少 curl/ws 客户端连通性脚本）。

### 遗漏 4: Python 版本基线不一致

本机存在 Python 3.13.14（venv）与系统 3.14.2；ci.yml 用 3.11；requirements 未声明最低版本。mypy/black target-version 若照抄计划的 py39-py311 会与本机 3.13 冲突。

**补充**: Phase 1 依赖管理任务中明确：**Python 支持 matrix = ["3.11", "3.12"]**（CI 与文档一致），pyproject.toml 声明 `requires-python = ">=3.11"`；工具链 target 对齐 py311。验收：CI 双版本矩阵通过。

### 遗漏 5: comic_drama_fixes/、docs/project_review_report.md 等游离文件归属

git status 显示 `comic_drama_fixes/`（含 patch/md/py）、`PROJECT_ANALYSIS.md`、`EXECUTION_PLAN.md`、`docs/project_review_report.md`、`data/run_workflow.py.bak_rw4` 均未被跟踪。这些是历史修复记录与分析产物，长期留在工作区会持续污染 git status。

**补充**: Phase 0 增加 Task 0.8 —— 归档决策：有价值的并入 docs/ 并提交；过期的移出仓库或加入 .gitignore（如 *.bak_rw4、*.bak）。验收：git status 中不再出现来历不明文件。

---

## 四、验收标准不合理之处 ⚠️

| 位置 | 问题 | 修正建议 |
|------|------|----------|
| Task 0.4 "_external/ 处理" | 验收只有"决定方案"，不可度量 | 明确二选一硬标准：(a) 转 submodule 且 LICENSE_NOTICE.md 列全每个子项目许可证；(b) 移出仓库并在 README 记录获取方式。`du -sh _external` 结果必须反映所选方案 |
| Task 1.2 "覆盖率 >60% 即 fail-under" | 当前阈值 COVERAGE_THRESHOLD=0，直接跳 60% 大概率立即红 | 分级：P1 先 40%，P2 提至 60%，P3 视情况 80%。每级稳定两周再上调 |
| Task 1.3 "<5KB" | 字节数目标不如行为目标可靠 | 改为：所有端点迁入 routers/、import 兼容、全部现有测试通过、新增 routers 冒烟测试 |
| Task 1.4 "npm run dev 可启动" | 前端是原生 ES module 直连 FastAPI 静态托管，引 Vite dev server 会改变加载方式 | 验收改为：Vite 仅作为可选开发辅助，默认路径仍走 uvicorn 静态服务；`npm run lint/build` 通过即可，dev 不作为硬验收 |
| Task 1.6 mypy "关键模块类型覆盖 >80%" | 首次引入 mypy 对 12 万行代码库不现实 | 改为：mypy 对 backend/project_models.py 等 3 个核心模块零错误即可，其余模块 ignore_errors 渐进收紧 |
| Task 3.1 Celery | 项目已有自研 TaskStore + event_bus + WebSocket 推送，直接上 Celery 是架构推翻而非演进 | 改为两步：先评估现有 task_store 是否满足需求；确需分布式再引入 Celery，且保留 REST API 兼容层。降级为"可选评估任务" |
| Task 3.2 数据库迁移 | workspace JSON 是项目数据的事实源且有版本化快照机制（asset_retention），强行迁移风险极高 | 重新定位：DB 仅做**索引/查询层**（元数据镜像），JSON 仍为主存储；或整项推迟并明确 non-goal |
| 成功指标 "代码复杂度降低 50%（<8万行）" | 12万行统计含 .venv/_external 等非项目代码，基线本身错误 | 重测基线（仅 backend/scripts/tests/frontend），以重测值为基准谈降幅 |

---

## 五、计划中正确且无需修改的部分 ✅

- Phase 0 清理方向正确：tmp_pytest、*.log/*.pid/*.job 确实存在且应清理（注意：其中多数已被 .gitignore 覆盖，属磁盘清理而非 git 清理）
- .gitignore 补充清单基本正确（现有 .gitignore 已覆盖大半，增量补充即可）
- 依赖锁定、生产/开发依赖分离的方向正确
- pre-commit hook 强化 AI 协作规则与 AGENTS.md 高风险文件制度衔接良好
- Bandit/Safety 引入、健康检查完善、日志规范化的必要性成立
- Docker Compose 方向正确（Dockerfile 已存在，补 compose 即可）

---

## 六、修订后的阶段任务总表

| Phase | 原任务数 | 修订后 | 关键变化 |
|-------|---------|--------|----------|
| Phase 0 | 6 | **8** | +basetemp 根因治理(0.7)、+游离文件归档(0.8)；0.4/0.5 验收硬化 |
| Phase 1 | 8 | **9** | +Task 1.0 澄清 rw_* 重构去向（最高优先）；1.3/1.6 验收改写；1.7 改增量增强 |
| Phase 2 | 7 | 7 | 2.2 范围扩至 outputs/；2.1 基于现有 Dockerfile 增量化 |
| Phase 3 | 5 | **3+2可选** | 3.1 Celery、3.2 DB 迁移降级为评估项；Prometheus/OTel/插件保留 |

总计：26 → **27 个必做 + 2 个评估项**

---

## 七、给大王的三条最优先行动建议

1. **先跑 Task 1.0**：搞清 rw_* 重构提交（48d1f64，509 tests pass）为什么不在工作区——这直接决定后续所有重构路线，半天内可完成。
2. **Phase 0 收紧为纯磁盘/git 卫生**：不动代码逻辑，一天完成，立刻改善日常开发体验。
3. **覆盖率阈值阶梯化**（40→60→80），避免一次性拉高导致 CI 长期红灯、团队失去信心。

---

**审核结论**: 计划骨架保留，按本报告第二~四节修订后可执行。
