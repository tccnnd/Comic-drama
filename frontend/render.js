// ─── DOM Rendering Functions ─────────────────────────────────────────────────

import {
  state,
  appRoot,
  tabs,
  assetTabs,
  voiceEngines,
  voiceSamples,
  voiceProfiles,
  voiceEmotions,
  bgmStyles,
  bgmFiles,
  planners,
  cameraOptions,
  reviewStatusOptions,
  reviewFilterOptions,
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
  canonicalPictureTrack,
  timelineSceneItems,
  characterKey,
  sceneCharacterNames,
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
  sceneReviewMeta,
  reviewStatusLabel,
  reviewStatusClass,
} from "./utils.js";
import { renderVoiceCatalogDatalist } from "./api.js";
import { stopTemporalPreview } from "./timeline.js";

export function render() {
  stopTemporalPreview();
  appRoot.innerHTML = renderShell();
  renderVoiceCatalogDatalist();
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
      <div class="modal-shell" data-modal-stop>
        ${body}
      </div>
    </div>
  `;
}

export function renderSidebar() {
  const project = state.project;
  const scenes = project ? (project.scenes || []) : [];
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
        ${project ? `
        <section class="window-pane sidebar-scenes">
          <div class="window-head">场景 <small>${scenes.length} 镜</small></div>
          <div class="window-body card-list">${scenes.map(renderSceneMiniNav).join("")}</div>
        </section>
        ` : ""}
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
        <a class="button-link" href="${h(finalUrl)}" target="_blank" rel="noreferrer" ${finalUrl === "#" ? "aria-disabled=\"true\"" : ""}>打开成片</a>
        <a class="button-link" href="${h(subtitlesUrl)}" target="_blank" rel="noreferrer" ${subtitlesUrl === "#" ? "aria-disabled=\"true\"" : ""}>字幕</a>
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
  const label = provider.label || provider.id || project.settings?.video_provider || "auto";
  const backend = provider.backend || "unknown";
  const ready = backend === "local" || missing === 0;
  const readiness = ready ? "ready" : `${missing} missing`;
  return `<span class="summary-chip provider-status ${ready ? "is-ready" : "is-missing"}" title="${h(`${configuredCount} configured, ${missing} missing`)}">Video: ${h(label)} / ${h(backend)} / ${h(readiness)}</span>`;
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
    .map(([key, label, section]) => `<button type="button" class="${state.activeTab === key ? "is-active" : ""}" data-action="switch-tab" data-tab="${h(key)}" data-jump-section="${h(section)}">${h(label)}</button>`)
    .join("")}</nav>`;
}

export function renderActiveView(project) {
  if (!project) {
    return `<section class="panel"><div class="panel-head">未选择项目</div><div class="panel-body"><div class="empty-state">请选择左侧项目，或创建一个新项目。</div></div></section>`;
  }
  if (state.activeTab === "plan") return renderPlanView(project);
  if (state.activeTab === "assets") return renderAssetsView(project);
  if (state.activeTab === "storyboard") return renderStoryboardView(project);
  if (state.activeTab === "produce") return renderProduceView(project);
  return renderPlanView(project);
}

