from __future__ import annotations

import json

from scripts.prototype_gap_report import build_report, discover_project_files, summarize_project


def _project_payload(project_id: str = "proj_001") -> dict:
    return {
        "project_id": project_id,
        "scenes": [
            {
                "scene_id": "scene_001",
                "order": 1,
                "shot_plan": {
                    "shots": [
                        {
                            "shot_id": "scene_001_shot_01",
                            "visual_prototype": {
                                "mode": "prototype_lock",
                                "id": "dialogue_pressure_two_shot",
                                "params": {},
                                "constraints": {"hard": ["two_subjects_visible"], "soft": [], "guidelines": []},
                            },
                        },
                        {
                            "shot_id": "scene_001_shot_02",
                            "visual_prototype": {
                                "mode": "freeform",
                                "id": "",
                                "gap": {"reason": "no_matching_prototype"},
                                "constraints": {"hard": [], "soft": [], "guidelines": []},
                            },
                        },
                    ]
                },
            }
        ],
    }


def _write_project(root, payload):
    root.mkdir(parents=True)
    project_file = root / "project.json"
    project_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return project_file


def test_summarize_project_counts_prototype_and_gap_entries():
    report = summarize_project(_project_payload())

    assert report["total_shots"] == 2
    assert report["prototype_lock"] == 1
    assert report["freeform"] == 1
    assert report["unknown"] == 0
    assert report["prototype_ids"] == {"dialogue_pressure_two_shot": 1}
    assert report["gap_reasons"] == {"no_matching_prototype": 1}
    assert report["scenes_with_gaps"] == [
        {
            "project_id": "proj_001",
            "scene_id": "scene_001",
            "scene_order": 1,
            "freeform_shots": ["scene_001_shot_02"],
            "gap_reasons": {"no_matching_prototype": 1},
        }
    ]


def test_build_report_reads_project_json_input(tmp_path):
    project_file = _write_project(tmp_path / "project_a", _project_payload("project_a"))

    report = build_report(project_file)

    assert report["total_shots"] == 2
    assert report["prototype_lock"] == 1
    assert report["freeform"] == 1
    assert report["projects"][0]["project_id"] == "project_a"
    assert report["projects"][0]["source_path"].endswith("project.json")


def test_build_report_reads_workspace_project_directory(tmp_path):
    project_root = tmp_path / "workspace" / "project_b"
    _write_project(project_root, _project_payload("project_b"))

    assert discover_project_files(project_root) == [project_root.resolve() / "project.json"]

    report = build_report(project_root)

    assert report["total_shots"] == 2
    assert report["prototype_ids"] == {"dialogue_pressure_two_shot": 1}
    assert report["gap_reasons"] == {"no_matching_prototype": 1}


def test_build_report_reads_workspace_with_multiple_projects(tmp_path):
    workspace = tmp_path / "workspace"
    _write_project(workspace / "project_a", _project_payload("project_a"))
    second = _project_payload("project_b")
    second["scenes"][0]["shot_plan"]["shots"][0]["visual_prototype"]["id"] = "reaction_hold_closeup"
    _write_project(workspace / "project_b", second)

    report = build_report(workspace)

    assert report["total_shots"] == 4
    assert report["prototype_lock"] == 2
    assert report["freeform"] == 2
    assert report["prototype_ids"] == {
        "dialogue_pressure_two_shot": 1,
        "reaction_hold_closeup": 1,
    }
    assert report["gap_reasons"] == {"no_matching_prototype": 2}
    assert [project["project_id"] for project in report["projects"]] == ["project_a", "project_b"]


def test_legacy_missing_visual_prototype_is_counted_as_unknown():
    payload = {
        "project_id": "legacy",
        "scenes": [
            {
                "scene_id": "scene_001",
                "shot_plan": {
                    "shots": [
                        {"shot_id": "legacy_shot_01"},
                        {"shot_id": "legacy_shot_02", "visual_prototype": None},
                        {"shot_id": "legacy_shot_03", "visual_prototype": {"mode": "unexpected"}},
                    ]
                },
            }
        ],
    }

    report = summarize_project(payload)

    assert report["total_shots"] == 3
    assert report["prototype_lock"] == 0
    assert report["freeform"] == 0
    assert report["unknown"] == 3
    assert report["prototype_ids"] == {}
    assert report["gap_reasons"] == {}
    assert report["scenes_with_gaps"] == []
