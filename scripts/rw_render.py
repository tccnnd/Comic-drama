from __future__ import annotations

import shutil
import time
from pathlib import Path

from PIL import Image

from scripts.rw_config import *  # noqa: F401,F403  - re-exports config constants
from scripts.rw_models import StoryScene
from scripts.rw_ffmpeg import render_timeout, concat_timeout, run_guarded
from scripts.rw_utils import write_text, media_duration, clamp
from scripts.rw_styles import normalize_subtitle_style, normalize_audio_style
from scripts.rw_audio import (
    mix_voice_with_bgm,
    scene_audio_style,
    mix_scene_sfx,
    scene_should_screen_shake,
    apply_scene_grade,
    burn_subtitles_to_video,
)
from scripts.rw_voice import split_dialogue_speaker
from scripts.rw_comfyui import generate_keyframe, render_scene_video_comfyui
from scripts.rw_planning import build_scene_beats, build_scene_temporal_spec
from scripts.rw_prompts import build_scene_video_prompts, scene_consistency_spec
from scripts.rw_image import apply_crop_box, compose_comic_frame
from scripts.video_provider_adapters import VideoRenderRequest, render_remote_video_provider
from video_providers import get_video_provider_spec
from backend.video_generation import VideoGenerationResult, video_fallback_mode
from backend.config_utils import env_bool, env_float


def windows_fontfile() -> str | None:
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/simsun.ttc"),
    ]
    for item in candidates:
        if item.exists():
            return str(item).replace("\\", "/").replace(":", "\\:")
    return None


def drawtext(textfile: str, y: int, size: int, color: str = "white", box: bool = True) -> str:
    font = windows_fontfile()
    options = [
        f"textfile='{textfile}'",
        f"fontcolor={color}",
        f"fontsize={size}",
        "line_spacing=12",
        "x=(w-text_w)/2",
        f"y={y}",
    ]
    if font:
        options.insert(1, f"fontfile='{font}'")
    if box:
        options.extend(["box=1", "boxcolor=black@0.42", "boxborderw=24"])
    return "drawtext=" + ":".join(options)


