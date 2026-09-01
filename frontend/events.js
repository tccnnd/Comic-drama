// ─── Event Handling & Interactions ───────────────────────────────────────────

import {
  state,
  appRoot,
  TIMELINE_PX_PER_SECOND,
  MIN_SCENE_DURATION,
  DEFAULT_CROP_BOX,
  API,
} from "./state.js";
import {
  asNumber,
  normalizeCropBox,
  cropBoxFromInputs,
  formatSeconds,
  selectedScene,
  sceneTemporalShots,
  sceneShots,
  sceneSfxTrigger,
  sceneDurationMs,
  findShotByOrder,
  snapTemporalShotDuration,
  shotEditorId,
  temporalShotTimeline,
  normalizeExternalUrl,
  setStoredValue,
  characterKey,
  sceneCharacterNames,
  titleFromFilename,
  readTextFile,
  timelineSceneItems,
  applyReviewTriage,
} from "./utils.js";
import {
  setRenderFn,
  loadProjects,
  loadProject,
  refreshCurrentProject,
  loadVoiceCatalog,
  loadTtsProviders,
  loadVideoProviderStatus,
  loadComfyUIStatus,
  loadAssets,
  loadStyles,
  createProject,
  saveProject,
  deleteProject,
  saveScene,
  saveSceneReview,
  saveCropBox,
  resetCropBox,
  saveCharacter,
  previewVoice,
  previewScript,
  applyScript,
  repairStoryText,
  saveTtsProviders,
  saveLlmSettings,
  testLlmConnection,
  applyLlmPreset,
  loadLlmSettings,
  loadLlmUsage,
  saveComfyUIUrl,
  openComfyUI,
  fillMissingAssets,
  sceneAction,
  runSceneAction,
  runShotRerender,
  buildProject,
  exportProject,
  handleAssetExtract,
  handleAssetGenerate,
  handleAssetGenerateAll,
  handleAssetAddSubmit,
  openAssetAddModal,
  openModal,
  closeModal,
  selectAssetCard,
  uploadCharacterReferenceImage,
  importScriptFile,
  showToast,
  setBusy,
  clearProjectPoll,
  setCropInputs,
  updateCropOverlay,
  saveTimelineSceneDuration,
  saveSceneSfxTimestamp,
  setCurrentProject,
  apiJson,
  loadTasks,
  loadTaskDetail,
  loadTaskFiles,
  loadBgm,
  uploadBgm,
} from "./api.js";
import {
  render,
  renderTasksStats,
  renderTasksRows,
  renderTasksDetail,
  renderBgmStats,
  renderBgmCards,
  renderBgmDetail,
  renderBgmPlayer,
} from "./render.js";

import { playTemporalPreview, pauseTemporalPreview, resetTemporalPreview } from "./timeline.js";

// Wire up the render function into api.js to break the circular dependency
setRenderFn(render);

export { render };

// ─── Character Picker Handlers ───────────────────────────────────────────────

