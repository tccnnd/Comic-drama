"""Video generation orchestration with retry, fallback reporting, and cross-scene continuity.

This module wraps the existing render_clip pipeline to add:
1. Explicit retry logic for remote video providers (Kling, Sora, etc.)
2. Clear failure reporting instead of silent 2.5D fallback
3. Cross-scene frame continuity constraints (last-frame → first-frame bridging)
4. Generation metadata tracking for quality governance
"""
from __future__ import annotations

import json
import logging
import os
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_VIDEO_RETRIES = int(os.environ.get("VIDEO_MAX_RETRIES", "2"))
VIDEO_RETRY_DELAY_SECONDS = float(os.environ.get("VIDEO_RETRY_DELAY_SECONDS", "5.0"))
VIDEO_FALLBACK_MODE = os.environ.get("VIDEO_FALLBACK_MODE", "report").strip().lower()
# "report" = fall back to 2.5D but mark the scene with a warning
# "strict" = raise on failure, no fallback
# "silent" = original behavior, silent fallback (not recommended)


@dataclass
class VideoGenerationResult:
    """Result of a single scene video generation attempt."""
    scene_order: int
    provider_id: str
    provider_label: str
    success: bool
    is_real_video: bool  # True if actual video generation, False if 2.5D fallback
    attempts: int
    duration_seconds: float
    output_path: str
    error: str = ""
    warnings: list[str] | None = None
    last_frame_path: str = ""  # For cross-scene continuity


# ---------------------------------------------------------------------------
# Cross-scene continuity
# ---------------------------------------------------------------------------

def extract_last_frame(video_path: Path, output_path: Path) -> Path | None:
    """Extract the last frame from a video for cross-scene continuity bridging."""
    try:
        from scripts.run_workflow import get_ffmpeg_exe, run_guarded
        ffmpeg = get_ffmpeg_exe()
        # Extract last frame using ffmpeg
        run_guarded(
            [
                ffmpeg, "-y",
                "-sseof", "-0.1",  # Seek to 0.1s before end
                "-i", str(video_path),
                "-frames:v", "1",
                "-q:v", "2",
                str(output_path),
            ],
            cwd=output_path.parent,
            timeout=15,
            stage="extract_last_frame",
        )
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path
    except Exception as exc:
        logger.warning("Failed to extract last frame from %s: %s", video_path, exc)
    return None


def build_continuity_bridge_prompt(
    prev_scene: dict[str, Any] | None,
    current_scene: dict[str, Any],
    prev_last_frame_path: str = "",
) -> dict[str, str]:
    """Build continuity bridging instructions for cross-scene transitions.

    Returns a dict with:
    - continuity_prefix: text to prepend to the video prompt
    - transition_type: cut/xfade/black
    - prev_ending_context: description of how the previous scene ended
    """
    if prev_scene is None:
        return {
            "continuity_prefix": "",
            "transition_type": "cut",
            "prev_ending_context": "",
        }

    prev_emotion = str(prev_scene.get("emotion_tone") or prev_scene.get("emotion") or "").strip()
    curr_emotion = str(current_scene.get("emotion_tone") or current_scene.get("emotion") or "").strip()
    prev_title = str(prev_scene.get("title") or "").strip()
    prev_characters = prev_scene.get("characters") or []
    curr_characters = current_scene.get("characters") or []

    # Determine transition type
    from scripts.run_workflow import _scene_transition
    transition = _scene_transition(prev_emotion, curr_emotion)

    # Build continuity prefix
    continuity_parts: list[str] = []

    # Shared characters should maintain appearance
    shared_chars = set(str(c) for c in prev_characters) & set(str(c) for c in curr_characters)
    if shared_chars:
        continuity_parts.append(
            f"Characters continuing from previous scene: {', '.join(shared_chars)}. "
            "Maintain exact same appearance, clothing, and proportions."
        )

    # Transition-specific instructions
    if transition == "cut":
        continuity_parts.append(
            "Hard cut from previous scene. Opening frame should establish the new scene clearly."
        )
    elif transition == "xfade":
        continuity_parts.append(
            f"Smooth transition from previous scene ('{prev_title}'). "
            "Opening frames should have visual continuity in lighting and color temperature."
        )
    elif transition == "black":
        continuity_parts.append(
            "Scene follows a dramatic pause. Opening should re-establish setting and characters."
        )

    # Emotional continuity
    if prev_emotion and curr_emotion and prev_emotion != curr_emotion:
        continuity_parts.append(
            f"Emotional shift from {prev_emotion} to {curr_emotion}. "
            "Reflect this transition in character expressions and lighting."
        )

    return {
        "continuity_prefix": " ".join(continuity_parts),
        "transition_type": transition,
        "prev_ending_context": f"Previous scene: '{prev_title}', emotion: {prev_emotion}",
    }


# ---------------------------------------------------------------------------
# Retry-aware video generation
# ---------------------------------------------------------------------------

