"""Tests for backend.scene_graph — shot overrides, director recommendations, production bible."""
from __future__ import annotations

from copy import deepcopy

import pytest

from backend.scene_graph import (
    _normalize_shot_overrides,
    apply_director_recommendation,
    build_production_bible,
)


# ─── _normalize_shot_overrides ────────────────────────────────────────────────


class TestNormalizeShotOverrides:
    def test_non_list_returns_empty(self):
        assert _normalize_shot_overrides(None) == []
        assert _normalize_shot_overrides("invalid") == []
        assert _normalize_shot_overrides(123) == []
        assert _normalize_shot_overrides({}) == []

    def test_empty_list_returns_empty(self):
        assert _normalize_shot_overrides([]) == []

    def test_non_dict_items_skipped(self):
        result = _normalize_shot_overrides(["invalid", 123, None])
        assert result == []

    def test_item_without_shot_order_or_id_skipped(self):
        result = _normalize_shot_overrides([{"label": "test"}])
        assert result == []

    def test_valid_override_with_shot_order(self):
        overrides = [{"shot_order": 1, "label": "开场", "camera_movement": "slow_push_in"}]
        result = _normalize_shot_overrides(overrides)
        assert len(result) == 1
        assert result[0]["shot_order"] == 1
        assert result[0]["label"] == "开场"
        assert result[0]["camera_movement"] == "slow_push_in"

    def test_valid_override_with_shot_id(self):
        overrides = [{"shot_id": "scene_001_shot_01", "duration_seconds": 3.0}]
        result = _normalize_shot_overrides(overrides)
        assert len(result) == 1
        assert result[0]["shot_id"] == "scene_001_shot_01"
        assert result[0]["duration_seconds"] == 3.0

    def test_numeric_values_bounded(self):
        overrides = [{
            "shot_order": 1,
            "duration_seconds": 200.0,  # Max is 120
            "camera_speed": 10.0,  # Max is 5.0
            "zoom": 5.0,  # Max is 3.0
            "center_x": 2.0,  # Max is 1.0
        }]
        result = _normalize_shot_overrides(overrides)
        assert result[0]["duration_seconds"] <= 120.0
        assert result[0]["camera_speed"] <= 5.0
        assert result[0]["zoom"] <= 3.0
        assert result[0]["center_x"] <= 1.0

    def test_numeric_values_minimum_enforced(self):
        overrides = [{
            "shot_order": 1,
            "duration_seconds": 0.01,  # Min is 0.25
            "camera_speed": 0.01,  # Min is 0.1
        }]
        result = _normalize_shot_overrides(overrides)
        assert result[0]["duration_seconds"] >= 0.25
        assert result[0]["camera_speed"] >= 0.1

    def test_empty_string_values_not_included(self):
        overrides = [{"shot_order": 1, "label": "", "caption": ""}]
        result = _normalize_shot_overrides(overrides)
        assert "label" not in result[0]
        assert "caption" not in result[0]

    def test_multiple_overrides_preserved(self):
        overrides = [
            {"shot_order": 1, "label": "第一镜"},
            {"shot_order": 2, "label": "第二镜"},
        ]
        result = _normalize_shot_overrides(overrides)
        assert len(result) == 2


# ─── apply_director_recommendation ───────────────────────────────────────────


