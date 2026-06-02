"""Tests for backend.project_models — pure logic functions."""
from __future__ import annotations

import re
from copy import deepcopy

import pytest

from scripts.run_workflow import StoryScene, normalize_crop_box, DEFAULT_CROP_BOX
from backend.project_models import (
    utc_iso,
    derive_project_title,
    default_drama_config,
    _coerce_int_field,
    _scene_from_payload,
    scene_to_dict,
)


# ─── utc_iso ──────────────────────────────────────────────────────────────────


class TestUtcIso:
    def test_returns_valid_iso_format(self):
        result = utc_iso()
        # Should match YYYY-MM-DDTHH:MM:SSZ
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", result)

    def test_ends_with_z(self):
        result = utc_iso()
        assert result.endswith("Z")

    def test_contains_t_separator(self):
        result = utc_iso()
        assert "T" in result


# ─── derive_project_title ─────────────────────────────────────────────────────


class TestDeriveProjectTitle:
    def test_empty_string_returns_fallback(self):
        assert derive_project_title("") == "未命名漫剧"

    def test_whitespace_only_returns_fallback(self):
        assert derive_project_title("   \n\t  ") == "未命名漫剧"

    def test_short_text_returned_as_is(self):
        assert derive_project_title("短标题") == "短标题"

    def test_long_text_truncated_to_18_chars(self):
        long_text = "这是一个非常非常非常非常非常非常长的故事标题"
        result = derive_project_title(long_text)
        assert len(result) <= 18

    def test_custom_fallback(self):
        assert derive_project_title("", fallback="默认") == "默认"

    def test_multiline_text_compacted(self):
        text = "第一行\n第二行\n第三行"
        result = derive_project_title(text)
        assert "\n" not in result

    def test_leading_trailing_whitespace_stripped(self):
        result = derive_project_title("  hello  ")
        assert result == "hello"


# ─── normalize_crop_box ───────────────────────────────────────────────────────


class TestNormalizeCropBox:
    def test_none_returns_default(self):
        result = normalize_crop_box(None)
        assert result == DEFAULT_CROP_BOX

    def test_non_dict_returns_default(self):
        assert normalize_crop_box("invalid") == DEFAULT_CROP_BOX
        assert normalize_crop_box(123) == DEFAULT_CROP_BOX
        assert normalize_crop_box([]) == DEFAULT_CROP_BOX

    def test_valid_crop_box_preserved(self):
        box = {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.6}
        result = normalize_crop_box(box)
        assert result == box

    def test_values_clamped_to_valid_range(self):
        box = {"x": -0.5, "y": 2.0, "width": 0.3, "height": 0.3}
        result = normalize_crop_box(box)
        assert result["x"] >= 0.0
        assert result["y"] >= 0.0
        assert result["y"] <= 1.0

    def test_width_height_minimum_enforced(self):
        box = {"x": 0.0, "y": 0.0, "width": 0.001, "height": 0.001}
        result = normalize_crop_box(box)
        assert result["width"] >= 0.05  # MIN_CROP_BOX_SIZE
        assert result["height"] >= 0.05

    def test_x_plus_width_clamped(self):
        box = {"x": 0.9, "y": 0.0, "width": 0.5, "height": 1.0}
        result = normalize_crop_box(box)
        assert result["x"] + result["width"] <= 1.0

    def test_empty_dict_returns_default_values(self):
        result = normalize_crop_box({})
        assert result["x"] == 0.0
        assert result["y"] == 0.0
        assert result["width"] == 1.0
        assert result["height"] == 1.0


# ─── default_drama_config ─────────────────────────────────────────────────────


class TestDefaultDramaConfig:
    def test_returns_expected_keys(self):
        config = default_drama_config()
        assert "rhythm_preset" in config
        assert "sfx_type" in config
        assert "audio_manifest" in config
        assert "subtitle_preset" in config
        assert "camera_intensity" in config
        assert "camera_speed" in config

    def test_rhythm_preset_is_balanced(self):
        config = default_drama_config()
        assert config["rhythm_preset"] == "balanced"

    def test_audio_manifest_has_sfx_trigger(self):
        config = default_drama_config()
        manifest = config["audio_manifest"]
        assert "sfx_trigger" in manifest
        assert "sfx_triggers" in manifest
        assert isinstance(manifest["sfx_triggers"], list)

    def test_returns_new_instance_each_call(self):
        config1 = default_drama_config()
        config2 = default_drama_config()
        config1["rhythm_preset"] = "fast"
        assert config2["rhythm_preset"] == "balanced"


