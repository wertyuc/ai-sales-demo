"""Application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import scheduler
from .api import crm as crm_api
from .api import live as live_api
from .api import misc as misc_api
from .config import settings
from .db import Base, engine, session_scope
from .seed import run as run_seed

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s | %(message)s"
)
log = logging.getLogger("app")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    if settings.seed_on_startup:
        with session_scope() as db:
            summary = run_seed(db)
        log.info(
            "seed ready: %s products, %s leads, %s conversations",
            summary["products"], summary["leads"], summary["conversations"],
        )
    scheduler.start()
    yield
    await scheduler.stop()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    misc_api.auth_router,
    live_api.router,
    crm_api.router,
    misc_api.inventory_router,
    misc_api.followups_router,
    misc_api.analytics_router,
    misc_api.control_router,
    misc_api.kb_router,
    misc_api.logs_router,
    misc_api.system_router,
):
    app.include_router(router)


# --- single-page app ---------------------------------------------------------

if STATIC_DIR.exists():
    assets = STATIC_DIR / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")

else:  # pragma: no cover - dev without a built frontend

    @app.get("/", include_in_schema=False)
    def root():
        return {
            "app": settings.app_name,
            "note": "Frontend build not found. Run the Vite dev server on :5173.",
            "docs": "/api/docs",
        }
