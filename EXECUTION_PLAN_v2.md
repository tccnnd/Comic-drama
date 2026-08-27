# Comic Drama Workflow — 执行计划 v2.1（唯一执行版）

**版本**: v2.1（2026-08-27）  
**取代**: EXECUTION_PLAN.md、EXECUTION_PLAN_PATCH.md 及全部审核文档（已归档至 docs/planning/）  
**性质**: 本文件是唯一执行依据。任务编号唯一，验收命令可直接复制执行。  
**Status**: `READY FOR EXECUTION`（已吸收 EXECUTION_PLAN_v2_AUDIT.md 全部 B1-B5 / I1-I8 / 产品缺口 / E1-E3,E5 修正）  
**Validated on**: 2026-08-27  
**当前确定性门禁**: `201 passed, 8 warnings, exit=0`（完整测试，venv + 系统 TEMP basetemp）

---

## 0. 统一事实基线（已验证，2026-08-27）

| 事实 | 数值/状态 | 验证方式 |
|------|-----------|----------|
| 纯项目代码 | ~27,766 行（backend 27 py + scripts 20 py + tests + frontend 7 js） | wc -l 实测 |
| 最大文件 | run_workflow.py 6204 / render.js 2030 / app.py 1497（49 端点） | wc -l 实测 |
| 本地分支 | 8 个：5 个已合入 main，2 个未合入，1 个 main | git branch --merged/--no-merged |
| P2 重构分支 | codex/director-interpretation-mainline-impl 相对 main = 0 behind / 11 ahead，含 13 个 rw_* 模块；`merge-base --is-ancestor main <P2>` 为 true（main 已是 P2 祖先） | rev-list + is-ancestor |
| _external/Toonflow-app | gitlink（mode 160000, commit 122d2aa），remote 为 HBAI-Ltd/Toonflow-app，**主仓库缺 .gitmodules，子仓库有 tracked 修改 + 未跟踪/ignored 文件（.pnpm-store/ .pw-browsers/ .tmp/ .tools/）** | git ls-tree + remote -v + status --ignored |
| 测试基线（Gate A 主证据） | **完整测试 201 passed, 8 warnings, exit=0** | venv pytest + 系统 TEMP basetemp 实测 |
| 测试基线（环境干扰复核证据） | asset_retention 24 passed；此前"3 failed"经干净 basetemp 重跑后消失，确认为沙箱删除保护干扰，非代码回归 | 实测对比 |
| 静态检查 | py_compile 5 个高风险文件 PASS；node --check PASS | 实测 |
| CI | 已存在 ci.yml（backend/frontend/docker 三作业、coverage artifact、concurrency） | 已读取 |
| 环境 | Windows（PowerShell 5.1 / 7 均可能），无 make，无 Docker（本机）；系统全局 pytest 为 Python 3.14（禁用） | which 实测 |
| 产品主线 | v0.5.0 director interpretation：规范已完成（.kiro/specs/），implementation pending | README + docs 读取 |

---

## 1. 执行规则（所有任务必须遵守）

**R1 解释器与命令**
- 所有 Python 命令统一用 `.venv\Scripts\python.exe -m <module>`，**禁止裸 pytest / 裸 python**
- pytest 统一加 `--basetemp="$env:TEMP\cd_pytest" -p no:cacheprovider`（防沙箱删除保护干扰）
- **pytest.ini 不得写入机器相关路径**（如 `$env:TEMP`）——basetemp 只由脚本/CI 显式传递

**R2 Git 判定**
- 分支是否合入：`git branch --merged main` / `--no-merged main`，**禁止**用 `merge-base == main HEAD`
- 差异量化：`git rev-list --left-right --count main...<branch>`（区分 upstream ahead 与 main 关系）
- ancestry 判定：`git merge-base --is-ancestor <A> <B>`（exit 0 表示 A 是 B 祖先）

