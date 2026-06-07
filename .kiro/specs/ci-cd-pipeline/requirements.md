# Requirements Document

## Introduction

本文档定义 Comic Drama Workflow 仓库的 CI/CD 流水线需求。下文分为问题陈述、用户价值、名词表与具体需求等部分。

## 问题陈述

Comic Drama Workflow 仓库当前没有任何持续集成 / 持续交付（CI/CD）配置（`.github/` 下仅有 Issue 模板、PR 模板和标签定义，没有 `workflows/` 目录）。这意味着：

- 推送代码或提交 Pull Request 时，没有自动化检查保证后端 Python 代码可编译、测试通过。
- 高风险文件（`scripts/run_workflow.py`、`backend/project_runtime.py`、`backend/app.py`、`video_providers.py`、`scripts/video_provider_adapters.py` 等）的语法错误可能在合并后才被发现。
- 前端 `frontend/app.js`（原生 JavaScript）缺少自动语法检查。
- 仓库以 Windows 为主（包含 `.bat`、`.vbs`、`.ps1` 脚本），缺乏跨平台（Linux）可运行性的持续验证。
- 没有自动化机制防止凭据（`.env`、provider token、模型权重）在 CI 流程中被意外暴露。

本规范定义一套基于 GitHub Actions 的 CI/CD 流水线，在不要求真实第三方 provider 凭据的前提下，对每次推送和 Pull Request 自动执行编译、测试、覆盖率门禁和语法检查。

## 用户价值

- 维护者在合并前即可获得后端测试、覆盖率和语法检查的明确通过 / 失败信号。
- 高风险文件在每次变更时都被自动 `py_compile` 校验，降低运行时被破坏的风险。
- 前端 `frontend/app.js` 变更得到自动语法校验，配合 AGENTS.md 中的协作约定。
- 在 `ubuntu-latest` 上验证代码可在非 Windows 环境运行，提升可移植性。
- CI 流程不依赖也不暴露真实凭据，保护 API key、provider token 与模型权重。
- PR 页面上提供清晰的状态徽章 / 检查结果，便于评审决策。

## Glossary

- **CI_Pipeline（CI 流水线）**：定义在 `.github/workflows/` 下的 GitHub Actions 工作流集合，在指定事件触发时执行自动化检查。
- **Backend_Job（后端作业）**：负责安装 Python 依赖、运行 pytest 测试并执行覆盖率门禁的 CI 作业。
- **Frontend_Job（前端作业）**：负责对原生 JavaScript（含 `frontend/app.js`）执行语法检查及可用 lint 的 CI 作业。
- **Syntax_Check_Step（语法检查步骤）**：使用 `python -m py_compile` 对高风险 Python 文件执行编译校验的步骤。
- **Coverage_Gate（覆盖率门禁）**：当测试覆盖率低于配置阈值时使作业失败的判定机制。
- **Docker_Build_Job（Docker 构建作业）**：使用仓库现有 `Dockerfile` 验证镜像可成功构建的可选 CI 作业。
- **Coverage_Threshold（覆盖率阈值）**：覆盖率门禁所用的最小可接受测试覆盖率百分比，是一个可配置的数值。
- **High_Risk_Files（高风险文件）**：AGENTS.md 中列出的需额外谨慎处理的文件，包括 `scripts/run_workflow.py`、`backend/project_runtime.py`、`backend/app.py`、`video_providers.py`、`scripts/video_provider_adapters.py`。
- **Secret_Value（敏感值）**：API key、provider token、SSH 密码、模型权重等不应出现在 CI 日志或产物中的凭据数据。
- **Status_Badge（状态徽章）**：嵌入到 README 中、反映 CI 流水线最新执行结果的可视化标识。

## Requirements

### 需求 1：流水线触发

**用户故事：** 作为仓库维护者，我希望在每次推送和 Pull Request 时自动运行 CI 流水线，以便在合并前发现问题。

#### 验收标准

