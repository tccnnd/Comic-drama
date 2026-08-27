# EXECUTION_PLAN_v2 审核报告

**审核日期**: 2026-08-27  
**审核对象**: `EXECUTION_PLAN_v2.md`  
**审核目的**: 核验唯一执行版的事实准确性、任务边界、执行顺序、命令安全性和验收标准

---

## 一、结论

**结论：有条件通过，但暂不建议原样执行。**

`EXECUTION_PLAN_v2.md` 已经解决了前几版最严重的问题：

- 不再混淆 upstream ahead 与 main 合入状态
- 明确了 PASS / FAIL / NOT_EVALUATED 三态
- 把 PRE 任务吸收到 T0/T1，避免双轨执行
- 统一要求使用项目虚拟环境
- 明确 ComfyUI 不可用时允许 local 2.5D 降级

但仍有 **5 个阻断级问题、8 个重要问题、若干验收标准缺口**。建议先完成本报告第七节的修正，再把该文件作为正式执行版。

**当前评分**:

| 维度 | 评分 | 结论 |
|------|------|------|
| 问题覆盖度 | 8/10 | 主要工程风险已覆盖，但产品主线和安全验收不足 |
| 事实准确性 | 7/10 | 大部分正确，测试基线和任务计数仍有问题 |
| 命令可执行性 | 6/10 | 存在 pytest.ini、stash、Git 检查等命令风险 |
| 验收可证伪性 | 6/10 | 部分标准只有“做了”描述，缺少固定证据格式 |
| 执行安全性 | 6/10 | 已有保护意识，但删除、迁移、切分支仍需更严格前置条件 |
| **综合** | **6.6/10** | **修正后可执行** |

---

## 二、已验证的当前基线

本轮用当前工作区重新核对，结果如下：

```text
完整主要测试：201 passed, 8 warnings, exit=0
asset_retention 测试：24 passed, exit=0
高风险 Python 文件 py_compile：PASS
frontend/app.js node --check：PASS
本地分支：8 个
  已合入 main：5 个
  未合入 main：2 个
  main：1 个
P2 分支相对 main：0 behind / 11 ahead
Docker：本机不可用
Make：本机不可用
pytest.ini / pyproject.toml：不存在
package.json：不存在
Docker Compose：不存在
```

需要特别修正计划中的一处事实表达：当前“测试基线”不应只写 `asset_retention 24 passed`。Gate A 使用的应是完整测试基线：**201 passed, 8 warnings, exit=0**。`asset_retention 24 passed` 应作为环境干扰复核证据单独记录。

---

## 三、阻断级问题

### B1. T0.2 的 pytest.ini 固化方案不可直接实现

计划写的是：

```text
创建 pytest.ini，固化 basetemp 到系统临时目录
```

但 Windows 的 `%TEMP%` 是机器相关路径，pytest 配置文件不会按 PowerShell 语法自动展开 `$env:TEMP`。如果把 `$env:TEMP\cd_pytest` 直接写进 pytest.ini，通常不会得到预期的系统临时目录。

**建议改为三选一**：

