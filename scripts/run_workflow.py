from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import re
import subprocess
import shutil
import wave
import textwrap
import time
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from typing import Any

try:
    import imageio_ffmpeg
except ImportError:  # pragma: no cover - optional runtime dependency
    imageio_ffmpeg = None
from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont
try:
    import pyttsx3
except ImportError:  # pragma: no cover - optional runtime dependency
    pyttsx3 = None

from scripts import tts_engines
from scripts.director_classifier import (
    DirectorClassificationError,
    VISUAL_CONTENT_FIELDS,
    apply_default_classification,
    apply_llm_classification,
    apply_rules_classification,
    build_director_plan,
    build_shot_visual_content,
    classify_scenes_batch,
)
from scripts.bgm_matcher import select_bgm_for_scene
from scripts.comfyui_patcher import patch_workflow
from scripts.prompt_compiler import PromptCompiler, find_project_root
from scripts.subtitle_style import build_ass_document
from scripts.comfyui_ssh_tunnel import ensure_comfyui_tunnel
from scripts.video_provider_adapters import VideoRenderRequest, render_remote_video_provider
from video_providers import get_video_provider_spec, normalize_video_provider as resolve_video_provider_name
from backend.video_generation import VideoGenerationResult, generation_meta_from_result, normalize_generation_meta, video_fallback_mode, video_render_granularity
from backend.llm_hub import llm_client
from backend.config_utils import (
    env_value,
    env_optional_value,
    env_float,
    env_bool,
    coerce_int as _coerce_int,
    coerce_float as _coerce_float,
    coerce_bool as _coerce_bool,
)

edge_tts = tts_engines.edge_tts

from scripts.rw_config import *
from scripts.rw_models import (
    AudioConfig,
    CameraConfig,
    CharacterReferenceConfig,
    DirectorConfig,
    EpisodePacing,
    ProductionConfig,
    SceneValidationError,
    StoryScene,
    ValidationState,
    VoiceConfig,
)
from scripts.rw_ffmpeg import get_ffmpeg_exe, render_timeout, concat_timeout, _stderr_excerpt, run_guarded
from scripts.rw_utils import wrap_cn, write_text, load_env_file, ensure_parent, wav_duration, media_duration, write_silent_wav, load_json, replace_placeholders, unresolved_placeholders, write_debug_json, clamp
from scripts.rw_styles import default_subtitle_style, default_episode_pacing, normalize_episode_phase, normalize_episode_pacing, infer_episode_phase, apply_episode_pacing_to_scenes, normalize_subtitle_style, default_audio_style, normalize_audio_style, normalize_crop_box, normalize_audio_manifest
from scripts.rw_image import font_candidates, pick_font, hex_to_rgb, blend_color, wrap_for_pixels, draw_paragraph, apply_crop_box, split_text_chunks, focal_crop, emotion_stamp, create_keyframe, compose_comic_frame
from scripts.rw_voice import voice_presets_path, load_voice_presets, split_dialogue_speaker, split_dialogue_lines, infer_voice_profile, resolve_voice_name, resolve_voice_engine, local_tts_engine, synthesize_local_tts, synthesize_windows_sapi_tts, format_edge_rate, format_edge_volume, format_edge_pitch, synthesize_edge_tts, convert_audio_to_wav, concat_audio_segments, synthesize_voice_fragment, resolve_dialogue_voice, render_voice_track
from scripts.rw_audio import _subtitle_rolls, write_scene_subtitles, ass_timestamp, ass_escape_text, write_ass_entries, ffmpeg_escape_filter_path, burn_subtitles_to_video, db_to_linear, normalize_audio_track, resolve_path, mix_voice_with_bgm, audio_manifest_dict, resolve_audio_asset, normalize_sfx_kind, scene_audio_style, srt_timestamp, format_subtitle_text, write_srt_entries, write_srt, write_srt_from_durations, parse_srt_timestamp, parse_srt_entries, offset_srt_entries, _scene_field, _scene_subtitle_emotion, _scene_dialogue_segments, stitch_scene_subtitles, write_tone_sfx, sfx_kind_for_scene, _beat_sfx_triggers, scene_sfx_triggers, scene_should_screen_shake, mix_scene_sfx, apply_scene_grade

