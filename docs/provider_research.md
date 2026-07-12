# Provider 调研（桌面研究阶段）

> **状态**：桌面研究，未实测。  
> **目的**：在花账号额度前完成 6 维对比，筛出 1–2 家做付费小样本实测。  
> **配套**：`docs/provider_rubric.md`（评分标准）、`video_providers.py`（注册表）、`scripts/video_provider_adapters.py`（适配层）。  
> **版本**：v0.2.0 video-provider-mainline 准备阶段。

## 1. 调研目标

为 Phase 1 "Real Video Generation" 挑出 1–2 家**国内可访问 + 漫画/短剧适配**的视频生成 provider，作为主推方案进入付费实测。

硬约束（不满足即出局）：

- 国内可访问（不需要翻墙即可用）
- 有公开 API（不是只接 SDK 或仅 Web 控制台）
- 商用条款清晰（不锁商用、不锁版权归属）

软目标（按理论分排）：

- 漫画/二次元风格可控
- 首尾帧 / 人物参考能力
- 单价 ≤ 2 元/秒

## 2. 候选名单（8 家）

| Provider | 来源 | 类型 | 后端 backend | 代码侧状态 | 备注 |
|---|---|---|---|---|---|
| **可灵 Kling** | 快手 | I2V / T2V | `remote` | JWT 认证代码已预留 | 国内主力；漫画适配理论最优 |
| **Vidu** | 生数科技 | T2V 强 | `remote` | 未注册 | 长镜头、角色一致性强 |
| **PixVerse** | 爱诗科技 | I2V / T2V | `remote` | 未注册 | 模板化、短剧友好 |
| **Runway Gen-3/4** | 海外 | I2V / T2V | `remote` | 未注册 | 行业基准；质量高但国内不可访问 |
| **Pika 2.0** | 海外 | I2V 强 | `remote` | 未注册 | 编辑能力；国内不可访问 |
| **字节豆包 Seedance** | 火山引擎 | T2V / I2V | `remote` | 已注册（`seedance` id） | 国内便利、价格低 |
| **腾讯 HunyuanVideo** | 腾讯 | T2V | `local`（开源权重）| 暂无 | 自托管路径；可走 ComfyUI |
| **Hailuo / MiniMax Video** | MiniMax | T2V | `remote` | 未注册 | 性价比、二次元；时长偏短 |

> **HunyuanVideo** 不走 remote 路径，而是和 ComfyUI 自托管一起算（参考 `docs/cloud_gpu_restore.md`）。

## 3. 六维度对比

> **数据来源说明**：以下信息来自公开文档、媒体评测、官方价格页；**未经实测**。实测分需 `scripts/provider_viability_gate.py` 跑出。

### 3.1 维度 1 — API

| Provider | 官方/SDK | 文档 | 限流 | 备注 |
|---|---|---|---|---|
| Kling | 官方 | 完整 | 中 | JWT 认证（代码已有 `_kling_jwt_token` / `_kling_auth_headers`） |
| Vidu | 官方 | 中 | 偏紧 | 提交/轮询模式 |
| PixVerse | 官方 + SDK | 完整 | 中 | 海外域名，部分功能需代理 |
| Runway | 官方 | 完整 | 中 | 海外计费，信用卡 |
| Pika | 官方 | 完整 | 中 | 海外计费，信用卡 |
| Seedance | 火山引擎 | 完整 | 宽松 | 已有 `seedance` 注册项 |
| HunyuanVideo | 开源 | 自建文档 | N/A | 需自行部署/微调 |
| Hailuo | 官方 | 完整 | 宽松 | 邮箱注册 |

### 3.2 维度 2 — I2V / T2V 支持

| Provider | T2V | I2V | 首尾帧 | 人物参考 | 单镜头时长上限 |
|---|---|---|---|---|---|
| Kling | ✅ | ✅ | ✅ | ✅（多图）| 10s |
| Vidu | ✅ | ✅ | ✅ | ✅ | 8s |
| PixVerse | ✅ | ✅ | ✅ | ❌ | 8s |
| Runway | ✅ | ✅ | ✅ | ✅ | 10s |
| Pika | ✅ | ✅ | ✅ | ✅ | 10s |
| Seedance | ✅ | ✅ | ⚠️ | ❌ | 12s |
| HunyuanVideo | ✅ | ⚠️ | ❌ | ❌ | 取决于配置 |
| Hailuo | ✅ | ✅ | ✅ | ❌ | 6s |