def camera_zoompan_filter(
    camera: str,
    duration: float,
    zoom_limit: float,
    speed: float = 1.0,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    hold_in_ratio: float = 0.12,
    hold_out_ratio: float = 0.12,
) -> str:
    camera = (camera or "slow_push_in").strip().lower()
    frames = max(1, int(max(0.25, duration) * 30))
    speed = clamp(float(speed or 1.0), 0.35, 3.0)
    hold_in_ratio = clamp(float(hold_in_ratio or 0.0), 0.0, 0.45)
    hold_out_ratio = clamp(float(hold_out_ratio or 0.0), 0.0, 0.45)
    hold_in_frames = max(0, int(frames * hold_in_ratio))
    hold_out_frames = max(0, int(frames * hold_out_ratio))
    if hold_in_frames + hold_out_frames >= frames:
        overflow = hold_in_frames + hold_out_frames - (frames - 1)
        if overflow > 0:
            reduce_out = min(overflow, hold_out_frames)
            hold_out_frames -= reduce_out
            overflow -= reduce_out
            if overflow > 0:
                hold_in_frames = max(0, hold_in_frames - overflow)
    hold_out_start = max(hold_in_frames + 1, frames - hold_out_frames)
    motion_frames = max(1, hold_out_start - hold_in_frames)
    motion_progress = f"min(1,max(0,(on-{hold_in_frames})/{max(1, motion_frames - 1)}))"
    progress = f"if(lt(on,{hold_in_frames}),0,if(gte(on,{hold_out_start}),1,{motion_progress}))"
    ease_in = f"({progress})*({progress})"
    ease_out = f"1-(1-({progress}))*(1-({progress}))"
    zoom_limit = max(1.02, float(zoom_limit))
    focus_x = clamp(float(focus_x), 0.0, 1.0)
    focus_y = clamp(float(focus_y), 0.0, 1.0)
    focus_x_expr = f"iw*{focus_x:.3f}"
    focus_y_expr = f"ih*{focus_y:.3f}"

    zoom_in = f"min({zoom_limit:.3f},1+({zoom_limit:.3f}-1)*({ease_out}))"
    zoom_out = f"max(1.000,{zoom_limit:.3f}-({zoom_limit:.3f}-1)*({ease_out}))"
    center_x = "iw/2-(iw/zoom/2)"
    center_y = "ih/2-(ih/zoom/2)"
    max_x = "(iw-iw/zoom)"
    max_y = "(ih-ih/zoom)"

    if camera == "dramatic_push":
        target_zoom = min(max(zoom_limit + 0.05, 1.30), 1.46)
        return (
            f"zoompan=z='min({target_zoom:.3f},1+({target_zoom:.3f}-1)*({ease_out}))'"
            f":x='min(max({focus_x_expr}-(iw/zoom/2),0),(iw-iw/zoom))'"
            f":y='min(max({focus_y_expr}-(ih/zoom/2),0),(ih-ih/zoom))'"
            ":d=1:s=1080x1920:fps=30"
        )
    if camera == "melancholy_pan":
        return (
            "zoompan=z='1.180'"
            f":x='min(max((iw-(iw/zoom))*({progress}),0),(iw-iw/zoom))'"
            f":y='min(max({focus_y_expr}-(ih/zoom/2),0),(ih-ih/zoom))'"
            ":d=1:s=1080x1920:fps=30"
        )
    if camera == "establishing_tilt":
        return (
            "zoompan=z='1.200'"
            f":x='min(max({focus_x_expr}-(iw/zoom/2),0),(iw-iw/zoom))'"
            f":y='min(max({max_y}*(1-({progress})),0),(ih-ih/zoom))'"
            ":d=1:s=1080x1920:fps=30"
        )
    if camera == "slow_zoom_out":
        return (
            f"zoompan=z='{zoom_out}'"
            f":x='min(max({focus_x_expr}-(iw/zoom/2),0),(iw-iw/zoom))'"
            f":y='min(max({focus_y_expr}-(ih/zoom/2),0),(ih-ih/zoom))'"
            ":d=1:s=1080x1920:fps=30"
        )
    if camera == "pan_left":
        return f"zoompan=z='min({zoom_limit:.3f},1.100+0.00012*on)':x='min(max({max_x}*(1-{progress}),0),(iw-iw/zoom))':y='min(max({focus_y_expr}-(ih/zoom/2),0),(ih-ih/zoom))':d=1:s=1080x1920:fps=30"
    if camera == "pan_right":
        return f"zoompan=z='min({zoom_limit:.3f},1.100+0.00012*on)':x='min(max({max_x}*{progress},0),(iw-iw/zoom))':y='min(max({focus_y_expr}-(ih/zoom/2),0),(ih-ih/zoom))':d=1:s=1080x1920:fps=30"
    if camera == "tilt_down":
        return f"zoompan=z='min({zoom_limit:.3f},1.080+0.00010*on)':x='min(max({focus_x_expr}-(iw/zoom/2),0),(iw-iw/zoom))':y='min(max({max_y}*{progress},0),(ih-ih/zoom))':d=1:s=1080x1920:fps=30"
    if camera == "tilt_up":
        return f"zoompan=z='min({zoom_limit:.3f},1.080+0.00010*on)':x='min(max({focus_x_expr}-(iw/zoom/2),0),(iw-iw/zoom))':y='min(max({max_y}*(1-{progress}),0),(ih-ih/zoom))':d=1:s=1080x1920:fps=30"
    if camera == "dramatic_reveal":
        return (
            f"zoompan=z='min({zoom_limit + 0.030:.3f},1+0.00075*on)'"
            f":x='min(max({focus_x_expr}-(iw/zoom/2)+8*sin(on*0.65),0),(iw-iw/zoom))'"
            f":y='min(max({focus_y_expr}-(ih/zoom/2)+6*sin(on*0.93),0),(ih-ih/zoom))'"
            ":d=1:s=1080x1920:fps=30"
        )
    if camera == "pull_back":
        return (
            f"zoompan=z='max(1.0,{zoom_limit:.3f}-(0.20*({progress})))'"
            f":x='min(max({focus_x_expr}-(iw/zoom/2),0),(iw-iw/zoom))'"
            f":y='min(max({focus_y_expr}-(ih/zoom/2),0),(ih-ih/zoom))'"
            ":d=1:s=1080x1920:fps=30"
        )
    if camera == "slow_push":
        target_zoom = max(zoom_limit, 1.17)
        return (
            f"zoompan=z='min({target_zoom:.3f},1+({target_zoom:.3f}-1)*({ease_out}))'"
            f":x='min(max({focus_x_expr}-(iw/zoom/2),0),(iw-iw/zoom))'"
            f":y='min(max({focus_y_expr}-(ih/zoom/2),0),(ih-ih/zoom))'"
            ":d=1:s=1080x1920:fps=30"
        )
    return (
        f"zoompan=z='{zoom_in}'"
        f":x='min(max({focus_x_expr}-(iw/zoom/2),0),(iw-iw/zoom))'"
        f":y='min(max({focus_y_expr}-(ih/zoom/2),0),(ih-ih/zoom))'"
        ":d=1:s=1080x1920:fps=30"
    )


