"""Tests for backend.character_manager — character card, prompt, and voice logic."""
from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.run_workflow import StoryScene
from backend.character_manager import (
    normalize_character_card,
    build_initial_characters,
    merge_character_configs,
    remove_placeholder_scene_characters,
    compile_character_prompt,
    scene_with_inherited_voice,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_story_scene(
    scene: int = 1,
    characters: list[str] | None = None,
    speaker: str = "",
    voice_profile: str = "",
    voice_engine: str = "",
    voice_id: str = "",
    reference_audio_path: str = "",
    reference_text: str = "",
    emotion: str = "",
    voice_rate: float = 1.0,
    voice_pitch: float = 0.0,
    voice_volume: float = 1.0,
) -> StoryScene:
    return StoryScene(
        scene=scene,
        duration=4.0,
        title="测试分镜",
        visual="视觉描述",
        dialogue="对话内容",
        camera="slow_push_in",
        emotion=emotion,
        characters=characters or ["角色A"],
        bg_color="0x182033",
        accent_color="0x4ea3ff",
        speaker=speaker,
        voice_profile=voice_profile,
        voice_engine=voice_engine,
        voice_id=voice_id,
        reference_audio_path=reference_audio_path,
        reference_text=reference_text,
        voice_rate=voice_rate,
        voice_pitch=voice_pitch,
        voice_volume=voice_volume,
    )


# ─── normalize_character_card ─────────────────────────────────────────────────


class TestNormalizeCharacterCard:
    def test_normalizes_all_string_fields(self):
        card = {
            "char_id": "  c_001  ",
            "name": "  林晚  ",
            "appearance_core": "  黑色长发  ",
            "clothing_style": "  白色连衣裙  ",
            "negative_constraints": "  不要改变  ",
            "description": "  温柔  ",
            "voice_profile": "  female_lead  ",
        }
        result = normalize_character_card(card)
        assert result["char_id"] == "c_001"
        assert result["name"] == "林晚"
        assert result["appearance_core"] == "黑色长发"
        assert result["clothing_style"] == "白色连衣裙"
        assert result["negative_constraints"] == "不要改变"
        assert result["description"] == "温柔"
        assert result["voice_profile"] == "female_lead"

    def test_normalizes_meta_field(self):
        card = {"name": "test", "meta": {"age": "25", "role": "主角"}}
        result = normalize_character_card(card)
        assert result["meta"]["age"] == "25"
        assert result["meta"]["role"] == "主角"

    def test_missing_meta_gets_default(self):
        card = {"name": "test"}
        result = normalize_character_card(card)
        assert result["meta"] == {"age": "", "role": ""}

    def test_none_values_become_empty_strings(self):
        card = {
            "name": None,
            "char_id": None,
            "appearance_core": None,
            "voice_id": None,
        }
        result = normalize_character_card(card)
        assert result["name"] == ""
        assert result["char_id"] == ""
        assert result["appearance_core"] == ""
        assert result["voice_id"] == ""

    def test_suggested_voice_engine_defaults_to_edge(self):
        card = {"name": "test"}
        result = normalize_character_card(card)
        assert result["suggested_voice_engine"] == "edge"

    def test_reference_meta_is_dict(self):
        card = {"name": "test", "reference_meta": {"crop_method": "face"}}
        result = normalize_character_card(card)
        assert result["reference_meta"] == {"crop_method": "face"}

    def test_non_dict_reference_meta_becomes_empty_dict(self):
        card = {"name": "test", "reference_meta": "invalid"}
        result = normalize_character_card(card)
        assert result["reference_meta"] == {}


# ─── build_initial_characters ─────────────────────────────────────────────────


class TestBuildInitialCharacters:
    def test_extracts_unique_characters_from_scenes(self):
        scenes = [
            _make_story_scene(scene=1, characters=["林晚", "陆远"]),
            _make_story_scene(scene=2, characters=["陆远", "秘书"]),
        ]
        result = build_initial_characters(scenes)
        names = [c["name"] for c in result]
        assert "林晚" in names
        assert "陆远" in names
        assert "秘书" in names
        assert len(result) == 3

    def test_assigns_sequential_char_ids(self):
        scenes = [_make_story_scene(scene=1, characters=["A", "B", "C"])]
        result = build_initial_characters(scenes)
        ids = [c["char_id"] for c in result]
        assert ids == ["c_001", "c_002", "c_003"]

    def test_preserves_order_of_first_appearance(self):
        scenes = [
            _make_story_scene(scene=1, characters=["第一个", "第二个"]),
            _make_story_scene(scene=2, characters=["第三个"]),
        ]
        result = build_initial_characters(scenes)
        names = [c["name"] for c in result]
        assert names == ["第一个", "第二个", "第三个"]

    def test_uses_role_data_when_provided(self):
        scenes = [_make_story_scene(scene=1, characters=["林晚"])]
        roles = [{"name": "林晚", "appearance_core": "黑色长发", "summary": "女主角"}]
        result = build_initial_characters(scenes, roles=roles)
        assert result[0]["appearance_core"] == "黑色长发"
        assert result[0]["description"] == "女主角"

    def test_empty_scenes_returns_empty_list(self):
        result = build_initial_characters([])
        assert result == []

    def test_skips_empty_character_names(self):
        scenes = [_make_story_scene(scene=1, characters=["", "  ", "有效名"])]
        result = build_initial_characters(scenes)
        names = [c["name"] for c in result]
        assert "有效名" in names
        assert len(result) == 1


# ─── merge_character_configs ──────────────────────────────────────────────────


class TestMergeCharacterConfigs:
    def test_preserves_existing_char_id(self):
        existing = [{"char_id": "custom_id", "name": "林晚", "voice_id": "custom_voice"}]
        scenes = [_make_story_scene(scene=1, characters=["林晚"])]
        result = merge_character_configs(existing, scenes)
        assert result[0]["char_id"] == "custom_id"

    def test_preserves_existing_reference_image(self):
        existing = [{"name": "林晚", "reference_image_path": "characters/ref.png"}]
        scenes = [_make_story_scene(scene=1, characters=["林晚"])]
        result = merge_character_configs(existing, scenes)
        assert result[0]["reference_image_path"] == "characters/ref.png"

    def test_adds_new_characters_from_scenes(self):
        existing = [{"name": "林晚", "char_id": "c_001"}]
        scenes = [
            _make_story_scene(scene=1, characters=["林晚"]),
            _make_story_scene(scene=2, characters=["新角色"]),
        ]
        result = merge_character_configs(existing, scenes)
        names = [c["name"] for c in result]
        assert "林晚" in names
        assert "新角色" in names

    def test_empty_existing_returns_fresh_characters(self):
        scenes = [_make_story_scene(scene=1, characters=["角色A"])]
        result = merge_character_configs([], scenes)
        assert len(result) == 1
        assert result[0]["name"] == "角色A"

    def test_preserves_voice_settings(self):
        existing = [{"name": "林晚", "voice_id": "custom_voice", "voice_rate": 1.5}]
        scenes = [_make_story_scene(scene=1, characters=["林晚"])]
        result = merge_character_configs(existing, scenes)
        assert result[0]["voice_id"] == "custom_voice"
        assert result[0]["voice_rate"] == 1.5


# ─── remove_placeholder_scene_characters ──────────────────────────────────────


class TestRemovePlaceholderSceneCharacters:
    def test_removes_generic_names_when_roles_exist(self):
        scenes = [_make_story_scene(scene=1, characters=["主角", "林晚"], speaker="主角")]
        roles = [{"name": "林晚"}]
        result = remove_placeholder_scene_characters(scenes, roles=roles)
        assert "主角" not in result[0].characters
        assert "林晚" in result[0].characters

    def test_clears_placeholder_speaker(self):
        scenes = [_make_story_scene(scene=1, characters=["林晚"], speaker="旁白")]
        roles = [{"name": "林晚"}]
        result = remove_placeholder_scene_characters(scenes, roles=roles)
        assert result[0].speaker == ""

    def test_keeps_placeholder_if_in_roles(self):
        """If a placeholder name is explicitly in roles, it should be kept."""
        scenes = [_make_story_scene(scene=1, characters=["主角", "林晚"])]
        roles = [{"name": "主角"}, {"name": "林晚"}]
        result = remove_placeholder_scene_characters(scenes, roles=roles)
        # "主角" is in role_map, so it's NOT a placeholder
        assert "主角" in result[0].characters

    def test_no_roles_returns_unchanged(self):
        scenes = [_make_story_scene(scene=1, characters=["主角", "林晚"])]
        result = remove_placeholder_scene_characters(scenes, roles=None)
        assert result[0].characters == ["主角", "林晚"]


# ─── compile_character_prompt ─────────────────────────────────────────────────


class TestCompileCharacterPrompt:
    def test_generates_positive_prompt_with_character_info(self):
        scene = {"title": "测试场景", "character_descriptions": ""}
        refs = [
            {
                "char_id": "c_001",
                "name": "林晚",
                "meta": {"age": "22", "role": "女主"},
                "appearance_core": "黑色长发",
                "clothing_style": "白色连衣裙",
                "description": "温柔的女主角",
                "negative_constraints": "不要改变发型",
            }
        ]
        positive, negative = compile_character_prompt(scene, refs)
        assert "林晚" in positive
        assert "黑色长发" in positive
        assert "白色连衣裙" in positive
        assert "不要改变发型" in negative

    def test_includes_scene_title_in_positive(self):
        scene = {"title": "初次相遇", "character_descriptions": ""}
        refs = [{"char_id": "c_001", "name": "角色", "meta": {}, "appearance_core": "", "clothing_style": "", "description": "", "negative_constraints": ""}]
        positive, _ = compile_character_prompt(scene, refs)
        assert "初次相遇" in positive

    def test_includes_character_descriptions(self):
        scene = {"title": "", "character_descriptions": "两人对峙"}
        refs = [{"char_id": "c_001", "name": "角色", "meta": {}, "appearance_core": "", "clothing_style": "", "description": "", "negative_constraints": ""}]
        positive, _ = compile_character_prompt(scene, refs)
        assert "两人对峙" in positive

    def test_limits_to_four_characters(self):
        scene = {"title": "", "character_descriptions": ""}
        refs = [
            {"char_id": f"c_{i:03d}", "name": f"角色{i}", "meta": {}, "appearance_core": "外貌", "clothing_style": "", "description": "", "negative_constraints": ""}
            for i in range(1, 7)
        ]
        positive, _ = compile_character_prompt(scene, refs)
        # Only first 4 characters should be included
        assert "角色5" not in positive
        assert "角色6" not in positive

    def test_empty_refs_returns_empty_strings(self):
        scene = {"title": "", "character_descriptions": ""}
        positive, negative = compile_character_prompt(scene, [])
        assert positive == ""
        assert negative == ""

    def test_negative_prompt_includes_identity_preservation(self):
        scene = {"title": "", "character_descriptions": ""}
        refs = [{"char_id": "c_001", "name": "林晚", "meta": {}, "appearance_core": "", "clothing_style": "", "description": "", "negative_constraints": ""}]
        _, negative = compile_character_prompt(scene, refs)
        assert "林晚" in negative
        assert "辨识度" in negative


# ─── scene_with_inherited_voice ───────────────────────────────────────────────


class TestSceneWithInheritedVoice:
    def test_inherits_voice_from_character(self):
        project = {
            "characters": [
                {
                    "name": "林晚",
                    "voice_profile": "female_lead",
                    "voice_engine": "edge",
                    "voice_id": "zh-CN-XiaoxiaoNeural",
                    "reference_audio_path": "/audio/ref.wav",
                    "reference_text": "参考文本",
                    "emotion": "happy",
                    "voice_rate": 1.2,
                    "voice_pitch": 0.5,
                    "voice_volume": 0.9,
                }
            ]
        }
        scene = {
            "speaker": "林晚",
            "characters": ["林晚"],
            "voice_profile": "",
            "voice_engine": "",
            "voice_id": "",
            "reference_audio_path": "",
            "reference_text": "",
            "emotion": "",
            "voice_rate": "",
            "voice_pitch": "",
            "voice_volume": "",
        }
        result = scene_with_inherited_voice(project, scene)
        assert result["voice_engine"] == "edge"
        assert result["voice_id"] == "zh-CN-XiaoxiaoNeural"
        assert result["voice_rate"] == 1.2

    def test_does_not_override_existing_scene_values(self):
        project = {
            "characters": [
                {
                    "name": "林晚",
                    "voice_engine": "edge",
                    "voice_id": "zh-CN-XiaoxiaoNeural",
                }
            ]
        }
        scene = {
            "speaker": "林晚",
            "characters": ["林晚"],
            "voice_engine": "local",
            "voice_id": "custom_voice",
            "voice_profile": "",
            "reference_audio_path": "",
            "reference_text": "",
            "emotion": "",
            "voice_rate": "",
            "voice_pitch": "",
            "voice_volume": "",
        }
        result = scene_with_inherited_voice(project, scene)
        assert result["voice_engine"] == "local"
        assert result["voice_id"] == "custom_voice"

    def test_no_matching_character_returns_unchanged(self):
        project = {"characters": [{"name": "其他角色", "voice_engine": "edge"}]}
        scene = {
            "speaker": "未知角色",
            "characters": ["未知角色"],
            "voice_engine": "",
            "voice_id": "",
            "voice_profile": "",
            "reference_audio_path": "",
            "reference_text": "",
            "emotion": "",
            "voice_rate": "",
            "voice_pitch": "",
            "voice_volume": "",
        }
        result = scene_with_inherited_voice(project, scene)
        assert result["voice_engine"] == ""

    def test_does_not_mutate_original_scene(self):
        project = {
            "characters": [{"name": "林晚", "voice_engine": "edge", "voice_id": "test"}]
        }
        scene = {
            "speaker": "林晚",
            "characters": ["林晚"],
            "voice_engine": "",
            "voice_id": "",
            "voice_profile": "",
            "reference_audio_path": "",
            "reference_text": "",
            "emotion": "",
            "voice_rate": "",
            "voice_pitch": "",
            "voice_volume": "",
        }
        original_scene = deepcopy(scene)
        scene_with_inherited_voice(project, scene)
        assert scene == original_scene