# ─── _scene_from_payload ──────────────────────────────────────────────────────


class TestSceneFromPayload:
    def test_converts_basic_payload(self):
        payload = {
            "order": 1,
            "duration_seconds": 5.0,
            "title": "测试分镜",
            "visual_prompt": "一个美丽的场景",
            "dialogue": "你好世界",
            "camera_movement": "slow_push_in",
            "emotion": "happy",
            "characters": ["角色A", "角色B"],
        }
        scene = _scene_from_payload(payload)
        assert isinstance(scene, StoryScene)
        assert scene.scene == 1
        assert scene.duration == 5.0
        assert scene.title == "测试分镜"
        assert scene.visual == "一个美丽的场景"
        assert scene.dialogue == "你好世界"
        assert scene.emotion == "happy"
        assert scene.characters == ["角色A", "角色B"]

    def test_defaults_for_missing_fields(self):
        payload = {}
        scene = _scene_from_payload(payload)
        assert scene.scene == 1
        assert scene.duration == 4.0
        assert scene.title == "分镜"
        assert scene.visual == ""
        assert scene.camera == "slow_push_in"

    def test_filters_empty_characters(self):
        payload = {"characters": ["角色A", "", "  ", "角色B"]}
        scene = _scene_from_payload(payload)
        assert "角色A" in scene.characters
        assert "角色B" in scene.characters
        # Empty strings should be filtered
        assert "" not in scene.characters

    def test_voice_fields_populated(self):
        payload = {
            "voice_engine": "edge",
            "voice_id": "zh-CN-XiaoxiaoNeural",
            "voice_rate": 1.2,
            "voice_pitch": -0.5,
            "voice_volume": 0.8,
        }
        scene = _scene_from_payload(payload)
        assert scene.voice_engine == "edge"
        assert scene.voice_id == "zh-CN-XiaoxiaoNeural"
        assert scene.voice_rate == 1.2
        assert scene.voice_pitch == -0.5
        assert scene.voice_volume == 0.8


# ─── scene_to_dict round-trip ─────────────────────────────────────────────────


class TestSceneToDict:
    def test_round_trip_preserves_core_fields(self):
        payload = {
            "order": 2,
            "duration_seconds": 5.0,
            "title": "测试场景",
            "visual_prompt": "视觉描述",
            "dialogue": "对话内容",
            "camera_movement": "slow_push_in",
            "emotion": "happy",
            "characters": ["角色A"],
            "speaker": "角色A",
        }
        scene = _scene_from_payload(payload)
        result = scene_to_dict(scene, 2)

        assert result["order"] == 2
        assert result["title"] == "测试场景"
        assert result["visual_prompt"] == "视觉描述"
        assert result["dialogue"] == "对话内容"
        assert result["emotion"] == "happy"
        assert "角色A" in result["characters"]

    def test_output_has_assets_structure(self):
        payload = {"order": 1, "title": "test"}
        scene = _scene_from_payload(payload)
        result = scene_to_dict(scene, 1)

        assert "assets" in result
        assert "status" in result["assets"]
        assert "versions" in result["assets"]

    def test_output_has_scene_id(self):
        payload = {"order": 3}
        scene = _scene_from_payload(payload)
        result = scene_to_dict(scene, 3)
        assert result["scene_id"] == "scene_003"


# ─── _coerce_int_field ────────────────────────────────────────────────────────


class TestCoerceIntField:
    def test_valid_int_within_range(self):
        assert _coerce_int_field(5, 1, 1, 10) == 5

    def test_value_below_minimum_clamped(self):
        assert _coerce_int_field(-5, 1, 1, 10) == 1

    def test_value_above_maximum_clamped(self):
        assert _coerce_int_field(100, 1, 1, 10) == 10

    def test_none_returns_default(self):
        assert _coerce_int_field(None, 7, 1, 10) == 7

    def test_empty_string_returns_default(self):
        assert _coerce_int_field("", 3, 1, 10) == 3

    def test_non_numeric_string_returns_default(self):
        assert _coerce_int_field("abc", 5, 1, 10) == 5

    def test_float_string_returns_default(self):
        # int("3.7") raises ValueError, so the default is returned
        assert _coerce_int_field("3.7", 1, 1, 10) == 1

    def test_string_number_converted(self):
        assert _coerce_int_field("8", 1, 1, 10) == 8

    def test_boundary_minimum(self):
        assert _coerce_int_field(1, 5, 1, 100) == 1

    def test_boundary_maximum(self):
        assert _coerce_int_field(100, 5, 1, 100) == 100
