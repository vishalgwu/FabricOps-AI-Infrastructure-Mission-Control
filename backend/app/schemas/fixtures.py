"""The runtime fixture file format. Expected outcomes are NOT part of it (see data/evals/)."""
from typing import Literal

from pydantic import model_validator

from app.schemas.common import StrictModel, UtcDatetime
from app.schemas.domain import Host, HostConfiguration, Incident, LogRecord, MetricSample


class ScenarioFixture(StrictModel):
    synthetic: Literal[True]  # a fixture that is not labelled synthetic is rejected
    data_notice: str
    scenario_id: str
    # The "as of" time for freshness checks, so tests do not depend on the wall clock.
    reference_time: UtcDatetime
    incident: Incident
    hosts: list[Host]
    metrics: list[MetricSample] = []
    logs: list[LogRecord] = []
    configs: list[HostConfiguration] = []

    @model_validator(mode="after")
    def _cross_checks(self) -> "ScenarioFixture":
        known = {h.id for h in self.hosts}
        if len(known) != len(self.hosts):
            raise ValueError("duplicate host ids")
        if not self.incident.synthetic:
            raise ValueError("incident must be marked synthetic: true")
        refs: list[tuple[str, str]] = [("incident.affected_hosts", h) for h in self.incident.affected_hosts]
        refs += [("metrics", m.host_id) for m in self.metrics]
        refs += [("logs", r.host_id) for r in self.logs]
        refs += [("configs", c.host_id) for c in self.configs]
        unknown = sorted({f"{where}: '{hid}'" for where, hid in refs if hid not in known})
        if unknown:
            raise ValueError(f"unknown host reference(s): {unknown}; known hosts: {sorted(known)}")
        return self