from scripts.rw_planning import (
    build_scene_beats,
    build_scene_graph,
    build_scene_temporal_spec,
    _timeline_scene_field,
    _scene_media_reference,
    _scene_duration_seconds,
    normalize_shot_plan_visual_content,
    _merge_default_dict,
    build_shot_plan,
    _compact_shot_generation,
    _shot_timeline_with_generation,
    build_canonical_timeline,
)
from scripts.rw_prompts import (
    ANIME_STYLE_SUFFIX,
    ANIME_STYLE_SUFFIX_EXTRA,
    ANIME_NEGATIVE_PROMPT_EXTRA,
    DIRECTOR_SYSTEM_PROMPT,
    anime_visual_prompt,
    anime_video_prompt,
    infer_character_appearance_hint,
    clean_comfyui_visual_prompt,
    scene_consistency_spec,
    temporal_spec_prompt_lines,
    _scene_prompt_mapping,
    _existing_scene_shot_plan,
    _prototype_constraint_prompt_line,
    _shot_visual_content_prompt_lines,
    _scene_visual_prompt_source,
    build_scene_video_prompts,
    storyboard_prompt,
    extract_json_object,
    post_llm_chat_completion,
    _call_llm_chat_content,
    script_storyboard_prompt,
    call_llm_script_storyboard,
)
from scripts.rw_comfyui import (
    COMFYUI_STYLE_PRESETS,
    comfyui_style_preset,
    append_prompt_suffix,
    inject_comfyui_workflow,
    comfyui_base_url,
    comfyui_auth_headers,
    comfyui_workflow_path,
    comfyui_video_workflow_path,
    comfyui_input_dir,
    comfyui_reference_mode,
    comfyui_is_local,
    default_comfyui_reference_image_path,
    ensure_default_comfyui_reference_image,
    comfyui_upload_image,
    prepare_comfyui_reference_image,
    _build_consistency_meta,
    _initial_consistency_meta,
    submit_comfyui_prompt,
    poll_comfyui_history,
    download_comfyui_image,
    download_comfyui_asset,
    render_scene_video_comfyui,
    render_keyframe_comfyui,
    generate_keyframe,
    _generate_keyframe_cloud,
    normalize_video_provider,
    comfyui_checkpoint_name,
    comfyui_lora_name,
)
from scripts.rw_storyboard import (
    build_rule_storyboard,
    _raw_scene_number,
    validate_scene,
    make_failed_placeholder,
    _apply_director_rule_recommendation,
    _apply_director_classification_to_scenes,
    coerce_scene,
    call_llm_storyboard,
    build_storyboard,
    _clean_script_label,
    _looks_like_speaker_label,
    _looks_like_scene_heading,
    _split_script_dialogue,
    _is_script_cue_line,
    _normalize_script_lines,
    _script_block_char_count,
    _split_script_paragraphs,
    _is_storyboard_shot_heading,
    _merge_script_shot_blocks,
    _strip_brackets,
    _merge_script_text,
    _infer_script_camera,
    _infer_script_emotion,
    _derive_script_scene_title,
    _build_scene_block,
    _compress_script_blocks,
    build_rule_script_storyboard,
    build_script_storyboard,
    _collect_script_role_counts,
    _event_summary_lines,
    analyze_script_text,
    validate_script_text,
    is_script_text_garbled,
    analyze_script_workflow,
)
from scripts.rw_render import (
    windows_fontfile,
    drawtext,
    camera_zoompan_filter,
    render_silent_visual_segment,
    concat_video_segments,
    mux_audio_to_visual,
    render_clip_with_meta,
    render_clip,
    _normalize_scene_emotion,
    _scene_transition,
    _concat_cut_pair,
    _concat_xfade_pair,
    _concat_black_pair,
    concat_clips,
)