def render_silent_visual_segment(
    ffmpeg: str,
    image_path: Path,
    duration: float,
    out_path: Path,
    zoom_limit: float,
    camera: str = "slow_push_in",
    beat_index: int = 1,
    camera_speed: float = 1.0,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    hold_in_ratio: float = 0.12,
    hold_out_ratio: float = 0.12,
    screen_shake: bool = False,
) -> Path:
    duration = max(0.25, float(duration))
    fade_out_start = max(0.0, duration - 0.18)
    reveal_filter = "eq=contrast=1.08:saturation=1.05"
    if beat_index >= 3 or camera == "dramatic_reveal":
        reveal_filter = "eq=contrast=1.16:saturation=1.12"
    filter_parts = [
        "scale=1080:1920",
        camera_zoompan_filter(
            camera,
            duration,
            zoom_limit,
            speed=camera_speed,
            focus_x=focus_x,
            focus_y=focus_y,
            hold_in_ratio=hold_in_ratio,
            hold_out_ratio=hold_out_ratio,
        ),
    ]
    if screen_shake:
        filter_parts.append("crop=1060:1884:x='10+10*sin(n*1.9)':y='18+14*sin(n*2.7)',scale=1080:1920")
    filter_parts.extend(
        [
            reveal_filter,
            f"fade=t=in:st=0:d=0.10,fade=t=out:st={fade_out_start:.3f}:d=0.18",
            "format=yuv420p",
        ]
    )
    video_filter = ",".join(filter_parts)
    cmd = [
        ffmpeg,
        "-y",
        "-loop",
        "1",
        "-i",
        str(image_path),
        "-vf",
        video_filter,
        "-t",
        f"{duration:.3f}",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        str(out_path),
    ]
    run_guarded(
        cmd,
        cwd=out_path.parent,
        timeout=render_timeout(duration),
        stage="ffmpeg_render_segment",
    )
    return out_path


