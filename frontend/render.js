// DOM Rendering Functions

import {
  state,
  appRoot,
  tabs,
  TASK_CAPABILITIES,
  assetTabs,
  voiceEngines,
  voiceSamples,
  voiceProfiles,
  voiceEmotions,
  bgmStyles,
  bgmFiles,
  planners,
  cameraOptions,
  TIMELINE_PX_PER_SECOND,
} from "./state.js";
import {
  h,
  nl,
  asNumber,
  clamp,
  normalizeCropBox,
  cropPercent,
  formatSeconds,
  looksGarbledScriptText,
  statusClass,
  previewSceneFieldId,
  selectedScene,
  selectedCharacter,
  canonicalTimeline,
  timelineSceneItems,
  sceneAssetGaps,
  projectAssetGapEntries,
  sceneAudioManifest,
  sceneSfxTrigger,
  sceneShots,
  sceneTemporalShots,
  temporalShotTimeline,
  sceneDurationMs,
  shotBeatClass,
  shotEditorId,
  fieldText,
  fieldNumber,
  fieldTextarea,
  fieldSelect,
  fieldCheckbox,
  storedValue,
  assetStatusLabel,
  assetTypeLabel,
  cameraClassName,
} from "./utils.js";
import { renderVoiceCatalogDatalist, taskVideoUrl } from "./api.js";
import { stopTemporalPreview } from "./timeline.js";
import { renderStoryboardReviewCanvas } from "./components/review/canvas.js";

export function render() {
  stopTemporalPreview();
  const previousContent = appRoot.querySelector?.(".content");
  const previousShell = appRoot.querySelector?.(".shell");
  const shouldRestoreSettingsScroll =
    previousShell?.dataset?.activeTab === "settings" &&
    state.activeTab === "settings" &&
    previousContent;
  if (shouldRestoreSettingsScroll) {
    const previousSettingsBody = appRoot.querySelector?.("#settingsSection .window-body");
    state.settingsScrollTop = previousContent.scrollTop;
    state.settingsBodyScrollTop = previousSettingsBody?.scrollTop || 0;
  }
  // Phase C: preserve focus, text selection and scroll positions across the
  // full re-render so typing in dense forms is never interrupted.
  const active = document.activeElement;
  const focusId = active && active.id ? active.id : "";
  const focusSelection =
    focusId && typeof active.selectionStart === "number"
      ? { start: active.selectionStart, end: active.selectionEnd }
      : null;
  const scrollSelectors = ".content .window-body, .sidebar-scroll";
  const previousScrollables = previousContent
    ? [
        [previousContent, previousContent.scrollTop],
        ...Array.from(appRoot.querySelectorAll(scrollSelectors)).map((el) => [el, el.scrollTop]),
      ]
    : [];
  appRoot.innerHTML = renderShell();
  renderVoiceCatalogDatalist();
  // restore scroll positions (matched by structural order; counts are
  // template-driven so they stay stable between renders of the same view)
  if (!shouldRestoreSettingsScroll && previousScrollables.length) {
    const newScrollables = [
      appRoot.querySelector(".content"),
      ...Array.from(appRoot.querySelectorAll(scrollSelectors)),
    ];
    previousScrollables.forEach(([el, top], index) => {
      const target = newScrollables[index];
      if (target && top) target.scrollTop = top;
    });
  }
  if (focusId) {
    const restored = document.getElementById(focusId);
    if (restored) {
      try {
        restored.focus({ preventScroll: true });
        if (focusSelection && typeof restored.setSelectionRange === "function") {
          restored.setSelectionRange(focusSelection.start, focusSelection.end);
        }
      } catch {
        /* element type changed or not focusable anymore — ignore */
      }
    }
  }
  if (shouldRestoreSettingsScroll) {
    requestAnimationFrame(() => {
      const content = document.querySelector(".content");
      const settingsBody = document.querySelector("#settingsSection .window-body");
      if (content) content.scrollTop = state.settingsScrollTop || 0;
      if (settingsBody) settingsBody.scrollTop = state.settingsBodyScrollTop || 0;
    });
  }
}

export function renderShell() {
  const project = state.project;
  return `
    <div class="shell" data-active-tab="${h(state.activeTab)}">
      ${renderSidebar()}
      <section class="workspace" data-active-tab="${h(state.activeTab)}">
        ${renderTopbar(project)}
        ${renderTabs()}
        <div class="content">${renderActiveView(project)}</div>
        <div class="bottom-timeline">${project ? renderTimelinePanel(project) : ""}</div>
      </section>
    </div>
    <div id="toast" class="toast ${state.toast ? `is-visible ${h(state.toast.type)}` : ""}">${state.toast ? h(state.toast.message) : ""}</div>
    ${renderModal()}
  `;
}

export function renderModal() {
  if (!state.modal) return "";
  const { type, data } = state.modal;
  let body = "";
  if (type === "style-picker") body = renderStylePickerModal(data || {});
  else if (type === "asset-add") body = renderAssetAddModal(data || {});
  else return "";
  return `
    <div class="modal-overlay" data-action="modal-close-overlay">
      <div class="modal-shell" data-modal-stop role="dialog" aria-modal="true" aria-labelledby="modal-title">
        ${body}
      </div>
    </div>
  `;
}

export function renderSidebar() {
  const project = state.project;
  const scenes = project ? project.scenes || [] : [];
  return `
    <aside class="sidebar">
      <div class="sidebar-head">
        <h1 class="app-title">漫剧工作台</h1>
        <button class="primary-button sidebar-create-btn" type="button" data-action="create-project">+ 新建项目</button>
      </div>
      <div class="sidebar-scroll">
        <section class="window-pane sidebar-projects">
          <div class="window-head">项目 <small>${state.projects.length}</small></div>
          <div class="window-body project-list">
            ${renderProjectList()}
          </div>
        </section>
        ${
          project
            ? `
        <section class="window-pane sidebar-scenes">
          <div class="window-head">场景 <small>${scenes.length} 镜</small></div>
          <div class="window-body card-list">${scenes.map(renderSceneMiniNav).join("")}</div>
        </section>
        `
            : ""
        }
        <section class="window-pane sidebar-status">
          <div class="window-head">状态</div>
          <div class="window-body">
            <div class="status-pill ${state.busy ? "warn" : "ok"}">${h(state.busy ? state.busyText || "处理中" : "空闲")}</div>
            <button type="button" class="ghost-button" style="margin-top:6px;width:100%" data-action="refresh-all">刷新</button>
          </div>
        </section>
      </div>
    </aside>
  `;
}

function renderSceneMiniNav(scene) {
  const order = Number(scene.order);
  const active = order === Number(state.selectedSceneOrder) ? "is-active" : "";
  const assets = scene.assets || {};
  const hasImage = Boolean(assets.image_path);
  const hasVideo = Boolean(assets.video_path);
  const statusDot = hasVideo ? "dot-ok" : hasImage ? "dot-warn" : "dot-empty";
  return `
    <button class="scene-mini-nav ${active}" type="button" data-action="select-scene" data-scene-order="${h(order)}">
      <span class="scene-dot ${statusDot}"></span>
      <span class="scene-mini-title">#${order} ${h((scene.title || "").slice(0, 8))}</span>
    </button>
  `;
}

export function renderProjectList() {
  if (!state.projects.length) {
    return `<div class="empty-state">暂无项目，先在下方创建一个。</div>`;
  }
  return state.projects
    .map((project) => {
      const active = project.project_id === state.currentProjectId ? "is-active" : "";
      const summary = project.summary || {};
      return `
        <div class="project-item ${active}">
          <button class="project-main" type="button" data-action="select-project" data-project-id="${h(project.project_id)}">
            <div class="item-title">${h(project.title || project.project_id)}</div>
            <div class="item-meta">${h(project.project_id)} · ${summary.total_scenes || (project.scenes || []).length || 0} 镜</div>
          </button>
          <button class="project-delete-button" type="button" data-action="delete-project" data-project-id="${h(project.project_id)}" title="删除项目">删除</button>
        </div>
      `;
    })
    .join("");
}

export function renderTopbar(project) {
  const summary = project?.summary || {};
  const output = project?.output || {};
  const runtime = project?.runtime || {};
  const finalUrl = output.final_video_url || "#";
  const subtitlesUrl = output.subtitles_url || "#";
  return `
    <header class="topbar">
      <div>
        <h2 class="project-title">${h(project?.title || "请选择项目")}</h2>
        <p class="project-meta">${h(project?.project_id || "本地文件工作流 MVP")}</p>
        <div class="summary-strip">
          <span class="summary-chip">分镜 ${summary.completed_scenes || 0}/${summary.total_scenes || 0}</span>
          <span class="summary-chip">素材 ${summary.asset_totals?.image || 0}/${summary.asset_totals?.audio || 0}/${summary.asset_totals?.video || 0}</span>
          <span class="summary-chip">角色 ${summary.total_characters || 0}</span>
          ${renderContinuitySummaryChip(project)}
          ${renderVideoProviderStatus(project)}
          <span class="status-pill ${statusClass(runtime.status)}">${h(runtime.stage || runtime.status || "draft")} ${runtime.progress ?? 0}%</span>
        </div>
      </div>
      <div class="toolbar">
        <button class="ghost-button" type="button" data-action="refresh-project">刷新</button>
        <button class="ghost-button" type="button" data-action="save-project">保存项目</button>
        <button class="primary-button" type="button" data-action="build-project">生成整集</button>
        <button class="ghost-button" type="button" data-action="export-project">导出成片</button>
        ${project?.project_id ? `<button class="danger-button" type="button" data-action="delete-project" data-project-id="${h(project.project_id)}">删除项目</button>` : ""}
        <a class="button-link" href="${h(finalUrl)}" target="_blank" rel="noreferrer" ${finalUrl === "#" ? 'aria-disabled="true"' : ""}>打开成片</a>
        <a class="button-link" href="${h(subtitlesUrl)}" target="_blank" rel="noreferrer" ${subtitlesUrl === "#" ? 'aria-disabled="true"' : ""}>字幕</a>
      </div>
    </header>
  `;
}

function renderVideoProviderStatus(project) {
  if (!project) return "";
  if (state.videoProviderStatusLoading) {
    return `<span class="summary-chip provider-status is-loading">Video provider: checking</span>`;
  }
  if (state.videoProviderStatusError) {
    return `<span class="summary-chip provider-status is-error" title="${h(state.videoProviderStatusError)}">Video provider: error</span>`;
  }
  const status = state.videoProviderStatus || {};
  const provider = status.provider || {};
  const configuredCount = Number(status.configured_count || 0);
  const missing = Array.isArray(status.missing_env) ? status.missing_env.length : 0;
  const readiness =
    status.readiness && typeof status.readiness === "object" ? status.readiness : {};
  const blocking = Array.isArray(readiness.blocking_env) ? readiness.blocking_env.length : missing;
  const label = provider.label || provider.id || project.settings?.video_provider || "auto";
  const backend = provider.backend || "unknown";
  const ready = readiness.ready === true || backend === "local";
  const readinessLabel = ready ? "ready" : `${blocking} missing`;
  return `<span class="summary-chip provider-status ${ready ? "is-ready" : "is-missing"}" title="${h(`${configuredCount} configured, ${missing} optional missing, ${blocking} blocking`)}">Video: ${h(label)} / ${h(backend)} / ${h(readinessLabel)}</span>`;
}

function projectContinuityLedger(project) {
  const ledger = project?.continuity_ledger;
  return ledger && typeof ledger === "object" ? ledger : {};
}

function sceneGovernance(scene) {
  return scene?.governance && typeof scene.governance === "object" ? scene.governance : {};
}

function governanceStatus(scene) {
  return String(sceneGovernance(scene).status || "not_evaluated");
}

function governanceStatusClass(status) {
  const value = String(status || "not_evaluated");
  if (value === "pass") return "is-pass";
  if (value === "warn") return "is-warn";
  if (value === "fail") return "is-fail";
  return "is-not-evaluated";
}

function governanceStatusLabel(status) {
  const value = String(status || "not_evaluated");
  if (value === "pass") return "Continuity pass";
  if (value === "warn") return "Continuity warn";
  if (value === "fail") return "Continuity fail";
  return "Continuity not evaluated";
}

function renderContinuitySummaryChip(project) {
  const counts = projectContinuityLedger(project).status_counts || {};
  const fail = Number(counts.fail || 0);
  const warn = Number(counts.warn || 0);
  const pass = Number(counts.pass || 0);
  const pending = Number(counts.not_evaluated || 0);
  const status = fail ? "is-fail" : warn ? "is-warn" : pending ? "is-not-evaluated" : "is-pass";
  return `<span class="summary-chip continuity-chip ${status}" title="${h(`pass ${pass}, warn ${warn}, fail ${fail}, not evaluated ${pending}`)}">Continuity ${h(pass)}/${h(warn)}/${h(fail)}</span>`;
}

export function renderTabs() {
  return `<nav class="tabbar" aria-label="工作区导航">${tabs
    .map(
      ([key, label, section]) =>
        `<button type="button" class="${state.activeTab === key ? "is-active" : ""}" data-action="switch-tab" data-tab="${h(key)}" data-jump-section="${h(section)}">${h(label)}</button>`
    )
    .join("")}</nav>`;
}

