import json

from backend.assets import Asset, AssetType
from backend import asset_generation


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
