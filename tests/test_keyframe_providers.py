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

    monkeypatch.delenv("KEYFRAME_T2I_REFERENCE", raising=False)
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


def test_generate_keyframe_openai_edit_posts_multipart_with_reference(tmp_path, monkeypatch):
    """Reference image must be sent as multipart and prompt gets the identity prefix."""
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"data": [{"b64_json": base64.b64encode(_png_bytes()).decode("ascii")}]}
            ).encode("utf-8")

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["auth"] = req.headers.get("Authorization")
        captured["content_type"] = req.headers.get("Content-type") or req.headers.get(
            "Content-Type"
        )
        captured["body"] = req.data
        return FakeResponse()

    ref = tmp_path / "ref.png"
    ref.write_bytes(b"REF-DATA")
    monkeypatch.delenv("KEYFRAME_T2I_MODEL", raising=False)
    monkeypatch.setenv("XL_API_KEY", "test-xl-key")
    monkeypatch.setenv("XL_BASE_URL", "https://memefast.top")
    monkeypatch.setenv("KEYFRAME_T2I_REFERENCE", "1")
    monkeypatch.setattr(kp, "urlopen", fake_urlopen)

    out = tmp_path / "kf.png"
    result = kp.generate_keyframe_openai(
        "standing in a bamboo forest",
        width=832,
        height=1216,
        output_path=out,
        reference_image=ref,
    )
    assert result == out
    assert out.exists() and out.stat().st_size > 0
    assert captured["url"] == "https://memefast.top/v1/images/edits"
    assert captured["timeout"] == 300
    assert captured["auth"] == "Bearer test-xl-key"
    body = captured["body"]
    assert isinstance(body, bytes)
    assert b'Content-Disposition: form-data; name="image"' in body
    assert b"REF-DATA" in body
    assert b'name="model"\r\n\r\ngpt-image-2' in body
    assert b'name="size"\r\n\r\n1024x1536' in body
    assert kp.REFERENCE_PROMPT_PREFIX.encode().split(b" ")[1] in body


def test_generate_keyframe_openai_disables_reference_when_env_off(tmp_path, monkeypatch):
    """KEYFRAME_T2I_REFERENCE=0 should keep generation text-only even if a ref is passed."""
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"data": [{"b64_json": base64.b64encode(_png_bytes()).decode("ascii")}]}
            ).encode("utf-8")

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["body"] = req.data
        return FakeResponse()

    ref = tmp_path / "ref.png"
    ref.write_bytes(b"REF-DATA")
    monkeypatch.setenv("XL_API_KEY", "test-xl-key")
    monkeypatch.setenv("XL_BASE_URL", "https://memefast.top")
    monkeypatch.setenv("KEYFRAME_T2I_REFERENCE", "0")
    monkeypatch.setattr(kp, "urlopen", fake_urlopen)

    kp.generate_keyframe_openai("a scene", output_path=tmp_path / "kf.png", reference_image=ref)
    assert captured["url"] == "https://memefast.top/v1/images/generations"
    assert isinstance(captured["body"], bytes)  # JSON-encoded body, not multipart
    assert b"REF-DATA" not in captured["body"]


def _urlopen_capture(captured):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"data": [{"b64_json": base64.b64encode(_png_bytes()).decode("ascii")}]}
            ).encode("utf-8")

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["body"] = req.data
        return FakeResponse()

    return fake_urlopen


def test_reference_enabled_true_overrides_env_off(tmp_path, monkeypatch):
    """Explicit lock must win over KEYFRAME_T2I_REFERENCE=0."""
    captured: dict[str, object] = {}
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"REF-DATA")
    monkeypatch.setenv("XL_API_KEY", "test-xl-key")
    monkeypatch.setenv("XL_BASE_URL", "https://memefast.top")
    monkeypatch.setenv("KEYFRAME_T2I_REFERENCE", "0")
    monkeypatch.setattr(kp, "urlopen", _urlopen_capture(captured))

    kp.generate_keyframe_openai(
        "a scene",
        output_path=tmp_path / "kf.png",
        reference_image=ref,
        reference_enabled=True,
    )
    assert captured["url"] == "https://memefast.top/v1/images/edits"
    assert b"REF-DATA" in captured["body"]


def test_reference_enabled_false_overrides_env_on(tmp_path, monkeypatch):
    """Explicit unlock must win over KEYFRAME_T2I_REFERENCE=1 (default)."""
    captured: dict[str, object] = {}
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"REF-DATA")
    monkeypatch.setenv("XL_API_KEY", "test-xl-key")
    monkeypatch.setenv("XL_BASE_URL", "https://memefast.top")
    monkeypatch.setenv("KEYFRAME_T2I_REFERENCE", "1")
    monkeypatch.setattr(kp, "urlopen", _urlopen_capture(captured))

    kp.generate_keyframe_openai(
        "a scene",
        output_path=tmp_path / "kf.png",
        reference_image=ref,
        reference_enabled=False,
    )
    assert captured["url"] == "https://memefast.top/v1/images/generations"
    assert b"REF-DATA" not in captured["body"]


