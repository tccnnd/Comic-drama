"""Tests for scene split, merge, renumbering, and validation logic."""
from __future__ import annotations

from copy import deepcopy

import pytest

from backend.scene_renderer import (
    _invalidate_scene_assets,
    _scene_validation_blocked,
    _scene_validation_resolved,
    IMAGE_STALE_FIELDS,
    AUDIO_STALE_FIELDS,
    VIDEO_STALE_FIELDS,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_scene(
    order: int = 1,
    duration: float = 4.0,
    title: str = "分镜",
    dialogue: str = "对话",
    characters: list[str] | None = None,
    visual_prompt: str = "视觉描述",
    camera_movement: str = "slow_push_in",
    camera_speed: float = 1.0,
) -> dict:
    return {
        "scene_id": f"scene_{order:03d}",
        "order": order,
        "title": title,
        "visual_prompt": visual_prompt,
        "dialogue": dialogue,
        "speaker": "",
        "camera_movement": camera_movement,
        "emotion": "neutral",
        "duration_seconds": duration,
        "characters": characters or ["角色A"],
        "voice_engine": "edge",
        "voice_id": "",
        "voice_rate": 1.0,
        "voice_pitch": 0.0,
        "voice_volume": 1.0,
        "camera_speed": camera_speed,
        "sfx_type": "auto",
        "audio_manifest": {
            "bgm_style": "",
            "bgm_file": "",
            "bgm_gain_db": "",
            "sfx_trigger": {"file": "", "timestamp_ms": 0, "volume": 0.65},
            "sfx_triggers": [],
        },
        "assets": {
            "status": "completed",
            "versions": {"image": 2, "audio": 1, "video": 1},
            "image_path": "scenes/scene_001/image_v2.png",
            "image_url": "/workspace/test/scenes/scene_001/image_v2.png",
            "audio_path": "scenes/scene_001/audio_v1.wav",
            "audio_url": "/workspace/test/scenes/scene_001/audio_v1.wav",
            "video_path": "scenes/scene_001/video_v1.mp4",
            "video_url": "/workspace/test/scenes/scene_001/video_v1.mp4",
        },
        "history": [],
    }


def _simulate_split(scene: dict) -> tuple[dict, dict]:
    """Simulate the split logic from project_runtime.split_scene without I/O."""
    source = deepcopy(scene)
    duplicate = deepcopy(source)
    duplicate["title"] = f"{source.get('title') or '分镜'} B"
    duplicate["dialogue"] = ""
    duplicate["assets"] = {
        "status": "pending",
        "versions": {"image": 0, "audio": 0, "video": 0},
        "image_path": "",
        "image_url": "",
        "audio_path": "",
        "audio_url": "",
        "video_path": "",
        "video_url": "",
    }
    duplicate["history"] = []
    original_duration = float(source.get("duration_seconds") or 4.0)
    half_duration = max(1.0, round(original_duration / 2, 1))
    source["duration_seconds"] = half_duration
    duplicate["duration_seconds"] = half_duration
    _invalidate_scene_assets(source, ["duration_seconds"])
    return source, duplicate


def _simulate_merge(current: dict, following: dict) -> dict:
    """Simulate the merge logic from project_runtime.merge_scene_with_next without I/O."""
    merged = deepcopy(current)
    merged["title"] = " / ".join(
        part for part in [str(current.get("title") or "").strip(), str(following.get("title") or "").strip()] if part
    )[:80]
    merged["visual_prompt"] = "\n".join(
        part for part in [str(current.get("visual_prompt") or "").strip(), str(following.get("visual_prompt") or "").strip()] if part
    )
    merged["dialogue"] = "\n".join(
        part for part in [str(current.get("dialogue") or "").strip(), str(following.get("dialogue") or "").strip()] if part
    )
    merged["characters"] = list(dict.fromkeys([*(current.get("characters") or []), *(following.get("characters") or [])]))
    merged["duration_seconds"] = round(
        float(current.get("duration_seconds") or 0) + float(following.get("duration_seconds") or 0), 1
    )
    merged["assets"] = {
        "status": "pending",
        "versions": {"image": 0, "audio": 0, "video": 0},
        "image_path": "",
        "image_url": "",
        "audio_path": "",
        "audio_url": "",
        "video_path": "",
        "video_url": "",
    }
    return merged


def _renumber_scenes(scenes: list[dict]) -> None:
    """Simulate _renumber_scenes logic."""
    for index, scene in enumerate(scenes, start=1):
        scene["order"] = index
        scene["scene_id"] = f"scene_{index:03d}"


# ─── Scene Split ──────────────────────────────────────────────────────────────


class TestSceneSplit:
    def test_split_creates_two_scenes(self):
        scene = _make_scene(order=1, duration=6.0)
        source, duplicate = _simulate_split(scene)
        assert source is not duplicate

    def test_split_halves_duration(self):
        scene = _make_scene(order=1, duration=8.0)
        source, duplicate = _simulate_split(scene)
        assert source["duration_seconds"] == 4.0
        assert duplicate["duration_seconds"] == 4.0

    def test_split_minimum_duration_is_one(self):
        scene = _make_scene(order=1, duration=1.5)
        source, duplicate = _simulate_split(scene)
        assert source["duration_seconds"] >= 1.0
        assert duplicate["duration_seconds"] >= 1.0

    def test_split_duplicate_has_empty_dialogue(self):
        scene = _make_scene(order=1, dialogue="原始对话")
        _, duplicate = _simulate_split(scene)
        assert duplicate["dialogue"] == ""

    def test_split_duplicate_title_has_b_suffix(self):
        scene = _make_scene(order=1, title="初次相遇")
        _, duplicate = _simulate_split(scene)
        assert "B" in duplicate["title"]

    def test_split_duplicate_has_pending_assets(self):
        scene = _make_scene(order=1)
        _, duplicate = _simulate_split(scene)
        assert duplicate["assets"]["status"] == "pending"
        assert duplicate["assets"]["versions"]["image"] == 0

    def test_split_source_assets_invalidated_for_duration_change(self):
        scene = _make_scene(order=1)
        source, _ = _simulate_split(scene)
        # duration_seconds is in VIDEO_STALE_FIELDS, so video should be invalidated
        assert source["assets"]["video_path"] == ""
        assert source["assets"]["video_url"] == ""


# ─── Scene Merge ──────────────────────────────────────────────────────────────


class TestSceneMerge:
    def test_merge_combines_dialogue(self):
        scene1 = _make_scene(order=1, dialogue="第一段对话")
        scene2 = _make_scene(order=2, dialogue="第二段对话")
        merged = _simulate_merge(scene1, scene2)
        assert "第一段对话" in merged["dialogue"]
        assert "第二段对话" in merged["dialogue"]

    def test_merge_combines_characters_without_duplicates(self):
        scene1 = _make_scene(order=1, characters=["角色A", "角色B"])
        scene2 = _make_scene(order=2, characters=["角色B", "角色C"])
        merged = _simulate_merge(scene1, scene2)
        assert merged["characters"] == ["角色A", "角色B", "角色C"]

    def test_merge_sums_duration(self):
        scene1 = _make_scene(order=1, duration=4.0)
        scene2 = _make_scene(order=2, duration=5.0)
        merged = _simulate_merge(scene1, scene2)
        assert merged["duration_seconds"] == 9.0

    def test_merge_combines_titles(self):
        scene1 = _make_scene(order=1, title="开头")
        scene2 = _make_scene(order=2, title="结尾")
        merged = _simulate_merge(scene1, scene2)
        assert "开头" in merged["title"]
        assert "结尾" in merged["title"]
        assert " / " in merged["title"]

    def test_merge_resets_assets(self):
        scene1 = _make_scene(order=1)
        scene2 = _make_scene(order=2)
        merged = _simulate_merge(scene1, scene2)
        assert merged["assets"]["status"] == "pending"


# ─── Scene Renumbering ────────────────────────────────────────────────────────


class TestSceneRenumbering:
    def test_renumber_after_split(self):
        scenes = [_make_scene(order=i) for i in range(1, 4)]
        # Simulate split at scene 2
        source, duplicate = _simulate_split(scenes[1])
        scenes[1] = source
        scenes.insert(2, duplicate)
        _renumber_scenes(scenes)
        orders = [s["order"] for s in scenes]
        assert orders == [1, 2, 3, 4]

    def test_renumber_after_merge(self):
        scenes = [_make_scene(order=i) for i in range(1, 5)]
        # Simulate merge of scene 2 with scene 3
        merged = _simulate_merge(scenes[1], scenes[2])
        scenes[1] = merged
        scenes.pop(2)
        _renumber_scenes(scenes)
        orders = [s["order"] for s in scenes]
        assert orders == [1, 2, 3]

    def test_renumber_updates_scene_ids(self):
        scenes = [_make_scene(order=i) for i in range(1, 4)]
        _renumber_scenes(scenes)
        assert scenes[0]["scene_id"] == "scene_001"
        assert scenes[1]["scene_id"] == "scene_002"
        assert scenes[2]["scene_id"] == "scene_003"


# ─── _invalidate_scene_assets ─────────────────────────────────────────────────


class TestInvalidateSceneAssets:
    def test_image_field_change_invalidates_image_and_video(self):
        scene = _make_scene()
        _invalidate_scene_assets(scene, ["visual_prompt"])
        assets = scene["assets"]
        assert assets["image_path"] == ""
        assert assets["image_url"] == ""
        assert assets["video_path"] == ""
        assert assets["video_url"] == ""
        # Audio should remain
        assert assets["audio_path"] != ""

    def test_audio_field_change_invalidates_audio_and_video(self):
        scene = _make_scene()
        _invalidate_scene_assets(scene, ["dialogue"])
        assets = scene["assets"]
        assert assets["audio_path"] == ""
        assert assets["audio_url"] == ""
        assert assets["video_path"] == ""
        assert assets["video_url"] == ""
        # Image should remain
        assert assets["image_path"] != ""

    def test_video_field_change_invalidates_only_video(self):
        scene = _make_scene()
        _invalidate_scene_assets(scene, ["duration_seconds"])
        assets = scene["assets"]
        assert assets["video_path"] == ""
        assert assets["video_url"] == ""
        # Image and audio should remain
        assert assets["image_path"] != ""
        assert assets["audio_path"] != ""

    def test_unrelated_field_does_not_invalidate(self):
        scene = _make_scene()
        original_assets = deepcopy(scene["assets"])
        _invalidate_scene_assets(scene, ["some_random_field"])
        assert scene["assets"] == original_assets

    def test_multiple_fields_combined(self):
        scene = _make_scene()
        _invalidate_scene_assets(scene, ["visual_prompt", "dialogue", "duration_seconds"])
        assets = scene["assets"]
        assert assets["image_path"] == ""
        assert assets["audio_path"] == ""
        assert assets["video_path"] == ""

    def test_status_set_to_pending(self):
        scene = _make_scene()
        _invalidate_scene_assets(scene, ["visual_prompt"])
        assert scene["assets"]["status"] == "pending"


# ─── _scene_validation_blocked ────────────────────────────────────────────────


class TestSceneValidationBlocked:
    def test_valid_scene_returns_none(self):
        scene = _make_scene()
        scene["validation_failed"] = False
        assert _scene_validation_blocked(scene) is None

    def test_validation_failed_returns_message(self):
        scene = _make_scene()
        scene["validation_failed"] = True
        scene["error_message"] = "LLM parse error"
        result = _scene_validation_blocked(scene)
        assert result is not None
        assert "LLM parse error" in result

    def test_assets_status_failed_returns_message(self):
        scene = _make_scene()
        scene["assets"]["status"] = "failed"
        scene["error_message"] = "Generation failed"
        result = _scene_validation_blocked(scene)
        assert result is not None


# ─── _scene_validation_resolved ───────────────────────────────────────────────


class TestSceneValidationResolved:
    def test_valid_scene_returns_true(self):
        scene = _make_scene(
            visual_prompt="有效视觉描述",
            camera_movement="slow_push_in",
            camera_speed=1.0,
        )
        scene["audio_manifest"] = {
            "sfx_trigger": {"file": "", "timestamp_ms": 0, "volume": 0.65},
            "sfx_triggers": [],
        }
        assert _scene_validation_resolved(scene) is True

    def test_missing_visual_prompt_returns_false(self):
        scene = _make_scene(visual_prompt="")
        assert _scene_validation_resolved(scene) is False

    def test_zero_duration_returns_false(self):
        scene = _make_scene(duration=0)
        assert _scene_validation_resolved(scene) is False

    def test_invalid_camera_speed_returns_false(self):
        scene = _make_scene(camera_speed=0.1)  # Below 0.35 minimum
        scene["audio_manifest"] = {"sfx_trigger": {"file": "", "timestamp_ms": 0, "volume": 0.65}}
        assert _scene_validation_resolved(scene) is False

    def test_missing_camera_movement_returns_false(self):
        scene = _make_scene(camera_movement="")
        scene["audio_manifest"] = {"sfx_trigger": {"file": "", "timestamp_ms": 0, "volume": 0.65}}
        assert _scene_validation_resolved(scene) is False

    def test_missing_audio_manifest_returns_false(self):
        scene = _make_scene()
        scene["audio_manifest"] = None
        assert _scene_validation_resolved(scene) is False

    def test_characters_not_list_returns_false(self):
        scene = _make_scene()
        scene["characters"] = "not a list"
        scene["audio_manifest"] = {"sfx_trigger": {"file": "", "timestamp_ms": 0, "volume": 0.65}}
        assert _scene_validation_resolved(scene) is False
