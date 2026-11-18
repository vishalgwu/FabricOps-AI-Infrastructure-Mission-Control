"""A scripted provider for tests and local runs without an API key."""
import json
from collections.abc import Callable
from typing import Any

from app.llm.provider import ProviderRequest, ProviderResponse

Script = str | dict | Exception | Callable[[ProviderRequest], Any]


class MockProvider:
    name = "mock"

    def __init__(self, *script: Script, model_id: str = "mock-model-1"):
        """Each call consumes the next item: JSON text, a dict (serialised), an exception to raise,
        or a function of the request. The last item repeats if the script runs out."""
        self._script = list(script)
        self._model_id = model_id
        self.requests: list[ProviderRequest] = []

    @property
    def calls(self) -> int:
        return len(self.requests)

    def generate_investigation(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        if not self._script:
            raise AssertionError("MockProvider has no scripted response")
        item = self._script[min(len(self.requests), len(self._script)) - 1]
        if callable(item) and not isinstance(item, (str, dict, Exception)):
            item = item(request)
        if isinstance(item, Exception):
            raise item
        text = item if isinstance(item, str) else json.dumps(item)
        return ProviderResponse(text=text, model_id=self._model_id, latency_ms=1.0,
                                usage={"input_tokens": 100, "output_tokens": 50}, request_id="mock-req-1")
