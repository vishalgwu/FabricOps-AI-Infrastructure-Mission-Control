from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.deps import get_db, get_run_service
from app.core.errors import NotFoundError
from app.schemas.common import ScenarioType
from app.schemas.domain import EvidenceRecord, InvestigationReport, Run
from app.services.services import RunService
from app.storage.db import Database
from app.storage.repositories import EvidenceRepository, ReportRepository

router = APIRouter(prefix="/api")

MAX_OFFSET = 2**31 - 1  # larger values cannot be stored by SQLite and used to cause a 500


class RunSummary(Run):
    incident_title: str
    scenario_type: ScenarioType


class RunList(BaseModel):
    items: list[RunSummary]
    total: int
    limit: int
    offset: int


@router.get("/runs", response_model=RunList)
def list_runs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=MAX_OFFSET),
    svc: RunService = Depends(get_run_service),
):
    """Run history across all incidents, newest first."""
    rows, total = svc.list_recent(limit, offset)
    items = [RunSummary(**run.model_dump(), incident_title=title, scenario_type=scenario)
             for run, title, scenario in rows]
    return RunList(items=items, total=total, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=Run)
def get_run(run_id: str, svc: RunService = Depends(get_run_service)):
    return svc.get(run_id)


@router.get("/runs/{run_id}/events")
def get_run_events(
    run_id: str,
    after_seq: int = Query(0, ge=0, le=MAX_OFFSET, description="Return only events after this sequence number"),
    svc: RunService = Depends(get_run_service),
):
    """Ordered stage and state events. A client that refreshed or reconnected passes the last
    `seq` it saw and receives everything after it; with 0 it replays the whole run."""
    events = svc.events(run_id, after_seq)
    return {"run_id": run_id, "events": events, "last_seq": events[-1]["seq"] if events else after_seq}


@router.get("/runs/{run_id}/report", response_model=InvestigationReport)
def get_run_report(run_id: str, svc: RunService = Depends(get_run_service), db: Database = Depends(get_db)):
    svc.get(run_id)
    report = ReportRepository(db).get(run_id)
    if report is None:
        raise NotFoundError(f"run '{run_id}' has no report (it may still be running, or it failed)")
    return report


@router.get("/runs/{run_id}/evidence", response_model=list[EvidenceRecord])
def list_run_evidence(run_id: str, svc: RunService = Depends(get_run_service), db: Database = Depends(get_db)):
    """Every evidence record collected for this run (the records the report's citations point at)."""
    svc.get(run_id)
    return EvidenceRepository(db).list_for_run(run_id)


@router.get("/runs/{run_id}/evidence/{evidence_id}", response_model=EvidenceRecord)
def get_run_evidence(run_id: str, evidence_id: str, svc: RunService = Depends(get_run_service),
                     db: Database = Depends(get_db)):
    """Resolve one evidence ID. It must belong to this run: another run's evidence never resolves here."""
    svc.get(run_id)
    record = EvidenceRepository(db).get(evidence_id)
    if record is None or record.run_id != run_id:
        raise NotFoundError(f"evidence '{evidence_id}' not found for run '{run_id}'")
    return record
