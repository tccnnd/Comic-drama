# 执行计划审核报告 v3（对 AUDIT_v2 与 PATCH 的元审核）

**审核日期**: 2026-08-27  
**审核对象**: `EXECUTION_PLAN_AUDIT.md`、`EXECUTION_PLAN_AUDIT_v2.md`、`EXECUTION_PLAN_META_AUDIT.md`、`EXECUTION_PLAN_PATCH.md`  
**审核目标**: 验证审核结论、修正补丁和验收标准是否互相一致，并确认命令可以安全、准确地证明任务通过

---

## 一、最终结论

本轮审核结果：**不建议按 PATCH.md 原样执行**。

原因不是总体方向错误，而是发现了 4 个阻断级问题：

1. **分支合入判定逻辑反了**，可能把“main 是该分支祖先”误判为“该分支已合入 main”。
2. **_external/ 已经是 Git link，但缺少 `.gitmodules`，修正补丁仍按普通目录处理**，且删除/移动命令没有保护已有未提交修改。
3. **P2 分支“ahead 3”的含义被误读**：这是相对远端 tracking branch 的状态，不是相对 main 的差异；相对 main 实际是 `0 behind / 11 ahead`。
4. **当前测试门禁实际失败**：当前 main 主要测试结果为 `198 passed, 3 failed`，另有清理临时目录时的环境错误；不能继续沿用“509 tests pass”作为未复核的验收证据。

**建议状态**：审核报告方向基本正确，但 `EXECUTION_PLAN_PATCH.md` 需要修订为 v2.1 后才能作为执行依据。

---

## 二、阻断级问题（必须先修正）🔴

### 问题 1：分支“已合入”判断条件错误

PATCH.md 第 63-67 行使用：

```powershell
$mergeBase = git merge-base main $branch
$mainHead = git rev-parse main

if ($mergeBase -eq $mainHead) {
    Write-Host "状态: 已合入 main"
}
```

这个判断的真实含义是：**main 的 HEAD 是 branch 的祖先**，也就是 branch 包含了 main 的最新提交；这通常说明 branch 是从最新 main 开出来或后来合并了 main，不能证明 branch 已经合入 main。

本项目中：

```text
main...codex/director-interpretation-mainline-impl = 0 11
```

含义是：
- main 独有提交：0
- P2 分支独有提交：11
- P2 分支包含 main，但 P2 分支尚未被 main 包含

**正确判断**：

```powershell
$branchIsMerged = git merge-base --is-ancestor $branch main
if ($LASTEXITCODE -eq 0) {
    Write-Host "状态: branch 已合入 main"
} else {
    Write-Host "状态: branch 尚未合入 main"
}
```

更简单可靠的方式：

```powershell
git branch --merged main
git branch --no-merged main
```

**验收标准修正**：
- [ ] 使用 `git branch --merged main` 或 `git merge-base --is-ancestor branch main`
- [ ] 不得使用 `merge-base(main, branch) == main HEAD` 作为“已合入”依据
- [ ] 每个分支同时记录 `git rev-list --left-right --count main...branch`

这是阻断级问题，因为错误结果会直接影响后续删除分支的动作。

---

### 问题 2：_external/ 的实际状态与 PATCH.md 假设不一致

当前 Git 状态显示：

```text
git ls-tree HEAD _external/Toonflow-app
160000 commit 122d2aa... _external/Toonflow-app
```

这表示 `_external/Toonflow-app` 在主仓库中已经是 **Git submodule link（gitlink）**，不是普通文件目录。与此同时：

- 主仓库没有 `.gitmodules`
- 子仓库有 remote：`https://github.com/HBAI-Ltd/Toonflow-app.git`
- 子仓库工作区存在未提交修改和未跟踪文件
- 子仓库当前工作区不是干净状态

因此，PATCH.md 的以下做法不安全或不准确：

```powershell
git submodule add <repo-url> Toonflow-app
Remove-Item -Recurse -Force Toonflow-app/* -Exclude .git
```

以及：

```powershell
Move-Item _external\* ..\Comic-drama-references\
Remove-Item -Recurse -Force _external\
```

