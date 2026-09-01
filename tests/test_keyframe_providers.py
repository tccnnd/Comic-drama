from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path

from PIL import Image

from backend import keyframe_providers as kp


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (8, 8), (20, 40, 80)).save(buf, format="PNG")
    return buf.getvalue()


def test_openai_image_model_detection():
    assert kp._is_openai_image_model("gpt-image-2")
    assert kp._is_openai_image_model("gpt-image-1.5")
    assert kp._is_openai_image_model("dall-e-3")
    assert not kp._is_openai_image_model("wanx2.1-t2i-turbo")
    assert not kp._is_openai_image_model("happyhorse-1.0-i2v")


def test_nearest_openai_image_size_maps_portrait_and_square():
    assert kp._nearest_openai_image_size(832, 1216) == "1024x1536"
    assert kp._nearest_openai_image_size(1216, 832) == "1536x1024"
    assert kp._nearest_openai_image_size(1024, 1024) == "1024x1024"


def test_generate_keyframe_dashscope_routes_gpt_image_to_openai(tmp_path, monkeypatch):
    captured: dict[str, object] = {}
    png = _png_bytes()

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"data": [{"b64_json": base64.b64encode(png).decode("ascii")}]}
            ).encode("utf-8")

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["auth"] = req.headers.get("Authorization")
        return FakeResponse()

    monkeypatch.delenv("KEYFRAME_T2I_MODEL", raising=False)
    monkeypatch.setenv("XL_API_KEY", "test-xl-key")
    monkeypatch.setenv("XL_BASE_URL", "https://memefast.top")
    monkeypatch.setattr(kp, "urlopen", fake_urlopen)

    out = tmp_path / "kf.png"
    result = kp.generate_keyframe_dashscope(
        "a night corridor", output_path=out, width=832, height=1216
    )
    assert result == out
    assert out.exists() and out.stat().st_size > 0
    assert captured["url"] == "https://memefast.top/v1/images/generations"
    assert captured["body"]["model"] == "gpt-image-2"
    assert captured["body"]["size"] == "1024x1536"
    assert captured["auth"] == "Bearer test-xl-key"


def test_generate_keyframe_dashscope_keeps_wanx_on_dashscope(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps({"output": {"task_id": "task-1", "results": []}}).encode("utf-8")

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setenv("KEYFRAME_T2I_MODEL", "wanx2.1-t2i-turbo")
    monkeypatch.setenv("XL_API_KEY", "test-xl-key")
    monkeypatch.setenv("XL_BASE_URL", "https://memefast.top")
    monkeypatch.setattr(kp, "urlopen", fake_urlopen)
    clock = {"now": 0.0}

    def fake_time() -> float:
        clock["now"] += 200.0
        return clock["now"]

    monkeypatch.setattr(kp.time, "time", fake_time)
    monkeypatch.setattr(kp.time, "sleep", lambda *_args, **_kwargs: None)

    result = kp.generate_keyframe_dashscope(
        "a night corridor",
        output_path=tmp_path / "kf.png",
        model="wanx2.1-t2i-turbo",
    )
    assert result is None
    assert "/alibailian/api/v1/services/aigc/text2image/image-synthesis" in str(captured["url"])
    assert captured["body"]["model"] == "wanx2.1-t2i-turbo"