// ─── Phase ① Plan View ───────────────────────────────────────────────────────
export function renderPlanView(project) {
  const scenes = timelineSceneItems(project);
  const summary = project.summary || {};
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

// ─── Phase ④ Produce View ────────────────────────────────────────────────────
export function renderProduceView(project) {
  const scenes = timelineSceneItems(project);
  const summary = project.summary || {};
  const totalScenes = scenes.length;
  const withImage = scenes.filter(s => s.assets?.image_path).length;
  const withAudio = scenes.filter(s => s.assets?.audio_path).length;
  const withVideo = scenes.filter(s => s.assets?.video_path).length;
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

export function renderOverviewView(project) {
  const scenes = timelineSceneItems(project);
  const summary = project.summary || {};
  const runtime = project.runtime || {};
  return `
    <div class="dashboard-grid">
      <section id="projectOverviewPanel" class="window-pane">
        <div class="window-head">项目总览 <small>${h(project.settings?.global_style || "竖屏动态漫画")}</small></div>
        <div class="window-body section-stack">
          <div class="overview-cards">
            <div class="metric-card"><div class="muted">分镜</div><div class="metric-value">${summary.total_scenes || scenes.length}</div></div>
            <div class="metric-card"><div class="muted">角色</div><div class="metric-value">${summary.total_characters || (project.characters || []).length}</div></div>
            <div class="metric-card"><div class="muted">预计时长</div><div class="metric-value">${formatSeconds(scenes.reduce((sum, scene) => sum + asNumber(scene.duration_seconds, 0), 0))}</div></div>
          </div>
          <div class="scene-card">
            <div class="item-title">故事文本</div>
            <div class="item-meta">${nl(String(project.story_text || "").slice(0, 600))}</div>
          </div>
          <div class="preview-list">${scenes.slice(0, 6).map(renderSceneMiniCard).join("")}</div>
        </div>
      </section>
      <section class="window-pane">
        <div class="window-head">流水线状态 <small>${h(runtime.updated_at || "")}</small></div>
        <div class="window-body section-stack">
          <span class="status-pill ${statusClass(runtime.status)}">${h(runtime.status || "idle")} · ${runtime.progress ?? 0}%</span>
          <div class="muted">${h(runtime.message || "等待操作")}</div>
          ${renderOutputLinks(project)}
          <div class="row-actions">
            <button class="primary-button" type="button" data-action="switch-tab" data-tab="workbench" data-jump-section="sceneWorkbenchSection">进入工作台</button>
            <button class="ghost-button" type="button" data-action="switch-tab" data-tab="script" data-jump-section="scriptRecognitionPanel">识别剧本</button>
          </div>
        </div>
      </section>
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
            ${fieldSelect("projectKeyframeInput", "关键帧引擎", [["auto", "自动"], ["local", "本地占位"], ["comfyui", "ComfyUI"]], settings.keyframe_provider || "auto")}
            ${fieldSelect("projectVoiceInput", "配音引擎", [["auto", "自动"], ["edge", "Edge"], ["local", "本地"], ["silent", "静音"]], settings.voice_provider || "auto")}
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
            ${fieldSelect("subtitleAlignmentInput", "位置", [["2", "底部居中"], ["8", "顶部居中"], ["5", "画面居中"]], subtitle.alignment ?? 2)}
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
      ${isCharacterTab ? `
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
      ` : ""}
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
      ${assetTabs.map(([key, _bucket, label]) => `
        <button class="${activeTab === key ? "is-active" : ""}" type="button" data-action="asset-tab" data-asset-tab="${h(key)}">
          <span>${h(label)}</span>
          <strong>${h(counts[key] || 0)}</strong>
        </button>
      `).join("")}
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
  const initials = String(asset.name || assetTypeLabel(type)).trim().slice(0, 2) || "资产";
  const thumbnail = asset.thumbnail ? `<img src="${h(asset.thumbnail)}" alt="">` : `<div class="asset-thumb-placeholder">${h(initials)}</div>`;
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
        ${type === "character" ? `<div class="asset-traits">${[asset.gender, asset.age, asset.personality].filter(Boolean).map((item) => `<span>${h(item)}</span>`).join("")}</div>` : ""}
      </div>
      <div class="asset-card-actions">
        <button class="ghost-button mini-button" type="button" data-action="asset-generate" data-asset-id="${h(asset.id)}" ${status === "generating" ? "disabled" : ""}>${status === "failed" ? "重试" : "生成"}</button>
      </div>
    </article>
  `;
}

function renderCharacterEditor(character, charIndex) {
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

export function renderTemplatesView() {
  return `
    <div class="split-grid">
      <section id="templateLibraryPanel" class="window-pane">
        <div class="window-head">外部 TTS / 视频增强</div>
        <div class="window-body section-stack">
          ${renderComfyUIStatus()}
          <div class="form-grid">
            ${fieldText("comfyuiBaseUrlInput", "ComfyUI URL", storedValue("comfyuiBaseUrl", "http://127.0.0.1:8188"))}
          </div>
          <div class="row-actions">
            <button class="primary-button" type="button" data-action="open-comfyui">打开 ComfyUI</button>
            <button class="ghost-button" type="button" data-action="save-comfyui-url">保存地址</button>
          </div>
          <div class="row-actions">
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
            <button class="ghost-button" type="button" data-action="refresh-all">刷新目录</button>
          </div>
          <div class="muted">ComfyUI / AnimateDiff / CogVideoX 继续作为可选增强层，不进入主链路。</div>
        </div>
      </section>
      <section class="window-pane">
        <div class="window-head">声线试听 <small>${state.voiceCatalog.length} 条目录</small></div>
        <div class="window-body section-stack">
          ${renderVoicePreviewForm()}
          ${renderVoicePreviewResult()}
        </div>
      </section>
    </div>
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

function renderVoicePreviewForm() {
  const scene = selectedScene();
  const character = selectedCharacter();
  const source = character || scene || {};
  return `
    <div class="form-grid">
      ${fieldSelect("voicePreviewEngineInput", "引擎", voiceEngines, source.voice_engine || "auto")}
      <label class="field"><span>Voice</span><input id="voicePreviewVoiceInput" list="voiceCatalogList" type="text" value="${h(source.voice_id || source.voice_profile || "zh-CN-XiaoxiaoNeural")}"></label>
      ${fieldNumber("voicePreviewRateInput", "语速", source.voice_rate ?? 1, 'min="0.5" max="2" step="0.05"')}
      ${fieldNumber("voicePreviewPitchInput", "音高", source.voice_pitch ?? 0, 'min="-24" max="24" step="0.5"')}
      ${fieldNumber("voicePreviewVolumeInput", "音量", source.voice_volume ?? 1, 'min="0" max="2" step="0.05"')}
      ${fieldText("voicePreviewEmotionInput", "情绪", source.emotion || "")}
      ${fieldText("voicePreviewReferenceAudioInput", "参考音频路径", source.reference_audio_path || "")}
      ${fieldTextarea("voicePreviewReferenceTextInput", "参考音频文本", source.reference_text || "", 3)}
      ${fieldTextarea("voicePreviewTextInput", "试听文本", scene?.dialogue || "这是一次漫剧配音试听。", 3)}
    </div>
    <button class="primary-button" type="button" data-action="preview-voice">生成试听</button>
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
      <section id="sceneWorkbenchSection" class="window-pane workbench-secondary">
        <div class="window-head">时间轴<small>拖拽片段右侧手柄调整时长</small></div>
        <div class="window-body">${renderTimelinePanel(project)}</div>
      </section>
      <section id="storyboardReviewSection" class="window-pane workbench-secondary">
        <div class="window-head">Storyboard review <small>canonical timeline 实片台</small></div>
        <div class="window-body">${renderStoryboardReviewCanvas(project)}</div>
      </section>
      </div>
      ${renderSelectedSceneWindow(project)}
    </div>
  `;
}

export function renderSceneView(project) {
  return renderSelectedSceneWindow(project);
}

function renderSceneCard(scene) {
  const active = Number(scene.order) === Number(state.selectedSceneOrder) ? "is-active" : "";
  const gaps = sceneAssetGaps(scene);
  const failed = Boolean(scene.validation_failed || String(scene.assets?.status || "").toLowerCase() === "failed");
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
  const total = Math.max(1, asNumber(timeline?.duration_seconds, 0) || scenes.reduce((sum, scene) => sum + asNumber(scene.duration_seconds, 4), 0));
  const width = Math.max(900, Math.round(total * TIMELINE_PX_PER_SECOND));
  const selected = scenes.find((scene) => Number(scene.order) === Number(state.selectedSceneOrder)) || scenes[0] || selectedScene(project);
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
    marks.push(`<div class="ruler-mark" style="left:${Math.round(second * TIMELINE_PX_PER_SECOND)}px">${second}s</div>`);
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
  const span = hasStart || hasEnd ? ` @ ${hasStart ? formatSeconds(scene.start_seconds) : formatSeconds(0)} → ${hasEnd ? formatSeconds(scene.end_seconds) : formatSeconds(duration)}` : "";
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

export function renderStoryboardReviewCanvas(project) {
  const scenes = timelineSceneItems(project);
  if (!scenes.length) return `<div class="empty-state">暂无 canonical timeline。</div>`;
  const selected = selectedTimelineScene(project);
  const filter = state.reviewFilter || "all";
  const visibleScenes = filter === "all" ? scenes : scenes.filter((scene) => sceneReviewMeta(scene).status === filter);
  const summary = scenes.reduce((acc, scene) => {
    const meta = sceneReviewMeta(scene);
    acc[meta.status] = (acc[meta.status] || 0) + 1;
    return acc;
  }, {});
  const ledger = projectContinuityLedger(project);
  const counts = ledger.status_counts || {};
  const blocked = Number(ledger.blocked_scene_count || 0);
  return `
    <div class="storyboard-review">
      <div class="review-summary">
        <span>${h(scenes.length)} 镜</span>
        <span>通过 ${h(summary.approved || 0)}</span>
        <span>需修改 ${h(summary.needs_work || 0)}</span>
        <span>阻塞 ${h(summary.blocked || 0)}</span>
        <span>连贯 ${h(counts.pass || 0)} / ${h(counts.warn || 0)} / ${h(counts.fail || 0)}</span>
        ${blocked ? `<span class="danger-text">治理阻塞 ${h(blocked)}</span>` : ""}
      </div>
      <div class="review-filter-bar">
        ${reviewFilterOptions.map(([value, label]) => `
          <button class="filter-chip ${filter === value ? "is-active" : ""}" type="button" data-action="review-filter" data-review-filter="${h(value)}">${h(label)}</button>
        `).join("")}
      </div>
      <div class="storyboard-review-grid">
        ${visibleScenes.length ? visibleScenes.map(renderStoryboardReviewCard).join("") : `<div class="empty-state">当前筛选下没有分镜。</div>`}
      </div>
      <div class="storyboard-review-detail">
        ${renderStoryboardReviewDetail(selected)}
      </div>
    </div>
  `;
}

function selectedTimelineScene(project = state.project) {
  const scenes = timelineSceneItems(project);
  return scenes.find((scene) => Number(scene.order) === Number(state.selectedSceneOrder)) || scenes[0] || null;
}

function sceneGenerationMeta(scene) {
  return scene?.generation_meta && typeof scene.generation_meta === "object" ? scene.generation_meta : {};
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

function renderGenerationDetail(scene) {
  const meta = sceneGenerationMeta(scene);
  if (!Object.keys(meta).length) {
    return `<div class="generation-detail is-unknown"><strong>Generation</strong><span>Unknown provenance</span></div>`;
  }
  return `
    <div class="generation-detail ${generationBadgeClass(meta)}">
      <strong>${h(generationLabel(meta))}</strong>
      <span>${h(meta.provider_label || meta.provider_id || "provider unknown")} · ${h(meta.backend || "backend unknown")} · ${h(meta.attempts || 0)} attempt(s)</span>
      ${meta.error ? `<span class="danger-text">${h(meta.error)}</span>` : ""}
      ${Array.isArray(meta.warnings) && meta.warnings.length ? `<span>${h(meta.warnings[0])}</span>` : ""}
    </div>
  `;
}

function renderGovernanceBadge(scene) {
  const status = governanceStatus(scene);
  const governance = sceneGovernance(scene);
  const policy = governance.policy && typeof governance.policy === "object" ? governance.policy : {};
  const blocked = policy.mode === "block" && governance.deliverable === false;
  return `<div class="governance-badge ${governanceStatusClass(status)}${blocked ? " is-blocked" : ""}">${h(governanceStatusLabel(status))}${blocked ? " · blocked" : ""}</div>`;
}

function renderGovernanceDetail(scene) {
  const governance = sceneGovernance(scene);
  const status = governanceStatus(scene);
  const dimensions = governance.dimensions && typeof governance.dimensions === "object" ? governance.dimensions : {};
  const dimensionRows = ["character", "lighting", "environment", "prop", "camera"]
    .map((dimension) => {
      const data = dimensions[dimension] && typeof dimensions[dimension] === "object" ? dimensions[dimension] : {};
      const dimStatus = String(data.status || "not_evaluated");
      const score = Number.isFinite(Number(data.score)) ? Number(data.score).toFixed(2) : "0.00";
      return `<span class="governance-dimension ${governanceStatusClass(dimStatus)}" title="${h(data.reason || "")}">${h(dimension)} ${h(dimStatus)} ${h(score)}</span>`;
    })
    .join("");
  const policy = governance.policy && typeof governance.policy === "object" ? governance.policy : {};
  const offenders = Array.isArray(governance.offending_dimensions) ? governance.offending_dimensions : [];
  return `
    <div class="governance-detail ${governanceStatusClass(status)}">
      <strong>${h(governanceStatusLabel(status))}</strong>
      <span>${h(policy.mode || "report")} · ${h(policy.action || "recorded")} · ${governance.deliverable === false ? "not deliverable" : "deliverable"}</span>
      <div class="governance-dimension-grid">${dimensionRows}</div>
      ${offenders.length ? `<span class="danger-text">${h(offenders.join(" / "))}</span>` : ""}
    </div>
  `;
}

function renderStoryboardReviewCard(scene) {
  const assets = scene.assets || {};
  const active = Number(scene.order) === Number(state.selectedSceneOrder) ? "is-active" : "";
  const meta = sceneReviewMeta(scene);
  const sClass = reviewStatusClass(meta.status);
  const media = assets.image_url
    ? `<img src="${h(assets.image_url)}" alt="">`
    : assets.video_url
      ? `<video src="${h(assets.video_url)}" muted playsinline preload="metadata"></video>`
      : `<span>暂无画面</span>`;
  return `
    <button class="storyboard-review-card ${active}" type="button" data-action="select-scene" data-scene-order="${h(scene.order)}">
      <div class="storyboard-thumb">${media}</div>
      <div class="storyboard-review-card-body">
        ${renderGenerationBadge(scene)}
        ${renderGovernanceBadge(scene)}
        <div class="storyboard-review-card-title">#${h(scene.order)} ${h(scene.title || "分镜")}</div>
        <div class="storyboard-review-card-meta">${formatSeconds(scene.duration_seconds)} · ${h(scene.emotion_tone || scene.emotion || "")}</div>
        <div class="review-badge ${sClass}">${h(reviewStatusLabel(meta.status))}${meta.rating ? ` · ${h(meta.rating)}/5` : ""}</div>
      </div>
    </button>
  `;
}

function renderStoryboardReviewDetail(scene) {
  if (!scene) return `<div class="empty-state">请选择分镜。</div>`;
  const assets = scene.assets || {};
  const meta = sceneReviewMeta(scene);
  const media = assets.video_url
    ? `<video src="${h(assets.video_url)}" controls playsinline></video>`
    : assets.image_url
      ? `<img src="${h(assets.image_url)}" alt="">`
      : `<span>暂无画面</span>`;
  return `
    <div class="review-detail-preview">
      <div class="thumb-frame">${media}</div>
      <div class="section-stack">
        ${renderGenerationDetail(scene)}
        ${renderGovernanceDetail(scene)}
        <div class="item-title">#${h(scene.order)} ${h(scene.title || "分镜")}</div>
        <div class="muted">${formatSeconds(scene.duration_seconds)} · ${h(scene.camera_movement || "镜头")} · ${h(scene.emotion_tone || scene.emotion || "")}</div>
        <div>${nl(scene.dialogue || "暂无台词")}</div>
      </div>
    </div>
    <div class="review-form">
      ${fieldSelect("reviewStatusInput", "审片状态", reviewStatusOptions, meta.status)}
      ${fieldNumber("reviewRatingInput", "评分", meta.rating || "", 'min="0" max="5" step="0.5"')}
      ${fieldTextarea("reviewNoteInput", "导演备注", meta.note, 3, "记录画面、表演、连贯性或重做原因")}
      ${renderReviewCompare(scene)}
      <div class="row-actions">
        <button class="primary-button" type="button" data-action="save-scene-review">保存审片</button>
        ${meta.reviewed_at ? `<span class="muted">上次保存：${h(meta.reviewed_at)}</span>` : ""}
      </div>
    </div>
  `;
}

function renderReviewCompare(scene) {
  const assets = scene?.assets || {};
  const versions = assets.versions || {};
  const history = Array.isArray(scene?.history) ? scene.history.slice(0, 4) : [];
  return `
    <div class="review-compare">
      <div class="section-label">版本对比</div>
      <div class="review-version-row">
        <span>图 v${h(versions.image || 0)}</span>
        <span>音 v${h(versions.audio || 0)}</span>
        <span>视 v${h(versions.video || 0)}</span>
      </div>
      <div class="review-compare-links">
        ${assets.image_url ? `<a href="${h(assets.image_url)}" target="_blank" rel="noreferrer">图片</a>` : `<span>无图片</span>`}
        ${assets.audio_url ? `<a href="${h(assets.audio_url)}" target="_blank" rel="noreferrer">音频</a>` : `<span>无音频</span>`}
        ${assets.video_url ? `<a href="${h(assets.video_url)}" target="_blank" rel="noreferrer">视频</a>` : `<span>无视频</span>`}
      </div>
      ${history.length ? `
        <div class="review-history">
          ${history.map((item) => `
            <div>
              <strong>${h(item.label || item.action || "记录")}</strong>
              <span>${h(item.status || "")} · ${h(item.ts || "")}</span>
            </div>
          `).join("")}
        </div>
      ` : `<div class="muted">暂无历史版本记录。</div>`}
    </div>
  `;
}

function renderAssetQueueSummary(project) {
  const scenes = project?.scenes || [];
  const counts = scenes.reduce((acc, scene) => {
    for (const gap of sceneAssetGaps(scene)) {
      if (gap === "图片") acc.image += 1;
      if (gap === "音频") acc.audio += 1;
      if (gap === "视频") acc.video += 1;
    }
    return acc;
  }, { image: 0, audio: 0, video: 0 });
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
        ${items.map(({ scene, gaps }) => `
          <div class="preview-card">
            <div class="item-title">#${h(scene.order)} ${h(scene.title || "分镜")}</div>
            <div class="item-meta">${h(gaps.join(" / "))}</div>
            <div class="item-meta">${h(scene.speaker || "角色")} · ${formatSeconds(scene.duration_seconds)}</div>
          </div>
        `).join("")}
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
  const total = shots.reduce((sum, shot) => sum + Math.max(0.1, asNumber(shot.duration_seconds, 0)), 0) || 1;
  return `
    <div class="micro-track shot-track">
      ${shots
        .map((shot, index) => {
          const duration = Math.max(0.1, asNumber(shot.duration_seconds, 0.1));
          const label = String(shot.label || shot.beat_type || `SHOT ${index + 1}`).trim();
          const beatType = shotBeatClass(shot.beat_type || label);
          const width = Math.max(18, (duration / total) * 100);
          const caption = String(shot.caption || shot.bubble || shot.dialogue || shot.title || "").trim();
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
  const total = timeline.reduce((sum, item) => sum + item.duration, 0) || scene.duration_seconds || 1;
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
            const label = String(item.shot.label || item.shot.beat_type || `SHOT ${item.index + 1}`).trim();
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
  const recentFailure = (scene.history || []).find((item) => ["failed", "error"].includes(String(item.status || "").toLowerCase()));
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
  const phase = scene.episode_phase ? `${scene.episode_phase} ${scene.episode_phase_index || ""}/${scene.episode_phase_total || totalScenes}` : "未分配";
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
  const link = (label, url) => (url ? `<a href="${h(url)}" target="_blank" rel="noreferrer">${h(label)}</a>` : `<span>${h(label)}：缺失</span>`);
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
    .filter((scene) => sceneGovernance(scene).deliverable === false && sceneGovernance(scene).policy?.mode === "block")
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
        ${allEntries.map(({ scene, gaps }) => `
          <div class="preview-card">
            <div class="item-title">#${h(scene.order)} ${h(scene.title || "分镜")}</div>
            <div class="item-meta">${h(gaps.join(" / "))}</div>
          </div>
        `).join("")}
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
        ${selected ? `
          <div class="style-preview-label">当前选择：${h(selected.name)}</div>
          <div class="style-preview-prompt">${h(selected.positive_suffix || "")}</div>
          ${selected.negative_suffix ? `<div class="style-preview-negative">${h(selected.negative_suffix)}</div>` : ""}
        ` : `<div class="style-preview-empty">未选择风格</div>`}
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