export function renderActiveView(project) {
  if (!project) {
    return `<section class="panel"><div class="panel-head">未选择项目</div><div class="panel-body"><div class="empty-state">请选择左侧项目，或创建一个新项目。</div></div></section>`;
  }
  if (state.activeTab === "plan") return renderPlanView(project);
  if (state.activeTab === "assets") return renderAssetsView(project);
  if (state.activeTab === "storyboard") return renderStoryboardView(project);
  if (state.activeTab === "review") return renderWorkbenchView(project);
  if (state.activeTab === "produce") return renderProduceView(project);
  if (state.activeTab === "tasks") return renderTasksView();
  if (state.activeTab === "settings") return renderSettingsView(project);
  return renderPlanView(project);
}

// ─── Phase ① Plan View ───────────────────────────────────────────────────────
export function renderPlanView(project) {
  const scenes = timelineSceneItems(project);
  return `
    <div class="plan-layout">
      <div class="plan-main">
        <section class="window-pane">
          <div class="window-head">故事 / 剧本 <small>${(project.story_text || "").length} 字</small></div>
          <div class="window-body">
            ${fieldTextarea("scriptTextInput", "", project.story_text || "", 10, "粘贴故事大纲或完整剧本...")}
            <div class="form-grid" style="margin-top:10px">
              ${fieldSelect("scriptPlannerInput", "拆解器", planners, project.settings?.planner || "auto")}
              ${fieldNumber("scriptMaxScenesInput", "分镜数", project.settings?.scene_count || 5, 'min="1" max="24" step="1"')}
            </div>
            <div class="row-actions" style="margin-top:10px">
              <button class="primary-button" type="button" data-action="preview-script">AI 拆解分镜</button>
              <button class="ghost-button" type="button" data-action="apply-script">应用到项目</button>
              <button class="ghost-button" type="button" data-action="save-project">保存</button>
            </div>
            <input type="hidden" id="scriptTitleInput" value="${h(project.title || "")}">
            <input type="hidden" id="scriptHintInput" value="">
          </div>
        </section>
        ${state.scriptPreview ? renderScriptPreview(state.scriptPreview) : ""}
        <section class="window-pane">
          <div class="window-head">当前分镜 <small>${scenes.length} 镜</small></div>
          <div class="window-body">
            <div class="scene-preview-strip">${scenes.map(renderSceneMiniCard).join("")}</div>
          </div>
        </section>
      </div>
      <div class="plan-side">
        <section class="window-pane">
          <div class="window-head">项目设置</div>
          <div class="window-body section-stack">
            ${fieldText("projectTitleInput", "标题", project.title || "")}
            <div class="style-preview">
              <span class="muted">风格：</span>
              <button class="ghost-button" type="button" data-action="open-style-picker">${h(project.style_id || "默认")}</button>
            </div>
          </div>
        </section>
        <section class="window-pane">
          <div class="window-head">新建项目</div>
          <div class="window-body section-stack">
            ${fieldText("newProjectTitle", "标题", "", "新项目名称")}
            ${fieldTextarea("newProjectStory", "故事", "", 4, "粘贴故事")}
            <button class="primary-button" type="button" data-action="create-project">创建</button>
          </div>
        </section>
      </div>
    </div>
  `;
}

// ─── Phase ③ Storyboard View ─────────────────────────────────────────────────
export function renderStoryboardView(project) {
  const scene = selectedScene(project);
  return `
    <div class="storyboard-layout">
      <div class="storyboard-preview-area">
        ${scene ? renderScenePreviewLarge(scene) : `<div class="empty-state">请选择一个分镜</div>`}
        <div class="scene-thumb-strip">
          ${(project.scenes || []).map(renderSceneThumbCard).join("")}
        </div>
      </div>
      <div class="storyboard-editor-area">
        ${scene ? renderSceneEditor(scene, project) : ""}
      </div>
    </div>
  `;
}

function renderScenePreviewLarge(scene) {
  const assets = scene.assets || {};
  const media = assets.video_url
    ? `<video src="${h(assets.video_url)}" controls playsinline class="preview-video"></video>`
    : assets.image_url
      ? `<img src="${h(assets.image_url)}" alt="" class="preview-image">`
      : `<div class="preview-placeholder">暂无画面<br><small>点击"重绘图"生成关键帧</small></div>`;
  return `
    <div class="large-preview">
      ${media}
      <div class="preview-info">
        <span class="preview-title">#${h(scene.order)} ${h(scene.title || "")}</span>
        <span class="preview-meta">${formatSeconds(scene.duration_seconds)} · ${h(scene.camera_movement || "")} · ${h(scene.emotion || "")}</span>
      </div>
    </div>
  `;
}

function renderSceneThumbCard(scene) {
  const active = Number(scene.order) === Number(state.selectedSceneOrder) ? "is-active" : "";
  const assets = scene.assets || {};
  const thumb = assets.image_url
    ? `<img src="${h(assets.image_url)}" alt="">`
    : `<span class="thumb-empty">${h(scene.order)}</span>`;
  return `
    <button class="scene-thumb ${active}" type="button" data-action="select-scene" data-scene-order="${h(scene.order)}">
      <div class="scene-thumb-img">${thumb}</div>
      <div class="scene-thumb-label">#${h(scene.order)}</div>
    </button>
  `;
}

// ─── Task Center (C1) ────────────────────────────────────────────────────────
// 数据模型以 backend/task_store.py 的 snapshot() 为准。注意它与设计稿 C1 的
// 假设不同：后端一个 task = 一条完整渲染流水线（story + planner + scene_count），
// 没有「任务类型 / 关联对象」字段，因此表格列按真实字段组织。
// 生命周期：status queued → running → succeeded|failed
//           stage  queued → starting → planning|rendering|assembling → done|failed

const TASK_STATUS_META = {
  queued: { label: "排队", pill: "" },
  running: { label: "运行中", pill: "" },
  succeeded: { label: "成功", pill: "ok" },
  failed: { label: "失败", pill: "danger" },
};

const TASK_STAGE_LABEL = {
  queued: "排队",
  starting: "准备",
  running: "运行",
  planning: "规划",
  rendering: "渲染",
  assembling: "合成",
  done: "完成",
  failed: "失败",
};

function taskStatusMeta(status) {
  return TASK_STATUS_META[status] || { label: h(status || "未知"), pill: "" };
}

function taskProgressValue(task) {
  const raw = Number(task?.progress);
  if (!Number.isFinite(raw)) return 0;
  return Math.max(0, Math.min(100, Math.round(raw)));
}

