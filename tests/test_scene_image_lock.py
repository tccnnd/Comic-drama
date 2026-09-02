"""Tests for per-request lock_reference propagation in scene rerender-image and batch asset generation."""

from __future__ import annotations

import json
from pathlib import Path

from backend import asset_generation
from backend.assets import Asset, AssetStatus, AssetType


def _fake_scene(reference_path: str) -> object:
    class FakeScene:
        scene = 1
        duration = 4.0
        title = "probe"
        visual = "a corridor"
        dialogue = ""
        camera = "slow_push"
        emotion = ""
        characters = []
        bg_color = ""
        accent_color = ""
        character_references = []
        character_prompt_compilation = ""
        character_descriptions = ""
        consistency_meta: dict = {}
        primary_reference_image_abs_path = reference_path
        primary_reference_image_path = Path(reference_path).name if reference_path else ""
        primary_reference_meta = {"absolute": reference_path} if reference_path else None

    return FakeScene()


def test_generate_keyframe_cloud_lock_false_passes_empty_reference(tmp_path, monkeypatch):
    """scene rerender-image with lock_reference=False must NOT send a reference image."""
    import scripts.rw_comfyui as rwc

    ref_file = tmp_path / "ref.png"
    ref_file.write_bytes(b"PNG")

    captured: dict[str, object] = {}

    def fake_dashscope(**kwargs):
        captured.update(kwargs)
        out = Path(kwargs["output_path"])
        out.write_bytes(b"png")
        return out

    monkeypatch.setattr("backend.keyframe_providers.generate_keyframe_dashscope", fake_dashscope)
    scene = _fake_scene(str(ref_file))

    rwc._generate_keyframe_cloud(scene, tmp_path, lock_reference=False)
    assert captured["reference_image"] == ""


def test_generate_keyframe_cloud_lock_none_passes_reference(tmp_path, monkeypatch):
    """Default (None) keeps the auto-selected reference."""
    import scripts.rw_comfyui as rwc

    ref_file = tmp_path / "ref.png"
    ref_file.write_bytes(b"PNG")

    captured: dict[str, object] = {}

    def fake_dashscope(**kwargs):
        captured.update(kwargs)
        out = Path(kwargs["output_path"])
        out.write_bytes(b"png")
        return out

    monkeypatch.setattr("backend.keyframe_providers.generate_keyframe_dashscope", fake_dashscope)
    scene = _fake_scene(str(ref_file))

    rwc._generate_keyframe_cloud(scene, tmp_path, lock_reference=None)
    assert captured["reference_image"] == str(ref_file)


def test_generate_all_assets_passes_lock_false_per_asset(tmp_path, monkeypatch):
    """Batch generate-all must propagate lock_reference=False to every asset render."""
    calls: list[bool | None] = []

    def fake_store(_project_id: str):
        class FakeStore:
            characters = [
                Asset(id="c1", asset_type=AssetType.CHARACTER, name="A", visual_prompt="x")
            ]
            scene_bgs = []
            props = []

            def model_dump(self, mode="json"):
                return {
                    "characters": [a.model_dump(mode=mode) for a in self.characters],
                    "scene_bgs": [],
                    "props": [],
                }

        return FakeStore()

    def fake_update_status(_project_id, _asset_id, _payload):
        return Asset(id="c1", asset_type=AssetType.CHARACTER, name="A", visual_prompt="x")

    def fake_publish(_project_id):
        return None

    def fake_render(_project_id, _asset_id, lock_reference=None):
        calls.append(lock_reference)
        return Asset(
            id="c1",
            asset_type=AssetType.CHARACTER,
            name="A",
            visual_prompt="x",
            status=AssetStatus.DONE,
        )

    monkeypatch.setattr(asset_generation, "load_asset_store", fake_store)
    monkeypatch.setattr(asset_generation, "update_project_asset", fake_update_status)
    monkeypatch.setattr(asset_generation, "_publish_project_update", fake_publish)
    monkeypatch.setattr(asset_generation, "_render_asset_image", fake_render)

    asset_generation.generate_all_assets("proj", lock_reference=False)
    assert calls == [False]
