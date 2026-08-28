# Phase 3 评估 A/B：任务队列 + 数据库（2026-08-28）

> 评估先行结论记录。结论用于决定 P3.x 立项范围，不引入 Celery/数据库除非触发条件成立。

## 部署模型事实基线

| 维度 | 事实 |
|---|---|
| 部署形态 | uvicorn 起 `backend.app:app`，监听 `127.0.0.1:8000`（本地单机） |
| 用户模型 | 单用户本地应用（前端 Web 访问本地 FastAPI；无多租户/多实例） |
| 项目规模 | workspace 下 **4** 个 `proj_*` 目录 |
| 单项目数据量 | `project.json` 约 1.2MB（含内嵌资产元数据） |
| 前端界面 | frontend/（HTML+JS），无 PySide6 壳（grep 无 QApplication） |

---

## 评估 A：任务队列

### 现状事实

- `backend/task_store.py`：`TaskStore` = 内存 `dict[str, TaskRecord]` + `threading.Lock`；`TaskRecord` 含完整进度字段（status/progress/stage/message/logs 尾 120 行）。
- 任务执行：`backend/routers/tasks.py:193` `threading.Thread(target=run_workflow_task, daemon=True)`，即**单进程 daemon 线程**，非进程池/外部 worker。
- 进度推送：`backend/routers/tasks.py:247` `/api/tasks/{task_id}/stream` WebSocket（带 Origin 校验）+ `backend/event_bus.py` 单例 `ProjectEventBus`（asyncio.Queue，maxsize=100，满则丢弃并 warn）。

### 需求分析

- 任务种类单一（run_workflow 生成视频），无 fan-out、无优先级队列、无跨机调度需求。
- 单用户 → 并发任务数恒为个位数，内存 dict + Lock 完全够用。
- WebSocket 推送已在进程内闭环（同一 event loop）。

### 结论：**无需引入 Celery**

现有 `task_store + event_bus + WebSocket` 满足当前与可预见需求。引入 Celery 会：
1. 增加 broker（Redis/RabbitMQ）运维负担，与单机桌面部署矛盾；
2. 破坏 daemon 线程 + PySide6/本地进程生命周期假设；
3. 收益为零（无分布式/高并发/持久化队列诉求）。

**可选改进（低优先级，非阻塞，不立项）**：
- 任务状态持久化到 workspace（`proj_*/task.json`），使应用重启后任务历史/日志可恢复。当前 daemon 线程随进程退出而中断，属单机本地应用可接受行为，仅当用户反馈"重启后任务丢失不可接受"时才实施。

---

## 评估 B：数据库

### 现状事实

- **事实源**：`workspace/proj_*/project.json`（`backend/project_runtime.py:399 load_project / 431 save_project`）。
- 写入：`atomic_write_json`（原子写，防半写损坏）。
- 版本快照：`save_project` 后 `cleanup_project_versions(project_dir, project, keep=2)`（asset_retention 模块，保留最近 2 版）。
- 加载兼容：`load_project` 内 hydrate 字段 + `normalize_generation_meta` + `_normalize_director_interpretation` + governance 归一化（旧项目无损加载）。
- 列表查询：`list_projects` = `sorted(WORKSPACE.glob("proj_*/project.json"))` 逐个 load + `project_snapshot`（深拷贝）。

### 需求分析

- 数据量：4 项目 × ~1.2MB = 总量 <10MB，glob + 全量 load 毫秒级完成，无性能瓶颈。
- 查询模式：仅"列出全部项目"（`GET /api/projects`），无全文搜索、无聚合报表、无跨项目关联查询。
- 事实源已含原子写 + 版本快照 + 向后兼容归一化，一致性已满足。

### 结论：**暂不引入数据库**

当前无数据库诉求；workspace JSON 保持事实源是正确架构。

**触发条件（满足任一才立项"SQLite 只读镜像层"）**：
1. 项目数增长到数百，`list_projects` 全量 load 出现可感知延迟；
2. 出现全文搜索需求（按剧名/角色/台词检索项目）；
3. 出现跨项目聚合报表（如"所有项目的 provider 用量统计"）。

实现形态（届时）：SQLite + FTS5 只读镜像，`workspace JSON` 仍是唯一事实源，镜像由 save 钩子增量刷新，缺失即重建。

---

## 对 P3.x 立项建议

| 任务 | 建议 | 理由 |
|---|---|---|
| P3.1 Prometheus /metrics | **暂缓 / 降级为可选** | 单用户本地应用无 Prometheus 抓取场景；若加，仅作调试用轻量计数器，价值低 |
| P3.2 OpenTelemetry | **暂缓** | 无分布式链路，trace 收益极低；当前 logs/ + task stage 字段已覆盖可观测性 |
| P3.3 插件系统 | **可立项（E5 隔离承诺）** | 有真实功能诉求（第三方扩展），按 E5 只承诺显式注册/版本校验/错误边界/禁用，不承诺热加载与安全隔离 |

**建议下一步**：直接进入 P3.3 插件系统（唯一有真实价值且被 E5 约束范围清晰的项）；P3.1/P3.2 标记 deferred，等有多实例/分布式诉求时再议。
