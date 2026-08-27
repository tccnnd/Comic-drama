"""Unit tests for video_providers module.

Covers VideoProviderSpec, register_video_provider, list/query/normalize
functions, and provider readiness logic.
"""
from __future__ import annotations

import pytest

from video_providers import (
    VideoProviderSpec,
    register_video_provider,
    list_video_provider_specs,
    list_video_providers,
    get_video_provider_spec,
    get_video_provider_status,
    normalize_video_provider,
    video_provider_backend,
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegisterVideoProvider:
    def test_normalizes_id_to_lowercase(self):
        spec = register_video_provider(VideoProviderSpec(
            id="TestProvider",
            label="Test",
            backend="remote",
        ))
        assert spec.id == "testprovider"

    def test_normalizes_aliases_to_lowercase(self):
        spec = register_video_provider(VideoProviderSpec(
            id="MyProvider",
            label="My",
            backend="remote",
            aliases=("MyAlias", "  Spaced  ", ""),
        ))
        assert spec.aliases == ("myalias", "spaced")

    def test_rejects_empty_id(self):
        with pytest.raises(ValueError, match="video provider id is required"):
            register_video_provider(VideoProviderSpec(
                id="  ",
                label="Empty",
                backend="local",
            ))

    def test_returns_frozen_spec(self):
        spec = register_video_provider(VideoProviderSpec(
            id="frozen_test",
            label="Frozen",
            backend="local",
        ))
        with pytest.raises(AttributeError):
            spec.id = "changed"

    def test_overwrites_existing(self):
        register_video_provider(VideoProviderSpec(
            id="overwrite_me",
            label="Original",
            backend="local",
        ))
        register_video_provider(VideoProviderSpec(
            id="overwrite_me",
            label="Updated",
            backend="remote",
        ))
        spec = get_video_provider_spec("overwrite_me")
        assert spec.label == "Updated"
        assert spec.backend == "remote"

    def test_aliases_registered_for_lookup(self):
        register_video_provider(VideoProviderSpec(
            id="alias_host",
            label="Alias Host",
            backend="remote",
            aliases=("alias_one", "alias_two"),
        ))
        assert get_video_provider_spec("alias_one").id == "alias_host"
        assert get_video_provider_spec("alias_two").id == "alias_host"


# ---------------------------------------------------------------------------
# Default providers
# ---------------------------------------------------------------------------

class TestDefaultProviders:
    @pytest.fixture
    def default_ids(self):
        return {spec.id for spec in list_video_provider_specs()}

    def test_local_registered(self, default_ids):
        assert "local" in default_ids

    def test_comfyui_registered(self, default_ids):
        assert "comfyui" in default_ids

    def test_sora_registered(self, default_ids):
        assert "sora" in default_ids

    def test_xl_registered(self, default_ids):
        assert "xl" in default_ids

    def test_doubao_registered(self, default_ids):
        assert "doubao" in default_ids

    def test_seedance_registered(self, default_ids):
        assert "seedance" in default_ids

    def test_local_backend_is_local(self):
        assert get_video_provider_spec("local").backend == "local"

    def test_comfyui_backend_is_comfyui(self):
        assert get_video_provider_spec("comfyui").backend == "comfyui"

    def test_sora_backend_is_remote(self):
        assert get_video_provider_spec("sora").backend == "remote"

    def test_local_aliases_include_kenburns(self):
        assert "kenburns" in get_video_provider_spec("local").aliases

    def test_xl_aliases_include_happyhorse(self):
        assert "happyhorse" in get_video_provider_spec("xl").aliases


# ---------------------------------------------------------------------------
# List functions
# ---------------------------------------------------------------------------

class TestListFunctions:
    def test_list_specs_returns_list_of_video_provider_spec(self):
        specs = list_video_provider_specs()
        assert len(specs) > 0
        assert all(isinstance(s, VideoProviderSpec) for s in specs)

    def test_list_providers_returns_list_of_dicts(self):
        providers = list_video_providers()
        assert len(providers) > 0
        assert all(isinstance(p, dict) for p in providers)
        assert all("id" in p and "label" in p and "backend" in p for p in providers)

    def test_list_lengths_match(self):
        assert len(list_video_provider_specs()) == len(list_video_providers())


# ---------------------------------------------------------------------------
# get_video_provider_spec
# ---------------------------------------------------------------------------

class TestGetVideoProviderSpec:
    def test_by_id(self):
        spec = get_video_provider_spec("local")
        assert spec.id == "local"

    def test_by_alias(self):
        spec = get_video_provider_spec("kenburns")
        assert spec.id == "local"

    def test_case_insensitive(self):
        spec = get_video_provider_spec("LOCAL")
        assert spec.id == "local"

    def test_strips_whitespace(self):
        spec = get_video_provider_spec("  local  ")
        assert spec.id == "local"

    def test_none_returns_default(self, monkeypatch):
        monkeypatch.delenv("VIDEO_PROVIDER", raising=False)
        spec = get_video_provider_spec(None)
        assert spec.id == "local"

    def test_empty_string_returns_default(self, monkeypatch):
        monkeypatch.delenv("VIDEO_PROVIDER", raising=False)
        spec = get_video_provider_spec("")
        assert spec.id == "local"

    def test_unknown_returns_default(self):
        spec = get_video_provider_spec("nonexistent_provider")
        assert spec.id == "local"

    def test_auto_without_env_returns_default(self, monkeypatch):
        monkeypatch.delenv("VIDEO_PROVIDER", raising=False)
        spec = get_video_provider_spec("auto")
        assert spec.id == "local"

    def test_auto_with_env_returns_env_provider(self, monkeypatch):
        monkeypatch.setenv("VIDEO_PROVIDER", "sora")
        spec = get_video_provider_spec("auto")
        assert spec.id == "sora"

    def test_custom_default(self):
        spec = get_video_provider_spec("nonexistent", default="comfyui")
        assert spec.id == "comfyui"


# ---------------------------------------------------------------------------
# normalize_video_provider
# ---------------------------------------------------------------------------

class TestNormalizeVideoProvider:
    def test_returns_id(self):
        assert normalize_video_provider("local") == "local"

    def test_resolves_alias(self):
        assert normalize_video_provider("kenburns") == "local"

    def test_unknown_returns_default(self):
        assert normalize_video_provider("nonexistent") == "local"

    def test_custom_default(self):
        assert normalize_video_provider("nonexistent", default="sora") == "sora"

    def test_none_returns_default(self, monkeypatch):
        monkeypatch.delenv("VIDEO_PROVIDER", raising=False)
        assert normalize_video_provider(None) == "local"


# ---------------------------------------------------------------------------
# video_provider_backend
# ---------------------------------------------------------------------------

class TestVideoProviderBackend:
    def test_local_backend(self):
        assert video_provider_backend("local") == "local"

    def test_comfyui_backend(self):
        assert video_provider_backend("comfyui") == "comfyui"

    def test_remote_backend(self):
        assert video_provider_backend("sora") == "remote"

    def test_unknown_returns_default_backend(self):
        assert video_provider_backend("nonexistent") == "local"


# ---------------------------------------------------------------------------
# get_video_provider_status
# ---------------------------------------------------------------------------

class TestGetVideoProviderStatus:
    def test_local_status_is_ready(self):
        status = get_video_provider_status("local")
        assert status["readiness"]["ready"] is True
        assert status["readiness"]["level"] == "ready"

    def test_returns_provider_dict(self):
        status = get_video_provider_status("local")
        assert isinstance(status["provider"], dict)
        assert status["provider"]["id"] == "local"

    def test_env_list_contains_config_env_entries(self):
        """ComfyUI has non-ignored config_env entries."""
        status = get_video_provider_status("comfyui")
        env_names = [e["name"] for e in status["env"]]
        assert "COMFYUI_VIDEO_WORKFLOW_PATH" in env_names

    def test_local_env_empty_because_all_ignored(self):
        """Local provider's config_env (VIDEO_PROVIDER, VIDEO_STRICT) are all ignored."""
        status = get_video_provider_status("local")
        assert status["env"] == []

    def test_ignore_env_excluded_from_missing(self, monkeypatch):
        monkeypatch.delenv("VIDEO_PROVIDER", raising=False)
        monkeypatch.delenv("VIDEO_STRICT", raising=False)
        status = get_video_provider_status("local")
        assert "VIDEO_PROVIDER" not in status["missing_env"]
        assert "VIDEO_STRICT" not in status["missing_env"]

    def test_configured_count(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_VIDEO_WORKFLOW_PATH", "/path/to/workflow")
        status = get_video_provider_status("comfyui")
        assert status["configured_count"] >= 1

    def test_remote_missing_env(self, monkeypatch):
        for var in ("SORA_API_KEY", "SORA_MODEL", "SORA_BASE_URL", "SORA_SUBMIT_URL",
                     "OPENAI_API_KEY", "OPENAI_VIDEO_MODEL", "OPENAI_BASE_URL"):
            monkeypatch.delenv(var, raising=False)
        status = get_video_provider_status("sora")
        assert not status["readiness"]["ready"]
        assert status["readiness"]["level"] == "missing_config"
        assert len(status["readiness"]["blocking_env"]) > 0

    def test_remote_ready_with_env(self, monkeypatch):
        monkeypatch.setenv("SORA_API_KEY", "test-key")
        monkeypatch.setenv("SORA_MODEL", "test-model")
        monkeypatch.setenv("SORA_BASE_URL", "https://example.com")
        status = get_video_provider_status("sora")
        assert status["readiness"]["ready"] is True

    def test_comfyui_missing_workflow(self, monkeypatch):
        monkeypatch.delenv("COMFYUI_VIDEO_WORKFLOW_PATH", raising=False)
        monkeypatch.delenv("COMFYUI_VIDEO_CHECKPOINT_NAME", raising=False)
        monkeypatch.delenv("COMFYUI_CHECKPOINT_NAME", raising=False)
        status = get_video_provider_status("comfyui")
        assert not status["readiness"]["ready"]
        assert "COMFYUI_VIDEO_WORKFLOW_PATH" in status["readiness"]["blocking_env"]

    def test_comfyui_ready_with_config(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_VIDEO_WORKFLOW_PATH", "/path/to/workflow")
        monkeypatch.setenv("COMFYUI_VIDEO_CHECKPOINT_NAME", "model.safetensors")
        status = get_video_provider_status("comfyui")
        assert status["readiness"]["ready"] is True

    def test_sora_uses_openai_fallback_env(self, monkeypatch):
        """Sora should accept OPENAI_API_KEY as alternative to SORA_API_KEY."""
        for var in ("SORA_API_KEY", "SORA_MODEL", "SORA_BASE_URL", "SORA_SUBMIT_URL"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
        monkeypatch.setenv("OPENAI_VIDEO_MODEL", "sora-2")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com")
        status = get_video_provider_status("sora")
        assert status["readiness"]["ready"] is True