**风险**：
- 对已存在 gitlink 再执行 `git submodule add` 可能失败或造成元数据冲突
- `Remove-Item` / `Move-Item` 没有先备份和核对子仓库未提交修改
- `-Exclude .git` 不能作为可靠的 Git 子模块迁移方案
- 子模块转换不会自动使当前工作区磁盘占用降到 0；submodule 仍然需要完整 checkout

**正确处理方向**：

#### 选项 A：修复现有 submodule 元数据（优先评估）

```powershell
# 只读核验
Test-Path .gitmodules
git ls-tree HEAD _external/Toonflow-app
git -C _external/Toonflow-app remote -v
git -C _external/Toonflow-app status --short
```

若确认保留：
- 补齐 `.gitmodules` 的 `path` 和 `url`
- 核对 gitlink 指向的 commit 是否为预期版本
- 先另行保存子仓库工作区的未提交修改
- 增加许可证清单
- 重新 clone 验证 `git submodule update --init --recursive`

#### 选项 B：移出仓库

只有在明确确认子仓库工作区修改已保留后，才允许迁移。验收必须包含：

- [ ] 迁移前后 commit hash 一致或变更已记录
- [ ] 子仓库未提交修改已单独保存
- [ ] 主仓库不再保留 `_external/Toonflow-app` gitlink
- [ ] README 记录获取方式
- [ ] 新 clone 后主项目仍可运行

**验收修正**：不能使用“`du -sh _external/` 显著下降”证明 submodule 转换成功。应分别记录：
- 主仓库是否存在有效 `.gitmodules`
- `git submodule status` 是否成功
- 全新 clone 是否能初始化子模块
- 当前工作区占用是否符合明确的保留策略

---

### 问题 3：“ahead 3”被错误解释为相对 main 的差异

报告和 PATCH.md 中多次写：

```text
codex/director-interpretation-mainline-impl: [ahead 3]
```

`git branch -vv` 的 `[ahead 3]` 是相对该分支配置的 upstream tracking branch，不是相对 main。

实际核验：

```text
main...codex/director-interpretation-mainline-impl = 0 11
```

因此报告中的以下表述需要改写：

- 错误/不严谨：P2 分支“ahead 3，未合入 main”
- 正确：P2 分支相对其 upstream ahead 3；相对 main 为 0 behind、11 ahead，且 `git branch --no-merged main` 将其列为未合入

**验收修正**：所有分支报告同时记录三项数据：

```powershell
git rev-list --left-right --count main...$branch
git rev-list --left-right --count "origin/<upstream>...$branch"
git branch --merged main
```

不能把 upstream 关系和 main 合入关系混用。

---

### 问题 4：测试验收使用了未经当前基线复核的“509 tests pass”

PATCH.md 以 commit message 中的：

```text
509 tests pass
```

作为验收预期。commit message 只能作为历史记录，不能替代当前环境中的测试证据。

当前 main 实测：

```text
198 passed, 3 failed, 8 warnings
```

失败集中在 `tests/test_asset_retention.py`，并伴随清理 `.tmp` 临时目录时的环境保护错误。当前状态至少应标记为：

```text
Current main test gate: FAIL
```

**验收标准修正**：

- [ ] 在目标分支当前环境执行测试
- [ ] 以 pytest 退出码为准，不以 commit message 的测试数量为准
- [ ] 记录实际 collected / passed / failed / error 数量
- [ ] 失败必须按“代码失败 / 环境保护失败 / 外部服务不可用”分类
- [ ] 合入 main 后重新执行一次完整门禁

建议使用：

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp <系统临时目录>
```

不要把项目内 `.tmp` 路径作为默认 basetemp，除非已确认当前清理保护机制允许该路径。

---

## 三、重要问题（应修正）🟠

### 问题 5：PowerShell 快速启动脚本存在自动变量名冲突

PATCH.md 中：

```powershell
param(
    [string]$Host = "127.0.0.1",
    [int]$Port = 8000
)
```

以及：

```powershell
$args = @()
```

`$Host` 和 `$args` 都是 PowerShell 自动变量名。将它们用作参数或临时变量会造成冲突或不可预期行为。

**修正**：

```powershell
param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000
)

