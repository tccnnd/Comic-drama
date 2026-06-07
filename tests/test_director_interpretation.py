import json

from scripts.director_classifier import (
    VISUAL_CONTENT_FIELDS,
    VISUAL_PROTOTYPE_IDS,
    build_director_plan,
    build_shot_visual_content,
)
from scripts.run_workflow import build_shot_plan
from scripts.run_workflow import build_scene_video_prompts, StoryScene


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
    assert plan["emotional_curve"] == "impact_spike"
    assert plan["dramatic_weight"] >= 0.9
    assert plan["shot_archetypes"][0]["prototype_id"] == "danger_intro_extreme_closeup"
    assert plan["shot_archetypes"][0]["constraints"]["hard"]
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
    assert result["visual_prototype"]["id"] == "isolation_single_wide"
    assert result["visual_prototype"]["mode"] == "prototype_lock"
    assert set(result["visual_prototype"]["constraints"]) == {"hard", "soft", "guidelines"}
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
    assert result["visual_prototype"]["id"] == "dialogue_pressure_two_shot"
    assert set(VISUAL_CONTENT_FIELDS) == set(result["visual_content"])
    assert "We only have one chance" in result["visual_content"]["shot_description"]


def test_build_shot_visual_content_records_freeform_gap_when_no_prototype_matches():
    scene = {
        "visual_prompt": "A quiet cup of tea sits beside a closed notebook.",
        "scene_intent": "transition",
        "emotion_tone": "calm",
        "pacing": "slow",
        "subject_focus": "single_character",
        "camera_movement": "static",
    }

    result = build_shot_visual_content(scene, {})

    assert result["visual_prototype"]["mode"] == "freeform"
    assert result["visual_prototype"]["id"] == ""
    assert result["visual_prototype"]["gap"]["reason"]
    assert result["visual_prototype"]["constraints"] == {"hard": [], "soft": [], "guidelines": []}


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
        assert shot["visual_prototype"]["id"] in VISUAL_PROTOTYPE_IDS
        assert shot["visual_prototype"]["constraints"]["hard"]
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
    assert scene["director_plan"]["shot_archetypes"][0]["prototype_id"] == "isolation_single_wide"
    assert scene["shot_plan"]["shots"][0]["visual_prototype"]["id"] == "isolation_single_wide"
    assert set(VISUAL_CONTENT_FIELDS) == set(scene["shot_plan"]["shots"][0]["visual_content"])

    snapshot = project_runtime.project_snapshot(loaded)
    snapshot_scene = snapshot["scenes"][0]
    assert snapshot_scene["director_plan"]["dramatic_intent"]
    assert snapshot_scene["shot_plan"]["shots"][0]["camera_language"]["movement"]


def test_build_scene_video_prompts_uses_visual_content_as_primary_source(tmp_path):
    scene = StoryScene(
        scene=1,
        title="Detonator Closeup",
        duration=4.0,
        visual="legacy visual should not drive this prompt",
        dialogue="SECRET_DIALOGUE_SHOULD_NOT_DRIVE_VISUALS",
        camera="slow_push",
        emotion="tension",
        characters=["Lead"],
        bg_color="0x182033",
        accent_color="0x4ea3ff",
    )
    scene.shot_plan = {
        "version": 1,
        "scene_id": "scene_001",
        "scene_order": 1,
        "duration_seconds": 4.0,
        "shot_count": 1,
        "source": "test",
        "shots": [
            {
                "shot_id": "scene_001_shot_01",
                "shot_order": 1,
                "shot_size": "extreme_close_up",
                "dramatic_intent": "hold on the decisive prop before the choice",
                "camera_language": {
                    "movement": "locked-off frame with a small pressure push",
                    "lens": "telephoto macro compression",
                    "depth_of_field": "shallow depth of field",
                    "framing": "detail dominates the frame",
                },
                "visual_prototype": {
                    "version": 1,
                    "mode": "prototype_lock",
                    "id": "danger_intro_extreme_closeup",
                    "params": {"object": "red detonator", "environment": "ticket booth"},
                    "constraints": {
                        "hard": ["object_dominates_frame"],
                        "soft": ["no_environment_pan"],
                        "guidelines": ["color_contrast_between_object_and_background"],
                    },
                    "source": "test",
                },
                "visual_content": {
                    "shot_description": "extreme close-up of a red detonator light",
                    "foreground": "thumb hovering over the trigger",
                    "midground": "scratched ticket-counter glass",
                    "background": "panicked crowd blurred into color streaks",
                    "composition": "detonator centered with shallow negative space",
                    "motion": "fixed camera, tiny hand tremor",
                    "lighting": "narrow red practical light",
                    "focus": "audience attention stays on the trigger decision",
                },
            }
        ],
    }

    positive, negative = build_scene_video_prompts(scene, 4.0, tmp_path)

    assert "visual_content is the primary visual source" in positive
    assert "prototype_id:" in positive
    assert "hard_constraints:" in positive
    assert "foreground: thumb hovering over the trigger" in positive
    assert "background: panicked crowd blurred into color streaks" in positive
    assert "composition: detonator centered with shallow negative space" in positive
    assert "motion: fixed camera, tiny hand tremor" in positive
    assert "focus: audience attention stays on the trigger decision" in positive
    assert "SECRET_DIALOGUE_SHOULD_NOT_DRIVE_VISUALS" not in positive
    assert "worst quality" in negative


def test_build_scene_video_prompts_legacy_fallback_without_visual_content(tmp_path):
    scene = StoryScene(
        scene=2,
        title="Legacy Prompt",
        duration=3.0,
        visual="legacy alley visual anchor with rain and neon",
        dialogue="Lead: keep moving",
        camera="static",
        emotion="calm",
        characters=["Lead"],
        bg_color="0x182033",
        accent_color="0x4ea3ff",
    )
    scene.shot_plan = {
        "version": 1,
        "scene_id": "scene_002",
        "scene_order": 2,
        "shot_count": 1,
        "source": "legacy",
        "shots": [{"shot_id": "scene_002_shot_01", "shot_order": 1}],
    }

    positive, _ = build_scene_video_prompts(scene, 3.0, tmp_path)

    assert "legacy alley visual anchor with rain and neon" in positive
    assert "visual_content is the primary visual source" not in positive
