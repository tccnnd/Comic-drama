from __future__ import annotations

import json

from scripts.prototype_quality_scorecard import (
    build_project_entries,
    build_scorecard,
    summarize_entries,
    summarize_scorecard,
)


def _project_payload(project_id: str = "project_a") -> dict:
    return {
        "project_id": project_id,
        "scenes": [
            {
                "scene_id": "scene_001",
                "order": 1,
                "title": "Pressure dialogue",
                "assets": {
                    "image_url": "/scene.png",
                    "image_path": "out/scene.png",
                    "video_url": "/scene.mp4",
                    "video_path": "out/scene.mp4",
                },
                "generation_meta": {
                    "provider_id": "doubao",
                    "provider_label": "Doubao",
                    "backend": "remote",
                    "is_real_video": True,
                    "fallback_used": False,
                    "attempts": 2,
                },
                "shot_plan": {
                    "shots": [
                        {
                            "shot_id": "scene_001_shot_01",
                            "shot_order": 1,
                            "visual_prototype": {
                                "mode": "prototype_lock",
                                "id": "dialogue_pressure_two_shot",
                                "constraints": {
                                    "hard": ["preserve_eyelines"],
                                    "soft": ["background_subordinate"],
                                    "guidelines": ["separate_speakers"],
                                },
                            },
                            "visual_content": {
                                "_source": "prototype",
                                "shot_description": "two people held in a tense frame",
                                "foreground": "speaker in profile",
                                "background": "office wall",
                                "composition": "balanced pressure two-shot",
                                "motion": "static",
                                "focus": "dialogue pressure",
                            },
                        },
                        {
                            "shot_id": "scene_001_shot_02",
                            "shot_order": 2,
                            "visual_prototype": {
                                "mode": "freeform",
                                "id": "",
                                "gap": {"reason": "no_matching_prototype"},
                                "constraints": {"hard": [], "soft": [], "guidelines": []},
                            },
                            "visual_content": {
                                "_source": "rules",
                                "shot_description": "quiet insert",
                            },
                        },
                    ]
                },
            }
        ],
    }


def _write_project(root, payload):
    root.mkdir(parents=True)
    path = root / "project.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_build_project_entries_extracts_scorecard_fields():
    entries = build_project_entries(_project_payload(), "project.json")

    assert len(entries) == 2
    locked = entries[0]
    assert (
        locked["entry_id"]
        == "project_a:scene_001:scene_001_shot_01:prototype_lock:dialogue_pressure_two_shot"
    )
    assert locked["variant"] == "prototype_lock"
    assert locked["prototype_id"] == "dialogue_pressure_two_shot"
    assert locked["constraints"]["hard"] == ["preserve_eyelines"]
    assert locked["visual_content_source"] == "prototype"
    assert locked["output"]["video_url"] == "/scene.mp4"
    assert locked["output"]["video_path"] == "out/scene.mp4"
    assert locked["output"]["image_path"] == "out/scene.png"
    assert locked["generation"]["is_real_video"] is True
    assert locked["scores"]["overall_usable"] is None
    assert locked["review"] == {"reviewer": "", "reviewed_at": "", "evidence": "", "rationale": ""}
    assert locked["decision"] == "unscored"

    freeform = entries[1]
    assert freeform["variant"] == "freeform"
    assert freeform["gap_reason"] == "no_matching_prototype"


def test_summarize_entries_counts_and_averages_scores():
    entries = build_project_entries(_project_payload())
    entries[0]["scores"] = {
        "composition_intent": 4,
        "subject_clarity": 5,
        "constraint_adherence": 4,
        "emotional_fit": 3,
        "overall_usable": 4,
    }
    entries[1]["scores"] = {"overall_usable": 2}

    summary = summarize_entries(entries)

    assert summary["total_entries"] == 2
    assert summary["scoreable_entries"] == 2
    assert summary["missing_visual_evidence"] == 0
    assert summary["scored_entries"] == 2
    assert summary["variant_counts"] == {"freeform": 1, "prototype_lock": 1}
    assert summary["prototype_counts"] == {"dialogue_pressure_two_shot": 1}
    assert summary["average_by_variant"] == {"freeform": 2.0, "prototype_lock": 4.0}
    assert summary["average_by_prototype"] == {"dialogue_pressure_two_shot": 4.0}
    assert summary["average_score"] == 3.0


def test_build_scorecard_reads_workspace_projects(tmp_path):
    workspace = tmp_path / "workspace"
    _write_project(workspace / "project_a", _project_payload("project_a"))
    second = _project_payload("project_b")
    second["scenes"][0]["shot_plan"]["shots"][0]["visual_prototype"]["id"] = "reaction_hold_closeup"
    _write_project(workspace / "project_b", second)

    scorecard = build_scorecard(workspace)

    assert scorecard["version"] == 1
    assert scorecard["summary"]["total_entries"] == 4
    assert scorecard["summary"]["prototype_counts"] == {
        "dialogue_pressure_two_shot": 1,
        "reaction_hold_closeup": 1,
    }


def test_scorecard_counts_video_path_only_as_scoreable():
    payload = _project_payload()
    assets = payload["scenes"][0]["assets"]
    assets.clear()
    assets["video_path"] = "local/video.mp4"

    entries = build_project_entries(payload)
    summary = summarize_entries(entries)

    assert entries[0]["output"]["video_path"] == "local/video.mp4"
    assert summary["scoreable_entries"] == 2
    assert summary["missing_visual_evidence"] == 0


def test_summarize_scorecard_reads_filled_scorecard(tmp_path):
    entries = build_project_entries(_project_payload())
    entries[0]["scores"]["overall_usable"] = 5
    scorecard_file = tmp_path / "scorecard.json"
    scorecard_file.write_text(json.dumps({"entries": entries}), encoding="utf-8")

    report = summarize_scorecard(scorecard_file)

    assert report["summary"]["total_entries"] == 2
    assert report["summary"]["scored_entries"] == 1
    assert report["summary"]["average_score"] == 5.0


def test_legacy_project_without_shot_plan_has_empty_scorecard():
    entries = build_project_entries({"project_id": "legacy", "scenes": [{"order": 1}]})
    assert entries == []
    assert summarize_entries(entries)["total_entries"] == 0