**R3 破坏性操作前置**
- 范围限定在主仓库，**不递归进入 `_external/`**
- 备份目录：`<repo>/.workbuddy/backups/<task>-<date>/`，命名规则 `<kind>_<branch_or_path>_<shortsha>.patch|.bundle`
- 备份内容：tracked 用 `git diff --binary` / `git diff --cached --binary`；untracked 用 `git ls-files --others --exclude-standard` 清单 + 复制；ignored 单独评估是否保留
- 每个破坏性任务记录 `backup_path / backup_manifest / restore_command / verification_result / rollback_owner`
- 单批 ≤10 项；删除前逐批验证；运行中的 PID 对应进程须先确认已退出

**R4 验收三态**
- PASS / FAIL / NOT_EVALUATED（环境不可用时，禁止把 NOT_EVALUATED 写成 PASS）
- 证据格式统一：`collected / passed / failed / warnings / coverage / threshold / exit_code / 命令`

**R5 计划唯一性**
- 本文件为唯一执行版；新发现问题记入 `docs/planning/CHANGELOG_v2.md` 的"发现"区，同批次任务内消化，**不再开新审核报告**

**R6 环境矩阵**
- 本地支持：Windows（PowerShell 5.1 与 7 均验证）；合并门禁：Linux CI（Python 3.11/3.12）
- Docker / ComfyUI / 远程视频 / 浏览器冒烟 = 条件门禁（Gate C），不可用时 NOT_EVALUATED
- 任何 check 脚本必须同时兼容 PowerShell 5.1 与 7

---

## 2. Phase 0：卫生与澄清（1 周，7 个任务）

### T0.1 磁盘清理（pytest 残留 + 日志/PID）
```
安全条件（I2）：
- 默认 dry-run，仅生成清单（Get-ChildItem | Select-Object FullName）
- 删除前验证 PID 对应进程已退出：Get-CimInstance Win32_Process -Filter "ProcessId=<pid>" 为空才删
- 范围限定主仓库，不递归 _external/
- 每批 ≤10 个目录/文件，不允许一次性 Remove-Item -Recurse 覆盖整个 .tmp/
- 删除前备份 manifest 到 .workbuddy/backups/T0.1/
范围：data/tmp_pytest*（~20 个）、根目录 *.log/*.pid/*.job/*.exit.txt、主仓库 .tmp/ 残留
验收：
- [ ] data/ 下 tmp_pytest* 目录数 = 0
- [ ] 根目录无 *.log/*.pid/*.job（运行中服务文件除外，且须记录原因）
- [ ] git status --short 无新增未跟踪残留（按计划内 allowlist 判定）
```

### T0.2 pytest basetemp 根因治理（修正 B1）
```
动作：
- 创建 pytest.ini，仅固化机器无关配置（testpaths=tests、addopts=-p no:cacheprovider）
- 不在 pytest.ini 写 basetemp（Windows 不会展开 $env:TEMP）
- basetemp 由 scripts/test.ps1 与 CI 显式传递 --basetemp="$env:TEMP/cd_pytest"
- CI 的 --basetemp data/tmp_pytest_ci 改为 ${{ runner.temp }}/cd_pytest
验收：
- [ ] 本地连续 2 次全量测试后，data/ 与项目根无新增临时目录
- [ ] CI 使用系统 TEMP，不再产生 data/tmp_pytest_ci
- [ ] pytest.ini 不含任何绝对/机器相关 basetemp 路径
```

### T0.3 .gitignore 增量补全
```
增量项：.tmp/、*.bak*、*.bak_rw4、pytest_dirs.txt、coverage.xml、.workbuddy/backups/（视团队约定）
验收：
- [ ] 新建测试文件 test.log / test.bak 后 git status 不显示
- [ ] 现有已跟踪文件不受影响（git status 干净）
```

