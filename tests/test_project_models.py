"""Tests for backend.project_models — pure logic functions."""
from __future__ import annotations

import re
from copy import deepcopy

import pytest

from scripts.run_workflow import StoryScene, normalize_crop_box, DEFAULT_CROP_BOX
from scripts.rw_models import (
    AudioConfig,
    CameraConfig,
    CharacterReferenceConfig,
    DirectorConfig,
    EpisodePacing,
    ProductionConfig,
    ValidationState,
    VoiceConfig,
)
from backend.project_models import (
    utc_iso,
    derive_project_title,
    default_drama_config,
    _coerce_int_field,
    _scene_from_payload,
    project_dir,
    scene_to_dict,
    validate_project_id,
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


class TestProjectIdValidation:
    def test_accepts_legacy_safe_project_ids(self, tmp_path, monkeypatch):
        import backend.project_models as project_models

        monkeypatch.setattr(project_models, "WORKSPACE", tmp_path)

        assert validate_project_id("legacy_project") == "legacy_project"
        assert project_dir("proj_20260625_120000_abcdef") == tmp_path / "proj_20260625_120000_abcdef"

    @pytest.mark.parametrize("project_id", ["../escape", "..\\escape", "C:\\escape", ".", "", "bad/id"])
    def test_rejects_path_traversal_project_ids(self, project_id):
        with pytest.raises(ValueError):
            validate_project_id(project_id)


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


# ─── StoryScene grouped properties ───────────────────────────────────────────


def _make_scene(**overrides) -> StoryScene:
    defaults = dict(
        scene=1,
        duration=4.0,
        title="测试",
        visual="画面",
        dialogue="对白",
        camera="slow_push_in",
        emotion="happy",
        characters=["角色A"],
        bg_color="#000000",
        accent_color="#FFFFFF",
    )
    defaults.update(overrides)
    return StoryScene(**defaults)


class TestVoiceConfigProperty:
    def test_returns_voice_config_type(self):
        scene = _make_scene(voice_engine="edge", voice_id="zh-CN-XiaoxiaoNeural")
        assert isinstance(scene.voice_config, VoiceConfig)

    def test_reflects_flat_fields(self):
        scene = _make_scene(
            speaker="角色A",
            voice_profile="female_lead",
            voice_engine="edge",
            voice_id="zh-CN-XiaoxiaoNeural",
            voice_rate=1.2,
            voice_pitch=-0.5,
            voice_volume=0.8,
            voice_emotion="cheerful",
            reference_audio_path="/path/audio.wav",
            reference_text="参考文本",
        )
        vc = scene.voice_config
        assert vc.speaker == "角色A"
        assert vc.profile == "female_lead"
        assert vc.engine == "edge"
        assert vc.id == "zh-CN-XiaoxiaoNeural"
        assert vc.rate == 1.2
        assert vc.pitch == -0.5
        assert vc.volume == 0.8
        assert vc.emotion == "cheerful"
        assert vc.reference_audio_path == "/path/audio.wav"
        assert vc.reference_text == "参考文本"

    def test_is_frozen_cannot_mutate(self):
        scene = _make_scene(voice_engine="edge")
        vc = scene.voice_config
        with pytest.raises(AttributeError):
            vc.engine = "sapi"

    def test_snapshot_does_not_reflect_later_changes(self):
        scene = _make_scene(voice_engine="edge")
        vc = scene.voice_config
        scene.voice_engine = "sapi"
        assert vc.engine == "edge"


class TestCameraConfigProperty:
    def test_returns_camera_config_type(self):
        scene = _make_scene()
        assert isinstance(scene.camera_config, CameraConfig)

    def test_reflects_flat_fields(self):
        scene = _make_scene(
            camera_movement="dramatic_push",
            camera_intensity=1.5,
            camera_speed=0.7,
        )
        cc = scene.camera_config
        assert cc.movement == "dramatic_push"
        assert cc.intensity == 1.5
        assert cc.speed == 0.7


class TestEpisodePacingProperty:
    def test_returns_episode_pacing_type(self):
        scene = _make_scene()
        assert isinstance(scene.episode_pacing, EpisodePacing)

    def test_reflects_flat_fields(self):
        scene = _make_scene(
            episode_rhythm="three_act",
            episode_phase="climax",
            episode_phase_index=3,
            episode_phase_total=5,
        )
        ep = scene.episode_pacing
        assert ep.rhythm == "three_act"
        assert ep.phase == "climax"
        assert ep.phase_index == 3
        assert ep.phase_total == 5


class TestDirectorConfigProperty:
    def test_returns_director_config_type(self):
        scene = _make_scene()
        assert isinstance(scene.director_config, DirectorConfig)

    def test_reflects_flat_fields(self):
        scene = _make_scene(
            emotion_tone="tense",
            scene_intent="confrontation",
            pacing="fast",
            subject_focus="主角",
            director_meta={"rule": "dramatic"},
        )
        dc = scene.director_config
        assert dc.emotion_tone == "tense"
        assert dc.scene_intent == "confrontation"
        assert dc.pacing == "fast"
        assert dc.subject_focus == "主角"
        assert dc.meta == {"rule": "dramatic"}


class TestValidationStateProperty:
    def test_returns_validation_state_type(self):
        scene = _make_scene()
        assert isinstance(scene.validation_state, ValidationState)

    def test_reflects_flat_fields(self):
        scene = _make_scene(
            validation_failed=True,
            error_message="解析失败",
            raw_llm_output={"raw": "data"},
        )
        vs = scene.validation_state
        assert vs.failed is True
        assert vs.error_message == "解析失败"
        assert vs.raw_llm_output == {"raw": "data"}


class TestAudioConfigProperty:
    def test_returns_audio_config_type(self):
        scene = _make_scene()
        assert isinstance(scene.audio_config, AudioConfig)

    def test_reflects_flat_fields(self):
        manifest = {"bgm_style": "rock"}
        scene = _make_scene(
            rhythm_preset="fast",
            sfx_type="hit",
            audio_manifest=manifest,
            subtitle_preset="minimal",
        )
        ac = scene.audio_config
        assert ac.rhythm_preset == "fast"
        assert ac.sfx_type == "hit"
        assert ac.manifest is manifest
        assert ac.subtitle_preset == "minimal"


class TestCharacterReferenceConfigProperty:
    def test_returns_character_reference_config_type(self):
        scene = _make_scene()
        assert isinstance(scene.character_reference_config, CharacterReferenceConfig)

    def test_reflects_flat_fields(self):
        refs = [{"char_id": "c1"}]
        meta = {"source": "comfyui"}
        scene = _make_scene(
            character_descriptions="描述",
            character_references=refs,
            primary_reference_image_path="/img.png",
            primary_reference_image_abs_path="/abs/img.png",
            primary_reference_meta=meta,
            consistency_meta={"hash": "abc"},
        )
        crc = scene.character_reference_config
        assert crc.descriptions == "描述"
        assert crc.references is refs
        assert crc.primary_image_path == "/img.png"
        assert crc.primary_image_abs_path == "/abs/img.png"
        assert crc.primary_meta is meta
        assert crc.consistency_meta == {"hash": "abc"}


class TestProductionConfigProperty:
    def test_returns_production_config_type(self):
        scene = _make_scene()
        assert isinstance(scene.production_config, ProductionConfig)

    def test_reflects_flat_fields(self):
        bible = {"style": "anime"}
        spec = {"shots": []}
        scene = _make_scene(
            production_bible=bible,
            temporal_spec=spec,
            character_prompt_compilation="角色提示词",
            negative_prompt_compilation="负面提示词",
        )
        pc = scene.production_config
        assert pc.bible is bible
        assert pc.temporal_spec is spec
        assert pc.character_prompt == "角色提示词"
        assert pc.negative_prompt == "负面提示词"


# ─── StoryScene __post_init__ validation ─────────────────────────────────────


class TestPostInitValidation:
    def test_accepts_valid_scene(self):
        scene = _make_scene()
        assert scene.scene == 1

    def test_rejects_scene_zero(self):
        with pytest.raises(ValueError, match="Scene number must be >= 1"):
            _make_scene(scene=0)

    def test_rejects_negative_duration(self):
        with pytest.raises(ValueError, match="Duration must be non-negative"):
            _make_scene(duration=-1.0)

    def test_rejects_negative_voice_rate(self):
        with pytest.raises(ValueError, match="voice_rate must be >= 0.0"):
            _make_scene(voice_rate=-0.5)

    def test_rejects_negative_voice_volume(self):
        with pytest.raises(ValueError, match="voice_volume must be >= 0.0"):
            _make_scene(voice_volume=-0.1)

    def test_rejects_phase_total_zero(self):
        with pytest.raises(ValueError, match="episode_phase_total must be >= 1"):
            _make_scene(episode_phase_total=0)

    def test_rejects_phase_index_below_one(self):
        with pytest.raises(ValueError, match="episode_phase_index 0 out of range"):
            _make_scene(episode_phase_index=0)

    def test_rejects_phase_index_above_total(self):
        with pytest.raises(ValueError, match="episode_phase_index 5 out of range"):
            _make_scene(episode_phase_index=5, episode_phase_total=4)

    def test_accepts_phase_index_equal_to_total(self):
        scene = _make_scene(episode_phase_index=4, episode_phase_total=4)
        assert scene.episode_phase_index == 4


# ─── asdict backward compatibility ───────────────────────────────────────────


class TestAsdictFlatCompat:
    def test_asdict_produces_flat_keys(self):
        from dataclasses import asdict

        scene = _make_scene(voice_engine="edge", voice_id="test_id")
        d = asdict(scene)
        # Flat keys must exist (not nested under "voice")
        assert "voice_engine" in d
        assert "voice_id" in d
        assert "voice" not in d
        assert "camera_config" not in d
        assert d["voice_engine"] == "edge"
        assert d["voice_id"] == "test_id"

    def test_asdict_has_all_50_fields(self):
        from dataclasses import asdict, fields

        scene = _make_scene()
        d = asdict(scene)
        field_names = {f.name for f in fields(StoryScene)}
        assert set(d.keys()) == field_names
