"""Intelligent provider routing based on cost, quality, and speed.

Routes video/image generation requests to the optimal provider based on:
- Cost budget (per-scene or per-project)
- Quality requirements (resolution, model tier)
- Speed constraints (deadline, batch vs single)
- Provider availability and health

Provider tiers:
  - economy: fastest, cheapest, lower quality (e.g., local 2.5D, fast models)
  - standard: balanced (e.g., Happy Horse standard, Kling std)
  - premium: highest quality, slower, more expensive (e.g., Kling pro, Sora)
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from video_providers import get_video_provider_spec, list_video_provider_specs, VideoProviderSpec

logger = logging.getLogger(__name__)


@dataclass
class ProviderCost:
    """Cost model for a provider."""
    provider_id: str
    cost_per_second: float = 0.0  # CNY per second of video
    cost_per_image: float = 0.0  # CNY per image
    avg_latency_seconds: float = 60.0  # Average generation time
    quality_score: float = 0.5  # 0.0 to 1.0
    tier: str = "standard"  # economy, standard, premium
    max_duration: int = 10  # Max video duration in seconds
    available: bool = True


# Default cost models (configurable via env)
DEFAULT_COSTS: dict[str, ProviderCost] = {
    "local": ProviderCost(
        provider_id="local",
        cost_per_second=0.0,
        cost_per_image=0.0,
        avg_latency_seconds=5.0,
        quality_score=0.3,
        tier="economy",
        max_duration=30,
    ),
    "xl": ProviderCost(
        provider_id="xl",
        cost_per_second=0.02,
        cost_per_image=0.01,
        avg_latency_seconds=120.0,
        quality_score=0.75,
        tier="standard",
        max_duration=10,
    ),
    "comfyui": ProviderCost(
        provider_id="comfyui",
        cost_per_second=0.005,
        cost_per_image=0.005,
        avg_latency_seconds=30.0,
        quality_score=0.7,
        tier="standard",
        max_duration=10,
    ),
    "sora": ProviderCost(
        provider_id="sora",
        cost_per_second=0.10,
        cost_per_image=0.05,
        avg_latency_seconds=180.0,
        quality_score=0.95,
        tier="premium",
        max_duration=20,
    ),
    "doubao": ProviderCost(
        provider_id="doubao",
        cost_per_second=0.03,
        cost_per_image=0.02,
        avg_latency_seconds=90.0,
        quality_score=0.8,
        tier="standard",
        max_duration=10,
    ),
    "seedance": ProviderCost(
        provider_id="seedance",
        cost_per_second=0.04,
        cost_per_image=0.02,
        avg_latency_seconds=100.0,
        quality_score=0.85,
        tier="premium",
        max_duration=10,
    ),
}


@dataclass
class RouteRequest:
    """Request for provider routing."""
    kind: str = "video"  # "video" or "image"
    duration: float = 5.0
    quality_min: float = 0.5  # Minimum acceptable quality
    budget_max: float = 1.0  # Maximum cost in CNY
    deadline_seconds: float = 300.0  # Must complete within this time
    prefer_tier: str = ""  # Prefer a specific tier
    exclude_providers: list[str] = field(default_factory=list)


@dataclass
class RouteResult:
    """Result of provider routing."""
    provider_id: str
    provider_spec: VideoProviderSpec | None
    reason: str
    estimated_cost: float
    estimated_latency: float
    quality_score: float
    tier: str
    fallback_chain: list[str] = field(default_factory=list)


def _load_provider_costs() -> dict[str, ProviderCost]:
    """Load provider costs, allowing env overrides."""
    costs = dict(DEFAULT_COSTS)
    # Allow env overrides like PROVIDER_XL_COST_PER_SECOND=0.03
    for provider_id, cost in costs.items():
        prefix = f"PROVIDER_{provider_id.upper()}"
        raw_cost = os.environ.get(f"{prefix}_COST_PER_SECOND", "").strip()
        if raw_cost:
            try:
                cost.cost_per_second = float(raw_cost)
            except ValueError:
                pass
        raw_quality = os.environ.get(f"{prefix}_QUALITY_SCORE", "").strip()
        if raw_quality:
            try:
                cost.quality_score = float(raw_quality)
            except ValueError:
                pass
    return costs


def _is_provider_configured(provider_id: str) -> bool:
    """Check if a provider has the minimum required configuration."""
    spec = get_video_provider_spec(provider_id)
    if spec.backend == "local":
        return True
    prefix = provider_id.upper().replace("-", "_")
    api_key = os.environ.get(f"{prefix}_API_KEY", "").strip()
    return bool(api_key)


def route_provider(request: RouteRequest) -> RouteResult:
    """Select the optimal provider based on constraints.

    Priority:
    1. Filter by availability and configuration
    2. Filter by quality minimum
    3. Filter by budget
    4. Filter by deadline
    5. Sort by quality (descending) within budget
    """
    costs = _load_provider_costs()
    candidates: list[tuple[str, ProviderCost]] = []

    for provider_id, cost in costs.items():
        # Skip excluded
        if provider_id in request.exclude_providers:
            continue
        # Skip unconfigured
        if not _is_provider_configured(provider_id):
            continue
        # Skip if quality too low
        if cost.quality_score < request.quality_min:
            continue
        # Skip if too slow
        if cost.avg_latency_seconds > request.deadline_seconds:
            continue
        # Skip if over budget
        estimated_cost = cost.cost_per_second * request.duration if request.kind == "video" else cost.cost_per_image
        if estimated_cost > request.budget_max:
            continue
        # Skip if duration exceeds provider max
        if request.kind == "video" and request.duration > cost.max_duration:
            continue
        # Prefer tier if specified
        candidates.append((provider_id, cost))

    if not candidates:
        # Fallback to local
        return RouteResult(
            provider_id="local",
            provider_spec=get_video_provider_spec("local"),
            reason="No provider meets all constraints, falling back to local",
            estimated_cost=0.0,
            estimated_latency=5.0,
            quality_score=0.3,
            tier="economy",
            fallback_chain=["local"],
        )

    # Sort: prefer tier match, then quality descending
    def sort_key(item: tuple[str, ProviderCost]) -> tuple[int, float]:
        _, cost = item
        tier_match = 0 if request.prefer_tier and cost.tier == request.prefer_tier else 1
        return (tier_match, -cost.quality_score)

    candidates.sort(key=sort_key)
    best_id, best_cost = candidates[0]
    estimated_cost = best_cost.cost_per_second * request.duration if request.kind == "video" else best_cost.cost_per_image

    # Build fallback chain
    fallback_chain = [pid for pid, _ in candidates[1:3]] + ["local"]

    return RouteResult(
        provider_id=best_id,
        provider_spec=get_video_provider_spec(best_id),
        reason=f"Best quality ({best_cost.quality_score:.2f}) within budget (¥{estimated_cost:.3f})",
        estimated_cost=round(estimated_cost, 4),
        estimated_latency=best_cost.avg_latency_seconds,
        quality_score=best_cost.quality_score,
        tier=best_cost.tier,
        fallback_chain=fallback_chain,
    )


def estimate_project_cost(project: dict[str, Any], provider_id: str = "") -> dict[str, Any]:
    """Estimate total cost for rendering all scenes in a project."""
    costs = _load_provider_costs()
    scenes = [s for s in project.get("scenes", []) if isinstance(s, dict)]

    if not provider_id:
        provider_id = os.environ.get("VIDEO_PROVIDER", "xl").strip().lower()

    cost_model = costs.get(provider_id, DEFAULT_COSTS.get("xl", ProviderCost(provider_id="unknown")))

    total_duration = sum(float(s.get("duration_seconds") or 5.0) for s in scenes)
    video_cost = cost_model.cost_per_second * total_duration
    image_cost = cost_model.cost_per_image * len(scenes)
    total_cost = video_cost + image_cost
    total_time = cost_model.avg_latency_seconds * len(scenes)

    return {
        "provider": provider_id,
        "tier": cost_model.tier,
        "scene_count": len(scenes),
        "total_duration_seconds": round(total_duration, 1),
        "estimated_video_cost_cny": round(video_cost, 3),
        "estimated_image_cost_cny": round(image_cost, 3),
        "estimated_total_cost_cny": round(total_cost, 3),
        "estimated_total_time_seconds": round(total_time, 0),
        "estimated_total_time_minutes": round(total_time / 60, 1),
    }
