"""Unit tests for scripts.video_provider_adapters module.

Covers pure helper functions (URL, size, route, extraction), env helpers,
auth helpers, and config validation in render_remote_video_provider.
HTTP-dependent functions are tested via integration in test_video_provider_mainline.py.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.video_provider_adapters import (
    VideoProviderConfigError,
    VideoProviderError,
    VideoRenderRequest,
    _aspect_ratio,
    _detect_route,
    _env,
    _env_any,
    _env_float,
    _extract_task_id,
    _extract_video_base64,
    _extract_video_url,
    _join_url,
    _kling_auth_headers,
    _kling_jwt_token,
    _openai_size,
    _provider_prefix,
    _root_base_url,
    _send_structured_spec,
    _status,
    _structured_spec_mode,
    render_remote_video_provider,
)
from video_providers import VideoProviderSpec, get_video_provider_spec

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TestExceptions:
    def test_video_provider_error_is_runtime_error(self):
        assert issubclass(VideoProviderError, RuntimeError)

    def test_video_provider_config_error_is_video_provider_error(self):
        assert issubclass(VideoProviderConfigError, VideoProviderError)

    def test_video_provider_config_error_is_runtime_error(self):
        assert issubclass(VideoProviderConfigError, RuntimeError)


# ---------------------------------------------------------------------------
# VideoRenderRequest
# ---------------------------------------------------------------------------


class TestVideoRenderRequest:
    def _make_request(self, **overrides):
        defaults = dict(
            scene=1,
            title="Test Scene",
            prompt="A test prompt",
            negative_prompt="blurry",
            keyframe_path=Path("/tmp/keyframe.png"),
            out_path=Path("/tmp/output.mp4"),
            run_dir=Path("/tmp/run"),
            duration=5.0,
            width=1280,
            height=720,
            fps=24,
        )
        defaults.update(overrides)
        return VideoRenderRequest(**defaults)

    def test_construct_with_required_fields(self):
        req = self._make_request()
        assert req.scene == 1
        assert req.prompt == "A test prompt"
        assert req.width == 1280

    def test_default_optional_fields(self):
        req = self._make_request()
        assert req.camera == ""
        assert req.characters == ()
        assert req.temporal_spec is None
        assert req.consistency_spec is None

    def test_frozen(self):
        req = self._make_request()
        with pytest.raises(AttributeError):
            req.scene = 2

    def test_custom_optional_fields(self):
        req = self._make_request(
            camera="zoom_in",
            characters=("Alice", "Bob"),
            temporal_spec={"shots": []},
        )
        assert req.camera == "zoom_in"
        assert req.characters == ("Alice", "Bob")
        assert req.temporal_spec == {"shots": []}


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


class TestUrlHelpers:
    def test_join_url_simple(self):
        assert (
            _join_url("https://api.example.com", "/v1/submit")
            == "https://api.example.com/v1/submit"
        )

    def test_join_url_strips_trailing_slash_from_base(self):
        assert (
            _join_url("https://api.example.com/", "/v1/submit")
            == "https://api.example.com/v1/submit"
        )

    def test_join_url_strips_leading_slash_from_path(self):
        assert (
            _join_url("https://api.example.com", "v1/submit") == "https://api.example.com/v1/submit"
        )

    def test_join_url_returns_absolute_path_unchanged(self):
        assert (
            _join_url("https://api.example.com", "https://other.com/submit")
            == "https://other.com/submit"
        )

    def test_root_base_url_strips_trailing_slash(self):
        assert _root_base_url("https://api.example.com/") == "https://api.example.com"

    def test_root_base_url_strips_v1_suffix(self):
        assert _root_base_url("https://api.example.com/v1") == "https://api.example.com"

    def test_root_base_url_strips_v2_suffix(self):
        assert _root_base_url("https://api.example.com/v2") == "https://api.example.com"

    def test_root_base_url_no_suffix(self):
        assert _root_base_url("https://api.example.com") == "https://api.example.com"


# ---------------------------------------------------------------------------
# Size helpers
# ---------------------------------------------------------------------------


class TestSizeHelpers:
    def test_aspect_ratio_landscape(self):
        assert _aspect_ratio(1280, 720) == "16:9"

    def test_aspect_ratio_portrait(self):
        assert _aspect_ratio(720, 1280) == "9:16"  # height >= width → portrait

    def test_aspect_ratio_square_is_portrait(self):
        assert _aspect_ratio(1080, 1080) == "9:16"  # height >= width → portrait

    def test_openai_size_standard_portrait(self):
        assert _openai_size(720, 1280, "sora-2") == "720x1280"

    def test_openai_size_standard_landscape(self):
        assert _openai_size(1280, 720, "sora-2") == "1280x720"

    def test_openai_size_pro_model_large_portrait(self):
        assert _openai_size(1080, 1920, "sora-2-pro") == "1080x1920"

    def test_openai_size_pro_model_large_landscape(self):
        assert _openai_size(1920, 1080, "sora-2-pro") == "1920x1080"

    def test_openai_size_pro_model_small_uses_standard(self):
        assert _openai_size(720, 1280, "sora-2-pro") == "720x1280"


# ---------------------------------------------------------------------------
# Route detection
# ---------------------------------------------------------------------------


class TestDetectRoute:
    def test_explicit_route_overrides(self, monkeypatch):
        monkeypatch.setenv("SORA_ROUTE", "kling")
        spec = get_video_provider_spec("sora")
        assert _detect_route("SORA", spec, "sora-2") == "kling"

    def test_sora_defaults_to_openai_official(self, monkeypatch):
        monkeypatch.delenv("SORA_ROUTE", raising=False)
        spec = get_video_provider_spec("sora")
        assert _detect_route("SORA", spec, "sora-2") == "openai_official"

    def test_doubao_defaults_to_volc(self, monkeypatch):
        monkeypatch.delenv("DOUBAO_ROUTE", raising=False)
        spec = get_video_provider_spec("doubao")
        assert _detect_route("DOUBAO", spec, "doubao-video") == "volc"

    def test_kling_model_routes_to_kling(self, monkeypatch):
        monkeypatch.delenv("XL_ROUTE", raising=False)
        spec = get_video_provider_spec("xl")
        assert _detect_route("XL", spec, "kling-v2") == "kling"

    def test_happyhorse_routes_to_dashscope(self, monkeypatch):
        monkeypatch.delenv("XL_ROUTE", raising=False)
        spec = get_video_provider_spec("xl")
        assert _detect_route("XL", spec, "happyhorse-v1") == "dashscope"

    def test_unfamiliar_model_defaults_to_unified(self, monkeypatch):
        monkeypatch.delenv("XL_ROUTE", raising=False)
        monkeypatch.delenv("XL_SUBMIT_PATH", raising=False)
        spec = get_video_provider_spec("xl")
        assert _detect_route("XL", spec, "unknown-model") == "unified"

    def test_dashscope_detected_from_submit_path(self, monkeypatch):
        monkeypatch.delenv("XL_ROUTE", raising=False)
        monkeypatch.setenv("XL_SUBMIT_PATH", "/api/v1/services/aigc/video-generation/generation")
        spec = get_video_provider_spec("xl")
        assert _detect_route("XL", spec, "unknown-model") == "dashscope"


# ---------------------------------------------------------------------------
# Response extraction
# ---------------------------------------------------------------------------


class TestExtractTaskId:
    def test_top_level_task_id(self):
        assert _extract_task_id({"task_id": "abc123"}) == "abc123"

    def test_top_level_taskId(self):
        assert _extract_task_id({"taskId": "abc123"}) == "abc123"

    def test_top_level_id(self):
        assert _extract_task_id({"id": "abc123"}) == "abc123"

    def test_top_level_job_id(self):
        assert _extract_task_id({"job_id": "abc123"}) == "abc123"

    def test_nested_data(self):
        assert _extract_task_id({"data": {"task_id": "abc123"}}) == "abc123"

    def test_nested_result(self):
        assert _extract_task_id({"result": {"taskId": "abc123"}}) == "abc123"

    def test_nested_response(self):
        assert _extract_task_id({"response": {"id": "abc123"}}) == "abc123"

    def test_empty_returns_empty_string(self):
        assert _extract_task_id({}) == ""

    def test_none_value_skipped(self):
        assert _extract_task_id({"task_id": None, "id": "fallback"}) == "fallback"


class TestExtractVideoUrl:
    def test_top_level_video_url(self):
        assert (
            _extract_video_url({"video_url": "https://cdn.example.com/v.mp4"})
            == "https://cdn.example.com/v.mp4"
        )

    def test_top_level_videoUrl(self):
        assert (
            _extract_video_url({"videoUrl": "https://cdn.example.com/v.mp4"})
            == "https://cdn.example.com/v.mp4"
        )

    def test_top_level_output_url(self):
        assert (
            _extract_video_url({"output_url": "https://cdn.example.com/v.mp4"})
            == "https://cdn.example.com/v.mp4"
        )

    def test_nested_data(self):
        assert (
            _extract_video_url({"data": {"video_url": "https://cdn.example.com/v.mp4"}})
            == "https://cdn.example.com/v.mp4"
        )

    def test_empty_returns_empty_string(self):
        assert _extract_video_url({}) == ""


class TestExtractVideoBase64:
    def test_top_level_video_base64(self):
        assert _extract_video_base64({"video_base64": "AAAA"}) == "AAAA"

    def test_top_level_videoBase64(self):
        assert _extract_video_base64({"videoBase64": "BBBB"}) == "BBBB"

    def test_nested_data(self):
        assert _extract_video_base64({"data": {"video_base64": "CCCC"}}) == "CCCC"

    def test_empty_returns_empty_string(self):
        assert _extract_video_base64({}) == ""


class TestStatus:
    def test_top_level_status(self):
        assert _status({"status": "SUCCEEDED"}) == "succeeded"

    def test_top_level_task_status(self):
        assert _status({"task_status": "FAILED"}) == "failed"

    def test_nested_data(self):
        assert _status({"data": {"status": "running"}}) == "running"

    def test_empty_returns_empty_string(self):
        assert _status({}) == ""

    def test_none_value_skipped(self):
        assert _status({"status": None, "task_status": "queued"}) == "queued"


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------


class TestEnvHelpers:
    def test_env_returns_value(self, monkeypatch):
        monkeypatch.setenv("SORA_API_KEY", "test-key")
        assert _env("SORA", "API_KEY") == "test-key"

    def test_env_returns_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("SORA_API_KEY", raising=False)
        assert _env("SORA", "API_KEY", "default-key") == "default-key"

    def test_env_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("SORA_API_KEY", "  test-key  ")
        assert _env("SORA", "API_KEY") == "test-key"

    def test_env_any_returns_first_match(self, monkeypatch):
        monkeypatch.setenv("SORA_API_KEY", "sora-key")
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
        assert _env_any("SORA", ("API_KEY", "OPENAI_API_KEY")) == "sora-key"

    def test_env_any_falls_through_to_second(self, monkeypatch):
        monkeypatch.delenv("SORA_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
        assert _env_any("SORA", ("API_KEY", "OPENAI_API_KEY")) == "openai-key"

    def test_env_any_returns_default_when_none_set(self, monkeypatch):
        monkeypatch.delenv("SORA_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert _env_any("SORA", ("API_KEY", "OPENAI_API_KEY"), default="fallback") == "fallback"

    def test_env_float_returns_float(self, monkeypatch):
        monkeypatch.setenv("SORA_TIMEOUT_SECONDS", "120")
        assert _env_float("SORA", "TIMEOUT_SECONDS", 60.0) == 120.0

    def test_env_float_returns_default_on_invalid(self, monkeypatch):
        monkeypatch.setenv("SORA_TIMEOUT_SECONDS", "not-a-number")
        assert _env_float("SORA", "TIMEOUT_SECONDS", 60.0) == 60.0

    def test_env_float_returns_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("SORA_TIMEOUT_SECONDS", raising=False)
        assert _env_float("SORA", "TIMEOUT_SECONDS", 60.0) == 60.0


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


class TestKlingAuth:
    def test_jwt_token_has_three_parts(self):
        token = _kling_jwt_token("access_key", "secret_key")
        assert token.count(".") == 2

    def test_jwt_token_contains_header_and_payload(self):
        token = _kling_jwt_token("access_key", "secret_key")
        header_b64, payload_b64, _ = token.split(".")
        import base64

        # Add padding for base64 decode
        header = json.loads(base64.urlsafe_b64decode(header_b64 + "==").decode())
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "==").decode())
        assert header["alg"] == "HS256"
        assert header["typ"] == "JWT"
        assert payload["iss"] == "access_key"

    def test_auth_headers_contain_jwt(self, monkeypatch):
        monkeypatch.setenv("KLING_ACCESS_KEY", "ak123")
        monkeypatch.setenv("KLING_SECRET_KEY", "sk456")
        headers = _kling_auth_headers("KLING", "unused-api-key")
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")
        assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# Provider prefix
# ---------------------------------------------------------------------------


class TestProviderPrefix:
    def test_local_prefix(self):
        assert _provider_prefix(get_video_provider_spec("local")) == "LOCAL"

    def test_comfyui_prefix(self):
        assert _provider_prefix(get_video_provider_spec("comfyui")) == "COMFYUI"

    def test_sora_prefix(self):
        assert _provider_prefix(get_video_provider_spec("sora")) == "SORA"

    def test_doubao_prefix(self):
        assert _provider_prefix(get_video_provider_spec("doubao")) == "DOUBAO"


# ---------------------------------------------------------------------------
# Structured spec helpers
# ---------------------------------------------------------------------------


class TestStructuredSpec:
    def test_send_structured_spec_default_false(self, monkeypatch):
        monkeypatch.delenv("SORA_SEND_STRUCTURED_SPEC", raising=False)
        monkeypatch.delenv("VIDEO_SEND_STRUCTURED_SPEC", raising=False)
        assert _send_structured_spec("SORA") is False

    def test_send_structured_spec_provider_specific(self, monkeypatch):
        monkeypatch.setenv("SORA_SEND_STRUCTURED_SPEC", "1")
        assert _send_structured_spec("SORA") is True

    def test_send_structured_spec_global(self, monkeypatch):
        monkeypatch.delenv("SORA_SEND_STRUCTURED_SPEC", raising=False)
        monkeypatch.setenv("VIDEO_SEND_STRUCTURED_SPEC", "true")
        assert _send_structured_spec("SORA") is True

    def test_structured_spec_mode_default_auto_unified_route(self, monkeypatch):
        monkeypatch.delenv("SORA_STRUCTURED_SPEC_MODE", raising=False)
        monkeypatch.delenv("VIDEO_STRUCTURED_SPEC_MODE", raising=False)
        assert _structured_spec_mode("SORA", "unified") == "fields"

    def test_structured_spec_mode_default_auto_other_route(self, monkeypatch):
        monkeypatch.delenv("SORA_STRUCTURED_SPEC_MODE", raising=False)
        monkeypatch.delenv("VIDEO_STRUCTURED_SPEC_MODE", raising=False)
        assert _structured_spec_mode("SORA", "openai_official") == "prompt"

    def test_structured_spec_mode_explicit_fields(self, monkeypatch):
        monkeypatch.setenv("SORA_STRUCTURED_SPEC_MODE", "fields")
        assert _structured_spec_mode("SORA", "unified") == "fields"

    def test_structured_spec_mode_explicit_none(self, monkeypatch):
        monkeypatch.setenv("SORA_STRUCTURED_SPEC_MODE", "off")
        assert _structured_spec_mode("SORA", "unified") == "none"


# ---------------------------------------------------------------------------
# render_remote_video_provider config validation
# ---------------------------------------------------------------------------


class TestRenderRemoteVideoProviderConfig:
    def _make_request(self, tmp_path):
        return VideoRenderRequest(
            scene=1,
            title="Test",
            prompt="test",
            negative_prompt="",
            keyframe_path=tmp_path / "keyframe.png",
            out_path=tmp_path / "output.mp4",
            run_dir=tmp_path,
            duration=5.0,
            width=1280,
            height=720,
            fps=24,
        )

    def test_raises_config_error_without_api_key(self, tmp_path, monkeypatch):
        for var in ("DOUBAO_API_KEY",):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("DOUBAO_MODEL", "doubao-test")
        monkeypatch.setenv("DOUBAO_BASE_URL", "https://api.example.com")
        with pytest.raises(VideoProviderConfigError, match="API_KEY"):
            render_remote_video_provider(
                self._make_request(tmp_path), get_video_provider_spec("doubao")
            )

    def test_raises_config_error_without_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DOUBAO_API_KEY", "test-key")
        monkeypatch.delenv("DOUBAO_MODEL", raising=False)
        monkeypatch.setenv("DOUBAO_BASE_URL", "https://api.example.com")
        with pytest.raises(VideoProviderConfigError, match="MODEL"):
            render_remote_video_provider(
                self._make_request(tmp_path), get_video_provider_spec("doubao")
            )

    def test_raises_config_error_without_base_url(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DOUBAO_API_KEY", "test-key")
        monkeypatch.setenv("DOUBAO_MODEL", "doubao-test")
        for var in ("DOUBAO_BASE_URL", "DOUBAO_SUBMIT_URL"):
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(VideoProviderConfigError, match="BASE_URL"):
            render_remote_video_provider(
                self._make_request(tmp_path), get_video_provider_spec("doubao")
            )
