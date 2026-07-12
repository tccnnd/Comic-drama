from __future__ import annotations

from fastapi import APIRouter

from video_providers import get_video_provider_status, list_video_providers

router = APIRouter(prefix="/api/video-providers", tags=["video-providers"])


@router.get("")
def list_video_providers_endpoint() -> dict[str, list[dict[str, object]]]:
    return {"providers": list_video_providers()}


@router.get("/status")
def video_providers_status(provider: str = "auto") -> dict[str, object]:
    return get_video_provider_status(provider)