def concat_video_segments(
    ffmpeg: str,
    clips: list[Path],
    out_path: Path,
    run_dir: Path,
    durations: list[float] | None = None,
    transition_duration: float = 0.24,
) -> Path:
    def _concat_copy(stage: str = "ffmpeg_concat_video") -> Path:
        concat_file = run_dir / f"{out_path.stem}_concat.txt"
        lines = [f"file '{clip.name}'" for clip in clips]
        write_text(concat_file, "\n".join(lines))
        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(out_path),
        ]
        run_guarded(cmd, cwd=run_dir, timeout=concat_timeout(len(clips)), stage=stage)
        return out_path

    if len(clips) <= 1 or not durations or len(durations) != len(clips) or not env_bool("COMICDRAMA_ENABLE_XFADE", default=False):
        return _concat_copy()

    xfades = ["fade", "smoothleft", "wipeleft", "fadeblack"]
    filter_parts: list[str] = []
    for index, clip in enumerate(clips):
        filter_parts.append(f"[{index}:v]settb=AVTB,fps=30,setpts=PTS-STARTPTS,format=yuv420p[v{index}]")
    current = "v0"
    current_duration = float(durations[0])
    for index in range(1, len(clips)):
        next_label = f"v{index}"
        transition = xfades[(index - 1) % len(xfades)]
        available = max(0.05, current_duration + float(durations[index]) - transition_duration)
        offset = max(0.0, available - transition_duration)
        out_label = f"x{index}"
        filter_parts.append(
            f"[{current}][{next_label}]xfade=transition={transition}:duration={transition_duration:.3f}:offset={offset:.3f}[{out_label}]"
        )
        current = out_label
        current_duration = available
    cmd = [ffmpeg, "-y"]
    for clip in clips:
        cmd.extend(["-i", str(clip)])
    cmd.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            f"[{current}]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(out_path),
        ]
    )
    try:
        run_guarded(cmd, cwd=run_dir, timeout=concat_timeout(len(clips)) + 120, stage="ffmpeg_concat_video_xfade")
    except Exception as exc:
        print(f"[video] xfade failed for {out_path.name}: {exc}; falling back to concat")
        return _concat_copy(stage="ffmpeg_concat_video_fallback")
    return out_path


def mux_audio_to_visual(ffmpeg: str, visual_path: Path, voice_path: Path, out_path: Path) -> Path:
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(visual_path),
        "-i",
        str(voice_path),
        "-shortest",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(out_path),
    ]
    run_guarded(cmd, cwd=out_path.parent, timeout=DEFAULT_SUBPROCESS_TIMEOUTS["ffmpeg_audio"], stage="ffmpeg_mux_audio")
    return out_path