function syncCharacterPickerField(fieldId, nextNames) {
  const field = document.getElementById(fieldId);
  if (field) {
    field.value = nextNames.join(", ");
  }
  const picker = document.querySelector(
    `[data-character-picker-field="${CSS?.escape ? CSS.escape(fieldId) : fieldId}"]`
  );
  if (picker) {
    picker
      .querySelectorAll(
        `[data-character-toggle][data-character-field-id="${CSS?.escape ? CSS.escape(fieldId) : fieldId}"]`
      )
      .forEach((input) => {
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
  document
    .querySelectorAll(`[data-character-toggle][data-character-field-id="${fieldId}"]`)
    .forEach((input) => {
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
  )
    .map((input) => String(input.dataset.characterName || input.value || "").trim())
    .filter(Boolean);
  syncCharacterPickerField(fieldId, nextNames);
  return true;
}

// ─── Crop Input Handlers ─────────────────────────────────────────────────────

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
  const previousTab = state.activeTab;
  state.activeTab = tab;
  render();
  // 任务中心轮询：仅在停留该页时运行，离开即停，避免后台无谓请求
  stopTasksPoll();
  if (tab === "tasks") {
    startTasksPoll();
    await refreshTasks();
  }
  if (tab === "bgm") {
    await refreshBgm();
  }
  if (tab === "assets" && state.currentProjectId) {
    await loadAssets(state.currentProjectId);
  }
  if (tab === "settings") {
    await loadLlmSettings();
    await loadLlmUsage();
    render();
  }
  requestAnimationFrame(() => {
    const content = document.querySelector(".content");
    if (tab === "settings" && previousTab === "settings" && !section) {
      if (content) content.scrollTop = state.settingsScrollTop || content.scrollTop || 0;
      return;
    }
    const target = section ? document.getElementById(section) : null;
    if (content && target) {
      const contentRect = content.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      content.scrollTo({
        top: Math.max(0, content.scrollTop + targetRect.top - contentRect.top - 12),
        left: 0,
      });
    } else {
      content?.scrollTo({ top: 0, left: 0 });
    }
    document
      .querySelectorAll(".window-body, .panel-body")
      .forEach((element) => element.scrollTo({ top: 0, left: 0 }));
  });
}

// ─── LLM Task Override Toggle ────────────────────────────────────────────────

function toggleTaskOverride(taskKey) {
  if (!state.llmSettings?.settings) return;
  const settings = state.llmSettings.settings;
  if (!settings.task_overrides) settings.task_overrides = {};

  if (settings.task_overrides[taskKey]) {
    // Disable: remove the override
    delete settings.task_overrides[taskKey];
  } else {
    // Enable: add an empty override (inherits all defaults)
    settings.task_overrides[taskKey] = {};
  }
  render();
}

// ─── Timeline Drag Handlers ──────────────────────────────────────────────────

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
  const nextDuration = Math.max(
    MIN_SCENE_DURATION,
    Math.round((drag.startDuration + deltaSeconds) / step) * step
  );
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

// ─── Temporal Shot Drag Handlers ─────────────────────────────────────────────

function setSceneShotDuration(scene, order, duration) {
  const sceneShot = findShotByOrder(sceneShots(scene), order);
  if (sceneShot) {
    sceneShot.duration_seconds = duration;
  }
  const spec =
    scene?.temporal_spec && typeof scene.temporal_spec === "object" ? scene.temporal_spec : null;
  const temporalShot = spec
    ? findShotByOrder(Array.isArray(spec.shots) ? spec.shots : [], order)
    : null;
  if (temporalShot) {
    temporalShot.duration_seconds = duration;
  }
  const input = document.getElementById(shotEditorId(order, "Duration"));
  if (input) {
    input.value = duration.toFixed(2);
  }
}

function startTemporalShotDrag(event, handle) {
  const scene = selectedScene();
  const preview = handle.closest("[data-temporal-preview]");
  const strip = handle.closest(".temporal-preview-strip");
  const shotNode = handle.closest("[data-temporal-shot]");
  const order = Number(handle.dataset.shotOrder || shotNode?.dataset.shotOrder || 0);
  const shot = findShotByOrder(sceneTemporalShots(scene), order);
  if (!scene || !preview || !strip || !shot || !order) return;
  event.preventDefault();
  event.stopPropagation();
  pauseTemporalPreview();
  const shots = sceneTemporalShots(scene);
  const total =
    shots.reduce((sum, item) => sum + Math.max(0.25, asNumber(item.duration_seconds, 0.25)), 0) ||
    1;
  const stripWidth = Math.max(160, strip.getBoundingClientRect().width);
  const pointerId = "pointerId" in event ? event.pointerId : "mouse";
  state.temporalShotDrag = {
    pointerId,
    sceneOrder: Number(scene.order || state.selectedSceneOrder || 0),
    order,
    strip,
    shotNode,
    startX: event.clientX,
    startDuration: Math.max(0.25, asNumber(shot.duration_seconds, 0.25)),
    activeDuration: Math.max(0.25, asNumber(shot.duration_seconds, 0.25)),
    secondsPerPx: total / stripWidth,
  };
  if ("pointerId" in event) {
    handle.setPointerCapture?.(event.pointerId);
  }
  document.body.style.cursor = "ew-resize";
}

function updateTemporalShotStrip(drag) {
  const scene = selectedScene();
  const shots = sceneTemporalShots(scene);
  const timeline = temporalShotTimeline(shots);
  const total = timeline.reduce((sum, item) => sum + item.duration, 0) || 1;
  const nodes = drag.strip.querySelectorAll("[data-temporal-shot]");
  nodes.forEach((node) => {
    const order = Number(node.dataset.shotOrder || 0);
    const item = timeline.find((entry) => entry.order === order);
    if (!item) return;
    const duration = item.duration;
    node.style.flex = `${Math.max(20, (duration / total) * 100)}`;
    node.dataset.duration = String(duration);
    const label = node.querySelector("small");
    if (label) label.textContent = `${item.start.toFixed(1)}s`;
    node.title = `${String(item.shot.label || item.shot.beat_type || `SHOT ${item.index + 1}`).trim()} · ${item.start.toFixed(1)}s → ${item.end.toFixed(1)}s`;
  });
  const rulerNodes = drag.strip.previousElementSibling?.classList?.contains(
    "temporal-preview-ruler"
  )
    ? drag.strip.previousElementSibling.querySelectorAll("[data-temporal-ruler]")
    : [];
  if (rulerNodes?.length) {
    rulerNodes.forEach((node) => {
      const order = Number(node.dataset.shotOrder || 0);
      const item = timeline.find((entry) => entry.order === order);
      if (!item) return;
      const width = Math.max(20, (item.duration / total) * 100);
      node.style.flex = `${width}`;
      const label = node.querySelector("span");
      if (label) label.textContent = item.start.toFixed(1);
    });
  }
  const summary = document.querySelector("[data-temporal-summary]");
  if (summary) {
    summary.textContent = `${shots.length} shots / ${total.toFixed(1)}s`;
  }
}

function handleTemporalShotMove(event) {
  const drag = state.temporalShotDrag;
  if (!drag) return;
  if ("pointerId" in event && drag.pointerId !== event.pointerId) return;
  event.preventDefault?.();
  const deltaSeconds = (event.clientX - drag.startX) * drag.secondsPerPx;
  const nextDuration = snapTemporalShotDuration(drag.startDuration + deltaSeconds, event.shiftKey);
  drag.activeDuration = nextDuration;
  const scene = selectedScene();
  if (!scene || Number(scene.order || 0) !== drag.sceneOrder) return;
  setSceneShotDuration(scene, drag.order, drag.activeDuration);
  updateTemporalShotStrip(drag);
}

function finishTemporalShotDrag(event) {
  const drag = state.temporalShotDrag;
  if (!drag) return;
  if ("pointerId" in event && drag.pointerId !== event.pointerId) return;
  event.preventDefault?.();
  state.temporalShotDrag = null;
  document.body.style.cursor = "";
  showToast("Shot duration updated. Save scene to persist.");
}

// ─── SFX Drag Handlers ──────────────────────────────────────────────────────

function startSfxDrag(event, anchor) {
  const track = anchor.closest(".sfx-track");
  const sceneOrder = Number(anchor.dataset.sceneOrder || state.selectedSceneOrder || 0);
  const durationMs = Math.max(
    250,
    asNumber(anchor.dataset.durationMs, sceneDurationMs(selectedScene()))
  );
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

// ─── Main Event Handlers ─────────────────────────────────────────────────────

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
    "task-filter",
    "refresh-tasks",
    "select-task",
    "task-detail",
    "bgm-filter",
    "refresh-bgm",
    "select-bgm",
  ]);
  if (state.busy && !allowedWhileBusy.has(action)) return;
  try {
    if (action === "switch-tab") {
      await switchTab(button.dataset.tab || "plan", button.dataset.jumpSection);
      return;
    }
    if (action === "task-filter") {
      state.taskFilter = button.dataset.filter || "all";
      render();
      return;
    }
    if (action === "refresh-tasks") {
      await refreshTasks();
      return;
    }
    if (action === "select-task" || action === "task-detail") {
      await selectTask(button.dataset.taskId || "");
      return;
    }
    if (action === "bgm-filter") {
      state.selectedBgmStyle = button.dataset.style || "all";
      render();
      return;
    }
    if (action === "refresh-bgm") {
      await refreshBgm();
      return;
    }
    if (action === "select-bgm") {
      await selectBgm(button.dataset.path || "");
      return;
    }
    if (action === "upload-bgm") {
      const input = document.getElementById("bgmFileInput");
      if (input) input.click();
      return;
    }
    if (action === "copy-bgm-path") {
      const path = button.dataset.path || "";
      const done = () => {
        const original = button.textContent;
        button.textContent = "已复制";
        setTimeout(() => {
          button.textContent = original;
        }, 1200);
      };
      if (navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(path).then(done).catch(() => {});
      }
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
    if (action === "review-filter") {
      state.reviewFilter = button.dataset.reviewFilter || "all";
      state.reviewTriageState = {
        ...(state.reviewTriageState || {}),
        review_status: state.reviewFilter,
      };
      render();
      return;
    }
    if (action === "review-overview-filter" || action === "review-triage-set") {
      setReviewTriageField(button.dataset.triageField, button.dataset.triageValue || "all");
      render();
      return;
    }
    if (action === "review-triage-reset") {
      resetReviewTriage();
      render();
      return;
    }
    if (action === "review-batch-rerender") {
      return runReviewBatchRerender(button.dataset.batchAction || "rerender-video");
    }
    if (action === "rerender-shot-video") {
      return runReviewShotRerender(button.dataset.sceneOrder, button.dataset.shotId);
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
    if (action === "asset-generate")
      return handleAssetGenerate(state.currentProjectId, button.dataset.assetId);
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
      const payload = await apiJson(
        `${API.projects}/${encodeURIComponent(state.currentProjectId)}/style`,
        {
          method: "POST",
          body: JSON.stringify({ style_id: styleId }),
        }
      );
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
      await Promise.all([
        loadVoiceCatalog(),
        loadTtsProviders(),
        loadVideoProviderStatus(),
        loadComfyUIStatus(),
        loadProjects(false),
      ]);
      return showToast("已刷新");
    }
    if (action === "refresh-project") return refreshCurrentProject();
    if (action === "save-project") return saveProject();
    if (action === "save-scene") return saveScene();
    if (action === "save-scene-review") return saveSceneReview();
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
    if (action === "save-llm-settings") return saveLlmSettings();
    if (action === "test-llm") return testLlmConnection();
    if (action === "llm-preset") return applyLlmPreset(Number(button.dataset.presetIdx || 0));
    if (action === "task-override-toggle") return toggleTaskOverride(button.dataset.taskKey);
    if (action === "save-comfyui-url") return saveComfyUIUrl();
    if (action === "check-comfyui") return loadComfyUIStatus();
    if (action === "open-comfyui") return openComfyUI();
    if (action === "temporal-preview-play") return playTemporalPreview();
    if (action === "temporal-preview-pause") return pauseTemporalPreview();
    if (action === "temporal-preview-reset") return resetTemporalPreview();
    if (action === "build-project") return buildProject();
    if (action === "export-project") return exportProject();
    if (action === "fill-missing-assets")
      return fillMissingAssets(["image", "audio", "video"], "补齐全部缺口");
    if (action === "fill-missing-images") return fillMissingAssets(["image"], "补图");
    if (action === "fill-missing-audio") return fillMissingAssets(["audio"], "补音频");
    if (action === "fill-missing-video") return fillMissingAssets(["video"], "补视频");
    if (action === "timeline-resize") return;
    if (
      [
        "split-scene",
        "merge-scene",
        "rerender-image",
        "rerender-audio",
        "rerender-video",
        "rebuild-scene",
        "restore-scene",
      ].includes(action)
    ) {
      if (button.dataset.sceneOrder)
        state.selectedSceneOrder = Number(button.dataset.sceneOrder || state.selectedSceneOrder);
      return sceneAction(action);
    }
  } catch (error) {
    showToast(error.message || String(error), "danger");
  }
}

function defaultReviewTriageState() {
  return {
    review_status: "all",
    governance_status: "all",
    provenance: "all",
    deliverable: "all",
    prototype_mode: "all",
    prototype_gap: "all",
    min_rating: 0,
    sort: "scene_order",
  };
}

function setReviewTriageField(field, value) {
  if (!field) return;
  const next = { ...defaultReviewTriageState(), ...(state.reviewTriageState || {}) };
  next[field] =
    field === "min_rating" ? Math.max(0, Math.min(5, asNumber(value, 0))) : String(value || "all");
  state.reviewTriageState = next;
  if (field === "review_status") state.reviewFilter = next.review_status;
}

function resetReviewTriage() {
  state.reviewTriageState = defaultReviewTriageState();
  state.reviewFilter = "all";
}

function reviewBatchActionLabel(action) {
  if (action === "rerender-image") return "image";
  if (action === "rerender-audio") return "audio";
  if (action === "rerender-video") return "video";
  if (action === "rebuild-scene") return "full rebuild";
  return action;
}

async function runReviewBatchRerender(action) {
  if (!state.currentProjectId || !state.project) return;
  const scenes = applyReviewTriage(
    timelineSceneItems(state.project),
    state.reviewTriageState || defaultReviewTriageState()
  );
  const supported = new Set([
    "rerender-image",
    "rerender-audio",
    "rerender-video",
    "rebuild-scene",
  ]);
  if (!supported.has(action) || !scenes.length) return;
  const label = reviewBatchActionLabel(action);
  const confirmed = window.confirm(
    `Run ${label} rerender for ${scenes.length} filtered scene(s)? This may take time and provider quota.`
  );
  if (!confirmed) return;

  state.reviewBatchRerender = {
    running: true,
    action,
    total: scenes.length,
    completed: 0,
    results: [],
  };
  setBusy(true, `Batch ${label}`);
  try {
    for (const scene of scenes) {
      const order = Number(scene.order || 0);
      state.selectedSceneOrder = order;
      render();
      try {
        await runSceneAction(action, order);
        state.reviewBatchRerender.results.push({ order, status: "ok", message: "completed" });
      } catch (error) {
        state.reviewBatchRerender.results.push({
          order,
          status: "failed",
          message: error.message || String(error),
        });
      } finally {
        state.reviewBatchRerender.completed += 1;
        render();
      }
    }
    const failures = state.reviewBatchRerender.results.filter(
      (item) => item.status === "failed"
    ).length;
    showToast(
      failures ? `Batch finished with ${failures} failure(s)` : "Batch rerender completed",
      failures ? "danger" : "ok"
    );
  } finally {
    state.reviewBatchRerender.running = false;
    setBusy(false);
  }
}

async function runReviewShotRerender(sceneOrderValue, shotId) {
  const sceneOrder = Number(sceneOrderValue || state.selectedSceneOrder || 0);
  const normalizedShotId = String(shotId || "").trim();
  if (!state.currentProjectId || !sceneOrder || !normalizedShotId) return;
  const confirmed = window.confirm(
    `Rerender shot ${normalizedShotId}? This may use provider quota.`
  );
  if (!confirmed) return;
  state.selectedSceneOrder = sceneOrder;
  setBusy(true, "Rerender shot");
  try {
    await runShotRerender(sceneOrder, normalizedShotId);
    showToast("Shot rerender submitted", "ok");
    await refreshCurrentProject();
  } finally {
    setBusy(false);
  }
}

function handleChange(event) {
  if (handleCropInput(event.target)) return;
  if (event.target?.dataset?.action === "review-triage-input") {
    setReviewTriageField(event.target.dataset.triageField, event.target.value);
    render();
    return;
  }
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
  if (event.target?.id === "bgmFileInput") {
    const file = event.target.files?.[0];
    if (file) {
      handleBgmFile(file).catch((error) => showToast(error?.message || "上传失败", "danger"));
    }
    event.target.value = "";
    return;
  }
  // Auto-fill reference text when selecting a voice sample
  if (
    event.target?.id === "characterReferenceAudioInput" ||
    event.target?.id === "sceneReferenceAudioInput"
  ) {
    const samplePath = event.target.value;
    const refTextMap = {};
    const refText = refTextMap[samplePath] || "";
    const textFieldId =
      event.target.id === "characterReferenceAudioInput"
        ? "characterReferenceTextInput"
        : "sceneReferenceTextInput";
    const textField = document.getElementById(textFieldId);
    if (textField && refText && !textField.value.trim()) {
      textField.value = refText;
    }
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
  if (event.target?.dataset?.action === "review-triage-input") {
    setReviewTriageField(event.target.dataset.triageField, event.target.value);
    render();
    return;
  }
  if (event.target?.dataset?.action === "task-search") {
    // 任务中心搜索：局部刷新表格，不全量重渲染（保留输入焦点）
    state.taskKeyword = event.target.value;
    const tbody = document.getElementById("tasksTableBody");
    if (tbody) tbody.innerHTML = renderTasksRows();
    return;
  }
  if (event.target?.dataset?.action === "bgm-search") {
    // BGM 搜索：局部刷新卡片网格，保留输入焦点（与 task-search 同一手法）
    state.bgmKeyword = event.target.value;
    const cards = document.getElementById("bgmCards");
    if (cards) cards.innerHTML = renderBgmCards();
    return;
  }
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

// ─── Task Center (C1) ────────────────────────────────────────────────────────
// 局部刷新是这里的重点：render() 会全量重建 DOM（render.js 的 appRoot.innerHTML
// = renderShell()），轮询若走全量渲染，用户正在搜索框输入时会被打断。
// 因此轮询与搜索都只替换三个容器的 innerHTML，不碰整棵树。

const TASKS_POLL_INTERVAL = 3000;
let tasksPollTimer = null;

export function startTasksPoll() {
  stopTasksPoll();
  if (state.activeTab !== "tasks") return;
  tasksPollTimer = setInterval(() => {
    refreshTasks({ silent: true });
  }, TASKS_POLL_INTERVAL);
}

export function stopTasksPoll() {
  if (tasksPollTimer) {
    clearInterval(tasksPollTimer);
    tasksPollTimer = null;
  }
}

function taskSyncText() {
  if (state.tasksLoading) return "同步中…";
  if (state.tasksError) return "同步失败";
  if (!state.tasksLastSync) return "尚未同步";
  return `已同步 ${new Date(state.tasksLastSync).toLocaleTimeString("zh-CN", { hour12: false })}`;
}

function patchTasksDom() {
  if (state.activeTab !== "tasks") return;
  const stats = document.getElementById("tasksStats");
  const tbody = document.getElementById("tasksTableBody");
  const detail = document.getElementById("tasksDetail");
  const hint = document.getElementById("tasksSyncHint");
  if (stats) stats.innerHTML = renderTasksStats();
  if (tbody) tbody.innerHTML = renderTasksRows();
  if (detail) detail.innerHTML = renderTasksDetail();
  if (hint) hint.textContent = taskSyncText();
}

export async function refreshTasks({ silent = false } = {}) {
  if (state.activeTab !== "tasks") return;
  state.tasksLoading = true;
  if (!silent) patchTasksDom();
  try {
    await loadTasks();
    state.tasksError = "";
    if (state.selectedTaskId) {
      await loadTaskDetail(state.selectedTaskId);
      await loadTaskFiles(state.selectedTaskId);
    }
  } catch (error) {
    state.tasksError = error?.message || "加载任务失败";
  } finally {
    state.tasksLoading = false;
    patchTasksDom();
  }
}

async function selectTask(taskId) {
  if (state.selectedTaskId === taskId) return;
  state.selectedTaskId = taskId;
  state.selectedTaskDetail = null;
  state.selectedTaskFiles = [];
  patchTasksDom();
  try {
    await loadTaskDetail(taskId);
    await loadTaskFiles(taskId);
  } catch (error) {
    state.tasksError = error?.message || "加载任务详情失败";
  } finally {
    patchTasksDom();
  }
}

// ─── BGM Library (C2) ──────────────────────────────────────────────────────────
// 与 C1 任务中心不同，BGM 库不是实时数据：素材只在上传时变化，因此不做轮询，
// 仅在进入该页时 refreshBgm 一次 + 上传后刷新。搜索 / 筛选走局部 DOM 替换保留焦点。

function bgmSyncText() {
  if (state.bgmLoading) return "同步中…";
  if (state.bgmError) return "同步失败";
  if (!state.bgmLastSync) return "尚未同步";
  return `已同步 ${new Date(state.bgmLastSync).toLocaleTimeString("zh-CN", { hour12: false })}`;
}

function patchBgmDom() {
  if (state.activeTab !== "bgm") return;
  const stats = document.getElementById("bgmStats");
  const cards = document.getElementById("bgmCards");
  const detail = document.getElementById("bgmDetail");
  const player = document.getElementById("bgmPlayer");
  const hint = document.getElementById("bgmSyncHint");
  if (stats) stats.innerHTML = renderBgmStats();
  if (cards) cards.innerHTML = renderBgmCards();
  if (detail) detail.innerHTML = renderBgmDetail();
  if (player) player.innerHTML = renderBgmPlayer();
  if (hint) hint.textContent = bgmSyncText();
}

export async function refreshBgm() {
  if (state.activeTab !== "bgm") return;
  state.bgmLoading = true;
  patchBgmDom();
  try {
    await loadBgm();
    state.bgmError = "";
  } catch (error) {
    state.bgmError = error?.message || "加载 BGM 素材库失败";
  } finally {
    state.bgmLoading = false;
    patchBgmDom();
  }
}

async function selectBgm(path) {
  if (state.selectedBgmPath === path) return;
  state.selectedBgmPath = path;
  patchBgmDom();
  const audio = document.getElementById("bgmAudioBar");
  if (audio) audio.play().catch(() => {});
}

const BGM_UPLOAD_MAX_BYTES = 10 * 1024 * 1024; // 后端上限 10 MB
const BGM_ALLOWED_EXT = [".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"];
const BGM_ALLOWED_STYLE = /^[a-zA-Z0-9_-]+$/;

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("读取文件失败"));
    reader.readAsDataURL(file);
  });
}

