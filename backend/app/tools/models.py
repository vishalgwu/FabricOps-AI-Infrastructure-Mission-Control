"""Typed inputs and outputs for the telemetry tools."""
from datetime import timedelta
from enum import Enum
from typing import Annotated, Any

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.schemas.common import StrictModel, UtcDatetime
from app.schemas.domain import METRIC_UNITS, EvidenceRecord

# ---- hard bounds (the model/caller cannot raise these) ----
MAX_WINDOW_MINUTES = 720          # metrics: at most 12 hours back
MAX_LOG_SPAN = timedelta(hours=24)
MAX_LOG_LIMIT = 100
DEFAULT_LOG_LIMIT = 50
MAX_METRIC_FILTER = 10
MAX_SAMPLES_PER_CALL = 1000
MAX_LOG_MESSAGE_CHARS = 500

HostId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", max_length=64)]


class ToolStatus(str, Enum):
    """Outcome of a tool call. Only OK and STALE carry usable readings; none of the others
    may ever be interpreted as a measurement (and certainly not as zero)."""

    OK = "ok"                 # fresh readings returned (a reading of 0 is still OK)
    NO_DATA = "no_data"       # the source has nothing for this request
    STALE = "stale"           # data exists but is older than the freshness threshold
    TIMEOUT = "timeout"       # the source did not answer in time
    ERROR = "error"           # the source failed
    REJECTED = "rejected"     # unknown tool, invalid input, unknown host, or out of scope
    MALFORMED = "malformed"   # the source returned data that failed validation


class TimeRange(StrictModel):
    start: UtcDatetime
    end: UtcDatetime

    @model_validator(mode="after")
    def _check(self) -> "TimeRange":
        if self.end <= self.start:
            raise ValueError("time_range.end must be after time_range.start")
        if self.end - self.start > MAX_LOG_SPAN:
            raise ValueError(f"time_range may span at most {MAX_LOG_SPAN}")
        return self


class ReadMetricsInput(StrictModel):
    host_id: HostId
    time_window_minutes: int = Field(ge=1, le=MAX_WINDOW_MINUTES)
    metrics: list[str] | None = Field(default=None, max_length=MAX_METRIC_FILTER)

    @field_validator("metrics")
    @classmethod
    def _known(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            bad = [m for m in v if m not in METRIC_UNITS]
            if bad:
                raise ValueError(f"unknown metric(s) {bad}; supported: {sorted(METRIC_UNITS)}")
        return v


class ReadLogsInput(StrictModel):
    host_id: HostId
    time_range: TimeRange
    limit: int = Field(default=DEFAULT_LOG_LIMIT, ge=1, le=MAX_LOG_LIMIT)


class ReadConfigInput(StrictModel):
    host_id: HostId


class Freshness(StrictModel):
    as_of: UtcDatetime
    newest_observed_at: UtcDatetime | None
    age_seconds: float | None
    threshold_seconds: float


class ToolResult(StrictModel):
    tool_name: str
    status: ToolStatus
    parameters: dict[str, Any]           # the validated parameters (or the raw ones if rejected)
    host_scope: list[str]                # hosts this call was allowed to read
    collected_at: UtcDatetime
    as_of: UtcDatetime                   # the reference time freshness was judged against
    evidence_ids: list[str]
    records: list[EvidenceRecord]
    provenance: list[str]                # distinct data sources the records came from
    observed_from: UtcDatetime | None
    observed_to: UtcDatetime | None
    freshness: Freshness | None = None
    truncated: bool = False
    error_code: str | None = None
    message: str | None = None

    @property
    def has_readings(self) -> bool:
        return self.status in (ToolStatus.OK, ToolStatus.STALE)