def render_clip_with_meta(
    ffmpeg: str,
    scene: StoryScene,
    run_dir: Path,
    keyframe_provider: str,
    voice_provider: str,
    clip_duration: float,
    voice_path: Path,
    subtitle_style: dict | None = None,
    audio_style: dict | None = None,
    project_root: Path | None = None,
    keyframe_path: Path | None = None,
    video_provider: str = "auto",
) -> tuple[Path, VideoGenerationResult]:
    style = normalize_subtitle_style(subtitle_style)
    audio_settings = normalize_audio_style(audio_style)
    scene_id = f"{scene.scene:02}"
    keyframe = keyframe_path if keyframe_path and keyframe_path.exists() else generate_keyframe(scene, run_dir, keyframe_provider)
    out = run_dir / f"clip_{scene_id}.mp4"
    muxed = run_dir / f"clip_{scene_id}_muxed.mp4"
    graded = run_dir / f"clip_{scene_id}_graded.mp4"
    visual_path = run_dir / f"scene_{scene_id}_visual.mp4"
    subtitle_path = run_dir / f"scene_{scene_id}_dialogue.srt"
    subtitle_ass_path = run_dir / f"scene_{scene_id}_dialogue.ass"
    scene_audio = mix_voice_with_bgm(
        ffmpeg,
        voice_path,
        run_dir / f"scene_{scene_id}_mix.wav",
        clip_duration,
        scene_audio_style(scene, audio_settings, project_root=project_root),
        project_root=project_root,
    )
    scene_audio = mix_scene_sfx(ffmpeg, scene_audio, scene, run_dir, clip_duration, project_root=project_root)

    visual_generated = False
    provider_spec = get_video_provider_spec(video_provider)
    provider = provider_spec.id
    fallback_mode = video_fallback_mode(provider)
    attempts = 1
    last_error = ""
    warnings: list[str] = []
    used_backend = provider_spec.backend
    fallback_used = False
    if provider_spec.backend == "comfyui":
        try:
            print(f"[video] Rendering scene {scene_id} with {provider_spec.label} video provider")
            render_scene_video_comfyui(scene, keyframe, clip_duration, visual_path, run_dir)
            visual_generated = True
        except Exception as exc:
            last_error = str(exc)
            if fallback_mode == "strict":
                raise
            fallback_used = True
            used_backend = "local"
            if fallback_mode == "report":
                warnings.append(f"{provider_spec.label} video provider failed; using local 2.5D fallback.")
            print(f"[video] {provider_spec.label} video provider failed for scene {scene_id}; falling back to 2.5D clip: {exc}")
    elif provider_spec.backend == "remote":
        max_retries = int(env_float("VIDEO_MAX_RETRIES", default=2))
        retry_delay = env_float("VIDEO_RETRY_DELAY_SECONDS", default=5.0)
        last_exc = None
        for attempt in range(1, max_retries + 2):
            attempts = attempt
            try:
                print(f"[video] Rendering scene {scene_id} with {provider_spec.label} remote video provider (attempt {attempt}/{max_retries + 1})")
                prompt_text, negative_text = build_scene_video_prompts(scene, clip_duration, run_dir)
                temporal_spec = scene.temporal_spec or build_scene_temporal_spec(
                    scene,
                    clip_duration,
                    width=int(env_float("VIDEO_WIDTH", default=1080)),
                    height=int(env_float("VIDEO_HEIGHT", default=1920)),
                    fps=int(env_float("VIDEO_FPS", default=24)),
                )
                consistency_spec = scene_consistency_spec(scene)
                render_remote_video_provider(
                    VideoRenderRequest(
                        scene=scene.scene,
                        title=scene.title,
                        prompt=prompt_text,
                        negative_prompt=negative_text,
                        keyframe_path=keyframe,
                        out_path=visual_path,
                        run_dir=run_dir,
                        duration=clip_duration,
                        width=int(env_float("VIDEO_WIDTH", default=1080)),
                        height=int(env_float("VIDEO_HEIGHT", default=1920)),
                        fps=int(env_float("VIDEO_FPS", default=24)),
                        camera=scene.camera,
                        emotion=scene.emotion,
                        dialogue=scene.dialogue,
                        characters=tuple(scene.characters or []),
                        temporal_spec=temporal_spec,
                        consistency_spec=consistency_spec,
                    ),
                    provider_spec,
                    ffmpeg=ffmpeg,
                    run_guarded=run_guarded,
                    timeout_s=render_timeout(clip_duration) + 300,
                )
                visual_generated = True
                break
            except Exception as exc:
                last_exc = exc
                last_error = str(exc)
                if attempt <= max_retries:
                    # Use longer backoff for rate limiting / quota errors
                    error_str = str(exc).lower()
                    if "429" in error_str or "quota" in error_str or "饱和" in error_str:
                        backoff = max(retry_delay, 30.0)  # At least 30s for quota issues
                        print(f"[video] {provider_spec.label} attempt {attempt} rate-limited for scene {scene_id}. Waiting {backoff:.0f}s...")
                    else:
                        backoff = retry_delay
                        print(f"[video] {provider_spec.label} attempt {attempt} failed for scene {scene_id}: {exc}. Retrying in {backoff:.0f}s...")
                    time.sleep(backoff)
                    retry_delay = min(retry_delay * 2.0, 120.0)
                else:
                    if fallback_mode == "strict":
                        raise
                    fallback_used = True
                    used_backend = "local"
                    if fallback_mode == "report":
                        warnings.append(
                            f"{provider_spec.label} remote video provider failed after {attempt} attempts; using local 2.5D fallback."
                        )
                    print(f"[video] {provider_spec.label} remote video provider failed for scene {scene_id} after {attempt} attempts; falling back to 2.5D clip: {exc}")
    elif provider_spec.backend != "local":
        raise ValueError(f"Unsupported video provider backend: {provider_spec.backend}")

    if not visual_generated:
        d = clip_duration
        spoken_text = split_dialogue_speaker(scene.dialogue)[1]
        beat_specs = build_scene_beats(scene, d, spoken_text)
        screen_shake = scene_should_screen_shake(scene)

        with Image.open(keyframe) as source:
            base_image = apply_crop_box(source.convert("RGBA"), scene.crop_box)
        beat_segments: list[Path] = []
        for idx, beat in enumerate(beat_specs, start=1):
            frame_path = compose_comic_frame(base_image, scene, beat, run_dir, scene_id, idx, len(beat_specs))
            segment_path = run_dir / f"scene_{scene_id}_beat_{idx}.mp4"
            render_silent_visual_segment(
                ffmpeg,
                frame_path,
                float(beat["duration"]),
                segment_path,
                float(beat["zoom"]) + 0.06,
                scene.camera,
                idx,
                camera_speed=float(scene.camera_speed or 1.0),
                focus_x=float(beat.get("center_x", 0.5)),
                focus_y=float(beat.get("center_y", 0.5)),
                hold_in_ratio=float(beat.get("hold_in_ratio", 0.12)),
                hold_out_ratio=float(beat.get("hold_out_ratio", 0.12)),
                screen_shake=screen_shake and idx >= 3,
            )
            beat_segments.append(segment_path)

        concat_video_segments(
            ffmpeg,
            beat_segments,
            visual_path,
            run_dir,
            durations=[float(beat["duration"]) for beat in beat_specs],
            transition_duration=0.22,
        )
    mux_audio_to_visual(ffmpeg, visual_path, scene_audio, muxed)
    try:
        apply_scene_grade(ffmpeg, muxed, graded, scene)
    except Exception as exc:
        print(f"[video] Cinematic grade failed for scene {scene_id}: {exc}")
        graded = muxed

    subtitle_source = subtitle_ass_path if subtitle_ass_path.exists() and subtitle_ass_path.read_text(encoding="utf-8").strip() else subtitle_path
    if style.get("burn_in", True) and subtitle_source.exists() and subtitle_source.read_text(encoding="utf-8").strip():
        try:
            burn_subtitles_to_video(ffmpeg, graded, subtitle_source, out, style, timeout_s=render_timeout(clip_duration))
        except Exception as exc:
            print(f"[video] Subtitle burn failed for scene {scene_id}: {exc}")
            if graded != out:
                graded.replace(out)
        finally:
            if muxed.exists():
                muxed.unlink()
            if graded.exists() and graded != out:
                graded.unlink()
    else:
        if graded != out:
            graded.replace(out)
    result = VideoGenerationResult(
        scene_order=scene.scene,
        provider_id=provider_spec.id,
        provider_label=provider_spec.label,
        success=True,
        is_real_video=bool(visual_generated and provider_spec.backend in {"comfyui", "remote"} and not fallback_used),
        attempts=attempts,
        duration_seconds=clip_duration,
        output_path=str(out),
        error=last_error if fallback_used else "",
        warnings=warnings,
        backend=used_backend,
        fallback_used=fallback_used,
    )
    return out, result


