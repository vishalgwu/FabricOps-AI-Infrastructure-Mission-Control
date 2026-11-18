"""Fixture adapter: the ONLY data source the MVP tools read. It has no write methods.

No real infrastructure, network, shell or arbitrary file access happens here.
"""
import json
from collections.abc import Callable
from datetime import datetime

from pydantic import ValidationError

from app.schemas.domain import HostConfiguration, LogRecord, MetricSample
from app.schemas.fixtures import ScenarioFixture


class SourceTimeout(Exception):
    """The data source did not answer in time."""


class SourceError(Exception):
    """The data source failed."""


class MalformedSourceError(Exception):
    """The data source returned data that does not match the schema."""


class FixtureAdapter:
    def __init__(self, load: Callable[[], ScenarioFixture]):
        # `load` is called on every query so malformed data surfaces at read time.
        self._load = load

    @classmethod
    def from_fixture(cls, fixture: ScenarioFixture) -> "FixtureAdapter":
        return cls(lambda: fixture)

    def _fixture(self) -> ScenarioFixture:
        try:
            return self._load()
        except (ValidationError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise MalformedSourceError(f"fixture failed validation: {str(exc)[:300]}") from exc

    @property
    def as_of(self) -> datetime:
        return self._fixture().reference_time

    def known_hosts(self) -> set[str]:
        return {h.id for h in self._fixture().hosts}

    def metrics_for(self, host_id: str) -> list[MetricSample]:
        return [m for m in self._fixture().metrics if m.host_id == host_id]

    def logs_for(self, host_id: str) -> list[LogRecord]:
        return [r for r in self._fixture().logs if r.host_id == host_id]

    def configs_for(self, host_id: str) -> list[HostConfiguration]:
        return [c for c in self._fixture().configs if c.host_id == host_id]


class FaultInjectingAdapter(FixtureAdapter):
    """Test helper: raises a chosen exception from a chosen read ('metrics', 'logs', 'configs')."""

    def __init__(self, load: Callable[[], ScenarioFixture], faults: dict[str, Exception]):
        super().__init__(load)
        self._faults = faults

    def _maybe_fail(self, kind: str) -> None:
        if kind in self._faults:
            raise self._faults[kind]

    def metrics_for(self, host_id: str) -> list[MetricSample]:
        self._maybe_fail("metrics")
        return super().metrics_for(host_id)

    def logs_for(self, host_id: str) -> list[LogRecord]:
        self._maybe_fail("logs")
        return super().logs_for(host_id)

    def configs_for(self, host_id: str) -> list[HostConfiguration]:
        self._maybe_fail("configs")
        return super().configs_for(host_id)
