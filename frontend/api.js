// ─── API Communication ───────────────────────────────────────────────────────

import { state, API, appRoot, voiceCatalogList, assetTabs, DEFAULT_CROP_BOX, MIN_SCENE_DURATION } from "./state.js";
import {
  asNumber,
  characterKey,
  selectedScene,
  selectedCharacter,
  getValue,
  getChecked,
  looksGarbledScriptText,
  splitPreviewCharacters,
  previewSceneFieldId,
  sceneShots,
  sceneAudioManifest,
  sceneSfxTrigger,
  shotEditorId,
  normalizeCropBox,
  cropBoxFromInputs,
  cropPercent,
  formatSeconds,
  projectHasAssetGaps,
  projectIsBusy,
  assetTypeLabel,
  storedValue,
  setStoredValue,
  comfyuiEditorUrl,
  normalizeExternalUrl,
  h,
  sceneReviewMeta,
} from "./utils.js";

// Forward reference for render - will be set by events.js
let _render = () => {};
export function setRenderFn(fn) { _render = fn; }
function render() { _render(); }

export async function apiJson(url, options = {}) {
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

export function setBusy(busy, text = "") {
  state.busy = busy;
  state.busyText = text;
  render();
}

export function showToast(message, type = "ok") {
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

export function renderVoiceCatalogDatalist() {
  if (!voiceCatalogList) return;
  voiceCatalogList.innerHTML = state.voiceCatalog
    .slice(0, 180)
    .map((item) => `<option value="${h(item.short_name || item.ShortName || "")}">${h(item.friendly_name || item.FriendlyName || "")}</option>`)
    .join("");
}

export function setCurrentProject(project) {
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

export function subscribeProjectEvents(projectId) {
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

export function unsubscribeProjectEvents() {
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

export async function loadProjects(selectNewest = true) {
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

export async function loadProject(projectId) {
  const project = await apiJson(`${API.projects}/${encodeURIComponent(projectId)}`);
  setCurrentProject(project);
  await loadVideoProviderStatus(project?.settings?.video_provider || "auto");
  if (state.activeTab === "assets") {
    await loadAssets(project.project_id, { force: true, silent: true });
  }
  render();
}

export async function refreshCurrentProject() {
  if (!state.currentProjectId) return loadProjects();
  await loadProject(state.currentProjectId);
}

export function clearProjectPoll() {
  if (state.projectPollTimer) {
    window.clearTimeout(state.projectPollTimer);
    state.projectPollTimer = null;
  }
}

export async function refreshUntilProjectSettles(timeoutMs = 25000, intervalMs = 1600) {
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

export async function loadVoiceCatalog() {
  try {
    const payload = await apiJson(API.voiceCatalog);
    state.voiceCatalog = Array.isArray(payload?.items) ? payload.items : [];
    renderVoiceCatalogDatalist();
  } catch (error) {
    console.warn(error);
  }
}

export async function loadTtsProviders() {
  try {
    const payload = await apiJson(API.ttsProviders);
    state.ttsProviders = payload?.providers || {};
  } catch (error) {
    console.warn(error);
  }
}

export async function loadVideoProviderStatus(provider = state.project?.settings?.video_provider || "auto") {
  state.videoProviderStatusLoading = true;
  state.videoProviderStatusError = "";
  try {
    const providersPayload = await apiJson("/api/video-providers");
    state.videoProviders = Array.isArray(providersPayload?.providers) ? providersPayload.providers : [];
    state.videoProviderStatus = await apiJson(`/api/video-providers/status?provider=${encodeURIComponent(provider || "auto")}`);
  } catch (error) {
    state.videoProviderStatus = null;
    state.videoProviderStatusError = error.message || String(error);
  } finally {
    state.videoProviderStatusLoading = false;
  }
  render();
}

export async function loadComfyUIStatus() {
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

export async function loadAssets(projectId = state.currentProjectId, options = {}) {
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

export async function loadStyles() {
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
      visual_prompt: String(raw?.visual_prompt || "").trim(),
      first_scene: Number(raw?.order || 1),
    });
  }
  return payloads;
}

export async function handleAssetExtract(projectId = state.currentProjectId) {
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
    showToast(`资产提取完成：角色 ${added.characters || 0} / 场景 ${added.scene_bgs || 0} / 道具 ${added.props || 0}`);
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
    showToast(`LLM 不可用，已本地补齐 ${addedCount} 个资产`, "warning");
  } finally {
    state.assets.loading = false;
    render();
  }
}

export function updateLocalAsset(assetId, patch) {
  for (const bucket of ["characters", "scene_bgs", "props"]) {
    const index = state.assets[bucket].findIndex((asset) => asset.id === assetId);
    if (index >= 0) {
      state.assets[bucket][index] = { ...state.assets[bucket][index], ...patch };
      return state.assets[bucket][index];
    }
  }
  return null;
}

export async function handleAssetGenerate(projectId = state.currentProjectId, assetId) {
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

export async function handleAssetGenerateAll(projectId = state.currentProjectId) {
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

export async function handleAssetAddSubmit(projectId = state.currentProjectId) {
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

export function openModal(type, data = {}) {
  state.modal = { type, data };
  render();
}

export function closeModal() {
  if (!state.modal) return;
  state.modal = null;
  render();
}

export function openAssetAddModal() {
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

export function selectAssetCard(assetType, assetName) {
  if (assetType !== "character") return;
  const name = characterKey(assetName);
  if (!name) return;
  const characters = state.project?.characters || [];
  const index = characters.findIndex((character) => characterKey(character?.name) === name);
  if (index >= 0) {
    state.selectedCharacterIndex = index + 1;
  }
}

export function focusFinalPreview() {
  requestAnimationFrame(() => {
    document.querySelector(".content")?.scrollTo({ top: 0, left: 0 });
    document.getElementById("finalPreviewSection")?.scrollIntoView({ block: "start", behavior: "smooth" });
  });
}

export function sceneShotOverridesPayload(scene) {
  return sceneShots(scene).map((shot, index) => {
    const order = Number(shot.shot_order || index + 1);
    return {
      shot_id: String(shot.shot_id || "").trim(),
      shot_order: order,
      label: String(shot.label || shot.beat_type || `SHOT ${order}`).trim(),
      caption: String(shot.caption || "").trim(),
      bubble: String(shot.bubble || "").trim(),
      duration_seconds: Math.max(0.25, asNumber(getValue(shotEditorId(order, "Duration"), shot.duration_seconds ?? 1), 1)),
      camera_movement: getValue(shotEditorId(order, "Camera"), shot.camera_movement || scene?.camera_movement || "slow_push_in"),
      camera_speed: Math.max(0.1, asNumber(getValue(shotEditorId(order, "Speed"), shot.camera_speed ?? scene?.camera_speed ?? 1), 1)),
      zoom: Math.max(1, asNumber(getValue(shotEditorId(order, "Zoom"), shot.zoom ?? 1), 1)),
      hold_in_ratio: asNumber(shot.hold_in_ratio, 0),
      hold_out_ratio: asNumber(shot.hold_out_ratio, 0),
      center_x: asNumber(shot.center_x, 0.5),
      center_y: asNumber(shot.center_y, 0.5),
    };
  });
}

export function sceneAudioManifestPayload(scene) {
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

export function scenePatchPayload() {
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
    shot_overrides: sceneShotOverridesPayload(scene),
  };
}

export function projectPatchPayload() {
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

export function characterPatchPayload() {
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

export function voicePreviewPayload(source = "manual") {
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

export function collectScriptPreviewDraft() {
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

export async function createProject() {
  if (state.scriptPreview) {
    setBusy(true, "应用脚本预览");
    try {
      const project = await apiJson(`${API.applyScriptPreview}/${state.currentProjectId}/apply-script-preview`, {
        method: "POST",
        body: JSON.stringify(collectScriptPreviewDraft()),
      });
      state.scriptPreview = null;
      setCurrentProject(project);
      state.activeTab = "storyboard";
      showToast("脚本预览已应用");
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

export async function saveProject() {
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

export async function deleteProject(projectId) {
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

export async function patchScene(order, payload) {
  const project = await apiJson(`${API.projects}/${state.currentProjectId}/scenes/${order}`, { method: "PATCH", body: JSON.stringify(payload) });
  setCurrentProject(project);
}

export async function saveScene() {
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

export async function saveSceneReview() {
  const scene = selectedScene();
  if (!scene) return;
  const rating = Math.max(0, Math.min(5, asNumber(getValue("reviewRatingInput"), 0)));
  const review_meta = {
    ...sceneReviewMeta(scene),
    status: getValue("reviewStatusInput", "unreviewed") || "unreviewed",
    rating,
    note: getValue("reviewNoteInput", ""),
    reviewed_at: new Date().toISOString(),
  };
  setBusy(true, "保存审片");
  try {
    await patchScene(scene.order, { review_meta });
    showToast("审片记录已保存");
  } finally {
    setBusy(false);
  }
}

export async function saveCropBox(cropBox = null) {
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

export async function resetCropBox() {
  setCropInputs(DEFAULT_CROP_BOX);
  updateCropOverlay(DEFAULT_CROP_BOX);
  await saveCropBox(DEFAULT_CROP_BOX);
}

export async function saveTimelineSceneDuration(order, duration) {
  await patchScene(order, { duration_seconds: duration });
  showToast(`分镜 #${order} 时长已更新为 ${formatSeconds(duration)}`);
}

export async function saveSceneSfxTimestamp(order, timestampMs) {
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
  showToast(`音效锚点已移动到 ${trigger.timestamp_ms}ms，当前格视频需要重合成`);
}

export async function saveCharacter() {
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

export async function previewVoice(source = "manual") {
  // Auto-save character/scene before preview to prevent form reset on render()
  if (source === "character" && state.currentProjectId && state.selectedCharacterIndex) {
    const charPayload = characterPatchPayload();
    try {
      const project = await apiJson(`${API.projects}/${state.currentProjectId}/characters/${state.selectedCharacterIndex}`, { method: "PATCH", body: JSON.stringify(charPayload) });
      setCurrentProject(project);
    } catch (e) { /* proceed with preview even if save fails */ }
  }
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

export async function previewScript() {
  if (!state.currentProjectId) return;
  const scriptText = getValue("scriptTextInput");
  if (looksGarbledScriptText(scriptText)) {
    showToast("剧本文本疑似损坏，请重新粘贴原文后再预览。", "danger");
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

export async function applyScript() {
  if (!state.currentProjectId) return;
  const scriptText = getValue("scriptTextInput");
  if (looksGarbledScriptText(scriptText)) {
    showToast("剧本文本疑似损坏，请重新粘贴原文后再应用。", "danger");
    return;
  }
  const payload = {
    title: getValue("scriptTitleInput"),
    script_text: scriptText,
    script_hint: getValue("scriptHintInput"),
    planner: getValue("scriptPlannerInput", "auto"),
    max_scenes: Math.max(1, Math.min(24, Math.round(asNumber(getValue("scriptMaxScenesInput"), 12)))),
  };
  setBusy(true, "应用脚本");
  try {
    const project = await apiJson(`${API.projects}/${state.currentProjectId}/recognize-script`, { method: "POST", body: JSON.stringify(payload) });
    state.scriptPreview = null;
    setCurrentProject(project);
    state.activeTab = "storyboard";
    showToast("剧本已应用到分镜");
  } finally {
    setBusy(false);
  }
}

export async function repairStoryText() {
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

export async function saveTtsProviders() {
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

export function saveComfyUIUrl() {
  const url = comfyuiEditorUrl();
  if (!url) {
    showToast("请输入有效的 ComfyUI 地址", "danger");
    return;
  }
  setStoredValue("comfyuiBaseUrl", url);
  showToast("ComfyUI 地址已保存");
}

export function openComfyUI() {
  const url = comfyuiEditorUrl();
  if (!url) {
    showToast("请输入有效的 ComfyUI 地址", "danger");
    return;
  }
  setStoredValue("comfyuiBaseUrl", url);
  window.open(url, "_blank", "noopener");
}

export async function fillMissingAssets(kinds, label) {
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
      state.activeTab = "produce";
      render();
      showToast("素材已就绪，可以导出成片");
    }
  } finally {
    clearProjectPoll();
    setBusy(false);
  }
}

export async function sceneAction(action) {
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

export async function runSceneAction(action, sceneOrder) {
  if (!state.currentProjectId || !sceneOrder) return null;
  const endpointMap = {
    "rerender-image": "rerender-image",
    "rerender-audio": "rerender-audio",
    "rerender-video": "rerender-video",
    "rebuild-scene": "rebuild",
  };
  const endpoint = endpointMap[action];
  if (!endpoint) return null;
  const project = await apiJson(`${API.projects}/${state.currentProjectId}/scenes/${sceneOrder}/${endpoint}`, { method: "POST", body: "{}" });
  setCurrentProject(project);
  return project;
}

export async function buildProject() {
  if (!state.currentProjectId) return;
  setBusy(true, "整集生成");
  try {
    const project = await apiJson(`${API.projects}/${state.currentProjectId}/build`, { method: "POST", body: "{}" });
    setCurrentProject(project);
    showToast("已提交整集生成");
    await refreshUntilProjectSettles(60000, 2000);
    state.activeTab = "produce";
    render();
    focusFinalPreview();
  } finally {
    clearProjectPoll();
    setBusy(false);
  }
}

export async function exportProject() {
  if (!state.currentProjectId) return;
  setBusy(true, "导出成片");
  try {
    const project = await apiJson(`${API.projects}/${state.currentProjectId}/export`, { method: "POST", body: "{}" });
    setCurrentProject(project);
    state.activeTab = "produce";
    showToast("导出完成");
    render();
    focusFinalPreview();
  } finally {
    setBusy(false);
  }
}

export async function uploadCharacterReferenceImage(file) {
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

// ─── Crop helpers (used by events.js too) ────────────────────────────────────

export function setCropInputs(cropBox) {
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

export function updateCropOverlay(cropBox) {
  const overlay = document.getElementById("sceneCropOverlay");
  if (!overlay) return;
  const box = normalizeCropBox(cropBox);
  overlay.style.left = cropPercent(box.x);
  overlay.style.top = cropPercent(box.y);
  overlay.style.width = cropPercent(box.width);
  overlay.style.height = cropPercent(box.height);
}

export async function importScriptFile(file) {
  const { readTextFile, titleFromFilename } = await import("./utils.js");
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
