from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal
import os

VideoProviderBackend = Literal["local", "comfyui", "remote"]


@dataclass(frozen=True)
class VideoProviderSpec:
    id: str
    label: str
    backend: VideoProviderBackend
    aliases: tuple[str, ...] = ()
    description: str = ""
    config_env: tuple[str, ...] = ()
    supports: tuple[str, ...] = ()
    notes: str = ""


_VIDEO_PROVIDER_REGISTRY: dict[str, VideoProviderSpec] = {}
_VIDEO_PROVIDER_ALIASES: dict[str, str] = {}


def register_video_provider(spec: VideoProviderSpec) -> VideoProviderSpec:
    provider_id = spec.id.strip().lower()
    if not provider_id:
        raise ValueError("video provider id is required")
    normalized = VideoProviderSpec(
        id=provider_id,
        label=spec.label,
        backend=spec.backend,
        aliases=tuple(alias.strip().lower() for alias in spec.aliases if alias.strip()),
        description=spec.description,
        config_env=tuple(spec.config_env),
        supports=tuple(spec.supports),
        notes=spec.notes,
    )
    _VIDEO_PROVIDER_REGISTRY[provider_id] = normalized
    _VIDEO_PROVIDER_ALIASES[provider_id] = provider_id
    for alias in normalized.aliases:
        _VIDEO_PROVIDER_ALIASES[alias] = provider_id
    return normalized


def _register_defaults() -> None:
    if _VIDEO_PROVIDER_REGISTRY:
        return

    register_video_provider(
        VideoProviderSpec(
            id="local",
            label="Local 2.5D",
            backend="local",
            aliases=("2.5d", "kenburns", "keyframe"),
            description="Keyframe PNG -> 2.5D motion clip -> concat",
            config_env=("VIDEO_PROVIDER", "VIDEO_STRICT"),
            supports=("image", "audio", "subtitle"),
        )
    )
    register_video_provider(
        VideoProviderSpec(
            id="comfyui",
            label="ComfyUI",
            backend="comfyui",
            aliases=("self_hosted", "self-hosted", "video_model"),
            description="Self-hosted ComfyUI workflow renderer",
            config_env=(
                "VIDEO_PROVIDER",
                "VIDEO_STRICT",
                "COMFYUI_VIDEO_WORKFLOW_PATH",
                "COMFYUI_VIDEO_CHECKPOINT_NAME",
                "COMFYUI_VIDEO_LORA_NAME",
                "COMFYUI_VIDEO_LORA_STRENGTH_MODEL",
                "COMFYUI_VIDEO_LORA_STRENGTH_CLIP",
                "COMFYUI_VIDEO_IP_ADAPTER_WEIGHT",
            ),
            supports=("image", "audio", "workflow"),
        )
    )
    register_video_provider(
        VideoProviderSpec(
            id="sora",
            label="Sora",
            backend="remote",
            aliases=("openai_sora", "sora2"),
            description="Remote Sora-style video provider through a submit/poll/download gateway",
            config_env=(
                "OPENAI_API_KEY",
                "OPENAI_VIDEO_MODEL",
                "OPENAI_BASE_URL",
                "OPENAI_SUBMIT_PATH",
                "OPENAI_POLL_PATH",
                "OPENAI_CONTENT_PATH",
                "OPENAI_REFERENCE_FIELD",
                "OPENAI_SIZE",
                "OPENAI_TIMEOUT_SECONDS",
                "OPENAI_POLL_INTERVAL_SECONDS",
                "SORA_API_KEY",
                "SORA_MODEL",
                "SORA_BASE_URL",
                "SORA_SUBMIT_URL",
                "SORA_POLL_URL",
                "SORA_TIMEOUT_SECONDS",
                "SORA_POLL_INTERVAL_SECONDS",
            ),
            supports=("text", "image", "audio"),
            notes="Uses the generic remote video adapter protocol.",
        )
    )
    register_video_provider(
        VideoProviderSpec(
            id="xl",
            label="XL Aggregator",
            backend="remote",
            aliases=("moyin", "memefast", "moyin-creator", "xl-aggregate"),
            description="Aggregated video provider compatible with Moyin-style gateway routing",
            config_env=(
                "XL_API_KEY",
                "XL_MODEL",
                "XL_BASE_URL",
                "XL_SUBMIT_PATH",
                "XL_POLL_PATH",
                "XL_CONTENT_URL",
                "XL_IMAGE_UPLOAD_URL",
                "XL_REFERENCE_IMAGE_URL",
                "XL_ROUTE",
                "XL_TIMEOUT_SECONDS",
                "XL_POLL_INTERVAL_SECONDS",
            ),
            supports=("text", "image", "audio"),
            notes="Can route to unified / volc / kling / openai_official based on model or XL_ROUTE.",
        )
    )
    register_video_provider(
        VideoProviderSpec(
            id="doubao",
            label="Doubao",
            backend="remote",
            aliases=("volcengine", "doubao-video"),
            description="Remote Doubao video provider through a submit/poll/download gateway",
            config_env=(
                "DOUBAO_API_KEY",
                "DOUBAO_MODEL",
                "DOUBAO_BASE_URL",
                "DOUBAO_SUBMIT_URL",
                "DOUBAO_POLL_URL",
                "DOUBAO_TIMEOUT_SECONDS",
                "DOUBAO_POLL_INTERVAL_SECONDS",
            ),
            supports=("text", "image", "audio"),
            notes="Uses the generic remote video adapter protocol.",
        )
    )
    register_video_provider(
        VideoProviderSpec(
            id="seedance",
            label="Seedance",
            backend="remote",
            aliases=("doubao-seedance", "seedance-video"),
            description="Remote Seedance video provider through a submit/poll/download gateway",
            config_env=(
                "SEEDANCE_API_KEY",
                "SEEDANCE_MODEL",
                "SEEDANCE_BASE_URL",
                "SEEDANCE_SUBMIT_URL",
                "SEEDANCE_POLL_URL",
                "SEEDANCE_TIMEOUT_SECONDS",
                "SEEDANCE_POLL_INTERVAL_SECONDS",
            ),
            supports=("text", "image", "audio"),
            notes="Uses the generic remote video adapter protocol.",
        )
    )


