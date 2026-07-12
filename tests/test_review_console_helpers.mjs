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

const {
  deriveReviewOverview,
  derivePrototypeOverview,
  scenePrototypeEntries,
  sceneShotRenderEntries,
  shotRenderStatusLabel,
  applyReviewTriage,
} = await import("../frontend/utils.js");

const project = {
  scenes: [
    {
      order: 1,
      title: "Real pass",
      review_meta: { status: "approved", rating: 4.5 },
      generation_meta: {
        is_real_video: true,
        provider_id: "xl",
        render_granularity: "shot",
        shot_outputs: [
          {
            shot_id: "scene_001_shot_01",
            index: 1,
            status: "real_video",
            provider_id: "xl",
            backend: "remote",
            attempts: 1,
            duration_seconds: 2,
          },
        ],
      },
      governance: { status: "pass", deliverable: true, policy: { mode: "report" } },
      assets: { image_url: "/a.png", audio_url: "/a.mp3", video_url: "/a.mp4" },
      shot_plan: {
        shots: [
          {
            shot_order: 1,
            label: "SHOT 1",
            visual_prototype: {
              mode: "prototype_lock",
              id: "dialogue_pressure_two_shot",
              constraints: {
                hard: ["preserve_eyelines"],
                soft: ["background_subordinate"],
                guidelines: ["separate_speakers"],
              },
            },
          },
        ],
      },
    },
    {
      order: 2,
      title: "Fallback warn",
      dialogue: "Needs an audio track",
      review_meta: { status: "needs_work", rating: 2 },
      generation_meta: { fallback_used: true, provider_id: "xl" },
      governance: { status: "warn", deliverable: true, policy: { mode: "report" } },
      assets: { image_url: "/b.png", video_url: "/b.mp4" },
      shot_plan: {
        shots: [
          {
            shot_order: 1,
            label: "SHOT 1",
            visual_prototype: {
              mode: "freeform",
              id: "",
              constraints: { hard: [], soft: [], guidelines: [] },
              gap: { reason: "no prototype trigger matched calm low-risk scene" },
            },
          },
        ],
      },
    },
    {
      order: 3,
      title: "Blocked fail",
      review_meta: { status: "blocked", rating: 1 },
      generation_meta: { is_real_video: false, provider_id: "local" },
      governance: { status: "fail", deliverable: false, policy: { mode: "block" } },
      assets: { image_url: "/c.png", audio_url: "/c.mp3", video_url: "/c.mp4" },
      shot_plan: {
        shots: [
          {
            shot_order: 1,
            label: "SHOT 1",
            visual_prototype: {
              mode: "prototype_lock",
              id: "reaction_hold_closeup",
              constraints: { hard: ["hold_performance_detail"], soft: [], guidelines: [] },
            },
          },
        ],
      },
    },
    {
      order: 4,
      title: "Legacy unknown",
      assets: {},
    },
  ],
  continuity_ledger: {
    status_counts: { pass: 1, warn: 1, fail: 1, not_evaluated: 1 },
    blocked_scene_count: 1,
  },
};

const overview = deriveReviewOverview(project);
assert.equal(overview.total_scenes, 4);
assert.deepEqual(overview.provenance, { real: 1, fallback: 1, local: 1, unknown: 1 });
assert.equal(overview.review.approved, 1);
assert.equal(overview.review.needs_work, 1);
assert.equal(overview.review.blocked, 1);
assert.equal(overview.review.unreviewed, 1);
assert.equal(overview.readiness.blocked, 1);
assert.equal(overview.readiness.asset_gaps, 2);
assert.equal(overview.continuity.not_evaluated, 1);
assert.equal(overview.prototype.total_shots, 3);
assert.equal(overview.prototype.prototype_lock, 2);
assert.equal(overview.prototype.freeform, 1);
assert.equal(overview.prototype.ids.dialogue_pressure_two_shot, 1);
assert.equal(overview.prototype.gaps["no prototype trigger matched calm low-risk scene"], 1);

