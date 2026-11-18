"""Application settings, loaded from environment variables and an optional .env file."""
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FABRICOPS_", env_file=".env", extra="ignore")

    app_name: str = "FabricOps"
    max_request_bytes: int = 65536             # request bodies larger than this get HTTP 413
    environment: str = "local"
    log_level: str = "INFO"
    # SQLite file. Defaults to backend/data/fabricops.db (git-ignored).
    database_path: str = str(Path(__file__).resolve().parents[2] / "data" / "fabricops.db")
    # --- LLM provider (backend only; never exposed to the browser) ---
    llm_provider: str = "anthropic"            # "anthropic" or "mock"
    llm_model: str = "claude-opus-5-5"
    # If unset, the Anthropic SDK falls back to ANTHROPIC_API_KEY / an `ant auth login` profile.
    llm_api_key: SecretStr | None = None
    llm_max_tokens: int = 8000
    llm_effort: str = "high"                    # low | medium | high | xhigh | max
    llm_timeout_seconds: float = 120.0
    llm_max_attempts: int = 3                   # bounded retries for transient failures only
    llm_enable_fallbacks: bool = True           # server-side refusal fallbacks (Anthropic beta)
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
