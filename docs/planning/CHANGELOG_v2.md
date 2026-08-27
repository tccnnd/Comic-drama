# EXECUTION_PLAN_v2 修订日志

**主文件**: `EXECUTION_PLAN_v2.md`  
**规则**: 新发现问题记入本文件"发现"区，同批次任务内消化，不再开新审核报告（R5）。

---

## v2.0 → v2.1（2026-08-27）

吸收 `EXECUTION_PLAN_v2_AUDIT.md` 全部结论：

- 5 个阻断级问题（B1-B5）：basetemp 实现、子模块完整备份、dirty worktree 前置、P2 ancestry 流程、v0.5 产品主线遗漏
- 8 个重要问题（I1-I8）：任务计数、清理安全、allowlist、coverage scope、format:check、格式化范围、安全职责拆分、所有权检查
- 产品验收缺口：Gate B 增加媒体/时间线/降级/兼容确定性验收；新增 Gate D
- 工程遗漏（E1-E3,E5）：备份/回滚规则、环境矩阵、API 契约快照、spec→test 映射、插件隔离承诺收敛

**结果**: 状态由 CONDITIONAL_PASS 提升为 READY FOR EXECUTION；当前确定性门禁 201 passed, 8 warnings, exit=0。

---

## 发现区（后续任务中新增，按 R5 追加）

（暂无）
