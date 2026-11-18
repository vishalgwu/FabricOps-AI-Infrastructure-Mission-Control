import re

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.deps import get_incident_service, get_run_service, get_workflow
from app.schemas.common import ScenarioType, Severity
from app.schemas.domain import Incident, Run
from app.services.services import IncidentService, RunService
from app.workflow.engine import InvestigationWorkflow

router = APIRouter(prefix="/api")

_HOST_ID = r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"


class IncidentCreate(BaseModel):
    """Request body. The server generates `id` and `created_at`; clients cannot set them."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    scenario_type: ScenarioType
    severity: Severity = Severity.UNKNOWN
    affected_hosts: list[str] = Field(min_length=1, max_length=50)

    @field_validator("affected_hosts")
    @classmethod
    def _valid_host_ids(cls, hosts: list[str]) -> list[str]:
        bad = [h for h in hosts if not re.match(_HOST_ID, h)]
        if bad:
            raise ValueError(f"invalid host id(s): {bad}")
        return hosts


class IncidentList(BaseModel):
    items: list[Incident]
    total: int
    limit: int
    offset: int


@router.post("/incidents", response_model=Incident, status_code=status.HTTP_201_CREATED)
def create_incident(body: IncidentCreate, svc: IncidentService = Depends(get_incident_service)):
    return svc.create(**body.model_dump())


@router.get("/incidents", response_model=IncidentList)
def list_incidents(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    svc: IncidentService = Depends(get_incident_service),
):
    items, total = svc.list(limit, offset)
    return IncidentList(items=items, total=total, limit=limit, offset=offset)


@router.get("/incidents/{incident_id}", response_model=Incident)
def get_incident(incident_id: str, svc: IncidentService = Depends(get_incident_service)):
    return svc.get(incident_id)


@router.get("/incidents/{incident_id}/runs", response_model=list[Run])
def list_incident_runs(incident_id: str, svc: RunService = Depends(get_run_service)):
    return svc.list_for_incident(incident_id)


@router.post("/incidents/{incident_id}/runs", response_model=Run, status_code=status.HTTP_202_ACCEPTED)
def start_investigation(
    incident_id: str,
    background: BackgroundTasks,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=1, max_length=64,
                                         pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"),
    svc: RunService = Depends(get_run_service),
    workflow: InvestigationWorkflow = Depends(get_workflow),
):
    """Start an investigation and return immediately (202). The work runs in the background;
    poll `GET /api/runs/{id}` and `GET /api/runs/{id}/events`.

    Repeating the request does not start a second investigation: the same Idempotency-Key, or
    an investigation already in flight for this incident, returns the existing run with 200.
    """
    run, created = svc.start(incident_id, idempotency_key)
    if created:
        background.add_task(workflow.execute, run.id)
    else:
        response.status_code = status.HTTP_200_OK
    return run