const prototypeEntries = scenePrototypeEntries(project.scenes[0]);
assert.equal(prototypeEntries.length, 1);
assert.equal(prototypeEntries[0].id, "dialogue_pressure_two_shot");
assert.deepEqual(prototypeEntries[0].constraints.hard, ["preserve_eyelines"]);

const prototypeOverview = derivePrototypeOverview(project.scenes);
assert.equal(prototypeOverview.prototype_lock, 2);
assert.equal(prototypeOverview.freeform, 1);

const shotEntries = sceneShotRenderEntries(project.scenes[0]);
assert.equal(shotEntries.length, 1);
assert.equal(shotEntries[0].status, "real_video");
assert.equal(shotEntries[0].provider_id, "xl");
assert.equal(shotRenderStatusLabel("fallback"), "Fallback");

const timelineShotEntries = sceneShotRenderEntries({
  shot_timeline: [
    {
      shot_id: "timeline_shot_01",
      duration_seconds: 1.5,
      generation: { status: "fallback", provider_id: "xl", backend: "local", attempts: 2 },
    },
  ],
});
assert.equal(timelineShotEntries[0].status, "fallback");
assert.equal(timelineShotEntries[0].duration_seconds, 1.5);

const plannedEntries = sceneShotRenderEntries({ shot_plan: { shots: [{ shot_id: "planned_01", duration_seconds: 1 }] } });
assert.equal(plannedEntries[0].status, "planned");

assert.deepEqual(applyReviewTriage(project.scenes, { review_status: "approved" }).map((scene) => scene.order), [1]);
assert.deepEqual(applyReviewTriage(project.scenes, { governance_status: "warn" }).map((scene) => scene.order), [2]);
assert.deepEqual(applyReviewTriage(project.scenes, { provenance: "fallback" }).map((scene) => scene.order), [2]);
assert.deepEqual(applyReviewTriage(project.scenes, { deliverable: "blocked" }).map((scene) => scene.order), [3]);
assert.deepEqual(applyReviewTriage(project.scenes, { deliverable: "asset_gaps" }).map((scene) => scene.order), [2, 4]);
assert.deepEqual(applyReviewTriage(project.scenes, { prototype_mode: "prototype_lock" }).map((scene) => scene.order), [1, 3]);
assert.deepEqual(applyReviewTriage(project.scenes, { prototype_mode: "freeform" }).map((scene) => scene.order), [2]);
assert.deepEqual(applyReviewTriage(project.scenes, { prototype_mode: "unknown" }).map((scene) => scene.order), [4]);
assert.deepEqual(applyReviewTriage(project.scenes, { prototype_gap: "gap_only" }).map((scene) => scene.order), [2]);
assert.deepEqual(applyReviewTriage(project.scenes, { prototype_gap: "no_gap" }).map((scene) => scene.order), [1, 3, 4]);
assert.deepEqual(applyReviewTriage(project.scenes, { prototype_mode: "freeform", prototype_gap: "gap_only" }).map((scene) => scene.order), [2]);
assert.deepEqual(applyReviewTriage(project.scenes, { min_rating: 4 }).map((scene) => scene.order), [1]);
assert.deepEqual(applyReviewTriage(project.scenes, { review_status: "approved", governance_status: "fail" }), []);
assert.deepEqual(applyReviewTriage(project.scenes, { sort: "rating_desc" }).map((scene) => scene.order), [1, 2, 3, 4]);
assert.deepEqual(applyReviewTriage(project.scenes, { sort: "governance_severity" }).map((scene) => scene.order), [3, 2, 4, 1]);
assert.deepEqual(applyReviewTriage(project.scenes, { sort: "fallback_first" }).map((scene) => scene.order), [2, 1, 3, 4]);

const legacyOverview = deriveReviewOverview({ scenes: [{ order: 1 }] });
assert.equal(legacyOverview.continuity.not_evaluated, 1);
assert.equal(legacyOverview.provenance.unknown, 1);

console.log("review console helper tests passed");