### T0.4 游离文件归档（修正 I3，用 allowlist）
```
对象：comic_drama_fixes/、data/run_workflow.py.bak_rw4、docs/project_review_report.md、
     根目录全部计划/审核文档（本 v2.1 之外的）
allowlist（每项归属任务 + 处置）：
- EXECUTION_PLAN_v2.md（本计划，保留根目录）
- PROJECT_ANALYSIS.md（现状分析，保留根目录）
- docs/planning/（归档目录，T0.4 创建）
- .workbuddy/backups/（R3 备份，T0.1/T0.5 等产生）
- .workbuddy/memory/（项目记忆，不纳入 git）
动作：有价值内容并入 docs/，其余移入 docs/planning/ 归档；*.bak 移出仓库
验收：
- [ ] git status --short 中每一项都有：任务编号 / 保留原因 / 最终处置
- [ ] 无 allowlist 外的未跟踪项
```

### T0.5 _external/ 规范化（修正 B2，完整备份）
```
现状：Toonflow-app 已是 gitlink 但缺 .gitmodules；子仓库有 tracked 修改 + 未跟踪/ignored 文件
前置（必做，完整备份，禁止仅 git stash push）：
  cd _external/Toonflow-app
  git status --short --ignored                          # 制造完整清单
  git diff --binary > ../../.workbuddy/backups/T0.5/tracked.patch
  git diff --cached --binary > ../../.workbuddy/backups/T0.5/index.patch
  git ls-files --others --exclude-standard > ../../.workbuddy/backups/T0.5/untracked.txt
  # ignored 文件（.pnpm-store/.pw-browsers/.tmp/.tools）按是否需保留评估，需保留则复制出仓库
  # 小规模未跟踪可用 git stash push -u 并验证 stash 内容；含 ignored 构建缓存则复制而非 stash -a
方案二选一：
A) 修复 submodule：补 .gitmodules（path=_external/Toonflow-app, url=已知 remote），
   核对 gitlink commit，新增 LICENSE_NOTICE.md，新 clone 验证 git submodule update --init
B) 移出仓库：备份后 mv 至仓库外，主仓库删除 gitlink，README 记录获取方式
验收（按所选方案）：
- [ ] 已跟踪修改有 patch 或 stash 证据；未跟踪清单已保存；ignored 处置已明确
- [ ] 方案 A：git submodule status 正常；新 clone 可初始化；许可证已记录
- [ ] 方案 B：git ls-tree HEAD _external/ 为空；README 有获取说明
- [ ] 迁移后能从备份恢复一个抽样文件（verification_result 已记录）
- [ ] 注意：gitlink 的 stat Size:0 是正常现象，不是损坏
```

### T0.6 分支清理（合并 0.9/PRE-1，修正 B3 dirty worktree）
```
前置（任何 checkout/merge/branch -d 之前，R3 扩展）：
  1. git status --short --branch（记录 dirty 状态）
  2. 生成主仓库工作区 patch + 未跟踪清单（R3 备份规则）
  3. 将变更分类为 保留/归档/待确认
  4. 工作区达到 clean，或使用独立 worktree（不切当前目录）
判定（用 R2 命令）：
- 已合入（5 个）：consolidate-production-docs、director-review-console(-impl)、
  global-consistency-governance、video-provider-mainline → git branch -d 删除
- 未合入（2 个）：director-interpretation-mainline（main 领先 18，含旧 spec 提交，
  保留待 T1.1 一并决策）；director-interpretation-mainline-impl（P2 重构，保留等 T1.1）
删除前逐项确认：无未 push 提交（git log origin/<b>..<b>）、可从 main/remote 恢复
验收：
- [ ] 分支决策表已生成（8 行：状态/差异/决策/依据）
- [ ] 5 个已合入分支已删除
- [ ] 当前工作区未被 checkout/merge 改写（有前后 git status --short --branch 记录）
- [ ] 剩余分支 ≤3 且用途明确（main + 2 个待 T1.1 决策）
```

