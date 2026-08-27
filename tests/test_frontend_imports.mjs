import assert from "node:assert/strict";

globalThis.document = {
  getElementById() {
    return null;
  },
};

globalThis.window = {
  localStorage: {
    getItem() {
      return null;
    },
    setItem() {},
  },
};

const renderModule = await import("../frontend/render.js");
const reviewCanvasModule = await import("../frontend/components/review/canvas.js");
const utilsModule = await import("../frontend/utils.js");
const stateModule = await import("../frontend/state.js");

assert.equal(typeof renderModule.renderShell, "function");
assert.equal(typeof reviewCanvasModule.renderStoryboardReviewCanvas, "function");
assert.equal(typeof utilsModule.governanceStatus, "function");
assert.equal(typeof utilsModule.projectContinuityLedger, "function");

const project = {
  settings: { video_provider: "doubao" },
  scenes: [
    {
      order: 1,
      scene_id: "scene_001",
      title: "Provider readiness scene",
      assets: {},
      generation_meta: {
        render_granularity: "shot",
        shot_outputs: [
          {
            shot_id: "scene_001_shot_01",
            index: 1,
            status: "real_video",
            provider_id: "doubao",
            backend: "remote",
            attempts: 1,
          },
        ],
      },
    },
  ],
};

stateModule.state.videoProviderStatusLoading = false;
stateModule.state.videoProviderStatusError = "";
stateModule.state.videoProviderStatus = {
  provider: { id: "doubao", label: "Doubao", backend: "remote" },
  readiness: {
    ready: false,
    summary: "Missing 3 required remote provider setting(s).",
    blocking_env: ["DOUBAO_API_KEY", "DOUBAO_MODEL", "DOUBAO_BASE_URL or DOUBAO_SUBMIT_URL"],
  },
};

const missingProviderHtml = reviewCanvasModule.renderStoryboardReviewCanvas(project);
assert.match(missingProviderHtml, /review-provider-banner is-warning/);
assert.match(missingProviderHtml, /Doubao is not ready/);
assert.match(missingProviderHtml, /DOUBAO_API_KEY/);
assert.match(missingProviderHtml, /Shot render status/);
assert.match(missingProviderHtml, /scene_001_shot_01/);
assert.match(missingProviderHtml, /Real/);
assert.match(missingProviderHtml, /data-action="rerender-shot-video"/);
assert.match(missingProviderHtml, /data-scene-order="1"/);
assert.match(missingProviderHtml, /data-shot-id="scene_001_shot_01"/);

const reviewUnitMain = missingProviderHtml.match(/<button class="review-unit-main"[\s\S]*?<\/button>/)?.[0] || "";
assert.doesNotMatch(reviewUnitMain, /rerender-shot-video/);

stateModule.state.videoProviderStatus = {
  provider: { id: "local", label: "Local 2.5D", backend: "local" },
  readiness: { ready: true, summary: "Local 2.5D provider is always available.", blocking_env: [] },
};

const localProviderHtml = reviewCanvasModule.renderStoryboardReviewCanvas({
  ...project,
  settings: { video_provider: "local" },
});
assert.doesNotMatch(localProviderHtml, /review-provider-banner/);

stateModule.state.project = project;
stateModule.state.activeTab = "settings";
stateModule.state.llmSettings = {
  settings: {
    api_key_masked: "••••••••test",
    api_key_set: true,
    base_url: "https://api.example.test/v1",
    model: "test-model",
    json_mode: true,
    task_overrides: {},
  },
  presets: [],
  task_definitions: [],
};

const settingsHtml = renderModule.renderShell();
assert.match(settingsHtml, /语言模型 API/);
assert.match(settingsHtml, /角色图生成 API/);
assert.match(settingsHtml, /taskOvApiKey_language_model/);
assert.match(settingsHtml, /taskOvApiKey_character_image/);

console.log("frontend import smoke tests passed");
