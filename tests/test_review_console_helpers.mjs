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

const { deriveReviewOverview, applyReviewTriage } = await import("../frontend/utils.js");

const project = {
  scenes: [
    {
      order: 1,
      title: "Real pass",
      review_meta: { status: "approved", rating: 4.5 },
      generation_meta: { is_real_video: true, provider_id: "xl" },
      governance: { status: "pass", deliverable: true, policy: { mode: "report" } },
      assets: { image_url: "/a.png", audio_url: "/a.mp3", video_url: "/a.mp4" },
    },
    {
      order: 2,
      title: "Fallback warn",
      dialogue: "Needs an audio track",
      review_meta: { status: "needs_work", rating: 2 },
      generation_meta: { fallback_used: true, provider_id: "xl" },
      governance: { status: "warn", deliverable: true, policy: { mode: "report" } },
      assets: { image_url: "/b.png", video_url: "/b.mp4" },
    },
    {
      order: 3,
      title: "Blocked fail",
      review_meta: { status: "blocked", rating: 1 },
      generation_meta: { is_real_video: false, provider_id: "local" },
      governance: { status: "fail", deliverable: false, policy: { mode: "block" } },
      assets: { image_url: "/c.png", audio_url: "/c.mp3", video_url: "/c.mp4" },
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

assert.deepEqual(applyReviewTriage(project.scenes, { review_status: "approved" }).map((scene) => scene.order), [1]);
assert.deepEqual(applyReviewTriage(project.scenes, { governance_status: "warn" }).map((scene) => scene.order), [2]);
assert.deepEqual(applyReviewTriage(project.scenes, { provenance: "fallback" }).map((scene) => scene.order), [2]);
assert.deepEqual(applyReviewTriage(project.scenes, { deliverable: "blocked" }).map((scene) => scene.order), [3]);
assert.deepEqual(applyReviewTriage(project.scenes, { deliverable: "asset_gaps" }).map((scene) => scene.order), [2, 4]);
assert.deepEqual(applyReviewTriage(project.scenes, { min_rating: 4 }).map((scene) => scene.order), [1]);
assert.deepEqual(applyReviewTriage(project.scenes, { review_status: "approved", governance_status: "fail" }), []);
assert.deepEqual(applyReviewTriage(project.scenes, { sort: "rating_desc" }).map((scene) => scene.order), [1, 2, 3, 4]);
assert.deepEqual(applyReviewTriage(project.scenes, { sort: "governance_severity" }).map((scene) => scene.order), [3, 2, 4, 1]);
assert.deepEqual(applyReviewTriage(project.scenes, { sort: "fallback_first" }).map((scene) => scene.order), [2, 1, 3, 4]);

const legacyOverview = deriveReviewOverview({ scenes: [{ order: 1 }] });
assert.equal(legacyOverview.continuity.not_evaluated, 1);
assert.equal(legacyOverview.provenance.unknown, 1);

console.log("review console helper tests passed");
