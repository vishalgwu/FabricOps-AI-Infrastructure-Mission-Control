"""Application settings, loaded from environment variables and an optional .env file."""
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MODELS = {"anthropic": "claude-opus-5-5", "openai": "gpt-4.1"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FABRICOPS_", env_file=".env", extra="ignore", populate_by_name=True)

    app_name: str = "FabricOps"
    max_request_bytes: int = 65536             # request bodies larger than this get HTTP 413
    environment: str = "local"
    log_level: str = "INFO"
    # SQLite file. Defaults to backend/data/fabricops.db (git-ignored).
    database_path: str = str(Path(__file__).resolve().parents[2] / "data" / "fabricops.db")
    # --- LLM provider (backend only; never exposed to the browser) ---
    # "anthropic", "openai", "demo" (a SCRIPTED model, not an AI) or "mock"
    llm_provider: str = "anthropic"
    # Empty means "the provider's default" (see DEFAULT_MODELS). Set it to use a different model.
    llm_model: str | None = None
    # One key for whichever provider is selected. If unset, the provider's own key below is used.
    llm_api_key: SecretStr | None = None
    # The providers' standard variable names, so a backend/.env containing OPENAI_API_KEY=... just works.
    openai_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("OPENAI_API_KEY", "FABRICOPS_OPENAI_API_KEY"))
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "FABRICOPS_ANTHROPIC_API_KEY"))
    llm_max_tokens: int = 8000
    llm_effort: str = "high"                    # low | medium | high | xhigh | max (OpenAI: sent only to reasoning models)
    llm_timeout_seconds: float = 120.0
    llm_max_attempts: int = 3                   # bounded retries for transient failures only
    llm_enable_fallbacks: bool = True           # server-side refusal fallbacks (Anthropic beta only)
    # --- approvals (DEMO identity only: this is not production authentication) ---
    demo_reviewers: str = "demo-reviewer"      # comma-separated names allowed to approve/reject
    approval_ttl_minutes: int = 1440           # how long a pending proposal stays decidable
    # Comma-separated list of allowed browser origins for the local frontend.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def reviewer_set(self) -> frozenset[str]:
        return frozenset(r.strip() for r in self.demo_reviewers.split(",") if r.strip())

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def resolved_model(self, provider: str) -> str:
        """The model to use: the configured one, or the provider's default."""
        return self.llm_model or DEFAULT_MODELS[provider]

    def api_key_for(self, provider: str) -> str | None:
        """The key for this provider from settings (None means: let the SDK look in its own environment)."""
        own = {"openai": self.openai_api_key, "anthropic": self.anthropic_api_key}.get(provider)
        chosen = self.llm_api_key or own
        return chosen.get_secret_value() if chosen else None

    def all_secret_values(self) -> list[str]:
        return [k.get_secret_value() for k in (self.llm_api_key, self.openai_api_key, self.anthropic_api_key) if k]


@lru_cache
def get_settings() -> Settings:
    return Settings()
