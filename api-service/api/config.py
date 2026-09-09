"""Runtime configuration. One place that knows local from deployed.

The same image runs on a laptop and in Azure; only env vars differ.
Anything unsafe outside local is refused at startup, not at request time —
a misconfigured deployment should fail to boot, not quietly serve open data.
"""
import os
from dataclasses import dataclass, field
from functools import lru_cache


class ConfigError(RuntimeError):
    """Raised at startup when the environment is unsafe or incomplete."""


def _csv(name: str) -> list[str]:
    return [v.strip() for v in os.getenv(name, "").split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    environment: str            # local | dev | test | prod
    table_name: str
    connection_string: str      # local only
    account_name: str           # set instead, for managed identity
    api_key: str
    cors_origins: list[str] = field(default_factory=list)
    cache_ttl: int = 60
    dedup_strategy: str = "latest"

    @property
    def is_local(self) -> bool:
        return self.environment == "local"

    @property
    def uses_managed_identity(self) -> bool:
        return not self.connection_string and bool(self.account_name)

    @property
    def table_endpoint(self) -> str:
        return f"https://{self.account_name}.table.core.windows.net/"

    def validate(self) -> None:
        if self.environment not in {"local", "dev", "test", "prod"}:
            raise ConfigError(
                f"ENVIRONMENT must be local|dev|test|prod, got {self.environment!r}")
        if not self.connection_string and not self.account_name:
            raise ConfigError(
                "Set AZURE_STORAGE_CONNECTION_STRING (local) or "
                "AZURE_STORAGE_ACCOUNT (managed identity in Azure)")
        if self.dedup_strategy not in {"latest", "first", "sum"}:
            raise ConfigError(
                f"DEDUP_STRATEGY must be latest|first|sum, got {self.dedup_strategy!r}")

        if self.is_local:
            return

        # --- everything below is refused outside local ---
        if not self.api_key:
            raise ConfigError(
                f"API_KEY is required when ENVIRONMENT={self.environment}. "
                "An unauthenticated reconciliation API must never be deployed.")
        if len(self.api_key) < 24:
            raise ConfigError("API_KEY must be at least 24 characters.")
        if not self.cors_origins:
            raise ConfigError(
                f"CORS_ORIGINS is required when ENVIRONMENT={self.environment}. "
                "Set the exact origins that may call this API.")
        if "*" in self.cors_origins:
            raise ConfigError("CORS_ORIGINS cannot be '*' outside local.")
        if self.connection_string:
            # works, but a rotatable key beats a long-lived one in app settings
            import warnings
            warnings.warn(
                "Using a connection string in a deployed environment. Prefer "
                "AZURE_STORAGE_ACCOUNT with a managed identity.", stacklevel=2)


@lru_cache
def settings() -> Settings:
    s = Settings(
        environment=os.getenv("ENVIRONMENT", "local").strip().lower(),
        table_name=os.getenv("AZURE_TABLE", "summarylogs").strip(),
        connection_string=os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip(),
        account_name=os.getenv("AZURE_STORAGE_ACCOUNT", "").strip(),
        api_key=os.getenv("API_KEY", "").strip(),
        cors_origins=_csv("CORS_ORIGINS"),
        cache_ttl=int(os.getenv("CACHE_TTL_SECONDS", "60")),
        dedup_strategy=os.getenv("DEDUP_STRATEGY", "latest").strip(),
    )
    s.validate()
    return s
