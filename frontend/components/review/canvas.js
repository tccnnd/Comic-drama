// ─── Director Review Canvas (v0.4+) ───────────────────────────────────────────
// Extracted from render.js to make the v0.4 review console navigable in
// isolation. All 26 functions below were previously private helpers in
// render.js. The single export (renderStoryboardReviewCanvas) is re-exported
// from render.js so external imports keep working unchanged.

import {
  state,
  reviewFilterOptions,
  reviewGovernanceFilterOptions,
  reviewProvenanceFilterOptions,
  reviewDeliverableFilterOptions,
  reviewPrototypeModeFilterOptions,
  reviewPrototypeGapFilterOptions,
  reviewSortOptions,
  reviewStatusOptions,
} from "../../state.js";
import {
  h,
  nl,
  asNumber,
  formatSeconds,
  timelineSceneItems,
  applyReviewTriage,
  deriveReviewOverview,
  sceneReviewMeta,
  sceneShotRenderEntries,
  reviewStatusClass,
  reviewStatusLabel,
  shotRenderStatusClass,
  shotRenderStatusLabel,
  sceneGovernance,
  governanceStatus,
  governanceStatusClass,
  governanceStatusLabel,
  sceneAssetGaps,
  scenePrototypeEntries,
  projectContinuityLedger,
  fieldSelect,
  fieldNumber,
  fieldTextarea,
} from "../../utils.js";