1. WHEN 一次提交被推送到仓库的任意分支，THE CI_Pipeline SHALL 在 60 秒内将一次执行排入队列，并在 GitHub Actions 运行记录中创建一条状态为「进行中」的对应运行条目。
2. WHEN 一个面向默认分支的 Pull Request 被创建、更新（推送新提交）或重新打开，THE CI_Pipeline SHALL 在 60 秒内将一次执行排入队列，并将运行状态回报到该 Pull Request 的检查（checks）区域。
3. WHILE 同一分支或同一 Pull Request 已存在一次「进行中」的执行，WHEN 针对该分支或该 Pull Request 触发新一次执行，THE CI_Pipeline SHALL 取消先前「进行中」的执行，并仅保留最新一次执行继续运行。
4. IF 触发执行时 `.github/workflows/` 目录下的 YAML 工作流文件存在语法错误或无法被解析，THEN THE CI_Pipeline SHALL 不启动任何作业，并在 GitHub Actions 运行记录中将该次触发标记为失败，同时给出指明工作流文件无效的错误提示。
5. THE CI_Pipeline SHALL 将所有作业定义在 `.github/workflows/` 目录下的 YAML 工作流文件中。
6. THE CI_Pipeline SHALL 在 `ubuntu-latest` 运行器上执行所有作业。

### 需求 2：后端测试与依赖安装

**用户故事：** 作为后端开发者，我希望 CI 自动安装依赖并运行 pytest，以便确认后端逻辑在干净环境中通过测试。

#### 验收标准

1. THE Backend_Job SHALL 在执行前配置 Python 3.11 或更高且低于 4.0 版本的运行环境。
2. WHEN Backend_Job 开始执行，THE Backend_Job SHALL 使用仓库根目录下的 `requirements.txt` 安装项目依赖，并在 600 秒内完成安装。
3. IF `requirements.txt` 文件不存在或为空，THEN THE Backend_Job SHALL 以失败状态结束，并在日志中记录指示文件缺失或为空的错误信息。
4. WHEN 依赖安装成功完成，THE Backend_Job SHALL 执行 `tests/` 目录下的全部 pytest 测试套件。
5. WHEN 全部 pytest 测试通过，THE Backend_Job SHALL 以成功状态结束，并在日志中记录通过与失败的测试数量。
6. IF 任一 pytest 测试失败，THEN THE Backend_Job SHALL 以失败状态结束，并在日志中记录失败测试的名称与数量。
7. IF 依赖安装在 600 秒内未完成或返回非零退出码，THEN THE Backend_Job SHALL 以失败状态结束，并在日志中记录指示安装失败原因的错误信息。

### 需求 3：覆盖率报告与门禁

**用户故事：** 作为仓库维护者，我希望 CI 报告测试覆盖率并在覆盖率过低时阻止合并，以便维持测试质量。

#### 验收标准

1. WHEN Backend_Job 运行 pytest 测试套件，THE Backend_Job SHALL 生成包含总体覆盖率百分比与各模块覆盖率百分比的测试覆盖率报告。
2. THE Backend_Job SHALL 将覆盖率报告输出到作业日志，且日志内容至少包含精确到 0.01% 的总体覆盖率百分比与各模块覆盖率百分比。
3. IF 测量得到的总体覆盖率低于 Coverage_Threshold，THEN THE Coverage_Gate SHALL 使 Backend_Job 以失败状态结束，并在作业日志中输出指明覆盖率未达标的信息。
4. WHEN 测量得到的总体覆盖率大于或等于 Coverage_Threshold，THE Coverage_Gate SHALL 使 Backend_Job 以成功状态继续。
5. WHERE 配置文件中提供了介于 0 到 100（含端点）之间的 Coverage_Threshold 值，THE Coverage_Gate SHALL 使用该配置值作为门禁判定依据。
6. IF 配置文件中未提供 Coverage_Threshold 值，THEN THE Coverage_Gate SHALL 使用默认阈值 80% 作为门禁判定依据。
7. WHEN Backend_Job 完成 pytest 测试套件运行，THE Backend_Job SHALL 将覆盖率报告作为构建产物（artifact）上传，且该产物在作业完成后至少保留 7 天以供查阅。

### 需求 4：高风险文件语法检查

