// ─── Timeline & Temporal Preview ─────────────────────────────────────────────

import {
  state,
  temporalPreviewTimeline,
  temporalPreviewFallbackTimer,
  gsapLoadPromise,
  setTemporalPreviewTimeline,
  setTemporalPreviewFallbackTimer,
  setGsapLoadPromise,
} from "./state.js";
import {
  asNumber,
  clamp,
  selectedScene,
  sceneTemporalShots,
} from "./utils.js";

export function ensureGsapLoaded() {
  if (window.gsap) {
    return Promise.resolve(window.gsap);
  }
  if (gsapLoadPromise) {
    return gsapLoadPromise;
  }
  const promise = new Promise((resolve) => {
    const script = document.createElement("script");
    script.src = "https://cdn.jsdelivr.net/npm/gsap@3.13.0/dist/gsap.min.js";
    script.async = true;
    script.onload = () => resolve(window.gsap || null);
    script.onerror = () => resolve(null);
    document.head.appendChild(script);
  });
  setGsapLoadPromise(promise);
  return promise;
}

export function temporalPreviewState(shot, index = 0) {
  const zoom = Math.max(1, asNumber(shot?.zoom, 1.04));
  const centerX = clamp(shot?.center_x ?? 0.5, 0, 1);
  const centerY = clamp(shot?.center_y ?? 0.5, 0, 1);
  const movement = String(shot?.camera_movement || "").toLowerCase();
  const panBias = movement.includes("left") ? -24 : movement.includes("right") ? 24 : 0;
  const tiltBias = movement.includes("up") ? -20 : movement.includes("down") ? 20 : 0;
  return {
    scale: zoom,
    x: (0.5 - centerX) * 130 + panBias,
    y: (0.5 - centerY) * 100 + tiltBias,
    actorX: (centerX - 0.5) * 72 + (index % 2 ? 10 : -8),
    actorY: (centerY - 0.5) * 48,
  };
}

export function updateTemporalPreviewUi(progress, activeIndex) {
  const progressEl = document.getElementById("temporalPreviewProgress");
  if (progressEl) {
    progressEl.style.width = `${Math.max(0, Math.min(100, progress * 100))}%`;
  }
  document.querySelectorAll("[data-temporal-shot]").forEach((node) => {
    node.classList.toggle("is-active", Number(node.dataset.temporalShot) === Number(activeIndex));
  });
}

export function activeTemporalShotIndex(shots, elapsed) {
  let cursor = 0;
  for (let index = 0; index < shots.length; index += 1) {
    cursor += Math.max(0.25, asNumber(shots[index]?.duration_seconds, 0.25)) * 0.55;
    if (elapsed <= cursor) return index;
  }
  return Math.max(0, shots.length - 1);
}

export function stopTemporalPreview() {
  if (temporalPreviewTimeline?.kill) {
    temporalPreviewTimeline.kill();
  }
  setTemporalPreviewTimeline(null);
  if (temporalPreviewFallbackTimer) {
    window.clearInterval(temporalPreviewFallbackTimer);
    setTemporalPreviewFallbackTimer(null);
  }
}

export function resetTemporalPreview() {
  stopTemporalPreview();
  const world = document.getElementById("temporalPreviewWorld");
  const actor = document.getElementById("temporalPreviewActor");
  if (window.gsap && world && actor) {
    window.gsap.set(world, { x: 0, y: 0, scale: 1, transformOrigin: "50% 50%" });
    window.gsap.set(actor, { x: 0, y: 0 });
  } else {
    if (world) world.style.transform = "translate3d(0,0,0) scale(1)";
    if (actor) actor.style.transform = "translate3d(0,0,0)";
  }
  updateTemporalPreviewUi(0, -1);
}

export function pauseTemporalPreview() {
  if (temporalPreviewTimeline?.pause) {
    temporalPreviewTimeline.pause();
  }
  if (temporalPreviewFallbackTimer) {
    window.clearInterval(temporalPreviewFallbackTimer);
    setTemporalPreviewFallbackTimer(null);
  }
}

export async function playTemporalPreview() {
  const scene = selectedScene();
  const shots = sceneTemporalShots(scene);
  const world = document.getElementById("temporalPreviewWorld");
  const actor = document.getElementById("temporalPreviewActor");
  if (!scene || !shots.length || !world || !actor) return;
  resetTemporalPreview();
  const durations = shots.map((shot) => Math.max(0.25, asNumber(shot.duration_seconds, 0.25)) * 0.55);
  const total = durations.reduce((sum, duration) => sum + duration, 0) || 1;
  const gsap = await ensureGsapLoaded();
  if (gsap) {
    let cursor = 0;
    const tl = gsap.timeline({
      paused: true,
      onUpdate: () => {
        updateTemporalPreviewUi(tl.progress(), activeTemporalShotIndex(shots, tl.time()));
      },
      onComplete: () => updateTemporalPreviewUi(1, shots.length - 1),
    });
    setTemporalPreviewTimeline(tl);
    shots.forEach((shot, index) => {
      const st = temporalPreviewState(shot, index);
      const ease = String(shot.camera_movement || "").includes("dramatic") ? "power3.out" : "sine.inOut";
      tl.to(world, { x: st.x, y: st.y, scale: st.scale, duration: durations[index], ease }, cursor);
      tl.to(actor, { x: st.actorX, y: st.actorY, duration: durations[index], ease: "sine.inOut" }, cursor);
      cursor += durations[index];
    });
    tl.play(0);
    return;
  }
  const started = performance.now();
  const timer = window.setInterval(() => {
    const elapsed = Math.min(total, (performance.now() - started) / 1000);
    const active = activeTemporalShotIndex(shots, elapsed);
    const st = temporalPreviewState(shots[active], active);
    world.style.transform = `translate3d(${st.x}px, ${st.y}px, 0) scale(${st.scale})`;
    actor.style.transform = `translate3d(${st.actorX}px, ${st.actorY}px, 0)`;
    updateTemporalPreviewUi(elapsed / total, active);
    if (elapsed >= total) pauseTemporalPreview();
  }, 33);
  setTemporalPreviewFallbackTimer(timer);
}
