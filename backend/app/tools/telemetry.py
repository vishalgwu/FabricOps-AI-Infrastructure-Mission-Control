"""Typed, read-only telemetry tools over the fixture adapter.

Only the three tools in TOOL_NAMES exist. The caller (later, the LLM workflow) can choose a tool
name and arguments, but cannot choose arbitrary hosts, URLs, file paths or commands: every
argument is validated, hosts must be known and in scope, and ranges/sizes are bounded.
"""
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ValidationError

from app.schemas.domain import EvidenceRecord
from app.storage.repositories import EvidenceRepository
from app.tools.adapter import (
    FixtureAdapter,
    MalformedSourceError,
    SourceError,
    SourceTimeout,
)
from app.tools.models import (
    MAX_LOG_MESSAGE_CHARS,
    MAX_SAMPLES_PER_CALL,
    Freshness,
    ReadConfigInput,
    ReadLogsInput,
    ReadMetricsInput,
    ToolResult,
    ToolStatus,
)

TOOL_NAMES = ("read_metrics", "read_logs", "read_config")
DEFAULT_FRESHNESS = timedelta(minutes=15)
DEFAULT_CONFIG_MAX_AGE = timedelta(hours=24)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _jsonable(value: Any) -> Any:
    """Make rejected/raw arguments safe to echo back (bounded, JSON-serialisable)."""
    try:
        text = json.dumps(value, default=str)
    except (TypeError, ValueError):
        return {"unserialisable": True}
    return json.loads(text[:2000]) if len(text) <= 2000 else {"truncated_arguments": text[:200]}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class _Outcome:
    status: ToolStatus
    records: list[EvidenceRecord] = field(default_factory=list)
    message: str | None = None
    newest_observed: datetime | None = None
    threshold: timedelta = DEFAULT_FRESHNESS
    truncated: bool = False
    observed_from: datetime | None = None
    observed_to: datetime | None = None