def test_generate_keyframe_dashscope_forwards_reference_enabled(tmp_path, monkeypatch):
    forwarded: dict[str, object] = {}

    def fake_openai(prompt, **kwargs):
        forwarded.update(kwargs)
        return tmp_path / "kf.png"

    monkeypatch.delenv("KEYFRAME_T2I_MODEL", raising=False)
    monkeypatch.setattr(kp, "generate_keyframe_openai", fake_openai)

    kp.generate_keyframe_dashscope(
        "a scene",
        output_path=tmp_path / "kf.png",
        reference_image=tmp_path / "ref.png",
        reference_enabled=True,
    )
    assert forwarded["reference_enabled"] is True


def _fake_image_response(payload: bytes):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"data": [{"b64_json": base64.b64encode(payload).decode("ascii")}]}
            ).encode("utf-8")

    return FakeResponse


def test_generate_keyframe_openai_uses_edits_when_reference_given(tmp_path, monkeypatch):
    captured: dict[str, object] = {}
    png = _png_bytes()
    ref = tmp_path / "ref.png"
    ref.write_bytes(png)

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["ctype"] = req.headers.get("Content-type") or req.headers.get("Content-Type")
        captured["body"] = req.data
        return _fake_image_response(png)()

    monkeypatch.delenv("KEYFRAME_T2I_REFERENCE", raising=False)
    monkeypatch.setenv("XL_API_KEY", "test-xl-key")
    monkeypatch.setenv("XL_BASE_URL", "https://memefast.top")
    monkeypatch.setattr(kp, "urlopen", fake_urlopen)

    out = tmp_path / "out.png"
    result = kp.generate_keyframe_openai(
        "same character in a temple",
        width=832,
        height=1216,
        output_path=out,
        model="gpt-image-2",
        reference_image=ref,
    )
    assert result == out and out.exists()
    assert captured["url"] == "https://memefast.top/v1/images/edits"
    assert "multipart/form-data" in str(captured["ctype"])
    body = bytes(captured["body"])
    assert b'name="image"' in body and b"ref.png" in body
    assert b"gpt-image-2" in body and b"1024x1536" in body


def test_generate_keyframe_openai_text_only_without_reference(tmp_path, monkeypatch):
    captured: dict[str, object] = {}
    png = _png_bytes()

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _fake_image_response(png)()

    monkeypatch.setenv("XL_API_KEY", "test-xl-key")
    monkeypatch.setenv("XL_BASE_URL", "https://memefast.top")
    monkeypatch.setattr(kp, "urlopen", fake_urlopen)

    out = tmp_path / "out2.png"
    result = kp.generate_keyframe_openai("a heroine portrait", output_path=out, model="gpt-image-2")
    assert result == out
    assert captured["url"] == "https://memefast.top/v1/images/generations"
    assert captured["body"]["model"] == "gpt-image-2"


def test_reference_edit_failure_falls_back_to_text_only(tmp_path, monkeypatch):
    from urllib.error import URLError

    urls: list[str] = []
    png = _png_bytes()
    ref = tmp_path / "ref.png"
    ref.write_bytes(png)

    def fake_urlopen(req, timeout=0):
        urls.append(req.full_url)
        if req.full_url.endswith("/images/edits"):
            raise URLError("edits unsupported")
        return _fake_image_response(png)()

    monkeypatch.setenv("XL_API_KEY", "test-xl-key")
    monkeypatch.setenv("XL_BASE_URL", "https://memefast.top")
    monkeypatch.setattr(kp, "urlopen", fake_urlopen)

    out = tmp_path / "out3.png"
    result = kp.generate_keyframe_openai(
        "same character", output_path=out, model="gpt-image-2", reference_image=ref
    )
    assert result == out and out.exists()
    assert urls == [
        "https://memefast.top/v1/images/edits",
        "https://memefast.top/v1/images/generations",
    ]


def test_resolve_reference_image_ignores_missing_paths(tmp_path):
    assert kp._resolve_reference_image(tmp_path / "nope.png") is None
    assert kp._resolve_reference_image("") is None
    ok = tmp_path / "ok.png"
    ok.write_bytes(b"png")
    assert kp._resolve_reference_image(ok) == ok