function taskDuration(task) {
  const start = Date.parse(task?.created_at || "");
  const end = Date.parse(task?.updated_at || "");
  if (!Number.isFinite(start)) return "—";
  const stop = Number.isFinite(end) ? end : Date.now();
  const seconds = Math.max(0, Math.round((stop - start) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

function taskTime(value) {
  const parsed = Date.parse(value || "");
  if (!Number.isFinite(parsed)) return "—";
  return new Date(parsed).toLocaleTimeString("zh-CN", { hour12: false });
}

function filteredTasks() {
  const keyword = String(state.taskKeyword || "").trim().toLowerCase();
  return (state.tasks || []).filter((task) => {
    if (state.taskFilter !== "all" && task.status !== state.taskFilter) return false;
    if (!keyword) return true;
    const haystack = [task.id, task.stage, task.message, task.planner]
      .map((item) => String(item || "").toLowerCase())
      .join(" ");
    return haystack.includes(keyword);
  });
}

export function renderTasksView() {
  return `
    <div class="tasks-layout">
      <div id="tasksStats" class="tasks-stats">${renderTasksStats()}</div>
      <div class="window-pane tasks-toolbar">
        <div class="window-body row-actions">
          <div class="tasks-filter-group">
            ${[
              ["all", "全部"],
              ["queued", "排队"],
              ["running", "运行中"],
              ["succeeded", "成功"],
              ["failed", "失败"],
            ]
              .map(
                ([key, label]) =>
                  `<button type="button" class="ghost-button tasks-filter ${
                    state.taskFilter === key ? "is-active" : ""
                  }" data-action="task-filter" data-filter="${h(key)}">${h(label)}</button>`
              )
              .join("")}
          </div>
          <input
            id="taskKeywordInput"
            class="field-text tasks-search"
            type="search"
            placeholder="搜索任务 ID / 阶段 / 规划器…"
            value="${h(state.taskKeyword || "")}"
            data-action="task-search"
          />
          <span class="spacer"></span>
          <span id="tasksSyncHint" class="muted fs11">${
            state.tasksLoading ? "同步中…" : state.tasksError ? "同步失败" : `已同步 ${taskTime(state.tasksLastSync)}`
          }</span>
          <button class="ghost-button" type="button" data-action="refresh-tasks">刷新</button>
        </div>
      </div>
      <div class="tasks-body">
        <div class="window-pane tasks-list-pane">
          <div class="window-head">任务列表<div class="spacer"></div><small>轮询 3s · 局部刷新</small></div>
          <div class="window-body tasks-list-body">
            ${
              state.tasksError
                ? `<div class="status-pill danger">加载失败：${h(state.tasksError)}</div>`
                : ""
            }
            <table class="mini-table tasks-table">
              <thead>
                <tr>
                  <th>任务 ID</th><th>状态</th><th style="width:120px">进度</th>
                  <th>阶段</th><th>场景</th><th>创建</th><th>耗时</th><th style="width:150px">操作</th>
                </tr>
              </thead>
              <tbody id="tasksTableBody">${renderTasksRows()}</tbody>
            </table>
          </div>
        </div>
        <div id="tasksDetail" class="window-pane tasks-detail-pane">${renderTasksDetail()}</div>
      </div>
    </div>
  `;
}

export function renderTasksStats() {
  const list = state.tasks || [];
  const count = (status) => list.filter((task) => task.status === status).length;
  const cards = [
    ["排队", count("queued"), ""],
    ["运行中", count("running"), ""],
    ["成功", count("succeeded"), "ok"],
    ["失败", count("failed"), "danger"],
  ];
  return cards
    .map(
      ([label, value, tone]) => `
        <div class="tasks-stat">
          <span class="tasks-stat-label">${h(label)}</span>
          <span class="tasks-stat-value ${tone ? `is-${tone}` : ""}">${value}</span>
        </div>`
    )
    .join("");
}

export function renderTasksRows() {
  const rows = filteredTasks();
  if (!rows.length) {
    return `<tr><td colspan="8" class="muted" style="padding:16px 6px">${
      state.tasks.length ? "没有匹配的任务" : "暂无任务"
    }</td></tr>`;
  }
  return rows
    .map((task) => {
      const meta = taskStatusMeta(task.status);
      const progress = taskProgressValue(task);
      const selected = state.selectedTaskId === task.id;
      const hasVideo = Boolean(task.final_video);
      return `
        <tr class="${selected ? "is-selected" : ""}" data-action="select-task" data-task-id="${h(task.id)}">
          <td class="mono">${h(task.id)}</td>
          <td><span class="status-pill ${meta.pill}">${h(meta.label)}</span></td>
          <td>
            <div class="tasks-progress"><div class="tasks-progress-fill" style="width:${progress}%"></div></div>
            <span class="fs11 muted">${progress}%</span>
          </td>
          <td>${h(TASK_STAGE_LABEL[task.stage] || task.stage || "—")}</td>
          <td>${h(task.scene_count ?? "—")}</td>
          <td class="fs11 muted">${h(taskTime(task.created_at))}</td>
          <td class="fs11 muted">${h(taskDuration(task))}</td>
          <td>
            <div class="row-actions">
              <button class="ghost-button mini" type="button" data-action="task-detail" data-task-id="${h(task.id)}">详情</button>
              ${
                hasVideo
                  ? `<a class="ghost-button mini" href="${h(taskVideoUrl(task.id))}" target="_blank" rel="noopener">视频</a>`
                  : `<button class="ghost-button mini" type="button" disabled title="任务完成后可下载成片">视频</button>`
              }
              ${
                TASK_CAPABILITIES.cancel
                  ? `<button class="ghost-button mini" type="button" data-action="task-cancel" data-task-id="${h(task.id)}">取消</button>`
                  : `<button class="ghost-button mini" type="button" disabled title="后端未提供取消端点（tasks.py 仅有只读 + WS）">取消</button>`
              }
            </div>
          </td>
        </tr>`;
    })
    .join("");
}

export function renderTasksDetail() {
  const taskId = state.selectedTaskId;
  const detail = state.selectedTaskDetail;
  if (!taskId) {
    return `
      <div class="window-head">任务详情</div>
      <div class="window-body">
        <p class="muted">点击左侧任意任务查看详情、产物与日志。</p>
      </div>`;
  }
  if (!detail) {
    return `
      <div class="window-head">任务详情<div class="spacer"></div><small class="mono">${h(taskId)}</small></div>
      <div class="window-body"><p class="muted">加载中…</p></div>`;
  }
  const logs = Array.isArray(detail.logs) ? detail.logs : [];
  const files = Array.isArray(state.selectedTaskFiles) ? state.selectedTaskFiles : [];
  return `
    <div class="window-head">任务详情<div class="spacer"></div><small class="mono">${h(detail.id || taskId)}</small></div>
    <div class="window-body tasks-detail-body">
      <div class="tasks-detail-section">
        <div class="tasks-kv"><span class="muted">状态</span><b>${h(taskStatusMeta(detail.status).label)}</b></div>
        <div class="tasks-kv"><span class="muted">阶段</span><b>${h(TASK_STAGE_LABEL[detail.stage] || detail.stage || "—")}</b></div>
        <div class="tasks-kv"><span class="muted">进度</span><b>${taskProgressValue(detail)}%</b></div>
        <div class="tasks-kv"><span class="muted">场景数</span><b>${h(detail.scene_count ?? "—")}</b></div>
        <div class="tasks-kv"><span class="muted">规划器</span><b>${h(detail.planner || "—")}</b></div>
        <div class="tasks-kv"><span class="muted">关键帧</span><b>${h(detail.keyframe_provider || "—")}</b></div>
        <div class="tasks-kv"><span class="muted">视频</span><b>${h(detail.video_provider || "—")}</b></div>
        <div class="tasks-kv"><span class="muted">粒度</span><b>${h(detail.video_render_granularity || "—")}</b></div>
        <div class="tasks-kv"><span class="muted">配音</span><b>${h(detail.voice_provider || "—")}</b></div>
        <div class="tasks-kv"><span class="muted">耗时</span><b>${h(taskDuration(detail))}</b></div>
      </div>
      ${
        detail.error
          ? `<div class="status-pill danger" style="margin:8px 0">${h(String(detail.error))}</div>`
          : ""
      }
      <div class="tasks-detail-section">
        <div class="tasks-detail-title">产物 · GET /files · /video</div>
        ${
          detail.final_video
            ? `<a class="primary-button mini" href="${h(taskVideoUrl(detail.id))}" target="_blank" rel="noopener">下载成片</a>`
            : `<span class="muted fs11">任务尚未产出成片</span>`
        }
        ${
          files.length
            ? `<table class="mini-table"><tbody>${files
                .map(
                  (file) => `<tr>
                    <td class="mono fs11">${h(file.name)}</td>
                    <td class="fs11 muted">${h(file.size ?? "")}</td>
                    <td><a class="ghost-button mini" href="${h(file.url)}" target="_blank" rel="noopener">下载</a></td>
                  </tr>`
                )
                .join("")}</tbody></table>`
            : `<p class="muted fs11">暂无产物文件</p>`
        }
      </div>
      <div class="tasks-detail-section">
        <div class="tasks-detail-title">日志 · 最近 ${logs.length} 条</div>
        <div class="tasks-log">${
          logs.length
            ? logs.map((line) => `<div>${h(line)}</div>`).join("")
            : `<span class="muted fs11">暂无日志</span>`
        }</div>
      </div>
    </div>`;
}

// ─── Phase ④ Produce View ────────────────────────────────────────────────────
export function renderProduceView(project) {
  const scenes = timelineSceneItems(project);
  const totalScenes = scenes.length;
  const withImage = scenes.filter((s) => s.assets?.image_path).length;
  const withAudio = scenes.filter((s) => s.assets?.audio_path).length;
  const withVideo = scenes.filter((s) => s.assets?.video_path).length;
  return `
    <div class="produce-layout">
      <div class="produce-header">
        <div class="produce-progress">
          <div class="progress-item"><span class="progress-label">关键帧</span><span class="progress-value">${withImage}/${totalScenes}</span></div>
          <div class="progress-item"><span class="progress-label">配音</span><span class="progress-value">${withAudio}/${totalScenes}</span></div>
          <div class="progress-item"><span class="progress-label">视频</span><span class="progress-value">${withVideo}/${totalScenes}</span></div>
        </div>
        <div class="produce-actions">
          <button class="primary-button" type="button" data-action="build-project">▶ 批量生成全部</button>
          <button class="ghost-button" type="button" data-action="export-project">导出成片</button>
          <button class="ghost-button" type="button" data-action="export-otio">导出 OTIO</button>
        </div>
      </div>
      <div class="produce-grid">
        ${scenes.map(renderProduceCard).join("")}
      </div>
    </div>
  `;
}

function renderProduceCard(scene) {
  const assets = scene.assets || {};
  const hasImage = Boolean(assets.image_path);
  const hasAudio = Boolean(assets.audio_path);
  const hasVideo = Boolean(assets.video_path);
  const status = hasVideo ? "complete" : hasImage ? "partial" : "empty";
  const thumb = assets.image_url
    ? `<img src="${h(assets.image_url)}" alt="">`
    : `<div class="produce-thumb-empty">${h(scene.order)}</div>`;
  return `
    <div class="produce-card produce-${status}">
      <div class="produce-card-thumb">${thumb}</div>
      <div class="produce-card-body">
        <div class="produce-card-title">#${h(scene.order)} ${h((scene.title || "").slice(0, 10))}</div>
        ${renderGenerationBadge(scene)}
        <div class="produce-card-status">
          <span class="dot ${hasImage ? "dot-ok" : "dot-empty"}"></span>图
          <span class="dot ${hasAudio ? "dot-ok" : "dot-empty"}"></span>音
          <span class="dot ${hasVideo ? "dot-ok" : "dot-empty"}"></span>视频
        </div>
      </div>
      <div class="produce-card-actions">
        <button class="ghost-button small" type="button" data-action="rerender-video" data-scene-order="${h(scene.order)}">生成</button>
      </div>
    </div>
  `;
}

function renderSceneMiniCard(scene) {
  return `
    <button class="scene-card" type="button" data-action="select-scene" data-scene-order="${h(scene.order)}">
      <div class="item-title">#${h(scene.order)} ${h(scene.title || "未命名分镜")}</div>
      <div class="item-meta">${formatSeconds(scene.duration_seconds)} · ${h(scene.speaker || "角色")} · ${h(scene.camera_movement || "镜头")}</div>
    </button>
  `;
}

export function renderSettingsView(project) {
  const settings = project.settings || {};
  const subtitle = settings.subtitle_style || {};
  const audio = settings.audio_style || {};
  const storyText = String(project.story_text || "");
  const storyWarning = looksGarbledScriptText(storyText)
    ? `<div class="preview-note">当前故事文本已经损坏成问号了。不要直接保存这段文本；请重新从原始来源粘贴，或先从分镜重建后再整理。</div>`
    : "";
  return `
    <div class="split-grid">
      <section id="projectSettingsSection" class="window-pane">
        <div class="window-head">项目设置</div>
        <div class="window-body section-stack">
          ${storyWarning}
          <div class="form-grid">
            ${fieldText("projectTitleInput", "标题", project.title || "")}
            ${fieldSelect("projectPlannerInput", "剧本拆解", planners, settings.planner || "auto")}
            ${fieldSelect(
              "projectKeyframeInput",
              "关键帧引擎",
              [
                ["auto", "自动"],
                ["local", "本地占位"],
                ["comfyui", "ComfyUI"],
              ],
              settings.keyframe_provider || "auto"
            )}
            ${fieldSelect(
              "projectVoiceInput",
              "配音引擎",
              [
                ["auto", "自动"],
                ["edge", "Edge"],
                ["local", "本地"],
                ["silent", "静音"],
              ],
              settings.voice_provider || "auto"
            )}
            ${fieldNumber("projectSceneCountInput", "分镜数", settings.scene_count || (project.scenes || []).length || 5, 'min="1" max="24" step="1"')}
            ${fieldText("projectGlobalStyleInput", "美术风格", settings.global_style || "")}
            ${fieldTextarea("projectStoryInput", "故事 / 原始剧本", project.story_text || "", 10)}
          </div>
          <div class="row-actions">
            <button class="primary-button" type="button" data-action="save-project">保存项目设置</button>
            <button class="ghost-button" type="button" data-action="refresh-project">刷新项目</button>
          </div>
        </div>
      </section>
      <section class="window-pane">
        <div class="window-head">字幕与音频后期</div>
        <div class="window-body section-stack">
          <div class="form-grid three">
            ${fieldText("subtitleFontNameInput", "字幕字体", subtitle.font_name || "Microsoft YaHei")}
            ${fieldNumber("subtitleFontSizeInput", "字号", subtitle.font_size ?? 34, 'min="12" max="96" step="1"')}
            ${fieldNumber("subtitleMarginVInput", "底边距", subtitle.margin_v ?? 120, 'min="0" max="600" step="1"')}
            ${fieldNumber("subtitleOutlineInput", "描边", subtitle.outline ?? 2, 'min="0" max="8" step="1"')}
            ${fieldNumber("subtitleShadowInput", "阴影", subtitle.shadow ?? 0, 'min="0" max="8" step="1"')}
            ${fieldSelect(
              "subtitleAlignmentInput",
              "位置",
              [
                ["2", "底部居中"],
                ["8", "顶部居中"],
                ["5", "画面居中"],
              ],
              subtitle.alignment ?? 2
            )}
          </div>
          <div class="toggle-row">
            ${fieldCheckbox("subtitleSpeakerInput", "显示说话人", subtitle.show_speaker !== false)}
            ${fieldCheckbox("subtitleBurnInput", "烧录字幕", subtitle.burn_in !== false)}
          </div>
          <div class="form-grid three">
            ${fieldNumber("audioLufsInput", "Target LUFS", audio.master_lufs ?? -16, 'min="-30" max="-6" step="0.1"')}
            ${fieldNumber("audioTruePeakInput", "True Peak", audio.true_peak ?? -1.5, 'min="-6" max="0" step="0.1"')}
            ${fieldNumber("audioLimiterInput", "Limiter", audio.limiter_level ?? 0.98, 'min="0.5" max="0.999" step="0.001"')}
            ${fieldNumber("audioBgmGainInput", "BGM Gain", audio.bgm_gain_db ?? -18, 'min="-60" max="0" step="0.1"')}
            ${fieldNumber("audioDuckThresholdInput", "Duck Threshold", audio.duck_threshold ?? 0.08, 'min="0.01" max="1" step="0.01"')}
            ${fieldNumber("audioDuckRatioInput", "Duck Ratio", audio.duck_ratio ?? 8, 'min="1" max="20" step="0.1"')}
            ${fieldText("audioBgmPathInput", "BGM 路径", audio.bgm_path || "")}
          </div>
          <button class="primary-button" type="button" data-action="save-project">保存字幕 / 音频</button>
        </div>
      </section>
    </div>
    ${renderLlmConfigSection()}
    ${renderEnhanceSection()}
  `;
}

function renderEnhanceSection() {
  return `
    <section id="enhanceSection" class="window-pane" style="margin-top:16px">
      <div class="window-head">ComfyUI / TTS 引擎 <small>可选增强层，不进入主链路</small></div>
      <div class="window-body section-stack">
        ${renderComfyUIStatus()}
        <div class="form-grid">
          ${fieldText("comfyuiBaseUrlInput", "ComfyUI URL", storedValue("comfyuiBaseUrl", "http://127.0.0.1:8188"))}
        </div>
        <div class="row-actions">
          <button class="primary-button" type="button" data-action="open-comfyui">打开 ComfyUI</button>
          <button class="ghost-button" type="button" data-action="save-comfyui-url">保存地址</button>
          <button class="ghost-button" type="button" data-action="check-comfyui">检测连接</button>
        </div>
        <div class="form-grid">
          ${fieldText("providerCosyVoiceInput", "OmniVoice URL", state.ttsProviders.cosyvoice || "")}
          ${fieldText("providerGptSovitsInput", "GPT-SoVITS URL", state.ttsProviders.gpt_sovits || "")}
          ${fieldText("providerFishInput", "Fish Speech URL", state.ttsProviders.fish || "")}
          ${fieldText("providerIndexTtsInput", "IndexTTS2 URL", state.ttsProviders.indextts || "")}
        </div>
        <div class="row-actions">
          <button class="primary-button" type="button" data-action="save-tts-providers">保存引擎地址</button>
        </div>
      </div>
    </section>
  `;
}

function renderLlmConfigSection() {
  const llm = state.llmSettings;
  const testing = state.llmTesting;
  const testResult = state.llmTestResult;
  const presets = llm?.presets || [];
  const cfg = llm?.settings || {};

  const presetButtons = presets
    .map(
      (p, i) =>
        `<button class="ghost-button" type="button" data-action="llm-preset" data-preset-idx="${i}" style="font-size:12px;padding:4px 10px">${h(p.label)}</button>`
    )
    .join(" ");

  const testBadge = !testResult
    ? ""
    : testResult.ok
      ? `<span class="asset-readiness is-ready" style="font-size:12px">✓ 连接成功 (${h(testResult.model || cfg.model)})</span>`
      : `<span class="asset-readiness is-blocked" style="font-size:12px">✗ ${h(testResult.error || "连接失败")}</span>`;

  return `
    <section id="settingsSection" class="window-pane" style="margin-top:16px">
      <div class="window-head">LLM API 配置 <small>用于 AI 剧本拆解与导演解读</small></div>
      <div class="window-body section-stack">
        <div class="form-grid">
          ${apiConfigInput("llmApiKeyInput", "API Key", cfg.api_key_masked || "", "sk-...", "password")}
          ${apiConfigInput("llmBaseUrlInput", "Base URL", cfg.base_url || "https://api.deepseek.com/v1", "https://api.openai.com/v1")}
          ${apiConfigInput("llmModelInput", "Model", cfg.model || "deepseek-chat", "deepseek-chat")}
        </div>
        <div class="toggle-row">
          ${fieldCheckbox("llmJsonModeInput", "JSON Mode（结构化输出）", cfg.json_mode !== false)}
        </div>
        <div class="row-actions" style="flex-wrap:wrap;gap:6px">
          <span class="muted" style="font-size:12px;line-height:28px">快捷预设：</span>
          ${presetButtons}
        </div>
        <div class="row-actions">
          <button class="primary-button" type="button" data-action="save-llm-settings">保存配置</button>
          <button class="ghost-button" type="button" data-action="test-llm" ${testing ? "disabled" : ""}>
            ${testing ? "测试中..." : "测试连接"}
          </button>
          ${testBadge}
        </div>
        ${cfg.api_key_set === false ? `<div class="preview-note" style="color:var(--warn)">⚠ 尚未配置 API Key，LLM 相关功能将不可用</div>` : ""}
        ${renderApiProfileCards(cfg)}
        ${renderTaskOverridesSection(cfg, llm?.task_definitions || [])}
        ${renderLlmUsageSection()}
      </div>
    </section>
  `;
}

function apiConfigInput(id, label, value = "", placeholder = "", type = "text") {
  return `
    <label class="field">
      <span>${h(label)}</span>
      <input id="${h(id)}" type="${h(type)}" value="${h(value)}" placeholder="${h(placeholder)}">
    </label>
  `;
}

function renderApiProfileCards(cfg) {
  const cards = [
    {
      key: "language_model",
      title: "语言模型 API",
      desc: "文本改写、剧本拆解、导演解读等语言任务优先使用此配置；留空则继承上方默认 LLM。",
      modelPlaceholder: cfg.model || "deepseek-chat",
    },
    {
      key: "character_image",
      title: "角色图生成 API",
      desc: "为角色设定图、参考图生成预留的独立接口；留空则继承上方默认 LLM 配置。",
      modelPlaceholder: "image-model-or-compatible-model",
    },
  ];

  const overrides = cfg.task_overrides || {};
  const defaultBaseUrl = cfg.base_url || "https://api.openai.com/v1";

  return `
    <div class="api-profile-grid">
      ${cards.map((card) => renderApiProfileCard(card, overrides[card.key] || {}, defaultBaseUrl)).join("")}
    </div>
  `;
}

function renderApiProfileCard(card, override, defaultBaseUrl) {
  const apiKeySet = override.api_key_set === true;
  return `
    <section class="api-profile-card" data-api-profile="${h(card.key)}">
      <div class="api-profile-head">
        <div>
          <div class="item-title">${h(card.title)}</div>
          <div class="item-meta">${h(card.desc)}</div>
        </div>
        <span class="summary-chip">${apiKeySet ? "已设置 Key" : "继承默认"}</span>
      </div>
      <div class="form-grid three">
        ${apiConfigInput(`taskOvApiKey_${card.key}`, "API Key", override.api_key_masked || "", apiKeySet ? "••••••••(已设置)" : "留空则继承默认", "password")}
        ${apiConfigInput(`taskOvBaseUrl_${card.key}`, "Base URL", override.base_url || "", `留空则继承默认 (${defaultBaseUrl})`)}
        ${apiConfigInput(`taskOvModel_${card.key}`, "Model", override.model || "", card.modelPlaceholder)}
      </div>
    </section>
  `;
}

function renderTaskOverridesSection(cfg, taskDefs) {
  const overrides = cfg.task_overrides || {};
  const defaultBaseUrl = cfg.base_url || "";
  const defaultModel = cfg.model || "";
  const visibleProfileKeys = new Set(["language_model", "character_image"]);

  const taskCards = taskDefs
    .map((td) => {
      const key = td.key;
      if (visibleProfileKeys.has(key)) return "";
      const ov = overrides[key] || {};
      const enabled = overrides[key] != null;
      const ovBaseUrl = ov.base_url || "";
      const ovModel = ov.model || "";
      const ovKeyMasked = ov.api_key_masked || "";
      const ovKeySet = ov.api_key_set === true;

      return `
      <div class="task-override-card" style="border:1px solid var(--line-soft);border-radius:8px;padding:10px;margin-bottom:8px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          <label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-size:13px">
            <input type="checkbox" data-action="task-override-toggle" data-task-key="${h(key)}" ${enabled ? "checked" : ""} style="margin:0" />
            <strong>${h(td.label)}</strong>
          </label>
          <span class="muted" style="font-size:11px">${h(td.desc)}</span>
        </div>
        ${
          enabled
            ? `
          <div class="form-grid" style="grid-template-columns:1fr 1fr 1fr;gap:8px">
            <div>
              <label style="font-size:11px;color:var(--muted)">独立 API Key</label>
              <input type="password" id="taskOvApiKey_${h(key)}" value="${h(ovKeyMasked)}" placeholder="${ovKeySet ? "••••••••(已设置)" : "留空则继承默认"}" style="width:100%;font-size:12px" />
            </div>
            <div>
              <label style="font-size:11px;color:var(--muted)">独立 Base URL</label>
              <input type="text" id="taskOvBaseUrl_${h(key)}" value="${h(ovBaseUrl)}" placeholder="留空则继承默认 (${h(defaultBaseUrl)})" style="width:100%;font-size:12px" />
            </div>
            <div>
              <label style="font-size:11px;color:var(--muted)">独立 Model</label>
              <input type="text" id="taskOvModel_${h(key)}" value="${h(ovModel)}" placeholder="留空则继承默认 (${h(defaultModel)})" style="width:100%;font-size:12px" />
            </div>
          </div>
        `
            : `<div class="muted" style="font-size:12px">使用默认配置（${h(defaultModel)} @ ${h(defaultBaseUrl)}）</div>`
        }
      </div>
    `;
    })
    .join("");

  return `
    <details style="margin-top:12px">
      <summary style="cursor:pointer;font-size:13px;color:var(--muted)">
        🔧 任务级配置：为不同任务分别指定 LLM
      </summary>
      <div style="margin-top:8px">
        ${taskCards}
        <div class="muted" style="font-size:11px;margin-top:4px">
          勾选任务后可填写独立的 API Key / Base URL / Model。留空的字段会自动继承默认配置。
        </div>
      </div>
    </details>
  `;
}

function renderLlmUsageSection() {
  const usage = state.llmUsage;
  if (!usage || usage.total_calls === 0) {
    return `<div class="muted" style="font-size:12px;margin-top:8px">暂无 LLM 调用记录</div>`;
  }

  const byTaskEntries = Object.entries(usage.by_task || {});
  const byModelEntries = Object.entries(usage.by_model || {});
  const recent = usage.recent || [];

  const taskRows =
    byTaskEntries.length === 0
      ? ""
      : byTaskEntries
          .map(
            ([task, info]) =>
              `<tr><td>${h(task)}</td><td style="text-align:right">${info.calls}</td><td style="text-align:right">${(info.tokens || 0).toLocaleString()}</td></tr>`
          )
          .join("");

  const modelRows =
    byModelEntries.length === 0
      ? ""
      : byModelEntries
          .map(
            ([model, info]) =>
              `<tr><td>${h(model)}</td><td style="text-align:right">${info.calls}</td><td style="text-align:right">${(info.tokens || 0).toLocaleString()}</td></tr>`
          )
          .join("");

  const recentRows =
    recent.length === 0
      ? ""
      : recent
          .slice(-5)
          .reverse()
          .map((r) => {
            const status = r.ok
              ? '<span style="color:var(--ok)">✓</span>'
              : '<span style="color:var(--danger)">✗</span>';
            return `<tr><td>${h(r.ts || "")}</td><td>${h(r.task || "")}</td><td>${h(r.model || "")}</td><td style="text-align:right">${(r.total_tokens || 0).toLocaleString()}</td><td style="text-align:right">${r.duration_ms || 0}ms</td><td>${status}</td></tr>`;
          })
          .join("");

  return `
    <details style="margin-top:12px">
      <summary style="cursor:pointer;font-size:13px;color:var(--muted)">
        📊 用量统计：${usage.total_calls} 次调用 · ${usage.total_tokens.toLocaleString()} tokens
      </summary>
      <div style="margin-top:8px;display:grid;grid-template-columns:1fr 1fr;gap:12px">
        <div>
          <div style="font-size:12px;color:var(--muted);margin-bottom:4px">按任务</div>
          <table class="mini-table" style="width:100%;font-size:12px">
            <thead><tr><th>任务</th><th style="text-align:right">调用</th><th style="text-align:right">tokens</th></tr></thead>
            <tbody>${taskRows}</tbody>
          </table>
        </div>
        <div>
          <div style="font-size:12px;color:var(--muted);margin-bottom:4px">按模型</div>
          <table class="mini-table" style="width:100%;font-size:12px">
            <thead><tr><th>模型</th><th style="text-align:right">调用</th><th style="text-align:right">tokens</th></tr></thead>
            <tbody>${modelRows}</tbody>
          </table>
        </div>
      </div>
      ${
        recentRows
          ? `
        <div style="margin-top:8px">
          <div style="font-size:12px;color:var(--muted);margin-bottom:4px">最近调用</div>
          <table class="mini-table" style="width:100%;font-size:12px">
            <thead><tr><th>时间</th><th>任务</th><th>模型</th><th style="text-align:right">tokens</th><th style="text-align:right">耗时</th><th>状态</th></tr></thead>
            <tbody>${recentRows}</tbody>
          </table>
        </div>
      `
          : ""
      }
    </details>
  `;
}

export function renderScriptView(project) {
  const preview = state.scriptPreview;
  const scriptText = String(project.story_text || "");
  const scriptWarning = looksGarbledScriptText(scriptText)
    ? `<div class="preview-note">当前剧本文本看起来已经损坏成问号了。可以先点击"从分镜重建剧本"，再重新粘贴原文后预览或应用。</div>`
    : "";
  return `
    <div class="split-grid">
      <section id="scriptRecognitionPanel" class="window-pane">
        <div class="window-head">剧本识别 <small>提取角色、台词、镜头</small></div>
        <div class="window-body section-stack">
          ${scriptWarning}
          <div class="form-grid">
            ${fieldText("scriptTitleInput", "标题", project.title || "")}
            ${fieldSelect("scriptPlannerInput", "识别模式", planners, project.settings?.planner || "auto")}
            ${fieldNumber("scriptMaxScenesInput", "最大分镜", Math.min(24, Math.max(1, (project.scenes || []).length || 12)), 'min="1" max="24" step="1"')}
            ${fieldText("scriptHintInput", "提示", "支持小说、剧本、台词本")}
            ${fieldTextarea("scriptTextInput", "粘贴剧本", project.story_text || "", 18, "例如：场景一：雨夜。林晚：这是最后一次。")}
          </div>
          <div class="row-actions">
            <button class="ghost-button" type="button" data-action="pick-script-file">导入 TXT/MD</button>
            <button class="ghost-button" type="button" data-action="preview-script">预览识别</button>
            <button class="primary-button" type="button" data-action="apply-script">应用到项目</button>
            ${looksGarbledScriptText(scriptText) ? '<button class="ghost-button" type="button" data-action="repair-story-text">从分镜重建剧本</button>' : ""}
          </div>
          <input id="scriptFileInput" type="file" accept=".txt,.md,.markdown,text/plain,text/markdown" hidden>
        </div>
      </section>
      <section class="window-pane">
        <div class="window-head">识别预览 <small>${h(preview?.planner_used || "未运行")}</small></div>
        <div class="window-body section-stack">
          ${preview ? renderScriptPreview(preview) : `<div class="empty-state">先点击"预览识别"，确认角色和分镜再应用。</div>`}
        </div>
      </section>
    </div>
  `;
}

export function renderScriptPreview(preview) {
  const analysis = preview?.analysis || {};
  const roles = Array.isArray(analysis.roles) ? analysis.roles : [];
  const events = Array.isArray(analysis.events) ? analysis.events : [];
  const scenes = Array.isArray(preview?.scenes) ? preview.scenes : [];
  return `
    <div class="scene-card">
      <div class="item-title">${h(preview.title || "未命名")}</div>
      <div class="item-meta">角色：${h((preview.analysis?.characters || []).map((item) => item.name || item).join("、"))}</div>
    </div>
    ${roles.length ? `<div class="preview-list">${roles.map(renderScriptRoleCard).join("")}</div>` : ""}
    ${events.length ? `<div class="preview-list">${events.map(renderScriptEventCard).join("")}</div>` : ""}
    <div class="preview-list">${scenes.map(renderScriptSceneEditableCard).join("")}</div>
  `;
}

function renderScriptRoleCard(role) {
  return `
    <div class="preview-role-card">
      <div class="item-title">${h(role.name || "未命名角色")}</div>
      <div class="preview-tags">
        <span class="badge ok">${h(role.voice_profile || "voice")}</span>
        <span class="badge">${h(role.suggested_voice_engine || "auto")}</span>
        <span class="badge warn">${h(role.mentions ?? 0)} 次提及</span>
      </div>
      <div class="item-meta">首见于第 ${h(role.first_scene ?? 0)} 段 · 重要度 ${h(role.importance ?? 0)}</div>
      <div class="preview-snippet">${h(role.summary || "未生成摘要")}</div>
    </div>
  `;
}

function renderScriptEventCard(event) {
  const characters = Array.isArray(event.characters) ? event.characters : [];
  const sourceLines = Array.isArray(event.source_lines) ? event.source_lines : [];
  return `
    <div class="preview-event-card">
      <div class="item-title">#${h(event.index)} ${h(event.title || "事件")}</div>
      <div class="preview-tags">
        <span class="badge ok">${h(event.camera || "slow_push_in")}</span>
        <span class="badge warn">${h(event.emotion || "neutral")}</span>
        <span class="badge">${h(characters.length ? characters.join("、") : "无明确角色")}</span>
      </div>
      <div class="preview-snippet">${h(event.summary || "未生成摘要")}</div>
      ${event.dialogue ? `<div class="preview-snippet">${nl(event.dialogue)}</div>` : ""}
      ${sourceLines.length ? `<div class="item-meta">原始行数 ${h(sourceLines.length)}</div>` : ""}
    </div>
  `;
}

function renderScriptSceneEditableCard(scene) {
  const order = Number(scene.order || scene.index || 0);
  const characters = Array.isArray(scene.characters) ? scene.characters : [];
  const sourceLines = Array.isArray(scene.source_lines) ? scene.source_lines : [];
  const assets = scene.assets || {};
  return `
    <div class="preview-scene-card" data-preview-scene-order="${h(order)}">
      <div class="preview-scene-head">
        <div>
          <div class="item-title">#${h(order)} ${h(scene.title || "分镜")}</div>
          <div class="item-meta">可直接修改后再应用到项目</div>
        </div>
        <div class="preview-tags">
          <span class="badge ok">${h(scene.camera_movement || scene.camera || "slow_push_in")}</span>
          <span class="badge warn">${h(scene.emotion || "neutral")}</span>
          <span class="badge">${h(formatSeconds(scene.duration_seconds ?? scene.duration))}</span>
        </div>
      </div>
      <div class="form-grid preview-scene-grid">
        ${fieldText(previewSceneFieldId(order, "Title"), "分镜标题", scene.title || "")}
        ${fieldText(previewSceneFieldId(order, "Speaker"), "说话人", scene.speaker || "")}
        ${fieldSelect(previewSceneFieldId(order, "Camera"), "镜头", cameraOptions, scene.camera_movement || scene.camera || "slow_push_in")}
        ${fieldText(previewSceneFieldId(order, "Emotion"), "情绪", scene.emotion || "")}
        ${fieldNumber(previewSceneFieldId(order, "Duration"), "时长(秒)", scene.duration_seconds ?? scene.duration ?? 4, 'min="1" max="120" step="0.1"')}
        ${fieldText(previewSceneFieldId(order, "Characters"), "角色", characters.join(", "))}
        ${fieldTextarea(previewSceneFieldId(order, "Visual"), "画面提示", scene.visual_prompt || scene.visual || "", 3)}
        ${fieldTextarea(previewSceneFieldId(order, "Dialogue"), "台词", scene.dialogue || "", 3)}
      </div>
      <div class="preview-tags">
        ${assets.image_url ? '<span class="badge ok">图像已生成</span>' : '<span class="badge">图像待生成</span>'}
        ${assets.audio_url ? '<span class="badge ok">配音已生成</span>' : '<span class="badge">配音待生成</span>'}
        ${assets.video_url ? '<span class="badge ok">视频已生成</span>' : '<span class="badge">视频待生成</span>'}
      </div>
      ${sourceLines.length ? `<div class="item-meta">原始行数 ${h(sourceLines.length)}</div>` : ""}
    </div>
  `;
}

export function renderAssetsView(project) {
  const active = state.assets.activeTab || "character";
  const tab = assetTabs.find(([key]) => key === active) || assetTabs[0];
  const bucket = tab[1];
  const assets = state.assets[bucket] || [];
  const counts = {
    character: state.assets.characters.length,
    scene_bg: state.assets.scene_bgs.length,
    prop: state.assets.props.length,
  };
  const isCharacterTab = active === "character";
  const character = selectedCharacter(project);
  return `
    <div class="asset-library-view ${isCharacterTab ? "has-voice-pane" : ""}">
      <section id="characterSection" class="window-pane asset-library-main">
        <div class="window-head">资产库 <small>${state.assets.loading ? "同步中" : `${counts.character + counts.scene_bg + counts.prop} 项`}</small></div>
        <div class="window-body asset-library-body">
          <div class="asset-library-toolbar">
            ${renderAssetTabs(active, counts)}
            <div class="asset-library-actions">
              <button class="ghost-button" type="button" data-action="asset-refresh" ${state.assets.loading ? "disabled" : ""}>刷新</button>
              <button class="ghost-button" type="button" data-action="asset-style">风格选择</button>
              <button class="primary-button" type="button" data-action="asset-extract" ${state.assets.loading ? "disabled" : ""}>${state.assets.loading ? "提取中..." : "AI 智能提取"}</button>
              <button class="ghost-button" type="button" data-action="asset-add">+ 添加</button>
            </div>
          </div>
          ${state.assets.loading ? `<div class="asset-loading"><span class="asset-spinner"></span><span>正在同步资产库...</span></div>` : ""}
          ${renderAssetGrid(assets, active)}
        </div>
      </section>
      ${
        isCharacterTab
          ? `
        <section class="window-pane asset-voice-pane">
          <div class="window-head">角色声线配置 <small>按资产名关联旧角色库</small></div>
          <div class="window-body section-stack">
            <details class="asset-voice-details" open>
              <summary>展开 / 收起声线配置</summary>
              <div class="asset-voice-editor">
              ${character ? renderCharacterEditor(character, state.selectedCharacterIndex) : `<div class="empty-state">请选择角色资产，或先完成剧本识别。</div>`}
              </div>
            </details>
          </div>
        </section>
      `
          : ""
      }
      <section class="window-pane asset-library-footer">
        <div class="window-head">批量操作 <small>阶段 2 生成接口中 stub</small></div>
        <div class="window-body">
          <div class="row-actions">
            <button class="primary-button" type="button" data-action="asset-generate-all" ${counts.character + counts.scene_bg + counts.prop ? "" : "disabled"}>一键重新生成</button>
            <button class="ghost-button" type="button" disabled>一键下载</button>
          </div>
        </div>
      </section>
    </div>
  `;
}

function renderAssetTabs(activeTab, counts) {
  return `
    <div class="asset-type-tabs" role="tablist" aria-label="资产类型">
      ${assetTabs
        .map(
          ([key, _bucket, label]) => `
        <button class="${activeTab === key ? "is-active" : ""}" type="button" data-action="asset-tab" data-asset-tab="${h(key)}">
          <span>${h(label)}</span>
          <strong>${h(counts[key] || 0)}</strong>
        </button>
      `
        )
        .join("")}
    </div>
  `;
}

function renderAssetGrid(assets, type) {
  if (!assets.length) {
    return `
      <div class="asset-empty-state">
        <div class="item-title">当前分类还没有资产</div>
        <div class="item-meta">点击"AI 智能提取"从剧本里生成资产清单，或使用"+ 添加"手动补充。</div>
      </div>
    `;
  }
  return `
    <div class="asset-card-grid" data-asset-grid-type="${h(type)}">
      ${assets.map((asset) => renderAssetCard(asset)).join("")}
    </div>
  `;
}

function renderAssetCard(asset) {
  const status = String(asset.status || "pending");
  const type = String(asset.asset_type || "character");
  const prompt = asset.visual_prompt || asset.appearance || asset.description || "暂无视觉描述";
  const initials =
    String(asset.name || assetTypeLabel(type))
      .trim()
      .slice(0, 2) || "资产";
  const thumbnail = asset.thumbnail
    ? `<img src="${h(asset.thumbnail)}" alt="">`
    : `<div class="asset-thumb-placeholder">${h(initials)}</div>`;
  return `
    <article class="asset-card status-${h(status)}" data-action="select-asset" data-asset-id="${h(asset.id)}" data-asset-type="${h(type)}" data-asset-name="${h(asset.name || "")}">
      <div class="asset-thumb">
        ${thumbnail}
        ${status === "generating" ? `<span class="asset-spinner asset-thumb-spinner"></span>` : ""}
      </div>
      <div class="asset-card-body">
        <div class="asset-card-head">
          <div>
            <div class="asset-name">${h(asset.name || "未命名资源")}</div>
            <div class="item-meta">${h(assetTypeLabel(type))} · 首见第 ${h(asset.first_scene || 1)} 场</div>
          </div>
          <span class="asset-status status-${h(status)}">${h(assetStatusLabel(status))}</span>
        </div>
        <div class="asset-prompt">${h(prompt)}</div>
        ${
          type === "character"
            ? `<div class="asset-traits">${[asset.gender, asset.age, asset.personality]
                .filter(Boolean)
                .map((item) => `<span>${h(item)}</span>`)
                .join("")}</div>`
            : ""
        }
      </div>
      <div class="asset-card-actions">
        <button class="ghost-button mini-button" type="button" data-action="asset-generate" data-asset-id="${h(asset.id)}" ${status === "generating" ? "disabled" : ""}>${status === "failed" ? "重试" : "生成"}</button>
      </div>
    </article>
  `;
}

function renderCharacterEditor(character) {
  return `
    <div class="form-grid">
      ${fieldText("characterNameInput", "角色名", character.name || "")}
      ${fieldSelect("characterVoiceProfileInput", "声线标签", voiceProfiles, character.voice_profile || "")}
      ${fieldSelect("characterVoiceEngineInput", "引擎", voiceEngines, character.voice_engine || "auto")}
      ${fieldText("characterVoiceIdInput", "Voice ID", character.voice_id || "", "可填预设名或留空")}
      ${fieldSelect("characterReferenceAudioInput", "参考音频", voiceSamples, character.reference_audio_path || "")}
      ${fieldSelect("characterEmotionInput", "默认情绪", voiceEmotions, character.emotion || "")}
      ${fieldNumber("characterRateInput", "语速", character.voice_rate ?? 1, 'min="0.5" max="2" step="0.05"')}
      ${fieldNumber("characterPitchInput", "音高", character.voice_pitch ?? 0, 'min="-24" max="24" step="0.5"')}
      ${fieldNumber("characterVolumeInput", "音量", character.voice_volume ?? 1, 'min="0" max="2" step="0.05"')}
      ${fieldTextarea("characterDescriptionInput", "人设描述", character.description || "", 5)}
      ${fieldTextarea("characterReferenceTextInput", "参考音频文本", character.reference_text || "", 3)}
    </div>
    <div class="item-meta">首见第 ${h(character.first_scene ?? 0)} 段 · 重要度 ${h(character.importance ?? 0)} · 建议引擎 ${h(character.suggested_voice_engine || "edge")}</div>
    <div class="row-actions">
      <button class="primary-button" type="button" data-action="save-character">保存角色</button>
      <button class="ghost-button" type="button" data-action="preview-character-voice">试听声线</button>
      <label class="button-link">上传参考图<input id="characterReferenceFileInput" type="file" accept="image/*" hidden></label>
    </div>
    ${character.reference_image_url ? `<div class="clip-preview"><div class="thumb-frame"><img src="${h(character.reference_image_url)}" alt=""></div><div class="muted">参考图已绑定。</div></div>` : ""}
    ${renderVoicePreviewResult()}
  `;
}

function renderComfyUIStatus() {
  const status = state.comfyuiStatus;
  if (!status) {
    return `<div class="diagnostic-card"><span class="status-pill warn">ComfyUI 未检测</span><span class="muted">点击检测连接，确认后端是否能提交工作流。</span></div>`;
  }
  const queue = status.queue || {};
  const running = Array.isArray(queue.queue_running) ? queue.queue_running.length : 0;
  const pending = Array.isArray(queue.queue_pending) ? queue.queue_pending.length : 0;
  const missing = Array.isArray(status.missing_nodes) ? status.missing_nodes : [];
  const registered = Array.isArray(status.registered_nodes) ? status.registered_nodes : [];
  const missingModels = Array.isArray(status.models?.missing) ? status.models.missing : [];
  const argv = Array.isArray(status.system?.argv) ? status.system.argv.join(" ") : "";
  const modelText = status.models?.skipped
    ? "模型：远程 ComfyUI 已跳过本地文件检查"
    : "模型：checkpoint / IPAdapter / CLIP Vision 已就绪";
  return `
    <div class="diagnostic-card">
      <div class="row-actions">
        <span class="status-pill ${status.available ? "ok" : "danger"}">ComfyUI ${status.available ? "可用" : "不可用"}</span>
        <span class="summary-chip">${h(status.base_url || "")}</span>
        <span class="summary-chip">队列 ${running}/${pending}</span>
      </div>
       <div class="item-meta">工作流：${status.workflow_exists ? "已找到" : "未找到"} · 节点 ${registered.length}/${(status.required_nodes || []).length || registered.length}</div>
       ${missing.length ? `<div class="item-meta danger-text">缺少节点：${h(missing.join(", "))}</div>` : ""}
       ${missingModels.length ? `<div class="item-meta danger-text">缺少模型：${h(missingModels.join(", "))}</div>` : `<div class="item-meta">${h(modelText)}</div>`}
       <div class="item-meta">参考图：${status.reference_mode === "upload" || !status.is_local ? "上传到 ComfyUI input" : "本地 input 目录"} · ${status.is_local ? "本地" : "远程"}</div>
       ${argv ? `<div class="item-meta">启动参数：${h(argv)}</div>` : ""}
      ${status.error ? `<div class="item-meta danger-text">${h(status.error)}</div>` : ""}
    </div>
  `;
}

function renderVoicePreviewResult() {
  if (!state.voicePreview?.url) return "";
  return `
    <div class="scene-card">
      <div class="item-title">试听结果 · ${h(state.voicePreview.engine || state.voicePreview.requested_engine || "")}</div>
      <audio controls src="${h(state.voicePreview.url)}"></audio>
      ${(state.voicePreview.warnings || []).map((warning) => `<div class="item-meta">${h(warning)}</div>`).join("")}
    </div>
  `;
}

export function renderWorkbenchView(project) {
  return `
    <div class="workbench-grid">
      <div class="workbench-column">
        <section id="assetQueueSection" class="window-pane workbench-secondary">
          <div class="window-head">资产缺口队列 <small>${renderAssetQueueSummary(project)}</small></div>
          <div class="window-body">${renderAssetQueue(project)}</div>
        </section>
        <section id="sceneListSection" class="window-pane workbench-secondary">
          <div class="window-head">分镜列表 <small>${(project.scenes || []).length} 镜</small></div>
          <div class="window-body card-list">${(project.scenes || []).map(renderSceneCard).join("")}</div>
        </section>
      </div>
      <div class="workbench-main">
      <section id="storyboardReviewSection" class="window-pane workbench-secondary">
        <div class="window-head">Storyboard review <small>canonical timeline 实片台</small></div>
        <div class="window-body">${renderStoryboardReviewCanvas(project)}</div>
      </section>
      </div>
      ${renderSelectedSceneWindow(project)}
    </div>
  `;
}

function renderSceneCard(scene) {
  const active = Number(scene.order) === Number(state.selectedSceneOrder) ? "is-active" : "";
  const gaps = sceneAssetGaps(scene);
  const failed = Boolean(
    scene.validation_failed || String(scene.assets?.status || "").toLowerCase() === "failed"
  );
  return `
    <button class="scene-card ${active} ${failed ? "is-failed" : ""}" type="button" data-action="select-scene" data-scene-order="${h(scene.order)}">
      <div class="item-title">#${h(scene.order)} ${h(scene.title || "分镜")}</div>
      <div class="item-meta">${formatSeconds(scene.duration_seconds)} · ${h(scene.speaker || "角色")}</div>
      <div class="item-meta">${gaps.length ? `缺口：${gaps.join(" / ")}` : "资产已齐"}</div>
      <div class="item-meta">${h(String(scene.dialogue || "").slice(0, 80))}</div>
      ${failed ? `<div class="item-meta danger-text">${h(scene.error_message || "分镜校验失败")}</div>` : ""}
    </button>
  `;
}

export function renderTimelinePanel(project) {
  const scenes = timelineSceneItems(project);
  if (!scenes.length) return `<div class="empty-state">还没有分镜。</div>`;
  const timeline = canonicalTimeline(project);
  const total = Math.max(
    1,
    asNumber(timeline?.duration_seconds, 0) ||
      scenes.reduce((sum, scene) => sum + asNumber(scene.duration_seconds, 4), 0)
  );
  const width = Math.max(900, Math.round(total * TIMELINE_PX_PER_SECOND));
  const selected =
    scenes.find((scene) => Number(scene.order) === Number(state.selectedSceneOrder)) ||
    scenes[0] ||
    selectedScene(project);
  return `
    <div class="timeline-shell">
      <div class="timeline-ruler" style="width:${width}px">${renderTimelineRuler(total)}</div>
      <div class="timeline-track" style="width:${width}px">${scenes.map(renderTimelineClip).join("")}</div>
      <div class="clip-preview">${renderClipPreview(selected)}</div>
    </div>
  `;
}

function renderTimelineRuler(total) {
  const marks = [];
  for (let second = 0; second <= Math.ceil(total); second += 2) {
    marks.push(
      `<div class="ruler-mark" style="left:${Math.round(second * TIMELINE_PX_PER_SECOND)}px">${second}s</div>`
    );
  }
  return marks.join("");
}

function renderTimelineClip(scene) {
  const duration = asNumber(scene.duration_seconds, 4);
  const width = Math.max(92, Math.round(duration * TIMELINE_PX_PER_SECOND));
  const assets = scene.assets || {};
  const active = Number(scene.order) === Number(state.selectedSceneOrder) ? "is-active" : "";
  const gaps = sceneAssetGaps(scene);
  const hasStart = Number.isFinite(Number(scene.start_seconds));
  const hasEnd = Number.isFinite(Number(scene.end_seconds));
  const span =
    hasStart || hasEnd
      ? ` @ ${hasStart ? formatSeconds(scene.start_seconds) : formatSeconds(0)} → ${hasEnd ? formatSeconds(scene.end_seconds) : formatSeconds(duration)}`
      : "";
  return `
    <div class="timeline-clip ${active}" style="width:${width}px" data-action="select-scene" data-scene-order="${h(scene.order)}">
      <div class="clip-title">#${h(scene.order)} ${h(scene.title || "分镜")}</div>
      <div class="clip-meta" data-clip-duration="${h(scene.order)}">${formatSeconds(duration)}${h(span)}</div>
      ${gaps.length ? `<div class="clip-gap">${h(gaps.join(" / "))}</div>` : ""}
      <div class="clip-dots">
        <span class="asset-dot ${assets.image_url ? "ok" : ""}" title="image"></span>
        <span class="asset-dot ${assets.audio_url ? "ok" : ""}" title="audio"></span>
        <span class="asset-dot ${assets.video_url ? "ok" : ""}" title="video"></span>
      </div>
      <div class="clip-resize-handle" data-action="timeline-resize" data-scene-order="${h(scene.order)}"></div>
    </div>
  `;
}

function renderClipPreview(scene) {
  if (!scene) return `<div class="empty-state">请选择分镜。</div>`;
  const assets = scene.assets || {};
  const media = assets.video_url
    ? `<video src="${h(assets.video_url)}" controls playsinline></video>`
    : assets.image_url
      ? `<img src="${h(assets.image_url)}" alt="">`
      : `<span>暂无画面</span>`;
  return `
    <div class="thumb-frame">${media}</div>
    <div class="section-stack">
      <div class="item-title">#${h(scene.order)} ${h(scene.title || "分镜")}</div>
      <div class="muted">${formatSeconds(scene.duration_seconds)} · ${h(scene.camera_movement || "镜头")}</div>
      <div>${nl(scene.dialogue || "暂无台词")}</div>
      ${renderAssetLinks(scene)}
    </div>
  `;
}

function sceneGenerationMeta(scene) {
  return scene?.generation_meta && typeof scene.generation_meta === "object"
    ? scene.generation_meta
    : {};
}
function generationBadgeClass(meta) {
  if (!meta || !Object.keys(meta).length) return "is-unknown";
  if (meta.fallback_used) return "is-fallback";
  if (meta.is_real_video) return "is-real";
  return "is-local";
}
function generationLabel(meta) {
  if (!meta || !Object.keys(meta).length) return "Unknown";
  if (meta.fallback_used) return "2.5D fallback";
  if (meta.is_real_video) return "Real video";
  return "Local 2.5D";
}
function renderGenerationBadge(scene) {
  const meta = sceneGenerationMeta(scene);
  const provider = meta.provider_label || meta.provider_id || "";
  const attempts = Number(meta.attempts || 0);
  const suffix = [provider, attempts > 1 ? `${attempts} tries` : ""].filter(Boolean).join(" · ");
  return `<div class="generation-badge ${generationBadgeClass(meta)}">${h(generationLabel(meta))}${suffix ? ` · ${h(suffix)}` : ""}</div>`;
}
function renderGovernanceDetail(scene) {
  const governance = sceneGovernance(scene);
  const status = governanceStatus(scene);
  const dimensions =
    governance.dimensions && typeof governance.dimensions === "object" ? governance.dimensions : {};
  const dimensionRows = ["character", "lighting", "environment", "prop", "camera"]
    .map((dimension) => {
      const data =
        dimensions[dimension] && typeof dimensions[dimension] === "object"
          ? dimensions[dimension]
          : {};
      const dimStatus = String(data.status || "not_evaluated");
      const score = Number.isFinite(Number(data.score)) ? Number(data.score).toFixed(2) : "0.00";
      return `<span class="governance-dimension ${governanceStatusClass(dimStatus)}" title="${h(data.reason || "")}">${h(dimension)} ${h(dimStatus)} ${h(score)}</span>`;
    })
    .join("");
  const policy =
    governance.policy && typeof governance.policy === "object" ? governance.policy : {};
  const offenders = Array.isArray(governance.offending_dimensions)
    ? governance.offending_dimensions
    : [];
  return `
    <div class="governance-detail ${governanceStatusClass(status)}">
      <strong>${h(governanceStatusLabel(status))}</strong>
      <span>${h(policy.mode || "report")} · ${h(policy.action || "recorded")} · ${governance.deliverable === false ? "not deliverable" : "deliverable"}</span>
      <div class="governance-dimension-grid">${dimensionRows}</div>
      ${offenders.length ? `<span class="danger-text">${h(offenders.join(" / "))}</span>` : ""}
    </div>
  `;
}

function renderAssetQueueSummary(project) {
  const scenes = project?.scenes || [];
  const counts = scenes.reduce(
    (acc, scene) => {
      for (const gap of sceneAssetGaps(scene)) {
        if (gap === "图片") acc.image += 1;
        if (gap === "音频") acc.audio += 1;
        if (gap === "视频") acc.video += 1;
      }
      return acc;
    },
    { image: 0, audio: 0, video: 0 }
  );
  const total = counts.image + counts.audio + counts.video;
  return total ? `${total} 项缺口` : "全部就绪";
}

function renderAssetQueue(project) {
  const scenes = project?.scenes || [];
  const items = scenes
    .map((scene) => ({ scene, gaps: sceneAssetGaps(scene) }))
    .filter((entry) => entry.gaps.length);
  if (!items.length) {
    return `<div class="empty-state">当前没有资产缺口。</div>`;
  }
  return `
    <div class="section-stack">
      <div class="row-actions">
        <button class="primary-button" type="button" data-action="fill-missing-assets">补齐全部缺口</button>
        <button class="ghost-button" type="button" data-action="fill-missing-images">补图</button>
        <button class="ghost-button" type="button" data-action="fill-missing-audio">补音频</button>
        <button class="ghost-button" type="button" data-action="fill-missing-video">补视频</button>
      </div>
      <div class="preview-list">
        ${items
          .map(
            ({ scene, gaps }) => `
          <div class="preview-card">
            <div class="item-title">#${h(scene.order)} ${h(scene.title || "分镜")}</div>
            <div class="item-meta">${h(gaps.join(" / "))}</div>
            <div class="item-meta">${h(scene.speaker || "角色")} · ${formatSeconds(scene.duration_seconds)}</div>
          </div>
        `
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderSelectedSceneWindow(project) {
  const scene = selectedScene(project);
  return `
    <section id="selectedSceneSection" class="window-pane" data-workspace-view="workbench scene">
      <div class="window-head">当前分镜 <small>${scene ? `#${h(scene.order)}` : "未选择"}</small></div>
      <div class="window-body">${scene ? renderSceneEditor(scene, project) : `<div class="empty-state">请选择一个分镜。</div>`}</div>
    </section>
  `;
}

export function renderSceneEditor(scene, project) {
  const assets = scene.assets || {};
  return `
    <div class="scene-editor">
      <div class="scene-stage-panel">
        ${renderSceneMedia(scene)}
        ${renderSceneClipInspector(scene)}
        ${renderCropEditor(scene)}
        ${renderSceneReadiness(scene)}
        ${renderGovernanceDetail(scene)}
        ${renderProductionMeta(scene, project)}
        ${renderAssetLinks(scene)}
      </div>
      <div class="scene-control-panel">
        <div class="scene-action-dock">
          <div class="action-group">
            <div class="action-group-title">编辑</div>
            <button class="primary-button" type="button" data-action="save-scene">保存分镜</button>
            <button class="ghost-button" type="button" data-action="split-scene">拆分</button>
            <button class="ghost-button" type="button" data-action="merge-scene">合并下一个</button>
            <button class="ghost-button" type="button" data-action="restore-scene">回滚</button>
          </div>
          <div class="action-group">
            <div class="action-group-title">生成</div>
            <button class="ghost-button" type="button" data-action="rerender-image">重绘图</button>
            <button class="ghost-button" type="button" data-action="rerender-audio">重配音</button>
            <button class="ghost-button" type="button" data-action="rerender-video">重合成</button>
            <button class="ghost-button" type="button" data-action="rebuild-scene">单格重跑</button>
          </div>
          <div class="action-group">
            <div class="action-group-title">预览</div>
            <button class="ghost-button" type="button" data-action="preview-scene-voice">试听声线</button>
          </div>
        </div>
        <div class="editor-block">
          <div class="editor-block-title">分镜内容</div>
          <div class="form-grid">
            ${fieldText("sceneTitleInput", "标题", scene.title || "")}
            ${fieldNumber("sceneDurationInput", "时长(秒)", scene.duration_seconds ?? 4, 'min="1" max="120" step="0.1"')}
            ${fieldText("sceneSpeakerInput", "说话人", scene.speaker || "")}
            ${fieldSelect("sceneCameraInput", "镜头", cameraOptions, scene.camera_movement || "slow_push_in")}
            ${fieldNumber("sceneCameraSpeedInput", "镜头速度", scene.camera_speed ?? 1, 'min="0.35" max="3" step="0.05"')}
            ${fieldText("sceneCharactersInput", "出场角色", (scene.characters || []).join(", "))}
            ${fieldSelect("sceneEmotionInput", "情绪", voiceEmotions, scene.emotion || "")}
            ${fieldTextarea("sceneVisualInput", "画面提示词", scene.visual_prompt || "", 6)}
            ${fieldTextarea("sceneDialogueInput", "台词", scene.dialogue || "", 4)}
          </div>
        </div>
        <div class="editor-block">
          <div class="editor-block-title">声线配置</div>
          <div class="form-grid">
            ${fieldSelect("sceneVoiceEngineInput", "配音引擎", voiceEngines, scene.voice_engine || "auto")}
            ${fieldText("sceneVoiceIdInput", "Voice ID", scene.voice_id || scene.voice_profile || "")}
            ${fieldSelect("sceneVoiceProfileInput", "声线标签", voiceProfiles, scene.voice_profile || "")}
            ${fieldSelect("sceneReferenceAudioInput", "参考音频", voiceSamples, scene.reference_audio_path || "")}
            ${fieldNumber("sceneRateInput", "语速", scene.voice_rate ?? 1, 'min="0.5" max="2" step="0.05"')}
            ${fieldNumber("scenePitchInput", "音高", scene.voice_pitch ?? 0, 'min="-24" max="24" step="0.5"')}
            ${fieldNumber("sceneVolumeInput", "音量", scene.voice_volume ?? 1, 'min="0" max="2" step="0.05"')}
            ${fieldTextarea("sceneReferenceTextInput", "参考文本", scene.reference_text || "", 3)}
          </div>
        </div>
        ${renderSceneShotEditor(scene)}
        ${renderSceneAudioManifestEditor(scene)}
        ${renderSceneHistory(scene)}
        ${renderVoicePreviewResult()}
      </div>
      <div class="scene-watermark">${h(assets.status || "pending")}</div>
    </div>
  `;
}

export function renderSceneMedia(scene) {
  const assets = scene.assets || {};
  const cropBox = normalizeCropBox(scene.crop_box);
  const isCropEditing = Number(state.cropEditorSceneOrder) === Number(scene.order);
  const showingImage = Boolean(assets.image_url && (isCropEditing || !assets.video_url));
  const media = showingImage
    ? `<img src="${h(assets.image_url)}" alt="">`
    : assets.video_url
      ? `<video src="${h(assets.video_url)}" controls playsinline></video>`
      : `<div class="scene-media-empty">暂无画面<br><span>先重绘图或单格重跑</span></div>`;
  return `
    <div class="scene-preview-frame">
      ${media}
      ${showingImage ? renderCropOverlay(cropBox) : ""}
      <div class="scene-preview-badge">#${h(scene.order)} · ${formatSeconds(scene.duration_seconds)}</div>
    </div>
    ${assets.audio_url ? `<audio class="scene-audio" controls src="${h(assets.audio_url)}"></audio>` : `<div class="scene-audio-missing">音频未生成</div>`}
    <div class="scene-subtitle-preview">
      <span>${h(scene.speaker || "角色")}</span>
      <strong>${nl(scene.dialogue || "暂无台词")}</strong>
      <small>${h(scene.emotion || "未设置情绪")}</small>
    </div>
  `;
}

function renderCropOverlay(cropBox) {
  return `
    <div class="crop-dim-layer" aria-hidden="true"></div>
    <div
      id="sceneCropOverlay"
      class="crop-overlay"
      style="left:${cropPercent(cropBox.x)}; top:${cropPercent(cropBox.y)}; width:${cropPercent(cropBox.width)}; height:${cropPercent(cropBox.height)}"
      aria-hidden="true"
    ></div>
  `;
}

export function renderCropEditor(scene) {
  const assets = scene.assets || {};
  if (!assets.image_url) {
    return `
      <div class="crop-panel is-disabled">
        <div>
          <strong>9:16 取景框</strong>
          <span>当前分镜还没有图片，生成图片后可调整。</span>
        </div>
      </div>
    `;
  }
  const cropBox = normalizeCropBox(scene.crop_box);
  const isEditing = Number(state.cropEditorSceneOrder) === Number(scene.order);
  if (!isEditing) {
    return `
      <div class="crop-panel">
        <div>
          <strong>9:16 取景框</strong>
          <span>X ${Math.round(cropBox.x * 100)}% · Y ${Math.round(cropBox.y * 100)}% · 宽 ${Math.round(cropBox.width * 100)}% · 高 ${Math.round(cropBox.height * 100)}%</span>
        </div>
        <button class="ghost-button" type="button" data-action="enable-crop-editor">开启取景调整</button>
      </div>
    `;
  }
  return `
    <div class="crop-panel crop-editor-panel">
      <div class="crop-panel-head">
        <div>
          <strong>9:16 取景框</strong>
          <span>数值为 0-1 归一化坐标，保存到 scene.crop_box。</span>
        </div>
        <div class="crop-actions">
          <button class="primary-button" type="button" data-action="save-crop-box">保存取景框</button>
          <button class="ghost-button" type="button" data-action="reset-crop-box">重置取景框</button>
        </div>
      </div>
      <div class="crop-control-grid">
        ${renderCropControl("sceneCropXInput", "X", cropBox.x)}
        ${renderCropControl("sceneCropYInput", "Y", cropBox.y)}
        ${renderCropControl("sceneCropWidthInput", "宽", cropBox.width, 0.05)}
        ${renderCropControl("sceneCropHeightInput", "高", cropBox.height, 0.05)}
      </div>
    </div>
  `;
}

function renderCropControl(id, label, value, min = 0) {
  const safeValue = clamp(value, min, 1);
  return `
    <label class="crop-control">
      <span>${h(label)}</span>
      <input id="${h(id)}" class="crop-range" type="range" min="${min}" max="1" step="0.001" value="${h(safeValue)}" data-crop-field="${h(id)}">
      <input class="crop-number" type="number" min="${min}" max="1" step="0.001" value="${h(safeValue.toFixed(3))}" data-crop-field="${h(id)}">
    </label>
  `;
}

function renderSceneClipInspector(scene) {
  const assets = scene.assets || {};
  const manifest = sceneAudioManifest(scene);
  const trigger = sceneSfxTrigger(scene);
  const triggerFile = String(trigger.file || "").trim();
  const triggerMs = Number(trigger.timestamp_ms || 0);
  const durationMs = sceneDurationMs(scene);
  const sfxPosition = Math.max(0, Math.min(100, (triggerMs / durationMs) * 100));
  const camera = scene.camera_movement || "slow_push_in";
  const cameraClass = cameraClassName(camera);
  const voiceReady = Boolean(assets.audio_url);
  return `
    <div class="clip-inspector">
      <div class="clip-inspector-head">
        <div>
          <strong>单格即时预览</strong>
          <span>${h(camera)} · ${formatSeconds(scene.duration_seconds)} · 速率 ${h(scene.camera_speed ?? 1)}</span>
        </div>
        <div class="clip-director-pill">${h(scene.director_recommendation?.reason || "manual")}</div>
      </div>
      <div class="micro-timeline" aria-label="分镜时间轴">
        <div class="micro-timeline-row">
          <span>镜头</span>
          <div class="micro-track camera-track ${cameraClass}">
            <i></i>
            <strong>${h(camera)}</strong>
          </div>
        </div>
        <div class="micro-timeline-row">
          <span>镜头节拍轨</span>
          ${renderSceneShotTrack(scene)}
        </div>
        <div class="micro-timeline-row">
          <span>音效</span>
          <div class="micro-track sfx-track">
            ${triggerFile ? `<b class="sfx-node" data-sfx-anchor="true" data-scene-order="${h(scene.order)}" data-duration-ms="${h(durationMs)}" data-current-ms="${h(triggerMs)}" style="left:${sfxPosition}%" title="${h(triggerFile)} @ ${h(triggerMs)}ms">${h(triggerFile)} ${h(triggerMs)}ms</b>` : `<em>无触发音效</em>`}
          </div>
        </div>
        <div class="micro-timeline-row">
          <span>对白</span>
          <div class="micro-track voice-track ${voiceReady ? "is-ready" : ""}">
            <i style="width:${voiceReady ? "100" : "36"}%"></i>
            <strong>${voiceReady ? "已生成配音/字幕" : "待生成配音"}</strong>
          </div>
        </div>
      </div>
      <div class="clip-inspector-meta">
        <span>BGM ${h(manifest.bgm_style || manifest.bgm_file || "未设置")}</span>
        <span>SFX ${triggerFile ? `${h(triggerFile)} / ${h(triggerMs)}ms` : "无"}</span>
      </div>
      ${renderTemporalPreview(scene)}
      <button class="ghost-button clip-rerender-button" type="button" data-action="rerender-video">重合成当前格</button>
    </div>
  `;
}

function renderSceneShotTrack(scene) {
  const shots = sceneShots(scene);
  if (!shots.length) {
    return `<div class="micro-track shot-track"><em>暂无 shot</em></div>`;
  }
  const total =
    shots.reduce((sum, shot) => sum + Math.max(0.1, asNumber(shot.duration_seconds, 0)), 0) || 1;
  return `
    <div class="micro-track shot-track">
      ${shots
        .map((shot, index) => {
          const duration = Math.max(0.1, asNumber(shot.duration_seconds, 0.1));
          const label = String(shot.label || shot.beat_type || `SHOT ${index + 1}`).trim();
          const beatType = shotBeatClass(shot.beat_type || label);
          const width = Math.max(18, (duration / total) * 100);
          const caption = String(
            shot.caption || shot.bubble || shot.dialogue || shot.title || ""
          ).trim();
          return `
            <b class="shot-node${beatType ? ` is-${h(beatType)}` : ""}${shot.has_override ? " is-overridden" : ""}" style="flex:${width};" title="${h(caption || shot.title || label)}">
              ${h(label)}
              <span>${h(duration.toFixed(1))}s</span>
            </b>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderTemporalPreview(scene) {
  const shots = sceneTemporalShots(scene);
  if (!shots.length) return "";
  const timeline = temporalShotTimeline(shots);
  const total =
    timeline.reduce((sum, item) => sum + item.duration, 0) || scene.duration_seconds || 1;
  return `
    <div class="temporal-preview" data-temporal-preview data-scene-order="${h(scene.order)}">
      <div class="temporal-preview-head">
        <div>
          <strong>Temporal preview</strong>
          <span data-temporal-summary>${h(shots.length)} shots / ${h(total.toFixed(1))}s</span>
        </div>
        <div class="temporal-preview-actions">
          <button class="ghost-button mini-button" type="button" data-action="temporal-preview-play">Play</button>
          <button class="ghost-button mini-button" type="button" data-action="temporal-preview-pause">Pause</button>
          <button class="ghost-button mini-button" type="button" data-action="temporal-preview-reset">Reset</button>
        </div>
      </div>
      <div class="temporal-preview-stage" id="temporalPreviewStage">
        <div class="temporal-preview-world" id="temporalPreviewWorld">
          <div class="temporal-preview-horizon"></div>
          <div class="temporal-preview-grid"></div>
          <div class="temporal-preview-actor" id="temporalPreviewActor">
            <i></i>
            <span>${h((scene.characters || [scene.speaker || "Actor"])[0] || scene.speaker || "Actor")}</span>
          </div>
          <div class="temporal-preview-title">${h(scene.title || "Scene")}</div>
        </div>
      </div>
      <div class="temporal-preview-progress"><i id="temporalPreviewProgress"></i></div>
      <div class="temporal-preview-ruler">
        ${timeline
          .map((item) => {
            const width = Math.max(20, (item.duration / total) * 100);
            return `<i data-temporal-ruler data-shot-order="${h(item.order)}" style="flex:${width};"><span>${h(item.start.toFixed(1))}</span></i>`;
          })
          .join("")}
      </div>
      <div class="temporal-preview-strip">
        ${timeline
          .map((item) => {
            const width = Math.max(20, (item.duration / total) * 100);
            const label = String(
              item.shot.label || item.shot.beat_type || `SHOT ${item.index + 1}`
            ).trim();
            const rangeLabel = `${item.start.toFixed(1)}s → ${item.end.toFixed(1)}s`;
            return `
              <b data-temporal-shot="${h(item.index)}" data-shot-order="${h(item.order)}" data-duration="${h(item.duration)}" style="flex:${width};" title="${h(label)} · ${h(rangeLabel)}">
                <span>${h(item.index + 1)}</span>
                <small>${h(item.start.toFixed(1))}</small>
                <i class="temporal-shot-resize" data-action="temporal-shot-resize" data-temporal-shot="${h(item.index)}" data-shot-order="${h(item.order)}" aria-hidden="true"></i>
              </b>
            `;
          })
          .join("")}
      </div>
    </div>
  `;
}

function renderSceneShotEditor(scene) {
  const shots = sceneShots(scene);
  if (!shots.length) return "";
  return `
    <div class="editor-block">
      <div class="editor-block-title">Shot overrides</div>
      <div class="shot-editor-list">
        ${shots
          .map((shot, index) => {
            const order = Number(shot.shot_order || index + 1);
            const label = String(shot.label || shot.beat_type || `SHOT ${order}`).trim();
            return `
              <div class="shot-editor-row">
                <div class="shot-editor-label">
                  <strong>${h(label)}</strong>
                  <span>${h(shot.beat_type || `#${order}`)}</span>
                </div>
                ${fieldNumber(shotEditorId(order, "Duration"), "Duration", shot.duration_seconds ?? 1, 'min="0.25" max="120" step="0.05"')}
                ${fieldSelect(shotEditorId(order, "Camera"), "Camera", cameraOptions, shot.camera_movement || scene.camera_movement || "slow_push_in")}
                ${fieldNumber(shotEditorId(order, "Zoom"), "Zoom", shot.zoom ?? 1, 'min="1" max="3" step="0.01"')}
                ${fieldNumber(shotEditorId(order, "Speed"), "Speed", shot.camera_speed ?? scene.camera_speed ?? 1, 'min="0.1" max="5" step="0.05"')}
              </div>
            `;
          })
          .join("")}
      </div>
    </div>
  `;
}

function renderSceneAudioManifestEditor(scene) {
  const manifest = sceneAudioManifest(scene);
  const trigger = sceneSfxTrigger(scene);
  return `
    <div class="editor-block">
      <div class="editor-block-title">声音资产轨</div>
      <div class="form-grid">
        ${fieldSelect("sceneBgmStyleInput", "BGM 风格", bgmStyles, manifest.bgm_style || "")}
        ${fieldSelect("sceneBgmFileInput", "BGM 文件", bgmFiles, manifest.bgm_file || "")}
        ${fieldNumber("sceneBgmGainInput", "BGM 增益 dB", manifest.bgm_gain_db ?? -12, 'min="-60" max="0" step="1"')}
        ${fieldText("sceneSfxTypeInput", "兜底音效", scene.sfx_type || "auto")}
        ${fieldText("sceneSfxFileInput", "触发音效文件", trigger.file || "")}
        ${fieldNumber("sceneSfxTimestampInput", "触发毫秒", trigger.timestamp_ms ?? 0, 'min="0" max="120000" step="50"')}
        ${fieldNumber("sceneSfxVolumeInput", "触发音量", trigger.volume ?? 0.65, 'min="0" max="2" step="0.05"')}
      </div>
    </div>
  `;
}

function renderSceneReadiness(scene) {
  const assets = scene.assets || {};
  const versions = assets.versions || {};
  const recentFailure = (scene.history || []).find((item) =>
    ["failed", "error"].includes(String(item.status || "").toLowerCase())
  );
  const directorReady = Boolean(scene.camera_movement || scene.director_recommendation);
  return `
    <div class="scene-status-grid asset-status-badges">
      ${renderAssetStatusCard("图", assets.image_url, versions.image, "图片")}
      ${renderAssetStatusCard("音", assets.audio_url, versions.audio, "音频")}
      ${renderAssetStatusCard("视", assets.video_url, versions.video, "视频")}
      ${renderAssetStatusCard("导", directorReady ? "#director" : "", scene.camera_speed || 1, "导演")}
    </div>
    ${recentFailure ? `<div class="scene-alert">最近失败：${h(recentFailure.message || recentFailure.label || recentFailure.action || "未知错误")}</div>` : ""}
  `;
}

function renderAssetStatusCard(label, url, version, title = label) {
  const ready = Boolean(url);
  const body = `
    <span class="asset-dot ${ready ? "ok" : ""}"></span>
    <div>
      <strong>${h(label)}</strong>
      <small>${ready ? `v${h(version || 1)}` : "缺失"}</small>
    </div>
  `;
  if (ready && String(url).startsWith("/")) {
    return `<a class="scene-status-card ok" href="${h(url)}" target="_blank" rel="noreferrer" title="${h(title)}">${body}</a>`;
  }
  return `<div class="scene-status-card ${ready ? "ok" : "missing"}" title="${h(title)}">${body}</div>`;
}

function renderProductionMeta(scene, project) {
  const totalScenes = (project.scenes || []).length;
  const phase = scene.episode_phase
    ? `${scene.episode_phase} ${scene.episode_phase_index || ""}/${scene.episode_phase_total || totalScenes}`
    : "未分配";
  return `
    <div class="production-meta-grid">
      <div class="meta-tile"><span>镜头</span><strong>${h(scene.camera_movement || "未设置")}</strong></div>
      <div class="meta-tile"><span>节奏</span><strong>${h(scene.episode_rhythm || "默认")}</strong></div>
      <div class="meta-tile"><span>段落</span><strong>${h(phase)}</strong></div>
      <div class="meta-tile"><span>声线</span><strong>${h(scene.voice_engine || "auto")} · ${h(scene.voice_id || scene.voice_profile || "未设置")}</strong></div>
      <div class="meta-tile"><span>参数</span><strong>速 ${h(scene.voice_rate ?? 1)} / 调 ${h(scene.voice_pitch ?? 0)} / 音 ${h(scene.voice_volume ?? 1)}</strong></div>
      <div class="meta-tile"><span>角色</span><strong>${h((scene.characters || []).join(", ") || "未设置")}</strong></div>
    </div>
  `;
}

function renderAssetLinks(scene) {
  const assets = scene.assets || {};
  const link = (label, url) =>
    url
      ? `<a href="${h(url)}" target="_blank" rel="noreferrer">${h(label)}</a>`
      : `<span>${h(label)}：缺失</span>`;
  return `<div class="asset-links">${link("图片", assets.image_url)}${link("音频", assets.audio_url)}${link("视频", assets.video_url)}</div>`;
}

function renderSceneHistory(scene) {
  const history = (scene.history || []).slice(0, 5);
  if (!history.length) return "";
  return `<div class="preview-list">${history.map((item) => `<div class="preview-card"><div class="item-title">${h(item.label || item.action || "记录")}</div><div class="item-meta">${h(item.status || "")} · ${h(item.ts || "")}</div><div class="item-meta">${h(item.message || "")}</div></div>`).join("")}</div>`;
}

export function renderExportView(project) {
  const output = project.output || {};
  return `
    <div class="split-grid">
      <section id="preflightSection" class="window-pane">
        <div class="window-head">合成与导出</div>
        <div class="window-body section-stack">
          ${renderExportReadiness(project)}
          ${renderOutputLinks(project)}
          <div class="row-actions">
            <button class="primary-button" type="button" data-action="build-project">生成整集</button>
            <button class="ghost-button" type="button" data-action="export-project">导出成片</button>
            <button class="ghost-button" type="button" data-action="fill-missing-assets">补齐素材</button>
            <button class="ghost-button" type="button" data-action="refresh-project">刷新状态</button>
          </div>
          <div class="muted">主链路：剧本拆解 -> 分镜 -> TTS -> 2.5D -> 合成。外部增强继续作为可选任务。</div>
        </div>
      </section>
      <section id="finalPreviewSection" class="window-pane">
        <div class="window-head">成片预览 <small>${h(output.status || "idle")}</small></div>
        <div class="window-body">
          ${output.final_video_url ? `<video class="final-video" controls playsinline src="${h(output.final_video_url)}"></video>` : `<div class="empty-state">暂无成片，先生成并导出。</div>`}
        </div>
      </section>
    </div>
  `;
}

function renderExportReadiness(project) {
  const entries = projectAssetGapEntries(project);
  const governanceEntries = (project.scenes || [])
    .filter(
      (scene) =>
        sceneGovernance(scene).deliverable === false &&
        sceneGovernance(scene).policy?.mode === "block"
    )
    .map((scene) => ({ scene, gaps: ["governance"] }));
  const allEntries = [...entries, ...governanceEntries];
  if (!allEntries.length) {
    return `
      <div class="scene-card">
        <div class="item-title">素材预检通过</div>
        <div class="item-meta">图片、音频和分镜视频均已就绪，可以生成整集或导出成片。</div>
      </div>
    `;
  }
  return `
    <div class="scene-card">
      <div class="item-title">素材预检未通过 · ${allEntries.length} 个分镜</div>
      <div class="item-meta">导出前需要先补齐以下缺口。</div>
      <div class="preview-list export-gap-list">
        ${allEntries
          .map(
            ({ scene, gaps }) => `
          <div class="preview-card">
            <div class="item-title">#${h(scene.order)} ${h(scene.title || "分镜")}</div>
            <div class="item-meta">${h(gaps.join(" / "))}</div>
          </div>
        `
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderOutputLinks(project) {
  const output = project.output || {};
  return `
    <div class="asset-links">
      ${output.final_video_url ? `<a href="${h(output.final_video_url)}" target="_blank" rel="noreferrer">最终视频</a>` : `<span>最终视频：缺失</span>`}
      ${output.subtitles_url ? `<a href="${h(output.subtitles_url)}" target="_blank" rel="noreferrer">SRT 字幕</a>` : `<span>SRT 字幕：缺失</span>`}
      ${output.subtitles_ass_url ? `<a href="${h(output.subtitles_ass_url)}" target="_blank" rel="noreferrer">ASS 字幕</a>` : ""}
      <span>状态：${h(output.status || "idle")}</span>
    </div>
  `;
}

function renderStylePickerModal(data = {}) {
  const styles = state.styles.list || [];
  const projectStyleId = state.project?.style_id || "";
  const tempSelected = data.tempSelected || projectStyleId || "";
  const filter = data.filter || "all";
  const filtered = styles.filter((style) => filter === "all" || style.category === filter);
  const selected = styles.find((style) => style.id === tempSelected) || null;
  const loading = state.styles.loading;
  return `
    <div class="modal-head">
      <div>
        <h3>选择风格</h3>
        <p class="modal-subtitle">为当前项目选择风格，后续资产和渲染都会沿用。</p>
      </div>
      <button class="ghost-button" type="button" data-action="modal-close" aria-label="关闭">×</button>
    </div>
    <div class="modal-body">
      <div class="style-filter-bar">
        <button type="button" class="${filter === "all" ? "is-active" : ""}" data-action="style-filter" data-filter="all">全部</button>
        <button type="button" class="${filter === "system" ? "is-active" : ""}" data-action="style-filter" data-filter="system">系统风格</button>
        <button type="button" class="${filter === "user" ? "is-active" : ""}" data-action="style-filter" data-filter="user">我的风格</button>
      </div>
      ${loading ? `<div class="modal-loading"><span class="asset-spinner"></span><span>正在加载风格库...</span></div>` : ""}
      ${!loading && !filtered.length ? `<div class="asset-empty-state"><div class="item-title">暂无风格</div><div class="item-meta">风格库为空，先检查后端数据。</div></div>` : ""}
      ${filtered.length ? `<div class="style-grid">${filtered.map((style) => renderStyleCard(style, style.id === tempSelected)).join("")}</div>` : ""}
    </div>
    <div class="modal-foot style-foot">
      <div class="style-preview">
        ${
          selected
            ? `
          <div class="style-preview-label">当前选择：${h(selected.name)}</div>
          <div class="style-preview-prompt">${h(selected.positive_suffix || "")}</div>
          ${selected.negative_suffix ? `<div class="style-preview-negative">${h(selected.negative_suffix)}</div>` : ""}
        `
            : `<div class="style-preview-empty">未选择风格</div>`
        }
      </div>
      <div class="modal-actions">
        <button class="ghost-button" type="button" data-action="modal-close">取消</button>
        <button class="primary-button" type="button" data-action="style-confirm" data-style-id="${h(tempSelected)}" ${tempSelected ? "" : "disabled"}>确认选择</button>
      </div>
    </div>
  `;
}

function renderStyleCard(style, isSelected) {
  const thumb = style.thumbnail
    ? `<img class="style-thumb-image" src="${h(style.thumbnail)}" alt="${h(style.name)}" onerror="this.remove()">`
    : "";
  return `
    <button type="button" class="style-card ${isSelected ? "is-selected" : ""}" data-action="style-pick" data-style-id="${h(style.id)}">
      <div class="style-thumb">
        <div class="style-thumb-placeholder">${h((style.name || "风格").slice(0, 2))}</div>
        ${thumb}
        <span class="style-tag">${h(style.category === "system" ? "系统" : "我的")}</span>
        ${isSelected ? `<span class="style-check">✓</span>` : ""}
      </div>
      <div class="style-name">${h(style.name)}</div>
      <div class="style-summary">${h(style.positive_suffix || "")}</div>
    </button>
  `;
}

function renderAssetAddModal(data = {}) {
  const type = data.type || state.assets.activeTab || "character";
  const form = data.form || { name: "", description: "", visual_prompt: "" };
  return `
    <div class="modal-head">
      <div>
        <h3>添加${h(assetTypeLabel(type))}</h3>
        <p class="modal-subtitle">先补一个简版条目，后续可以再单独编辑。</p>
      </div>
      <button class="ghost-button" type="button" data-action="modal-close" aria-label="关闭">×</button>
    </div>
    <div class="modal-body">
      <div class="asset-form">
        <label class="form-row">
          <span>名称</span>
          <input type="text" data-modal-field="name" value="${h(form.name || "")}" placeholder="例如：白云飘">
        </label>
        <label class="form-row">
          <span>描述</span>
          <textarea data-modal-field="description" rows="3" placeholder="简短描述">${h(form.description || "")}</textarea>
        </label>
        <label class="form-row">
          <span>视觉 prompt</span>
          <textarea data-modal-field="visual_prompt" rows="4" placeholder="英文绘图 prompt">${h(form.visual_prompt || "")}</textarea>
        </label>
      </div>
    </div>
    <div class="modal-foot">
      <button class="ghost-button" type="button" data-action="modal-close">取消</button>
      <button class="primary-button" type="button" data-action="asset-add-submit" data-asset-type="${h(type)}">添加</button>
    </div>
  `;
}