$pytestArgs = @()
```

并将后续引用全部同步改为 `$BindHost`、`$pytestArgs`。

验收追加：

- [ ] 在 Windows PowerShell 5.1 上执行
- [ ] 在 PowerShell 7 上执行
- [ ] `setup.ps1`、`dev.ps1`、`test.ps1` 均返回正确退出码

---

### 问题 6：Docker Compose 健康检查与 Dockerfile 不匹配

PATCH.md 的 compose 健康检查使用：

```yaml
test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
```

但当前 Dockerfile 只安装了 ffmpeg，没有安装 curl。容器内可能不存在 curl，导致服务实际可用但健康检查一直失败。

**修正选项（二选一）**：

- 在 Dockerfile 中安装 `curl`
- 改用 Python 标准库健康检查命令，或增加专用 healthcheck 脚本

验收：

- [ ] `docker compose ps` 的 health 状态与 `/api/health` 实际响应一致
- [ ] 重新构建镜像后健康检查仍然通过
- [ ] 未安装 Docker 时，该项标记为环境未验证，不得标记为 PASS

---

### 问题 7：计划计数仍然自相矛盾

不同文档出现了：

- 27 个必做 + 2 个评估
- 28 个必做 + 2 个评估
- 29 个必做 + 2 个评估
- Phase 0 任务数 8 或 9
- Phase 1 任务数 9 或 10

此外，Task 1.0、Task 1.9 的编号是补丁新增，但 `EXECUTION_PLAN.md` 正文并没有同步改写，导致“主计划”和“补丁执行版”并存。

**修正建议**：

1. 选定一个主计划文件
2. 将补丁内容合并回主计划，或明确 PATCH 是唯一执行版
3. 删除重复任务计数，统一为一张任务登记表
4. 每个任务增加唯一状态字段：`planned / in_progress / blocked / done / optional`
5. 对可选任务不计入必做任务总数

**验收**：

- [ ] 全部文档中的任务总数一致
- [ ] 每个任务编号唯一
- [ ] 必做与可选任务可机械统计
- [ ] 主计划与审核报告引用同一版本号

---

### 问题 8：当前测试文件数量被早期报告统计错误污染

早期报告曾写“1,712 个测试文件”。实际仓库顶层 `tests/` 当前只有：

- 8 个 Python 测试模块
- 1 个 JavaScript helper 测试
- `__init__.py` 和 `conftest.py`

早期统计把 `.venv`、临时目录、缓存或其他路径计入了结果。该错误已影响“测试基础设施脆弱”的论据强度。

**修正**：

- 删除“1,712 个测试文件”这一表述
- 使用 `find tests -maxdepth 1 -type f` 或 pytest collected 数量作为基线
- 将真实问题改写为：测试基线尚未稳定，当前有 asset retention 环境失败，且覆盖率阈值仍为 0

---

### 问题 9：覆盖率验收仍不够可执行

“先测量 X%，再按 X 设阶梯”方向正确，但仍缺少：

- 测量命令的固定 scope
- 是否把 tests、外部目录、运行时代码纳入统计
- 阶梯的生效提交
- 何谓“稳定两周”

**建议固定口径**：

```powershell
.venv\Scripts\python.exe -m pytest tests \
  --cov=backend --cov=scripts --cov=video_providers.py \
  --cov-report=term-missing --cov-report=xml:coverage.xml \
  --cov-fail-under=<threshold>
