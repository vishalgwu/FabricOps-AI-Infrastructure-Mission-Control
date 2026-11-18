"""The provider interface. All vendor-specific SDK code lives behind it (see anthropic_provider)."""
from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderError(Exception):
    """Base class for provider failures."""


class TransientProviderError(ProviderError):
    """Worth retrying a bounded number of times: rate limit, timeout, network, 5xx."""


class PermanentProviderError(ProviderError):
    """Not worth retrying: bad request, auth failure, truncated output."""


class ProviderRefusal(ProviderError):
    """The model declined the request on safety grounds."""


@dataclass(frozen=True)
class ProviderRequest:
    system: str
    user: str
    json_schema: dict[str, Any]
    max_tokens: int
    timeout_seconds: float | None = None  # what is left of the run's time limit; the provider must not exceed it


@dataclass
class ProviderResponse:
    text: str                        # the raw model output (expected to be JSON)
    model_id: str
    latency_ms: float
    usage: dict[str, int] = field(default_factory=dict)  # e.g. input_tokens, output_tokens
    request_id: str | None = None


class LLMProvider(Protocol):
    name: str

    def generate_investigation(self, request: ProviderRequest) -> ProviderResponse: ...
