from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from backend.video_generation import (
    VideoGenerationResult,
    VideoShotQuotaError,
    assemble_shot_clips,
    build_shot_assembly_manifest,
    build_shot_cache_key,
    build_shot_output,
    build_shot_provider_request_inputs,
    estimate_shot_render_quota,
    generation_meta_from_result,
    generation_meta_from_shot_outputs,
    normalize_generation_meta,
    render_shot_with_provider_policy,
    validate_shot_render_quota,
    video_fallback_mode,
    video_render_granularity,
    video_shot_quota_config,
)
from scripts.run_workflow import build_canonical_timeline, build_shot_plan

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def _minimal_project_payload(project_id: str, *, video_provider: str = "doubao", legacy: bool = False) -> dict:
    scene = {
        "scene_id": "scene_001",
        "order": 1,
        "title": "Provider scene",
        "visual_prompt": "A character stands in a city street.",
        "dialogue": "Lead: We are ready.",
        "speaker": "Lead",
        "camera_movement": "slow_push",
        "emotion": "neutral",
        "duration_seconds": 4.0,
        "characters": ["Lead"],
        "voice_engine": "silent",
        "voice_id": "",
        "voice_rate": 1.0,
        "voice_pitch": 0.0,
        "voice_volume": 1.0,
        "camera_speed": 1.0,
        "crop_box": {"x": 0, "y": 0, "width": 1, "height": 1},
        "audio_manifest": {
            "bgm_style": "",
            "bgm_file": "",
            "bgm_gain_db": "",
            "sfx_trigger": {"file": "", "timestamp_ms": 0, "volume": 0.65},
            "sfx_triggers": [],
        },
        "temporal_spec": {
            "shots": [
                {
                    "beat_type": "full",
                    "duration_seconds": 4.0,
                    "camera_movement": "slow_push",
                }
            ]
        },
        "assets": {
            "status": "pending",
            "versions": {"image": 1, "audio": 0, "video": 0},
            "image_path": "scenes/scene_001/image_v1.png",
            "image_url": "",
            "audio_path": "",
            "audio_url": "",
            "video_path": "",
            "video_url": "",
        },
        "history": [],
    }
    if not legacy:
        scene["shot_plan"] = {}
        scene["generation_meta"] = {}
    return {
        "project_id": project_id,
        "title": "Provider Mainline Test",
        "story_text": "Provider mainline test.",
        "style_id": "anime_standard",
        "settings": {
            "aspect_ratio": "9:16",
            "global_style": "test",
            "planner": "test",
            "scene_count": 1,
            "keyframe_provider": "local",
            "video_provider": video_provider,
            "voice_provider": "silent",
            "subtitle_style": {"burn_in": False},
            "audio_style": {},
            "episode_pacing": {},
        },
        "characters": [],
        "scenes": [scene],
        "runtime": {"status": "idle", "progress": 0, "stage": "draft", "message": ""},
        "output": {"final_video_path": "", "final_video_url": "", "status": "idle"},
    }


