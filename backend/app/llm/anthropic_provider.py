"""The only module that imports the Anthropic SDK. Credentials come from backend settings/env."""
import time
from typing import Any

from app.core.config import Settings
from app.llm.provider import (
    PermanentProviderError,
    ProviderRefusal,
    ProviderRequest,
    ProviderResponse,
    TransientProviderError,
)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings, client: Any | None = None):
        self._model = settings.llm_model
        self._effort = settings.llm_effort
        self._timeout = settings.llm_timeout_seconds
        self._fallbacks = settings.llm_enable_fallbacks
        if client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - depends on the environment
                raise PermanentProviderError(
                    "the 'anthropic' package is not installed; run: pip install -e \".[llm]\""
                ) from exc
            key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
            # max_retries=0: retries are done by the investigator, so they stay bounded and logged.
            client = anthropic.Anthropic(api_key=key, max_retries=0, timeout=self._timeout)
        self._client = client

    def generate_investigation(self, request: ProviderRequest) -> ProviderResponse:
        import anthropic

        kwargs: dict[str, Any] = dict(
            model=self._model,
            max_tokens=request.max_tokens,
            system=request.system,
            messages=[{"role": "user", "content": request.user}],
            output_config={
                "effort": self._effort,
                "format": {"type": "json_schema", "schema": request.json_schema},
            },
            # Never wait longer than the run has left, even if the configured timeout is longer.
            timeout=min(request.timeout_seconds, self._timeout) if request.timeout_seconds else self._timeout,
        )
        started = time.monotonic()
        try:
            if self._fallbacks:
                # Server-side refusal fallback: the API re-runs a declined request on another model.
                response = self._client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
                )
            else:
                response = self._client.messages.create(**kwargs)
        except TypeError as exc:
            if "authentication" in str(exc).lower():  # the SDK found no credentials at all
                raise PermanentProviderError(
                    "no API credentials are configured: set FABRICOPS_LLM_API_KEY (or ANTHROPIC_API_KEY) "
                    "in backend/.env"
                ) from exc
            raise
        except (anthropic.RateLimitError, anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
            raise TransientProviderError(f"{type(exc).__name__}: {exc}") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500 or exc.status_code in (408, 409, 529):
                raise TransientProviderError(f"HTTP {exc.status_code}: {exc.message}") from exc
            raise PermanentProviderError(f"HTTP {exc.status_code}: {exc.message}") from exc
        latency_ms = (time.monotonic() - started) * 1000

        if response.stop_reason == "refusal":
            category = getattr(getattr(response, "stop_details", None), "category", None)
            raise ProviderRefusal(f"the model declined the request (category: {category})")
        if response.stop_reason == "max_tokens":
            raise PermanentProviderError("the model output was cut off at max_tokens")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise PermanentProviderError("the model returned no text block")
        usage = {}
        if getattr(response, "usage", None):
            for name in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
                value = getattr(response.usage, name, None)
                if isinstance(value, int):
                    usage[name] = value
        return ProviderResponse(text=text, model_id=response.model, latency_ms=latency_ms, usage=usage,
                                request_id=getattr(response, "_request_id", None))
