"""The controlled investigation workflow: a fixed, bounded sequence of stages.

This is deliberately not an agent loop. The stages run in order, each tool is called a
known number of times, the model is called at most once (plus bounded transient retries),
and nothing is ever executed on a host.

Stages: load_incident -> validate_scope -> collect_telemetry -> check_freshness ->
persist_evidence -> retrieve_docs -> investigate -> apply_policy -> persist_report.
A proposal that policy says needs approval parks the run in WAITING_APPROVAL; nothing is executed.
"""
import json
import logging
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta

from app.core.errors import InvalidTransitionError
from app.llm.investigator import InvestigationOutcome, Investigator
from app.llm.package import build_package
from app.llm.provider import LLMProvider
from app.retrieval.index import DocumentIndex
from app.retrieval.tool import DocSearchTool
from app.policy.policy import PolicyViolation
from app.schemas.common import ApprovalStatus, RunStatus, ScenarioType
from app.schemas.domain import Run
from app.schemas.fixtures import ScenarioFixture
from app.services.proposals import ProposalService
from app.services.services import RunService
from app.storage.db import Database
from app.storage.repositories import (
    EvidenceRepository,
    IncidentRepository,
    ReportRepository,
    RunRepository,
)
from app.tools.adapter import FixtureAdapter
from app.tools.models import MAX_WINDOW_MINUTES, ToolResult, ToolStatus
from app.tools.telemetry import TelemetryTools

log = logging.getLogger("fabricops.workflow")


@dataclass(frozen=True)
class WorkflowLimits:
    max_tool_calls: int = 12
    max_hosts: int = 8
    metrics_window_minutes: int = 60       # the time range read per host
    max_time_range_minutes: int = 120      # hard cap on any time range this workflow may request
    max_evidence_records: int = 200
    max_document_chunks: int = 5
    max_run_seconds: float = 120.0
    llm_max_tokens: int = 8000
    llm_max_attempts: int = 3
    max_output_chars: int = 60_000

    def __post_init__(self) -> None:
        if not 1 <= self.metrics_window_minutes <= min(self.max_time_range_minutes, MAX_WINDOW_MINUTES):
            raise ValueError("metrics_window_minutes must be within max_time_range_minutes and the tool bound")


