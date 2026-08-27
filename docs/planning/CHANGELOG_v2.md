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

### 2026-08-27 — T1.1 P2 分支合入完成

- **动作**: `git merge --no-ff codex/director-interpretation-mainline-impl`，冲突解决：
  - `pytest.ini`：保留 P2 的 `norecursedirs`，去除 `--basetemp=data/tmp_pytest`（遵循 R1，basetemp 由脚本/CI 显式传递）
  - `.gitignore`：合并两边增量（P2 完整列表 + Phase0 的 `.tmp/`、`*.bak`、`*.bak_rw4`、`pytest_dirs.txt`）
  - `ci.yml`：保留 CI 显式 `--basetemp=${{ runner.temp }}/cd_pytest` + P2 的 coverage 配置
- **验收（R4 证据）**: collected=509, passed=509, failed=0, warnings=10, exit_code=0
- **关键事实**: merge-base 为旧 main(`4caa6c3`)；Phase0 提交 `31bfa8e` 不在 P2 历史 → main 非 P2 祖先，故产生真实三方合并（非 fast-forward）
- **rw_\* 模块**: 13 个已落位 `scripts/`；`run_workflow.py` 由 6204 → 411 行
- **py_compile**: 7 个高风险文件 PASS；**node --check**: 8 个前端文件 PASS
- **环境坑（重要复用）**: Git Bash 下 `$TEMP` 展开为 `/tmp` → pytest 解析为 `E:\tmp`（盘根不存在），导致 basetemp 父目录 mkdir 失败、128 个 ERROR（setup 阶段）。修复：用 `tempfile.gettempdir()` 取真实 Windows 临时目录并 `-p` 创建父目录后再跑。CI 用 `runner.temp` 不受影响。本地跑测试务必确保 basetemp 父目录存在。

### 分支状态（T1.1 后）

- `codex/director-interpretation-mainline-impl`：已合入 main（`--merged`），可安全删除（暂不删，避免误删；且未推 GitHub）
- `codex/director-interpretation-mainline`：仍 `--no-merged`，含独有提交 → 按 T0.6 约定**保留**，待后续决策