### 3.3 维度 3 — 国内可访问性

| Provider | 注册门槛 | 网络 | 合规通道 |
|---|---|---|---|
| Kling | 实名 + 企业 | 直连 | ✅ ICP 备案 |
| Vidu | 实名 | 直连 | ✅ |
| PixVerse | 海外为主 | 部分需代理 | ⚠️ |
| Runway | 海外信用卡 | 完全不可 | ❌ |
| Pika | 海外信用卡 | 完全不可 | ❌ |
| Seedance | 实名 + 企业 | 直连 | ✅ 火山引擎 ICP |
| HunyuanVideo | 自建 | 完全本地 | ✅ |
| Hailuo | 邮箱 | 大陆可访问 | ✅ |

### 3.4 维度 4 — 成本（4s / 1080p 标准镜头）

| Provider | 单价 | 计费粒度 | 最小起付 | 备注 |
|---|---|---|---|---|
| Kling | 约 1–2 元/秒 | 视频秒 | 无 | 公开报价；阶梯优惠 |
| Vidu | 约 2–3 元/秒 | 视频秒 | 充值 | 阶梯 |
| PixVerse | 约 0.5 美元/秒 | 视频秒 | 信用卡 | 海外计费 |
| Runway | 0.5–1 美元/秒 | credit | 10 美元 | 海外 |
| Pika | 0.5–1 美元/秒 | credit | 10 美元 | 海外 |
| Seedance | 0.5–1 元/秒 | 视频秒 | 充值 | 阶梯优惠 |
| HunyuanVideo | GPU 推理成本 | 自建 | 一次性 | 算力租赁另算 |
| Hailuo | 约 0.3–0.5 元/秒 | 视频秒 | 充值 | 性价比 |

> 价格区间来自公开信息，**未对账**；实测阶段需从 API 控制台拉真实账单。

### 3.5 维度 5 — 输出质量（理论分，未实测）

| Provider | 分辨率 | 时长 | 运动稳定 | 人物一致 | 风格覆盖 |
|---|---|---|---|---|---|
| Kling | 1080p | ≤10s | 优 | 优 | 写实 + 二次元皆可 |
| Vidu | 1080p | ≤8s | 良 | 优 | 写实强 |
| PixVerse | 1080p | ≤8s | 中 | 良 | 多样 |
| Runway | 1080p+ | ≤10s | 优 | 优 | 电影感 |
| Pika | 1080p | ≤10s | 良 | 良 | 写实 |
| Seedance | 1080p | ≤12s | 良 | 良 | 写实强 |
| HunyuanVideo | 取决于配置 | 自定 | 中 | 良 | 写实 |
| Hailuo | 1080p | ≤6s | 良 | 优 | 写实 + 二次元 |

### 3.6 维度 6 — 漫画/短剧适配

| Provider | 漫画风 | 短剧节奏 | 镜头控制 | 备注 |
|---|---|---|---|---|
| Kling | ✅ 二次元 prompt 强 | ✅ | ✅ | 漫画适配理论最优 |
| Vidu | ⚠️ 偏写实 | ✅ | ✅ | 写实短剧 |
| PixVerse | ✅ 模板化 | ✅ | ⚠️ | 模板驱动 |
| Runway | ⚠️ 偏写实 | ✅ | ✅ | 电影感 |
| Pika | ❌ 偏写实 | ✅ | ✅ | 写实短剧 |
| Seedance | ⚠️ | ✅ | ✅ | 写实短剧 |
| HunyuanVideo | ⚠️ 取决于微调 | 自定义 | 自定义 | 自托管灵活 |
| Hailuo | ✅ 二次元 | ⚠️ 时长短 | ⚠️ | 时长 6s 是短板 |

## 4. 理论分（0–5）

> ⚠️ 全部为**理论分**，未实测。实际分需 viability gate 验证后填入。  
> 评分标准见 `docs/provider_rubric.md`。