def render_clip(
    ffmpeg: str,
    scene: StoryScene,
    run_dir: Path,
    keyframe_provider: str,
    voice_provider: str,
    clip_duration: float,
    voice_path: Path,
    subtitle_style: dict | None = None,
    audio_style: dict | None = None,
    project_root: Path | None = None,
    keyframe_path: Path | None = None,
    video_provider: str = "auto",
) -> Path:
    clip_path, _ = render_clip_with_meta(
        ffmpeg,
        scene,
        run_dir,
        keyframe_provider,
        voice_provider,
        clip_duration,
        voice_path,
        subtitle_style,
        audio_style,
        project_root,
        keyframe_path=keyframe_path,
        video_provider=video_provider,
    )
    return clip_path


def _normalize_scene_emotion(value: object) -> str:
    emotion = str(value or "").strip().lower()
    aliases = {
        "angry": "anger",
        "tense": "tension",
        "tense_scene": "tension",
        "fearful": "fear",
        "scared": "fear",
        "panic": "fear",
        "happy": "joy",
        "joyful": "joy",
        "sad": "sadness",
        "sorrow": "sadness",
        "melancholy": "sadness",
        "neutral": "neutral",
    }
    return aliases.get(emotion, emotion)


def _scene_transition(prev_emotion: str, next_emotion: str) -> str:
    prev = _normalize_scene_emotion(prev_emotion)
    nxt = _normalize_scene_emotion(next_emotion)
    if not prev or not nxt or prev == nxt:
        return "cut"

    black = {
        ("anger", "sadness"),
        ("anger", "calm"),
        ("fear", "calm"),
        ("tension", "calm"),
        ("joy", "sadness"),
        ("joy", "anger"),
    }
    xfade = {
        ("calm", "tension"),
        ("calm", "anger"),
        ("calm", "fear"),
        ("calm", "sadness"),
        ("calm", "surprise"),
        ("calm", "joy"),
        ("tension", "fear"),
        ("tension", "sadness"),
        ("sadness", "joy"),
        ("sadness", "calm"),
        ("sadness", "tension"),
        ("surprise", "sadness"),
        ("surprise", "calm"),
        ("fear", "sadness"),
    }

    pair = (prev, nxt)
    if pair in black:
        return "black"
    if pair in xfade:
        return "xfade"
    return "cut"


