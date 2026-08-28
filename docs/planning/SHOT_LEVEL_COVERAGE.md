# shot-level-video-rendering 覆盖度核查（2026-08-28）

> 对 `.kiro/specs/shot-level-video-rendering`（draft spec）的实现覆盖度核查。
> 核查方式：任务勾选统计 → 代码定位 → 测试映射 → 端到端实测。

## 结论摘要

| 项 | 结论 |
|---|---|
| 任务完成度 | **16/17 已勾选**（task 17 = Optional controlled live validation，需真实 provider，属 Gate C） |
| 后端 API / 项目路径 | ✅ 已完整接入 shot 渲染编排 |
| **CLI 批处理路径** | ⚠️ **缺口**：`--video-render-granularity shot` 仅写入 storyboard 元数据，渲染不消费 |

---

## Requirement → 实现 → 测试映射

| Requirement | 实现位置 | 测试 |
|---|---|---|
| FR-1 渲染粒度控制 | `backend/video_generation.py` `video_render_granularity()`(L130) / `normalize_video_render_granularity()`(L119)；`project_runtime.py` L190 | `test_video_render_granularity_resolves_precedence`、`test_create_project_persists_video_render_granularity` |
| FR-2 逐镜头 provider 渲染 | `build_shot_provider_request_inputs`(L770)、`render_shot_with_provider_policy`(L897) | `test_build_shot_provider_request_inputs_preserves_shot_context_and_video_model`、`_uses_video_provider_env_model_not_llm`、`test_render_shot_with_provider_policy_returns_real_video_output` |
| FR-3 镜头组装 | `assemble_shot_clips`(L1135)、`build_shot_assembly_manifest`(L1546) | `test_assemble_shot_clips_uses_hard_cut_concat_and_writes_manifest`、`_rejects_empty_usable_outputs` |
| FR-4 镜头级 provenance | `build_shot_output`(L1440)、`generation_meta_from_shot_outputs`(L1482) | `test_build_shot_output_sanitizes_and_stabilizes_record`、`test_generation_meta_from_shot_outputs_aggregates_counts_and_sanitizes` |
| FR-5 镜头级 fallback | `render_shot_with_provider_policy` fallback 分支 | `test_render_shot_with_provider_policy_report_failure_uses_fallback`、`_strict_failure_raises`、`test_video_fallback_mode_honors_provider_specific_strict` |
| FR-6 resume / 定向重渲染 | `build_shot_cache_key`(L257)；`scene_renderer.rerender_scene_shot_video`(L802) | `test_build_shot_cache_key_is_stable_and_tracks_render_inputs` |
| FR-7 成本/配额控制 | `estimate_shot_render_quota`(L312)、`validate_shot_render_quota`(L368) | `test_estimate_shot_render_quota_counts_calls_seconds_and_cache_reuse`、`test_validate_shot_render_quota_blocks_over_limit_before_submit`、`test_video_shot_quota_config_resolves_request_project_and_env` |
| FR-8 Review Console 可见性 | `frontend/utils.js` L476 `meta.shot_outputs` | `tests/test_frontend_imports.mjs`（shot_outputs 渲染 + `data-action="rerender-shot-video"`） |
| AC-5 timeline 兼容 | `normalize_generation_meta` | `test_normalize_generation_meta_preserves_v2_shot_outputs_and_counts` |

**测试实测**：Python shot 级测试 **29 passed**；前端 mjs **2 passed**。

---

## 缺口：CLI 批处理路径不消费 render granularity

### 证据

1. 端到端实测（`--video-render-granularity shot --video-provider local`）：
   - `outputs/run_20260828_232724/` 成功产出 final MP4（exit=0）
   - 日志中**无任何 shot/granularity 输出**
   - `storyboard.json` 的 `video_render_granularity: "shot"`（仅元数据记录）
   - 每个 scene 的 `generation_meta` **无 `shot_outputs` 字段**
2. 代码定位：
   - `scripts/run_workflow.py`：`render_granularity` 仅用于 L387 解析、L448/521/551 写入 storyboard 元数据
   - 实际渲染调用：L478 `render_clip_with_meta` → `scripts/rw_render.py` L430-476（remote backend，**scene 级**单次调用）
   - `scripts/rw_render.py` 全文件无 granularity/shot 处理
3. 对照：后端 API 路径 `backend/scene_renderer.py` L468 已调用 `render_scene_shots_with_provider_policy`，L802 有 `rerender_scene_shot_video` → **已接入**

### 与 spec 的偏差

- FR-1.3 要求："Granularity SHALL be configurable through `VIDEO_RENDER_GRANULARITY=scene|shot`, with **CLI**/API/project settings allowed to override the environment default"
- 实际：CLI 可传参但未在渲染路径消费 → **FR-1.3 在 CLI 侧未完整实现**

### 补齐方案（待确认后实施）

复用 `backend/video_generation.render_scene_shots_with_provider_policy`（**纯函数式签名**：scene/shot_plan/run_dir/ffmpeg + `fallback_renderer` 回调，无 project_id 依赖，CLI 可复用）：

1. 在 `scripts/rw_render.py` 新增 `render_clip_shots_with_meta(...)`：
   - 用 `build_shot_plan(storyboard_scene)` 取 shot_plan
   - 调用 `render_scene_shots_with_provider_policy(..., fallback_renderer=<CLI local 2.5D 渲染器>)`
   - 返回 `(clip_path, shot_generation_meta)`
2. `scripts/run_workflow.py` L478 处加分支（改动最小，该文件属 AGENTS.md high-risk）：
   ```python
   if render_granularity == "shot":
       clip_path, shot_meta = render_clip_shots_with_meta(...)
       storyboard_scene["generation_meta"] = merge(generation_meta_from_result(...), shot_meta)
   else:
       clip_path, render_result = render_clip_with_meta(...)   # 原路径不变
   ```
3. 验收：shot 模式端到端产出 `shot_outputs`；scene 模式回归不受影响；全量测试通过。

### 附带发现（文档与代码不一致）

`AGENTS.md` 的 Required Checks 写 `python scripts\run_workflow.py --input inputs\sample_story.txt`，
实际参数名为 `--story`（非 `--input`），且直接跑脚本需 `PYTHONPATH=.`（否则 `ModuleNotFoundError: No module named 'backend'`）。
建议更新 AGENTS.md 的示例命令。