class WorkflowAbort(Exception):
    """A stage failed. `code` and `message` are safe to show to users and store."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class InvestigationWorkflow:
    def __init__(
        self,
        db: Database,
        fixtures: dict[ScenarioType, ScenarioFixture],
        docs: DocumentIndex,
        provider_factory: Callable[[], LLMProvider],
        proposals: ProposalService,
        limits: WorkflowLimits = WorkflowLimits(),
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._db = db
        self._fixtures = fixtures
        self._docs = docs
        self._provider_factory = provider_factory
        self._proposals = proposals
        self.limits = limits
        self._monotonic = monotonic
        self._sleep = sleep
        self._runs = RunRepository(db)
        self._incidents = IncidentRepository(db)
        self._evidence = EvidenceRepository(db)
        self._reports = ReportRepository(db)
        self._run_service = RunService(self._runs, self._incidents)

    # ---- public entry point ----

    def execute(self, run_id: str) -> Run:
        """Run the investigation for a CREATED run and return the final run. Never raises.

        Idempotent: a run that is not CREATED is returned untouched, and the CREATED -> RUNNING
        compare-and-swap lets exactly one caller execute a given run.
        """
        run = self._run_service.get(run_id)
        if run.status != RunStatus.CREATED:
            return run
        try:
            self._run_service.transition(run_id, RunStatus.RUNNING)
        except InvalidTransitionError:
            return self._run_service.get(run_id)  # someone else started it first

        deadline = self._monotonic() + self.limits.max_run_seconds
        try:
            outcome, final_status = self._pipeline(run, deadline)
            self._finish(run_id, final_status, outcome.error_code)
        except WorkflowAbort as abort:  # the failing stage already recorded a stage_failed event
            self._finish(run_id, RunStatus.FAILED, abort.code)
        except Exception:  # noqa: BLE001 - last line of defence; details go to the log, not the user
            log.exception("unexpected error in workflow for %s", run_id)
            self._runs.add_event(run_id, "stage_failed", json.dumps(
                {"code": "internal_error", "message": "An unexpected error occurred; see server logs."}))
            self._finish(run_id, RunStatus.FAILED, "internal_error")
        return self._run_service.get(run_id)

    # ---- stages ----

    def _pipeline(self, run: Run, deadline: float) -> tuple[InvestigationOutcome, RunStatus]:
        lim = self.limits

        def check_time() -> None:
            if self._monotonic() > deadline:
                raise WorkflowAbort("run_timeout", f"the run exceeded its {lim.max_run_seconds:g}s time limit")

        # 1. Load incident
        with self._stage(run.id, "load_incident"):
            incident = self._incidents.get(run.incident_id)
            if incident is None:
                raise WorkflowAbort("incident_not_found", "the incident for this run no longer exists")
            fixture = self._fixtures.get(incident.scenario_type)
            if fixture is None:
                raise WorkflowAbort("unsupported_scenario",
                                    f"no data source for scenario '{incident.scenario_type.value}'")

        # 2. Validate host scope and limits (before any work is done)
        with self._stage(run.id, "validate_scope") as done:
            inventory = sorted(h.id for h in fixture.hosts)
            unknown = [h for h in incident.affected_hosts if h not in inventory]
            if unknown:
                raise WorkflowAbort("invalid_host_scope",
                                    f"host(s) {unknown} are not in this scenario's inventory {inventory}")
            if len(inventory) > lim.max_hosts:
                raise WorkflowAbort("limit_exceeded", f"{len(inventory)} hosts exceeds the limit of {lim.max_hosts}")
            planned = len(inventory) + 2 * len(incident.affected_hosts)
            if planned > lim.max_tool_calls:
                raise WorkflowAbort("limit_exceeded", f"{planned} planned tool calls exceeds the limit of {lim.max_tool_calls}")
            done({"hosts": inventory, "affected_hosts": incident.affected_hosts, "planned_tool_calls": planned})

        # 3. Collect read-only telemetry through the typed tools (every call is counted)
        tools = TelemetryTools(FixtureAdapter.from_fixture(fixture), run.id, self._evidence, allowed_hosts=set(inventory))
        results: list[ToolResult] = []
        calls = 0

        def counted(fn: Callable[[], ToolResult]) -> ToolResult:
            nonlocal calls
            check_time()
            if calls >= lim.max_tool_calls:
                raise WorkflowAbort("limit_exceeded", f"tool call limit of {lim.max_tool_calls} reached")
            calls += 1
            return fn()

        with self._stage(run.id, "collect_telemetry") as done:
            window_end = fixture.reference_time
            rng = {"start": (window_end - timedelta(minutes=lim.metrics_window_minutes)).isoformat(),
                   "end": window_end.isoformat()}
            for host in inventory:
                results.append(counted(lambda h=host: tools.read_metrics(h, lim.metrics_window_minutes)))
            for host in incident.affected_hosts:
                results.append(counted(lambda h=host: tools.read_logs(h, rng)))
                results.append(counted(lambda h=host: tools.read_config(h)))
            done({"tool_calls": calls,
                  "results": [{"tool": r.tool_name, "host": r.parameters.get("host_id"), "status": r.status.value}
                              for r in results]})

        # 4. Check freshness (judged by observation time inside the tools)
        with self._stage(run.id, "check_freshness") as done:
            freshness = {r.parameters["host_id"]: r.status.value for r in results if r.tool_name == "read_metrics"}
            done({"metrics_status_by_host": freshness,
                  "all_fresh": all(v == ToolStatus.OK.value for v in freshness.values())})

        # 5. Evidence is persisted by the tools (deterministic IDs); verify and enforce the cap
        with self._stage(run.id, "persist_evidence") as done:
            stored = self._evidence.list_for_run(run.id)
            if len(stored) > lim.max_evidence_records:
                raise WorkflowAbort("limit_exceeded",
                                    f"{len(stored)} evidence records exceeds the limit of {lim.max_evidence_records}")
            done({"evidence_records": len(stored)})

        # 6. Retrieve approved documentation
        check_time()
        with self._stage(run.id, "retrieve_docs") as done:
            doc_result = DocSearchTool(self._docs).search_docs(
                f"{incident.title}. {incident.description}", top_k=min(lim.max_document_chunks, 10))
            done({"status": doc_result.status.value, "citation_ids": doc_result.citation_ids})

        # 7-8. Call the investigator once; it validates the output and every referenced ID
        check_time()
        with self._stage(run.id, "investigate") as done:
            package = build_package(run.id, incident, inventory, results, doc_result, fixture.reference_time)
            investigator = Investigator(
                provider_factory=self._provider_factory, max_tokens=lim.llm_max_tokens,
                max_attempts=lim.llm_max_attempts, sleep=self._sleep, max_output_chars=lim.max_output_chars)
            outcome = investigator.investigate(package)
            m = outcome.metadata
            if outcome.status == RunStatus.FAILED:
                if m.llm_called:  # still record which model/prompt produced the failed attempt
                    self._runs.record_model_metadata(run.id, m.model_id, m.prompt_version)
                detail = "; ".join(e[:200] for e in outcome.errors[:3])
                raise WorkflowAbort(outcome.error_code or "investigation_failed",
                                    f"after {m.attempts} model attempt(s): {detail}")
            done({"status": outcome.status.value, "llm_called": m.llm_called, "provider": m.provider,
                  "model_id": m.model_id, "prompt_version": m.prompt_version if m.llm_called else None,
                  "attempts": m.attempts, "latency_ms": m.latency_ms, "usage": m.usage})

        # 9. Apply deterministic policy to the suggested next step (the model cannot authorise anything)
        final_status = outcome.status
        with self._stage(run.id, "apply_policy") as done:
            proposal = None
            if outcome.report is not None:
                try:
                    proposal = self._proposals.create_for_run(outcome.report, incident.affected_hosts)
                except PolicyViolation as exc:
                    raise WorkflowAbort("policy_violation", str(exc)) from exc
            if proposal is None:
                done({"proposal": None})
            else:
                if proposal.approval_status == ApprovalStatus.PENDING:
                    final_status = RunStatus.WAITING_APPROVAL  # parked until a human decides
                done({"proposal_id": proposal.id, "risk_class": proposal.risk_class.value,
                      "approval_status": proposal.approval_status.value, "proposal_hash": proposal.proposal_hash,
                      "reasons": proposal.policy_reasons, "executed": False})

        # 10. Persist the report and model metadata
        with self._stage(run.id, "persist_report") as done:
            if outcome.report is not None:
                self._reports.save(outcome.report)
            used = outcome.metadata.llm_called
            self._runs.record_model_metadata(run.id, outcome.metadata.model_id if used else None,
                                             outcome.metadata.prompt_version if used else None)
            done({"report_saved": outcome.report is not None})
        return outcome, final_status

    # ---- helpers ----

    @contextmanager
    def _stage(self, run_id: str, name: str):
        self._runs.add_event(run_id, "stage_started", json.dumps({"stage": name}))
        data: dict = {}

        def done(info: dict | None = None) -> None:
            data.update(info or {})

        try:
            yield done
        except WorkflowAbort as abort:
            self._runs.add_event(run_id, "stage_failed",
                                 json.dumps({"stage": name, "code": abort.code, "message": abort.message}))
            raise WorkflowAbort(abort.code, abort.message) from None
        self._runs.add_event(run_id, "stage_completed", json.dumps({"stage": name, **data}, default=str))

    def _finish(self, run_id: str, status: RunStatus, error_code: str | None) -> None:
        try:
            self._run_service.transition(run_id, status, error_code)
        except InvalidTransitionError:
            log.warning("run %s could not move to %s", run_id, status.value)
