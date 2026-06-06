// ─── Pure Utility Functions ──────────────────────────────────────────────────

import { state, DEFAULT_CROP_BOX, STORAGE_KEYS, reviewStatusOptions } from "./state.js";

export function h(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function nl(value) {
  return h(value).replaceAll("\n", "<br>");
}

export function asNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

export function clamp(value, min = 0, max = 1) {
  return Math.min(max, Math.max(min, asNumber(value, min)));
}

export function normalizeCropBox(cropBox) {
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

export function cropBoxFromInputs(fallback = DEFAULT_CROP_BOX) {
  return normalizeCropBox({
    x: asNumber(getValue("sceneCropXInput", fallback.x), fallback.x),
    y: asNumber(getValue("sceneCropYInput", fallback.y), fallback.y),
    width: asNumber(getValue("sceneCropWidthInput", fallback.width), fallback.width),
    height: asNumber(getValue("sceneCropHeightInput", fallback.height), fallback.height),
  });
}

export function cropPercent(value) {
  return `${(clamp(value) * 100).toFixed(2)}%`;
}

export function formatSeconds(value) {
  return `${asNumber(value, 0).toFixed(1)}s`;
}

export function looksGarbledScriptText(value) {
  const text = String(value ?? "").trim();
  if (!text) return false;
  if (/[A-Za-z\u4e00-\u9fff]/.test(text)) return false;
  const damagedMarks = (text.match(/[?\uFFFD]/g) || []).length;
  return damagedMarks >= Math.max(4, Math.floor(text.length / 5));
}

export function statusClass(status) {
  if (["completed", "done", "idle", "draft"].includes(String(status || "").toLowerCase())) return "ok";
  if (["failed", "error"].includes(String(status || "").toLowerCase())) return "danger";
  return "warn";
}

export function previewSceneFieldId(order, field) {
  return `scriptPreviewScene${field}${order}`;
}

export function splitPreviewCharacters(value) {
  return String(value ?? "")
    .split(/[,，、\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function selectedScene(project = state.project) {
  const scenes = project?.scenes || [];
  return scenes.find((scene) => Number(scene.order) === Number(state.selectedSceneOrder)) || scenes[0] || null;
}

export function canonicalTimeline(project = state.project) {
  const timeline = project?.canonical_timeline;
  return timeline && typeof timeline === "object" ? timeline : null;
}

export function canonicalPictureTrack(project = state.project) {
  const timeline = canonicalTimeline(project);
  const tracks = Array.isArray(timeline?.tracks) ? timeline.tracks : [];
  return tracks.find((track) => track?.track_id === "picture" || track?.track_type === "video") || null;
}

export function timelineSceneItems(project = state.project) {
  const scenes = Array.isArray(project?.scenes) ? project.scenes : [];
  const sceneByOrder = new Map(scenes.map((scene) => [Number(scene.order), scene]));
  const pictureTrack = canonicalPictureTrack(project);
  const clips = Array.isArray(pictureTrack?.children) ? pictureTrack.children : [];
  if (!clips.length) return scenes;
  return clips.map((clip, index) => {
    const order = Number(clip.scene_order || index + 1);
    const scene = sceneByOrder.get(order) || {};
    const assets = { ...(scene.assets || {}) };
    const media = clip.media_reference && typeof clip.media_reference === "object" ? clip.media_reference : {};
    const clipMetadata = clip.metadata && typeof clip.metadata === "object" ? clip.metadata : {};
    const clipGeneration = clipMetadata.generation && typeof clipMetadata.generation === "object" ? clipMetadata.generation : null;
    if (media.url && !assets.video_url && String(media.path || "").toLowerCase().endsWith(".mp4")) assets.video_url = media.url;
    if (media.url && !assets.image_url && !String(media.path || "").toLowerCase().endsWith(".mp4")) assets.image_url = media.url;
    return {
      ...scene,
      order,
      scene_id: clip.scene_id || scene.scene_id || `scene_${String(order).padStart(3, "0")}`,
      title: clip.name || scene.title || `Scene ${order}`,
      duration_seconds: asNumber(clip.duration_seconds, scene.duration_seconds ?? 4),
      start_seconds: asNumber(clip.start_seconds, 0),
      end_seconds: asNumber(clip.end_seconds, 0),
      timeline_clip_id: clip.clip_id || "",
      timeline_media_reference: media,
      generation_meta: scene.generation_meta || clipGeneration || {},
      assets,
    };
  });
}

export function selectedCharacter(project = state.project) {
  const characters = project?.characters || [];
  return characters[Math.max(0, Number(state.selectedCharacterIndex || 1) - 1)] || characters[0] || null;
}

export function characterKey(value) {
  return String(value ?? "").trim().toLowerCase();
}

export function characterNamesFromFieldValue(value) {
  return String(value ?? "")
    .split(/[,，\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function sceneCharacterNames(scene) {
  return Array.isArray(scene?.characters) ? scene.characters.map((item) => String(item ?? "").trim()).filter(Boolean) : [];
}

export function getValue(id, fallback = "") {
  const element = document.getElementById(id);
  return element ? element.value : fallback;
}

export function getChecked(id) {
  return Boolean(document.getElementById(id)?.checked);
}

export function titleFromFilename(filename) {
  const base = String(filename || "")
    .replace(/\.[^.]+$/, "")
    .trim();
  if (!base) return "";
  return base.replace(/[._-]+/g, " ").replace(/\s+/g, " ").trim();
}

export async function readTextFile(file) {
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

export function storedValue(key, fallback = "") {
  try {
    return window.localStorage.getItem(STORAGE_KEYS[key]) || fallback;
  } catch {
    return fallback;
  }
}

export function setStoredValue(key, value) {
  try {
    window.localStorage.setItem(STORAGE_KEYS[key], String(value || ""));
  } catch {
    // ignore storage failures
  }
}

export function normalizeExternalUrl(raw, fallback = "") {
  const value = String(raw || fallback || "").trim();
  if (!value) return "";
  try {
    const url = new URL(value);
    return url.toString().replace(/\/$/, "");
  } catch {
    return "";
  }
}

export function comfyuiEditorUrl() {
  return normalizeExternalUrl(getValue("comfyuiBaseUrlInput", storedValue("comfyuiBaseUrl", "http://127.0.0.1:8188")), "http://127.0.0.1:8188");
}

export function sceneAudioManifest(scene) {
  return scene?.audio_manifest && typeof scene.audio_manifest === "object" ? scene.audio_manifest : {};
}

export function sceneSfxTrigger(scene) {
  const manifest = sceneAudioManifest(scene);
  return manifest.sfx_trigger && typeof manifest.sfx_trigger === "object" ? manifest.sfx_trigger : {};
}

export function sceneShots(scene) {
  return Array.isArray(scene?.shots) ? scene.shots : [];
}

export function sceneTemporalShots(scene) {
  const spec = scene?.temporal_spec && typeof scene.temporal_spec === "object" ? scene.temporal_spec : {};
  return Array.isArray(spec.shots) && spec.shots.length ? spec.shots : sceneShots(scene);
}

export function temporalShotTimeline(shots) {
  let cursor = 0;
  return shots.map((shot, index) => {
    const duration = Math.max(0.25, asNumber(shot.duration_seconds, 0.25));
    const start = cursor;
    const end = start + duration;
    cursor = end;
    return {
      shot,
      index,
      order: Number(shot.shot_order || index + 1),
      duration,
      start,
      end,
    };
  });
}

export function sceneDurationMs(scene) {
  return Math.max(250, Number(scene?.duration_seconds || 4) * 1000);
}

export function shotBeatClass(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9_-]/g, "");
}

export function shotEditorId(order, field) {
  return `sceneShot${field}_${order}`;
}

export function sceneAssetGaps(scene) {
  const assets = scene?.assets || {};
  const gaps = [];
  if (!assets.image_url) gaps.push("图片");
  if ((scene?.dialogue || "").trim() && !assets.audio_url) gaps.push("音频");
  if (!assets.video_url) gaps.push("视频");
  return gaps;
}

export function projectAssetGapEntries(project) {
  return (project?.scenes || [])
    .map((scene) => ({ scene, gaps: sceneAssetGaps(scene) }))
    .filter((entry) => entry.gaps.length);
}

export function projectHasAssetGaps(project = state.project) {
  return projectAssetGapEntries(project).length > 0;
}

export function projectIsBusy(project = state.project) {
  const status = String(project?.runtime?.status || "").toLowerCase();
  const stage = String(project?.runtime?.stage || "").toLowerCase();
  return ["queued", "running", "repairing"].includes(status) || stage === "repairing" || stage.startsWith("scene_");
}

export function sceneReviewMeta(scene) {
  const meta = scene?.review_meta && typeof scene.review_meta === "object" ? scene.review_meta : {};
  return {
    status: String(meta.status || "unreviewed"),
    rating: Math.max(0, Math.min(5, asNumber(meta.rating, 0))),
    note: String(meta.note || ""),
    reviewed_at: String(meta.reviewed_at || ""),
  };
}

function sceneGovernanceStatus(scene) {
  const governance = scene?.governance && typeof scene.governance === "object" ? scene.governance : {};
  return String(governance.status || "not_evaluated");
}

function sceneGovernanceBlocked(scene) {
  const governance = scene?.governance && typeof scene.governance === "object" ? scene.governance : {};
  const policy = governance.policy && typeof governance.policy === "object" ? governance.policy : {};
  return policy.mode === "block" && governance.deliverable === false;
}

function sceneGenerationKind(scene) {
  const meta = scene?.generation_meta && typeof scene.generation_meta === "object" ? scene.generation_meta : {};
  if (!Object.keys(meta).length) return "unknown";
  if (meta.fallback_used) return "fallback";
  if (meta.is_real_video) return "real";
  return "local";
}

function triageValue(triage, key, fallback = "all") {
  const value = triage && typeof triage === "object" ? triage[key] : "";
  return String(value || fallback);
}

function governanceSeverity(status) {
  if (status === "fail") return 3;
  if (status === "warn") return 2;
  if (status === "not_evaluated") return 1;
  return 0;
}

export function deriveReviewOverview(project = state.project) {
  const scenes = timelineSceneItems(project);
  const ledger = project?.continuity_ledger && typeof project.continuity_ledger === "object" ? project.continuity_ledger : {};
  const ledgerCounts = ledger.status_counts && typeof ledger.status_counts === "object" ? ledger.status_counts : {};
  const overview = {
    total_scenes: scenes.length,
    review: {
      unreviewed: 0,
      approved: 0,
      needs_work: 0,
      blocked: 0,
      rated: 0,
      unrated: 0,
    },
    provenance: {
      real: 0,
      fallback: 0,
      local: 0,
      unknown: 0,
    },
    continuity: {
      pass: asNumber(ledgerCounts.pass, 0),
      warn: asNumber(ledgerCounts.warn, 0),
      fail: asNumber(ledgerCounts.fail, 0),
      not_evaluated: asNumber(ledgerCounts.not_evaluated, 0),
      blocked_scene_count: asNumber(ledger.blocked_scene_count, 0),
    },
    readiness: {
      deliverable: 0,
      blocked: 0,
      asset_gaps: 0,
    },
  };

  for (const scene of scenes) {
    const review = sceneReviewMeta(scene);
    const status = review.status || "unreviewed";
    overview.review[status] = (overview.review[status] || 0) + 1;
    if (review.rating > 0) overview.review.rated += 1;
    else overview.review.unrated += 1;

    overview.provenance[sceneGenerationKind(scene)] += 1;
    if (sceneGovernanceBlocked(scene)) overview.readiness.blocked += 1;
    else overview.readiness.deliverable += 1;
    if (sceneAssetGaps(scene).length) overview.readiness.asset_gaps += 1;
  }

  const continuityTotal = overview.continuity.pass + overview.continuity.warn + overview.continuity.fail + overview.continuity.not_evaluated;
  if (!continuityTotal && scenes.length) overview.continuity.not_evaluated = scenes.length;
  return overview;
}

export function applyReviewTriage(scenes, triage = {}) {
  const source = Array.isArray(scenes) ? scenes : [];
  const reviewStatus = triageValue(triage, "review_status", triageValue(triage, "reviewFilter", "all"));
  const governanceStatus = triageValue(triage, "governance_status");
  const provenance = triageValue(triage, "provenance");
  const deliverable = triageValue(triage, "deliverable");
  const minRating = Math.max(0, Math.min(5, asNumber(triage?.min_rating, 0)));
  const sort = triageValue(triage, "sort", "scene_order");

  const filtered = source.filter((scene) => {
    const review = sceneReviewMeta(scene);
    if (reviewStatus !== "all" && review.status !== reviewStatus) return false;
    if (governanceStatus !== "all" && sceneGovernanceStatus(scene) !== governanceStatus) return false;
    if (provenance !== "all" && sceneGenerationKind(scene) !== provenance) return false;
    if (minRating > 0 && review.rating < minRating) return false;
    if (deliverable === "blocked" && !sceneGovernanceBlocked(scene)) return false;
    if (deliverable === "deliverable" && sceneGovernanceBlocked(scene)) return false;
    if (deliverable === "asset_gaps" && !sceneAssetGaps(scene).length) return false;
    return true;
  });

  return filtered.slice().sort((a, b) => {
    if (sort === "rating_desc") {
      const diff = sceneReviewMeta(b).rating - sceneReviewMeta(a).rating;
      if (diff) return diff;
    }
    if (sort === "governance_severity") {
      const diff = governanceSeverity(sceneGovernanceStatus(b)) - governanceSeverity(sceneGovernanceStatus(a));
      if (diff) return diff;
    }
    if (sort === "fallback_first") {
      const aScore = sceneGenerationKind(a) === "fallback" ? 1 : 0;
      const bScore = sceneGenerationKind(b) === "fallback" ? 1 : 0;
      if (bScore - aScore) return bScore - aScore;
    }
    return Number(a?.order || 0) - Number(b?.order || 0);
  });
}

export function reviewStatusLabel(status) {
  const entry = reviewStatusOptions.find(([value]) => value === status);
  return entry ? entry[1] : "未审";
}

export function reviewStatusClass(status) {
  if (status === "approved") return "is-approved";
  if (status === "needs_work") return "is-needs-work";
  if (status === "blocked") return "is-blocked";
  return "is-unreviewed";
}

export function cameraClassName(camera) {
  const value = String(camera || "").toLowerCase().replace(/[^a-z0-9_-]/g, "");
  if (["dramatic_push", "melancholy_pan", "establishing_tilt"].includes(value)) return value;
  if (value.includes("pan")) return "melancholy_pan";
  if (value.includes("tilt")) return "establishing_tilt";
  if (value.includes("push") || value.includes("reveal")) return "dramatic_push";
  return "slow_push_in";
}

export function assetStatusLabel(status) {
  if (status === "done") return "已完成";
  if (status === "generating") return "生成中";
  if (status === "failed") return "失败";
  return "待生成";
}

export function assetTypeLabel(type) {
  if (type === "scene_bg") return "场景";
  if (type === "prop") return "道具";
  return "角色";
}

export function fieldText(id, label, value = "", placeholder = "") {
  return `<label class="field"><span>${h(label)}</span><input id="${h(id)}" type="text" value="${h(value)}" placeholder="${h(placeholder)}"></label>`;
}

export function fieldNumber(id, label, value = "", attrs = "") {
  return `<label class="field"><span>${h(label)}</span><input id="${h(id)}" type="number" value="${h(value)}" ${attrs}></label>`;
}

export function fieldTextarea(id, label, value = "", rows = 4, placeholder = "") {
  return `<label class="field full"><span>${h(label)}</span><textarea id="${h(id)}" rows="${rows}" placeholder="${h(placeholder)}">${h(value)}</textarea></label>`;
}

export function fieldSelect(id, label, options, value = "") {
  return `<label class="field"><span>${h(label)}</span><select id="${h(id)}">${options
    .map(([optionValue, optionLabel]) => `<option value="${h(optionValue)}" ${String(optionValue) === String(value) ? "selected" : ""}>${h(optionLabel)}</option>`)
    .join("")}</select></label>`;
}

export function fieldCheckbox(id, label, checked) {
  return `<label class="toggle-field"><input id="${h(id)}" type="checkbox" ${checked ? "checked" : ""}><span>${h(label)}</span></label>`;
}

export function findShotByOrder(shots, order) {
  const numericOrder = Number(order || 0);
  return shots.find((shot, index) => Number(shot.shot_order || index + 1) === numericOrder) || null;
}

export function snapTemporalShotDuration(value, shiftKey = false) {
  const step = shiftKey ? 0.01 : 0.1;
  const snapped = Math.round(value / step) * step;
  return Number(Math.max(0.25, snapped).toFixed(2));
}