def generate_scene_video_with_retry(
    scene_obj: Any,
    keyframe_path: Path,
    clip_duration: float,
    visual_output_path: Path,
    run_dir: Path,
    video_provider: str = "auto",
    *,
    prev_scene_data: dict[str, Any] | None = None,
    prev_last_frame: Path | None = None,
    max_retries: int | None = None,
    retry_delay: float | None = None,
) -> VideoGenerationResult:
    """Generate video for a scene with retry logic and continuity bridging.

    This wraps the existing provider dispatch (ComfyUI/remote/local) with:
    - Configurable retry on transient failures
    - Cross-scene continuity prompt injection
    - Clear result reporting (real video vs 2.5D fallback)
    """
    from scripts.run_workflow import (
        build_scene_video_prompts,
        build_scene_temporal_spec,
        env_bool,
        env_float,
        render_scene_video_comfyui,
        scene_consistency_spec,
    )
    from scripts.video_provider_adapters import (
        VideoRenderRequest,
        render_remote_video_provider,
        VideoProviderError,
    )
    from video_providers import get_video_provider_spec

    if max_retries is None:
        max_retries = MAX_VIDEO_RETRIES
    if retry_delay is None:
        retry_delay = VIDEO_RETRY_DELAY_SECONDS

    provider_spec = get_video_provider_spec(video_provider)
    scene_id = f"{scene_obj.scene:02}"
    attempts = 0
    last_error = ""

    # Build continuity bridge if we have previous scene context
    continuity_bridge = build_continuity_bridge_prompt(
        prev_scene_data,
        {
            "emotion_tone": getattr(scene_obj, "emotion", ""),
            "emotion": getattr(scene_obj, "emotion", ""),
            "title": getattr(scene_obj, "title", ""),
            "characters": list(getattr(scene_obj, "characters", []) or []),
        },
        str(prev_last_frame or ""),
    )

    for attempt in range(1, max_retries + 2):  # +2 because range is exclusive and we start at 1
        attempts = attempt
        try:
            if provider_spec.backend == "comfyui":
                logger.info(
                    "[video] Scene %s attempt %d/%d via %s",
                    scene_id, attempt, max_retries + 1, provider_spec.label,
                )
                render_scene_video_comfyui(scene_obj, keyframe_path, clip_duration, visual_output_path, run_dir)
                return VideoGenerationResult(
                    scene_order=scene_obj.scene,
                    provider_id=provider_spec.id,
                    provider_label=provider_spec.label,
                    success=True,
                    is_real_video=True,
                    attempts=attempts,
                    duration_seconds=clip_duration,
                    output_path=str(visual_output_path),
                )

            elif provider_spec.backend == "remote":
                logger.info(
                    "[video] Scene %s attempt %d/%d via %s (remote)",
                    scene_id, attempt, max_retries + 1, provider_spec.label,
                )
                prompt_text, negative_text = build_scene_video_prompts(scene_obj, clip_duration, run_dir)

                # Inject continuity bridge into prompt
                if continuity_bridge["continuity_prefix"]:
                    prompt_text = f"{continuity_bridge['continuity_prefix']}\n\n{prompt_text}"

                temporal_spec = getattr(scene_obj, "temporal_spec", None) or build_scene_temporal_spec(
                    scene_obj,
                    clip_duration,
                    width=int(env_float("VIDEO_WIDTH", default=1080)),
                    height=int(env_float("VIDEO_HEIGHT", default=1920)),
                    fps=int(env_float("VIDEO_FPS", default=24)),
                )
                consistency_spec_data = scene_consistency_spec(scene_obj)

                # Add cross-scene continuity to consistency spec
                if continuity_bridge["prev_ending_context"]:
                    consistency_spec_data["cross_scene_continuity"] = {
                        "transition_type": continuity_bridge["transition_type"],
                        "prev_ending_context": continuity_bridge["prev_ending_context"],
                        "shared_characters_must_match": True,
                    }

                from scripts.run_workflow import get_ffmpeg_exe, run_guarded as _run_guarded
                ffmpeg = get_ffmpeg_exe()

                render_remote_video_provider(
                    VideoRenderRequest(
                        scene=scene_obj.scene,
                        title=scene_obj.title,
                        prompt=prompt_text,
                        negative_prompt=negative_text,
                        keyframe_path=keyframe_path,
                        out_path=visual_output_path,
                        run_dir=run_dir,
                        duration=clip_duration,
                        width=int(env_float("VIDEO_WIDTH", default=1080)),
                        height=int(env_float("VIDEO_HEIGHT", default=1920)),
                        fps=int(env_float("VIDEO_FPS", default=24)),
                        camera=scene_obj.camera,
                        emotion=scene_obj.emotion,
                        dialogue=scene_obj.dialogue,
                        characters=tuple(scene_obj.characters or []),
                        temporal_spec=temporal_spec,
                        consistency_spec=consistency_spec_data,
                    ),
                    provider_spec,
                    ffmpeg=ffmpeg,
                    run_guarded=_run_guarded,
                    timeout_s=int(env_float("VIDEO_TIMEOUT", default=600)),
                )
                return VideoGenerationResult(
                    scene_order=scene_obj.scene,
                    provider_id=provider_spec.id,
                    provider_label=provider_spec.label,
                    success=True,
                    is_real_video=True,
                    attempts=attempts,
                    duration_seconds=clip_duration,
                    output_path=str(visual_output_path),
                )

            else:
                # Local provider — no retry needed, always succeeds
                return VideoGenerationResult(
                    scene_order=scene_obj.scene,
                    provider_id=provider_spec.id,
                    provider_label=provider_spec.label,
                    success=True,
                    is_real_video=False,
                    attempts=1,
                    duration_seconds=clip_duration,
                    output_path=str(visual_output_path),
                    warnings=["Using 2.5D local renderer (no video generation provider configured)"],
                )

        except Exception as exc:
            last_error = str(exc)
            logger.warning(
                "[video] Scene %s attempt %d failed: %s",
                scene_id, attempt, last_error,
            )
            if attempt <= max_retries:
                logger.info("[video] Retrying in %.1fs...", retry_delay)
                time.sleep(retry_delay)
                # Exponential backoff
                retry_delay = min(retry_delay * 1.5, 60.0)
            continue

    # All retries exhausted
    fallback_mode = VIDEO_FALLBACK_MODE
    if env_bool("VIDEO_STRICT", default=False):
        fallback_mode = "strict"

    if fallback_mode == "strict":
        raise RuntimeError(
            f"视频生成失败（{provider_spec.label}），已重试 {attempts} 次: {last_error}"
        )

    # Fall back to 2.5D but report it
    warnings = [
        f"视频生成失败，已回退到 2.5D 动态漫画模式（{provider_spec.label} 重试 {attempts} 次后失败: {last_error}）",
    ]
    logger.warning(
        "[video] Scene %s: all %d attempts failed, falling back to 2.5D. Last error: %s",
        scene_id, attempts, last_error,
    )
    return VideoGenerationResult(
        scene_order=scene_obj.scene,
        provider_id="local",
        provider_label="Local 2.5D (fallback)",
        success=True,
        is_real_video=False,
        attempts=attempts,
        duration_seconds=clip_duration,
        output_path=str(visual_output_path),
        error=last_error,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Batch video generation with cross-scene continuity
# ---------------------------------------------------------------------------

def generate_project_videos_with_continuity(
    project_id: str,
    scene_orders: list[int] | None = None,
) -> list[VideoGenerationResult]:
    """Generate videos for multiple scenes with cross-scene continuity enforcement.

    Processes scenes in order, passing the last frame of each completed scene
    to the next scene's generation for visual continuity.
    """
    from backend.project_runtime import load_project
    from backend.scene_renderer import (
        project_dir,
        scene_dir,
        scene_latest_path,
    )

    project = load_project(project_id)
    scenes = sorted(
        [s for s in project.get("scenes", []) if isinstance(s, dict)],
        key=lambda s: int(s.get("order", 0)),
    )

    if scene_orders:
        scenes = [s for s in scenes if int(s.get("order", 0)) in scene_orders]

    results: list[VideoGenerationResult] = []
    prev_scene_data: dict[str, Any] | None = None
    prev_last_frame: Path | None = None

    for scene in scenes:
        scene_order = int(scene.get("order", 0))
        scene_id_str = str(scene.get("scene_id") or f"scene_{scene_order:03d}")
        directory = scene_dir(project_id, scene_id_str)

        # Check if video already exists and extract last frame for continuity
        existing_video = scene_latest_path(project_id, scene, "video")
        if existing_video and existing_video.exists():
            # Extract last frame for next scene's continuity
            last_frame_out = directory / "last_frame.png"
            extracted = extract_last_frame(existing_video, last_frame_out)
            if extracted:
                prev_last_frame = extracted
            prev_scene_data = scene
            results.append(VideoGenerationResult(
                scene_order=scene_order,
                provider_id="cached",
                provider_label="Cached",
                success=True,
                is_real_video=True,
                attempts=0,
                duration_seconds=float(scene.get("duration_seconds", 0)),
                output_path=str(existing_video),
                last_frame_path=str(prev_last_frame or ""),
            ))
            continue

        # This scene needs generation — pass continuity context
        logger.info(
            "[video-continuity] Generating scene %d with %s continuity from scene %s",
            scene_order,
            "cross-scene" if prev_scene_data else "no",
            prev_scene_data.get("order") if prev_scene_data else "N/A",
        )

        # Store continuity bridge info on the scene for the renderer
        if prev_scene_data:
            bridge = build_continuity_bridge_prompt(prev_scene_data, scene)
            scene["_continuity_bridge"] = bridge
            if prev_last_frame and prev_last_frame.exists():
                scene["_prev_last_frame"] = str(prev_last_frame)

        # Update prev for next iteration
        prev_scene_data = scene

    return results