### T0.7 工作区终验
```
验收：
- [ ] git status --short 仅显示 allowlist 内文件
- [ ] 磁盘回收量记录（清理前后 du 对比）
- [ ] 备份目录 .workbuddy/backups/ 结构完整可查
```

---

## 3. Phase 1：基础设施现代化（2-3 周，10 个任务）

### T1.1 P2 重构分支合入（最高优先，修正 B3/B4 ancestry）
```
前置：主仓库与子模块 dirty 处理（同 R3/T0.6）；优先用 worktree 验证，不切当前目录
  git worktree add ..\comic-drama-p2-check codex/director-interpretation-mainline-impl
步骤：
1. 在 clean worktree 中 ls scripts/rw_*.py（应 13 个），用 R1 命令跑测试
   记录真实 collected/passed/failed（不以 commit message 的 "509 tests pass" 为准）
2. ancestry 判定（R2）：
   git merge-base --is-ancestor main codex/director-interpretation-mainline-impl
   exit 0 → main 已是 P2 祖先，跳过"先合 main 进 P2"
3. 按实际需要的步骤合入：
   A 直接合入 / B main→P2 验证反向 / C cherry-pick（B/C 仅在 main 非祖先时适用）
4. 合入后在 main clean worktree 全量测试 + py_compile + node --check
验收：
- [ ] ancestry 判定结果与所选步骤已记录
- [ ] main 含 13 个 rw_* 模块，run_workflow.py ≤1000 行
- [ ] main 全量测试 exit=0（证据 R4 格式）
- [ ] 合入前后 git status --short --branch 已记录；分支已删除或标注已合入
```

### T1.2 测试基线与覆盖率阶梯（修正 I4 固定 scope）
```
固定命令（scope 一致，CI/本地同口径）：
  .\.venv\Scripts\python.exe -m pytest tests `
    -q -p no:cacheprovider `
    --basetemp="$env:TEMP\cd_pytest" `
    --cov=backend --cov=scripts --cov=video_providers.py `
    --cov-report=term-missing --cov-report=xml:coverage.xml `
    --cov-fail-under=<threshold>
步骤：先测当前覆盖率 X% → 按下表设阈值
  X<30%: 30→50→70 | 30≤X<60: X+10→X+20→80 | X≥60: 保持→80
验收：
- [ ] 记录 collected/passed/failed/warnings/coverage/threshold/exit_code
- [ ] 排除 tests/.venv/_external/临时文件；video_providers.py 纳入
- [ ] CI COVERAGE_THRESHOLD 已更新为第一阶梯值
- [ ] 连续 3 次 CI 绿后再上调阈值；新增代码须有对应测试
```

### T1.3 依赖管理现代化
```
pip-tools 方案：requirements.in + requirements-dev.in → pip-compile 锁定
新增 pyproject.toml：requires-python = ">=3.11"（CI 3.11/3.12 矩阵）
验收：
- [ ] 锁定文件存在且 pip-sync 成功
- [ ] .venv\Scripts\python.exe -m scripts.run_workflow --input inputs\sample_story.txt
      --keyframe-provider local 端到端成功（Gate B）
```

### T1.4 app.py 路由拆分（增加 E3 API 契约快照）
```
前置（拆分前导出契约快照，避免静默破坏）：
  method / path / status code / request schema / response schema / WebSocket message schema
目标：49 端点迁入 backend/routers/（WebSocket 端点路径与消息格式不变）
验收（行为验收，非字节数）：
- [ ] 所有端点迁入 routers/，app.py 仅初始化+注册
- [ ] import backend.app 向后兼容，现有测试全过
- [ ] /api/tasks/{id}/stream 连通性测试新增且通过
- [ ] 拆分后契约快照与原快照 diff 无路径/状态码/字段非预期变化
- [ ] node --check 前端全过 + 一次浏览器冒烟（NOT_EVALUATED 需注明原因）
```

### T1.5 前端工具链（修正 I5）
```
package.json（lint/format:check 必做，Vite 可选不作为硬验收——默认仍走 uvicorn 静态服务）
锁定：Node 主版本、package manager（npm）、package-lock.json、scripts 与依赖版本
验收：
- [ ] npm install / npm run lint / npm run format:check 通过（format:check 非 format）
- [ ] 现有浏览器访问路径不受影响
```

### T1.6 格式化（修正 I6 收窄范围）
```
命令（显式目录，不扫 .）：
  .\.venv\Scripts\python.exe -m black --check backend scripts tests video_providers.py
  .\.venv\Scripts\python.exe -m isort --check-only backend scripts tests video_providers.py
