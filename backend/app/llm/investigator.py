"""The investigator: package -> (optional) model call -> validated report or honest abstention.

No tool loops and no remediation: the model gets one evidence package and returns one answer.
"""
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.llm.package import EvidencePackage
from app.llm.prompt import PROMPT_VERSION, build_prompt
from app.llm.provider import (
    LLMProvider,
    PermanentProviderError,
    ProviderRefusal,
    ProviderRequest,
    TransientProviderError,
)
from app.llm.schema import ModelInvestigation, response_json_schema
from app.llm.validator import InvestigationRejected, validate_investigation
from app.schemas.common import RunStatus, Severity
from app.schemas.domain import InvestigationReport

BACKOFF_SECONDS = (0.5, 1.0, 2.0)
log = logging.getLogger("fabricops.investigator")


@dataclass
class InvestigationMetadata:
    provider: str
    model_id: str | None
    prompt_version: str
    llm_called: bool
    attempts: int = 0
    latency_ms: float | None = None
    usage: dict[str, int] = field(default_factory=dict)
    request_id: str | None = None


@dataclass
class InvestigationOutcome:
    status: RunStatus                          # COMPLETE, ABSTAINED or FAILED
    report: InvestigationReport | None
    metadata: InvestigationMetadata
    error_code: str | None = None
    errors: list[str] = field(default_factory=list)


class Investigator:
    def __init__(
        self,
        provider: LLMProvider | None = None,
        max_tokens: int = 8000,
        max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        max_output_chars: int = 60_000,
        provider_factory: Callable[[], LLMProvider] | None = None,
    ):
        """Give either a ready `provider` or a `provider_factory`. A factory is only called when the
        model is actually needed, so a run that abstains on stale data never builds a client."""
        if (provider is None) == (provider_factory is None):
            raise ValueError("pass exactly one of provider or provider_factory")
        self._max_output_chars = max_output_chars
        self._provider = provider
        self._provider_factory = provider_factory
        self._max_tokens = max_tokens
        self._max_attempts = max(1, max_attempts)
        self._sleep = sleep

    def investigate(self, pkg: EvidencePackage) -> InvestigationOutcome:
        meta = InvestigationMetadata(provider=self._provider.name if self._provider else "none",
                                     model_id=None, prompt_version=PROMPT_VERSION, llm_called=False)

        # 1. Server-side abstention gate: stale/missing evidence never reaches the model.
        if pkg.abstention_reasons:
            return InvestigationOutcome(RunStatus.ABSTAINED, self._server_abstention(pkg), meta)

        try:
            system, user = build_prompt(pkg)
        except ValueError as exc:
            return self._failed(meta, "package_too_large", [str(exc)])
        request = ProviderRequest(system=system, user=user, json_schema=response_json_schema(),
                                  max_tokens=self._max_tokens)

        if self._provider is None:  # build the client now, only because the model is needed
            try:
                self._provider = self._provider_factory()
            except PermanentProviderError as exc:
                return self._failed(meta, "provider_not_configured", [str(exc)[:300]])
            except Exception as exc:  # noqa: BLE001
                log.exception("could not create the LLM provider")
                return self._failed(meta, "provider_not_configured",
                                    [f"the model provider could not be created ({type(exc).__name__})"])
        meta.provider = self._provider.name

        # 2. Call the model; retry only bounded transient failures.
        response = None
        for attempt in range(1, self._max_attempts + 1):
            meta.attempts, meta.llm_called = attempt, True
            try:
                response = self._provider.generate_investigation(request)
                break
            except TransientProviderError as exc:
                if attempt == self._max_attempts:
                    return self._failed(meta, "provider_unavailable",
                                        [f"gave up after {attempt} attempts: {exc}"])
                self._sleep(BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)])
            except ProviderRefusal as exc:
                return self._failed(meta, "model_refused", [str(exc)])
            except PermanentProviderError as exc:
                return self._failed(meta, "provider_error", [str(exc)[:300]])
            except Exception as exc:  # noqa: BLE001 - never let a provider surprise become a crash
                log.exception("unexpected provider error")
                return self._failed(meta, "provider_error", [f"unexpected provider error ({type(exc).__name__})"])
        assert response is not None
        meta.model_id, meta.latency_ms = response.model_id, response.latency_ms
        meta.usage, meta.request_id = response.usage, response.request_id

        if len(response.text) > self._max_output_chars:
            return self._failed(meta, "output_too_large",
                                [f"model output is {len(response.text)} characters; limit {self._max_output_chars}"])

        # 3. Parse against the strict schema. Malformed output is a failure, not retried.
        try:
            raw = ModelInvestigation.model_validate_json(response.text)
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            return self._failed(meta, "invalid_model_output", [f"does not match the schema: {str(exc)[:500]}"])

        # 4. Validate every ID, the scope and the proposal against this run.
        try:
            report = validate_investigation(raw, pkg)
        except InvestigationRejected as exc:
            return self._failed(meta, "model_output_rejected", exc.errors)

        status = RunStatus.ABSTAINED if report.insufficient_evidence else RunStatus.COMPLETE
        return InvestigationOutcome(status, report, meta)

    @staticmethod
    def _failed(meta: InvestigationMetadata, code: str, errors: list[str]) -> InvestigationOutcome:
        return InvestigationOutcome(RunStatus.FAILED, None, meta, error_code=code, errors=errors)

    @staticmethod
    def _server_abstention(pkg: EvidencePackage) -> InvestigationReport:
        return InvestigationReport(
            run_id=pkg.run_id, severity=Severity.UNKNOWN, insufficient_evidence=True,
            observations=[], hypotheses=[], citations=[],
            missing_evidence=[r[0].upper() + r[1:] for r in pkg.abstention_reasons],
            proposed_next_test=None,
            limitations=[
                "Abstained before any model call: the evidence is stale, missing or insufficient.",
                "No hardware or software cause is asserted. Restore telemetry visibility first, then re-run.",
                "All data is synthetic.",
            ],
        )
