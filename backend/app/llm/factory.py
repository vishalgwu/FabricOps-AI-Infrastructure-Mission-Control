from app.core.config import Settings
from app.llm.mock import MockProvider
from app.llm.provider import LLMProvider, PermanentProviderError


def create_provider(settings: Settings) -> LLMProvider:
    """Pick the provider named in backend settings. The API key never leaves the backend."""
    if settings.llm_provider == "anthropic":
        from app.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings)
    if settings.llm_provider == "mock":
        return MockProvider({"observations": [], "hypotheses": [], "missing_evidence": ["mock provider"],
                             "next_test": None, "abstain": True, "abstain_reason": "mock provider",
                             "limitations": [], "document_citations": []})
    raise PermanentProviderError(f"unknown llm_provider '{settings.llm_provider}' (use 'anthropic' or 'mock')")