class TestApplyDirectorRecommendation:
    def _make_scene(self, **kwargs) -> dict:
        scene = {
            "title": "",
            "visual_prompt": "",
            "dialogue": "",
            "emotion": "",
            "camera_movement": "",
            "sfx_type": "auto",
            "camera_speed": None,
            "audio_manifest": {
                "bgm_style": "",
                "bgm_file": "",
                "bgm_gain_db": "",
                "sfx_trigger": {"file": "", "timestamp_ms": 0, "volume": 0.65},
                "sfx_triggers": [],
            },
        }
        scene.update(kwargs)
        return scene

    def test_impact_token_assigns_dramatic_push(self):
        scene = self._make_scene(dialogue="他一巴掌打了过去")
        apply_director_recommendation(scene)
        assert scene["camera_movement"] == "dramatic_push"

    def test_melancholy_token_assigns_melancholy_pan(self):
        scene = self._make_scene(dialogue="她独自一人在雨夜中回忆过去")
        apply_director_recommendation(scene)
        assert scene["camera_movement"] == "melancholy_pan"

    def test_establishing_token_assigns_establishing_tilt(self):
        scene = self._make_scene(visual_prompt="全景远景，宏伟的宫殿")
        apply_director_recommendation(scene)
        assert scene["camera_movement"] == "establishing_tilt"

    def test_no_matching_token_keeps_empty_camera(self):
        scene = self._make_scene(dialogue="普通的对话内容")
        apply_director_recommendation(scene)
        # No recommendation matched, camera_movement stays empty or unchanged
        assert scene["camera_movement"] in ("", "auto", "static", "slow_push_in")

    def test_dramatic_push_sets_high_speed(self):
        scene = self._make_scene(dialogue="一拳打飞了对手")
        apply_director_recommendation(scene)
        assert scene["camera_speed"] >= 1.35

    def test_melancholy_pan_sets_low_speed(self):
        scene = self._make_scene(dialogue="内心独白，悲伤的回忆")
        apply_director_recommendation(scene)
        assert scene["camera_speed"] <= 0.8

    def test_preserve_explicit_camera_when_set(self):
        scene = self._make_scene(
            dialogue="他一巴掌打了过去",
            camera_movement="custom_camera",
        )
        apply_director_recommendation(scene, preserve_explicit=True)
        # custom_camera is not in auto_cameras set, so it should be preserved
        assert scene["camera_movement"] == "custom_camera"

    def test_sfx_trigger_assigned_for_impact(self):
        scene = self._make_scene(dialogue="巴掌扇了过去")
        apply_director_recommendation(scene)
        trigger = scene["audio_manifest"]["sfx_trigger"]
        assert trigger["file"] == "slap"

    def test_thunder_sfx_for_thunder_token(self):
        scene = self._make_scene(dialogue="一道惊雷劈下")
        apply_director_recommendation(scene)
        trigger = scene["audio_manifest"]["sfx_trigger"]
        assert trigger["file"] == "thunder"

    def test_director_recommendation_metadata_added(self):
        scene = self._make_scene(dialogue="他一拳砸了过去")
        apply_director_recommendation(scene)
        assert "director_recommendation" in scene
        rec = scene["director_recommendation"]
        assert "camera_movement" in rec
        assert "camera_speed" in rec
        assert rec["reason"] == "rule_heuristic"

    def test_camera_speed_bounded(self):
        scene = self._make_scene(dialogue="一拳打飞", camera_speed=100.0)
        apply_director_recommendation(scene)
        assert scene["camera_speed"] <= 3.0
        assert scene["camera_speed"] >= 0.35


# ─── build_production_bible ───────────────────────────────────────────────────


