const API = {
  projects: "/api/projects",
  voiceCatalog: "/api/voice-catalog",
  ttsProviders: "/api/tts-providers",
  comfyuiStatus: "/api/comfyui/status",
  voicePreview: "/api/voice-preview",
  fillMissingAssets: "/api/projects",
  repairStoryText: "/api/projects",
  applyScriptPreview: "/api/projects",
};

const TIMELINE_PX_PER_SECOND = 72;
const MIN_SCENE_DURATION = 1;
const DEFAULT_CROP_BOX = { x: 0, y: 0, width: 1, height: 1 };

const state = {
  projects: [],
  project: null,
  currentProjectId: "",
  selectedSceneOrder: 1,
  selectedCharacterIndex: 1,
  activeTab: "overview",
  voiceCatalog: [],
  ttsProviders: {},
  comfyuiStatus: null,
  scriptPreview: null,
  voicePreview: null,
  modal: null,
  assets: {
    characters: [],
    scene_bgs: [],
    props: [],
    activeTab: "character",
    loading: false,
    loadedFor: "",
  },
  styles: {
    list: [],
    loaded: false,
    loading: false,
  },
  busy: false,
  busyText: "",
  projectPollTimer: null,
  fallbackPollTimer: null,
  eventSource: null,
  eventSourceProjectId: "",
  sseConnected: false,
  timelineDrag: null,
  sfxDrag: null,
  cropEditorSceneOrder: null,
  cropBoxDirty: false,
  toast: null,
  toastTimer: null,
};

const STORAGE_KEYS = {
  comfyuiBaseUrl: "comicdrama.comfyuiBaseUrl",
};

const appRoot = document.getElementById("app");
const voiceCatalogList = document.getElementById("voiceCatalogList");

const assetTabs = [
  ["character", "characters", "角色"],
  ["scene_bg", "scene_bgs", "场景"],
  ["prop", "props", "道具"],
];

const tabs = [
  ["overview", "项目总览", "projectOverviewPanel"],
  ["settings", "项目设置", "projectSettingsSection"],
  ["script", "剧本识别", "scriptRecognitionPanel"],
  ["assets", "角色与声线", "characterSection"],
  ["templates", "外部引擎", "templateLibraryPanel"],
  ["workbench", "分镜工作台", "sceneWorkbenchSection"],
  ["scene", "当前分镜", "selectedSceneSection"],
  ["export", "合成导出", "preflightSection"],
];

const voiceEngines = [
  ["auto", "自动"],
  ["edge", "Edge TTS"],
  ["local", "本地 pyttsx3"],
  ["cosyvoice", "CosyVoice"],
  ["gpt_sovits", "GPT-SoVITS"],
  ["fish", "Fish Speech"],
  ["indextts", "IndexTTS2"],
  ["silent", "静音"],
];

const planners = [
  ["auto", "自动"],
  ["rule", "规则"],
  ["llm", "LLM"],
];

const cameraOptions = [
  ["dramatic_push", "戏剧推镜"],
  ["melancholy_pan", "情绪横移"],
  ["establishing_tilt", "纵向升降"],
  ["slow_push_in", "慢推近"],
  ["slow_zoom_out", "慢拉远"],
  ["pan_left", "左移"],
  ["pan_right", "右移"],
  ["tilt_down", "下摇"],
  ["tilt_up", "上摇"],
  ["dramatic_reveal", "揭示"],
];

