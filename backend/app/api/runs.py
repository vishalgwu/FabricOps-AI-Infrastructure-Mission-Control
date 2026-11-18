from fastapi import APIRouter, Depends, Query

from app.api.deps import get_db, get_run_service
from app.core.errors import NotFoundError
from app.schemas.domain import InvestigationReport, Run
from app.services.services import RunService
from app.storage.repositories import ReportRepository

from app.storage.db import Database

router = APIRouter(prefix="/api")


@router.get("/runs/{run_id}", response_model=Run)
def get_run(run_id: str, svc: RunService = Depends(get_run_service)):
    return svc.get(run_id)


@router.get("/runs/{run_id}/events")
def get_run_events(
    run_id: str,
    after_seq: int = Query(0, ge=0, description="Return only events after this sequence number"),
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
