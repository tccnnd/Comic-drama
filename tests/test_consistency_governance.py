"""Tests for continuity validator additions and governance aggregation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import backend.consistency_governance as governance
from backend.video_generation import VideoGenerationResult
from backend.consistency_validator import (
    ValidationCheck,
    evaluate_camera_continuity,
    validate_prop_continuity,
)


Image = pytest.importorskip("PIL.Image")
ImageDraw = pytest.importorskip("PIL.ImageDraw")


def _write_image(path: Path, *, pattern: str) -> Path:
    image = Image.new("RGB", (64, 64), "white")
    draw = ImageDraw.Draw(image)
    if pattern == "prop_ref":
        draw.rectangle((8, 8, 56, 56), fill=(40, 180, 80))
        draw.line((8, 8, 56, 56), fill=(20, 90, 40), width=4)
    elif pattern == "prop_mismatch":
        draw.rectangle((0, 0, 63, 63), fill=(0, 0, 0))
    else:
        draw.rectangle((0, 0, 63, 63), fill=(120, 120, 120))
    image.save(path)
    return path


def _check(name: str, passed: bool, score: float, severity: str = "warning") -> ValidationCheck:
    return ValidationCheck(name=name, passed=passed, score=score, details=name, severity=severity)


@pytest.fixture()
def runtime_workspace(tmp_path, monkeypatch):
    import backend.project_models as project_models
    import backend.project_runtime as project_runtime

    workspace = tmp_path / "workspace"
    monkeypatch.setattr(project_models, "WORKSPACE", workspace)
    monkeypatch.setattr(project_runtime, "WORKSPACE", workspace)
    return workspace


def _runtime_project_payload(project_id: str, *, with_assets: bool = False) -> dict:
    assets = {
        "status": "pending",
        "versions": {"image": 0, "audio": 0, "video": 0},
        "image_path": "",
        "image_url": "",
        "audio_path": "",
        "audio_url": "",
        "video_path": "",
        "video_url": "",
    }
    if with_assets:
        assets.update(
            {
                "status": "completed",
                "versions": {"image": 1, "audio": 1, "video": 1},
                "image_path": "scenes/scene_001/image_v1.png",
                "audio_path": "scenes/scene_001/audio_v1.wav",
                "video_path": "scenes/scene_001/video_v1.mp4",
            }
        )
    return {
        "project_id": project_id,
        "title": "Governance Runtime Test",
        "story_text": "Runtime test.",
        "style_id": "anime_standard",
        "settings": {
            "keyframe_provider": "local",
            "video_provider": "local",
            "voice_provider": "silent",
            "subtitle_style": {"burn_in": False},
            "audio_style": {},
            "episode_pacing": {},
        },
        "characters": [],
        "scenes": [
            {
                "scene_id": "scene_001",
                "order": 1,
                "title": "Scene 1",
                "visual_prompt": "A quiet street.",
                "dialogue": "",
                "speaker": "",
                "camera_movement": "static",
                "emotion": "calm",
                "duration_seconds": 4.0,
                "characters": [],
                "camera_speed": 1.0,
                "audio_manifest": {
                    "bgm_style": "",
                    "bgm_file": "",
                    "bgm_gain_db": "",
                    "sfx_trigger": {"file": "", "timestamp_ms": 0, "volume": 0.65},
                    "sfx_triggers": [],
                },
                "assets": assets,
                "history": [],
            }
        ],
        "runtime": {"status": "idle", "progress": 0, "stage": "draft", "message": ""},
        "output": {"final_video_path": "", "final_video_url": "", "status": "idle"},
    }


def _write_runtime_project(workspace: Path, project_id: str, payload: dict) -> Path:
    project_root = workspace / project_id
    scene_root = project_root / "scenes" / "scene_001"
    (project_root / "characters").mkdir(parents=True, exist_ok=True)
    scene_root.mkdir(parents=True, exist_ok=True)
    (project_root / "output").mkdir(parents=True, exist_ok=True)
    (project_root / "project.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return project_root


def test_validate_prop_continuity_passes_matching_reference(tmp_path):
    ref = _write_image(tmp_path / "ref.png", pattern="prop_ref")
    current = _write_image(tmp_path / "current.png", pattern="prop_ref")

    result = validate_prop_continuity(current, {"prop_id": "jade", "reference_image_path": str(ref)})

    assert result.name == "prop_continuity:jade"
    assert result.passed is True
    assert result.severity == "warning"
    assert result.score >= 0.9


def test_validate_prop_continuity_warns_on_mismatch(tmp_path):
    ref = _write_image(tmp_path / "ref.png", pattern="prop_ref")
    current = _write_image(tmp_path / "current.png", pattern="prop_mismatch")

    result = validate_prop_continuity(current, {"prop_id": "jade", "reference_image_path": str(ref)})

    assert result.passed is False
    assert result.severity == "warning"
    assert result.score < 0.6


def test_validate_prop_continuity_missing_reference_is_info(tmp_path):
    current = _write_image(tmp_path / "current.png", pattern="prop_ref")

    result = validate_prop_continuity(current, {"prop_id": "jade"})

    assert result.passed is True
    assert result.severity == "info"
    assert result.score == 0.0


def test_evaluate_camera_continuity_treats_first_scene_as_info():
    result = evaluate_camera_continuity({"camera_movement": "static"}, None)

    assert result.passed is True
    assert result.severity == "info"
    assert result.score == 1.0


def test_evaluate_camera_continuity_allows_motivated_change():
    prev_scene = {
        "camera_movement": "static",
        "camera_speed": 0.8,
        "emotion_tone": "calm",
        "scene_intent": "setup",
        "subject_focus": "hero",
    }
    scene = {
        "camera_movement": "dramatic_push",
        "camera_speed": 1.8,
        "emotion_tone": "panic",
        "scene_intent": "reveal",
        "subject_focus": "villain",
    }

    result = evaluate_camera_continuity(scene, prev_scene)

    assert result.passed is True
    assert result.score >= 0.6


def test_evaluate_camera_continuity_flags_unmotivated_jump():
    prev_scene = {
        "camera_movement": "static",
        "camera_speed": 0.6,
        "emotion_tone": "calm",
        "scene_intent": "setup",
        "subject_focus": "hero",
    }
    scene = {
        "camera_movement": "handheld_shake",
        "camera_speed": 2.0,
        "emotion_tone": "calm",
        "scene_intent": "setup",
        "subject_focus": "hero",
    }

    result = evaluate_camera_continuity(scene, prev_scene)

    assert result.passed is False
    assert result.score < 0.6
    assert "no emotion/intent/focus change" in result.details


def test_evaluate_scene_governance_aggregates_all_five_dimensions(monkeypatch, tmp_path):
    current = _write_image(tmp_path / "current.png", pattern="prop_ref")
    project = {
        "characters": [{"name": "Lin", "reference_image_path": str(current)}],
        "production_bible": {
            "props": [
                {
                    "prop_id": "jade",
                    "name": "Jade",
                    "scenes": ["scene_001"],
                    "reference_image_path": str(current),
                }
            ]
        },
    }
    scene = {"scene_id": "scene_001", "order": 1, "characters": ["Lin"], "props": ["jade"]}

    monkeypatch.setattr(governance, "validate_character_identity", lambda *args, **kwargs: _check("character", True, 0.9))
    monkeypatch.setattr(governance, "validate_style_consistency", lambda *args, **kwargs: _check("environment", True, 0.8))
    monkeypatch.setattr(governance, "validate_lighting_continuity", lambda *args, **kwargs: _check("lighting", True, 0.7))
    monkeypatch.setattr(governance, "validate_prop_continuity", lambda *args, **kwargs: _check("prop", True, 0.95))
    monkeypatch.setattr(governance, "evaluate_camera_continuity", lambda *args, **kwargs: _check("camera", True, 0.85))

    verdict = governance.evaluate_scene_governance(project, scene, images={"current_image": current})

    assert verdict["status"] == "pass"
    assert verdict["deliverable"] is True
    assert set(verdict["dimensions"]) == {"character", "lighting", "environment", "prop", "camera"}
    assert verdict["offending_dimensions"] == []


def test_evaluate_scene_governance_uses_fail_warn_pass_precedence(monkeypatch, tmp_path):
    current = _write_image(tmp_path / "current.png", pattern="prop_ref")
    project = {"characters": [{"name": "Lin", "reference_image_path": str(current)}]}
    scene = {"scene_id": "scene_001", "order": 1, "characters": ["Lin"]}

    monkeypatch.setattr(governance, "validate_character_identity", lambda *args, **kwargs: _check("character", False, 0.2, "error"))
    monkeypatch.setattr(governance, "validate_style_consistency", lambda *args, **kwargs: _check("environment", False, 0.4))
    monkeypatch.setattr(governance, "validate_lighting_continuity", lambda *args, **kwargs: _check("lighting", True, 0.9))
    monkeypatch.setattr(governance, "evaluate_camera_continuity", lambda *args, **kwargs: _check("camera", True, 1.0, "info"))

    verdict = governance.evaluate_scene_governance(project, scene, images={"current_image": current})

    assert verdict["status"] == "fail"
    assert verdict["dimensions"]["character"]["status"] == "fail"
    assert verdict["dimensions"]["environment"]["status"] == "warn"
    assert verdict["dimensions"]["prop"]["status"] == "info"
    assert verdict["offending_dimensions"] == ["character", "environment"]


def test_info_dimensions_do_not_worsen_passing_verdict(monkeypatch, tmp_path):
    current = _write_image(tmp_path / "current.png", pattern="prop_ref")
    scene = {"scene_id": "scene_001", "order": 1, "characters": []}

    monkeypatch.setattr(governance, "validate_style_consistency", lambda *args, **kwargs: _check("environment", True, 0.8))
    monkeypatch.setattr(governance, "validate_lighting_continuity", lambda *args, **kwargs: _check("lighting", True, 0.8))
    monkeypatch.setattr(governance, "evaluate_camera_continuity", lambda *args, **kwargs: _check("camera", True, 1.0, "info"))

    verdict = governance.evaluate_scene_governance({}, scene, images={"current_image": current})

    assert verdict["status"] == "pass"
    assert verdict["dimensions"]["character"]["status"] == "info"
    assert verdict["dimensions"]["prop"]["status"] == "info"


def test_apply_governance_policy_report_and_block_modes():
    failed = {
        "scene_id": "scene_001",
        "status": "fail",
        "offending_dimensions": ["character"],
        "deliverable": True,
    }
    warned = {
        "scene_id": "scene_002",
        "status": "warn",
        "offending_dimensions": ["lighting"],
        "deliverable": True,
    }

    assert governance.apply_governance_policy(failed, "report")["deliverable"] is True
    blocked = governance.apply_governance_policy(failed, "block")
    assert blocked["deliverable"] is False
    assert blocked["policy"] == {"mode": "block", "action": "blocked"}
    assert governance.apply_governance_policy(warned, "block")["deliverable"] is True


def test_build_continuity_ledger_counts_statuses_pass_rates_and_offenders(monkeypatch):
    monkeypatch.setenv("CONSISTENCY_POLICY_MODE", "block")
    project = {
        "scenes": [
            {
                "scene_id": "scene_001",
                "order": 1,
                "governance": {
                    "status": "pass",
                    "deliverable": True,
                    "dimensions": {
                        "character": {"status": "pass"},
                        "lighting": {"status": "pass"},
                    },
                },
            },
            {
                "scene_id": "scene_002",
                "order": 2,
                "governance": {
                    "status": "warn",
                    "deliverable": True,
                    "offending_dimensions": ["camera"],
                    "dimensions": {
                        "character": {"status": "pass"},
                        "camera": {"status": "warn"},
                    },
                },
            },
            {
                "scene_id": "scene_003",
                "order": 3,
                "governance": {
                    "status": "fail",
                    "deliverable": False,
                    "offending_dimensions": ["character"],
                    "dimensions": {
                        "character": {"status": "fail"},
                        "prop": {"status": "pass"},
                    },
                },
            },
            {"scene_id": "scene_004", "order": 4},
        ]
    }

    ledger = governance.build_continuity_ledger(project)

    assert ledger["evaluated_scene_count"] == 4
    assert ledger["status_counts"] == {"pass": 1, "warn": 1, "fail": 1, "not_evaluated": 1}
    assert ledger["blocked_scene_count"] == 1
    assert ledger["dimension_pass_rates"]["character"] == pytest.approx(2 / 3, abs=0.001)
    assert ledger["dimension_pass_rates"]["prop"] == 1.0
    assert ledger["offending_scenes"] == [
        {"scene_id": "scene_002", "scene_order": 2, "status": "warn", "offending_dimensions": ["camera"]},
        {"scene_id": "scene_003", "scene_order": 3, "status": "fail", "offending_dimensions": ["character"]},
    ]
    assert ledger["policy_mode"] == "block"


def test_update_scene_governance_persists_verdict(runtime_workspace):
    import backend.project_runtime as project_runtime

    project_id = "governance_persist"
    _write_runtime_project(runtime_workspace, project_id, _runtime_project_payload(project_id))
    verdict = {
        "version": 1,
        "scene_id": "scene_001",
        "scene_order": 1,
        "status": "warn",
        "evaluated_at": "2026-06-06T12:00:00Z",
        "dimensions": {"camera": {"status": "warn", "score": 0.4, "threshold": 0.6, "reason": "jump"}},
        "offending_dimensions": ["camera"],
        "policy": {"mode": "report", "action": "recorded"},
        "deliverable": True,
    }

    project_runtime.update_scene_governance(project_id, 1, verdict)
    loaded = project_runtime.load_project(project_id)

    assert loaded["scenes"][0]["governance"]["status"] == "warn"
    assert loaded["scenes"][0]["governance"]["offending_dimensions"] == ["camera"]


def test_load_project_and_snapshot_normalize_legacy_governance(runtime_workspace):
    import backend.project_runtime as project_runtime

    project_id = "legacy_governance"
    _write_runtime_project(runtime_workspace, project_id, _runtime_project_payload(project_id))

    loaded = project_runtime.load_project(project_id)
    scene = loaded["scenes"][0]
    assert scene["props"] == []
    assert scene["governance"]["status"] == "not_evaluated"

    snapshot = project_runtime.project_snapshot(loaded)
    assert snapshot["scenes"][0]["governance"]["status"] == "not_evaluated"
    assert snapshot["continuity_ledger"]["status_counts"]["not_evaluated"] == 1
    assert snapshot["continuity_ledger"]["evaluated_scene_count"] == 1


def test_export_readiness_blocks_undeliverable_governance(runtime_workspace):
    import backend.project_export as project_export
    from backend.project_models import ExportAssetReadinessError

    project_id = "blocked_export"
    project_root = _write_runtime_project(
        runtime_workspace,
        project_id,
        _runtime_project_payload(project_id, with_assets=True),
    )
    scene_root = project_root / "scenes" / "scene_001"
    _write_image(scene_root / "image_v1.png", pattern="prop_ref")
    (scene_root / "audio_v1.wav").write_bytes(b"wav")
    (scene_root / "video_v1.mp4").write_bytes(b"mp4")
    scene = _runtime_project_payload(project_id, with_assets=True)["scenes"][0]
    scene["governance"] = {
        "status": "fail",
        "policy": {"mode": "block", "action": "blocked"},
        "deliverable": False,
    }

    with pytest.raises(ExportAssetReadinessError) as exc_info:
        project_export.validate_export_assets(project_id, [scene])

    assert exc_info.value.detail["items"][0]["missing"] == ["governance"]
    assert exc_info.value.detail["totals"]["governance"] == 1


def test_rerender_scene_video_persists_governance_verdict(runtime_workspace, monkeypatch):
    import backend.scene_renderer as scene_renderer
    import backend.project_runtime as project_runtime

    project_id = "render_governance"
    project_root = _write_runtime_project(
        runtime_workspace,
        project_id,
        _runtime_project_payload(project_id, with_assets=True),
    )
    scene_root = project_root / "scenes" / "scene_001"
    _write_image(scene_root / "image_v1.png", pattern="prop_ref")

    monkeypatch.setattr(scene_renderer, "load_env_file", lambda: None)
    monkeypatch.setattr(scene_renderer, "get_ffmpeg_exe", lambda: "ffmpeg")
    monkeypatch.setattr(scene_renderer, "wav_duration", lambda path: 4.0)

    def fake_voice_track(ffmpeg, scene_obj, directory, voice_provider, **kwargs):
        path = Path(directory) / "voice_source.wav"
        path.write_bytes(b"wav")
        return path, 4.0

    def fake_clip_with_meta(*args, **kwargs):
        directory = Path(args[2])
        path = directory / "clip_source.mp4"
        path.write_bytes(b"mp4")
        return path, VideoGenerationResult(
            scene_order=1,
            provider_id="local",
            provider_label="Local",
            success=True,
            is_real_video=False,
            attempts=1,
            duration_seconds=4.0,
            output_path=str(path),
        )

    monkeypatch.setattr(scene_renderer, "render_voice_track", fake_voice_track)
    monkeypatch.setattr(scene_renderer, "render_clip_with_meta", fake_clip_with_meta)

    result = project_runtime.rerender_scene_video(project_id, 1)
    scene = result["scenes"][0]

    assert scene["governance"]["status"] == "pass"
    assert set(scene["governance"]["dimensions"]) == {"character", "lighting", "environment", "prop", "camera"}
    snapshot = project_runtime.project_snapshot(project_runtime.load_project(project_id))
    assert snapshot["continuity_ledger"]["status_counts"]["pass"] == 1
