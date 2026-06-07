from scripts.director_classifier import (
    VISUAL_CONTENT_FIELDS,
    build_director_plan,
    build_shot_visual_content,
)


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
