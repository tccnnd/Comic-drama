"""Direct unit tests for backend.project_runtime.

Covers core CRUD (create/load/save/list/delete), project_snapshot,
runtime updates, scene/character/project field updates, and
split/merge/restore operations. Filesystem is isolated via tmp_path
with both project_models.WORKSPACE and project_runtime.WORKSPACE
patched to the same temp directory.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.run_workflow import StoryScene
from backend import project_runtime
from backend.project_runtime import (
    create_project,
    load_project,
    save_project,
    list_projects,
    delete_project,
    project_snapshot,
    update_runtime,
    update_scene_fields,
    update_character_fields,
    update_project_fields,
    split_scene,
    merge_scene_with_next,
    restore_scene_snapshot,
    capture_scene_snapshot,
    latest_scene_snapshot,
    apply_project_episode_pacing,
    normalize_scene_pacing_update,
    reconstruct_story_text_from_scenes,
    _set_runtime,
    _renumber_scenes,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def runtime_workspace(tmp_path):
    """Patch WORKSPACE in both project_models and project_runtime to a temp dir."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with patch("backend.project_models.WORKSPACE", workspace), \
         patch("backend.project_runtime.WORKSPACE", workspace):
        yield workspace


def _make_scene(order: int, title: str = "", dialogue: str = "", duration: float = 4.0) -> dict:
    return {
        "scene_id": f"scene_{order:03d}",
        "order": order,
        "title": title or f"场景 {order}",
        "visual_prompt": f"画面 {order}",
        "dialogue": dialogue,
        "speaker": "",
        "camera_movement": "slow_push_in",
        "emotion": "neutral",
        "duration_seconds": duration,
        "characters": [],
        "voice_engine": "edge",
        "voice_id": "",
        "voice_rate": 1.0,
        "voice_pitch": 0.0,
        "voice_volume": 1.0,
        "camera_speed": 1.0,
        "sfx_type": "auto",
        "audio_manifest": {
            "bgm_style": "",
            "bgm_file": "",
            "bgm_gain_db": "",
            "sfx_trigger": {"file": "", "timestamp_ms": 0, "volume": 0.65},
            "sfx_triggers": [],
        },
        "assets": {
            "status": "pending",
            "versions": {"image": 0, "audio": 0, "video": 0},
            "image_path": "",
            "image_url": "",
            "audio_path": "",
            "audio_url": "",
            "video_path": "",
            "video_url": "",
        },
        "history": [],
    }


def _write_project(workspace: Path, project_id: str, project: dict) -> Path:
    """Write a project.json directly to the workspace."""
    project_root = workspace / project_id
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "scenes").mkdir(exist_ok=True)
    (project_root / "characters").mkdir(exist_ok=True)
    (project_root / "output").mkdir(exist_ok=True)
    project["project_id"] = project_id
    project_file = project_root / "project.json"
    project_file.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    return project_root


def _make_minimal_project(project_id: str = "proj_test_001", scene_count: int = 3) -> dict:
    return {
        "project_id": project_id,
        "title": "测试漫剧",
        "story_text": "这是一个测试故事。",
        "style_id": "anime_standard",
        "style_guide": "",
        "settings": {
            "aspect_ratio": "9:16",
            "global_style": "竖屏动态漫画",
            "planner": "rule",
            "scene_count": scene_count,
            "keyframe_provider": "local",
            "video_provider": "local",
            "voice_provider": "edge",
            "video_render_granularity": {"value": "scene", "label": "场景级"},
            "subtitle_style": {"font": "", "size": 0, "color": "", "bg": ""},
            "audio_style": {"bgm_gain_db": 0, "sfx_volume": 0.65},
            "episode_pacing": {"preset": "classic_four_act"},
        },
        "characters": [],
        "scenes": [_make_scene(i) for i in range(1, scene_count + 1)],
        "runtime": {
            "status": "idle",
            "progress": 0,
            "stage": "draft",
            "message": "Draft ready",
            "updated_at": "2026-01-01T00:00:00Z",
        },
        "output": {
            "final_video_path": "",
            "final_video_url": "",
            "subtitles_path": "",
            "subtitles_url": "",
            "status": "idle",
        },
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }


def _mock_storyboard(scene_count: int = 3):
    """Return a mock build_storyboard that returns scene_count scenes."""
    scenes = [
        StoryScene(
            scene=i,
            duration=4.0,
            title=f"场景 {i}",
            visual=f"画面 {i}",
            dialogue=f"对白 {i}",
            camera="slow_push_in",
            emotion="neutral",
            characters=[],
            bg_color="#000000",
            accent_color="#FFFFFF",
        )
        for i in range(1, scene_count + 1)
    ]
    return scenes, "rule"


# ---------------------------------------------------------------------------
# create_project
# ---------------------------------------------------------------------------

class TestCreateProject:
    def test_creates_project_with_valid_fields(self, runtime_workspace):
        scenes, planner = _mock_storyboard(2)
        with patch("backend.project_runtime.build_storyboard", return_value=(scenes, planner)):
            project = create_project(
                title="我的测试项目",
                story_text="故事内容",
                planner="rule",
                scene_count=2,
                keyframe_provider="local",
                video_provider="local",
                voice_provider="edge",
            )
        assert project["project_id"].startswith("proj_")
        assert project["title"] == "我的测试项目"
        assert project["story_text"] == "故事内容"
        assert len(project["scenes"]) == 2
        assert project["settings"]["planner"] == "rule"
        assert project["settings"]["keyframe_provider"] == "local"
        assert project["runtime"]["status"] == "idle"

    def test_project_id_format(self, runtime_workspace):
        scenes, planner = _mock_storyboard(1)
        with patch("backend.project_runtime.build_storyboard", return_value=(scenes, planner)):
            project = create_project("T", "story", "rule", 1, "local", "local", "edge")
        assert project["project_id"].startswith("proj_")
        # Format: proj_YYYYMMDD_HHMMSS_hex6
        parts = project["project_id"].split("_")
        assert len(parts) == 4
        assert parts[0] == "proj"

    def test_empty_title_derives_from_story(self, runtime_workspace):
        scenes, planner = _mock_storyboard(1)
        with patch("backend.project_runtime.build_storyboard", return_value=(scenes, planner)):
            project = create_project("", "这是一个故事", "rule", 1, "local", "local", "edge")
        assert project["title"]  # should be non-empty (derived)

    def test_creates_project_directory(self, runtime_workspace):
        scenes, planner = _mock_storyboard(1)
        with patch("backend.project_runtime.build_storyboard", return_value=(scenes, planner)):
            project = create_project("T", "story", "rule", 1, "local", "local", "edge")
        project_root = runtime_workspace / project["project_id"]
        assert project_root.exists()
        assert (project_root / "project.json").exists()
        assert (project_root / "scenes").exists()
        assert (project_root / "characters").exists()

    def test_persists_to_disk(self, runtime_workspace):
        scenes, planner = _mock_storyboard(2)
        with patch("backend.project_runtime.build_storyboard", return_value=(scenes, planner)):
            project = create_project("持久化", "story", "rule", 2, "local", "local", "edge")
        loaded = load_project(project["project_id"])
        assert loaded["title"] == "持久化"
        assert len(loaded["scenes"]) == 2

    def test_episode_pacing_applied(self, runtime_workspace):
        scenes, planner = _mock_storyboard(3)
        with patch("backend.project_runtime.build_storyboard", return_value=(scenes, planner)):
            project = create_project("T", "story", "rule", 3, "local", "local", "edge")
        for scene in project["scenes"]:
            assert "episode_phase" in scene
            assert "episode_phase_index" in scene
            assert "episode_rhythm" in scene


# ---------------------------------------------------------------------------
# load_project
# ---------------------------------------------------------------------------