ANIME_NEGATIVE_PROMPT = (
    "低质量，模糊，像解说封面，文字海报，漫画分镜板，"
    "旁白字幕块，信息图，过度扁平，畸形手指，重复脸，水印"
)


async def synthesize_edge_tts_async(
    text: str,
    out_path: Path,
    voice: str,
    rate: float = 1.0,
    volume: float = 1.0,
    pitch: float = 0.0,
) -> None:
    await tts_engines.synthesize_edge_tts_async(text, out_path, voice, rate=rate, volume=volume, pitch=pitch)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local comic-drama workflow MVP.")
    parser.add_argument("--story", "--input", dest="story", type=Path, default=DEFAULT_STORY, help="Path to a story text file.")
    parser.add_argument("--run-id", default=None, help="Optional output run id.")
    parser.add_argument("--planner", choices=["auto", "rule", "llm"], default="auto", help="Storyboard planner to use.")
    parser.add_argument("--scene-count", type=int, default=5, help="Number of storyboard scenes for LLM planning.")
    parser.add_argument("--keyframe-provider", choices=["auto", "local", "comfyui"], default="auto", help="Keyframe renderer backend.")
    parser.add_argument("--video-provider", type=str, default="auto", help="Scene video provider id (for example: auto, local, comfyui).")
    parser.add_argument("--video-render-granularity", choices=["scene", "shot"], default="", help="Video render granularity. Defaults to VIDEO_RENDER_GRANULARITY or scene.")
    parser.add_argument("--voice-provider", choices=["auto", "edge", "local", "silent"], default="auto", help="Voice renderer backend.")
    args = parser.parse_args()

    load_env_file()

    story = args.story.read_text(encoding="utf-8")
    run_id = args.run_id or time.strftime("run_%Y%m%d_%H%M%S")
    run_dir = OUTPUTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg = get_ffmpeg_exe()
    scene_count = min(12, max(1, args.scene_count))
    scenes, planner_used = build_storyboard(story, args.planner, scene_count)
    apply_episode_pacing_to_scenes(scenes, default_episode_pacing())
    keyframe_provider = args.keyframe_provider
    if keyframe_provider == "auto":
        keyframe_provider = env_value("KEYFRAME_PROVIDER", default="auto").lower()
    video_provider = normalize_video_provider(args.video_provider)
    render_granularity = video_render_granularity(cli_value=args.video_render_granularity)
    voice_provider = args.voice_provider
    if voice_provider == "auto":
        voice_provider = env_value("TTS_PROVIDER", default="auto").lower()

    assets = []
    for scene in scenes:
        print(f"[1/5] Preparing scene {scene.scene}: {scene.title}")
        keyframe_path = generate_keyframe(scene, run_dir, keyframe_provider)
        voice_path, voice_duration = render_voice_track(ffmpeg, scene, run_dir, voice_provider)
        clip_duration = max(scene.duration, voice_duration)
        assets.append(
            {
                "scene": scene,
                "keyframe": keyframe_path,
                "voice": voice_path,
                "voice_duration": voice_duration,
                "clip_duration": clip_duration,
                "subtitle": run_dir / f"scene_{scene.scene:02}_dialogue.srt",
            }
        )

    storyboard_path = run_dir / "storyboard.json"
    storyboard_scenes: list[dict[str, object]] = []
    storyboard_shot_count = 0
    for item in assets:
        scene_graph = build_scene_graph(item["scene"])
        storyboard_scene = {
            **asdict(item["scene"]),
            "voice_duration": item["voice_duration"],
            "clip_duration": item["clip_duration"],
            "keyframe": str(item["keyframe"]),
            "voice": str(item["voice"]),
            **scene_graph,
        }
        storyboard_scene["director_plan"] = build_director_plan(storyboard_scene)
        storyboard_scene["shot_plan"] = build_shot_plan(storyboard_scene)
        storyboard_scenes.append(storyboard_scene)
        storyboard_shot_count += len(scene_graph.get("shots") or [])
    canonical_timeline = build_canonical_timeline(
        {
            "project_id": run_dir.name,
            "title": str(storyboard_scenes[0].get("title") or "Storyboard Timeline") if storyboard_scenes else "Storyboard Timeline",
            "scenes": storyboard_scenes,
        }
    )
    canonical_timeline_path = run_dir / "canonical_timeline.json"
    canonical_timeline_path.write_text(json.dumps(canonical_timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    storyboard_path.write_text(
        json.dumps(
            {
                "story": story,
                "planner": planner_used,
                "keyframe_provider": keyframe_provider,
                "video_provider": video_provider,
                "video_render_granularity": render_granularity,
                "voice_provider": voice_provider,
                "canonical_timeline_path": str(canonical_timeline_path),
                "canonical_timeline": canonical_timeline,
                "scenes": storyboard_scenes,
                "scene_graph": {
                    "version": 1,
                    "scene_count": len(storyboard_scenes),
                    "shot_count": storyboard_shot_count,
                },
            },
            ensure_ascii=False,
            indent=2,
            ),
            encoding="utf-8",
        )
    stitch_scene_subtitles(
        [item["subtitle"] for item in assets],
        [item["clip_duration"] for item in assets],
        run_dir / "subtitles.srt",
        fallback_scenes=[item["scene"] for item in assets],
        ass_path=run_dir / "subtitles.ass",
    )

    print(f"[2/5] Storyboard written: {storyboard_path}")
    clips = []
    render_results: list[VideoGenerationResult] = []
    for index, item in enumerate(assets):
        scene = item["scene"]
        print(f"[3/5] Rendering scene {scene.scene}: {scene.title}")
        clip_path, render_result = render_clip_with_meta(
            ffmpeg,
            scene,
            run_dir,
            keyframe_provider,
            voice_provider,
            item["clip_duration"],
            item["voice"],
            keyframe_path=item["keyframe"],
            video_provider=video_provider,
        )
        clips.append(clip_path)
        render_results.append(render_result)
        storyboard_scene = storyboard_scenes[index]
        storyboard_scene["video"] = str(clip_path)
        storyboard_scene["generation_meta"] = generation_meta_from_result(
            render_result,
            requested_provider=video_provider,
            fallback_mode=video_fallback_mode(video_provider),
        )
        storyboard_scene["shot_plan"] = build_shot_plan(storyboard_scene)

    canonical_timeline = build_canonical_timeline(
        {
            "project_id": run_dir.name,
            "title": str(storyboard_scenes[0].get("title") or "Storyboard Timeline") if storyboard_scenes else "Storyboard Timeline",
            "scenes": storyboard_scenes,
        }
    )
    canonical_timeline_path.write_text(json.dumps(canonical_timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    storyboard_path.write_text(
        json.dumps(
            {
                "story": story,
                "planner": planner_used,
                "keyframe_provider": keyframe_provider,
                "video_provider": video_provider,
                "video_render_granularity": render_granularity,
                "voice_provider": voice_provider,
                "canonical_timeline_path": str(canonical_timeline_path),
                "canonical_timeline": canonical_timeline,
                "scenes": storyboard_scenes,
                "scene_graph": {
                    "version": 1,
                    "scene_count": len(storyboard_scenes),
                    "shot_count": storyboard_shot_count,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("[4/5] Concatenating clips")
    final_video = concat_clips(ffmpeg, clips, [item["scene"] for item in assets], [item["clip_duration"] for item in assets], run_dir)
    manifest = {
        "run_id": run_id,
        "planner": planner_used,
        "keyframe_provider": keyframe_provider,
        "video_provider": video_provider,
        "video_render_granularity": render_granularity,
        "voice_provider": voice_provider,
        "ffmpeg": ffmpeg,
        "storyboard": str(storyboard_path),
        "subtitles": str(run_dir / "subtitles.srt"),
        "keyframes": [str(item["keyframe"]) for item in assets],
        "voices": [str(item["voice"]) for item in assets],
        "clips": [str(clip) for clip in clips],
        "final_video": str(final_video),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[5/5] Done: {final_video}")


if __name__ == "__main__":
    main()
