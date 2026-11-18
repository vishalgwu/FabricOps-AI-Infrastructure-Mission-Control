"""FastAPI dependencies: build services from the app's Database."""
from fastapi import Depends, Request

from app.services.services import IncidentService, RunService
from app.workflow.engine import InvestigationWorkflow
from app.storage.db import Database
from app.services.proposals import ProposalService
from app.storage.repositories import (
    EvidenceRepository,
    IncidentRepository,
    ProposalRepository,
    RunRepository,
)


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_incident_service(db: Database = Depends(get_db)) -> IncidentService:
    return IncidentService(IncidentRepository(db))


def get_run_service(db: Database = Depends(get_db)) -> RunService:
    return RunService(RunRepository(db), IncidentRepository(db))


def get_proposal_service(request: Request) -> ProposalService:
    return build_proposal_service(request.app)


def build_proposal_service(app) -> ProposalService:
    from datetime import timedelta

    from app.core.config import get_settings

    settings = get_settings()
    db = app.state.db
    return ProposalService(
        ProposalRepository(db), EvidenceRepository(db), RunRepository(db),
        reviewers=app.state.reviewers if app.state.reviewers is not None else settings.reviewer_set,
        approval_ttl=timedelta(minutes=settings.approval_ttl_minutes), clock=app.state.clock,
    )


def get_workflow(request: Request) -> InvestigationWorkflow:
    """Build the workflow on first use (loads fixtures and the document corpus), then reuse it."""
    app = request.app
    if getattr(app.state, "workflow", None) is None:
        from app.core.config import get_settings
        from app.domain.fixture_loader import load_all_fixtures
        from app.llm.factory import create_provider
        from app.retrieval.index import load_corpus

        settings = get_settings()
        fixtures = {fx.incident.scenario_type: fx for fx in load_all_fixtures().values()}
        provider = app.state.provider
        app.state.workflow = InvestigationWorkflow(
            app.state.db, fixtures, load_corpus(),
            (lambda: provider) if provider is not None else (lambda: create_provider(settings)),
            build_proposal_service(app),
            limits=app.state.workflow_limits,
        )
    return app.state.workflow