def test_scene_reference_image_prefers_existing_primary(tmp_path):
    from scripts.rw_comfyui import _scene_reference_image
    from scripts.rw_models import StoryScene

    good = tmp_path / "primary.png"
    good.write_bytes(b"png")

    scene = StoryScene(
        scene=1,
        duration=5.0,
        title="t",
        visual="v",
        dialogue="d",
        camera="c",
        emotion="e",
        characters=[],
        bg_color="#000",
        accent_color="#fff",
        primary_reference_image_abs_path=str(good),
        primary_reference_image_path=str(tmp_path / "missing.png"),
    )
    assert _scene_reference_image(scene) == str(good)

    scene2 = StoryScene(
        scene=2,
        duration=5.0,
        title="t",
        visual="v",
        dialogue="d",
        camera="c",
        emotion="e",
        characters=[],
        bg_color="#000",
        accent_color="#fff",
        character_references=[{"absolute": str(good)}],
    )
    assert _scene_reference_image(scene2) == str(good)

    scene3 = StoryScene(
        scene=3,
        duration=5.0,
        title="t",
        visual="v",
        dialogue="d",
        camera="c",
        emotion="e",
        characters=[],
        bg_color="#000",
        accent_color="#fff",
    )
    assert _scene_reference_image(scene3) == ""


def test_generate_keyframe_leonardo_end_to_end(tmp_path, monkeypatch):
    """Provider dispatch + submit/poll/download flow with a mocked Leonardo API."""
    calls: list[tuple[str, bytes | None]] = []

    class FakeResponse:
        def __init__(self, body: bytes):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return self._body

    def fake_urlopen(req, timeout=0):
        url = req if isinstance(req, str) else req.full_url
        if url.endswith("/generations") and req.method == "POST":
            calls.append((url, req.data))
            body = json.dumps({"sdGenerationJob": {"generationId": "gen-123"}}).encode()
        elif "/generations/gen-123" in url:
            body = json.dumps(
                {
                    "generations_by_pk": {
                        "status": "COMPLETE",
                        "generated_images": [{"url": "https://img.example/out.png"}],
                    }
                }
            ).encode()
        elif url.startswith("https://img.example/"):
            body = _png_bytes()
        else:
            raise AssertionError(f"unexpected url {url}")
        return FakeResponse(body)

    monkeypatch.setenv("LEONARDO_API_KEY", "leo-key")
    monkeypatch.delenv("KEYFRAME_T2I_PROVIDER", raising=False)
    monkeypatch.delenv("LEONARDO_MODEL_ID", raising=False)
    monkeypatch.setattr(kp, "urlopen", fake_urlopen)
    monkeypatch.setattr(kp.time, "sleep", lambda *_: None)

    out = tmp_path / "kf.png"
    result = kp.generate_keyframe_dashscope(
        "a corridor",
        output_path=out,
        model="leonardo/phoenix",
    )
    assert result == out
    assert out.exists() and out.stat().st_size > 0
    submit_url, submit_body = calls[0]
    assert submit_url == "https://cloud.leonardo.ai/api/rest/v1/generations"
    payload = json.loads(submit_body)
    assert payload["modelId"] == kp.LEONARDO_DEFAULT_MODEL_ID
    assert payload["width"] % 64 == 0 and payload["height"] % 64 == 0


def test_generate_keyframe_leonardo_with_reference_uploads_init_image(tmp_path, monkeypatch):
    """Reference image must be uploaded via /init-image and passed as init_image_id."""
    gen_bodies: list[bytes] = []

    class FakeResponse:
        def __init__(self, body: bytes):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return self._body

    def fake_urlopen2(req, timeout=0):
        url = req if isinstance(req, str) else req.full_url
        if url.endswith("/init-image"):
            return FakeResponse(json.dumps({"init_image": {"id": "init-9"}}).encode())
        if url.endswith("/generations") and req.method == "POST":
            gen_bodies.append(req.data)
            return FakeResponse(json.dumps({"sdGenerationJob": {"generationId": "gen-9"}}).encode())
        if "/generations/gen-9" in url:
            return FakeResponse(
                json.dumps(
                    {
                        "generations_by_pk": {
                            "status": "COMPLETE",
                            "generated_images": [{"url": "https://img.example/x.png"}],
                        }
                    }
                ).encode()
            )
        if url.startswith("https://img.example/"):
            return FakeResponse(_png_bytes())
        raise AssertionError(f"unexpected url {url}")

    ref = tmp_path / "ref.png"
    ref.write_bytes(b"REFDATA")
    monkeypatch.setenv("LEONARDO_API_KEY", "leo-key")
    monkeypatch.setattr(kp, "urlopen", fake_urlopen2)
    monkeypatch.setattr(kp.time, "sleep", lambda *_: None)

    out = tmp_path / "kf.png"
    result = kp.generate_keyframe_leonardo(
        "same character, night market",
        width=832,
        height=1216,
        output_path=out,
        reference_image=ref,
    )
    assert result == out
    assert gen_bodies, "generation submit never happened"
    payload = json.loads(gen_bodies[0])
    assert payload["init_image_id"] == "init-9"
    assert 0 < payload["init_strength"] < 1


def test_generate_keyframe_leonardo_missing_key_returns_none(monkeypatch):
    monkeypatch.delenv("LEONARDO_API_KEY", raising=False)
    assert kp.generate_keyframe_leonardo("x") is None