// Public: render the full review console (overview + triage + list + detail).
export function renderStoryboardReviewCanvas(project) {
  const scenes = timelineSceneItems(project);
  if (!scenes.length) return `<div class="empty-state">暂无 canonical timeline。</div>`;
  const triage = activeReviewTriageState();
  const visibleScenes = applyReviewTriage(scenes, triage);
  const selected =
    visibleScenes.find((scene) => Number(scene.order) === Number(state.selectedSceneOrder)) ||
    selectedTimelineScene(project);
  const filter = triage.review_status;
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
      ${renderProviderReadinessBanner(project)}
      ${renderReviewOverviewHeader(project)}
      ${renderReviewTriageBar(project)}
      <div class="review-summary">
        <span>${h(scenes.length)} 镜</span>
        <span>通过 ${h(summary.approved || 0)}</span>
        <span>需修改 ${h(summary.needs_work || 0)}</span>
        <span>阻塞 ${h(summary.blocked || 0)}</span>
        <span>连贯 ${h(counts.pass || 0)} / ${h(counts.warn || 0)} / ${h(counts.fail || 0)}</span>
        ${blocked ? `<span class="danger-text">治理阻塞 ${h(blocked)}</span>` : ""}
      </div>
      <div class="review-filter-bar">
        ${reviewFilterOptions
          .map(
            ([value, label]) => `
          <button class="filter-chip ${filter === value ? "is-active" : ""}" type="button" data-action="review-filter" data-review-filter="${h(value)}">${h(label)}</button>
        `
          )
          .join("")}
      </div>
      <div class="storyboard-review-list">
        ${visibleScenes.length ? visibleScenes.map(renderStoryboardReviewCard).join("") : `<div class="empty-state">当前筛选下没有分镜。</div>`}
      </div>
      <div class="storyboard-review-detail">
        ${renderStoryboardReviewDetail(selected)}
      </div>
    </div>
  `;
}

function renderProviderReadinessBanner(project) {
  if (!project) return "";
  if (state.videoProviderStatusLoading) {
    return `
      <div class="review-provider-banner is-loading">
        <strong>Video provider check running</strong>
        <span>Provider readiness is still loading.</span>
      </div>
    `;
  }
  if (state.videoProviderStatusError) {
    return `
      <div class="review-provider-banner is-error">
        <strong>Video provider status unavailable</strong>
        <span>${h(state.videoProviderStatusError)}</span>
      </div>
    `;
  }
  const status =
    state.videoProviderStatus && typeof state.videoProviderStatus === "object"
      ? state.videoProviderStatus
      : {};
  const provider = status.provider && typeof status.provider === "object" ? status.provider : {};
  const readiness =
    status.readiness && typeof status.readiness === "object" ? status.readiness : {};
  const backend = String(provider.backend || "").toLowerCase();
  if (!backend || backend === "local" || readiness.ready === true) return "";
  const label = provider.label || provider.id || project.settings?.video_provider || "auto";
  const blocking = Array.isArray(readiness.blocking_env) ? readiness.blocking_env : [];
  const summary = readiness.summary || "Provider configuration is incomplete.";
  return `
    <div class="review-provider-banner is-warning">
      <strong>${h(label)} is not ready</strong>
      <span>${h(summary)}${blocking.length ? ` Required: ${h(blocking.join(", "))}.` : ""}</span>
    </div>
  `;
}

// Pick the currently selected scene from the timeline (or fall back to the first).
function selectedTimelineScene(project = state.project) {
  const scenes = timelineSceneItems(project);
  return (
    scenes.find((scene) => Number(scene.order) === Number(state.selectedSceneOrder)) ||
    scenes[0] ||
    null
  );
}

// Read the live triage state from global state, applying defaults for missing keys.
function activeReviewTriageState() {
  const triage =
    state.reviewTriageState && typeof state.reviewTriageState === "object"
      ? state.reviewTriageState
      : {};
  return {
    review_status: triage.review_status || state.reviewFilter || "all",
    governance_status: triage.governance_status || "all",
    provenance: triage.provenance || "all",
    deliverable: triage.deliverable || "all",
    prototype_mode: triage.prototype_mode || "all",
    prototype_gap: triage.prototype_gap || "all",
    min_rating: asNumber(triage.min_rating, 0),
    sort: triage.sort || "scene_order",
  };
}

// Top-of-canvas overview chips (counts driven by derived review metrics).
function renderReviewOverviewHeader(project) {
  const overview = deriveReviewOverview(project);
  const continuity = overview.continuity || {};
  const provenance = overview.provenance || {};
  const review = overview.review || {};
  const readiness = overview.readiness || {};
  const prototype = overview.prototype || {};
  const reviewed = overview.total_scenes - (review.unreviewed || 0);
  return `
    <div class="review-overview">
      ${renderReviewMetric("review_status", "all", "Scenes", overview.total_scenes)}
      ${renderReviewMetric("review_status", "approved", "Approved", review.approved || 0)}
      ${renderReviewMetric("review_status", "needs_work", "Needs work", review.needs_work || 0)}
      ${renderReviewMetric("review_status", "blocked", "Review blocked", review.blocked || 0)}
      ${renderReviewMetric("provenance", "real", "Real video", provenance.real || 0)}
      ${renderReviewMetric("provenance", "fallback", "Fallback", provenance.fallback || 0)}
      ${renderReviewMetric("governance_status", "fail", "Continuity fail", continuity.fail || 0, continuity.fail || 0 ? "is-danger" : "")}
      ${renderReviewMetric("deliverable", "blocked", "Export blocked", readiness.blocked || 0, readiness.blocked ? "is-danger" : "")}
      <div class="review-overview-progress">
        <span>Reviewed ${h(reviewed)} / ${h(overview.total_scenes)}</span>
        <span>Continuity ${h(continuity.pass || 0)} / ${h(continuity.warn || 0)} / ${h(continuity.fail || 0)} / ${h(continuity.not_evaluated || 0)}</span>
        <span>Prototype ${h(prototype.prototype_lock || 0)} lock / ${h(prototype.freeform || 0)} free / ${h(Object.keys(prototype.gaps || {}).length)} gaps</span>
      </div>
    </div>
  `;
}

// A single clickable overview chip; clicking sets the matching triage filter.
function renderReviewMetric(field, value, label, count, extraClass = "") {
  return `
    <button class="review-metric ${h(extraClass)}" type="button" data-action="review-overview-filter" data-triage-field="${h(field)}" data-triage-value="${h(value)}">
      <span>${h(label)}</span>
      <strong>${h(count)}</strong>
    </button>
  `;
}

// Triage controls + batch rerender row.
function renderReviewTriageBar(project) {
  const triage = activeReviewTriageState();
  const scenes = timelineSceneItems(project);
  const visible = applyReviewTriage(scenes, triage).length;
  return `
    <div class="review-triage-bar">
      <div class="review-triage-controls">
        ${renderTriageSelect("governance_status", reviewGovernanceFilterOptions, triage.governance_status)}
        ${renderTriageSelect("provenance", reviewProvenanceFilterOptions, triage.provenance)}
        ${renderTriageSelect("deliverable", reviewDeliverableFilterOptions, triage.deliverable)}
        ${renderTriageSelect("prototype_mode", reviewPrototypeModeFilterOptions, triage.prototype_mode)}
        ${renderTriageSelect("prototype_gap", reviewPrototypeGapFilterOptions, triage.prototype_gap)}
        <label class="triage-field"><span>Min rating</span><input type="number" min="0" max="5" step="0.5" value="${h(triage.min_rating || 0)}" data-action="review-triage-input" data-triage-field="min_rating"></label>
        ${renderTriageSelect("sort", reviewSortOptions, triage.sort)}
        <button type="button" class="ghost-button" data-action="review-triage-reset">Reset</button>
        <span class="muted">${h(visible)} / ${h(scenes.length)} shown</span>
      </div>
      ${renderBatchRerenderBar(visible)}
    </div>
  `;
}

// Single labeled <select> wired into the triage input handler.
function renderTriageSelect(field, options, value) {
  return `
    <label class="triage-field">
      <span>${h(field.replaceAll("_", " "))}</span>
      <select data-action="review-triage-input" data-triage-field="${h(field)}">
        ${options.map(([optionValue, optionLabel]) => `<option value="${h(optionValue)}" ${String(optionValue) === String(value) ? "selected" : ""}>${h(optionLabel)}</option>`).join("")}
      </select>
    </label>
  `;
}

// Batch rerender controls + progress tail of the last 4 results.
function renderBatchRerenderBar(visibleCount) {
  const batch =
    state.reviewBatchRerender && typeof state.reviewBatchRerender === "object"
      ? state.reviewBatchRerender
      : {};
  const running = Boolean(batch.running);
  const results = Array.isArray(batch.results) ? batch.results : [];
  const latest = results.slice(-4);
  return `
    <div class="review-batch-bar">
      <div class="review-batch-actions">
        <span class="section-label">Filtered rerender</span>
        ${renderBatchButton("rerender-image", "Image", visibleCount, running)}
        ${renderBatchButton("rerender-audio", "Audio", visibleCount, running)}
        ${renderBatchButton("rerender-video", "Video", visibleCount, running)}
        ${renderBatchButton("rebuild-scene", "Full", visibleCount, running)}
        <label class="lock-reference-toggle" title="重绘图时沿用场景参考图，保持角色长相不变；取消勾选则按文字重新想象">
          <input type="checkbox" data-action="lock-reference-toggle" ${state.lockReference !== false ? "checked" : ""}>
          <span>锁定角色</span>
        </label>
      </div>
      ${
        running || results.length
          ? `
        <div class="review-batch-progress">
          <span>${running ? "Running" : "Last batch"} ${h(batch.completed || 0)} / ${h(batch.total || 0)}</span>
          ${latest.map((item) => `<span class="${item.status === "failed" ? "danger-text" : "muted"}">#${h(item.order)} ${h(item.status)}${item.message ? `: ${h(item.message)}` : ""}</span>`).join("")}
        </div>
      `
          : ""
      }
    </div>
  `;
}

// Single batch action button (disabled while running or empty).
function renderBatchButton(action, label, visibleCount, running) {
  return `<button class="ghost-button small" type="button" data-action="review-batch-rerender" data-batch-action="${h(action)}" ${running || !visibleCount ? "disabled" : ""}>${h(label)}</button>`;
}

// Normalize scene.generation_meta to an object (legacy scenes may be missing it).
function sceneGenerationMeta(scene) {
  return scene?.generation_meta && typeof scene.generation_meta === "object"
    ? scene.generation_meta
    : {};
}

// Map a generation_meta to a CSS class for the badge.
function generationBadgeClass(meta) {
  if (!meta || !Object.keys(meta).length) return "is-unknown";
  if (meta.fallback_used) return "is-fallback";
  if (meta.is_real_video) return "is-real";
  return "is-local";
}

// Map a generation_meta to a human label.
function generationLabel(meta) {
  if (!meta || !Object.keys(meta).length) return "Unknown";
  if (meta.fallback_used) return "2.5D fallback";
  if (meta.is_real_video) return "Real video";
  return "Local 2.5D";
}

// Compact badge summarizing how the scene was generated.
function renderGenerationBadge(scene) {
  const meta = sceneGenerationMeta(scene);
  const provider = meta.provider_label || meta.provider_id || "";
  const attempts = Number(meta.attempts || 0);
  const suffix = [provider, attempts > 1 ? `${attempts} tries` : ""].filter(Boolean).join(" · ");
  return `<div class="generation-badge ${generationBadgeClass(meta)}">${h(generationLabel(meta))}${suffix ? ` · ${h(suffix)}` : ""}</div>`;
}

// Detailed generation panel (provider, backend, attempts, error).
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

function renderShotRenderSummary(scene) {
  const entries = sceneShotRenderEntries(scene);
  const rendered = entries.filter((entry) => entry.status !== "planned");
  if (!rendered.length) return "";
  const counts = rendered.reduce((acc, entry) => {
    acc[entry.status] = (acc[entry.status] || 0) + 1;
    return acc;
  }, {});
  const parts = [
    counts.real_video ? `${counts.real_video} real` : "",
    counts.fallback ? `${counts.fallback} fallback` : "",
    counts.failed ? `${counts.failed} failed` : "",
    counts.skipped ? `${counts.skipped} skipped` : "",
  ].filter(Boolean);
  return `<span class="shot-render-summary">${h(parts.join(" / ") || `${rendered.length} rendered shot(s)`)}</span>`;
}

function renderShotRenderDetail(scene) {
  const entries = sceneShotRenderEntries(scene);
  const meta = sceneGenerationMeta(scene);
  if (!entries.length) {
    return `<div class="shot-render-detail is-unknown"><strong>Shot render status</strong><span>No shot data</span></div>`;
  }
  const rendered = entries.filter((entry) => entry.status !== "planned");
  const title =
    meta.render_granularity === "shot" || rendered.length ? "Shot render status" : "Planned shots";
  return `
    <div class="shot-render-detail ${rendered.length ? "" : "is-planned"}">
      <strong>${h(title)}</strong>
      <span>${h(rendered.length || entries.length)} / ${h(entries.length)} shot(s)${meta.render_granularity ? ` · ${h(meta.render_granularity)}` : ""}</span>
      <div class="shot-render-list">
        ${entries
          .slice(0, 6)
          .map((entry) => renderShotRenderRow(entry, scene, false))
          .join("")}
      </div>
    </div>
  `;
}

function renderShotRenderDetailWithActions(scene) {
  const entries = sceneShotRenderEntries(scene);
  const meta = sceneGenerationMeta(scene);
  if (!entries.length || meta.render_granularity !== "shot") return renderShotRenderDetail(scene);
  const rendered = entries.filter((entry) => entry.status !== "planned");
  return `
    <div class="shot-render-detail ${rendered.length ? "" : "is-planned"}">
      <strong>Shot render status</strong>
      <span>${h(rendered.length || entries.length)} / ${h(entries.length)} shot(s) · ${h(meta.render_granularity)}</span>
      <div class="shot-render-list">
        ${entries
          .slice(0, 6)
          .map((entry) => renderShotRenderRow(entry, scene, true))
          .join("")}
      </div>
    </div>
  `;
}

function renderShotRenderRow(entry, scene, includeActions = false) {
  const provider = entry.provider_label || entry.provider_id || entry.backend || "";
  const details = [
    provider,
    entry.attempts ? `${entry.attempts} attempt(s)` : "",
    entry.duration_seconds ? formatSeconds(entry.duration_seconds) : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const meta = sceneGenerationMeta(scene);
  const canRerender = includeActions && entry.shot_id && meta.render_granularity === "shot";
  return `
    <div class="shot-render-row ${shotRenderStatusClass(entry.status)}">
      <span>${h(`#${entry.index} ${entry.shot_id || "shot"}`)}</span>
      <small>${h(shotRenderStatusLabel(entry.status))}${details ? ` · ${h(details)}` : ""}</small>
      ${entry.error ? `<small class="danger-text">${h(entry.error)}</small>` : ""}
      ${canRerender ? `<button class="ghost-button small shot-rerender-button" type="button" data-action="rerender-shot-video" data-scene-order="${h(scene.order)}" data-shot-id="${h(entry.shot_id)}">Rerender shot</button>` : ""}
    </div>
  `;
}

// Compact governance badge (status + block flag).
function renderGovernanceBadge(scene) {
  const status = governanceStatus(scene);
  const governance = sceneGovernance(scene);
  const policy =
    governance.policy && typeof governance.policy === "object" ? governance.policy : {};
  const blocked = policy.mode === "block" && governance.deliverable === false;
  return `<div class="governance-badge ${governanceStatusClass(status)}${blocked ? " is-blocked" : ""}">${h(governanceStatusLabel(status))}${blocked ? " · blocked" : ""}</div>`;
}

// Detailed governance panel (5 dimensions + policy mode).
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

// First non-empty prototype entry; prefers locked over freeform.
function firstPrototypeEntry(scene) {
  const entries = scenePrototypeEntries(scene);
  return (
    entries.find((entry) => entry.mode === "prototype_lock" && entry.id) ||
    entries.find((entry) => entry.mode === "freeform") ||
    null
  );
}

// Compact prototype badge showing locked id or freeform gap.
function renderPrototypeBadge(scene) {
  const entry = firstPrototypeEntry(scene);
  if (!entry) return `<span class="prototype-badge is-unknown">Prototype unknown</span>`;
  if (entry.mode === "freeform") {
    return `<span class="prototype-badge is-freeform">Freeform${entry.gap.reason ? ` / ${h(entry.gap.reason)}` : ""}</span>`;
  }
  return `<span class="prototype-badge is-locked">${h(entry.id)}</span>`;
}

// Detailed prototype panel (lock/free counts + first 4 shots).
function renderPrototypeDetail(scene) {
  const entries = scenePrototypeEntries(scene);
  if (!entries.length) {
    return `<div class="prototype-detail is-unknown"><strong>Director prototypes</strong><span>No shot prototype data</span></div>`;
  }
  const locked = entries.filter((entry) => entry.mode === "prototype_lock" && entry.id).length;
  const freeform = entries.filter((entry) => entry.mode === "freeform").length;
  return `
    <div class="prototype-detail">
      <strong>Director prototypes</strong>
      <span>${h(locked)} lock / ${h(freeform)} freeform / ${h(entries.length)} shot(s)</span>
      <div class="prototype-shot-list">
        ${entries
          .slice(0, 4)
          .map((entry) => renderPrototypeShotRow(entry))
          .join("")}
      </div>
    </div>
  `;
}

// One shot row in the prototype detail (label + constraint summary).
function renderPrototypeShotRow(entry) {
  const hard = entry.constraints.hard || [];
  const soft = entry.constraints.soft || [];
  const guidelines = entry.constraints.guidelines || [];
  const label = entry.mode === "prototype_lock" ? entry.id || "prototype" : "freeform";
  return `
    <div class="prototype-shot ${entry.mode === "freeform" ? "is-freeform" : "is-locked"}">
      <span>${h(entry.label)} / ${h(label)}</span>
      ${hard.length ? `<small>hard: ${h(hard.slice(0, 3).join(", "))}</small>` : ""}
      ${soft.length ? `<small>soft: ${h(soft.slice(0, 3).join(", "))}</small>` : ""}
      ${guidelines.length ? `<small>guide: ${h(guidelines.slice(0, 2).join(", "))}</small>` : ""}
      ${entry.mode === "freeform" && entry.gap.reason ? `<small>gap: ${h(entry.gap.reason)}</small>` : ""}
    </div>
  `;
}

// Per-scene review unit card with all three badges + rerender actions.
// The compact renderStoryboardReviewCard (line 393) delegates here.
function renderReviewUnit(scene, project) {
  const assets = scene.assets || {};
  const active = Number(scene.order) === Number(state.selectedSceneOrder) ? "is-active" : "";
  const meta = sceneReviewMeta(scene);
  const sClass = reviewStatusClass(meta.status);
  const gaps = sceneAssetGaps(scene);
  const governance = sceneGovernance(scene);
  const blocked = governance?.policy?.mode === "block" && governance.deliverable === false;
  const media = assets.image_url
    ? `<img src="${h(assets.image_url)}" alt="">`
    : assets.video_url
      ? `<video src="${h(assets.video_url)}" muted playsinline preload="metadata"></video>`
      : `<span>暂无画面</span>`;
  return `
    <article class="review-unit ${active}" data-scene-order="${h(scene.order)}">
      <button class="review-unit-main" type="button" data-action="select-scene" data-scene-order="${h(scene.order)}">
        <div class="storyboard-thumb">${media}</div>
        <div class="review-unit-body">
          <div class="review-unit-head">
            <strong>#${h(scene.order)} ${h(scene.title || "分镜")}</strong>
            <span>${formatSeconds(scene.duration_seconds)} 路 ${h(scene.emotion_tone || scene.emotion || "")}</span>
          </div>
          <div class="review-unit-badges">
            ${renderGenerationBadge(scene)}
            ${renderShotRenderSummary(scene)}
            ${renderGovernanceBadge(scene)}
            ${renderPrototypeBadge(scene)}
            <span class="review-badge ${sClass}">${h(reviewStatusLabel(meta.status))}${meta.rating ? ` 路 ${h(meta.rating)}/5` : ""}</span>
            <span class="asset-readiness ${gaps.length ? "is-warn" : "is-ready"}">${gaps.length ? `Missing ${h(gaps.join(" / "))}` : "Assets ready"}</span>
            ${blocked ? `<span class="asset-readiness is-blocked">Export blocked</span>` : ""}
          </div>
          <div class="review-unit-summary">${nl(scene.dialogue || "暂无台词")}</div>
          <div class="review-unit-details">
            ${renderGenerationDetail(scene)}
            ${renderShotRenderDetail(scene)}
            ${renderGovernanceDetail(scene)}
            ${renderPrototypeDetail(scene)}
          </div>
        </div>
      </button>
      <div class="review-unit-actions">
        <span class="section-label">Rerender</span>
        <button class="ghost-button small" type="button" data-action="rerender-image" data-scene-order="${h(scene.order)}">Image</button>
        <button class="ghost-button small" type="button" data-action="rerender-audio" data-scene-order="${h(scene.order)}">Audio</button>
        <button class="ghost-button small" type="button" data-action="rerender-video" data-scene-order="${h(scene.order)}">Video</button>
        <button class="ghost-button small" type="button" data-action="rebuild-scene" data-scene-order="${h(scene.order)}">Full</button>
      </div>
    </article>
  `;
}

// Compact per-scene card for the review list — delegates to renderReviewUnit.
function renderStoryboardReviewCard(scene) {
  return renderReviewUnit(scene, state.project);
}

// Bottom detail pane: media preview + review form + version compare.
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
        ${renderShotRenderDetailWithActions(scene)}
        ${renderGovernanceDetail(scene)}
        ${renderPrototypeDetail(scene)}
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

// Side-by-side compare panel (version numbers + asset links + recent history).
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
      ${
        history.length
          ? `
        <div class="review-history">
          ${history
            .map(
              (item) => `
            <div>
              <strong>${h(item.label || item.action || "记录")}</strong>
              <span>${h(item.status || "")} · ${h(item.ts || "")}</span>
            </div>
          `
            )
            .join("")}
        </div>
      `
          : `<div class="muted">暂无历史版本记录。</div>`
      }
    </div>
  `;
}

// Compact asset gap summary used in the workbench header.
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

// Asset queue list (used in the workbench view).
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
