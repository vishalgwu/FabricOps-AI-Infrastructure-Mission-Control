"""Application settings, loaded from environment variables and an optional .env file."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FABRICOPS_", env_file=".env", extra="ignore")

    app_name: str = "FabricOps"
    environment: str = "local"
    log_level: str = "INFO"
    # Comma-separated list of allowed browser origins for the local frontend.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
