from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import catalog, health, incidents, proposals, runs
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.storage.db import Database
from app.workflow.engine import WorkflowLimits


def create_app(database_path: str | None = None, provider=None, workflow_limits=None, clock=None,
               reviewers: frozenset[str] | None = None, adapter_factory=None) -> FastAPI:
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
    app.state.provider = provider            # tests inject a mock; None means use backend settings
    app.state.workflow_limits = workflow_limits or WorkflowLimits()
    app.state.clock = clock or (lambda: datetime.now(timezone.utc))
    app.state.reviewers = reviewers          # None means use FABRICOPS_DEMO_REVIEWERS
    app.state.adapter_factory = adapter_factory  # test/eval hook: swap the telemetry data source
    app.state.fixtures = None                # loaded lazily
    app.state.docs = None                    # loaded lazily
    app.state.workflow = None                # built lazily on first use
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(incidents.router)
    app.include_router(runs.router)
    app.include_router(catalog.router)
    app.include_router(proposals.router)
    return app


app = create_app()