async function handleBgmFile(file) {
  if (!file) return;
  const name = file.name || "bgm_upload";
  const ext = name.toLowerCase().slice(name.lastIndexOf("."));
  if (!BGM_ALLOWED_EXT.includes(ext)) {
    throw new Error(`不支持的格式：${ext || "无扩展名"}（允许 ${BGM_ALLOWED_EXT.join(", ")}）`);
  }
  if (file.size > BGM_UPLOAD_MAX_BYTES) {
    throw new Error(`文件过大：${(file.size / 1024 / 1024).toFixed(1)} MB，后端上限 10 MB`);
  }
  // 上传目录（style）默认用当前筛选风格；"全部"时落到 uploads 分组，名称需符合后端白名单
  const style = state.selectedBgmStyle && state.selectedBgmStyle !== "all" ? state.selectedBgmStyle : "uploads";
  if (!BGM_ALLOWED_STYLE.test(style)) {
    throw new Error("当前筛选风格名含非法字符，无法作为上传目录");
  }
  if (state.bgmUploading) {
    throw new Error("正在上传中，请稍候");
  }
  state.bgmUploading = true;
  try {
    const dataUrl = await readFileAsDataUrl(file);
    const result = await uploadBgm(name, style, dataUrl);
    showToast("BGM 上传成功", "ok");
    await refreshBgm();
    state.selectedBgmPath = result?.path || `assets/audio/bgm/${style}/${name}`;
    patchBgmDom();
  } catch (error) {
    state.bgmUploadError = error?.message || "上传失败";
    throw error;
  } finally {
    state.bgmUploading = false;
  }
}