class TelemetryTools:
    def __init__(
        self,
        adapter: FixtureAdapter,
        run_id: str,
        evidence_repo: EvidenceRepository | None = None,
        allowed_hosts: set[str] | None = None,
        freshness_threshold: timedelta = DEFAULT_FRESHNESS,
        config_max_age: timedelta = DEFAULT_CONFIG_MAX_AGE,
        clock: Callable[[], datetime] = _now,
    ):
        self._adapter = adapter
        self._run_id = run_id
        self._repo = evidence_repo
        self._allowed = allowed_hosts  # None = every host the adapter knows about
        self._freshness = freshness_threshold
        self._config_max_age = config_max_age
        self._clock = clock
        self._tools: dict[str, tuple[type[BaseModel], Callable[[Any], _Outcome]]] = {
            "read_metrics": (ReadMetricsInput, self._metrics),
            "read_logs": (ReadLogsInput, self._logs),
            "read_config": (ReadConfigInput, self._config),
        }

    # ---- public API ----

    def read_metrics(self, host_id: str, time_window_minutes: int, metrics: list[str] | None = None) -> ToolResult:
        return self.call("read_metrics", {"host_id": host_id, "time_window_minutes": time_window_minutes,
                                          "metrics": metrics})

    def read_logs(self, host_id: str, time_range: dict | Any, limit: int = 50) -> ToolResult:
        if hasattr(time_range, "model_dump"):
            time_range = time_range.model_dump(mode="json")
        return self.call("read_logs", {"host_id": host_id, "time_range": time_range, "limit": limit})

    def read_config(self, host_id: str) -> ToolResult:
        return self.call("read_config", {"host_id": host_id})

    def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        """Run a registered tool by name. Never raises for bad input or source failure."""
        collected_at = self._clock()
        try:
            as_of = self._adapter.as_of
        except MalformedSourceError as exc:
            as_of = collected_at
            return self._result(name, _Outcome(ToolStatus.MALFORMED, message=str(exc)),
                                _jsonable(args), [], collected_at, as_of, "malformed_source")

        entry = self._tools.get(name)
        if entry is None:
            return self._result(name, _Outcome(ToolStatus.REJECTED, message=f"unknown tool '{name}'; "
                                f"registered tools: {list(TOOL_NAMES)}"),
                                _jsonable(args), [], collected_at, as_of, "unknown_tool")
        model_cls, fn = entry
        try:
            inp = model_cls.model_validate(args)
        except ValidationError as exc:
            msg = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
            return self._result(name, _Outcome(ToolStatus.REJECTED, message=f"invalid arguments: {msg}"),
                                _jsonable(args), [], collected_at, as_of, "invalid_arguments")

        params = inp.model_dump(mode="json")
        host_id = params["host_id"]
        try:
            known = self._adapter.known_hosts()
        except MalformedSourceError as exc:
            return self._result(name, _Outcome(ToolStatus.MALFORMED, message=str(exc)),
                                params, [], collected_at, as_of, "malformed_source")
        if host_id not in known:
            return self._result(name, _Outcome(ToolStatus.REJECTED, message=f"unknown host '{host_id}'"),
                                params, [], collected_at, as_of, "unknown_host")
        scope = sorted(known if self._allowed is None else known & self._allowed)
        if host_id not in scope:
            return self._result(name, _Outcome(ToolStatus.REJECTED,
                                message=f"host '{host_id}' is outside this run's scope {scope}"),
                                params, scope, collected_at, as_of, "out_of_scope")
        try:
            outcome = fn(inp)
            code = None
        except SourceTimeout:
            outcome, code = _Outcome(ToolStatus.TIMEOUT, message="the data source timed out"), "source_timeout"
        except SourceError as exc:
            outcome, code = _Outcome(ToolStatus.ERROR, message=f"the data source failed: {exc}"), "source_error"
        except MalformedSourceError as exc:
            outcome, code = _Outcome(ToolStatus.MALFORMED, message=str(exc)), "malformed_source"
        return self._result(name, outcome, params, scope, collected_at, as_of, code)

    # ---- tools ----

    def _metrics(self, inp: ReadMetricsInput) -> _Outcome:
        as_of = self._adapter.as_of
        start = as_of - timedelta(minutes=inp.time_window_minutes)
        samples = self._adapter.metrics_for(inp.host_id)
        if inp.metrics is not None:
            samples = [s for s in samples if s.metric in inp.metrics]
        in_window = [s for s in samples if start <= s.observed_at <= as_of]
        if not in_window:
            history = [s for s in samples if s.observed_at <= as_of]
            if history:
                newest = max(s.observed_at for s in history)
                return _Outcome(ToolStatus.STALE, newest_observed=newest, threshold=self._freshness,
                                message=f"no samples in the last {inp.time_window_minutes} min; newest "
                                        f"observation is {_age(as_of - newest)} old (stale, not zero)")
            return _Outcome(ToolStatus.NO_DATA, message=f"no metric samples found for host '{inp.host_id}'")

        in_window.sort(key=lambda s: s.observed_at)
        truncated = len(in_window) > MAX_SAMPLES_PER_CALL
        if truncated:
            in_window = in_window[-MAX_SAMPLES_PER_CALL:]  # keep the newest

        groups: dict[tuple[str, str], list] = {}
        for s in in_window:
            groups.setdefault((s.metric, s.source), []).append(s)
        records: list[EvidenceRecord] = []
        newest_reading: datetime | None = None
        now = self._clock()
        for (metric, source), series in sorted(groups.items()):
            real = [s for s in series if s.value is not None]
            latest = real[-1] if real else None
            if latest and (newest_reading is None or latest.observed_at > newest_reading):
                newest_reading = latest.observed_at
            payload = {
                "metric": metric,
                "unit": series[0].unit.value,
                "source": source,
                "window_start": _iso(start),
                "window_end": _iso(as_of),
                "sample_count": len(series),
                "null_count": len(series) - len(real),  # nulls are kept as nulls, never zeros
                "latest_value": latest.value if latest else None,
                "latest_observed_at": _iso(latest.observed_at) if latest else None,
                "latest_age_seconds": (as_of - latest.observed_at).total_seconds() if latest else None,
                "min": min(s.value for s in real) if real else None,
                "max": max(s.value for s in real) if real else None,
                "samples": [{"observed_at": _iso(s.observed_at), "value": s.value} for s in series],
            }
            key = (inp.host_id, metric, source, _iso(start), _iso(as_of))
            records.append(self._evidence("metric", "read_metrics", inp.host_id, key,
                                          series[-1].observed_at, now, payload))
        base = dict(records=records, truncated=truncated, threshold=self._freshness,
                    observed_from=in_window[0].observed_at, observed_to=in_window[-1].observed_at)
        if newest_reading is None:
            return _Outcome(ToolStatus.NO_DATA, newest_observed=None,
                            message="the source reported only null readings (unknown, not zero)", **base)
        if as_of - newest_reading > self._freshness:
            return _Outcome(ToolStatus.STALE, newest_observed=newest_reading,
                            message=f"newest reading is {_age(as_of - newest_reading)} old", **base)
        return _Outcome(ToolStatus.OK, newest_observed=newest_reading, **base)

    def _logs(self, inp: ReadLogsInput) -> _Outcome:
        rng = inp.time_range
        logs = [r for r in self._adapter.logs_for(inp.host_id) if rng.start <= r.observed_at <= rng.end]
        if not logs:
            return _Outcome(ToolStatus.NO_DATA, message="no log records in the requested range")
        logs.sort(key=lambda r: r.observed_at, reverse=True)
        truncated = len(logs) > inp.limit
        logs = logs[: inp.limit]
        now = self._clock()
        records = []
        for r in logs:
            payload = {
                "level": r.level.value,
                "source": r.source,
                "message": r.message[:MAX_LOG_MESSAGE_CHARS],
                # Log text is data written by arbitrary systems. It must never be obeyed.
                "content_trust": "untrusted_data",
            }
            key = (inp.host_id, r.source, _iso(r.observed_at), r.level.value, r.message)
            records.append(self._evidence("log", "read_logs", inp.host_id, key, r.observed_at, now, payload))
        return _Outcome(ToolStatus.OK, records=records, truncated=truncated,
                        observed_from=min(r.observed_at for r in logs),
                        observed_to=max(r.observed_at for r in logs),
                        newest_observed=max(r.observed_at for r in logs))

    def _config(self, inp: ReadConfigInput) -> _Outcome:
        as_of = self._adapter.as_of
        configs = self._adapter.configs_for(inp.host_id)
        if not configs:
            return _Outcome(ToolStatus.NO_DATA, message=f"no configuration found for host '{inp.host_id}'")
        configs.sort(key=lambda c: c.observed_at)
        now = self._clock()
        records = []
        for c in configs:
            payload = {"source": c.source, "settings": dict(c.settings)}
            key = (inp.host_id, c.source, _iso(c.observed_at))
            records.append(self._evidence("config", "read_config", inp.host_id, key, c.observed_at, now, payload))
        newest = configs[-1].observed_at
        status = ToolStatus.OK if as_of - newest <= self._config_max_age else ToolStatus.STALE
        return _Outcome(status, records=records, newest_observed=newest, threshold=self._config_max_age,
                        observed_from=configs[0].observed_at, observed_to=newest,
                        message=None if status == ToolStatus.OK else f"configuration is {_age(as_of - newest)} old")

    # ---- helpers ----

    def _evidence(self, source_type: str, tool: str, host_id: str, key: tuple, observed_at: datetime,
                  ingested_at: datetime, payload: dict) -> EvidenceRecord:
        # Deterministic: the same underlying data in the same run always gets the same ID.
        digest = hashlib.sha256("|".join((self._run_id, tool, *map(str, key))).encode()).hexdigest()[:12]
        return EvidenceRecord(id=f"ev_{digest}", run_id=self._run_id, source_type=source_type,
                              host_id=host_id, tool_name=tool, observed_at=observed_at,
                              ingested_at=ingested_at, payload=payload, synthetic=True)

    def _result(self, name: str, o: _Outcome, params: dict, scope: list[str], collected_at: datetime,
                as_of: datetime, error_code: str | None) -> ToolResult:
        if o.records and self._repo is not None:
            self._repo.add_many(o.records)  # idempotent: INSERT OR IGNORE on the stable ID
        failed = o.status in (ToolStatus.TIMEOUT, ToolStatus.ERROR, ToolStatus.REJECTED, ToolStatus.MALFORMED)
        freshness = None
        if o.status in (ToolStatus.OK, ToolStatus.STALE, ToolStatus.NO_DATA) and o.newest_observed is not None:
            freshness = Freshness(as_of=as_of, newest_observed_at=o.newest_observed,
                                  age_seconds=(as_of - o.newest_observed).total_seconds(),
                                  threshold_seconds=o.threshold.total_seconds())
        records = [] if failed else o.records
        return ToolResult(
            tool_name=name, status=o.status, parameters=params, host_scope=scope,
            collected_at=collected_at, as_of=as_of,
            evidence_ids=[r.id for r in records], records=records,
            provenance=sorted({r.payload.get("source", "") for r in records} - {""}),
            observed_from=o.observed_from, observed_to=o.observed_to, freshness=freshness,
            truncated=o.truncated,
            error_code=error_code or {ToolStatus.NO_DATA: "no_data", ToolStatus.STALE: "stale_data"}.get(o.status),
            message=o.message,
        )


def _age(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes // 60}h{minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"
