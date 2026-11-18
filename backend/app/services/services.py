"""Business logic for incidents and runs. Routes call these; these call repositories."""
import uuid
from datetime import datetime, timezone

from app.core.errors import InvalidTransitionError, NotFoundError
from app.domain.run_state import check_transition
from app.schemas.common import TERMINAL_RUN_STATUSES, RunStatus, ScenarioType, Severity
from app.schemas.domain import Incident, Run
from app.storage.repositories import IncidentRepository, RunRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class IncidentService:
    def __init__(self, incidents: IncidentRepository):
        self._incidents = incidents

    def create(
        self,
        title: str,
        description: str,
        scenario_type: ScenarioType,
        severity: Severity,
        affected_hosts: list[str],
    ) -> Incident:
        incident = Incident(
            id=_new_id("inc"),  # server-generated and never changed afterwards
            title=title,
            description=description,
            scenario_type=scenario_type,
            severity=severity,
            affected_hosts=affected_hosts,
            created_at=_now(),
            synthetic=True,  # the MVP only handles synthetic data
        )
        self._incidents.add(incident)
        return incident

    def get(self, incident_id: str) -> Incident:
        incident = self._incidents.get(incident_id)
        if incident is None:
            raise NotFoundError(f"incident '{incident_id}' not found")
        return incident

    def list(self, limit: int, offset: int) -> tuple[list[Incident], int]:
        return self._incidents.list(limit, offset)


class RunService:
    def __init__(self, runs: RunRepository, incidents: IncidentRepository):
        self._runs = runs
        self._incidents = incidents

    def create(self, incident_id: str) -> Run:
        """Create a run in CREATED state. (Starting/executing runs arrives in Phase 07.)"""
        if self._incidents.get(incident_id) is None:
            raise NotFoundError(f"incident '{incident_id}' not found")
        run = Run(id=_new_id("run"), incident_id=incident_id, status=RunStatus.CREATED, started_at=_now())
        self._runs.add(run)
        return run

    def get(self, run_id: str) -> Run:
        run = self._runs.get(run_id)
        if run is None:
            raise NotFoundError(f"run '{run_id}' not found")
        return run

    def list_for_incident(self, incident_id: str) -> list[Run]:
        if self._incidents.get(incident_id) is None:
            raise NotFoundError(f"incident '{incident_id}' not found")
        return self._runs.list_for_incident(incident_id)

    def events(self, run_id: str) -> list[dict]:
        self.get(run_id)
        return self._runs.events(run_id)

    def transition(self, run_id: str, target: RunStatus, error_code: str | None = None) -> Run:
        run = self.get(run_id)
        check_transition(run.status, target)
        finished = target in TERMINAL_RUN_STATUSES
        if not self._runs.transition(run_id, run.status, target, _now(), finished, error_code):
            raise InvalidTransitionError(
                f"run '{run_id}' changed state concurrently; reload it and try again"
            )
        return self.get(run_id)
