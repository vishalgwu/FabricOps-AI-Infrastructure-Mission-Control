from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, incidents, runs
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.storage.db import Database


def create_app(database_path: str | None = None) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.state.db = Database(database_path or settings.database_path)
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(incidents.router)
    app.include_router(runs.router)
    return app


app = create_app()
