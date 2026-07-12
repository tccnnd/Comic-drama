from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from backend.routers._common import FRONTEND

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")