pyproject.toml 排除：_external/ .venv/ .tmp/ workspace/ outputs/ data/
验收：black/isort --check 通过；格式化后全量测试仍绿
```

### T1.7 mypy 渐进
```
先 3 个核心模块（project_models、video_providers、task_store）零错误，其余 ignore_errors
验收：mypy 配置存在；3 模块零错误；其余模块渐进收紧计划已记录
```

### T1.8 CI 增量增强（修正 I7 职责边界）
```
仅负责：新增 lint 作业（black/isort/mypy 的 --check）、保留 ci.yml 现有结构
不新增具体安全工具（安全归 T2.5）
验收：新作业在 main 通过；PR 触发完整流水线；无现有作业回归
```

### T1.9 快速启动（PowerShell 必做 + Docker 可选）
```
scripts/setup.ps1 / dev.ps1 / test.ps1（参数名用 $BindHost/$pytestArgs，禁止 $Host/$args 自动变量；命令全部 venv 前缀）
Docker 可选：docker-compose.yml（当前不存在需新建）+ healthcheck 用 Python stdlib
（urllib 查 /api/health，不装 curl——镜像零增量）
验收：
- [ ] .\scripts\setup.ps1 后 .\scripts\dev.ps1 启动，/api/health 返回 ok
- [ ] 新人克隆→启动 ≤10 分钟（记录网络条件）
- [ ] Docker 路径：docker --version 可用时才执行，否则 NOT_EVALUATED
```

### P1-PROD 实现 v0.5.0 director interpretation（新增，修正 B5）
```
来源：读取 .kiro/specs/ 对应规范，建立 requirement → test 映射（E4）
内容：
- deterministic-first planner（不依赖 LLM 随机性）
- director_plan 持久化（workspace JSON，纳入 asset_retention 版本快照机制）
- per-shot visual_content 进入 provider prompt
- 保持 legacy project 兼容（无该字段仍可加载/渲染/导出）
- 新增 schema 校验、回归测试、mock-provider 测试
验收（对应 Gate D）：
- [ ] sample story 生成 director_plan
- [ ] 每个 shot 有 visual_content 或明确 not_evaluated
- [ ] provider prompt 实际消费 visual_content（断言/快照验证）
- [ ] 旧项目无该字段时仍可加载、渲染、导出
- [ ] mock provider 的 success / failure / fallback 路径均通过
```

---

## 4. Phase 2：中期治理（3-6 周，5 个任务）

| 任务 | 核心内容 | 关键验收 |
|------|----------|----------|
| T2.1 数据目录治理 | data/ 拆 fixtures/templates + **outputs/（1.8GB）保留策略** + cleanup_outputs.py（dry-run 默认） | outputs/ <500MB；fixtures 版本化；运行时数据不入 git |
| T2.2 健康检查完善 | /api/health 已有，加 /api/health/detailed（provider/comfyui/storage） | detailed 返回各组件状态；Docker healthcheck 复用 |
| T2.3 pre-commit hook（修正 I8） | black/isort/bandit + 敏感信息扫描；文件所有权用 CODEOWNERS/CI，不靠提交消息字符串 | 格式/静态/secret 违规被拦截；高风险文件变更触发明确 review 要求 |
| T2.4 日志规范化 | 统一 logger 配置；WARNING+ 落文件（logs/ 入 .gitignore） | 各模块日志格式一致 |
| T2.5 安全扫描配置（修正 I7 唯一责任方） | .bandit + .safety-policy.yml（HIGH/CRITICAL 阻塞）+ CI security job（由 T2.5 创建并维护） | Bandit 无 HIGH+；Safety 无 CRITICAL；PR 被阻塞验证 |

---

## 5. Phase 3：长期（3 计划 + 2 评估）

**评估先行（各半天，结论记录后决定是否立项）**：
- 评估 A：任务队列——现有 task_store + event_bus + WebSocket 推送是否满足？确需分布式才引入 Celery（保留 REST 兼容层）
- 评估 B：数据库——仅作索引/查询层镜像，workspace JSON 保持事实源（含 asset_retention 版本快照）

**计划任务**：
- P3.1 Prometheus 指标（/metrics）
- P3.2 OpenTelemetry
- P3.3 插件系统（修正 E5 隔离承诺）：初版只承诺显式注册、版本校验、错误边界、禁用插件；不承诺热加载与安全隔离；若需隔离须独立进程+IPC+超时设计

---

## 6. 验收门禁（四层）

**Gate A 静态（必须 PASS）**：
- [ ] 当前工作区变更已分类且有记录
- [ ] 无未解释 secrets 或路径逃逸风险
- [ ] py_compile 5 高风险文件、node --check 通过
- [ ] 完整 pytest exit=0（当前确定性 201 passed / 8 warnings）
- [ ] coverage scope 与 threshold 已记录
- [ ] API/WebSocket 契约快照无非预期变化

**Gate B 本地生产链（必须 PASS，增加媒体/时间线/降级/兼容验收）**：
- [ ] sample story 可完成 local fallback workflow
- [ ] canonical timeline 生成且时间段连续（scene/shot 开始时间连续、覆盖全时长、无重叠/空洞）
- [ ] final MP4 存在且 >0，可被 ffprobe 读取（容器/视频流/音频流）
- [ ] 实际时长与 timeline 总时长误差在阈值内；帧率/分辨率/编码符合约定
- [ ] timeline media reference 指向存在文件；generation provenance 与实际 provider 一致
- [ ] 有音频时音频流与视频拼接一致
- [ ] remote provider 失败时 fallback_used=true 且原因脱敏；strict 模式失败不生成伪成功；report 模式产物可被 review console 识别
- [ ] 旧项目无 shot_plan/generation_meta/governance 时仍可加载
- [ ] 降级规则：ComfyUI 不可用 → local 2.5D 即可通过；记录实际 provider；不要求远程视频

**Gate C 环境依赖（三态）**：Docker Compose / ComfyUI tunnel / 远程视频 / 浏览器冒烟——条件满足才执行，未执行记 NOT_EVALUATED；不能用"环境不可用"掩盖确定性代码失败

**Gate D 产品主线（必须 PASS）**：
- [ ] v0.5.0 director_plan 生成（P1-PROD）
- [ ] visual_content 进入 provider prompt
- [ ] legacy project 兼容
- [ ] mock provider success/failure/fallback 测试通过
- [ ] review/export 仍可用

---

## 7. 任务登记表（唯一编号）

| 编号 | 任务 | Phase | 状态 |
|------|------|-------|------|
| T0.1 | 磁盘清理 | 0 | partial（B=PASS；A/C=NOT_EVALUATED 环境守卫） |
| T0.2 | basetemp 根因治理 | 0 | done |
| T0.3 | .gitignore 补全 | 0 | done |
| T0.4 | 游离文件归档 | 0 | completed |
| T0.5 | _external/ 规范化 | 0 | completed（方案A：submodule正式化） |
| T0.6 | 分支清理 | 0 | completed（删5已合入分支；剩 main + 2 未合入，mainline保留待决策） |
| T0.7 | 工作区终验 | 0 | completed |
| T1.1 | P2 分支合入 | 1 | completed（509 passed/10 warnings/exit=0；13 rw_* 落位；run_workflow.py 411 行；py_compile+node --check 通过） |
| T1.2 | 测试基线+覆盖率阶梯 | 1 | completed（实测 43.92%；阈值设 43% 保 CI 绿；scope=backend/scripts/video_providers.py；后续爬升 54→64→80） |
| T1.3 | 依赖现代化 | 1 | completed |
| T1.4 | app.py 路由拆分 | 1 | planned |
| T1.5 | 前端工具链 | 1 | planned |
| T1.6 | 格式化 | 1 | planned |
| T1.7 | mypy 渐进 | 1 | planned |
| T1.8 | CI 增量增强 | 1 | planned |
| T1.9 | 快速启动 | 1 | planned |
| P1-PROD | v0.5.0 director interpretation | 1 | planned |
| T2.1 | 数据目录治理 | 2 | planned |
| T2.2 | 健康检查完善 | 2 | planned |
| T2.3 | pre-commit hook | 2 | planned |
| T2.4 | 日志规范化 | 2 | planned |
| T2.5 | 安全扫描配置 | 2 | planned |
| P3.1-3.3 | 指标/追踪/插件 | 3 | planned |
| 评估 A/B | 队列/数据库 | 3 | optional |

**计数（机械可统计口径）**：
```
Phase 0 committed: 7
Phase 1 committed: 10  (T1.1-T1.9 + P1-PROD)
Phase 2 committed: 5
Phase 0-2 committed total: 22
Phase 3 planned: 3
Optional evaluation: 2
Total listed: 27
```

---

## 8. 立即执行顺序

```text
第 1 天：T0.1 → T0.2 → T0.3（纯卫生，零风险，dry-run 优先）
第 2 天：T0.4 → T0.5（_external/ 先完整备份，按 R3）
第 3 天：T0.6 → T0.7 → 启动 T1.1（P2 分支合入，本周核心；用 worktree 验证）
里程碑：第 1 周末工作区干净、分支清晰、P2 重构落位 main
后续：T1.1 后做 P1-PROD（v0.5 产品主线），再推进 T1.2-T1.9、Phase 2、Phase 3
```

## 9. 修订记录（源自 EXECUTION_PLAN_v2_AUDIT.md，2026-08-27）

- B1 T0.2 不再把 $env:TEMP 写进 pytest.ini，改由脚本/CI 显式传 basetemp
- B2 T0.5 完整备份（tracked patch / index patch / untracked 清单 / ignored 评估），禁止仅 git stash
- B3 T0.6/T1.1 增加 dirty worktree 前置 + 独立 worktree 验证
- B4 T1.1 用 merge-base --is-ancestor 判定 ancestry，main 已是祖先时跳过反向同步
- B5 新增 P1-PROD（v0.5.0 director interpretation）纳入 Phase 1 产品主线
- I1 计数改为机械口径（Phase0-2=22 + P3=3 + 评估=2 = 27）
- I2 T0.1 增加 dry-run、PID 进程校验、限主仓库、批量≤10
- I3 T0.4 引入 allowlist（每项归属任务+处置）
- I4 T1.2 固定 coverage scope 命令与证据格式
- I5 T1.5 改 format:check 验收 + 锁定 node/包管理器/lockfile
- I6 T1.6 收窄 black/isort 范围 + pyproject 排除目录
- I7 T1.8 不碰安全工具，T2.5 为唯一安全作业责任方
- I8 T2.3 用 CODEOWNERS/CI 取代提交消息字符串所有权检查
- 产品缺口 Gate B 增加媒体/时间线/降级/兼容确定性验收；新增 Gate D
- E1 R3 扩展备份位置/命名/restore/verification/rollback_owner
- E2 R6 新增环境矩阵
- E3 T1.4 增加 API 契约快照 diff
- E4 P1-PROD 增加 spec→test 映射要求
- E5 P3.3 收敛插件隔离承诺