def _concat_cut_pair(ffmpeg: str, first: Path, second: Path, out_path: Path, run_dir: Path, stage: str) -> None:
    filter_complex = ";".join(
        [
            "[0:v]setpts=PTS-STARTPTS,fps=30,format=yuv420p[v0]",
            "[1:v]setpts=PTS-STARTPTS,fps=30,format=yuv420p[v1]",
            "[0:a]asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo[a0]",
            "[1:a]asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo[a1]",
            "[v0][v1]concat=n=2:v=1:a=0[v]",
            "[a0][a1]concat=n=2:v=0:a=1[a]",
        ]
    )
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(first),
        "-i",
        str(second),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(out_path),
    ]
    run_guarded(cmd, cwd=run_dir, timeout=concat_timeout(2) + 120, stage=stage)


def _concat_xfade_pair(
    ffmpeg: str,
    first: Path,
    second: Path,
    out_path: Path,
    run_dir: Path,
    first_duration: float,
) -> bool:
    fade_duration = 0.2
    if float(first_duration) <= fade_duration + 0.1:
        print(
            f"[video] xfade skipped for short segment ({float(first_duration):.3f}s); falling back to cut"
        )
        _concat_cut_pair(ffmpeg, first, second, out_path, run_dir, "ffmpeg_concat_video_xfade_short_fallback")
        return False
    offset = max(0.0, float(first_duration) - fade_duration - 0.05)
    filter_complex = ";".join(
        [
            "[0:v]setpts=PTS-STARTPTS,fps=30,format=yuv420p[v0]",
            "[1:v]setpts=PTS-STARTPTS,fps=30,format=yuv420p[v1]",
            "[0:a]asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo[a0]",
            "[1:a]asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo[a1]",
            f"[v0][v1]xfade=transition=fade:duration={fade_duration:.3f}:offset={offset:.3f}[v]",
            f"[a0][a1]acrossfade=d={fade_duration:.3f}:c1=tri:c2=tri[a]",
        ]
    )
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(first),
        "-i",
        str(second),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(out_path),
    ]
    run_guarded(cmd, cwd=run_dir, timeout=concat_timeout(2) + 120, stage="ffmpeg_concat_video_xfade")
    return True