1. 在 `scripts/test.ps1` 中显式传递：
   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests `
     -p no:cacheprovider `
     --basetemp="$env:TEMP\cd_pytest"
   ```
2. 在 CI 中显式使用 `${{ runner.temp }}` 或系统临时目录
3. 仅在 pytest.ini 固化与机器无关的测试配置，不固化 basetemp 路径

**验收标准应改为**：

- [ ] 本地测试脚本显式传递系统临时目录
- [ ] CI 不再使用 `data/tmp_pytest_ci`
- [ ] 连续两次测试后 `data/` 与项目根目录无新增 pytest 临时目录

---

### B2. T0.5 的 `git stash` 不能保证保存当前子模块全部修改

计划要求：

```bash
cd _external/Toonflow-app && git stash push -m "backup before cleanup"
```

当前子模块不仅有已跟踪修改，还有未跟踪文件，例如 `.pnpm-store/`、`.pw-browsers/`、`.tmp/`、`.tools/` 等。普通 `git stash push` 默认不会保存未跟踪文件，更不会保存 ignored 文件。

**风险**：执行后认为“已备份”，实际可能丢失子模块工作区文件。

**修正方案**：

在迁移前先生成只读清单：

```powershell
git -C _external/Toonflow-app status --short --ignored
git -C _external/Toonflow-app diff --binary > external_tracked.patch
git -C _external/Toonflow-app diff --cached --binary > external_index.patch
git -C _external/Toonflow-app ls-files --others --exclude-standard > external_untracked.txt
```

之后根据文件规模选择：

- 小规模：使用 `git stash push -u`，并验证 stash 内容
- 含 ignored/构建缓存：将未跟踪文件复制或压缩到仓库外备份目录，不要盲目 `stash -a`
- 需要保留提交历史：使用 `git bundle`，但要另行处理未跟踪文件

**验收标准应增加**：

- [ ] 已跟踪修改有 patch 或 stash 证据
- [ ] 未跟踪文件清单已保存
- [ ] ignored 文件是否需要保留已明确
- [ ] 迁移后可从备份恢复一个抽样文件

---

### B3. T0.6 / T1.1 没有处理当前 dirty worktree 前置条件

当前主仓库有未提交修改和未跟踪文件，子模块也有未提交修改。计划随后直接使用：

```powershell
git checkout codex/director-interpretation-mainline-impl
git merge main
```

这可能被 Git 拒绝，也可能把工作区变化带到目标分支，造成无法辨认的污染。

**修正**：新增统一前置条件：

```text
任何 checkout / merge / branch -d 之前：
1. git status --short --branch
2. 生成工作区 patch 和未跟踪清单
3. 将用户/代理变更分类为保留、归档或待确认
4. 确认工作区达到 clean，或明确使用临时 worktree
```

更安全的方式是使用独立 worktree 验证 P2 分支，不切换当前工作目录：

```powershell
git worktree add ..\comic-drama-p2-check codex/director-interpretation-mainline-impl
```

**验收**：

- [ ] 当前工作区没有被 checkout/merge 改写
- [ ] P2 验证在 clean worktree 中完成
- [ ] 所有清理或合并动作均有前后 `git status --short --branch` 记录

---

### B4. T1.1 的推荐策略 B 不适合当前 P2 分支状态

当前实际关系是：

```text
main...codex/director-interpretation-mainline-impl = 0 11
```

这表示 main 是 P2 分支的祖先，P2 分支已经包含 main。计划推荐：

```text
先合 main 进 P2 分支，再反向合入 main
```

在当前状态下，第一步通常是无操作或产生无意义合并提交。若 main 在执行期间没有新提交，直接在 clean worktree 验证 P2 后合并即可。

**修正策略**：

1. 先用 ancestry 判断是否需要合并 main
2. 若 `main` 已是 P2 的祖先：跳过“main → P2”
3. 在 P2 clean worktree 运行完整测试
4. 再将 P2 合入 main，合入后在 main clean worktree 再测一次

推荐流程：

```powershell
git merge-base --is-ancestor main codex/director-interpretation-mainline-impl
# exit 0 表示 main 已是 P2 祖先，可跳过反向同步
```

**验收不能只写“策略 B 已执行”**，应写成：

- [ ] 根据 ancestry 结果选择实际需要的合并步骤
- [ ] 合并前后差异和测试结果已记录
- [ ] main 合入后完整测试 exit=0

---

### B5. 计划遗漏当前项目的产品主线 v0.5.0

项目 README 和生产流水线文档明确：

```text
v0.5.0 director interpretation：规范已完成，implementation pending
```

当前 v2 计划主要安排的是磁盘卫生、分支整合、工具链、Docker、日志、监控和插件系统，却没有把 **director_plan + per-shot visual_content** 的实现纳入任何 Phase。

这会导致基础设施工作完成后，项目的下一项产品能力仍未推进，与项目的当前版本方向不一致。

**修正建议**：

在 Phase 1 完成 P2 重构落位后，新增产品任务：

```text
P1-PROD：实现 v0.5.0 director interpretation
- 读取已有 .kiro/specs/ 规范
- deterministic-first planner
- director_plan 持久化
- per-shot visual_content 进入 provider prompt
- 保持 legacy project 兼容
- 增加 schema、回归和 mock-provider 测试
```

至少需要纳入以下验收：

- [ ] sample story 生成 director_plan
- [ ] 每个 shot 有 visual_content 或明确 not_evaluated
- [ ] provider prompt 实际消费 visual_content
- [ ] 旧项目无该字段时仍可加载、渲染、导出
- [ ] mock provider 成功、失败、fallback 路径均通过

---

## 四、重要问题

### I1. 任务计数仍然错误

计划登记表写：

```text
计数：21 必做（P0=7, P1=9, P2=5）+ P3 3 项 + 2 评估
```

但表内实际数量为：

- T0.1-T0.7：7
- T1.1-T1.9：9
- T2.1-T2.5：5
- P3.1-P3.3：3

因此应是：

```text
24 个必做任务 + 2 个评估任务
```

如果把 P3 也计入必做，则是 24 个必做；如果 P3 尚未承诺，则应写 21 个 Phase 0-2 必做 + 3 个 Phase 3 计划任务 + 2 个评估，不能写“21 必做 + P3 3 项”而不说明统计口径。

**修正**：采用机械可统计的格式：

```text
Phase 0-2 committed: 21
Phase 3 planned: 3
Optional evaluation: 2
Total listed: 26
```

不要再使用“必做”同时包含或不包含 P3 的模糊口径。

---

### I2. T0.1 删除范围和安全条件不足

计划的范围包括：

```text
.tmp/ 残留、根目录日志/PID/job、data/tmp_pytest*
```

但没有明确区分：

- 当前仍在运行的服务对应的 PID/log/job 文件
- 用户希望保留的调试日志
- `.tmp/` 中的分析产物和可能有价值的报告
- 子模块内部的 `.tmp/`、构建缓存

**修正**：

- 默认 dry-run，只生成清单
- 删除前验证 PID 对应进程是否仍在运行
- 清理范围限制在主仓库，不递归进入 `_external/`
- 每批最多 10 个目录/文件
- 删除前保留 manifest 和备份位置
- 删除后逐批验证，不允许一次性 `Remove-Item -Recurse` 覆盖整个 `.tmp/`

---

### I3. T0.4 的验收条件不能只看 `git status`

计划写：

```text
git status 未跟踪项仅剩 EXECUTION_PLAN_v2.md 与计划内产物
```

但当前计划本身会生成：

- `docs/planning/` 归档文件
- 分支状态表
- 外部仓库备份或 patch
- 覆盖率报告
- 可能的 `.workbuddy/` 项目记忆

如果没有固定 allowlist，“计划内产物”无法机械判断。

**修正**：创建 `allowed_untracked.txt` 或直接在计划中列出 allowlist，并把每个允许文件归属到具体任务。更好的目标是：

```text
git status --short 中每一项都有：任务编号、保留原因、最终处置
```

而不是简单追求“只剩某两个文件”。

---

### I4. T1.2 覆盖率阶梯缺少固定 scope 和统计口径

计划只写“用 R1 命令测当前覆盖率 X%”，但没有完整固定：

- `--cov` 的目标包
- 是否包含 `video_providers.py`
- 是否排除 tests、`.venv`、`_external`、临时文件
- 警告是否允许
- 当前基线和阶梯值保存在哪里

**建议固定命令**：

```powershell
.\.venv\Scripts\python.exe -m pytest tests `
  -q -p no:cacheprovider `
  --basetemp="$env:TEMP\cd_pytest" `
  --cov=backend `
  --cov=scripts `
  --cov=video_providers.py `
  --cov-report=term-missing `
  --cov-report=xml:coverage.xml `
  --cov-fail-under=<threshold>
