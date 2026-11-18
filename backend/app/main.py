import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import catalog, health, incidents, proposals, runs
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.security import BodySizeLimitMiddleware, SafeResponseMiddleware
from app.storage.db import Database
from app.storage.repositories import RunRepository
from app.workflow.engine import WorkflowLimits


def create_app(database_path: str | None = None, provider=None, workflow_limits=None, clock=None,
               reviewers: frozenset[str] | None = None, adapter_factory=None) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level,
                      secrets=[settings.llm_api_key.get_secret_value() if settings.llm_api_key else None])
    db = Database(database_path or settings.database_path)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # A run that was queued or running when the previous server stopped will never finish.
        recovered = RunRepository(db).fail_interrupted()
        if recovered:
            logging.getLogger("fabricops.startup").warning(
                "marked %d interrupted run(s) as failed: %s", len(recovered), ", ".join(recovered))
        yield

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    # Added innermost first: errors and oversized bodies are answered inside CORS, so the browser can read them.
    app.add_middleware(SafeResponseMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.state.db = db
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