**用户故事：** 作为仓库维护者，我希望 CI 对高风险文件执行编译检查，以便尽早发现语法破坏。

#### 验收标准

1. WHEN CI 流水线被触发，THE Syntax_Check_Step SHALL 依次对全部 High_Risk_Files（`scripts/run_workflow.py`、`backend/project_runtime.py`、`backend/app.py`、`video_providers.py`、`scripts/video_provider_adapters.py`，共 5 个文件）执行 `python -m py_compile`。
2. WHEN 全部 5 个 High_Risk_Files 均编译成功，THE Syntax_Check_Step SHALL 以成功状态（退出码 0）结束，并在日志中逐一记录每个文件的通过结果。
3. IF 任一 High_Risk_Files 编译失败，THEN THE Syntax_Check_Step SHALL 立即以失败状态（非 0 退出码）结束，并在日志中标明出错文件的相对路径及导致失败的错误说明，同时不修改任何被检查文件的内容。
4. WHERE 某个 High_Risk_Files 在仓库中不存在，THE Syntax_Check_Step SHALL 在日志中记录该文件缺失（含其相对路径），并以失败状态（非 0 退出码）结束。
5. IF Syntax_Check_Step 自启动起 60 秒内未完成全部 5 个文件的编译检查，THEN THE Syntax_Check_Step SHALL 以失败状态（非 0 退出码）结束，并在日志中记录超时及尚未完成检查的文件。

### 需求 5：前端语法检查

**用户故事：** 作为前端开发者，我希望 CI 自动检查 `frontend/app.js` 的语法，以便在合并前确认前端脚本可被解析。

#### 验收标准

1. WHEN Frontend_Job 启动，THE Frontend_Job SHALL 配置并固定使用单一指定的 Node.js LTS 版本作为运行环境。
2. WHEN Node.js 运行环境就绪，THE Frontend_Job SHALL 对 `frontend/app.js` 执行 `node --check` 语法检查。
3. IF `frontend/app.js` 不存在或无法读取，THEN THE Frontend_Job SHALL 以失败状态结束，并输出指明该文件缺失或不可读的错误信息。
4. IF `frontend/app.js` 语法检查失败，THEN THE Frontend_Job SHALL 以失败状态结束，输出指明语法错误的信息，且不再执行后续的 lint 与测试步骤。
5. WHERE 仓库中存在已配置的前端 lint 工具，THE Frontend_Job SHALL 执行该 lint 检查；IF lint 检查报告任一错误，THEN THE Frontend_Job SHALL 以失败状态结束并输出指明 lint 错误的信息。
6. WHERE 仓库中存在可执行的前端测试（例如 `tests/` 下的 `.mjs` 测试），THE Frontend_Job SHALL 使用已配置的 Node.js 运行环境执行这些测试；IF 任一测试失败，THEN THE Frontend_Job SHALL 以失败状态结束并输出指明失败测试的信息。

### 需求 6：跨平台可运行性

**用户故事：** 作为维护者，我希望在 Linux 环境验证项目逻辑，以便在以 Windows 为主的仓库中保持跨平台可移植性。

#### 验收标准

1. WHEN CI_Pipeline 收到 push 或 pull request 事件，THE CI_Pipeline SHALL 在 `ubuntu-latest` 运行器上执行 Backend_Job 与 Frontend_Job。
2. THE Backend_Job SHALL 在测试执行期间不调用任何 Windows 专用脚本（`.bat`、`.vbs`、`.ps1`）。
3. WHEN Backend_Job 与 Frontend_Job 的所有未被跳过测试均通过，THE CI_Pipeline SHALL 以表示成功的退出状态结束本次运行。
4. IF 某项测试依赖仅限 Windows 的能力，THEN THE Backend_Job SHALL 跳过该测试，并在运行日志中记录被跳过测试的标识与跳过原因。
5. IF Backend_Job 或 Frontend_Job 中存在任一未被跳过的失败测试，THEN THE CI_Pipeline SHALL 以表示失败的退出状态结束本次运行，并在运行日志中标示出现失败的作业。

### 需求 7：凭据与敏感数据保护

