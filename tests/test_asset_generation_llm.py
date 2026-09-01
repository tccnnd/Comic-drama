import json

from backend import asset_generation
from backend.assets import Asset, AssetStatus, AssetType


def test_asset_generation_prompts_use_character_image_llm(monkeypatch):
    calls = []

    def fake_chat(system_prompt, user_prompt, *, task, temperature=0.2, **kwargs):
        calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "task": task,
                "temperature": temperature,
            }
        )
        return json.dumps(
            {
                "positive_prompt": "single heroine portrait, blue coat, clean anime linework",
                "negative_prompt": "crowd, duplicate face",
            }
        )

    monkeypatch.setattr(asset_generation.llm_client, "chat", fake_chat)

    asset = Asset(
        asset_type=AssetType.CHARACTER,
        name="林夏",
        appearance="蓝色短外套，黑色短发",
        visual_prompt="anime heroine",
    )
    style = {"name": "anime", "positive_suffix": "clean lines", "negative_suffix": "low quality"}

    positive, negative = asset_generation._asset_generation_prompts(asset, style)

    assert calls
    assert calls[0]["task"] == "character_image"
    assert calls[0]["temperature"] == 0.25
    assert "blue coat" in positive
    assert "crowd" in negative


def test_asset_generation_prompts_fallback_when_llm_fails(monkeypatch):
    def fail_chat(*args, **kwargs):
        raise RuntimeError("missing key")

    monkeypatch.setattr(asset_generation.llm_client, "chat", fail_chat)

    asset = Asset(
        asset_type=AssetType.PROP,
        name="怀表",
        description="旧怀表",
        visual_prompt="antique pocket watch",
    )
    positive, negative = asset_generation._asset_generation_prompts(asset, {})

    assert "antique pocket watch" in positive
    assert "single object" in positive
    assert "low quality" in negative


def test_render_asset_image_falls_back_to_cloud_when_comfyui_offline(tmp_path, monkeypatch):
    from pathlib import Path

    asset = Asset(
        id="char01",
        asset_type=AssetType.CHARACTER,
        name="林夏",
        visual_prompt="anime heroine",
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(asset_generation, "_check_comfyui_online", lambda: False)
    monkeypatch.setattr(asset_generation, "comfyui_base_url", lambda: "http://127.0.0.1:8188")
    monkeypatch.setattr(asset_generation, "_load_asset_record", lambda *_args, **_kwargs: asset)
    monkeypatch.setattr(
        asset_generation,
        "_project_style",
        lambda *_args, **_kwargs: {"positive_suffix": "clean lines", "negative_suffix": ""},
    )
    monkeypatch.setattr(
        asset_generation,
        "_asset_generation_prompts",
        lambda *_args, **_kwargs: ("heroine portrait", "crowd"),
    )
    monkeypatch.setattr(
        asset_generation, "_asset_output_path", lambda *_args, **_kwargs: tmp_path / "char01.png"
    )
    monkeypatch.setattr(
        asset_generation,
        "workspace_url",
        lambda *_args, **_kwargs: "/workspace/p/assets/char01.png",
    )

    def fake_cloud(**kwargs):
        captured.update(kwargs)
        out = Path(kwargs["output_path"])
        out.write_bytes(b"png")
        return out

    monkeypatch.setattr(asset_generation, "generate_keyframe_dashscope", fake_cloud)

    def fake_update(project_id, asset_id, payload):
        captured["update"] = payload
        return asset.model_copy(
            update={"status": AssetStatus.DONE, "thumbnail": payload["thumbnail"]}
        )

    monkeypatch.setattr(asset_generation, "update_project_asset", fake_update)

    result = asset_generation._render_asset_image("proj", "char01")
    assert result.status == AssetStatus.DONE
    assert captured["width"] == 832
    assert captured["height"] == 1216
    assert "heroine portrait" in captured["prompt"]
    assert captured["update"]["status"] == AssetStatus.DONE