class TestLoadProject:
    def test_loads_existing_project(self, runtime_workspace):
        project_data = _make_minimal_project()
        _write_project(runtime_workspace, "proj_load_001", project_data)
        loaded = load_project("proj_load_001")
        assert loaded["project_id"] == "proj_load_001"
        assert loaded["title"] == "测试漫剧"
        assert len(loaded["scenes"]) == 3

    def test_raises_file_not_found_for_missing_project(self, runtime_workspace):
        with pytest.raises(FileNotFoundError):
            load_project("proj_nonexistent")

    def test_normalizes_missing_props_field(self, runtime_workspace):
        project_data = _make_minimal_project()
        _write_project(runtime_workspace, "proj_props_001", project_data)
        loaded = load_project("proj_props_001")
        assert isinstance(loaded.get("props"), list)

    def test_normalizes_scene_props_field(self, runtime_workspace):
        project_data = _make_minimal_project()
        _write_project(runtime_workspace, "proj_sprops_001", project_data)
        loaded = load_project("proj_sprops_001")
        for scene in loaded["scenes"]:
            assert isinstance(scene.get("props"), list)

    def test_normalizes_director_interpretation(self, runtime_workspace):
        project_data = _make_minimal_project()
        _write_project(runtime_workspace, "proj_dir_001", project_data)
        loaded = load_project("proj_dir_001")
        for scene in loaded["scenes"]:
            assert isinstance(scene.get("director_plan"), dict)
            assert isinstance(scene.get("shot_plan"), dict)

    def test_ensures_style_guide_field(self, runtime_workspace):
        project_data = _make_minimal_project()
        del project_data["style_guide"]
        _write_project(runtime_workspace, "proj_sg_001", project_data)
        loaded = load_project("proj_sg_001")
        assert "style_guide" in loaded


# ---------------------------------------------------------------------------
# save_project
# ---------------------------------------------------------------------------

class TestSaveProject:
    def test_saves_and_updates_timestamp(self, runtime_workspace):
        project_data = _make_minimal_project()
        _write_project(runtime_workspace, "proj_save_001", project_data)
        project = load_project("proj_save_001")
        old_updated = project["updated_at"]
        project["title"] = "更新后的标题"
        saved = save_project(project)
        assert saved["title"] == "更新后的标题"
        assert saved["updated_at"] != old_updated

    def test_persists_changes_to_disk(self, runtime_workspace):
        project_data = _make_minimal_project()
        _write_project(runtime_workspace, "proj_save_002", project_data)
        project = load_project("proj_save_002")
        project["title"] = "磁盘持久化"
        save_project(project)
        reloaded = load_project("proj_save_002")
        assert reloaded["title"] == "磁盘持久化"

    def test_ensures_style_id(self, runtime_workspace):
        project_data = _make_minimal_project()
        _write_project(runtime_workspace, "proj_save_003", project_data)
        project = load_project("proj_save_003")
        project["style_id"] = ""
        saved = save_project(project)
        assert saved["style_id"]  # non-empty after save


# ---------------------------------------------------------------------------
# list_projects
# ---------------------------------------------------------------------------

