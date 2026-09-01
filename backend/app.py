from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.assets import asset_router
from backend.event_bus import project_event_bus
from backend.project_runtime import WORKSPACE
from backend.routers._common import (
    FRONTEND,
    OUTPUTS,
    configured_cors_origins,
)
from backend.routers.bgm import router as bgm_router
from backend.routers.characters import router as characters_router
from backend.routers.comfyui import router as comfyui_router
from backend.routers.llm import router as llm_router
from backend.routers.production import router as production_router
from backend.routers.projects import router as projects_router
from backend.routers.scenes import router as scenes_router
from backend.routers.script import router as script_router
from backend.routers.system import router as system_router
from backend.routers.tasks import router as tasks_router
from backend.routers.video_provider_routes import router as video_provider_routes_router
from backend.routers.voice import router as voice_router
from backend.styles import style_router

OUTPUTS.mkdir(parents=True, exist_ok=True)
WORKSPACE.mkdir(parents=True, exist_ok=True)


app = FastAPI(title="Comic Drama Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/outputs", StaticFiles(directory=OUTPUTS), name="outputs")
app.mount("/workspace", StaticFiles(directory=WORKSPACE), name="workspace")
app.mount("/frontend", StaticFiles(directory=FRONTEND), name="frontend")

# BGM 素材只读静态挂载：bgm.py 的 GET/POST 只返回素材的仓库相对路径
# （assets/audio/bgm/{style}/{file}），此前没有任何端点能把这些文件流给前端，
# 导致「试听 / 下载」无法工作。这里补一个只读挂载，前端按 /bgm/{style}/{file} 取用。
_BGM_DIR = OUTPUTS.parent / "assets" / "audio" / "bgm"
if _BGM_DIR.is_dir():
    app.mount("/bgm", StaticFiles(directory=_BGM_DIR), name="bgm")
app.include_router(style_router)
app.include_router(asset_router)
app.include_router(system_router)
app.include_router(video_provider_routes_router)
app.include_router(comfyui_router)
app.include_router(tasks_router)
app.include_router(bgm_router)
app.include_router(llm_router)
app.include_router(voice_router)
app.include_router(projects_router)
app.include_router(scenes_router)
app.include_router(script_router)
app.include_router(characters_router)
app.include_router(production_router)


@app.on_event("startup")
async def _startup() -> None:
    project_event_bus.set_event_loop(asyncio.get_running_loop())
    app.state.event_bus = project_event_bus