def _concat_black_pair(
    ffmpeg: str,
    first: Path,
    second: Path,
    out_path: Path,
    run_dir: Path,
    first_duration: float,
    second_duration: float,
) -> None:
    fade_duration = 0.15
    first_fade_start = max(0.0, float(first_duration) - fade_duration)
    filter_complex = ";".join(
        [
            f"[0:v]setpts=PTS-STARTPTS,fps=30,format=yuv420p,fade=t=out:st={first_fade_start:.3f}:d={fade_duration:.3f}[v0]",
            f"[1:v]setpts=PTS-STARTPTS,fps=30,format=yuv420p,fade=t=in:st=0:d={fade_duration:.3f}[v1]",
            f"[0:a]asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo,afade=t=out:st={first_fade_start:.3f}:d={fade_duration:.3f}[a0]",
            f"[1:a]asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo,afade=t=in:st=0:d={fade_duration:.3f}[a1]",
            "[v0][v1]concat=n=2:v=1:a=0[v]",
            "[a0][a1]concat=n=2:v=0:a=1[a]",
        ]
    )
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(first),
        "-i",
        str(second),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(out_path),
    ]
    run_guarded(cmd, cwd=run_dir, timeout=concat_timeout(2) + 120, stage="ffmpeg_concat_video_black")


def concat_clips(
    ffmpeg: str,
    clips: list[Path],
    scenes: list[StoryScene],
    durations: list[float],
    run_dir: Path,
) -> Path:
    out = run_dir / "comic_drama_demo.mp4"
    if not clips:
        raise ValueError("No clips to concatenate")
    if len(clips) != len(scenes) or len(clips) != len(durations):
        concat_file = run_dir / "concat.txt"
        lines = [f"file '{clip.name}'" for clip in clips]
        write_text(concat_file, "\n".join(lines))
        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(out),
        ]
        run_guarded(cmd, cwd=run_dir, timeout=concat_timeout(len(clips)), stage="ffmpeg_concat_clips")
        return out

    current_path = clips[0]
    current_duration = media_duration(ffmpeg, current_path)

    for index in range(1, len(clips)):
        next_clip = clips[index]
        next_duration = media_duration(ffmpeg, next_clip)
        prev_scene = scenes[index - 1]
        next_scene = scenes[index]
        transition = _scene_transition(prev_scene.emotion_tone, next_scene.emotion_tone)
        print(
            f"[debug] scene transition {index}->{index + 1}: "
            f"{_normalize_scene_emotion(prev_scene.emotion_tone)} -> "
            f"{_normalize_scene_emotion(next_scene.emotion_tone)} = {transition}"
        )

        stage_out = run_dir / f"transition_{index:02d}.mp4"
        try:
            if transition == "xfade":
                used_xfade = _concat_xfade_pair(ffmpeg, current_path, next_clip, stage_out, run_dir, current_duration)
                if used_xfade:
                    current_duration = max(0.0, current_duration + next_duration - 0.2)
                else:
                    current_duration = current_duration + next_duration
            elif transition == "black":
                _concat_black_pair(ffmpeg, current_path, next_clip, stage_out, run_dir, current_duration, next_duration)
                current_duration = current_duration + next_duration
            else:
                _concat_cut_pair(ffmpeg, current_path, next_clip, stage_out, run_dir, "ffmpeg_concat_clips_cut")
                current_duration = current_duration + next_duration
        except Exception as exc:
            if transition != "cut":
                print(
                    f"[video] transition {index}->{index + 1} ({transition}) failed: {exc}; falling back to cut"
                )
            if stage_out.exists():
                try:
                    stage_out.unlink()
                except OSError:
                    pass
            _concat_cut_pair(ffmpeg, current_path, next_clip, stage_out, run_dir, "ffmpeg_concat_clips_cut_fallback")
            current_duration = current_duration + next_duration

        current_path = stage_out

    if current_path != out:
        shutil.copy2(current_path, out)
    faststart_out = out.with_name(f"{out.stem}_faststart{out.suffix}")
    try:
        run_guarded(
            [
                ffmpeg,
                "-y",
                "-i",
                str(out),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(faststart_out),
            ],
            cwd=run_dir,
            timeout=concat_timeout(1),
            stage="ffmpeg_faststart_remux",
        )
        faststart_out.replace(out)
    except Exception as exc:
        print(f"[video] faststart remux failed for {out.name}: {exc}")
        if faststart_out.exists():
            try:
                faststart_out.unlink()
            except OSError:
                pass
    return out
