"""The only module that imports the OpenAI SDK. Credentials come from backend settings/env.

Uses Chat Completions with a strict JSON-schema response format. Whether a particular account and
model accept this request is only known by running the optional live check and smoke test (see the
README): it has been tested against a fake client, not against the live service.
"""
import re
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

_REASONING_MODEL = re.compile(r"^(o\d|gpt-5)")
_EFFORT_MAP = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}
SCHEMA_NAME = "fabricops_investigation"
MISSING_KEY = ("no API credentials are configured: set OPENAI_API_KEY (or FABRICOPS_LLM_API_KEY) in backend/.env")


class OpenAIProvider:
    name = "openai"

    def __init__(self, settings: Settings, client: Any | None = None):
        self._model = settings.resolved_model("openai")
        self._effort = _EFFORT_MAP.get(settings.llm_effort)
        self._timeout = settings.llm_timeout_seconds
        if client is None:
            try:
                import openai
            except ImportError as exc:  # pragma: no cover - depends on the environment
                raise PermanentProviderError('the "openai" package is not installed; run: pip install -e ".[openai]"') from exc
            try:
                # max_retries=0: retries are done by the investigator, so they stay bounded and logged.
                client = openai.OpenAI(api_key=settings.api_key_for("openai"), max_retries=0, timeout=self._timeout)
            except openai.OpenAIError as exc:
                raise PermanentProviderError(MISSING_KEY) from exc
        self._client = client

    def generate_investigation(self, request: ProviderRequest) -> ProviderResponse:
        import openai

        kwargs: dict[str, Any] = dict(
            model=self._model,
            messages=[{"role": "system", "content": request.system}, {"role": "user", "content": request.user}],
            # Reasoning models count their hidden thinking against this limit as well.
            max_completion_tokens=request.max_tokens,
            response_format={"type": "json_schema",
                             "json_schema": {"name": SCHEMA_NAME, "strict": True, "schema": request.json_schema}},
            # Never wait longer than the run has left, even if the configured timeout is longer.
            timeout=min(request.timeout_seconds, self._timeout) if request.timeout_seconds else self._timeout,
        )
        if self._effort and _REASONING_MODEL.match(self._model):
            kwargs["reasoning_effort"] = self._effort  # other models reject this parameter
        started = time.monotonic()
        try:
            response = self._client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as exc:
            raise PermanentProviderError("OpenAI rejected the API key (authentication failed); check OPENAI_API_KEY") from exc
        except openai.RateLimitError as exc:
            if getattr(exc, "code", None) == "insufficient_quota":  # out of credit is not a transient condition
                raise PermanentProviderError("the OpenAI account has no remaining quota; check billing") from exc
            raise TransientProviderError(f"RateLimitError: {exc}") from exc
        except (openai.APITimeoutError, openai.APIConnectionError) as exc:
            raise TransientProviderError(f"{type(exc).__name__}: {exc}") from exc
        except openai.APIStatusError as exc:
            if exc.status_code >= 500 or exc.status_code in (408, 409):
                raise TransientProviderError(f"HTTP {exc.status_code}: {exc.message}") from exc
            raise PermanentProviderError(f"HTTP {exc.status_code}: {exc.message}") from exc
        except TypeError as exc:
            if "api_key" in str(exc).lower() or "credentials" in str(exc).lower():
                raise PermanentProviderError(MISSING_KEY) from exc
            raise
        latency_ms = (time.monotonic() - started) * 1000

        choice = response.choices[0]
        message = choice.message
        if getattr(message, "refusal", None):
            raise ProviderRefusal(f"the model declined the request: {str(message.refusal)[:200]}")
        if choice.finish_reason == "content_filter":
            raise ProviderRefusal("the response was blocked by the provider's content filter")
        if choice.finish_reason == "length":
            raise PermanentProviderError("the model output was cut off at max_completion_tokens "
                                         "(for reasoning models, raise FABRICOPS_LLM_MAX_TOKENS)")
        text = message.content
        if not text:
            raise PermanentProviderError("the model returned no content")
        usage: dict[str, int] = {}
        if getattr(response, "usage", None):
            for ours, theirs in (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens")):
                value = getattr(response.usage, theirs, None)
                if isinstance(value, int):
                    usage[ours] = value
        return ProviderResponse(text=text, model_id=response.model, latency_ms=latency_ms, usage=usage,
                                request_id=getattr(response, "_request_id", None))