**用户故事：** 作为仓库维护者，我希望 CI 流程既不要求也不暴露真实凭据，以便保护 API key、provider token 和模型权重。

#### 验收标准

1. THE CI_Pipeline SHALL 在运行所有作业期间不读取、不创建、不还原也不下载仓库内或环境中的 `.env` 文件。
2. WHEN 测试需要 provider 凭据，THE Backend_Job SHALL 使用 mock 替身或显式跳过策略替代真实凭据，且不对真实 provider 端点发起任何外部网络请求。
3. IF 真实 provider 凭据（如 `LLM_API_KEY`、ComfyUI SSH 密码）缺失或为空，THEN THE CI_Pipeline SHALL 仍将所有作业运行至完成并返回成功状态（在其余检查均通过的前提下）。
4. THE CI_Pipeline SHALL 不在作业日志或构建产物中以明文或可逆编码形式输出任何 Secret_Value，并对检测到的 Secret_Value 以固定掩码占位符（如 `***`）替换。
5. WHEN CI_Pipeline 收集并上传构建产物，THE CI_Pipeline SHALL 确保 `.env`、`workspace/`、`outputs/`、`tools/`、模型权重及私有生成媒体均不出现在上传的产物中。
6. IF 检测到被排除路径或 Secret_Value 即将进入上传产物，THEN THE CI_Pipeline SHALL 阻止该上传并以失败状态结束，同时输出不含 Secret_Value 的错误指示。

### 需求 8：Docker 构建验证（可选作业）

**用户故事：** 作为维护者，我希望 CI 可选地验证 Docker 镜像可成功构建，以便确认容器化交付路径有效。

#### 验收标准

1. WHERE 启用了 Docker 构建验证，WHEN CI 流水线触发 Docker_Build_Job，THE Docker_Build_Job SHALL 使用仓库根目录现有的 `Dockerfile` 构建镜像，并在镜像构建完成且无错误时以成功状态结束。
2. IF Docker 镜像构建失败，THEN THE Docker_Build_Job SHALL 以失败状态结束，并在作业日志中记录指示失败原因的错误信息。
3. THE Docker_Build_Job SHALL 在不向任何外部镜像仓库推送镜像的情况下完成构建验证。
4. WHERE 启用了 Docker 构建验证，IF 仓库根目录不存在可用的 `Dockerfile`，THEN THE Docker_Build_Job SHALL 以失败状态结束，并在作业日志中记录指示缺少 `Dockerfile` 的错误信息。
5. WHERE 启用了 Docker 构建验证，IF 镜像构建在 1800 秒（30 分钟）内未完成，THEN THE Docker_Build_Job SHALL 终止构建、以失败状态结束，并在作业日志中记录指示构建超时的错误信息。
6. WHERE 未启用 Docker 构建验证，WHEN CI 流水线运行，THE Docker_Build_Job SHALL 跳过镜像构建步骤，且不改变 CI 流水线的整体通过/失败状态。

### 需求 9：状态报告与徽章

**用户故事：** 作为评审者，我希望在 PR 上看到清晰的 CI 状态，以便据此做出合并决策。

#### 验收标准

1. WHEN CI_Pipeline 完成全部作业的执行，THE CI_Pipeline SHALL 在 60 秒内于对应的 Pull Request 上为每个作业报告其结束状态（通过、失败、跳过之一）。
2. WHEN CI_Pipeline 完成一次执行，THE CI_Pipeline SHALL 在 60 秒内更新可嵌入 README 的 Status_Badge，使其反映该次执行的结果状态（通过、失败、未知之一）。
3. WHILE CI_Pipeline 尚未完成任何一次执行，THE CI_Pipeline SHALL 将 Status_Badge 显示为「未知」状态。
4. WHEN 任一作业以失败或错误状态结束，THE CI_Pipeline SHALL 将整体流水线状态标记为失败。
5. IF CI_Pipeline 无法将状态报告写入对应的 Pull Request（如网络中断或权限不足），THEN THE CI_Pipeline SHALL 重试最多 3 次，且在全部重试均失败后将整体流水线状态标记为失败并在执行记录中保留可见的失败指示。