// ─── Boot ────────────────────────────────────────────────────────────────────

export async function boot() {
  clearProjectPoll();
  appRoot.addEventListener("click", handleClick);
  appRoot.addEventListener("mousedown", (event) => {
    const temporalShotHandle = event.target.closest?.('[data-action="temporal-shot-resize"]');
    if (temporalShotHandle) {
      startTemporalShotDrag(event, temporalShotHandle);
      return;
    }
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
    handleTemporalShotMove(event);
    updateSfxDragPosition(event);
  });
  document.addEventListener("pointerup", (event) => {
    finishTimelineDrag(event);
    finishTemporalShotDrag(event);
    finishSfxDrag(event);
  });
  document.addEventListener("pointercancel", (event) => {
    finishTimelineDrag(event);
    finishTemporalShotDrag(event);
    finishSfxDrag(event);
  });
  document.addEventListener("mousemove", (event) => {
    handleTimelineMove(event);
    handleTemporalShotMove(event);
    updateSfxDragPosition(event);
  });
  document.addEventListener("mouseup", (event) => {
    finishTimelineDrag(event);
    finishTemporalShotDrag(event);
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
    // 项目列表加载与状态探测解耦：任一状态接口失败不应阻断项目列表。
    await loadProjects(true);
  } catch (error) {
    render();
    showToast(error.message || "启动失败", "danger");
    return;
  }
  const statusResults = await Promise.allSettled([
    loadVoiceCatalog(),
    loadTtsProviders(),
    loadVideoProviderStatus(),
    loadComfyUIStatus(),
  ]);
  const failures = statusResults.filter((item) => item.status === "rejected");
  if (failures.length) {
    const reason = failures[0].reason;
    showToast(`部分状态加载失败：${reason?.message || reason || "未知错误"}`, "warn");
  }
}
