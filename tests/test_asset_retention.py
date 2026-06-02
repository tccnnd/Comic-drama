"""Tests for backend.asset_retention — version retention and cleanup logic."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.asset_retention import (
    _retained_versions,
    cleanup_scene_versions,
    _extract_version,
)


# ─── _retained_versions ──────────────────────────────────────────────────────


class TestRetainedVersions:
    def test_keep_2_current_5_retains_4_and_5(self):
        result = _retained_versions(5, keep=2)
        assert result == {4, 5}

    def test_keep_1_current_3_retains_only_3(self):
        result = _retained_versions(3, keep=1)
        assert result == {3}

    def test_keep_3_current_2_retains_1_and_2(self):
        result = _retained_versions(2, keep=3)
        assert result == {1, 2}

    def test_current_version_0_returns_empty(self):
        result = _retained_versions(0, keep=2)
        assert result == set()

    def test_current_version_negative_returns_empty(self):
        result = _retained_versions(-1, keep=2)
        assert result == set()

    def test_none_current_version_returns_empty(self):
        result = _retained_versions(None, keep=2)
        assert result == set()

    def test_non_numeric_current_version_returns_empty(self):
        result = _retained_versions("abc", keep=2)
        assert result == set()

    def test_keep_0_treated_as_keep_1(self):
        result = _retained_versions(5, keep=0)
        assert result == {5}

    def test_keep_negative_treated_as_keep_1(self):
        result = _retained_versions(5, keep=-3)
        assert result == {5}

    def test_large_keep_value(self):
        result = _retained_versions(3, keep=100)
        assert result == {1, 2, 3}

    def test_current_version_1_keep_2(self):
        result = _retained_versions(1, keep=2)
        assert result == {1}


# ─── _extract_version ─────────────────────────────────────────────────────────


class TestExtractVersion:
    def test_image_file(self):
        result = _extract_version("image_v3.png")
        assert result == ("image", 3)

    def test_audio_file(self):
        result = _extract_version("audio_v1.wav")
        assert result == ("audio", 1)

    def test_video_file(self):
        result = _extract_version("video_v10.mp4")
        assert result == ("video", 10)

    def test_subtitle_file(self):
        result = _extract_version("subtitle_v2.ass")
        assert result == ("subtitle", 2)

    def test_temp_file(self):
        result = _extract_version("render_v1.tmp")
        assert result == ("temp", 1)

    def test_unrecognized_file_returns_none(self):
        assert _extract_version("readme.txt") is None
        assert _extract_version("project.json") is None
        assert _extract_version("") is None


# ─── cleanup_scene_versions ───────────────────────────────────────────────────


class TestCleanupSceneVersions:
    def test_deletes_old_versions(self, tmp_path):
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        # Create versioned files
        (scene_dir / "image_v1.png").write_bytes(b"old")
        (scene_dir / "image_v2.png").write_bytes(b"old")
        (scene_dir / "image_v3.png").write_bytes(b"current")
        (scene_dir / "audio_v1.wav").write_bytes(b"old")
        (scene_dir / "audio_v2.wav").write_bytes(b"current")

        current_versions = {"image": 3, "audio": 2, "video": 0}
        deleted = cleanup_scene_versions(scene_dir, current_versions, keep=2)

        # image_v1 should be deleted (keep=2 means retain v2 and v3)
        assert not (scene_dir / "image_v1.png").exists()
        # image_v2 and v3 should remain
        assert (scene_dir / "image_v2.png").exists()
        assert (scene_dir / "image_v3.png").exists()
        # audio_v1 should be deleted (keep=2 means retain v1 and v2 for current=2)
        assert (scene_dir / "audio_v1.wav").exists()  # v1 is retained when current=2, keep=2
        assert (scene_dir / "audio_v2.wav").exists()

    def test_keep_1_deletes_all_but_current(self, tmp_path):
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        (scene_dir / "image_v1.png").write_bytes(b"old")
        (scene_dir / "image_v2.png").write_bytes(b"old")
        (scene_dir / "image_v3.png").write_bytes(b"current")

        current_versions = {"image": 3, "audio": 0, "video": 0}
        deleted = cleanup_scene_versions(scene_dir, current_versions, keep=1)

        assert not (scene_dir / "image_v1.png").exists()
        assert not (scene_dir / "image_v2.png").exists()
        assert (scene_dir / "image_v3.png").exists()
        assert len(deleted) == 2

    def test_empty_directory_returns_empty_list(self, tmp_path):
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        current_versions = {"image": 1, "audio": 1, "video": 1}
        deleted = cleanup_scene_versions(scene_dir, current_versions, keep=2)
        assert deleted == []

    def test_nonexistent_directory_returns_empty_list(self, tmp_path):
        scene_dir = tmp_path / "nonexistent"
        current_versions = {"image": 1, "audio": 1, "video": 1}
        deleted = cleanup_scene_versions(scene_dir, current_versions, keep=2)
        assert deleted == []

    def test_keep_less_than_1_returns_empty(self, tmp_path):
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        (scene_dir / "image_v1.png").write_bytes(b"data")
        current_versions = {"image": 1, "audio": 0, "video": 0}
        deleted = cleanup_scene_versions(scene_dir, current_versions, keep=0)
        assert deleted == []
        # File should still exist
        assert (scene_dir / "image_v1.png").exists()

    def test_non_versioned_files_not_deleted(self, tmp_path):
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        (scene_dir / "notes.txt").write_bytes(b"keep me")
        (scene_dir / "image_v1.png").write_bytes(b"old")
        (scene_dir / "image_v2.png").write_bytes(b"current")

        current_versions = {"image": 2, "audio": 0, "video": 0}
        cleanup_scene_versions(scene_dir, current_versions, keep=1)

        # Non-versioned file should remain
        assert (scene_dir / "notes.txt").exists()

    def test_current_version_0_no_retention(self, tmp_path):
        """When current version is 0, nothing is retained for that kind."""
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        (scene_dir / "image_v1.png").write_bytes(b"data")

        current_versions = {"image": 0, "audio": 0, "video": 0}
        deleted = cleanup_scene_versions(scene_dir, current_versions, keep=2)
        # With current=0, _retained_versions returns empty set, so v1 is not retained
        # But the union logic means it depends on video retention
        # Since video current is also 0, retained_derivatives is empty
        # So image_v1 should be deleted
        assert not (scene_dir / "image_v1.png").exists()
