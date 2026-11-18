"""Domain models for FabricOps (Phase 02). All demo data is synthetic."""
import math
import re
from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from app.schemas.common import (
    ApprovalStatus,
    Confidence,
    RiskClass,
    ScenarioType,
    Severity,
    StrictModel,
    Unit,
    UtcDatetime,
    RunStatus,
)

# Each supported metric has exactly one valid unit. Anything else is rejected.
METRIC_UNITS: dict[str, Unit] = {
    "request_latency_p95": Unit.MILLISECONDS,
    "requests_per_second": Unit.REQUESTS_PER_SECOND,
    "gpu_utilization": Unit.PERCENT,
    "kv_cache_used_pct": Unit.PERCENT,
    "gpu_memory_used": Unit.BYTES,
    "network_latency": Unit.MILLISECONDS,
    "packet_loss": Unit.PERCENT,
    "link_error_count": Unit.COUNT,
    "link_retrain_count": Unit.COUNT,
}

_ID = r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class Host(StrictModel):
    id: str = Field(pattern=_ID)
    role: str
    synthetic: bool = True


class Incident(StrictModel):
    id: str = Field(pattern=_ID)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    scenario_type: ScenarioType
    severity: Severity
    affected_hosts: list[str] = Field(min_length=1)
    created_at: UtcDatetime
    synthetic: bool


class MetricSample(StrictModel):
    """One reading. `value` is None when the source reported nothing; None is never zero."""

    host_id: str
    source: str = Field(min_length=1)
    metric: str
    value: float | None
    unit: Unit
    observed_at: UtcDatetime
    ingested_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _check_metric(self) -> "MetricSample":
        expected = METRIC_UNITS.get(self.metric)
        if expected is None:
            raise ValueError(f"unknown metric '{self.metric}'; supported: {sorted(METRIC_UNITS)}")
        if self.unit != expected:
            raise ValueError(
                f"metric '{self.metric}' must use unit '{expected.value}', got '{self.unit.value}'"
            )
        if self.value is not None:
            if not math.isfinite(self.value):
                raise ValueError("value must be finite")
            if self.value < 0:
                raise ValueError("value must be non-negative")
            if self.unit == Unit.PERCENT and self.value > 100:
                raise ValueError("percent values must be between 0 and 100")
        return self


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class LogRecord(StrictModel):
    """Log text is untrusted data. It must never be treated as an instruction."""

    host_id: str
    source: str = Field(min_length=1)
    level: LogLevel
    message: str
    observed_at: UtcDatetime
    ingested_at: UtcDatetime | None = None


class HostConfiguration(StrictModel):
    host_id: str
    source: str = Field(min_length=1)
    observed_at: UtcDatetime
    settings: dict[str, str | int | float | bool | None]


class EvidenceRecord(StrictModel):
    id: str = Field(pattern=_ID)
    run_id: str
    source_type: str  # "metric" | "log" | "config"
    host_id: str
    tool_name: str
    observed_at: UtcDatetime
    ingested_at: UtcDatetime
    payload: dict[str, Any]
    synthetic: bool

    @field_validator("source_type")
    @classmethod
    def _source_type(cls, v: str) -> str:
        if v not in {"metric", "log", "config"}:
            raise ValueError("source_type must be 'metric', 'log' or 'config'")
        return v


class DocumentSourceKind(str, Enum):
    SYNTHETIC = "synthetic"
    OFFICIAL = "official"


class DocumentChunk(StrictModel):
    id: str = Field(pattern=_ID)
    document_id: str
    version: str
    title: str
    section: str
    text: str = Field(min_length=1)
    source: str
    synthetic_or_official: DocumentSourceKind


class Observation(StrictModel):
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class Hypothesis(StrictModel):
    """An interpretation, not a fact. Must carry supporting evidence and counterevidence."""

    statement: str = Field(min_length=1)
    confidence: Confidence
    supporting_evidence_ids: list[str] = Field(min_length=1)
    counterevidence: list[str]
    citations: list[str] = []


class ProposedTest(StrictModel):
    description: str = Field(min_length=1)
    target_scope: list[str] = Field(min_length=1)
    parameters: dict[str, str | int | float | bool] = {}
    evidence_ids: list[str] = []


class InvestigationReport(StrictModel):
    run_id: str
    severity: Severity
    insufficient_evidence: bool
    observations: list[Observation]
    hypotheses: list[Hypothesis]
    citations: list[str]
    missing_evidence: list[str]
    proposed_next_test: ProposedTest | None
    limitations: list[str]

    @model_validator(mode="after")
    def _abstention_rules(self) -> "InvestigationReport":
        if self.insufficient_evidence:
            if self.hypotheses:
                raise ValueError("an abstaining report must not contain hypotheses")
            if not self.missing_evidence:
                raise ValueError("an abstaining report must list the missing evidence")
        return self


class Proposal(StrictModel):
    id: str = Field(pattern=_ID)
    run_id: str
    version: int = Field(ge=1)
    description: str = Field(min_length=1)
    parameters: dict[str, str | int | float | bool] = {}
    target_scope: list[str] = Field(min_length=1)
    risk_class: RiskClass
    approval_status: ApprovalStatus
    proposal_hash: str
    expires_at: UtcDatetime | None = None

    @field_validator("proposal_hash")
    @classmethod
    def _hash(cls, v: str) -> str:
        if not _SHA256.match(v):
            raise ValueError("proposal_hash must be a 64-character lowercase hex SHA-256")
        return v

    @model_validator(mode="after")
    def _risk_requires_approval(self) -> "Proposal":
        if (
            self.risk_class == RiskClass.WRITE_OR_DEPLOY
            and self.approval_status == ApprovalStatus.NOT_REQUIRED
        ):
            raise ValueError("write_or_deploy proposals can never have approval_status 'not_required'")
        return self


class DecisionKind(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalDecision(StrictModel):
    id: str = Field(pattern=_ID)
    proposal_id: str
    proposal_hash: str
    actor: str = Field(min_length=1)
    decision: DecisionKind
    reason: str = Field(min_length=1)
    created_at: UtcDatetime


class Run(StrictModel):
    id: str = Field(pattern=_ID)
    incident_id: str
    status: RunStatus
    started_at: UtcDatetime
    finished_at: UtcDatetime | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    error_code: str | None = None