```

**验收**：

- [ ] 记录 collected、passed、failed、warnings、coverage、threshold、exit code
- [ ] CI 和本地 scope 一致
- [ ] 连续 3 次 CI 通过后才提升阈值
- [ ] 新增代码有对应测试，不只依赖总覆盖率

---

### I5. T1.5 的 `npm run format` 不是有效的验收命令

`format` 通常是修改型命令，执行成功不代表代码已经符合格式；它可能每次都修改文件但仍返回 0。

**修正**：同时提供：

```json
{
  "scripts": {
    "format": "prettier --write ...",
    "format:check": "prettier --check ...",
    "lint": "eslint ..."
  }
}
```

验收使用 `npm run format:check`，`npm run format` 只用于开发者自动修复。

还应锁定：

- Node 主版本
- package manager
- `package-lock.json` 或等价 lockfile
- package.json 的 scripts 和依赖版本

---

### I6. T1.6 的格式化范围过宽

计划写：

```text
black --check . / isort --check .
```

这会把项目外部目录、数据目录、缓存和可能的子模块内容纳入检查，既不稳定也不符合项目实际边界。

**修正**：

```powershell
.\.venv\Scripts\python.exe -m black --check backend scripts tests video_providers.py
.\.venv\Scripts\python.exe -m isort --check-only backend scripts tests video_providers.py
```

并在 `pyproject.toml` 中明确排除：

```text
_external/
.venv/
.tmp/
workspace/
outputs/
data/
```

---

### I7. T1.8 与 T2.5 的安全扫描职责重叠

T1.8 写“CI 增量增加 security 作业”，T2.5 又写“安全扫描配置 + CI 作业”。这会产生重复实现或两个不同的 security 作业。

**建议拆分**：

- T1.8：只负责 CI 结构和 lint 作业，不新增具体安全工具
- T2.5：负责 Bandit/Safety 配置、阈值、报告和 CI security job

或者：

- T1.8 完成 security job 骨架
- T2.5 只补规则和基线

必须明确谁创建、谁维护、谁验收。

---

### I8. T2.3 文件所有权 hook 的实现边界不清晰

计划要求 pre-commit hook 检查 AGENTS.md 高风险文件，但没有定义可信的“所有者证明”。提交消息尚未在普通 pre-commit 阶段形成，不能可靠依赖“提交消息包含 Codex 标记”。

**建议**：

- 使用 `CODEOWNERS` 约束需要 reviewer 的文件
- pre-commit 只做格式、静态检查和敏感信息扫描
- 分支/文件所有权通过 PR review 或 CI 检查，不通过本地 hook 判断代理身份
- 验收改为：高风险文件变更触发明确 review 要求，不能仅靠字符串标记绕过

---

## 五、产品验收缺口

当前 Gate B 只验证“生成了 timeline、MP4 和 provenance”，还不足以证明视频产物可用。

建议增加以下确定性检查：

### 媒体完整性

- [ ] MP4 文件存在且大小 > 0
- [ ] ffprobe 能读取容器、视频流、音频流
- [ ] 实际时长与 canonical timeline 总时长误差在明确阈值内
- [ ] 帧率、分辨率、编码格式符合项目约定
- [ ] 有音频时音频时长和视频拼接结果一致

### 时间线完整性

- [ ] 所有 scene/shot 的开始时间连续
- [ ] shot 覆盖 scene 全时长且无重叠/空洞
- [ ] timeline media reference 指向存在的文件
- [ ] generation provenance 与实际 provider 一致

### 降级完整性

- [ ] remote provider 失败时 fallback_used=true
- [ ] fallback 原因已脱敏
- [ ] strict 模式失败时不生成伪成功结果
- [ ] report 模式生成结果但状态可被 review console 识别

### 兼容性

- [ ] 旧项目无 `shot_plan` / `generation_meta` / `governance` 时仍可加载
- [ ] API 路由与 WebSocket 消息 schema 不变
- [ ] 导出路径不允许通过 project_id 或文件名逃逸工作区

---

## 六、遗漏的基础工程任务

### E1. 缺少回滚与变更记录的落地规则

R3 只写“先备份”，但没有定义：

- 备份目录位置
- 备份命名规则
- 如何验证备份可恢复
- 失败后如何回滚
- 哪些操作需要用户二次确认

建议每个破坏性任务记录：

```text
backup_path
backup_manifest
restore_command
verification_result
rollback_owner
```

### E2. 缺少环境矩阵

计划提到 Python 3.11/3.12，但没有把以下组合纳入验收：

- Windows PowerShell 5.1
- PowerShell 7
- Linux CI
- Python 3.11 / 3.12
- Node 主版本
- Docker 可用 / 不可用

至少应明确：Windows 是本地支持环境，Linux CI 是合并门禁，Docker 是条件门禁。

### E3. 缺少 API 契约快照

T1.4 拆分 49 个端点时，只写“所有端点迁入 routers”，没有要求记录拆分前后路由清单。

建议在拆分前导出：

```text
method
path
status code
request schema
response schema
WebSocket message schema
```

拆分后进行差异比较，避免 endpoint path、状态码或字段被悄悄改变。

### E4. 缺少 v0.5 spec 的验收映射

`.kiro/specs/` 已有多份一手规范，但 v2 只提到“阅读”，没有把 spec 的 requirement/acceptance criterion 映射到任务表。

建议每个产品任务增加：

```text
source_spec
requirement_ids
acceptance_test_ids
```

### E5. P3 插件系统的隔离承诺过强

在进程内使用 `importlib` 加载插件，无法证明“插件错误不影响主系统”，更不能实现真正的安全隔离或可靠热加载。

如果保留 P3.3：

- 初版只承诺显式注册、版本校验、错误边界和禁用插件
- 不承诺热加载和安全隔离
- 若要隔离，使用独立进程/worker，并补充 IPC、权限和超时设计

---

## 七、建议修订顺序

### 第一优先级：先修执行安全

1. 修正 T0.2 的 basetemp 实现方式
2. 修正 T0.5 的完整备份方案
3. 增加 dirty worktree / clean worktree 前置条件
4. 修正 T1.1 的当前 ancestry 分支流程
5. 统一任务计数和统计口径

### 第二优先级：补产品主线

6. 将 v0.5.0 director interpretation 纳入 Phase 1 产品任务
7. 读取对应 `.kiro/specs/` 并建立 requirement 到 test 的映射
8. 增加 timeline、媒体完整性和 fallback 的确定性验收

### 第三优先级：治理工程质量

9. 固定 coverage scope 和证据格式
10. 将 `format` 改为 `format:check` 验收
11. 消除 T1.8/T2.5 安全扫描重复
12. 用 CODEOWNERS/CI 取代不可靠的所有权字符串检查

---

## 八、建议的最终门禁

### Gate A：代码与数据安全，必须 PASS

- [ ] 当前工作区变更已分类且有记录
- [ ] 无未解释的 secrets 或路径逃逸风险
- [ ] py_compile、node --check 通过
- [ ] 完整 pytest exit=0
- [ ] coverage scope 和 threshold 已记录
- [ ] API/WebSocket 契约快照无非预期变化

### Gate B：本地生产链，必须 PASS

- [ ] sample story 可完成 local fallback workflow
- [ ] canonical timeline 生成且时间段连续
- [ ] final MP4 可被 ffprobe 读取
- [ ] 实际时长、音频流、分辨率、帧率满足阈值
- [ ] generation provenance 与实际路径一致
- [ ] fallback/report/strict 行为符合配置

### Gate C：条件环境，三态记录

- [ ] Docker Compose
- [ ] ComfyUI tunnel
- [ ] 真实远程视频 provider
- [ ] 浏览器视觉冒烟

环境不可用时记 `NOT_EVALUATED`；测试执行但失败记 `FAIL`；不能用“环境不可用”掩盖确定性代码失败。

### Gate D：产品主线，必须 PASS

- [ ] v0.5.0 director_plan 生成
- [ ] visual_content 进入 provider prompt
- [ ] legacy project 兼容
- [ ] mock provider success/failure/fallback 测试通过
- [ ] review/export 仍可用

---

## 九、最终判定

`EXECUTION_PLAN_v2.md` 相比所有旧版本已经明显收敛，**可以作为修订基础，但还不是最终执行版**。

正式执行前必须完成：

```text
B1-B5：5 个阻断级问题
I1-I4：任务计数、清理安全、覆盖率和 allowlist
P1-PROD：v0.5 产品主线补充
Gate B：媒体和时间线完整性验收
```

完成后建议将文件版本更新为 `v2.1`，并在文件头写明：

```text
Status: READY FOR EXECUTION
Validated on: 2026-08-27
Current deterministic gate: 201 passed, 8 warnings, exit=0
```

**当前状态**：`CONDITIONAL_PASS`  
**不能原样执行**：`YES`  
**是否需要继续创建新的审核报告**：`NO`。下一步应直接修订执行计划并开始前置门禁，不再继续审核套审核。