function h(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function nl(value) {
  return h(value).replaceAll("\n", "<br>");
}

function asNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function clamp(value, min = 0, max = 1) {
  return Math.min(max, Math.max(min, asNumber(value, min)));
}

function normalizeCropBox(cropBox) {
  const source = cropBox && typeof cropBox === "object" ? cropBox : DEFAULT_CROP_BOX;
  const width = clamp(source.width, 0.05, 1);
  const height = clamp(source.height, 0.05, 1);
  return {
    x: clamp(source.x, 0, 1 - width),
    y: clamp(source.y, 0, 1 - height),
    width,
    height,
  };
}

function cropBoxFromInputs(fallback = DEFAULT_CROP_BOX) {
  return normalizeCropBox({
    x: asNumber(getValue("sceneCropXInput", fallback.x), fallback.x),
    y: asNumber(getValue("sceneCropYInput", fallback.y), fallback.y),
    width: asNumber(getValue("sceneCropWidthInput", fallback.width), fallback.width),
    height: asNumber(getValue("sceneCropHeightInput", fallback.height), fallback.height),
  });
}

function cropPercent(value) {
  return `${(clamp(value) * 100).toFixed(2)}%`;
}

function formatSeconds(value) {
  return `${asNumber(value, 0).toFixed(1)}s`;
}

function looksGarbledScriptText(value) {
  const text = String(value ?? "").trim();
  if (!text) return false;
  if (/[A-Za-z\u4e00-\u9fff]/.test(text)) return false;
  const damagedMarks = (text.match(/[?�]/g) || []).length;
  return damagedMarks >= Math.max(4, Math.floor(text.length / 5));
}

function statusClass(status) {
  if (["completed", "done", "idle", "draft"].includes(String(status || "").toLowerCase())) return "ok";
  if (["failed", "error"].includes(String(status || "").toLowerCase())) return "danger";
  return "warn";
}

function previewSceneFieldId(order, field) {
  return `scriptPreviewScene${field}${order}`;
}

function splitPreviewCharacters(value) {
  return String(value ?? "")
    .split(/[,，;；\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function selectedScene(project = state.project) {
  const scenes = project?.scenes || [];
  return scenes.find((scene) => Number(scene.order) === Number(state.selectedSceneOrder)) || scenes[0] || null;
}

function selectedCharacter(project = state.project) {
  const characters = project?.characters || [];
  return characters[Math.max(0, Number(state.selectedCharacterIndex || 1) - 1)] || characters[0] || null;
}

function characterKey(value) {
  return String(value ?? "").trim().toLowerCase();
}

function characterNamesFromFieldValue(value) {
  return String(value ?? "")
    .split(/[,，\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function sceneCharacterNames(scene) {
  return Array.isArray(scene?.characters) ? scene.characters.map((item) => String(item ?? "").trim()).filter(Boolean) : [];
}

function renderCharacterPicker(scene, fieldId, project = state.project) {
  const characters = Array.isArray(project?.characters) ? project.characters : [];
  const selectedNames = new Set(sceneCharacterNames(scene).map(characterKey));
  const selectedCount = sceneCharacterNames(scene).length;
  const knownCharacters = characters
    .map((character, index) => ({
      index: index + 1,
      name: String(character?.name || `角色 ${index + 1}`).trim(),
    }))
    .filter((item) => item.name);
  const extraNames = sceneCharacterNames(scene).filter((name) => !knownCharacters.some((item) => characterKey(item.name) === characterKey(name)));
  return `
    <div class="character-picker" data-character-picker-field="${h(fieldId)}">
      <div class="character-picker-head">
        <div>
          <strong>角色标签</strong>
          <span>勾选后会同步到出场角色字段，保存分镜时一并写回。</span>
        </div>
        <div class="character-picker-actions">
          <button class="ghost-button mini-button" type="button" data-action="scene-character-select-all" data-character-field-id="${h(fieldId)}">全选</button>
          <button class="ghost-button mini-button" type="button" data-action="scene-character-clear" data-character-field-id="${h(fieldId)}">清空</button>
        </div>
      </div>
      <div class="character-tag-grid">
        ${knownCharacters.length ? knownCharacters
          .map((character) => {
            const checked = selectedNames.has(characterKey(character.name));
            return `
              <label class="character-tag ${checked ? "is-selected" : ""}" data-character-chip>
                <input
                  type="checkbox"
                  data-character-toggle
                  data-character-field-id="${h(fieldId)}"
                  data-character-name="${h(character.name)}"
                  ${checked ? "checked" : ""}
                >
                <span>${h(character.name)}</span>
              </label>
            `;
          })
          .join("")
          : `<div class="empty-state">当前角色库为空，先在角色库里补充角色特征卡。</div>`}
      </div>
      ${extraNames.length ? `<div class="character-tag-extras">${extraNames.map((name) => `<span class="badge warn">${h(name)}</span>`).join("")}</div>` : ""}
      <div class="item-meta">已选择 ${h(selectedCount)} 个角色。</div>
    </div>
  `;
}

function syncCharacterPickerField(fieldId, nextNames) {
  const field = document.getElementById(fieldId);
  if (field) {
    field.value = nextNames.join(", ");
  }
  const picker = document.querySelector(`[data-character-picker-field="${CSS?.escape ? CSS.escape(fieldId) : fieldId}"]`);
  if (picker) {
    picker.querySelectorAll(`[data-character-toggle][data-character-field-id="${CSS?.escape ? CSS.escape(fieldId) : fieldId}"]`).forEach((input) => {
      const chip = input.closest(".character-tag");
      if (chip) {
        chip.classList.toggle("is-selected", input.checked);
      }
    });
    const meta = picker.querySelector(".item-meta");
    if (meta) {
      meta.textContent = `已选择 ${nextNames.length} 个角色。`;
    }
  }
}

function setCharacterPickerSelection(fieldId, nextNames) {
  const target = new Set(nextNames.map(characterKey));
  document.querySelectorAll(`[data-character-toggle][data-character-field-id="${fieldId}"]`).forEach((input) => {
    input.checked = target.has(characterKey(input.dataset.characterName || input.value));
  });
  syncCharacterPickerField(fieldId, nextNames);
}

function handleCharacterPickerChange(target) {
  const fieldId = target?.dataset?.characterFieldId;
  if (!fieldId) return false;
  const picker = target.closest("[data-character-picker-field]");
  if (!picker) return false;
  const nextNames = Array.from(
    picker.querySelectorAll(`[data-character-toggle][data-character-field-id="${fieldId}"]:checked`)
  ).map((input) => String(input.dataset.characterName || input.value || "").trim()).filter(Boolean);
  syncCharacterPickerField(fieldId, nextNames);
  return true;
}

function setBusy(busy, text = "") {
  state.busy = busy;
  state.busyText = text;
  render();
}

function showToast(message, type = "ok") {
  state.toast = { message, type };
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.className = `toast is-visible ${type}`;
  toast.textContent = message;
  window.clearTimeout(state.toastTimer);
  state.toastTimer = window.setTimeout(() => {
    state.toast = null;
    toast.className = "toast";
    toast.textContent = "";
  }, 2800);
}

async function apiJson(url, options = {}) {
  const init = {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  };
  const response = await fetch(url, init);
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { detail: text };
    }
  }
  if (!response.ok) {
    const detail = payload?.detail || payload?.message || response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload;
}

function storedValue(key, fallback = "") {
  try {
    return window.localStorage.getItem(STORAGE_KEYS[key]) || fallback;
  } catch {
    return fallback;
  }
}

function setStoredValue(key, value) {
  try {
    window.localStorage.setItem(STORAGE_KEYS[key], String(value || ""));
  } catch {
    // ignore storage failures
  }
}

function normalizeExternalUrl(raw, fallback = "") {
  const value = String(raw || fallback || "").trim();
  if (!value) return "";
  try {
    const url = new URL(value);
    return url.toString().replace(/\/$/, "");
  } catch {
    return "";
  }
}

function comfyuiEditorUrl() {
  return normalizeExternalUrl(getValue("comfyuiBaseUrlInput", storedValue("comfyuiBaseUrl", "http://127.0.0.1:8188")), "http://127.0.0.1:8188");
}

function setCurrentProject(project) {
  const previousProjectId = state.currentProjectId;
  state.project = project;
  state.currentProjectId = project?.project_id || "";
  if (previousProjectId !== state.currentProjectId) {
    state.cropEditorSceneOrder = null;
    state.cropBoxDirty = false;
    state.assets = {
      ...state.assets,
      characters: [],
      scene_bgs: [],
      props: [],
      loading: false,
      loadedFor: "",
    };
    if (state.currentProjectId) {
      subscribeProjectEvents(state.currentProjectId);
    } else {
      unsubscribeProjectEvents();
    }
  } else if (state.currentProjectId && !state.eventSource && typeof EventSource !== "undefined") {
    subscribeProjectEvents(state.currentProjectId);
  }
  const scenes = project?.scenes || [];
  if (!scenes.some((scene) => Number(scene.order) === Number(state.selectedSceneOrder))) {
    state.selectedSceneOrder = scenes[0]?.order || 1;
  }
  const characters = project?.characters || [];
  if (state.selectedCharacterIndex < 1 || state.selectedCharacterIndex > characters.length) {
    state.selectedCharacterIndex = characters.length ? 1 : 0;
  }
}

const PROJECT_EVENT_FALLBACK_INTERVAL = 30000;

function subscribeProjectEvents(projectId) {
  if (!projectId) return;
  if (state.eventSource && state.eventSourceProjectId === projectId) return;
  unsubscribeProjectEvents();
  if (typeof EventSource === "undefined") {
    startFallbackProjectPoll(projectId);
    return;
  }

  const source = new EventSource(`${API.projects}/${encodeURIComponent(projectId)}/events`);
  state.eventSource = source;
  state.eventSourceProjectId = projectId;
  state.sseConnected = false;

  source.addEventListener("connected", () => {
    state.sseConnected = true;
    stopFallbackProjectPoll();
  });
  source.addEventListener("scene_updated", handleProjectEvent);
  source.addEventListener("scene_split", handleProjectEvent);
  source.addEventListener("scene_merged", handleProjectEvent);
  source.addEventListener("scene_restored", handleProjectEvent);
  source.addEventListener("project_updated", handleProjectEvent);
  source.addEventListener("final_stale_changed", handleProjectEvent);
  source.addEventListener("export_progress", handleProjectEvent);
  source.onerror = () => {
    state.sseConnected = false;
    startFallbackProjectPoll(projectId);
  };
}

function unsubscribeProjectEvents() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
  state.eventSourceProjectId = "";
  state.sseConnected = false;
  stopFallbackProjectPoll();
}

function startFallbackProjectPoll(projectId) {
  if (!projectId || state.fallbackPollTimer) return;
  state.fallbackPollTimer = window.setInterval(() => {
    if (state.sseConnected || state.currentProjectId !== projectId) return;
    refreshCurrentProject().catch((error) => console.warn("[project-events] fallback refresh failed", error));
  }, PROJECT_EVENT_FALLBACK_INTERVAL);
}

function stopFallbackProjectPoll() {
  if (!state.fallbackPollTimer) return;
  window.clearInterval(state.fallbackPollTimer);
  state.fallbackPollTimer = null;
}

function parseProjectEvent(event) {
  try {
    return JSON.parse(event.data);
  } catch (error) {
    console.warn("[project-events] invalid event payload", error);
    return null;
  }
}

function handleProjectEvent(event) {
  const payload = parseProjectEvent(event);
  if (!payload || payload.project_id !== state.currentProjectId) return;
  const data = payload.payload || {};

  if (payload.type === "scene_updated") {
    applySceneEvent(data.scene_order, data.scene);
    return;
  }
  if (["scene_split", "scene_merged", "scene_restored", "project_updated"].includes(payload.type)) {
    if (data.project) {
      setCurrentProject(data.project);
      render();
      if (payload.type === "project_updated" && state.activeTab === "assets" && state.currentProjectId) {
        loadAssets(state.currentProjectId, { force: true, silent: true }).catch((error) => console.warn("[asset-events] refresh failed", error));
      }
    } else {
      refreshCurrentProject().catch((error) => console.warn("[project-events] refresh failed", error));
    }
    return;
  }
  if (payload.type === "final_stale_changed" && state.project) {
    state.project.output = state.project.output || {};
    state.project.output.status = data.stale ? "stale" : "idle";
    render();
    return;
  }
  if (payload.type === "export_progress" && state.project) {
    state.project.runtime = state.project.runtime || {};
    state.project.runtime.progress = asNumber(data.progress, 0);
    state.project.runtime.message = data.message || state.project.runtime.message;
    render();
  }
}

function applySceneEvent(sceneOrder, scene) {
  if (!state.project || !scene) return;
  const scenes = state.project.scenes || [];
  const idx = scenes.findIndex((item) => Number(item.order) === Number(sceneOrder));
  if (idx < 0) {
    refreshCurrentProject().catch((error) => console.warn("[project-events] refresh failed", error));
    return;
  }
  scenes[idx] = scene;
  recomputeProjectSummary(state.project);
  render();
}

function recomputeProjectSummary(project) {
  const scenes = project?.scenes || [];
  const output = project?.output || {};
  const assetTotals = { image: 0, audio: 0, video: 0 };
  let completedScenes = 0;
  scenes.forEach((scene) => {
    const assets = scene.assets || {};
    if (assets.status === "completed") completedScenes += 1;
    if (assets.image_url) assetTotals.image += 1;
    if (assets.audio_url) assetTotals.audio += 1;
    if (assets.video_url) assetTotals.video += 1;
  });
  project.summary = {
    total_scenes: scenes.length,
    completed_scenes: completedScenes,
    total_characters: (project.characters || []).length,
    asset_totals: assetTotals,
    has_final_video: Boolean(output.final_video_url),
  };
}

async function loadProjects(selectNewest = true) {
  const projects = await apiJson(API.projects);
  state.projects = Array.isArray(projects) ? projects : [];
  if (state.currentProjectId && !state.projects.some((project) => project.project_id === state.currentProjectId)) {
    unsubscribeProjectEvents();
    state.currentProjectId = "";
    state.project = null;
  }
  if (!state.currentProjectId && selectNewest && state.projects.length) {
    await loadProject(state.projects[0].project_id);
    return;
  }
  render();
}

async function loadProject(projectId) {
  const project = await apiJson(`${API.projects}/${encodeURIComponent(projectId)}`);
  setCurrentProject(project);
  if (state.activeTab === "assets") {
    await loadAssets(project.project_id, { force: true, silent: true });
  }
  render();
}

async function refreshCurrentProject() {
  if (!state.currentProjectId) return loadProjects();
  await loadProject(state.currentProjectId);
}

function clearProjectPoll() {
  if (state.projectPollTimer) {
    window.clearTimeout(state.projectPollTimer);
    state.projectPollTimer = null;
  }
}

function projectIsBusy(project = state.project) {
  const status = String(project?.runtime?.status || "").toLowerCase();
  const stage = String(project?.runtime?.stage || "").toLowerCase();
  return ["queued", "running", "repairing"].includes(status) || stage === "repairing" || stage.startsWith("scene_");
}

async function refreshUntilProjectSettles(timeoutMs = 25000, intervalMs = 1600) {
  clearProjectPoll();
  const startedAt = Date.now();
  while (true) {
    if (!state.sseConnected) {
      await refreshCurrentProject();
    }
    if (!projectIsBusy()) return;
    if (Date.now() - startedAt >= timeoutMs) return;
    await new Promise((resolve) => {
      state.projectPollTimer = window.setTimeout(resolve, intervalMs);
    });
  }
}

async function loadVoiceCatalog() {
  try {
    const payload = await apiJson(API.voiceCatalog);
    state.voiceCatalog = Array.isArray(payload?.items) ? payload.items : [];
    renderVoiceCatalogDatalist();
  } catch (error) {
    console.warn(error);
  }
}

async function loadTtsProviders() {
  try {
    const payload = await apiJson(API.ttsProviders);
    state.ttsProviders = payload?.providers || {};
  } catch (error) {
    console.warn(error);
  }
}

async function loadComfyUIStatus() {
  try {
    state.comfyuiStatus = await apiJson(API.comfyuiStatus);
  } catch (error) {
    state.comfyuiStatus = {
      available: false,
      base_url: "http://127.0.0.1:8188",
      error: error.message || String(error),
      missing_nodes: [],
      registered_nodes: [],
    };
  }
  render();
}

async function loadAssets(projectId = state.currentProjectId, options = {}) {
  if (!projectId) return;
  if (!options.force && state.assets.loadedFor === projectId && !state.assets.loading) return;
  state.assets.loading = true;
  if (!options.silent) render();
  try {
    const payload = await apiJson(`${API.projects}/${encodeURIComponent(projectId)}/assets`);
    state.assets.characters = Array.isArray(payload?.characters) ? payload.characters : [];
    state.assets.scene_bgs = Array.isArray(payload?.scene_bgs) ? payload.scene_bgs : [];
    state.assets.props = Array.isArray(payload?.props) ? payload.props : [];
    state.assets.loadedFor = projectId;
  } catch (error) {
    showToast(error.message || String(error), "danger");
  } finally {
    state.assets.loading = false;
    render();
  }
}

async function loadStyles() {
  if (state.styles.loaded || state.styles.loading) return;
  state.styles.loading = true;
  render();
  try {
    const payload = await apiJson("/api/styles");
    state.styles.list = Array.isArray(payload?.styles) ? payload.styles : [];
    state.styles.loaded = true;
  } catch (error) {
    showToast(error.message || "加载风格库失败", "danger");
  } finally {
    state.styles.loading = false;
    render();
  }
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
          <input type="text" data-modal-field="name" value="${h(form.name || "")}" placeholder="例如：白云飞">
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

function buildFallbackAssetPayloads(project = state.project) {
  const payloads = { characters: [], scene_bgs: [], props: [] };
  const characters = Array.isArray(project?.characters) ? project.characters : [];
  for (const raw of characters) {
    const name = String(raw?.name || "").trim();
    if (!name) continue;
    payloads.characters.push({
      asset_type: "character",
      name,
      description: String(raw?.summary || raw?.description || "").trim(),
      visual_prompt: [raw?.appearance_core, raw?.clothing_style, raw?.description].filter(Boolean).map((item) => String(item).trim()).join(" "),
      age: String(raw?.meta?.age || "").trim(),
      gender: String(raw?.meta?.gender || raw?.meta?.sex || "").trim(),
      appearance: String(raw?.appearance_core || "").trim(),
      personality: String(raw?.summary || "").trim(),
      voice_id: String(raw?.voice_id || raw?.voice_profile || "").trim(),
      first_scene: Number(raw?.first_scene || 1),
    });
  }
  const scenes = Array.isArray(project?.scenes) ? project.scenes : [];
  for (const raw of scenes) {
    const name = String(raw?.title || raw?.scene_id || "").trim();
    if (!name) continue;
    payloads.scene_bgs.push({
      asset_type: "scene_bg",
      name,
      description: String(raw?.visual_prompt || raw?.dialogue || "").trim(),
      visual_prompt: String(raw?.visual_prompt || raw?.title || "").trim(),
      first_scene: Number(raw?.order || 1),
    });
  }
  return payloads;
}

async function handleAssetExtract(projectId = state.currentProjectId) {
  if (!projectId) return;
  state.assets.loading = true;
  render();
  try {
    const payload = await apiJson(`${API.projects}/${encodeURIComponent(projectId)}/assets/extract`, { method: "POST", body: "{}" });
    const assets = payload?.assets || {};
    state.assets.characters = Array.isArray(assets.characters) ? assets.characters : state.assets.characters;
    state.assets.scene_bgs = Array.isArray(assets.scene_bgs) ? assets.scene_bgs : state.assets.scene_bgs;
    state.assets.props = Array.isArray(assets.props) ? assets.props : state.assets.props;
    state.assets.loadedFor = projectId;
    const added = payload?.added_counts || {};
    showToast(`宸叉彁鍙栵細瑙掕壊 ${added.characters || 0} / 鍦烘櫙 ${added.scene_bgs || 0} / 閬撳叿 ${added.props || 0}`);
  } catch {
    const fallback = buildFallbackAssetPayloads(state.project);
    const existing = new Set([
      ...state.assets.characters.map((asset) => characterKey(asset.name)),
      ...state.assets.scene_bgs.map((asset) => characterKey(asset.name)),
      ...state.assets.props.map((asset) => characterKey(asset.name)),
    ]);
    let addedCount = 0;
    for (const [bucket, items] of Object.entries(fallback)) {
      for (const item of items) {
        const nameKey = characterKey(item.name);
        if (!nameKey || existing.has(nameKey)) continue;
        const asset = await apiJson(`${API.projects}/${encodeURIComponent(projectId)}/assets`, {
          method: "POST",
          body: JSON.stringify(item),
        });
        state.assets[bucket].push(asset);
        existing.add(nameKey);
        addedCount += 1;
      }
    }
    state.assets.loadedFor = projectId;
    showToast(`LLM 不可用，已本地提取 ${addedCount} 个资产`);
  } finally {
    state.assets.loading = false;
    render();
  }
}

function updateLocalAsset(assetId, patch) {
  for (const bucket of ["characters", "scene_bgs", "props"]) {
    const index = state.assets[bucket].findIndex((asset) => asset.id === assetId);
    if (index >= 0) {
      state.assets[bucket][index] = { ...state.assets[bucket][index], ...patch };
      return state.assets[bucket][index];
    }
  }
  return null;
}

async function handleAssetGenerate(projectId = state.currentProjectId, assetId) {
  if (!projectId || !assetId) return;
  updateLocalAsset(assetId, { status: "generating" });
  render();
  try {
    const payload = await apiJson(`${API.projects}/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/generate`, { method: "POST", body: "{}" });
    if (payload?.asset) updateLocalAsset(assetId, payload.asset);
    showToast(payload?.message || "资产已生成");
  } catch (error) {
    updateLocalAsset(assetId, { status: "failed" });
    throw error;
  } finally {
    render();
  }
}

async function handleAssetGenerateAll(projectId = state.currentProjectId) {
  if (!projectId) return;
  for (const bucket of ["characters", "scene_bgs", "props"]) {
    state.assets[bucket] = state.assets[bucket].map((asset) => ({ ...asset, status: "generating" }));
  }
  render();
  try {
    const payload = await apiJson(`${API.projects}/${encodeURIComponent(projectId)}/assets/generate-all`, { method: "POST", body: "{}" });
    const assets = payload?.assets || {};
    state.assets.characters = Array.isArray(assets.characters) ? assets.characters : state.assets.characters;
    state.assets.scene_bgs = Array.isArray(assets.scene_bgs) ? assets.scene_bgs : state.assets.scene_bgs;
    state.assets.props = Array.isArray(assets.props) ? assets.props : state.assets.props;
    showToast(payload?.message || "资产已批量生成");
  } catch (error) {
    for (const bucket of ["characters", "scene_bgs", "props"]) {
      state.assets[bucket] = state.assets[bucket].map((asset) => asset.status === "generating" ? { ...asset, status: "failed" } : asset);
    }
    throw error;
  } finally {
    render();
  }
}

async function handleAssetAdd(projectId = state.currentProjectId) {
  if (!projectId) return;
  const active = state.assets.activeTab || "character";
  const label = assetTypeLabel(active);
  const name = window.prompt(`请输入${label}名称`);
  if (!name || !name.trim()) return;
  const payload = {
    asset_type: active,
    name: name.trim(),
    first_scene: Number(state.selectedSceneOrder || 1),
  };
  const asset = await apiJson(`${API.projects}/${encodeURIComponent(projectId)}/assets`, { method: "POST", body: JSON.stringify(payload) });
  const bucket = (assetTabs.find(([key]) => key === active) || assetTabs[0])[1];
  state.assets[bucket] = [...state.assets[bucket], asset];
  state.assets.loadedFor = projectId;
  showToast(`${label}已添加`);
  render();
}

function openAssetAddModal() {
  const active = state.assets.activeTab || "character";
  openModal("asset-add", {
    type: active,
    form: {
      name: "",
      description: "",
      visual_prompt: "",
    },
  });
}

async function handleAssetAddSubmit(projectId = state.currentProjectId) {
  if (!projectId || !state.modal?.data) return;
  const type = state.modal.data.type || state.assets.activeTab || "character";
  const form = state.modal.data.form || {};
  const name = String(form.name || "").trim();
  if (!name) {
    showToast("请输入名称", "danger");
    return;
  }
  try {
    const asset = await apiJson(`${API.projects}/${encodeURIComponent(projectId)}/assets`, {
      method: "POST",
      body: JSON.stringify({
        asset_type: type,
        name,
        description: String(form.description || "").trim(),
        visual_prompt: String(form.visual_prompt || "").trim(),
        first_scene: Number(state.selectedSceneOrder || 1),
      }),
    });
    const bucket = (assetTabs.find(([key]) => key === type) || assetTabs[0])[1];
    state.assets[bucket] = [...state.assets[bucket], asset];
    state.assets.loadedFor = projectId;
    closeModal();
    showToast(`${assetTypeLabel(type)}已添加`);
    render();
  } catch (error) {
    showToast(error.message || "添加失败", "danger");
  }
}

function selectAssetCard(assetType, assetName) {
  if (assetType !== "character") return;
  const name = characterKey(assetName);
  if (!name) return;
  const characters = state.project?.characters || [];
  const index = characters.findIndex((character) => characterKey(character?.name) === name);
  if (index >= 0) {
    state.selectedCharacterIndex = index + 1;
  }
}

function renderVoiceCatalogDatalist() {
  if (!voiceCatalogList) return;
  voiceCatalogList.innerHTML = state.voiceCatalog
    .slice(0, 180)
    .map((item) => `<option value="${h(item.short_name || item.ShortName || "")}">${h(item.friendly_name || item.FriendlyName || "")}</option>`)
    .join("");
}

function fieldText(id, label, value = "", placeholder = "") {
  return `<label class="field"><span>${h(label)}</span><input id="${h(id)}" type="text" value="${h(value)}" placeholder="${h(placeholder)}"></label>`;
}

function fieldNumber(id, label, value = "", attrs = "") {
  return `<label class="field"><span>${h(label)}</span><input id="${h(id)}" type="number" value="${h(value)}" ${attrs}></label>`;
}

function fieldTextarea(id, label, value = "", rows = 4, placeholder = "") {
  return `<label class="field full"><span>${h(label)}</span><textarea id="${h(id)}" rows="${rows}" placeholder="${h(placeholder)}">${h(value)}</textarea></label>`;
}

function fieldSelect(id, label, options, value = "") {
  return `<label class="field"><span>${h(label)}</span><select id="${h(id)}">${options
    .map(([optionValue, optionLabel]) => `<option value="${h(optionValue)}" ${String(optionValue) === String(value) ? "selected" : ""}>${h(optionLabel)}</option>`)
    .join("")}</select></label>`;
}

function fieldCheckbox(id, label, checked) {
  return `<label class="toggle-field"><input id="${h(id)}" type="checkbox" ${checked ? "checked" : ""}><span>${h(label)}</span></label>`;
}

function titleFromFilename(filename) {
  const base = String(filename || "")
    .replace(/\.[^.]+$/, "")
    .trim();
  if (!base) return "";
  return base.replace(/[._-]+/g, " ").replace(/\s+/g, " ").trim();
}

async function readTextFile(file) {
  const bytes = await file.arrayBuffer();
  const encodings = ["utf-8", "gb18030", "gbk", "utf-16le"];
  let lastError = null;
  for (const encoding of encodings) {
    try {
      const text = new TextDecoder(encoding, { fatal: false }).decode(bytes);
      if (text.trim()) return text;
    } catch (error) {
      lastError = error;
    }
  }
  if (lastError) throw lastError;
  return new TextDecoder().decode(bytes);
}

async function importScriptFile(file) {
  if (!file) return;
  const text = await readTextFile(file);
  if (state.project) {
    state.project.story_text = text;
    const suggestedTitle = titleFromFilename(file.name);
    if (suggestedTitle && !String(state.project.title || "").trim()) {
      state.project.title = suggestedTitle;
    }
  }
  const scriptTextarea = document.getElementById("scriptTextInput");
  if (scriptTextarea) scriptTextarea.value = text;
  const projectTextarea = document.getElementById("projectStoryInput");
  if (projectTextarea) projectTextarea.value = text;
  const titleInput = document.getElementById("scriptTitleInput");
  if (titleInput && !String(titleInput.value || "").trim()) {
    const suggestedTitle = titleFromFilename(file.name);
    if (suggestedTitle) titleInput.value = suggestedTitle;
  }
  state.scriptPreview = null;
  render();
  showToast(`已导入剧本：${file.name}`);
  if (state.currentProjectId) {
    previewScript().catch((error) => showToast(error.message, "danger"));
  }
}

function render() {
  appRoot.innerHTML = renderShell();
  renderVoiceCatalogDatalist();
}

function renderShell() {
  const project = state.project;
  return `
    <div class="shell" data-active-tab="${h(state.activeTab)}">
      ${renderSidebar()}
      <section class="workspace" data-active-tab="${h(state.activeTab)}">
        ${renderTopbar(project)}
        ${renderTabs()}
        <div class="content">${renderActiveView(project)}</div>
      </section>
    </div>
    <div id="toast" class="toast ${state.toast ? `is-visible ${h(state.toast.type)}` : ""}">${state.toast ? h(state.toast.message) : ""}</div>
    ${renderModal()}
  `;
}

function openModal(type, data = {}) {
  state.modal = { type, data };
  render();
}

function closeModal() {
  if (!state.modal) return;
  state.modal = null;
  render();
}

function renderModal() {
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

function renderSidebar() {
  return `
    <aside class="sidebar">
      <div class="sidebar-head">
        <h1 class="app-title">漫剧工作台</h1>
        <p class="app-caption">本地项目、脚本识别、分镜资产与时间轴。</p>
      </div>
      <div class="sidebar-scroll">
        <section class="window-pane">
          <div class="window-head">项目列表 <small>${state.projects.length} 个</small></div>
          <div class="window-body project-list">${renderProjectList()}</div>
        </section>
        <section class="window-pane">
          <div class="window-head">新建项目</div>
          <div class="window-body section-stack">
            ${fieldText("newProjectTitle", "标题", "", "例如：雨夜复仇")}
            ${fieldTextarea("newProjectStory", "故事 / 剧本", "", 7, "粘贴故事大纲或完整剧本")}
            <div class="form-grid">
              ${fieldSelect("newProjectPlanner", "拆解", planners, "auto")}
              ${fieldNumber("newProjectSceneCount", "分镜数", 5, 'min="1" max="12" step="1"')}
              ${fieldSelect("newProjectKeyframe", "生图", [["auto", "自动"], ["local", "本地占位"], ["comfyui", "ComfyUI"]], "auto")}
              ${fieldSelect("newProjectVoice", "配音", [["auto", "自动"], ["edge", "Edge"], ["local", "本地"], ["silent", "静音"]], "auto")}
            </div>
            <button class="primary-button" type="button" data-action="create-project">创建项目</button>
          </div>
        </section>
        <section class="window-pane">
          <div class="window-head">运行状态</div>
          <div class="window-body section-stack">
            <div class="status-pill ${state.busy ? "warn" : "ok"}">${h(state.busy ? state.busyText || "处理中" : "空闲")}</div>
            <div class="muted">声线目录：${state.voiceCatalog.length || 0} 条</div>
            <button type="button" class="ghost-button" data-action="refresh-all">刷新全部</button>
          </div>
        </section>
      </div>
    </aside>
  `;
}

function renderProjectList() {
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

function renderTopbar(project) {
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

function renderTabs() {
  return `<nav class="tabbar" aria-label="工作区导航">${tabs
    .map(([key, label, section]) => `<button type="button" class="${state.activeTab === key ? "is-active" : ""}" data-action="switch-tab" data-tab="${h(key)}" data-jump-section="${h(section)}">${h(label)}</button>`)
    .join("")}</nav>`;
}

function renderActiveView(project) {
  if (!project) {
    return `<section class="panel"><div class="panel-head">未选择项目</div><div class="panel-body"><div class="empty-state">请选择左侧项目，或创建一个新项目。</div></div></section>`;
  }
  if (state.activeTab === "settings") return renderSettingsView(project);
  if (state.activeTab === "script") return renderScriptView(project);
  if (state.activeTab === "assets") return renderAssetsView(project);
  if (state.activeTab === "templates") return renderTemplatesView(project);
  if (state.activeTab === "workbench") return renderWorkbenchView(project);
  if (state.activeTab === "scene") return renderSceneView(project);
  if (state.activeTab === "export") return renderExportView(project);
  return renderOverviewView(project);
}

function renderOverviewView(project) {
  const scenes = project.scenes || [];
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

function renderSettingsView(project) {
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
            <button class="ghost-button" type="button" data-action="refresh-project">放弃并刷新</button>
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

function renderScriptView(project) {
  const preview = state.scriptPreview;
  const scriptText = String(project.story_text || "");
  const scriptWarning = looksGarbledScriptText(scriptText)
    ? `<div class="preview-note">当前剧本文本看起来已经损坏成问号了。可以先点击“从分镜重建剧本”，再重新粘贴原文后预览或应用。</div>`
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
          ${preview ? renderScriptPreview(preview) : `<div class="empty-state">先点击“预览识别”，确认角色和分镜再应用。</div>`}
        </div>
      </section>
    </div>
  `;
}

function renderScriptPreview(preview) {
  const scenes = preview.scenes || [];
  return `
    <div class="scene-card">
      <div class="item-title">${h(preview.title || "未命名")}</div>
      <div class="item-meta">角色：${h((preview.analysis?.characters || []).map((item) => item.name || item).join("、"))}</div>
    </div>
    <div class="preview-list">${scenes
      .map((scene) => `
        <div class="preview-card">
          <div class="item-title">#${h(scene.order)} ${h(scene.title || "分镜")}</div>
          <div class="item-meta">${h(scene.speaker || "角色")} · ${formatSeconds(scene.duration_seconds)}</div>
          <div class="item-meta">${nl(scene.dialogue || "")}</div>
        </div>`)
      .join("")}</div>
  `;
}

function renderAssetsView(project) {
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
        <div class="window-head">资产库 <small>${state.assets.loading ? "同步中" : `${counts.character + counts.scene_bg + counts.prop} 个`}</small></div>
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
        <div class="window-head">批量操作 <small>阶段 2 生成接口为 stub</small></div>
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
        <div class="item-meta">点击“AI 智能提取”从剧本里生成资产清单，或使用“+ 添加”手动补充。</div>
      </div>
    `;
  }
  return `
    <div class="asset-card-grid" data-asset-grid-type="${h(type)}">
      ${assets.map((asset) => renderAssetCard(asset)).join("")}
    </div>
  `;
}

function assetStatusLabel(status) {
  if (status === "done") return "已完成";
  if (status === "generating") return "生成中";
  if (status === "failed") return "失败";
  return "待生成";
}

function assetTypeLabel(type) {
  if (type === "scene_bg") return "场景";
  if (type === "prop") return "道具";
  return "角色";
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
            <div class="asset-name">${h(asset.name || "未命名资产")}</div>
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

function renderCharacterCard(character, index) {
  const charIndex = index + 1;
  const importance = character.importance ?? 0;
  const firstScene = character.first_scene ?? 0;
  return `
    <button class="character-card ${charIndex === Number(state.selectedCharacterIndex) ? "is-active" : ""}" type="button" data-action="select-character" data-character-index="${charIndex}">
      <div class="item-title">${h(character.name || `角色 ${charIndex}`)}</div>
      <div class="item-meta">${h(character.voice_engine || character.suggested_voice_engine || "auto")} · ${h(character.voice_id || character.voice_profile || "未配置")}</div>
      <div class="item-meta">首见第 ${h(firstScene)} 段 · 重要度 ${h(importance)}${character.summary ? ` · ${h(character.summary)}` : ""}</div>
    </button>
  `;
}

function renderCharacterEditor(character, charIndex) {
  return `
    <div class="form-grid">
      ${fieldText("characterNameInput", "角色名", character.name || "")}
      ${fieldText("characterVoiceProfileInput", "声线标签", character.voice_profile || "")}
      ${fieldSelect("characterVoiceEngineInput", "引擎", voiceEngines, character.voice_engine || "auto")}
      ${fieldText("characterVoiceIdInput", "Voice ID", character.voice_id || "", "可填 Edge 短名或本地模型 ID")}
      ${fieldText("characterReferenceAudioInput", "参考音频路径", character.reference_audio_path || "")}
      ${fieldText("characterEmotionInput", "默认情绪", character.emotion || "")}
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

function renderTemplatesView() {
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
            ${fieldText("providerCosyVoiceInput", "CosyVoice URL", state.ttsProviders.cosyvoice || "")}
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
      ${fieldTextarea("voicePreviewReferenceTextInput", "参考文本", source.reference_text || "", 3)}
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

function renderWorkbenchView(project) {
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
      <section id="sceneWorkbenchSection" class="window-pane workbench-secondary">
        <div class="window-head">时间轴 <small>拖拽片段右侧手柄调整时长</small></div>
        <div class="window-body">${renderTimelinePanel(project)}</div>
      </section>
      ${renderSelectedSceneWindow(project)}
    </div>
  `;
}

function renderSceneView(project) {
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
      <div class="item-meta">${gaps.length ? `缺口：${gaps.join(" / ")}` : "资产已齐"} </div>
      <div class="item-meta">${h(String(scene.dialogue || "").slice(0, 80))}</div>
      ${failed ? `<div class="item-meta danger-text">${h(scene.error_message || "分镜校验失败")}</div>` : ""}
    </button>
  `;
}

function renderTimelinePanel(project) {
  const scenes = project.scenes || [];
  if (!scenes.length) return `<div class="empty-state">还没有分镜。</div>`;
  const total = Math.max(1, scenes.reduce((sum, scene) => sum + asNumber(scene.duration_seconds, 4), 0));
  const width = Math.max(900, Math.round(total * TIMELINE_PX_PER_SECOND));
  const selected = selectedScene(project);
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
  return `
    <div class="timeline-clip ${active}" style="width:${width}px" data-action="select-scene" data-scene-order="${h(scene.order)}">
      <div class="clip-title">#${h(scene.order)} ${h(scene.title || "分镜")}</div>
      <div class="clip-meta" data-clip-duration="${h(scene.order)}">${formatSeconds(duration)}</div>
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

function sceneAssetGaps(scene) {
  const assets = scene?.assets || {};
  const gaps = [];
  if (!assets.image_url) gaps.push("图片");
  if ((scene?.dialogue || "").trim() && !assets.audio_url) gaps.push("音频");
  if (!assets.video_url) gaps.push("视频");
  return gaps;
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

function renderSceneEditor(scene, project) {
  const assets = scene.assets || {};
  return `
    <div class="scene-editor">
      <div class="scene-stage-panel">
        ${renderSceneMedia(scene)}
        ${renderSceneClipInspector(scene)}
        ${renderCropEditor(scene)}
        ${renderSceneReadiness(scene)}
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
            ${fieldNumber("sceneDurationInput", "时长秒", scene.duration_seconds ?? 4, 'min="1" max="120" step="0.1"')}
            ${fieldText("sceneSpeakerInput", "说话人", scene.speaker || "")}
            ${fieldSelect("sceneCameraInput", "镜头", cameraOptions, scene.camera_movement || "slow_push_in")}
            ${fieldNumber("sceneCameraSpeedInput", "镜头速度", scene.camera_speed ?? 1, 'min="0.35" max="3" step="0.05"')}
            ${fieldText("sceneCharactersInput", "出场角色", (scene.characters || []).join(", "))}
            ${fieldText("sceneEmotionInput", "情绪", scene.emotion || "")}
            ${fieldTextarea("sceneVisualInput", "画面提示词", scene.visual_prompt || "", 6)}
            ${fieldTextarea("sceneDialogueInput", "台词", scene.dialogue || "", 4)}
          </div>
        </div>
        <div class="editor-block">
          <div class="editor-block-title">声线配置</div>
          <div class="form-grid">
            ${fieldSelect("sceneVoiceEngineInput", "配音引擎", voiceEngines, scene.voice_engine || "auto")}
            ${fieldText("sceneVoiceIdInput", "Voice ID", scene.voice_id || scene.voice_profile || "")}
            ${fieldText("sceneVoiceProfileInput", "声线标签", scene.voice_profile || "")}
            ${fieldText("sceneReferenceAudioInput", "参考音频", scene.reference_audio_path || "")}
            ${fieldNumber("sceneRateInput", "语速", scene.voice_rate ?? 1, 'min="0.5" max="2" step="0.05"')}
            ${fieldNumber("scenePitchInput", "音高", scene.voice_pitch ?? 0, 'min="-24" max="24" step="0.5"')}
            ${fieldNumber("sceneVolumeInput", "音量", scene.voice_volume ?? 1, 'min="0" max="2" step="0.05"')}
            ${fieldTextarea("sceneReferenceTextInput", "参考文本", scene.reference_text || "", 3)}
          </div>
        </div>
        ${renderSceneAudioManifestEditor(scene)}
        ${renderSceneHistory(scene)}
        ${renderVoicePreviewResult()}
      </div>
      <div class="scene-watermark">${h(assets.status || "pending")}</div>
    </div>
  `;
}

function renderSceneMedia(scene) {
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

function sceneAudioManifest(scene) {
  return scene?.audio_manifest && typeof scene.audio_manifest === "object" ? scene.audio_manifest : {};
}

function sceneSfxTrigger(scene) {
  const manifest = sceneAudioManifest(scene);
  return manifest.sfx_trigger && typeof manifest.sfx_trigger === "object" ? manifest.sfx_trigger : {};
}

function sceneDurationMs(scene) {
  return Math.max(250, Number(scene?.duration_seconds || 4) * 1000);
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
      <button class="ghost-button clip-rerender-button" type="button" data-action="rerender-video">重合成当前格</button>
    </div>
  `;
}

function cameraClassName(camera) {
  const value = String(camera || "").toLowerCase().replace(/[^a-z0-9_-]/g, "");
  if (["dramatic_push", "melancholy_pan", "establishing_tilt"].includes(value)) return value;
  if (value.includes("pan")) return "melancholy_pan";
  if (value.includes("tilt")) return "establishing_tilt";
  if (value.includes("push") || value.includes("reveal")) return "dramatic_push";
  return "slow_push_in";
}

function renderSceneAudioManifestEditor(scene) {
  const manifest = sceneAudioManifest(scene);
  const trigger = sceneSfxTrigger(scene);
  return `
    <div class="editor-block">
      <div class="editor-block-title">声音资产轨</div>
      <div class="form-grid">
        ${fieldText("sceneBgmStyleInput", "BGM 风格", manifest.bgm_style || "")}
        ${fieldText("sceneBgmFileInput", "BGM 文件", manifest.bgm_file || "")}
        ${fieldNumber("sceneBgmGainInput", "BGM 增益 dB", manifest.bgm_gain_db ?? "", 'min="-60" max="0" step="0.5"')}
        ${fieldText("sceneSfxTypeInput", "兜底音效", scene.sfx_type || "auto")}
        ${fieldText("sceneSfxFileInput", "触发音效文件", trigger.file || "")}
        ${fieldNumber("sceneSfxTimestampInput", "触发毫秒", trigger.timestamp_ms ?? 0, 'min="0" max="120000" step="50"')}
        ${fieldNumber("sceneSfxVolumeInput", "触发音量", trigger.volume ?? 0.65, 'min="0" max="2" step="0.05"')}
      </div>
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

function renderCropEditor(scene) {
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
  return `
    <div class="scene-status-card ${ready ? "ok" : "missing"}" title="${h(title)}">
      ${body}
    </div>
  `;
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
      <div class="meta-tile"><span>参数</span><strong>速${h(scene.voice_rate ?? 1)} / 调${h(scene.voice_pitch ?? 0)} / 音${h(scene.voice_volume ?? 1)}</strong></div>
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

function renderExportView(project) {
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

function projectAssetGapEntries(project) {
  return (project?.scenes || [])
    .map((scene) => ({ scene, gaps: sceneAssetGaps(scene) }))
    .filter((entry) => entry.gaps.length);
}

function projectHasAssetGaps(project = state.project) {
  return projectAssetGapEntries(project).length > 0;
}

function renderExportReadiness(project) {
  const entries = projectAssetGapEntries(project);
  if (!entries.length) {
    return `
      <div class="scene-card">
        <div class="item-title">素材预检通过</div>
        <div class="item-meta">图片、音频和分镜视频均已就绪，可以生成整集或导出成片。</div>
      </div>
    `;
  }
  return `
    <div class="scene-card">
      <div class="item-title">素材预检未通过 · ${entries.length} 个分镜</div>
      <div class="item-meta">导出前需要先补齐以下缺口。</div>
      <div class="preview-list export-gap-list">
        ${entries.map(({ scene, gaps }) => `
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

function focusFinalPreview() {
  requestAnimationFrame(() => {
    document.querySelector(".content")?.scrollTo({ top: 0, left: 0 });
    document.getElementById("finalPreviewSection")?.scrollIntoView({ block: "start", behavior: "smooth" });
  });
}

function getValue(id, fallback = "") {
  const element = document.getElementById(id);
  return element ? element.value : fallback;
}

function getChecked(id) {
  return Boolean(document.getElementById(id)?.checked);
}

function scenePatchPayload() {
  const scene = selectedScene();
  const cropBox = document.getElementById("sceneCropXInput")
    ? cropBoxFromInputs(normalizeCropBox(scene?.crop_box))
    : normalizeCropBox(scene?.crop_box);
  return {
    title: getValue("sceneTitleInput"),
    visual_prompt: getValue("sceneVisualInput"),
    dialogue: getValue("sceneDialogueInput"),
    speaker: getValue("sceneSpeakerInput"),
    voice_profile: getValue("sceneVoiceProfileInput"),
    voice_engine: getValue("sceneVoiceEngineInput"),
    voice_id: getValue("sceneVoiceIdInput"),
    reference_audio_path: getValue("sceneReferenceAudioInput"),
    reference_text: getValue("sceneReferenceTextInput"),
    emotion: getValue("sceneEmotionInput"),
    voice_rate: asNumber(getValue("sceneRateInput"), 1),
    voice_pitch: asNumber(getValue("scenePitchInput"), 0),
    voice_volume: asNumber(getValue("sceneVolumeInput"), 1),
    camera_movement: getValue("sceneCameraInput"),
    camera_speed: asNumber(getValue("sceneCameraSpeedInput"), scene?.camera_speed ?? 1),
    duration_seconds: Math.max(MIN_SCENE_DURATION, asNumber(getValue("sceneDurationInput"), 4)),
    characters: getValue("sceneCharactersInput").split(/[,，\n]/).map((item) => item.trim()).filter(Boolean),
    crop_box: cropBox,
    sfx_type: getValue("sceneSfxTypeInput", scene?.sfx_type || "auto"),
    audio_manifest: sceneAudioManifestPayload(scene),
  };
}

function sceneAudioManifestPayload(scene) {
  const current = scene?.audio_manifest && typeof scene.audio_manifest === "object" ? scene.audio_manifest : {};
  const currentTrigger = current.sfx_trigger && typeof current.sfx_trigger === "object" ? current.sfx_trigger : {};
  const triggerFile = getValue("sceneSfxFileInput", currentTrigger.file || "");
  const trigger = {
    file: triggerFile,
    timestamp_ms: Math.max(0, Math.round(asNumber(getValue("sceneSfxTimestampInput", currentTrigger.timestamp_ms || 0), 0))),
    volume: Math.max(0, asNumber(getValue("sceneSfxVolumeInput", currentTrigger.volume ?? 0.65), 0.65)),
  };
  return {
    ...current,
    bgm_style: getValue("sceneBgmStyleInput", current.bgm_style || ""),
    bgm_file: getValue("sceneBgmFileInput", current.bgm_file || ""),
    bgm_gain_db: getValue("sceneBgmGainInput", current.bgm_gain_db ?? ""),
    sfx_trigger: trigger,
    sfx_triggers: triggerFile ? [trigger] : Array.isArray(current.sfx_triggers) ? current.sfx_triggers : [],
  };
}

function projectPatchPayload() {
  const storyText =
    getValue("scriptTextInput") ||
    getValue("projectStoryInput", state.project?.story_text || "");
  return {
    title: getValue("projectTitleInput", state.project?.title || ""),
    story_text: storyText,
    settings: {
      planner: getValue("projectPlannerInput", state.project?.settings?.planner || "auto"),
      scene_count: Math.max(1, Math.round(asNumber(getValue("projectSceneCountInput"), 5))),
      keyframe_provider: getValue("projectKeyframeInput", state.project?.settings?.keyframe_provider || "auto"),
      voice_provider: getValue("projectVoiceInput", state.project?.settings?.voice_provider || "auto"),
      global_style: getValue("projectGlobalStyleInput", state.project?.settings?.global_style || ""),
      subtitle_style: {
        font_name: getValue("subtitleFontNameInput", "Microsoft YaHei"),
        font_size: Math.round(asNumber(getValue("subtitleFontSizeInput"), 34)),
        margin_v: Math.round(asNumber(getValue("subtitleMarginVInput"), 120)),
        outline: Math.round(asNumber(getValue("subtitleOutlineInput"), 2)),
        shadow: Math.round(asNumber(getValue("subtitleShadowInput"), 0)),
        alignment: Math.round(asNumber(getValue("subtitleAlignmentInput"), 2)),
        show_speaker: getChecked("subtitleSpeakerInput"),
        burn_in: getChecked("subtitleBurnInput"),
      },
      audio_style: {
        master_lufs: asNumber(getValue("audioLufsInput"), -16),
        true_peak: asNumber(getValue("audioTruePeakInput"), -1.5),
        limiter_level: asNumber(getValue("audioLimiterInput"), 0.98),
        bgm_gain_db: asNumber(getValue("audioBgmGainInput"), -18),
        duck_threshold: asNumber(getValue("audioDuckThresholdInput"), 0.08),
        duck_ratio: asNumber(getValue("audioDuckRatioInput"), 8),
        bgm_path: getValue("audioBgmPathInput", ""),
      },
    },
  };
}

function characterPatchPayload() {
  return {
    name: getValue("characterNameInput"),
    description: getValue("characterDescriptionInput"),
    voice_profile: getValue("characterVoiceProfileInput"),
    voice_engine: getValue("characterVoiceEngineInput"),
    voice_id: getValue("characterVoiceIdInput"),
    reference_audio_path: getValue("characterReferenceAudioInput"),
    reference_text: getValue("characterReferenceTextInput"),
    emotion: getValue("characterEmotionInput"),
    voice_rate: asNumber(getValue("characterRateInput"), 1),
    voice_pitch: asNumber(getValue("characterPitchInput"), 0),
    voice_volume: asNumber(getValue("characterVolumeInput"), 1),
  };
}

function voicePreviewPayload(source = "manual") {
  if (source === "scene") {
    const payload = scenePatchPayload();
    return {
      voice: payload.voice_id || payload.voice_profile || "zh-CN-XiaoxiaoNeural",
      text: payload.dialogue || "这是一次漫剧配音试听。",
      engine: payload.voice_engine || "auto",
      rate: payload.voice_rate,
      pitch: payload.voice_pitch,
      volume: payload.voice_volume,
      voice_id: payload.voice_id || "",
      reference_audio_path: payload.reference_audio_path || "",
      reference_text: payload.reference_text || "",
      emotion: payload.emotion || "",
    };
  }
  if (source === "character") {
    const payload = characterPatchPayload();
    return {
      voice: payload.voice_id || payload.voice_profile || "zh-CN-XiaoxiaoNeural",
      text: selectedScene()?.dialogue || "这是一次角色声线试听。",
      engine: payload.voice_engine || "auto",
      rate: payload.voice_rate,
      pitch: payload.voice_pitch,
      volume: payload.voice_volume,
      voice_id: payload.voice_id || "",
      reference_audio_path: payload.reference_audio_path || "",
      reference_text: payload.reference_text || "",
      emotion: payload.emotion || "",
    };
  }
  return {
    voice: getValue("voicePreviewVoiceInput", "zh-CN-XiaoxiaoNeural"),
    text: getValue("voicePreviewTextInput", "这是一次漫剧配音试听。"),
    engine: getValue("voicePreviewEngineInput", "auto"),
    rate: asNumber(getValue("voicePreviewRateInput"), 1),
    pitch: asNumber(getValue("voicePreviewPitchInput"), 0),
    volume: asNumber(getValue("voicePreviewVolumeInput"), 1),
    voice_id: getValue("voicePreviewVoiceInput", ""),
    reference_audio_path: getValue("voicePreviewReferenceAudioInput", ""),
    reference_text: getValue("voicePreviewReferenceTextInput", ""),
    emotion: getValue("voicePreviewEmotionInput", ""),
  };
}

function collectScriptPreviewDraft() {
  const preview = state.scriptPreview;
  if (!preview) {
    throw new Error("请先生成脚本预览");
  }
  const currentScriptText = String(getValue("scriptTextInput") || "");
  const previewScriptText = String(preview.script_text || "");
  if (previewScriptText && currentScriptText.trim() !== previewScriptText.trim()) {
    throw new Error("剧本内容已变更，请先重新预览再应用");
  }

  const scenes = Array.isArray(preview.scenes) ? preview.scenes : [];
  const draftedScenes = scenes.map((scene, index) => {
    const order = Number(scene.order || scene.index || index + 1);
    const characters = splitPreviewCharacters(getValue(previewSceneFieldId(order, "Characters"), (scene.characters || []).join(", ")));
    return {
      ...scene,
      order,
      title: getValue(previewSceneFieldId(order, "Title"), scene.title || ""),
      speaker: getValue(previewSceneFieldId(order, "Speaker"), scene.speaker || ""),
      camera_movement: getValue(previewSceneFieldId(order, "Camera"), scene.camera_movement || scene.camera || "slow_push_in"),
      emotion: getValue(previewSceneFieldId(order, "Emotion"), scene.emotion || ""),
      duration_seconds: Math.max(MIN_SCENE_DURATION, asNumber(getValue(previewSceneFieldId(order, "Duration"), scene.duration_seconds ?? scene.duration ?? 4), 4)),
      visual_prompt: getValue(previewSceneFieldId(order, "Visual"), scene.visual_prompt || scene.visual || ""),
      dialogue: getValue(previewSceneFieldId(order, "Dialogue"), scene.dialogue || ""),
      characters,
    };
  });

  return {
    title: getValue("scriptTitleInput", preview.title || state.project?.title || ""),
    story_text: currentScriptText,
    planner: getValue("scriptPlannerInput", "auto"),
    planner_used: preview.planner_used || getValue("scriptPlannerInput", "auto"),
    max_scenes: Math.max(1, Math.min(24, Math.round(asNumber(getValue("scriptMaxScenesInput"), scenes.length || 12)))),
    analysis: preview.analysis || {},
    scenes: draftedScenes,
  };
}

async function createProject() {
  if (state.scriptPreview) {
    setBusy(true, "搴旂敤鍓ф湰");
    try {
      const project = await apiJson(`${API.applyScriptPreview}/${state.currentProjectId}/apply-script-preview`, {
        method: "POST",
        body: JSON.stringify(collectScriptPreviewDraft()),
      });
      state.scriptPreview = null;
      setCurrentProject(project);
      state.activeTab = "workbench";
      showToast("鍓ф湰宸插簲鐢ㄥ埌鍒嗛暅");
    } finally {
      setBusy(false);
    }
    return;
  }
  const payload = {
    title: getValue("newProjectTitle"),
    story_text: getValue("newProjectStory"),
    planner: getValue("newProjectPlanner", "auto"),
    scene_count: Math.max(1, Math.min(12, Math.round(asNumber(getValue("newProjectSceneCount"), 5)))),
    keyframe_provider: getValue("newProjectKeyframe", "auto"),
    voice_provider: getValue("newProjectVoice", "auto"),
  };
  setBusy(true, "创建项目");
  try {
    const project = await apiJson(API.projects, { method: "POST", body: JSON.stringify(payload) });
    setCurrentProject(project);
    await loadProjects(false);
    showToast("项目已创建");
  } finally {
    setBusy(false);
  }
}

async function saveProject() {
  if (!state.currentProjectId) return;
  const payload = projectPatchPayload();
  setBusy(true, "保存项目");
  try {
    const project = await apiJson(`${API.projects}/${state.currentProjectId}`, { method: "PATCH", body: JSON.stringify(payload) });
    setCurrentProject(project);
    showToast("项目已保存");
  } finally {
    setBusy(false);
  }
}

async function deleteProject(projectId) {
  const targetId = projectId || state.currentProjectId;
  if (!targetId) return;
  const project = state.projects.find((item) => item.project_id === targetId) || (state.project?.project_id === targetId ? state.project : null);
  const title = project?.title || targetId;
  if (!window.confirm(`确认删除项目「${title}」？\n\n这会删除 workspace 中的项目文件夹，无法在应用内撤销。`)) {
    return;
  }
  setBusy(true, "删除项目");
  try {
    await apiJson(`${API.projects}/${encodeURIComponent(targetId)}`, { method: "DELETE" });
    if (state.currentProjectId === targetId) {
      unsubscribeProjectEvents();
      state.currentProjectId = "";
      state.project = null;
      state.scriptPreview = null;
      state.voicePreview = null;
    }
    await loadProjects(true);
    showToast("项目已删除");
  } finally {
    setBusy(false);
  }
}

async function patchScene(order, payload) {
  const project = await apiJson(`${API.projects}/${state.currentProjectId}/scenes/${order}`, { method: "PATCH", body: JSON.stringify(payload) });
  setCurrentProject(project);
}

async function saveScene() {
  const order = state.selectedSceneOrder;
  const payload = scenePatchPayload();
  setBusy(true, "保存分镜");
  try {
    await patchScene(order, payload);
    showToast("分镜已保存");
  } finally {
    setBusy(false);
  }
}

async function saveCropBox(cropBox = null) {
  const order = state.selectedSceneOrder;
  const scene = selectedScene();
  const payload = { crop_box: normalizeCropBox(cropBox || cropBoxFromInputs(normalizeCropBox(scene?.crop_box))) };
  setBusy(true, "保存取景框");
  try {
    await patchScene(order, payload);
    state.cropEditorSceneOrder = order;
    state.cropBoxDirty = false;
    showToast("取景框已保存");
  } finally {
    setBusy(false);
  }
}

async function resetCropBox() {
  setCropInputs(DEFAULT_CROP_BOX);
  updateCropOverlay(DEFAULT_CROP_BOX);
  await saveCropBox(DEFAULT_CROP_BOX);
}

async function saveTimelineSceneDuration(order, duration) {
  await patchScene(order, { duration_seconds: duration });
  showToast(`分镜 #${order} 时长已更新为 ${formatSeconds(duration)}`);
}

async function saveSceneSfxTimestamp(order, timestampMs) {
  const scene = (state.project?.scenes || []).find((item) => Number(item.order) === Number(order));
  if (!scene) return;
  const manifest = sceneAudioManifest(scene);
  const currentTrigger = sceneSfxTrigger(scene);
  const trigger = {
    ...currentTrigger,
    timestamp_ms: Math.max(0, Math.round(asNumber(timestampMs, currentTrigger.timestamp_ms || 0))),
    volume: currentTrigger.volume ?? 0.65,
  };
  const nextManifest = {
    ...manifest,
    sfx_trigger: trigger,
    sfx_triggers: trigger.file ? [trigger] : Array.isArray(manifest.sfx_triggers) ? manifest.sfx_triggers : [],
  };
  await patchScene(order, {
    audio_manifest: nextManifest,
    sfx_type: scene.sfx_type || "auto",
  });
  render();
  showToast(`音效锚点已移动到 ${trigger.timestamp_ms}ms，当前格视频需重合成`);
}

async function saveCharacter() {
  if (!state.currentProjectId || !state.selectedCharacterIndex) return;
  const payload = characterPatchPayload();
  setBusy(true, "保存角色");
  try {
    const project = await apiJson(`${API.projects}/${state.currentProjectId}/characters/${state.selectedCharacterIndex}`, { method: "PATCH", body: JSON.stringify(payload) });
    setCurrentProject(project);
    showToast("角色已保存");
  } finally {
    setBusy(false);
  }
}

async function previewVoice(source = "manual") {
  const payload = voicePreviewPayload(source);
  setBusy(true, "生成试听");
  try {
    state.voicePreview = await apiJson(API.voicePreview, { method: "POST", body: JSON.stringify(payload) });
    render();
    showToast("试听已生成");
  } finally {
    setBusy(false);
  }
}

async function previewScript() {
  if (!state.currentProjectId) return;
  const scriptText = getValue("scriptTextInput");
  if (looksGarbledScriptText(scriptText)) {
    showToast("剧本文本疑似损坏成问号了，请重新粘贴原文后再预览。", "danger");
    return;
  }
  const payload = {
    title: getValue("scriptTitleInput"),
    script_text: scriptText,
    script_hint: getValue("scriptHintInput"),
    planner: getValue("scriptPlannerInput", "auto"),
    max_scenes: Math.max(1, Math.min(24, Math.round(asNumber(getValue("scriptMaxScenesInput"), 12)))),
  };
  setBusy(true, "识别预览");
  try {
    state.scriptPreview = await apiJson(`${API.projects}/${state.currentProjectId}/recognize-script/preview`, { method: "POST", body: JSON.stringify(payload) });
    render();
    showToast("识别预览完成");
  } finally {
    setBusy(false);
  }
}

async function applyScript() {
  if (!state.currentProjectId) return;
  const scriptText = getValue("scriptTextInput");
  if (looksGarbledScriptText(scriptText)) {
    showToast("剧本文本疑似损坏成问号了，请重新粘贴原文后再应用。", "danger");
    return;
  }
  const payload = {
    title: getValue("scriptTitleInput"),
    script_text: scriptText,
    script_hint: getValue("scriptHintInput"),
    planner: getValue("scriptPlannerInput", "auto"),
    max_scenes: Math.max(1, Math.min(24, Math.round(asNumber(getValue("scriptMaxScenesInput"), 12)))),
  };
  setBusy(true, "应用剧本");
  try {
    const project = await apiJson(`${API.projects}/${state.currentProjectId}/recognize-script`, { method: "POST", body: JSON.stringify(payload) });
    state.scriptPreview = null;
    setCurrentProject(project);
    state.activeTab = "workbench";
    showToast("剧本已应用到分镜");
  } finally {
    setBusy(false);
  }
}

async function repairStoryText() {
  if (!state.currentProjectId) return;
  setBusy(true, "重建剧本");
  try {
    const project = await apiJson(`${API.repairStoryText}/${state.currentProjectId}/repair-story-text`, { method: "POST", body: "{}" });
    setCurrentProject(project);
    state.scriptPreview = null;
    render();
    showToast("已从现有分镜重建剧本");
  } finally {
    setBusy(false);
  }
}

async function saveTtsProviders() {
  const payload = {
    cosyvoice: getValue("providerCosyVoiceInput"),
    gpt_sovits: getValue("providerGptSovitsInput"),
    fish: getValue("providerFishInput"),
    indextts: getValue("providerIndexTtsInput"),
  };
  setBusy(true, "保存引擎");
  try {
    const saved = await apiJson(API.ttsProviders, { method: "PUT", body: JSON.stringify(payload) });
    state.ttsProviders = saved.providers || payload;
    render();
    showToast("TTS 引擎地址已保存");
  } finally {
    setBusy(false);
  }
}

function saveComfyUIUrl() {
  const url = comfyuiEditorUrl();
  if (!url) {
    showToast("请输入有效的 ComfyUI 地址", "danger");
    return;
  }
  setStoredValue("comfyuiBaseUrl", url);
  showToast("ComfyUI 地址已保存");
}

function openComfyUI() {
  const url = comfyuiEditorUrl();
  if (!url) {
    showToast("请输入有效的 ComfyUI 地址", "danger");
    return;
  }
  setStoredValue("comfyuiBaseUrl", url);
  window.open(url, "_blank", "noopener");
}

async function fillMissingAssets(kinds, label) {
  if (!state.currentProjectId) return;
  setBusy(true, label || "补齐资产");
  try {
    const project = await apiJson(`${API.fillMissingAssets}/${state.currentProjectId}/fill-missing-assets`, {
      method: "POST",
      body: JSON.stringify({ kinds }),
    });
    setCurrentProject(project);
    showToast("缺口补齐任务已提交");
    await refreshUntilProjectSettles();
    if (!projectHasAssetGaps() && (kinds || []).includes("video")) {
      state.activeTab = "export";
      render();
      showToast("素材已就绪，可以导出成片");
    }
  } finally {
    clearProjectPoll();
    setBusy(false);
  }
}

async function sceneAction(action) {
  if (!state.currentProjectId || !state.selectedSceneOrder) return;
  const endpointMap = {
    "split-scene": "split",
    "merge-scene": "merge-next",
    "rerender-image": "rerender-image",
    "rerender-audio": "rerender-audio",
    "rerender-video": "rerender-video",
    "rebuild-scene": "rebuild",
    "restore-scene": "restore",
  };
  const endpoint = endpointMap[action];
  if (!endpoint) return;
  setBusy(true, "分镜任务");
  try {
    const project = await apiJson(`${API.projects}/${state.currentProjectId}/scenes/${state.selectedSceneOrder}/${endpoint}`, { method: "POST", body: "{}" });
    setCurrentProject(project);
    showToast("分镜任务已完成");
  } finally {
    setBusy(false);
  }
}

async function buildProject() {
  if (!state.currentProjectId) return;
  setBusy(true, "整集生成");
  try {
    const project = await apiJson(`${API.projects}/${state.currentProjectId}/build`, { method: "POST", body: "{}" });
    setCurrentProject(project);
    showToast("已提交整集生成");
    await refreshUntilProjectSettles(60000, 2000);
    state.activeTab = "export";
    render();
    focusFinalPreview();
  } finally {
    clearProjectPoll();
    setBusy(false);
  }
}

async function exportProject() {
  if (!state.currentProjectId) return;
  setBusy(true, "导出成片");
  try {
    const project = await apiJson(`${API.projects}/${state.currentProjectId}/export`, { method: "POST", body: "{}" });
    setCurrentProject(project);
    state.activeTab = "export";
    showToast("导出完成");
    render();
    focusFinalPreview();
  } finally {
    setBusy(false);
  }
}

async function uploadCharacterReferenceImage(file) {
  if (!file || !state.currentProjectId || !state.selectedCharacterIndex) return;
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
  setBusy(true, "上传参考图");
  try {
    const project = await apiJson(`${API.projects}/${state.currentProjectId}/characters/${state.selectedCharacterIndex}/reference-image`, {
      method: "POST",
      body: JSON.stringify({ filename: file.name || "reference.png", data_url: dataUrl }),
    });
    setCurrentProject(project);
    showToast("参考图已上传");
  } finally {
    setBusy(false);
  }
}

function startTimelineDrag(event, handle) {
  const clip = handle.closest(".timeline-clip");
  const sceneOrder = Number(handle.dataset.sceneOrder || clip?.dataset.sceneOrder || 0);
  const scene = (state.project?.scenes || []).find((item) => Number(item.order) === sceneOrder);
  if (!clip || !scene) return;
  event.preventDefault();
  event.stopPropagation();
  const pointerId = "pointerId" in event ? event.pointerId : "mouse";
  state.timelineDrag = {
    pointerId,
    clip,
    sceneOrder,
    startX: event.clientX,
    startDuration: asNumber(scene.duration_seconds, 4),
    activeDuration: asNumber(scene.duration_seconds, 4),
  };
  if ("pointerId" in event) {
    handle.setPointerCapture?.(event.pointerId);
  }
  document.body.style.cursor = "ew-resize";
}

function handleTimelineMove(event) {
  const drag = state.timelineDrag;
  if (!drag) return;
  if ("pointerId" in event && drag.pointerId !== event.pointerId) return;
  event.preventDefault?.();
  const step = event.shiftKey ? 0.1 : 0.5;
  const deltaSeconds = (event.clientX - drag.startX) / TIMELINE_PX_PER_SECOND;
  const nextDuration = Math.max(MIN_SCENE_DURATION, Math.round((drag.startDuration + deltaSeconds) / step) * step);
  drag.activeDuration = Number(nextDuration.toFixed(1));
  drag.clip.style.width = `${Math.max(92, Math.round(drag.activeDuration * TIMELINE_PX_PER_SECOND))}px`;
  const label = drag.clip.querySelector(`[data-clip-duration="${drag.sceneOrder}"]`);
  if (label) label.textContent = formatSeconds(drag.activeDuration);
}

async function finishTimelineDrag(event) {
  const drag = state.timelineDrag;
  if (!drag) return;
  if ("pointerId" in event && drag.pointerId !== event.pointerId) return;
  event.preventDefault?.();
  state.timelineDrag = null;
  document.body.style.cursor = "";
  try {
    await saveTimelineSceneDuration(drag.sceneOrder, drag.activeDuration);
  } catch (error) {
    showToast(error.message, "danger");
    await refreshCurrentProject();
  }
}

function startSfxDrag(event, anchor) {
  const track = anchor.closest(".sfx-track");
  const sceneOrder = Number(anchor.dataset.sceneOrder || state.selectedSceneOrder || 0);
  const durationMs = Math.max(250, asNumber(anchor.dataset.durationMs, sceneDurationMs(selectedScene())));
  if (!track || !sceneOrder) return;
  event.preventDefault();
  event.stopPropagation();
  const pointerId = "pointerId" in event ? event.pointerId : "mouse";
  state.sfxDrag = {
    pointerId,
    anchor,
    track,
    sceneOrder,
    durationMs,
    activeMs: Math.max(0, Math.round(asNumber(anchor.dataset.currentMs, 0))),
  };
  if ("pointerId" in event) {
    anchor.setPointerCapture?.(event.pointerId);
  }
  document.body.style.cursor = "ew-resize";
  updateSfxDragPosition(event);
}

function updateSfxDragPosition(event) {
  const drag = state.sfxDrag;
  if (!drag) return;
  if ("pointerId" in event && drag.pointerId !== event.pointerId) return;
  event.preventDefault?.();
  const rect = drag.track.getBoundingClientRect();
  const width = Math.max(1, rect.width);
  const offsetX = Math.min(width, Math.max(0, event.clientX - rect.left));
  const ratio = offsetX / width;
  const currentMs = Math.round(ratio * drag.durationMs);
  drag.activeMs = currentMs;
  drag.anchor.style.left = `${(ratio * 100).toFixed(2)}%`;
  drag.anchor.dataset.currentMs = String(currentMs);
  const file = String(sceneSfxTrigger(selectedScene())?.file || "").trim() || "sfx";
  drag.anchor.textContent = `${file} ${currentMs}ms`;
  drag.anchor.title = `${file} @ ${currentMs}ms`;
  const input = document.getElementById("sceneSfxTimestampInput");
  if (input && Number(state.selectedSceneOrder) === Number(drag.sceneOrder)) {
    input.value = String(currentMs);
  }
}

async function finishSfxDrag(event) {
  const drag = state.sfxDrag;
  if (!drag) return;
  if ("pointerId" in event && drag.pointerId !== event.pointerId) return;
  event.preventDefault?.();
  state.sfxDrag = null;
  document.body.style.cursor = "";
  try {
    await saveSceneSfxTimestamp(drag.sceneOrder, drag.activeMs);
  } catch (error) {
    showToast(error.message, "danger");
    await refreshCurrentProject();
  }
}

async function persistDirtyCropBox() {
  if (!state.cropBoxDirty) return;
  const scene = selectedScene();
  if (!scene) {
    state.cropBoxDirty = false;
    return;
  }
  await saveCropBox(cropBoxFromInputs(normalizeCropBox(scene.crop_box)));
}

async function switchTab(tab, section) {
  await persistDirtyCropBox();
  state.activeTab = tab;
  render();
  if (tab === "assets" && state.currentProjectId) {
    await loadAssets(state.currentProjectId);
  }
  requestAnimationFrame(() => {
    document.querySelector(".content")?.scrollTo({ top: 0, left: 0 });
    document.querySelectorAll(".window-body, .panel-body").forEach((element) => element.scrollTo({ top: 0, left: 0 }));
  });
}

function setCropInputs(cropBox) {
  const box = normalizeCropBox(cropBox);
  const values = {
    sceneCropXInput: box.x,
    sceneCropYInput: box.y,
    sceneCropWidthInput: box.width,
    sceneCropHeightInput: box.height,
  };
  Object.entries(values).forEach(([fieldId, value]) => {
    document.querySelectorAll(`[data-crop-field="${fieldId}"]`).forEach((input) => {
      input.value = Number(value).toFixed(input.type === "number" ? 3 : 4);
    });
  });
}

function updateCropOverlay(cropBox) {
  const overlay = document.getElementById("sceneCropOverlay");
  if (!overlay) return;
  const box = normalizeCropBox(cropBox);
  overlay.style.left = cropPercent(box.x);
  overlay.style.top = cropPercent(box.y);
  overlay.style.width = cropPercent(box.width);
  overlay.style.height = cropPercent(box.height);
}

function handleCropInput(target) {
  const fieldId = target?.dataset?.cropField;
  if (!fieldId) return false;
  document.querySelectorAll(`[data-crop-field="${fieldId}"]`).forEach((input) => {
    if (input !== target) input.value = target.value;
  });
  const scene = selectedScene();
  const cropBox = cropBoxFromInputs(normalizeCropBox(scene?.crop_box));
  setCropInputs(cropBox);
  updateCropOverlay(cropBox);
  state.cropBoxDirty = true;
  return true;
}

async function handleClick(event) {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const action = button.dataset.action;
  const allowedWhileBusy = new Set([
    "switch-tab",
    "select-scene",
    "select-project",
    "select-character",
    "modal-close-overlay",
    "modal-close",
    "style-filter",
    "style-pick",
    "style-confirm",
    "asset-add-submit",
  ]);
  if (state.busy && !allowedWhileBusy.has(action)) return;
  try {
    if (action === "switch-tab") {
      await switchTab(button.dataset.tab || "overview", button.dataset.jumpSection);
      return;
    }
    if (action === "select-project") {
      await persistDirtyCropBox();
      return loadProject(button.dataset.projectId);
    }
    if (action === "select-scene") {
      await persistDirtyCropBox();
      state.selectedSceneOrder = Number(button.dataset.sceneOrder || 1);
      render();
      return;
    }
    if (action === "select-character") {
      state.selectedCharacterIndex = Number(button.dataset.characterIndex || 1);
      render();
      return;
    }
    if (action === "asset-tab") {
      state.assets.activeTab = button.dataset.assetTab || "character";
      render();
      return;
    }
    if (action === "select-asset") {
      selectAssetCard(button.dataset.assetType, button.dataset.assetName);
      render();
      return;
    }
    if (action === "asset-refresh") return loadAssets(state.currentProjectId, { force: true });
    if (action === "asset-style") {
      openModal("style-picker", {
        tempSelected: state.project?.style_id || "",
        filter: "all",
      });
      await loadStyles();
      return;
    }
    if (action === "asset-extract") return handleAssetExtract(state.currentProjectId);
    if (action === "asset-add") return openAssetAddModal();
    if (action === "asset-generate") return handleAssetGenerate(state.currentProjectId, button.dataset.assetId);
    if (action === "asset-generate-all") return handleAssetGenerateAll(state.currentProjectId);
    if (action === "modal-close-overlay") return closeModal();
    if (action === "modal-close") return closeModal();
    if (action === "style-filter") {
      if (!state.modal?.data) return;
      state.modal.data.filter = button.dataset.filter || "all";
      render();
      return;
    }
    if (action === "style-pick") {
      if (!state.modal?.data) return;
      state.modal.data.tempSelected = button.dataset.styleId || "";
      render();
      return;
    }
    if (action === "style-confirm") {
      const styleId = button.dataset.styleId || state.modal?.data?.tempSelected || "";
      if (!styleId || !state.currentProjectId) return;
      const payload = await apiJson(`${API.projects}/${encodeURIComponent(state.currentProjectId)}/style`, {
        method: "POST",
        body: JSON.stringify({ style_id: styleId }),
      });
      if (payload?.project) {
        setCurrentProject(payload.project);
      } else if (state.project) {
        state.project = { ...state.project, style_id: styleId };
      }
      closeModal();
      showToast("风格已更新");
      return;
    }
    if (action === "asset-add-submit") return handleAssetAddSubmit(state.currentProjectId);
    if (action === "create-project") return createProject();
    if (action === "delete-project") return deleteProject(button.dataset.projectId);
    if (action === "refresh-all") {
      await Promise.all([loadVoiceCatalog(), loadTtsProviders(), loadComfyUIStatus(), loadProjects(false)]);
      return showToast("已刷新");
    }
    if (action === "refresh-project") return refreshCurrentProject();
    if (action === "save-project") return saveProject();
    if (action === "save-scene") return saveScene();
    if (action === "pick-script-file") {
      document.getElementById("scriptFileInput")?.click();
      return;
    }
    if (action === "enable-crop-editor") {
      state.cropEditorSceneOrder = state.selectedSceneOrder;
      render();
      return;
    }
    if (action === "save-crop-box") return saveCropBox();
    if (action === "reset-crop-box") return resetCropBox();
    if (action === "save-character") return saveCharacter();
    if (action === "preview-voice") return previewVoice("manual");
    if (action === "preview-scene-voice") return previewVoice("scene");
    if (action === "preview-character-voice") return previewVoice("character");
    if (action === "preview-script") return previewScript();
    if (action === "apply-script") return applyScript();
    if (action === "repair-story-text") return repairStoryText();
    if (action === "save-tts-providers") return saveTtsProviders();
    if (action === "save-comfyui-url") return saveComfyUIUrl();
    if (action === "check-comfyui") return loadComfyUIStatus();
    if (action === "open-comfyui") return openComfyUI();
    if (action === "build-project") return buildProject();
    if (action === "export-project") return exportProject();
    if (action === "fill-missing-assets") return fillMissingAssets(["image", "audio", "video"], "补齐全部缺口");
    if (action === "fill-missing-images") return fillMissingAssets(["image"], "补图");
    if (action === "fill-missing-audio") return fillMissingAssets(["audio"], "补音频");
    if (action === "fill-missing-video") return fillMissingAssets(["video"], "补视频");
    if (action === "timeline-resize") return;
    if (["split-scene", "merge-scene", "rerender-image", "rerender-audio", "rerender-video", "rebuild-scene", "restore-scene"].includes(action)) return sceneAction(action);
  } catch (error) {
    showToast(error.message || String(error), "danger");
  }
}

function handleChange(event) {
  if (handleCropInput(event.target)) return;
  if (event.target?.id === "comfyuiBaseUrlInput") {
    const url = normalizeExternalUrl(event.target.value, "http://127.0.0.1:8188");
    if (url) {
      event.target.value = url;
      setStoredValue("comfyuiBaseUrl", url);
    }
    return;
  }
  if (event.target?.id === "characterReferenceFileInput") {
    const file = event.target.files?.[0];
    uploadCharacterReferenceImage(file).catch((error) => showToast(error.message, "danger"));
    event.target.value = "";
    return;
  }
  if (event.target?.id === "scriptFileInput") {
    const file = event.target.files?.[0];
    if (file) {
      importScriptFile(file).catch((error) => showToast(error.message, "danger"));
    }
    event.target.value = "";
  }
}

function handleInput(event) {
  if (handleCropInput(event.target)) return;
  if (state.modal && event.target?.dataset?.modalField) {
    const field = event.target.dataset.modalField;
    if (!state.modal.data.form) state.modal.data.form = {};
    state.modal.data.form[field] = event.target.value;
    return;
  }
  if (!state.project) return;
  if (event.target?.id === "scriptTextInput") {
    state.project.story_text = event.target.value;
    const projectTextarea = document.getElementById("projectStoryInput");
    if (projectTextarea && projectTextarea.value !== event.target.value) {
      projectTextarea.value = event.target.value;
    }
    state.scriptPreview = null;
    return;
  }
  if (event.target?.id === "projectStoryInput") {
    state.project.story_text = event.target.value;
    const scriptTextarea = document.getElementById("scriptTextInput");
    if (scriptTextarea && scriptTextarea.value !== event.target.value) {
      scriptTextarea.value = event.target.value;
    }
    state.scriptPreview = null;
    return;
  }
  if (event.target?.id === "scriptTitleInput") {
    state.project.title = event.target.value;
  }
}

async function boot() {
  clearProjectPoll();
  appRoot.addEventListener("click", handleClick);
  appRoot.addEventListener("mousedown", (event) => {
    const sfxAnchor = event.target.closest?.("[data-sfx-anchor]");
    if (sfxAnchor) {
      startSfxDrag(event, sfxAnchor);
      return;
    }
    const handle = event.target.closest?.('[data-action="timeline-resize"]');
    if (handle) startTimelineDrag(event, handle);
  });
  appRoot.addEventListener("change", handleChange);
  appRoot.addEventListener("input", handleInput);
  document.addEventListener("pointermove", (event) => {
    handleTimelineMove(event);
    updateSfxDragPosition(event);
  });
  document.addEventListener("pointerup", (event) => {
    finishTimelineDrag(event);
    finishSfxDrag(event);
  });
  document.addEventListener("pointercancel", (event) => {
    finishTimelineDrag(event);
    finishSfxDrag(event);
  });
  document.addEventListener("mousemove", (event) => {
    handleTimelineMove(event);
    updateSfxDragPosition(event);
  });
  document.addEventListener("mouseup", (event) => {
    finishTimelineDrag(event);
    finishSfxDrag(event);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.modal) {
      event.preventDefault();
      closeModal();
    }
  });
  render();
  try {
    await Promise.all([loadVoiceCatalog(), loadTtsProviders(), loadComfyUIStatus()]);
    await loadProjects(true);
  } catch (error) {
    render();
    showToast(error.message || "启动失败", "danger");
  }
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

function renderScriptSceneCard(scene) {
  const assets = scene.assets || {};
  return `
    <div class="preview-scene-card">
      <div class="item-title">#${h(scene.order)} ${h(scene.title || "分镜")}</div>
      <div class="preview-tags">
        <span class="badge ok">${h(scene.camera_movement || "slow_push_in")}</span>
        <span class="badge warn">${h(scene.emotion || "neutral")}</span>
        <span class="badge">${h(formatSeconds(scene.duration_seconds))}</span>
      </div>
      <div class="item-meta">${h(scene.speaker || "角色")} · ${h((scene.characters || []).join("、") || "未识别角色")}</div>
      <div class="preview-snippet">${h(scene.visual_prompt || "未生成镜头提示")}</div>
      <div class="preview-snippet">${nl(scene.dialogue || "暂无台词")}</div>
      <div class="item-meta">${assets.image_url ? "图像已就绪" : "图像待生成"} · ${assets.audio_url ? "配音已就绪" : "配音待生成"} · ${assets.video_url ? "视频已就绪" : "视频待生成"}</div>
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

function renderScriptPreview(preview) {
  const analysis = preview?.analysis || {};
  const roles = Array.isArray(analysis.roles) ? analysis.roles : [];
  const events = Array.isArray(analysis.events) ? analysis.events : [];
  const scenes = Array.isArray(preview?.scenes) ? preview.scenes : [];
  const summary = analysis.format_summary || {};
  const warnings = Array.isArray(analysis.warnings) ? analysis.warnings : [];
  const topRoles = roles.slice(0, 8);
  const topEvents = events.slice(0, 8);

  return `
    <div class="script-preview-stack">
      <div class="scene-card">
        <div class="item-title">${h(preview.title || "未命名")}</div>
        <div class="item-meta">${h(preview.planner_used || "rule")} · ${h(analysis.mode || "rule")} · 源文本 ${h(analysis.source_length ?? 0)} 字</div>
        <div class="preview-tags">
          <span class="badge ok">角色 ${h(analysis.role_count ?? roles.length)}</span>
          <span class="badge warn">事件 ${h(analysis.event_count ?? events.length)}</span>
          <span class="badge">分镜 ${h(scenes.length)}</span>
          <span class="badge">台词 ${h(summary.dialogue_line_count ?? 0)}</span>
          <span class="badge">叙述 ${h(summary.narrative_line_count ?? 0)}</span>
          <span class="badge">标头 ${h(summary.heading_count ?? 0)}</span>
          <span class="badge">cue ${h(summary.cue_count ?? 0)}</span>
        </div>
        ${warnings.length ? `<div class="preview-notes">${warnings.map((warning) => `<div class="preview-note">${h(warning)}</div>`).join("")}</div>` : ""}
      </div>

      <section class="preview-section">
        <div class="section-label">角色提取</div>
        <div class="preview-grid">
          ${topRoles.length ? topRoles.map(renderScriptRoleCard).join("") : `<div class="empty-state">未识别到角色。</div>`}
        </div>
      </section>

      <section class="preview-section">
        <div class="section-label">镜头事件</div>
        <div class="preview-list">
          ${topEvents.length ? topEvents.map(renderScriptEventCard).join("") : `<div class="empty-state">未识别到事件。</div>`}
        </div>
      </section>

      <section class="preview-section">
        <div class="section-label">分镜草稿（可编辑）</div>
        <div class="preview-list">
          ${scenes.length ? scenes.map(renderScriptSceneEditableCard).join("") : `<div class="empty-state">未生成分镜。</div>`}
        </div>
      </section>
    </div>
  `;
}

boot();