@pytest.fixture()
def provider_project(tmp_path, monkeypatch):
    import backend.project_models as project_models
    import backend.project_runtime as project_runtime

    workspace = tmp_path / "workspace"
    monkeypatch.setattr(project_models, "WORKSPACE", workspace)
    monkeypatch.setattr(project_runtime, "WORKSPACE", workspace)

    def create(project_id: str = "provider_project", *, video_provider: str = "doubao", legacy: bool = False) -> dict:
        project_root = workspace / project_id
        scene_root = project_root / "scenes" / "scene_001"
        (project_root / "characters").mkdir(parents=True, exist_ok=True)
        scene_root.mkdir(parents=True, exist_ok=True)
        (project_root / "output").mkdir(parents=True, exist_ok=True)
        (scene_root / "image_v1.png").write_bytes(PNG_1X1)
        payload = _minimal_project_payload(project_id, video_provider=video_provider, legacy=legacy)
        (project_root / "project.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"project_id": project_id, "workspace": workspace, "project_root": project_root}

    return create


@pytest.fixture()
def patched_render_runtime(monkeypatch):
    import backend.scene_renderer as scene_renderer
    import scripts.run_workflow as run_workflow

    monkeypatch.setattr(scene_renderer, "load_env_file", lambda: None)
    monkeypatch.setattr(scene_renderer, "get_ffmpeg_exe", lambda: "ffmpeg")
    monkeypatch.setattr(scene_renderer, "wav_duration", lambda path: 4.0)

    def fake_voice_track(ffmpeg, scene_obj, directory, voice_provider, **kwargs):
        path = Path(directory) / "voice_source.wav"
        path.write_bytes(b"fake wav")
        return path, 4.0

    monkeypatch.setattr(scene_renderer, "render_voice_track", fake_voice_track)
    monkeypatch.setattr(run_workflow.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(run_workflow, "mix_voice_with_bgm", lambda ffmpeg, voice_path, out_path, duration, style, project_root=None: voice_path)
    monkeypatch.setattr(run_workflow, "mix_scene_sfx", lambda ffmpeg, scene_audio, scene, run_dir, clip_duration, project_root=None: scene_audio)
    monkeypatch.setattr(run_workflow, "build_scene_video_prompts", lambda scene, duration, run_dir: ("positive prompt", "negative prompt"))
    monkeypatch.setattr(run_workflow, "mux_audio_to_visual", lambda ffmpeg, visual_path, voice_path, out_path: out_path.write_bytes(b"muxed") or out_path)
    monkeypatch.setattr(run_workflow, "apply_scene_grade", lambda ffmpeg, input_path, out_path, scene: out_path.write_bytes(b"graded") or out_path)
    monkeypatch.setattr(
        run_workflow,
        "build_scene_beats",
        lambda scene, total_duration, spoken_text: [
            {
                "duration": float(total_duration),
                "zoom": 1.0,
                "center_x": 0.5,
                "center_y": 0.5,
                "hold_in_ratio": 0.0,
                "hold_out_ratio": 0.0,
            }
        ],
    )
    monkeypatch.setattr(run_workflow, "scene_should_screen_shake", lambda scene: False)

    def fake_compose(base_image, scene, beat, run_dir, scene_id, idx, total):
        frame = Path(run_dir) / f"frame_{idx}.png"
        frame.write_bytes(PNG_1X1)
        return frame

    def fake_segment(ffmpeg, frame_path, duration, segment_path, *args, **kwargs):
        segment_path.write_bytes(b"segment")
        return segment_path

    def fake_concat(ffmpeg, beat_segments, visual_path, run_dir, **kwargs):
        visual_path.write_bytes(b"fallback visual")
        return visual_path

    monkeypatch.setattr(run_workflow, "compose_comic_frame", fake_compose)
    monkeypatch.setattr(run_workflow, "render_silent_visual_segment", fake_segment)
    monkeypatch.setattr(run_workflow, "concat_video_segments", fake_concat)
    try:
        import backend.consistency_validator as consistency_validator

        monkeypatch.setattr(consistency_validator, "CONSISTENCY_VALIDATION_ENABLED", False)
    except Exception:
        pass

    return run_workflow


def test_build_shot_plan_uses_temporal_spec_and_covers_duration():
    scene = {
        "scene_id": "scene_001",
        "order": 1,
        "duration_seconds": 4.0,
        "camera_movement": "slow_push",
        "speaker": "Lead",
        "dialogue": "Hello",
        "temporal_spec": {
            "shots": [
                {
                    "beat_type": "establish",
                    "duration_seconds": 1.0,
                    "camera_movement": "pan",
                    "center_x": 0.4,
                },
                {
                    "beat_type": "reaction",
                    "duration_seconds": 3.0,
                    "camera_movement": "push",
                    "center_y": 0.6,
                },
            ]
        },
    }

    plan = build_shot_plan(scene)

    assert plan["version"] == 1
    assert plan["scene_id"] == "scene_001"
    assert plan["source"] == "temporal_spec"
    assert plan["shot_count"] == 2
    assert [shot["shot_order"] for shot in plan["shots"]] == [1, 2]
    assert [shot["start_seconds"] for shot in plan["shots"]] == [0.0, 1.0]
    assert [shot["end_seconds"] for shot in plan["shots"]] == [1.0, 4.0]
    assert round(sum(shot["duration_seconds"] for shot in plan["shots"]), 3) == 4.0
    assert plan["shots"][0]["camera_movement"] == "pan"
    assert plan["shots"][1]["speaker"] == "Lead"


def test_build_shot_plan_synthesizes_full_duration_when_no_shots():
    plan = build_shot_plan(
        {
            "scene_id": "scene_002",
            "order": 2,
            "duration_seconds": 5.5,
            "camera_movement": "locked",
            "temporal_spec": {"shots": []},
        }
    )

    assert plan["source"] == "synthesized"
    assert plan["shot_count"] == 1
    assert plan["shots"][0]["start_seconds"] == 0.0
    assert plan["shots"][0]["duration_seconds"] == 5.5
    assert plan["shots"][0]["end_seconds"] == 5.5


def test_generation_meta_from_result_sanitizes_errors_and_records_policy():
    result = VideoGenerationResult(
        scene_order=1,
        provider_id="doubao",
        provider_label="Doubao",
        success=True,
        is_real_video=False,
        attempts=3,
        duration_seconds=4.0,
        output_path="clip.mp4",
        error="POST https://example.test/render?token=secret failed api_key=abc123",
        warnings=["provider failed with bearer token=hidden"],
        backend="local",
        fallback_used=True,
    )

    meta = generation_meta_from_result(result, requested_provider="auto", fallback_mode="report")

    assert meta["provider_id"] == "doubao"
    assert meta["requested_provider"] == "auto"
    assert meta["backend"] == "local"
    assert meta["is_real_video"] is False
    assert meta["fallback_used"] is True
    assert meta["attempts"] == 3
    assert meta["fallback_mode"] == "report"
    assert "?token=" not in meta["error"]
    assert "abc123" not in meta["error"]
    assert meta["generated_at"].endswith("Z")


def test_generation_meta_error_redacts_authorization_bearer_and_query_values():
    result = VideoGenerationResult(
        scene_order=1,
        provider_id="seedance",
        provider_label="Seedance",
        success=True,
        is_real_video=False,
        attempts=2,
        duration_seconds=4.0,
        output_path="clip.mp4",
        error=(
            "GET https://api.example.test/render?token=url-secret&api_key=url-key failed "
            "api_key=inline-key token=inline-token Authorization: Bearer header-secret "
            "bearer=bearer-secret authorization=auth-secret secret=raw-secret"
        ),
        warnings=[
            "retry used bearer=warning-secret and Authorization: Bearer warning-header-secret",
        ],
        backend="local",
        fallback_used=True,
    )

    meta = generation_meta_from_result(result, requested_provider="seedance", fallback_mode="report")
    serialized = json.dumps(meta, ensure_ascii=False)

    assert "https://api.example.test/render?" not in meta["error"]
    assert "https://api.example.test/render" in meta["error"]
    assert "url-secret" not in serialized
    assert "url-key" not in serialized
    assert "inline-key" not in serialized
    assert "inline-token" not in serialized
    assert "header-secret" not in serialized
    assert "bearer-secret" not in serialized
    assert "auth-secret" not in serialized
    assert "raw-secret" not in serialized
    assert "warning-secret" not in serialized
    assert "warning-header-secret" not in serialized
    assert "<redacted>" in serialized


def test_normalize_generation_meta_adds_v1_version_and_sanitizes_values():
    meta = normalize_generation_meta(
        {
            "provider_id": "doubao",
            "provider_label": "Doubao",
            "backend": "remote",
            "attempts": "2",
            "duration_seconds": "4.5",
            "is_real_video": 1,
            "fallback_used": 0,
            "error": "GET https://api.example.test/render?token=secret api_key=inline-secret",
            "warnings": ["Authorization: Bearer warning-secret"],
        }
    )
    serialized = json.dumps(meta, ensure_ascii=False)

    assert meta["version"] == 1
    assert meta["attempts"] == 2
    assert meta["duration_seconds"] == 4.5
    assert meta["is_real_video"] is True
    assert meta["fallback_used"] is False
    assert "secret" not in serialized
    assert "<redacted>" in serialized


def test_normalize_generation_meta_preserves_v2_shot_outputs_and_counts():
    meta = normalize_generation_meta(
        {
            "version": 2,
            "provider_id": "xl",
            "render_granularity": "shot",
            "real_video_shot_count": "bad",
            "fallback_shot_count": None,
            "failed_shot_count": -1,
            "total_provider_attempts": "",
            "shot_outputs": [
                {
                    "shot_id": "scene_001_shot_001",
                    "index": "1",
                    "status": "real_video",
                    "provider_id": "xl",
                    "model": "happyhorse-1.0-i2v",
                    "path": "scenes/scene_001/shots/shot_001.mp4?token=secret",
                    "duration_seconds": "2.0",
                    "target_duration_seconds": "2",
                    "attempts": "1",
                    "fallback_used": False,
                    "warnings": [],
                },
                {
                    "shot_id": "scene_001_shot_002",
                    "status": "fallback",
                    "attempts": "3",
                    "fallback_used": True,
                    "error": "provider failed token=shot-secret",
                    "warnings": ["retry api_key=warning-secret"],
                },
                "not-a-shot-output",
            ],
        }
    )
    serialized = json.dumps(meta, ensure_ascii=False)

    assert meta["version"] == 2
    assert meta["render_granularity"] == "shot"
    assert len(meta["shot_outputs"]) == 2
    assert meta["shot_outputs"][0]["index"] == 1
    assert meta["shot_outputs"][0]["duration_seconds"] == 2.0
    assert meta["shot_outputs"][1]["index"] == 2
    assert meta["real_video_shot_count"] == 1
    assert meta["fallback_shot_count"] == 1
    assert meta["failed_shot_count"] == 0
    assert meta["total_provider_attempts"] == 4
    assert "shot-secret" not in serialized
    assert "warning-secret" not in serialized
    assert "token=secret" not in serialized


def test_build_shot_output_sanitizes_and_stabilizes_record():
    output = build_shot_output(
        shot_id="scene_001_shot_001",
        index=1,
        status="REAL_VIDEO",
        provider_id="xl",
        provider_label="XL Aggregator",
        backend="remote",
        model="happyhorse-1.0-i2v",
        path="scenes/scene_001/shot_001.mp4?token=secret",
        duration_seconds=2.5,
        target_duration_seconds=2.0,
        attempts=1,
        fallback_used=False,
        warnings=["Authorization: Bearer warning-secret"],
        error="provider url https://api.example.test/render?api_key=secret",
        cache_key="sha256:test",
    )
    serialized = json.dumps(output, ensure_ascii=False)

    assert output["status"] == "real_video"
    assert output["duration_seconds"] == 2.5
    assert output["target_duration_seconds"] == 2.0
    assert output["attempts"] == 1
    assert "secret" not in serialized
    assert "<redacted>" in serialized


def test_generation_meta_from_shot_outputs_aggregates_counts_and_sanitizes():
    shot_outputs = [
        build_shot_output(
            shot_id="scene_001_shot_001",
            index=1,
            status="real_video",
            provider_id="xl",
            provider_label="XL Aggregator",
            backend="remote",
            path="scenes/scene_001/shot_001.mp4",
            duration_seconds=2.0,
            target_duration_seconds=2.0,
            attempts=1,
        ),
        build_shot_output(
            shot_id="scene_001_shot_002",
            index=2,
            status="fallback",
            provider_id="xl",
            provider_label="XL Aggregator",
            backend="local",
            path="scenes/scene_001/shot_002.mp4",
            duration_seconds=2.0,
            target_duration_seconds=2.0,
            attempts=3,
            fallback_used=True,
            error="provider failed token=shot-secret",
        ),
        {"shot_id": "scene_001_shot_003", "index": 3, "status": "failed", "attempts": 2, "error": "api_key=failed-secret"},
    ]

    meta = generation_meta_from_shot_outputs(
        shot_outputs,
        requested_provider="xl",
        fallback_mode="report",
        duration_seconds=6.0,
    )
    serialized = json.dumps(meta, ensure_ascii=False)

    assert meta["version"] == 2
    assert meta["render_granularity"] == "shot"
    assert meta["is_real_video"] is False
    assert meta["fallback_used"] is True
    assert meta["real_video_shot_count"] == 1
    assert meta["fallback_shot_count"] == 1
    assert meta["failed_shot_count"] == 1
    assert meta["total_provider_attempts"] == 6
    assert meta["attempts"] == 6
    assert len(meta["shot_outputs"]) == 3
    assert "shot-secret" not in serialized
    assert "failed-secret" not in serialized


def test_build_shot_assembly_manifest_accumulates_children():
    outputs = [
        build_shot_output(
            shot_id="scene_001_shot_001",
            index=1,
            status="real_video",
            path="scenes/scene_001/shot_001.mp4",
            duration_seconds=1.25,
            target_duration_seconds=1.25,
        ),
        build_shot_output(
            shot_id="scene_001_shot_002",
            index=2,
            status="fallback",
            path="scenes/scene_001/shot_002.mp4?token=secret",
            duration_seconds=2.5,
            target_duration_seconds=2.5,
            fallback_used=True,
        ),
        {"not": "normalized"},
    ]

    manifest = build_shot_assembly_manifest(
        scene_id="scene_001",
        output_path="scenes/scene_001/video_v2.mp4?token=secret",
        shot_outputs=outputs,
    )
    serialized = json.dumps(manifest, ensure_ascii=False)

    assert manifest["version"] == 1
    assert manifest["render_granularity"] == "shot"
    assert manifest["duration_seconds"] == 3.75
    assert len(manifest["children"]) == 3
    assert manifest["children"][0]["start_seconds"] == 0.0
    assert manifest["children"][1]["start_seconds"] == 1.25
    assert manifest["children"][2]["status"] == "unknown"
    assert "token=secret" not in serialized


def test_video_fallback_mode_honors_provider_specific_strict(monkeypatch):
    monkeypatch.setenv("VIDEO_FALLBACK_MODE", "report")
    monkeypatch.delenv("VIDEO_STRICT", raising=False)
    monkeypatch.setenv("DOUBAO_VIDEO_STRICT", "1")

    assert video_fallback_mode("doubao") == "strict"
    assert video_fallback_mode("seedance") == "report"


def test_video_render_granularity_resolves_precedence(monkeypatch):
    monkeypatch.setenv("VIDEO_RENDER_GRANULARITY", "shot")

    assert video_render_granularity() == "shot"
    assert video_render_granularity(project_settings={"video_render_granularity": "scene"}) == "scene"
    assert video_render_granularity(
        request_value="shot",
        project_settings={"video_render_granularity": "scene"},
    ) == "shot"
    assert video_render_granularity(
        cli_value="scene",
        request_value="shot",
        project_settings={"video_render_granularity": "shot"},
    ) == "scene"
    assert video_render_granularity(cli_value="bad-value") == "scene"


def test_video_shot_quota_config_resolves_request_project_and_env(monkeypatch):
    monkeypatch.setenv("VIDEO_SHOT_MAX_CALLS", "8")
    monkeypatch.setenv("VIDEO_SHOT_MAX_SECONDS", "12.5")
    monkeypatch.setenv("VIDEO_SHOT_DRY_RUN", "1")
    monkeypatch.setenv("VIDEO_SHOT_REUSE_CACHE", "0")

    env_config = video_shot_quota_config()
    assert env_config == {
        "max_calls": 8,
        "max_seconds": 12.5,
        "dry_run": True,
        "reuse_cache": False,
    }

    project_config = video_shot_quota_config(
        project_settings={
            "video_shot_max_calls": "4",
            "video_shot_max_seconds": "6",
            "video_shot_dry_run": False,
            "video_shot_reuse_cache": True,
        }
    )
    assert project_config["max_calls"] == 4
    assert project_config["max_seconds"] == 6.0
    assert project_config["dry_run"] is False
    assert project_config["reuse_cache"] is True

    request_config = video_shot_quota_config(
        request_values={"video_shot_max_calls": 2},
        project_settings={"video_shot_max_calls": 4},
    )
    assert request_config["max_calls"] == 2


def test_estimate_shot_render_quota_counts_calls_seconds_and_cache_reuse():
    shot_plan = {
        "shots": [
            {"shot_id": "shot_a", "duration_seconds": 1.5},
            {"shot_id": "shot_b", "duration_seconds": 2.0},
            {"shot_id": "shot_c", "duration_seconds": 0.5},
        ]
    }
    existing = [
        build_shot_output(
            shot_id="shot_b",
            index=2,
            status="real_video",
            path="scenes/scene_001/shot_b.mp4",
            duration_seconds=2.0,
        )
    ]

    no_reuse = estimate_shot_render_quota(shot_plan, existing_shot_outputs=existing, reuse_cache=False)
    assert no_reuse["shot_count"] == 3
    assert no_reuse["provider_call_count"] == 3
    assert no_reuse["generated_seconds"] == 4.0
    assert no_reuse["reused_shot_count"] == 0

    reused = estimate_shot_render_quota(shot_plan, existing_shot_outputs=existing, reuse_cache=True)
    assert reused["shot_count"] == 3
    assert reused["provider_call_count"] == 2
    assert reused["generated_seconds"] == 2.0
    assert reused["target_seconds"] == 4.0
    assert reused["reused_shot_count"] == 1
    assert [item["shot_id"] for item in reused["planned_shots"]] == ["shot_a", "shot_c"]


def test_validate_shot_render_quota_blocks_over_limit_before_submit():
    estimate = {
        "provider_call_count": 3,
        "generated_seconds": 7.5,
        "planned_shots": [],
    }

    with pytest.raises(VideoShotQuotaError) as exc_info:
        validate_shot_render_quota(estimate, max_calls=2, max_seconds=5.0, dry_run=False)

    detail = exc_info.value.detail
    assert detail["ok"] is False
    assert detail["dry_run"] is False
    assert len(detail["errors"]) == 2
    assert "VIDEO_SHOT_MAX_CALLS=2" in detail["errors"][0]
    assert "VIDEO_SHOT_MAX_SECONDS=5" in detail["errors"][1]

    dry_run_result = validate_shot_render_quota(
        estimate,
        max_calls=2,
        max_seconds=5.0,
        dry_run=True,
        raise_on_error=False,
    )
    assert dry_run_result["ok"] is False
    assert dry_run_result["dry_run"] is True


def test_build_shot_provider_request_inputs_preserves_shot_context_and_video_model(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4pro-should-not-leak")
    monkeypatch.setenv("DOUBAO_MODEL", "doubao-video-env-model")

    scene = {
        "scene_id": "scene_001",
        "order": 1,
        "title": "Ticket Counter",
        "visual_prompt": "Fallback scene visual should be secondary.",
        "dialogue": "Lead: Hold the line.",
        "speaker": "Lead",
        "characters": ["Lead", "Clerk"],
        "camera_movement": "slow_push",
        "emotion_tone": "tension",
        "scene_intent": "action",
        "subject_focus": "prop",
        "duration_seconds": 4.0,
        "video_provider": "xl",
        "production_bible": {
            "current_scene": {
                "location": "ticket booth",
                "active_characters": [
                    {"name": "Lead", "appearance_core": "blue coat", "clothing_style": "wet sleeves"}
                ],
            },
            "rules": {"preserve_character_identity": True, "keep_lighting_continuous_within_scene": True},
        },
    }
    shot_plan = {
        "scene_id": "scene_001",
        "scene_order": 1,
        "shots": [
            {
                "shot_id": "scene_001_shot_01",
                "shot_order": 1,
                "label": "detonator insert",
                "beat_type": "detail",
                "start_seconds": 0.0,
                "duration_seconds": 1.5,
                "end_seconds": 1.5,
                "camera_movement": "locked_insert",
                "visual_content": {
                    "_source": "prototype",
                    "shot_description": "extreme close-up of a red detonator light",
                    "foreground": "thumb hovering over the trigger",
                    "background": "ticket booth glass",
                    "motion": "tiny hand tremor",
                },
                "camera_language": {
                    "movement": "locked-off frame with small pressure push",
                    "lens": "macro telephoto",
                    "depth_of_field": "shallow",
                    "framing": "prop dominates frame",
                },
                "dramatic_intent": "hold on the decision object",
            },
            {
                "shot_id": "scene_001_shot_02",
                "shot_order": 2,
                "label": "lead reaction",
                "start_seconds": 1.5,
                "duration_seconds": 2.5,
                "end_seconds": 4.0,
                "video_provider": "doubao",
                "video_provider_model": "shot-specific-video-model",
                "visual_content": {"shot_description": "Lead looks up from the trigger"},
            },
        ],
    }

    requests = build_shot_provider_request_inputs(
        scene,
        shot_plan,
        provider_id="local",
        project_settings={"video_provider": "xl", "video_provider_model": "project-video-model"},
        width=720,
        height=1280,
        fps=24,
    )

    assert len(requests) == 2
    first = requests[0]
    assert first["shot_id"] == "scene_001_shot_01"
    assert first["duration_seconds"] == 1.5
    assert first["provider"]["provider_id"] == "xl"
    assert first["provider"]["model"] == "project-video-model"
    assert first["provider"]["model_source"] == "project:video_provider_model"
    assert "deepseek-v4pro-should-not-leak" not in json.dumps(first, ensure_ascii=False)
    assert "visual_content is the primary visual source" in first["prompt"]
    assert "extreme close-up of a red detonator light" in first["prompt"]
    assert first["camera"]["camera_movement"] == "locked_insert"
    assert first["camera"]["language"]["lens"] == "macro telephoto"
    assert first["intent"]["dramatic_intent"] == "hold on the decision object"
    assert first["continuity"]["location"] == "ticket booth"
    assert first["continuity"]["next_shot"]["shot_id"] == "scene_001_shot_02"
    assert first["temporal_spec"]["kind"] == "shot_temporal_spec"
    assert first["consistency_spec"]["kind"] == "shot_consistency_spec"

    second = requests[1]
    assert second["provider"]["provider_id"] == "doubao"
    assert second["provider"]["model"] == "shot-specific-video-model"
    assert second["provider"]["model_source"] == "shot:video_provider_model"
    assert second["continuity"]["previous_shot"]["shot_id"] == "scene_001_shot_01"
    assert second["width"] == 720
    assert second["height"] == 1280


def test_build_shot_provider_request_inputs_uses_video_provider_env_model_not_llm(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "kimi-k2.7-planning")
    monkeypatch.setenv("DOUBAO_MODEL", "doubao-video-env-model")

    requests = build_shot_provider_request_inputs(
        {
            "scene_id": "scene_009",
            "order": 9,
            "title": "Env Model",
            "characters": [],
            "duration_seconds": 2.0,
        },
        {
            "scene_id": "scene_009",
            "shots": [{"shot_id": "scene_009_shot_01", "duration_seconds": 2.0}],
        },
        provider_id="doubao",
    )

    assert requests[0]["provider"]["model"] == "doubao-video-env-model"
    assert requests[0]["provider"]["model_source"] == "env:DOUBAO_MODEL"
    assert "kimi-k2.7-planning" not in json.dumps(requests[0], ensure_ascii=False)


def test_build_shot_cache_key_is_stable_and_tracks_render_inputs(monkeypatch):
    monkeypatch.setenv("DOUBAO_MODEL", "doubao-cache-model")
    scene = {
        "scene_id": "scene_001",
        "order": 1,
        "title": "Cache",
        "visual_prompt": "A stable frame.",
        "duration_seconds": 2.0,
        "camera_movement": "static",
    }
    shot_plan = {
        "scene_id": "scene_001",
        "shots": [
            {
                "shot_id": "scene_001_shot_01",
                "duration_seconds": 2.0,
                "visual_content": {"shot_description": "Lead looks up."},
            }
        ],
    }
    request = build_shot_provider_request_inputs(scene, shot_plan, provider_id="doubao")[0]

    key = build_shot_cache_key(request, "scene_001/image_v1.png")
    assert key.startswith("sha256:")
    assert key == build_shot_cache_key(json.loads(json.dumps(request)), "scene_001/image_v1.png")

    prompt_changed = json.loads(json.dumps(request))
    prompt_changed["prompt"] += "\nextra direction"
    assert build_shot_cache_key(prompt_changed, "scene_001/image_v1.png") != key

    model_changed = json.loads(json.dumps(request))
    model_changed["provider"]["model"] = "different-video-model"
    assert build_shot_cache_key(model_changed, "scene_001/image_v1.png") != key


def test_render_shot_with_provider_policy_returns_real_video_output(tmp_path, monkeypatch):
    import backend.video_generation as video_generation

    request = build_shot_provider_request_inputs(
        {"scene_id": "scene_001", "order": 1, "title": "Shot Render", "characters": ["Lead"]},
        {"scene_id": "scene_001", "shots": [{"shot_id": "scene_001_shot_01", "duration_seconds": 1.25}]},
        provider_id="doubao",
    )[0]
    request["provider"]["model"] = "public-video-model"
    keyframe_path = tmp_path / "keyframe.png"
    keyframe_path.write_bytes(PNG_1X1)
    output_path = tmp_path / "shot_01.mp4"
    calls: list[str] = []

    def fake_remote_success(remote_request, provider_spec, **kwargs):
        calls.append(remote_request.prompt)
        remote_request.out_path.write_bytes(b"remote shot")
        return remote_request.out_path

    monkeypatch.setenv("VIDEO_FALLBACK_MODE", "report")
    monkeypatch.setattr(video_generation, "render_remote_video_provider", fake_remote_success, raising=False)
    monkeypatch.setattr("scripts.video_provider_adapters.render_remote_video_provider", fake_remote_success)

    output = render_shot_with_provider_policy(
        request,
        keyframe_path,
        output_path,
        tmp_path,
        video_provider="doubao",
        max_retries=1,
        retry_delay=0,
    )

    assert len(calls) == 1
    assert output["status"] == "real_video"
    assert output["provider_id"] == "doubao"
    assert output["backend"] == "remote"
    assert output["model"] == "public-video-model"
    assert output["path"] == str(output_path)
    assert output["attempts"] == 1
    assert output["fallback_used"] is False
    assert output["cache_key"] == build_shot_cache_key(request, keyframe_path)


def test_render_shot_with_provider_policy_report_failure_uses_fallback(tmp_path, monkeypatch):
    import backend.video_generation as video_generation

    request = build_shot_provider_request_inputs(
        {"scene_id": "scene_001", "order": 1, "title": "Shot Fallback"},
        {"scene_id": "scene_001", "shots": [{"shot_id": "scene_001_shot_01", "duration_seconds": 2.0}]},
        provider_id="doubao",
    )[0]
    keyframe_path = tmp_path / "keyframe.png"
    keyframe_path.write_bytes(PNG_1X1)
    output_path = tmp_path / "shot_01.mp4"
    attempts: list[int] = []

    def fake_remote_failure(remote_request, provider_spec, **kwargs):
        attempts.append(remote_request.scene)
        raise RuntimeError("shot failed token=shot-secret")

    def fake_fallback(shot_request, fallback_output_path):
        fallback_output_path.write_bytes(b"fallback shot")
        return fallback_output_path

    monkeypatch.setenv("VIDEO_FALLBACK_MODE", "report")
    monkeypatch.setattr(video_generation.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(video_generation, "render_remote_video_provider", fake_remote_failure, raising=False)
    monkeypatch.setattr("scripts.video_provider_adapters.render_remote_video_provider", fake_remote_failure)

    output = render_shot_with_provider_policy(
        request,
        keyframe_path,
        output_path,
        tmp_path,
        video_provider="doubao",
        fallback_renderer=fake_fallback,
        max_retries=1,
        retry_delay=0,
    )

    assert len(attempts) == 2
    assert output["status"] == "fallback"
    assert output["backend"] == "local"
    assert output["fallback_used"] is True
    assert output["attempts"] == 2
    assert output["warnings"]
    assert "shot-secret" not in output["error"]
    assert output_path.read_bytes() == b"fallback shot"


def test_render_shot_with_provider_policy_strict_failure_raises(tmp_path, monkeypatch):
    import backend.video_generation as video_generation

    request = build_shot_provider_request_inputs(
        {"scene_id": "scene_001", "order": 1, "title": "Strict Shot"},
        {"scene_id": "scene_001", "shots": [{"shot_id": "scene_001_shot_01", "duration_seconds": 1.0}]},
        provider_id="doubao",
    )[0]
    keyframe_path = tmp_path / "keyframe.png"
    keyframe_path.write_bytes(PNG_1X1)

    def fake_remote_failure(remote_request, provider_spec, **kwargs):
        raise RuntimeError("strict shot failed token=strict-shot-secret")

    monkeypatch.setenv("VIDEO_FALLBACK_MODE", "strict")
    monkeypatch.delenv("VIDEO_STRICT", raising=False)
    monkeypatch.setattr(video_generation, "render_remote_video_provider", fake_remote_failure, raising=False)
    monkeypatch.setattr("scripts.video_provider_adapters.render_remote_video_provider", fake_remote_failure)

    with pytest.raises(RuntimeError) as exc_info:
        render_shot_with_provider_policy(
            request,
            keyframe_path,
            tmp_path / "shot_01.mp4",
            tmp_path,
            video_provider="doubao",
            max_retries=0,
            retry_delay=0,
        )

    assert "strict shot failed" in str(exc_info.value)
    assert "strict-shot-secret" not in str(exc_info.value)


def test_assemble_shot_clips_uses_hard_cut_concat_and_writes_manifest(tmp_path):
    shot_a = tmp_path / "shot_a.mp4"
    shot_b = tmp_path / "shot_b.mp4"
    shot_a.write_bytes(b"a")
    shot_b.write_bytes(b"b")
    output_path = tmp_path / "scene_001.mp4"
    manifest_path = tmp_path / "scene_001_shot_manifest.json"
    commands: list[dict[str, object]] = []

    def fake_run_guarded(cmd, **kwargs):
        commands.append({"cmd": cmd, **kwargs})
        Path(cmd[-1]).write_bytes(b"assembled")

    output, manifest = assemble_shot_clips(
        ffmpeg="ffmpeg",
        shot_outputs=[
            build_shot_output(
                shot_id="scene_001_shot_01",
                index=1,
                status="real_video",
                path=str(shot_a),
                duration_seconds=1.0,
            ),
            build_shot_output(
                shot_id="scene_001_shot_02",
                index=2,
                status="failed",
                path=str(tmp_path / "failed.mp4"),
                duration_seconds=0.5,
                error="provider failed",
            ),
            build_shot_output(
                shot_id="scene_001_shot_03",
                index=3,
                status="fallback",
                path=str(shot_b),
                duration_seconds=2.0,
            ),
        ],
        output_path=output_path,
        run_dir=tmp_path,
        scene_id="scene_001",
        run_guarded=fake_run_guarded,
        manifest_path=manifest_path,
    )

    assert output == output_path
    assert output_path.read_bytes() == b"assembled"
    assert len(commands) == 1
    assert commands[0]["cmd"][:5] == ["ffmpeg", "-y", "-f", "concat", "-safe"]
    concat_text = (tmp_path / "scene_001_shot_concat.txt").read_text(encoding="utf-8")
    assert str(shot_a).replace("\\", "/") in concat_text
    assert str(shot_b).replace("\\", "/") in concat_text
    assert "failed.mp4" not in concat_text
    assert manifest["render_granularity"] == "shot"
    assert manifest["duration_seconds"] == 3.0
    assert [child["shot_id"] for child in manifest["children"]] == ["scene_001_shot_01", "scene_001_shot_03"]
    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert persisted == manifest


def test_assemble_shot_clips_rejects_empty_usable_outputs(tmp_path):
    with pytest.raises(ValueError, match="No usable shot clips"):
        assemble_shot_clips(
            ffmpeg="ffmpeg",
            shot_outputs=[{"shot_id": "bad", "status": "failed", "path": ""}],
            output_path=tmp_path / "scene.mp4",
            run_dir=tmp_path,
            run_guarded=lambda *args, **kwargs: None,
        )


def test_create_project_persists_video_render_granularity(tmp_path, monkeypatch):
    import backend.project_models as project_models
    import backend.project_runtime as project_runtime
    from scripts.run_workflow import StoryScene

    workspace = tmp_path / "workspace"
    monkeypatch.setattr(project_models, "WORKSPACE", workspace)
    monkeypatch.setattr(project_runtime, "WORKSPACE", workspace)
    monkeypatch.setattr(project_runtime, "sync_character_card_files", lambda project: None)
    monkeypatch.setattr(project_runtime, "cleanup_project_versions", lambda *args, **kwargs: None)
    monkeypatch.setattr(project_runtime, "build_initial_characters", lambda scenes: [])
    monkeypatch.setattr(
        project_runtime,
        "build_storyboard",
        lambda story, planner, scene_count: (
            [
                StoryScene(
                    scene=1,
                    duration=4.0,
                    title="Scene",
                    visual="Visual",
                    dialogue="Lead: line",
                    camera="slow_push",
                    emotion="neutral",
                    characters=["Lead"],
                    bg_color="0x182033",
                    accent_color="0x4ea3ff",
                )
            ],
            "rule",
        ),
    )

    project = project_runtime.create_project(
        title="Granularity",
        story_text="Story",
        planner="rule",
        scene_count=1,
        keyframe_provider="local",
        video_provider="local",
        voice_provider="silent",
        video_render_granularity_value="shot",
    )

    assert project["settings"]["video_render_granularity"] == "shot"


def test_configured_cors_origins_default_and_env(monkeypatch):
    import backend.app as backend_app

    monkeypatch.delenv("APP_CORS_ORIGINS", raising=False)
    assert backend_app.configured_cors_origins() == [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]

    monkeypatch.setenv("APP_CORS_ORIGINS", "http://studio.local:3000, https://example.test ")
    assert backend_app.configured_cors_origins() == [
        "http://studio.local:3000",
        "https://example.test",
    ]


def test_video_provider_status_reports_blocking_readiness(monkeypatch):
    from video_providers import get_video_provider_status

    env_names = [
        "DOUBAO_API_KEY",
        "DOUBAO_MODEL",
        "DOUBAO_BASE_URL",
        "DOUBAO_SUBMIT_URL",
        "DOUBAO_POLL_URL",
        "DOUBAO_TIMEOUT_SECONDS",
        "DOUBAO_POLL_INTERVAL_SECONDS",
    ]
    for name in env_names:
        monkeypatch.delenv(name, raising=False)

    local_status = get_video_provider_status("local")
    assert local_status["readiness"]["ready"] is True
    assert local_status["readiness"]["blocking_env"] == []

    missing_status = get_video_provider_status("doubao")
    assert missing_status["readiness"]["ready"] is False
    assert "DOUBAO_API_KEY" in missing_status["readiness"]["blocking_env"]
    assert "DOUBAO_MODEL" in missing_status["readiness"]["blocking_env"]
    assert "DOUBAO_BASE_URL or DOUBAO_SUBMIT_URL or DOUBAO_SUBMIT_PATH" in missing_status["readiness"]["blocking_env"]

    monkeypatch.setenv("DOUBAO_API_KEY", "secret")
    monkeypatch.setenv("DOUBAO_MODEL", "doubao-video")
    monkeypatch.setenv("DOUBAO_SUBMIT_URL", "https://example.test/videos")

    ready_status = get_video_provider_status("doubao")
    assert ready_status["readiness"]["ready"] is True
    assert ready_status["readiness"]["blocking_env"] == []
    assert "DOUBAO_POLL_URL" in ready_status["missing_env"]


def test_canonical_timeline_includes_generation_metadata_and_counts():
    project = {
        "project_id": "proj_test",
        "title": "Timeline Test",
        "settings": {},
        "scenes": [
            {
                "scene_id": "scene_001",
                "order": 1,
                "title": "Real",
                "duration_seconds": 4.0,
                "video_path": "scenes/scene_001/video.mp4",
                "generation_meta": {
                    "version": 2,
                    "is_real_video": True,
                    "fallback_used": False,
                    "provider_id": "doubao",
                    "render_granularity": "shot",
                    "shot_outputs": [
                        {
                            "shot_id": "scene_001_shot_01",
                            "index": 1,
                            "status": "real_video",
                            "provider_id": "doubao",
                            "backend": "remote",
                            "path": "scenes/scene_001/shots/scene_001_shot_01.mp4",
                            "attempts": 1,
                            "cache_key": "sha256:timeline",
                        }
                    ],
                },
                "temporal_spec": {"shots": [{"duration_seconds": 4.0, "beat_type": "full"}]},
            },
            {
                "scene_id": "scene_002",
                "order": 2,
                "title": "Fallback",
                "duration_seconds": 3.0,
                "image_path": "scenes/scene_002/keyframe.png",
                "generation_meta": {"is_real_video": False, "fallback_used": True, "provider_id": "doubao"},
            },
            {
                "scene_id": "scene_003",
                "order": 3,
                "title": "Unknown",
                "duration_seconds": 2.0,
                "image_path": "scenes/scene_003/keyframe.png",
            },
        ],
    }

    timeline = build_canonical_timeline(project)
    picture_items = timeline["tracks"][0]["children"]

    assert timeline["summary"]["real_video_scene_count"] == 1
    assert timeline["summary"]["fallback_scene_count"] == 1
    assert picture_items[0]["metadata"]["generation"]["is_real_video"] is True
    assert picture_items[1]["metadata"]["generation"]["fallback_used"] is True
    assert picture_items[2]["metadata"]["generation"] == {}
    assert picture_items[0]["metadata"]["shot_plan_source"] == "temporal_spec"
    assert picture_items[1]["metadata"]["shot_plan_source"] == "synthesized"
    assert picture_items[0]["shot_timeline"][0]["generation"]["status"] == "real_video"
    assert picture_items[0]["shot_timeline"][0]["generation"]["provider_id"] == "doubao"
    assert picture_items[0]["shot_timeline"][0]["generation"]["cache_key"] == "sha256:timeline"
    assert "generation" not in picture_items[1]["shot_timeline"][0]


def test_load_project_normalizes_legacy_generation_fields(tmp_path, monkeypatch):
    import backend.project_models as project_models
    import backend.project_runtime as project_runtime

    workspace = tmp_path / "workspace"
    project_id = "legacy_project"
    project_root = workspace / project_id
    project_root.mkdir(parents=True)
    (project_root / "characters").mkdir()
    (project_root / "scenes").mkdir()
    (project_root / "output").mkdir()
    payload = {
        "project_id": project_id,
        "title": "Legacy",
        "characters": [],
        "scenes": [
            {
                "scene_id": "scene_001",
                "order": 1,
                "duration_seconds": 4.0,
                "temporal_spec": {},
                "assets": {},
            }
        ],
    }
    (project_root / "project.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(project_models, "WORKSPACE", workspace)
    monkeypatch.setattr(project_runtime, "WORKSPACE", workspace)

    project = project_runtime.load_project(project_id)
    scene = project["scenes"][0]

    assert scene["generation_meta"] == {}
    assert scene["shot_plan"]["source"] == "synthesized"
    assert scene["shot_plan"]["shots"][0]["duration_seconds"] == 4.0


def test_load_project_normalizes_generation_meta_v2(tmp_path, monkeypatch):
    import backend.project_models as project_models
    import backend.project_runtime as project_runtime

    workspace = tmp_path / "workspace"
    project_id = "generation_meta_v2_project"
    project_root = workspace / project_id
    project_root.mkdir(parents=True)
    (project_root / "characters").mkdir()
    (project_root / "scenes").mkdir()
    (project_root / "output").mkdir()
    payload = {
        "project_id": project_id,
        "title": "V2 Meta",
        "characters": [],
        "scenes": [
            {
                "scene_id": "scene_001",
                "order": 1,
                "duration_seconds": 4.0,
                "temporal_spec": {},
                "generation_meta": {
                    "version": 2,
                    "provider_id": "xl",
                    "render_granularity": "shot",
                    "shot_outputs": [
                        {
                            "shot_id": "scene_001_shot_001",
                            "status": "real_video",
                            "attempts": "1",
                            "error": "ok",
                        }
                    ],
                },
                "assets": {},
            }
        ],
    }
    (project_root / "project.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(project_models, "WORKSPACE", workspace)
    monkeypatch.setattr(project_runtime, "WORKSPACE", workspace)

    project = project_runtime.load_project(project_id)
    meta = project["scenes"][0]["generation_meta"]

    assert meta["version"] == 2
    assert meta["render_granularity"] == "shot"
    assert meta["real_video_shot_count"] == 1
    assert meta["total_provider_attempts"] == 1


def test_update_scene_generation_meta_keeps_unchanged_shot_plan(provider_project):
    import backend.project_runtime as project_runtime
    import backend.scene_renderer as scene_renderer

    created = provider_project("stable_shot_plan_project", video_provider="doubao")
    project = project_runtime.load_project(created["project_id"])
    scene = project["scenes"][0]
    original_plan = build_shot_plan(scene)
    sentinel_plan = json.loads(json.dumps(original_plan))

    scene_renderer.update_scene_generation_meta(
        created["project_id"],
        1,
        {"version": 1, "provider_id": "doubao"},
        sentinel_plan,
    )
    loaded = project_runtime.load_project(created["project_id"])
    assert loaded["scenes"][0]["shot_plan"] == original_plan

    changed_plan = json.loads(json.dumps(original_plan))
    changed_plan["source"] = "test_override"
    scene_renderer.update_scene_generation_meta(
        created["project_id"],
        1,
        {"version": 1, "provider_id": "doubao", "attempts": 2},
        changed_plan,
    )
    loaded_after_change = project_runtime.load_project(created["project_id"])
    assert loaded_after_change["scenes"][0]["shot_plan"]["source"] == "test_override"
    assert loaded_after_change["scenes"][0]["generation_meta"]["attempts"] == 2


def test_project_snapshot_exposes_compact_shot_render_status(provider_project):
    import backend.project_runtime as project_runtime

    created = provider_project("snapshot_shot_status_project", video_provider="doubao")
    project = project_runtime.load_project(created["project_id"])
    scene = project["scenes"][0]
    scene["generation_meta"] = generation_meta_from_shot_outputs(
        [
            build_shot_output(
                shot_id="scene_001_shot_01",
                index=1,
                status="real_video",
                provider_id="doubao",
                backend="remote",
                path="scenes/scene_001/shots/scene_001_shot_01.mp4",
                attempts=1,
                cache_key="sha256:snapshot",
            )
        ],
        requested_provider="doubao",
        fallback_mode="report",
        duration_seconds=4.0,
    )
    snapshot = project_runtime.project_snapshot(project)
    scene_graph_entry = snapshot["scene_graph"]["scenes"][0]

    assert scene_graph_entry["render_granularity"] == "shot"
    assert scene_graph_entry["shot_render_status"] == [
        {
            "shot_id": "scene_001_shot_01",
            "index": 1,
            "status": "real_video",
            "provider_id": "doubao",
            "backend": "remote",
            "fallback_used": False,
            "attempts": 1,
        }
    ]
    picture_item = snapshot["canonical_timeline"]["tracks"][0]["children"][0]
    assert picture_item["metadata"]["generation"]["render_granularity"] == "shot"
    assert picture_item["shot_timeline"][0]["generation"]["cache_key"] == "sha256:snapshot"


def test_mock_remote_success_persists_real_video_metadata(provider_project, patched_render_runtime, monkeypatch):
    import backend.project_runtime as project_runtime

    created = provider_project("remote_success_project", video_provider="doubao")
    calls: list[int] = []

    def fake_remote_success(request, provider_spec, **kwargs):
        calls.append(request.scene)
        request.out_path.write_bytes(b"remote visual")
        return request.out_path

    monkeypatch.setenv("VIDEO_FALLBACK_MODE", "report")
    monkeypatch.setenv("VIDEO_MAX_RETRIES", "1")
    monkeypatch.setenv("VIDEO_RETRY_DELAY_SECONDS", "0")
    monkeypatch.delenv("VIDEO_STRICT", raising=False)
    monkeypatch.setattr(patched_render_runtime, "render_remote_video_provider", fake_remote_success)

    result = project_runtime.rerender_scene_video(created["project_id"], 1)
    scene = result["scenes"][0]

    assert len(calls) == 1
    assert scene["assets"]["video_path"]
    assert scene["generation_meta"]["provider_id"] == "doubao"
    assert scene["generation_meta"]["backend"] == "remote"
    assert scene["generation_meta"]["is_real_video"] is True
    assert scene["generation_meta"]["fallback_used"] is False
    assert scene["generation_meta"]["attempts"] == 1
    assert scene["shot_plan"]["source"] == "temporal_spec"


def test_shot_granularity_rerender_orchestrates_shots_and_persists_metadata(provider_project, monkeypatch):
    import backend.project_runtime as project_runtime
    import backend.scene_renderer as scene_renderer
    import backend.video_generation as video_generation

    created = provider_project("shot_granularity_project", video_provider="doubao")
    project = project_runtime.load_project(created["project_id"])
    project["settings"]["video_render_granularity"] = "shot"
    scene = project["scenes"][0]
    scene["duration_seconds"] = 4.0
    scene["temporal_spec"] = {
        "shots": [
            {"shot_id": "scene_001_shot_01", "duration_seconds": 1.5, "camera_movement": "slow_push"},
            {"shot_id": "scene_001_shot_02", "duration_seconds": 2.5, "camera_movement": "static"},
        ]
    }
    (created["project_root"] / "project.json").write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    calls: list[str] = []
    commands: list[list[str]] = []

    monkeypatch.setattr(scene_renderer, "load_env_file", lambda: None)
    monkeypatch.setattr(scene_renderer, "get_ffmpeg_exe", lambda: "ffmpeg")
    monkeypatch.setattr(scene_renderer, "wav_duration", lambda path: 4.0)
    def fake_voice_track(*args, **kwargs):
        path = Path(args[2]) / "voice.wav"
        path.write_bytes(b"voice")
        return path, 4.0

    monkeypatch.setattr(scene_renderer, "render_voice_track", fake_voice_track)
    monkeypatch.setattr(scene_renderer, "_evaluate_and_persist_scene_governance", lambda *args, **kwargs: None)
    monkeypatch.setattr(scene_renderer, "render_silent_visual_segment", lambda *args, **kwargs: Path(args[3]).write_bytes(b"fallback") or Path(args[3]))

    def fake_remote_success(request, provider_spec, **kwargs):
        calls.append(request.out_path.name)
        request.out_path.parent.mkdir(parents=True, exist_ok=True)
        request.out_path.write_bytes(b"remote shot")
        return request.out_path

    def fake_run_guarded(cmd, **kwargs):
        commands.append(cmd)
        Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(cmd[-1]).write_bytes(b"assembled")

    monkeypatch.setenv("VIDEO_FALLBACK_MODE", "report")
    monkeypatch.setenv("VIDEO_MAX_RETRIES", "0")
    monkeypatch.setenv("VIDEO_RETRY_DELAY_SECONDS", "0")
    monkeypatch.delenv("VIDEO_STRICT", raising=False)
    monkeypatch.setattr(video_generation, "render_remote_video_provider", fake_remote_success)
    monkeypatch.setattr(scene_renderer, "run_guarded", fake_run_guarded)

    result = project_runtime.rerender_scene_video(created["project_id"], 1)
    scene = result["scenes"][0]
    meta = scene["generation_meta"]

    assert calls == ["scene_001_shot_01.mp4", "scene_001_shot_02.mp4"]
    assert any("concat" in cmd for command in commands for cmd in command)
    assert scene["assets"]["video_path"]
    assert meta["version"] == 2
    assert meta["render_granularity"] == "shot"
    assert meta["real_video_shot_count"] == 2
    assert meta["fallback_shot_count"] == 0
    assert meta["total_provider_attempts"] == 2
    assert [output["status"] for output in meta["shot_outputs"]] == ["real_video", "real_video"]
    assert meta["shot_assembly_manifest"]["children"][1]["start_seconds"] == 1.5
    assert (created["project_root"] / "scenes" / "scene_001" / "shot_assembly_manifest.json").is_file()


def _prepare_shot_granularity_project(provider_project, monkeypatch, project_id: str, fallback_mode: str = "report"):
    import backend.project_runtime as project_runtime
    import backend.scene_renderer as scene_renderer

    created = provider_project(project_id, video_provider="doubao")
    project = project_runtime.load_project(created["project_id"])
    project["settings"]["video_render_granularity"] = "shot"
    scene = project["scenes"][0]
    scene["duration_seconds"] = 4.0
    scene["temporal_spec"] = {
        "shots": [
            {"shot_id": "scene_001_shot_01", "duration_seconds": 1.5, "camera_movement": "slow_push"},
            {"shot_id": "scene_001_shot_02", "duration_seconds": 2.5, "camera_movement": "static"},
        ]
    }
    (created["project_root"] / "project.json").write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")

    monkeypatch.setattr(scene_renderer, "load_env_file", lambda: None)
    monkeypatch.setattr(scene_renderer, "get_ffmpeg_exe", lambda: "ffmpeg")
    monkeypatch.setattr(scene_renderer, "wav_duration", lambda path: 4.0)

    def fake_voice_track(*args, **kwargs):
        path = Path(args[2]) / "voice.wav"
        path.write_bytes(b"voice")
        return path, 4.0

    def fake_fallback_segment(*args, **kwargs):
        Path(args[3]).parent.mkdir(parents=True, exist_ok=True)
        Path(args[3]).write_bytes(b"fallback shot")
        return Path(args[3])

    def fake_run_guarded(cmd, **kwargs):
        Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(cmd[-1]).write_bytes(b"assembled")

    monkeypatch.setattr(scene_renderer, "render_voice_track", fake_voice_track)
    monkeypatch.setattr(scene_renderer, "_evaluate_and_persist_scene_governance", lambda *args, **kwargs: None)
    monkeypatch.setattr(scene_renderer, "render_silent_visual_segment", fake_fallback_segment)
    monkeypatch.setattr(scene_renderer, "run_guarded", fake_run_guarded)
    monkeypatch.setenv("VIDEO_FALLBACK_MODE", fallback_mode)
    monkeypatch.setenv("VIDEO_MAX_RETRIES", "0")
    monkeypatch.setenv("VIDEO_RETRY_DELAY_SECONDS", "0")
    monkeypatch.setattr("backend.video_generation.VIDEO_RETRY_DELAY_SECONDS", 0.0)
    monkeypatch.setattr("backend.video_generation.MAX_VIDEO_RETRIES", 0)
    monkeypatch.delenv("VIDEO_STRICT", raising=False)
    monkeypatch.delenv("DOUBAO_VIDEO_STRICT", raising=False)
    return created


def test_shot_granularity_report_mode_assembles_mixed_real_and_fallback(provider_project, monkeypatch):
    import backend.project_runtime as project_runtime
    import backend.video_generation as video_generation

    created = _prepare_shot_granularity_project(provider_project, monkeypatch, "shot_report_mixed_project", "report")
    attempts: list[str] = []

    def fake_remote_mixed(request, provider_spec, **kwargs):
        attempts.append(request.out_path.name)
        if request.out_path.name.endswith("shot_02.mp4"):
            raise RuntimeError("second shot failed token=mixed-secret")
        request.out_path.parent.mkdir(parents=True, exist_ok=True)
        request.out_path.write_bytes(b"real shot")
        return request.out_path

    monkeypatch.setattr(video_generation, "render_remote_video_provider", fake_remote_mixed)

    result = project_runtime.rerender_scene_video(created["project_id"], 1)
    scene = result["scenes"][0]
    meta = scene["generation_meta"]

    assert attempts.count("scene_001_shot_01.mp4") == 1
    assert attempts.count("scene_001_shot_02.mp4") >= 1
    assert scene["assets"]["video_path"]
    assert meta["render_granularity"] == "shot"
    assert meta["real_video_shot_count"] == 1
    assert meta["fallback_shot_count"] == 1
    assert meta["failed_shot_count"] == 0
    assert meta["fallback_used"] is True
    assert [output["status"] for output in meta["shot_outputs"]] == ["real_video", "fallback"]
    assert meta["warnings"]
    assert "mixed-secret" not in json.dumps(meta, ensure_ascii=False)


def test_shot_granularity_silent_mode_records_fallback_without_warnings(provider_project, monkeypatch):
    import backend.project_runtime as project_runtime
    import backend.video_generation as video_generation

    created = _prepare_shot_granularity_project(provider_project, monkeypatch, "shot_silent_project", "silent")

    def fake_remote_failure(request, provider_spec, **kwargs):
        raise RuntimeError("silent shot failure token=silent-shot-secret")

    monkeypatch.setattr(video_generation, "render_remote_video_provider", fake_remote_failure)

    result = project_runtime.rerender_scene_video(created["project_id"], 1)
    meta = result["scenes"][0]["generation_meta"]

    assert meta["render_granularity"] == "shot"
    assert meta["real_video_shot_count"] == 0
    assert meta["fallback_shot_count"] == 2
    assert meta["fallback_mode"] == "silent"
    assert meta["warnings"] == []
    assert "silent-shot-secret" not in json.dumps(meta, ensure_ascii=False)


def test_targeted_shot_rerender_reuses_unchanged_shots_and_reassembles(provider_project, monkeypatch):
    import backend.project_runtime as project_runtime
    import backend.video_generation as video_generation

    created = _prepare_shot_granularity_project(provider_project, monkeypatch, "shot_targeted_rerender_project", "report")
    calls: list[str] = []

    def fake_remote_success(request, provider_spec, **kwargs):
        calls.append(request.out_path.name)
        request.out_path.parent.mkdir(parents=True, exist_ok=True)
        request.out_path.write_bytes(f"remote {len(calls)}".encode("utf-8"))
        return request.out_path

    monkeypatch.setattr(video_generation, "render_remote_video_provider", fake_remote_success)

    first_result = project_runtime.rerender_scene_video(created["project_id"], 1)
    first_outputs = first_result["scenes"][0]["generation_meta"]["shot_outputs"]
    first_keys = {output["shot_id"]: output["cache_key"] for output in first_outputs}

    assert calls == ["scene_001_shot_01.mp4", "scene_001_shot_02.mp4"]
    assert all(key.startswith("sha256:") for key in first_keys.values())

    calls.clear()
    second_result = project_runtime.rerender_scene_shot_video(created["project_id"], 1, "scene_001_shot_02")
    second_scene = second_result["scenes"][0]
    second_outputs = second_scene["generation_meta"]["shot_outputs"]

    assert calls == ["scene_001_shot_02.mp4"]
    assert [output["shot_id"] for output in second_outputs] == ["scene_001_shot_01", "scene_001_shot_02"]
    assert second_outputs[0]["path"] == first_outputs[0]["path"]
    assert second_outputs[0]["cache_key"] == first_keys["scene_001_shot_01"]
    assert second_outputs[1]["cache_key"] == first_keys["scene_001_shot_02"]
    assert second_scene["assets"]["video_path"]
    assert second_scene["generation_meta"]["total_provider_attempts"] == 2
    assert second_scene["history"][0]["action"] == "rerender-shot-video"
    assert (created["project_root"] / "scenes" / "scene_001" / "shot_assembly_manifest.json").is_file()


def test_shot_granularity_strict_mode_fails_without_video_asset(provider_project, monkeypatch):
    import backend.project_runtime as project_runtime
    import backend.video_generation as video_generation

    created = _prepare_shot_granularity_project(provider_project, monkeypatch, "shot_strict_project", "strict")

    def fake_remote_failure(request, provider_spec, **kwargs):
        raise RuntimeError("strict shot failure token=strict-shot-secret")

    monkeypatch.setattr(video_generation, "render_remote_video_provider", fake_remote_failure)

    with pytest.raises(RuntimeError) as exc_info:
        project_runtime.rerender_scene_video(created["project_id"], 1)

    error_text = str(exc_info.value)
    assert "Scene scene_001 video generation failed in strict mode" in error_text
    assert "strict-shot-secret" not in error_text
    project = project_runtime.load_project(created["project_id"])
    scene = project["scenes"][0]
    assert scene["assets"]["video_path"] == ""
    assert scene["generation_meta"] == {}
    assert not (created["project_root"] / "scenes" / "scene_001" / "shot_assembly_manifest.json").exists()


def test_mock_remote_report_failure_persists_fallback_metadata(provider_project, patched_render_runtime, monkeypatch):
    import backend.project_runtime as project_runtime

    created = provider_project("report_fallback_project", video_provider="doubao")
    attempts: list[int] = []

    def fake_remote_failure(request, provider_spec, **kwargs):
        attempts.append(request.scene)
        raise RuntimeError("mock provider exhausted token=secret")

    monkeypatch.setenv("VIDEO_FALLBACK_MODE", "report")
    monkeypatch.setenv("VIDEO_MAX_RETRIES", "1")
    monkeypatch.setenv("VIDEO_RETRY_DELAY_SECONDS", "0")
    monkeypatch.delenv("VIDEO_STRICT", raising=False)
    monkeypatch.setattr(patched_render_runtime, "render_remote_video_provider", fake_remote_failure)

    result = project_runtime.rerender_scene_video(created["project_id"], 1)
    scene = result["scenes"][0]
    meta = scene["generation_meta"]

    assert len(attempts) == 2
    assert scene["assets"]["video_path"]
    assert meta["provider_id"] == "doubao"
    assert meta["backend"] == "local"
    assert meta["is_real_video"] is False
    assert meta["fallback_used"] is True
    assert meta["attempts"] == 2
    assert meta["error"]
    assert "secret" not in meta["error"]
    assert meta["warnings"]


def test_mock_remote_silent_failure_records_fallback_without_warnings(provider_project, patched_render_runtime, monkeypatch):
    import backend.project_runtime as project_runtime

    created = provider_project("silent_fallback_project", video_provider="doubao")
    attempts: list[int] = []

    def fake_remote_failure(request, provider_spec, **kwargs):
        attempts.append(request.scene)
        raise RuntimeError("silent fallback provider failure token=silent-secret")

    monkeypatch.setenv("VIDEO_FALLBACK_MODE", "silent")
    monkeypatch.setenv("VIDEO_MAX_RETRIES", "1")
    monkeypatch.setenv("VIDEO_RETRY_DELAY_SECONDS", "0")
    monkeypatch.delenv("VIDEO_STRICT", raising=False)
    monkeypatch.delenv("DOUBAO_VIDEO_STRICT", raising=False)
    monkeypatch.setattr(patched_render_runtime, "render_remote_video_provider", fake_remote_failure)

    result = project_runtime.rerender_scene_video(created["project_id"], 1)
    scene = result["scenes"][0]
    meta = scene["generation_meta"]

    assert len(attempts) == 2
    assert scene["assets"]["video_path"]
    assert meta["provider_id"] == "doubao"
    assert meta["backend"] == "local"
    assert meta["is_real_video"] is False
    assert meta["fallback_used"] is True
    assert meta["attempts"] == 2
    assert meta["fallback_mode"] == "silent"
    assert meta["warnings"] == []
    assert "silent-secret" not in meta["error"]


def test_video_strict_env_overrides_report_mode_in_renderer(provider_project, patched_render_runtime, monkeypatch):
    import backend.project_runtime as project_runtime

    created = provider_project("global_strict_failure_project", video_provider="doubao")
    attempts: list[int] = []

    def fake_remote_failure(request, provider_spec, **kwargs):
        attempts.append(request.scene)
        raise RuntimeError("global strict provider failure token=strict-secret")

    monkeypatch.setenv("VIDEO_FALLBACK_MODE", "report")
    monkeypatch.setenv("VIDEO_STRICT", "1")
    monkeypatch.setenv("VIDEO_MAX_RETRIES", "1")
    monkeypatch.setenv("VIDEO_RETRY_DELAY_SECONDS", "0")
    monkeypatch.delenv("DOUBAO_VIDEO_STRICT", raising=False)
    monkeypatch.setattr(patched_render_runtime, "render_remote_video_provider", fake_remote_failure)

    assert video_fallback_mode("doubao") == "strict"
    with pytest.raises(RuntimeError) as exc_info:
        project_runtime.rerender_scene_video(created["project_id"], 1)

    error_text = str(exc_info.value)
    assert "Scene scene_001 video generation failed in strict mode" in error_text
    assert "Provider: doubao" in error_text
    assert "global strict provider failure" in error_text
    assert "strict-secret" not in error_text

    project = project_runtime.load_project(created["project_id"])
    scene = project["scenes"][0]
    history = scene.get("history") or []

    assert len(attempts) == 2
    assert scene["assets"]["video_path"] == ""
    assert scene["assets"]["versions"]["video"] == 0
    assert scene["generation_meta"] == {}
    assert history[0]["action"] == "rerender-video"
    assert history[0]["status"] == "failed"
    assert "Scene scene_001 video generation failed in strict mode" in history[0]["message"]
    assert "strict-secret" not in history[0]["message"]


def test_mock_remote_strict_failure_records_failed_history_without_video_asset(provider_project, patched_render_runtime, monkeypatch):
    import backend.project_runtime as project_runtime

    created = provider_project("strict_failure_project", video_provider="doubao")
    attempts: list[int] = []

    def fake_remote_failure(request, provider_spec, **kwargs):
        attempts.append(request.scene)
        raise RuntimeError("strict provider failure")

    monkeypatch.setenv("VIDEO_FALLBACK_MODE", "strict")
    monkeypatch.setenv("VIDEO_MAX_RETRIES", "1")
    monkeypatch.setenv("VIDEO_RETRY_DELAY_SECONDS", "0")
    monkeypatch.delenv("VIDEO_STRICT", raising=False)
    monkeypatch.setattr(patched_render_runtime, "render_remote_video_provider", fake_remote_failure)

    with pytest.raises(RuntimeError, match="strict provider failure"):
        project_runtime.rerender_scene_video(created["project_id"], 1)

    project = project_runtime.load_project(created["project_id"])
    scene = project["scenes"][0]
    history = scene.get("history") or []

    assert len(attempts) == 2
    assert scene["assets"]["video_path"] == ""
    assert scene["assets"]["versions"]["video"] == 0
    assert scene["generation_meta"] == {}
    assert history[0]["action"] == "rerender-video"
    assert history[0]["status"] == "failed"


def test_legacy_project_builds_timeline_and_rerenders_without_real_provider(provider_project, patched_render_runtime, monkeypatch):
    import backend.project_runtime as project_runtime

    created = provider_project("legacy_render_project", video_provider="doubao", legacy=True)

    def fake_remote_success(request, provider_spec, **kwargs):
        request.out_path.write_bytes(b"remote visual")
        return request.out_path

    monkeypatch.setenv("VIDEO_FALLBACK_MODE", "report")
    monkeypatch.setenv("VIDEO_MAX_RETRIES", "1")
    monkeypatch.setenv("VIDEO_RETRY_DELAY_SECONDS", "0")
    monkeypatch.delenv("VIDEO_STRICT", raising=False)
    monkeypatch.setattr(patched_render_runtime, "render_remote_video_provider", fake_remote_success)

    loaded = project_runtime.load_project(created["project_id"])
    timeline = build_canonical_timeline(loaded)
    assert timeline["summary"]["scene_count"] == 1
    assert timeline["tracks"][0]["children"][0]["metadata"]["generation"] == {}
    assert loaded["scenes"][0]["shot_plan"]["source"] == "temporal_spec"

    result = project_runtime.rerender_scene_video(created["project_id"], 1)
    scene = result["scenes"][0]
    timeline_after_render = build_canonical_timeline(result)

    assert scene["assets"]["video_path"]
    assert scene["generation_meta"]["is_real_video"] is True
    assert timeline_after_render["summary"]["real_video_scene_count"] == 1
    assert timeline_after_render["tracks"][0]["children"][0]["metadata"]["generation"]["provider_id"] == "doubao"