_register_defaults()


def list_video_provider_specs() -> list[VideoProviderSpec]:
    return list(_VIDEO_PROVIDER_REGISTRY.values())


def list_video_providers() -> list[dict[str, object]]:
    return [asdict(spec) for spec in list_video_provider_specs()]


def get_video_provider_status(provider: str | None = None) -> dict[str, object]:
    spec = get_video_provider_spec(provider)
    ignore_env = {"VIDEO_PROVIDER", "VIDEO_STRICT"}
    env_status = []
    missing_env = []
    for name in spec.config_env:
        if name in ignore_env:
            continue
        value = os.environ.get(name, "").strip()
        configured = bool(value)
        if not configured:
            missing_env.append(name)
        env_status.append(
            {
                "name": name,
                "configured": configured,
                "length": len(value),
            }
        )
    return {
        "provider": asdict(spec),
        "env": env_status,
        "configured_count": sum(1 for item in env_status if item["configured"]),
        "missing_env": missing_env,
    }


def get_video_provider_spec(provider: str | None = None, default: str = "local") -> VideoProviderSpec:
    value = (provider or "auto").strip().lower()
    if value == "auto":
        value = os.environ.get("VIDEO_PROVIDER", "").strip().lower() or default
    normalized = _VIDEO_PROVIDER_ALIASES.get(value, value)
    spec = _VIDEO_PROVIDER_REGISTRY.get(normalized)
    if spec is None:
        return _VIDEO_PROVIDER_REGISTRY[default]
    return spec


def normalize_video_provider(provider: str | None = None, default: str = "local") -> str:
    return get_video_provider_spec(provider, default=default).id


def video_provider_backend(provider: str | None = None, default: str = "local") -> VideoProviderBackend:
    return get_video_provider_spec(provider, default=default).backend
