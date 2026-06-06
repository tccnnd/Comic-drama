from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from backend.video_generation import VideoGenerationResult, generation_meta_from_result
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
                "generation_meta": {"is_real_video": True, "fallback_used": False, "provider_id": "doubao"},
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
