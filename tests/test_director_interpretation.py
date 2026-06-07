import json

from scripts.director_classifier import (
    VISUAL_CONTENT_FIELDS,
    build_director_plan,
    build_shot_visual_content,
)
from scripts.run_workflow import build_shot_plan


def test_build_director_plan_uses_classified_scene_fields():
    scene = {
        "scene": 1,
        "title": "Ticket booth threat",
        "visual_prompt": "A detonator sits beside a nervous hand at the ticket window.",
        "scene_intent": "action",
        "emotion_tone": "tension",
        "pacing": "fast",
        "subject_focus": "single_character",
        "camera_movement": "dramatic_push",
        "director_meta": {"source": "rules"},
    }

    plan = build_director_plan(scene)

    assert plan["version"] == 1
    assert plan["source"] == "rules"
    assert "kinetic cause and effect" in plan["dramatic_intent"]
    assert "unresolved danger" in plan["emotional_target"]
    assert "lead character" in plan["narrative_focus"]
    assert "Ticket booth threat" in plan["rationale"]


def test_build_director_plan_defaults_for_legacy_scene():
    plan = build_director_plan({"title": "Legacy scene"})

    assert plan["version"] == 1
    assert plan["source"] == "default"
    assert plan["dramatic_intent"]
    assert plan["emotional_target"]
    assert plan["narrative_focus"]
    assert plan["rationale"]


def test_build_shot_visual_content_maps_environment_and_camera_language():
    scene = {
        "visual": "Rain fills the empty alley while the getaway car waits.",
        "scene_intent": "establishing",
        "emotion_tone": "fear",
        "pacing": "slow",
        "subject_focus": "environment",
        "camera_movement": "pull_back",
    }
    shot = {"duration": 3, "camera_movement": "pull_back"}

    result = build_shot_visual_content(scene, shot)
    visual_content = result["visual_content"]

    assert result["shot_size"] == "extreme_wide"
    assert "pull back" in result["camera_language"]["movement"]
    assert "space and stakes" in result["dramatic_intent"]
    assert set(VISUAL_CONTENT_FIELDS) == set(visual_content)
    assert "Rain fills the empty alley" in visual_content["shot_description"]
    assert "background geography" in visual_content["background"]
    assert "negative space" in visual_content["lighting"]


def test_build_shot_visual_content_handles_empty_shot():
    scene = {
        "dialogue": "We only have one chance.",
        "scene_intent": "dialogue",
        "emotion_tone": "calm",
        "subject_focus": "two_shot",
        "camera_movement": "static",
    }

    result = build_shot_visual_content(scene, {})

    assert result["shot_size"] == "medium"
    assert result["dramatic_intent"]
    assert result["camera_language"]["movement"]
    assert set(VISUAL_CONTENT_FIELDS) == set(result["visual_content"])
    assert "We only have one chance" in result["visual_content"]["shot_description"]


def test_build_shot_plan_attaches_visual_content_to_each_shot():
    scene = {
        "scene_id": "scene_001",
        "order": 1,
        "duration_seconds": 4.0,
        "visual_prompt": "A bomb timer glows beneath the ticket counter.",
        "scene_intent": "action",
        "emotion_tone": "tension",
        "pacing": "fast",
        "subject_focus": "single_character",
        "camera_movement": "dramatic_push",
        "temporal_spec": {
            "shots": [
                {"duration_seconds": 1.5, "beat_type": "detail", "camera_movement": "dramatic_push"},
                {"duration_seconds": 2.5, "beat_type": "reaction", "camera_movement": "static"},
            ]
        },
    }

    plan = build_shot_plan(scene)

    assert plan["source"] == "temporal_spec"
    assert plan["shot_count"] == 2
    for shot in plan["shots"]:
        assert shot["shot_size"]
        assert shot["dramatic_intent"]
        assert set(VISUAL_CONTENT_FIELDS) == set(shot["visual_content"])
        assert set(shot["camera_language"]) == {"movement", "lens", "depth_of_field", "framing"}


def test_load_project_and_snapshot_normalize_legacy_director_interpretation(tmp_path, monkeypatch):
    import backend.project_models as project_models
    import backend.project_runtime as project_runtime

    workspace = tmp_path / "workspace"
    project_id = "legacy_director_interpretation"
    project_root = workspace / project_id
    project_root.mkdir(parents=True)
    (project_root / "characters").mkdir()
    (project_root / "scenes").mkdir()
    payload = {
        "project_id": project_id,
        "title": "Legacy Director Interpretation",
        "characters": [],
        "scenes": [
            {
                "scene_id": "scene_001",
                "order": 1,
                "duration_seconds": 4.0,
                "visual_prompt": "A lone guard watches the rain-heavy gate.",
                "scene_intent": "establishing",
                "emotion_tone": "fear",
                "subject_focus": "environment",
                "assets": {},
                "shot_plan": {
                    "version": 1,
                    "scene_id": "scene_001",
                    "scene_order": 1,
                    "duration_seconds": 4.0,
                    "shot_count": 1,
                    "source": "legacy",
                    "shots": [
                        {
                            "shot_id": "scene_001_shot_01",
                            "shot_order": 1,
                            "start_seconds": 0.0,
                            "duration_seconds": 4.0,
                            "end_seconds": 4.0,
                        }
                    ],
                },
            }
        ],
    }
    (project_root / "project.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(project_models, "WORKSPACE", workspace)
    monkeypatch.setattr(project_runtime, "WORKSPACE", workspace)

    loaded = project_runtime.load_project(project_id)
    scene = loaded["scenes"][0]

    assert scene["director_plan"]["source"] == "rules"
    assert scene["shot_plan"]["source"] == "legacy"
    assert set(VISUAL_CONTENT_FIELDS) == set(scene["shot_plan"]["shots"][0]["visual_content"])

    snapshot = project_runtime.project_snapshot(loaded)
    snapshot_scene = snapshot["scenes"][0]
    assert snapshot_scene["director_plan"]["dramatic_intent"]
    assert snapshot_scene["shot_plan"]["shots"][0]["camera_language"]["movement"]