class TestListProjects:
    def test_returns_empty_when_no_projects(self, runtime_workspace):
        assert list_projects() == []

    def test_returns_all_projects(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_list_001", _make_minimal_project())
        _write_project(runtime_workspace, "proj_list_002", _make_minimal_project())
        items = list_projects()
        assert len(items) == 2

    def test_skips_corrupt_json(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_list_003", _make_minimal_project())
        # Write a corrupt project.json
        bad_root = runtime_workspace / "proj_list_bad"
        bad_root.mkdir()
        (bad_root / "project.json").write_text("{invalid json", encoding="utf-8")
        items = list_projects()
        assert len(items) == 1  # only the valid one

    def test_returns_sorted_reverse(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_a_001", _make_minimal_project("proj_a_001"))
        _write_project(runtime_workspace, "proj_b_002", _make_minimal_project("proj_b_002"))
        items = list_projects()
        # Sorted reverse by path — proj_b comes before proj_a
        assert items[0]["project_id"] == "proj_b_002"
        assert items[1]["project_id"] == "proj_a_001"


# ---------------------------------------------------------------------------
# delete_project
# ---------------------------------------------------------------------------

class TestDeleteProject:
    def test_deletes_existing_project(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_del_001", _make_minimal_project())
        result = delete_project("proj_del_001")
        assert result["status"] == "deleted"
        assert not (runtime_workspace / "proj_del_001").exists()

    def test_raises_file_not_found_for_missing(self, runtime_workspace):
        with pytest.raises(FileNotFoundError):
            delete_project("proj_nonexistent_del")

    def test_rejects_invalid_path(self, runtime_workspace):
        with pytest.raises(ValueError):
            delete_project("..")


# ---------------------------------------------------------------------------
# project_snapshot
# ---------------------------------------------------------------------------

class TestProjectSnapshot:
    def test_returns_deep_copy(self, runtime_workspace):
        project = _make_minimal_project()
        snapshot = project_snapshot(project)
        assert snapshot is not project
        assert snapshot["scenes"] is not project["scenes"]

    def test_enriches_with_summary(self, runtime_workspace):
        project = _make_minimal_project(scene_count=3)
        snapshot = project_snapshot(project)
        assert "summary" in snapshot
        assert snapshot["summary"]["total_scenes"] == 3
        assert snapshot["summary"]["total_characters"] == 0
        assert snapshot["summary"]["completed_scenes"] == 0

    def test_enriches_with_scene_graph(self, runtime_workspace):
        project = _make_minimal_project()
        snapshot = project_snapshot(project)
        assert "scene_graph" in snapshot
        assert snapshot["scene_graph"]["scene_count"] == len(project["scenes"])

    def test_enriches_with_production_bible(self, runtime_workspace):
        project = _make_minimal_project()
        snapshot = project_snapshot(project)
        assert "production_bible" in snapshot

    def test_enriches_with_continuity_ledger(self, runtime_workspace):
        project = _make_minimal_project()
        snapshot = project_snapshot(project)
        assert "continuity_ledger" in snapshot

    def test_enriches_with_canonical_timeline(self, runtime_workspace):
        project = _make_minimal_project()
        snapshot = project_snapshot(project)
        assert "canonical_timeline" in snapshot

    def test_counts_total_shots(self, runtime_workspace):
        project = _make_minimal_project(scene_count=2)
        # Add shots to first scene
        project["scenes"][0]["shots"] = [{"shot_id": "s1"}, {"shot_id": "s2"}]
        snapshot = project_snapshot(project)
        # total_shots includes our 2 shots plus any defaults from shot_plan
        assert snapshot["summary"]["total_shots"] >= 2

    def test_clears_missing_output_paths(self, runtime_workspace):
        project = _make_minimal_project()
        project["output"]["final_video_path"] = "nonexistent.mp4"
        snapshot = project_snapshot(project)
        assert snapshot["output"]["final_video_path"] == ""
        assert snapshot["output"]["final_video_url"] == ""


# ---------------------------------------------------------------------------
# update_runtime
# ---------------------------------------------------------------------------

class TestUpdateRuntime:
    def test_updates_status_and_progress(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_rt_001", _make_minimal_project())
        updated = update_runtime("proj_rt_001", status="running", progress=50, stage="rendering", message="半完成")
        assert updated["runtime"]["status"] == "running"
        assert updated["runtime"]["progress"] == 50
        assert updated["runtime"]["stage"] == "rendering"
        assert updated["runtime"]["message"] == "半完成"

    def test_persists_to_disk(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_rt_002", _make_minimal_project())
        update_runtime("proj_rt_002", status="failed", stage="failed", message="出错")
        reloaded = load_project("proj_rt_002")
        assert reloaded["runtime"]["status"] == "failed"

    def test_partial_update_preserves_other_fields(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_rt_003", _make_minimal_project())
        original = load_project("proj_rt_003")
        update_runtime("proj_rt_003", progress=30)
        reloaded = load_project("proj_rt_003")
        assert reloaded["runtime"]["progress"] == 30
        assert reloaded["runtime"]["status"] == original["runtime"]["status"]


# ---------------------------------------------------------------------------
# update_scene_fields
# ---------------------------------------------------------------------------

class TestUpdateSceneFields:
    def test_updates_visual_prompt(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_usf_001", _make_minimal_project())
        updated = update_scene_fields("proj_usf_001", 1, {"visual_prompt": "新画面描述"})
        scene = next(s for s in updated["scenes"] if s["order"] == 1)
        assert scene["visual_prompt"] == "新画面描述"

    def test_raises_for_missing_scene(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_usf_002", _make_minimal_project())
        with pytest.raises(KeyError, match="Scene 99 not found"):
            update_scene_fields("proj_usf_002", 99, {"visual_prompt": "x"})

    def test_none_values_are_ignored(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_usf_003", _make_minimal_project())
        original = load_project("proj_usf_003")
        update_scene_fields("proj_usf_003", 1, {"visual_prompt": None, "dialogue": None})
        reloaded = load_project("proj_usf_003")
        scene = next(s for s in reloaded["scenes"] if s["order"] == 1)
        assert scene["visual_prompt"] == original["scenes"][0]["visual_prompt"]

    def test_normalizes_crop_box(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_usf_004", _make_minimal_project())
        updated = update_scene_fields("proj_usf_004", 1, {"crop_box": {"x": 10, "y": 20, "w": 100, "h": 200}})
        scene = next(s for s in updated["scenes"] if s["order"] == 1)
        assert "crop_box" in scene


# ---------------------------------------------------------------------------
# update_character_fields
# ---------------------------------------------------------------------------

class TestUpdateCharacterFields:
    def test_updates_character_name(self, runtime_workspace):
        project = _make_minimal_project()
        project["characters"] = [{"char_id": "c1", "name": "原角色", "voice_engine": "edge"}]
        _write_project(runtime_workspace, "proj_ucf_001", project)
        updated = update_character_fields("proj_ucf_001", 1, {"name": "新角色名"})
        assert updated["characters"][0]["name"] == "新角色名"

    def test_raises_for_invalid_index(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_ucf_002", _make_minimal_project())
        with pytest.raises(KeyError, match="Character 99 not found"):
            update_character_fields("proj_ucf_002", 99, {"name": "x"})

    def test_none_values_ignored(self, runtime_workspace):
        project = _make_minimal_project()
        project["characters"] = [{"char_id": "c1", "name": "原名"}]
        _write_project(runtime_workspace, "proj_ucf_003", project)
        update_character_fields("proj_ucf_003", 1, {"name": None})
        reloaded = load_project("proj_ucf_003")
        assert reloaded["characters"][0]["name"] == "原名"


# ---------------------------------------------------------------------------
# update_project_fields
# ---------------------------------------------------------------------------

class TestUpdateProjectFields:
    def test_updates_title(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_upf_001", _make_minimal_project())
        updated = update_project_fields("proj_upf_001", {"title": "新标题"})
        assert updated["title"] == "新标题"

    def test_updates_settings(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_upf_002", _make_minimal_project())
        updated = update_project_fields("proj_upf_002", {"settings": {"aspect_ratio": "16:9"}})
        assert updated["settings"]["aspect_ratio"] == "16:9"

    def test_updates_style_id(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_upf_003", _make_minimal_project())
        updated = update_project_fields("proj_upf_003", {"style_id": "new_style"})
        assert updated["style_id"] == "new_style"

    def test_none_values_ignored(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_upf_004", _make_minimal_project())
        original = load_project("proj_upf_004")
        update_project_fields("proj_upf_004", {"title": None})
        reloaded = load_project("proj_upf_004")
        assert reloaded["title"] == original["title"]


# ---------------------------------------------------------------------------
# split_scene
# ---------------------------------------------------------------------------

class TestSplitScene:
    def test_splits_scene_into_two(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_split_001", _make_minimal_project(scene_count=2))
        updated = split_scene("proj_split_001", 1)
        assert len(updated["scenes"]) == 3

    def test_split_preserves_order_sequence(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_split_002", _make_minimal_project(scene_count=2))
        updated = split_scene("proj_split_002", 1)
        orders = [s["order"] for s in updated["scenes"]]
        assert orders == [1, 2, 3]

    def test_split_divides_duration(self, runtime_workspace):
        project = _make_minimal_project(scene_count=1)
        project["scenes"][0]["duration_seconds"] = 8.0
        _write_project(runtime_workspace, "proj_split_003", project)
        updated = split_scene("proj_split_003", 1)
        scene1 = updated["scenes"][0]
        scene2 = updated["scenes"][1]
        assert scene1["duration_seconds"] == 4.0
        assert scene2["duration_seconds"] == 4.0

    def test_split_creates_blank_assets_for_duplicate(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_split_004", _make_minimal_project(scene_count=1))
        updated = split_scene("proj_split_004", 1)
        duplicate = updated["scenes"][1]
        assert duplicate["assets"]["status"] == "pending"

    def test_split_raises_for_missing_scene(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_split_005", _make_minimal_project())
        with pytest.raises(KeyError, match="Scene 99 not found"):
            split_scene("proj_split_005", 99)


# ---------------------------------------------------------------------------
# merge_scene_with_next
# ---------------------------------------------------------------------------

class TestMergeSceneWithNext:
    def test_merges_two_scenes_into_one(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_merge_001", _make_minimal_project(scene_count=3))
        updated = merge_scene_with_next("proj_merge_001", 1)
        assert len(updated["scenes"]) == 2

    def test_merge_combines_dialogue(self, runtime_workspace):
        project = _make_minimal_project(scene_count=2)
        project["scenes"][0]["dialogue"] = "第一句"
        project["scenes"][1]["dialogue"] = "第二句"
        _write_project(runtime_workspace, "proj_merge_002", project)
        updated = merge_scene_with_next("proj_merge_002", 1)
        assert "第一句" in updated["scenes"][0]["dialogue"]
        assert "第二句" in updated["scenes"][0]["dialogue"]

    def test_merge_combines_duration(self, runtime_workspace):
        project = _make_minimal_project(scene_count=2)
        project["scenes"][0]["duration_seconds"] = 3.0
        project["scenes"][1]["duration_seconds"] = 5.0
        _write_project(runtime_workspace, "proj_merge_003", project)
        updated = merge_scene_with_next("proj_merge_003", 1)
        assert updated["scenes"][0]["duration_seconds"] == 8.0

    def test_merge_raises_for_last_scene(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_merge_004", _make_minimal_project(scene_count=2))
        with pytest.raises(KeyError, match="has no next scene"):
            merge_scene_with_next("proj_merge_004", 2)

    def test_merge_renumbers_scenes(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_merge_005", _make_minimal_project(scene_count=3))
        updated = merge_scene_with_next("proj_merge_005", 1)
        orders = [s["order"] for s in updated["scenes"]]
        assert orders == [1, 2]


# ---------------------------------------------------------------------------
# restore_scene_snapshot
# ---------------------------------------------------------------------------

class TestRestoreSceneSnapshot:
    def test_raises_when_no_snapshot(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_restore_001", _make_minimal_project())
        with pytest.raises(FileNotFoundError, match="No snapshot available"):
            restore_scene_snapshot("proj_restore_001", 1)

    def test_restores_after_edit(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_restore_002", _make_minimal_project())
        # First edit to create a snapshot
        update_scene_fields("proj_restore_002", 1, {"visual_prompt": "修改后"})
        # Then restore
        restored = restore_scene_snapshot("proj_restore_002", 1)
        scene = next(s for s in restored["scenes"] if s["order"] == 1)
        # Should restore to the pre-edit state
        assert scene["visual_prompt"] == "画面 1"


# ---------------------------------------------------------------------------
# capture_scene_snapshot / latest_scene_snapshot
# ---------------------------------------------------------------------------

class TestSceneSnapshotCapture:
    def test_capture_creates_snapshot_file(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_cap_001", _make_minimal_project())
        path = capture_scene_snapshot("proj_cap_001", 1, "edit")
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["action"] == "edit"
        assert data["scene_order"] == 1

    def test_latest_returns_most_recent(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_cap_002", _make_minimal_project())
        capture_scene_snapshot("proj_cap_002", 1, "edit")
        import time
        time.sleep(0.01)
        capture_scene_snapshot("proj_cap_002", 1, "split")
        latest = latest_scene_snapshot("proj_cap_002", 1)
        assert latest is not None
        assert latest["action"] == "split"

    def test_latest_with_skip_actions(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_cap_003", _make_minimal_project())
        capture_scene_snapshot("proj_cap_003", 1, "edit")
        import time
        time.sleep(0.01)
        capture_scene_snapshot("proj_cap_003", 1, "split")
        latest = latest_scene_snapshot("proj_cap_003", 1, skip_actions={"split"})
        assert latest is not None
        assert latest["action"] == "edit"

    def test_latest_returns_none_when_no_snapshots(self, runtime_workspace):
        _write_project(runtime_workspace, "proj_cap_004", _make_minimal_project())
        latest = latest_scene_snapshot("proj_cap_004", 1)
        assert latest is None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestReconstructStoryText:
    def test_reconstructs_from_scenes(self):
        project = {
            "scenes": [
                {"order": 1, "title": "场景一", "visual_prompt": "画面一", "dialogue": "对白一", "speaker": ""},
                {"order": 2, "title": "场景二", "visual_prompt": "画面二", "dialogue": "对白二", "speaker": ""},
            ]
        }
        result = reconstruct_story_text_from_scenes(project)
        assert "场景一" in result
        assert "画面一" in result
        assert "对白一" in result
        assert "场景二" in result

    def test_empty_scenes_returns_empty(self):
        assert reconstruct_story_text_from_scenes({"scenes": []}) == ""

    def test_uses_default_title_when_missing(self):
        project = {"scenes": [{"order": 1, "title": "", "visual_prompt": "", "dialogue": "", "speaker": ""}]}
        result = reconstruct_story_text_from_scenes(project)
        assert "场景 1" in result

    def test_speaker_fallback_when_no_dialogue(self):
        project = {"scenes": [{"order": 1, "title": "T", "visual_prompt": "", "dialogue": "", "speaker": "林晚"}]}
        result = reconstruct_story_text_from_scenes(project)
        assert "林晚" in result


class TestNormalizeScenePacingUpdate:
    def test_passes_through_simple_values(self):
        result = normalize_scene_pacing_update({"visual_prompt": "x"})
        assert result["visual_prompt"] == "x"

    def test_normalizes_crop_box(self):
        result = normalize_scene_pacing_update({"crop_box": {"x": 0, "y": 0, "w": 100, "h": 200}})
        assert "crop_box" in result

    def test_normalizes_episode_phase(self):
        result = normalize_scene_pacing_update({"episode_phase": "setup"})
        assert result["episode_phase"] == "setup"

    def test_none_values_preserved(self):
        result = normalize_scene_pacing_update({"crop_box": None, "visual_prompt": "x"})
        assert result["crop_box"] is None
        assert result["visual_prompt"] == "x"


class TestApplyProjectEpisodePacing:
    def test_assigns_phases_to_all_scenes(self):
        project = _make_minimal_project(scene_count=4)
        apply_project_episode_pacing(project, force=True)
        for scene in project["scenes"]:
            assert scene["episode_phase"]
            assert scene["episode_phase_index"] > 0
            assert scene["episode_rhythm"]

    def test_preserves_existing_phase_when_not_forced(self):
        project = _make_minimal_project(scene_count=2)
        project["scenes"][0]["episode_phase"] = "setup"
        apply_project_episode_pacing(project, force=False)
        assert project["scenes"][0]["episode_phase"] == "setup"

    def test_overwrites_when_forced(self):
        project = _make_minimal_project(scene_count=2)
        project["scenes"][0]["episode_phase"] = "custom_phase"
        apply_project_episode_pacing(project, force=True)
        assert project["scenes"][0]["episode_phase"] != "custom_phase"


class TestRenumberScenes:
    def test_sequential_order(self):
        project = {"project_id": "p1", "scenes": [
            {"order": 5, "scene_id": ""},
            {"order": 3, "scene_id": ""},
            {"order": 1, "scene_id": ""},
        ]}
        _renumber_scenes(project)
        orders = [s["order"] for s in project["scenes"]]
        assert orders == [1, 2, 3]

    def test_assigns_scene_ids(self):
        project = {"project_id": "p1", "scenes": [
            {"order": 1, "scene_id": ""},
            {"order": 2, "scene_id": ""},
        ]}
        _renumber_scenes(project)
        for scene in project["scenes"]:
            assert scene["scene_id"].startswith("scene_")

    def test_updates_scene_count_setting(self):
        project = {"project_id": "p1", "settings": {}, "scenes": [
            {"order": 1, "scene_id": ""},
            {"order": 2, "scene_id": ""},
        ]}
        _renumber_scenes(project)
        assert project["settings"]["scene_count"] == 2


class TestSetRuntime:
    def test_updates_runtime_fields(self):
        project = {"runtime": {}}
        _set_runtime(project, status="running", progress=50)
        assert project["runtime"]["status"] == "running"
        assert project["runtime"]["progress"] == 50

    def test_creates_runtime_if_missing(self):
        project = {}
        _set_runtime(project, status="idle")
        assert "runtime" in project
        assert project["runtime"]["status"] == "idle"

    def test_sets_updated_at(self):
        project = {}
        _set_runtime(project, status="idle")
        assert "updated_at" in project["runtime"]