| Provider | API | T2V/I2V | 国内 | 成本 | 质量 | 漫画适配 | **总分** | 状态 |
|---|---|---|---|---|---|---|---|---|
| **Kling** | 4 | 5 | 5 | 3 | 4 | 5 | **26/30** | 主推候选 #1 |
| Vidu | 3 | 4 | 5 | 2 | 4 | 3 | **21/30** | 备选 |
| PixVerse | 4 | 3 | 3 | 3 | 3 | 4 | **20/30** | 备选 |
| Runway | 5 | 5 | 0 | 2 | 5 | 2 | **19/30** | 国内不可访问 → fail |
| Pika | 4 | 4 | 0 | 2 | 3 | 1 | **14/30** | 国内不可访问 → fail |
| Seedance | 4 | 4 | 5 | 4 | 3 | 2 | **22/30** | 主推候选 #2 |
| HunyuanVideo | 2 | 2 | 5 | 4 | 3 | 3 | **19/30** | 备选（自托管路径） |
| Hailuo | 4 | 3 | 4 | 5 | 3 | 3 | **22/30** | 主推候选 #3 |

## 5. 风险与注意事项

1. **理论分 ≠ 实测分**。Kling 看上去 26 分第一，但 5 维都需要"漫画风实测"才能确认；实测阶段可能 19 分也可能 28 分。
2. **价格波动大**。Seedance、Hailuo 都有阶梯优惠和促销期价；本表取常见区间，**实测需拉真实账单**。
3. **国内可访问性是硬约束**。Runway/Pika 即使总分 19-14 也直接 fail（F3 完全无法访问）。
4. **首尾帧 + 人物参考**。漫画/短剧最关心的两个能力，理论上 Kling/Vidu/Pika/Runway 都支持，但实测效果差别大。
5. **时长上限**。Hailuo 6 秒对短剧是短板（一个 30s 镜头要切 5 段才能凑齐）。
6. **代码侧**：当前 `video_providers.py` 只注册了 `local` / `comfyui` / `sora` / `seedance` 四家；Kling 已有 JWT 工具函数但未注册为独立 provider id，实测通过需在 `video_providers.py` 加 `register_video_provider` 项。

## 6. 实测推荐顺序

按"国内可访问 + 漫画适配最优"两个硬约束筛过的**前三家**：

1. **Kling**（理论 26/30，漫画适配理论最优）
2. **Seedance**（理论 22/30，国内便利、价格低；代码已注册）
3. **Hailuo**（理论 22/30，性价比 + 二次元）

**实测预算**：3 家各 5 镜头测试（每家约 50–100 元），总预算 < 300 元。

如果实测后**主推候选 #1 (Kling) 通过 fail 检查 + 总分 ≥ 22**，则主推 Kling + 备选 Seedance；否则降级为 Seedance + 备选 Hailuo。

## 7. 后续动作

| 阶段 | 动作 | 输出 | 阻塞 |
|---|---|---|---|
| 桌面研究（本文） | 列候选 + 理论分 | `provider_research.md` | — |
| 评分标准 | 细化 0–5 + fail 规则 | `provider_rubric.md` | — |
| Viability gate 脚本 | 自动化 4 维度 | `scripts/provider_viability_gate.py` | 前端 ESM 阻断修复 + scorecard 接入 |
| 准备 5 镜头 reference | 从 v0.5.0 `director_plan` 生成 | `inputs/viability_test/` | director_plan 已就绪 |
| 注册账号 | Kling / Seedance / Hailuo | `.env` 配置 | 账号申请 |
| 付费实测 | 3 家各 5 镜头 | 更新本表为实测分 | viability gate |

## 附录 A — 信息源（待补）

桌面研究阶段，本表信息来自公开文档和媒体评测；实测阶段会补充：

- [ ] 各 provider 官方 API 文档直链
- [ ] 价格表截图（避免凭印象）
- [ ] 实测账单对账记录
- [ ] VLM/CLIP 评分脚本输出

## 附录 B — 与代码的对齐

本文档与代码的对应关系：

| 文档内容 | 代码位置 | 状态 |
|---|---|---|
| Provider 注册表 | `video_providers.py` | 已有 `local` / `comfyui` / `sora` / `seedance` |
| Kling JWT 认证 | `scripts/video_provider_adapters.py:52-94` | 已有 |
| Kling adapter（未注册为 provider） | `scripts/video_provider_adapters.py` | 部分实现 |
| Structured spec 输出 | `docs/self_hosted_video_provider.md` | 已有 `temporal_spec` / `consistency_spec` |
| Provider 路由选择 | `VIDEO_PROVIDER` env | 已有 |

实测后新增 provider（如 Kling / Hailuo）需：

1. `video_providers.py` 加 `register_video_provider(VideoProviderSpec(...))`
2. `scripts/video_provider_adapters.py` 加对应 adapter 函数
3. `docs/self_hosted_video_provider.md` 加配置示例
