"""Shared types: UTC timestamps, units, and enums used across the domain models."""
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone (use UTC, e.g. 2026-03-10T14:00:00Z)")
    return value.astimezone(timezone.utc)


# A timezone-aware ISO 8601 timestamp, normalised to UTC. Naive timestamps are rejected.
UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]


class StrictModel(BaseModel):
    """Base class: unknown fields are errors, so typos in fixtures are caught."""

    model_config = ConfigDict(extra="forbid")


class Unit(str, Enum):
    MILLISECONDS = "ms"
    PERCENT = "percent"
    BYTES = "bytes"
    REQUESTS_PER_SECOND = "requests_per_second"
    COUNT = "count"


class ScenarioType(str, Enum):
    INFERENCE_SLOWDOWN = "inference_slowdown"
    LINK_INSTABILITY = "link_instability"
    STALE_TELEMETRY = "stale_telemetry"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RunStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETE = "COMPLETE"
    ABSTAINED = "ABSTAINED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_RUN_STATUSES = frozenset(
    {RunStatus.COMPLETE, RunStatus.ABSTAINED, RunStatus.FAILED, RunStatus.CANCELLED}
)


class RiskClass(str, Enum):
    READ_ONLY_DIAGNOSTIC = "read_only_diagnostic"
    CONTROLLED_TEST = "controlled_test"
    WRITE_OR_DEPLOY = "write_or_deploy"


class ApprovalStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