class TestBuildProductionBible:
    def test_returns_expected_structure(self):
        project = {
            "project_id": "test_001",
            "title": "测试项目",
            "style_id": "anime_standard",
            "style_guide": "",
            "characters": [
                {
                    "name": "林晚",
                    "char_id": "c_001",
                    "description": "女主角",
                    "appearance_core": "黑色长发",
                    "clothing_style": "白色连衣裙",
                    "negative_constraints": "",
                    "reference_image_path": "",
                    "reference_meta": {},
                }
            ],
            "scenes": [
                {
                    "scene_id": "scene_001",
                    "order": 1,
                    "title": "开场",
                    "emotion": "neutral",
                    "pacing": "",
                    "scene_intent": "",
                    "subject_focus": "",
                    "characters": ["林晚"],
                }
            ],
        }
        bible = build_production_bible(project)

        assert bible["version"] == 1
        assert bible["project_id"] == "test_001"
        assert bible["title"] == "测试项目"
        assert bible["style_id"] == "anime_standard"
        assert "characters" in bible
        assert "props" in bible
        assert "scene_continuity" in bible
        assert "rules" in bible

    def test_characters_extracted_correctly(self):
        project = {
            "project_id": "test",
            "title": "",
            "style_id": "",
            "characters": [
                {"name": "角色A", "char_id": "c_001", "description": "描述A", "appearance_core": "外貌A", "clothing_style": "", "negative_constraints": "", "reference_image_path": ""},
                {"name": "角色B", "char_id": "c_002", "description": "描述B", "appearance_core": "外貌B", "clothing_style": "", "negative_constraints": "", "reference_image_path": ""},
            ],
            "scenes": [],
        }
        bible = build_production_bible(project)
        assert len(bible["characters"]) == 2
        assert bible["characters"][0]["name"] == "角色A"
        assert bible["characters"][1]["name"] == "角色B"

    def test_scene_continuity_extracted(self):
        project = {
            "project_id": "test",
            "title": "",
            "style_id": "",
            "characters": [],
            "scenes": [
                {"scene_id": "scene_001", "order": 1, "title": "场景1", "emotion": "happy", "pacing": "fast", "scene_intent": "introduce", "subject_focus": "角色", "characters": ["A"]},
                {"scene_id": "scene_002", "order": 2, "title": "场景2", "emotion": "sad", "pacing": "slow", "scene_intent": "conflict", "subject_focus": "", "characters": ["A", "B"]},
            ],
        }
        bible = build_production_bible(project)
        assert len(bible["scene_continuity"]) == 2
        assert bible["scene_continuity"][0]["title"] == "场景1"
        assert bible["scene_continuity"][1]["characters"] == ["A", "B"]

    def test_rules_always_present(self):
        project = {"project_id": "", "title": "", "style_id": "", "characters": [], "scenes": []}
        bible = build_production_bible(project)
        rules = bible["rules"]
        assert rules["preserve_character_identity"] is True
        assert rules["preserve_costume_per_scene"] is True
        assert rules["avoid_identity_drift"] is True

    def test_empty_project_returns_valid_structure(self):
        project = {"project_id": "", "title": "", "style_id": "", "characters": [], "scenes": []}
        bible = build_production_bible(project)
        assert bible["version"] == 1
        assert bible["characters"] == []
        assert bible["scene_continuity"] == []

    def test_non_dict_characters_skipped(self):
        project = {
            "project_id": "",
            "title": "",
            "style_id": "",
            "characters": ["invalid", None, 123],
            "scenes": [],
        }
        bible = build_production_bible(project)
        assert bible["characters"] == []

    def test_non_dict_scenes_skipped(self):
        project = {
            "project_id": "",
            "title": "",
            "style_id": "",
            "characters": [],
            "scenes": ["invalid", None],
        }
        bible = build_production_bible(project)
        assert bible["scene_continuity"] == []

    def test_props_registry_extracted_and_linked_to_scene_continuity(self):
        project = {
            "project_id": "test",
            "title": "",
            "style_id": "",
            "characters": [],
            "props": [
                {
                    "id": "jade_pendant",
                    "name": "Jade Pendant",
                    "summary": "Green pendant on a red cord",
                    "owner_characters": ["Lin"],
                    "scenes": ["scene_002"],
                    "reference_image_path": "props/jade.png",
                    "reference_meta": {"source": "manual"},
                },
                "invalid",
            ],
            "scenes": [
                {"scene_id": "scene_002", "order": 2, "props": ["jade_pendant", "Jade Pendant"]},
            ],
        }

        bible = build_production_bible(project)

        assert bible["props"] == [
            {
                "prop_id": "jade_pendant",
                "name": "Jade Pendant",
                "description": "Green pendant on a red cord",
                "owner_characters": ["Lin"],
                "scenes": ["scene_002"],
                "reference_image_path": "props/jade.png",
                "reference_meta": {"source": "manual"},
            }
        ]
        assert bible["scene_continuity"][0]["props"] == ["jade_pendant", "Jade Pendant"]