```

PowerShell 多行命令应使用反引号，或者写成单行，避免把 bash 的反斜杠续行直接复制到 PowerShell。

**验收**：

- [ ] 记录 scope、collected、coverage、threshold、pytest exit code
- [ ] 阈值配置与本地命令一致
- [ ] 新增代码不得降低覆盖率（diff coverage 或新增测试作为补充）
- [ ] “稳定两周”改为可验证条件，例如连续 3 次 CI 成功 + 无已知 flaky failure

---

## 四、对原验收标准的最终判断

| 验收项 | 原判断 | v3 判断 | 结论 |
|--------|--------|---------|------|
| 分支数 ≤3 | 过于简化 | 仍不可单独作为验收 | 必须改为状态表 + ancestry + 决策 |
| P2 分支已合入 | 可通过 merge-base 判断 | 当前判断逻辑错误 | 阻断，必须修正 |
| `_external/` 转 submodule | 二选一 | 当前已经是 gitlink，缺 `.gitmodules` | 先修元数据，不能重复 add |
| `_external/` 占用下降 | 可作为结果 | 对 submodule 不成立 | 删除该指标或拆为仓库/工作区两个指标 |
| 509 tests pass | 预期结果 | 历史 commit message，不是当前证据 | 以当前 pytest 退出码为准 |
| 覆盖率阶梯 | 方向正确 | scope 和稳定条件不足 | 可保留，需补证据格式 |
| PowerShell 快速启动 | 可执行 | `$Host`/`$args` 有冲突 | 修正变量名后验收 |
| Docker Compose health | 可选 | curl 依赖未安装 | 修正 Dockerfile 或 healthcheck |
| 新人 ≤10分钟 | 明确 | 受首次下载依赖、网络和环境影响 | 改为“干净环境实测，记录网络条件” |
| 代码文件行数目标 | 可测 | 方向合理 | 需配合行为等价测试，不能单独验收 |

---

## 五、建议的验收门禁分层

不要用一个“全部通过/全部失败”指标覆盖所有环境依赖，建议分三层：

### Gate A：静态与确定性门禁（必须通过）

- [ ] Python 高风险文件 `py_compile` 通过
- [ ] 前端 `node --check` 通过
- [ ] 单元测试无代码失败
- [ ] 分支 ancestry 判断正确
- [ ] 无 secrets、无未解释的工作区变更

### Gate B：本地可复现工作流（必须记录）

- [ ] local keyframe workflow 成功
- [ ] `canonical_timeline.json` 生成
- [ ] final video 生成
- [ ] fallback provenance 正确记录
- [ ] 输出路径和项目 workspace 不污染 Git

### Gate C：环境依赖验证（条件通过）

- [ ] Docker Compose：仅 Docker 可用时执行
- [ ] ComfyUI tunnel：仅隧道可用时执行
- [ ] 真实远程视频：仅 API 配额和凭据可用时执行
- [ ] 浏览器视觉冒烟：浏览器允许 localhost 时执行

Gate C 未执行时状态应为 `not_evaluated`，不能写成 PASS，也不能一律算 FAIL。

---

## 六、最终任务状态建议

在修正计划前，建议先建立以下 4 个前置任务：

| 编号 | 任务 | 阻塞级别 | 通过证据 |
|------|------|----------|----------|
| PRE-1 | 修正分支 ancestry 判定 | 阻断 | `git branch --merged/--no-merged main` + rev-list 记录 |
| PRE-2 | 核对 `_external/` gitlink 和 `.gitmodules` | 阻断 | 元数据、remote、dirty state、许可证记录 |
| PRE-3 | 建立当前 pytest 基线并修复/分类失败 | 阻断 | 当前环境实际 pytest 退出码和分类报告 |
| PRE-4 | 统一主计划、补丁版本和任务计数 | 高 | 单一执行版 + 唯一任务表 |

完成 PRE-1 至 PRE-4 后，才开始 Task 0.9、Task 1.0 或新的重构工作。

---

## 七、最终结论

`EXECUTION_PLAN_AUDIT_v2.md` 的问题发现方向基本成立，但 `EXECUTION_PLAN_PATCH.md` 还不能作为安全执行版。

**最终评分**：

- 问题发现质量：8/10
- 证据准确性：6/10
- 验收标准可测性：6/10
- 执行安全性：4/10
- 文档一致性：5/10

**修订后目标**：

1. 修正分支 ancestry 逻辑
2. 重新处理已存在的 `_external/` gitlink
3. 用当前 pytest 结果替代“509 tests pass”历史描述
4. 修正 PowerShell 变量冲突和 Docker healthcheck 依赖
5. 统一任务编号、任务总数和唯一执行版
6. 将环境门禁分成 PASS / FAIL / NOT_EVALUATED

完成以上 6 项后，计划和验收标准才达到可执行状态。

**当前结论**：`PATCH.md` 暂不通过；按本报告 PRE-1 至 PRE-4 修正后再执行。
