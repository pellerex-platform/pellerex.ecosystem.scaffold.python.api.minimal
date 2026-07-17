"""Application configuration and secrets (P3 / P4 / PY-D6 / PY-D21).

Two deliberately separate sources of truth:

* :class:`Settings` — **non-secret** configuration. Read, in precedence order, from
  constructor args > process environment variables > the tokenised, env-specific
  ``config.{ENVIRONMENT}.json`` file. Instantiating it validates every value, so a
  missing/invalid value fails fast **at boot**, not at request time (PY-D21).

* :class:`Secrets` — **secret material** (e.g. the database connection string). Read
  **only** from the CSI driver's in-memory tmpfs file mount (one file per secret), via
  ``pydantic-settings`` ``secrets_dir`` (PY-D6). The environment-variable source is
  intentionally excluded, so a secret can never be injected through an env var or leak
  via ``/proc``/child processes/crash dumps (PY-R13).

No secret value ever sits in the repo, the image, a config file, etcd, or the process
environment — only the Key Vault *name* is tokenised into the SecretProviderClass.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

# The CSI driver mounts the Key Vault secrets as files on an in-memory tmpfs volume here
# (matches the Helm ``volumeMounts.mountPath``). Each secret is one file named after the
# Key Vault object, e.g. ``/mnt/secrets-store/DbConnectionString`` (PY-D6).
DEFAULT_SECRETS_MOUNT_PATH = os.environ.get("SECRETS_MOUNT_PATH", "/mnt/secrets-store")

Environment = Literal["development", "qualityassurance", "staging", "production"]


def _config_file_for(environment: str) -> str:
    return f"config.{environment}.json"


class Settings(BaseSettings):
    """Non-secret configuration (env vars + ``config.{env}.json``)."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        env_file=None,
    )

    # An explicit ENVIRONMENT is required (PY-D21) — the analog of ASPNETCORE_ENVIRONMENT.
    # No default: booting without it (and without a config value) raises ValidationError
    # at startup — fail fast (PY-R11 / test J6). The container, Helm values and run scripts
    # all set ENVIRONMENT, so normal boots always have it.
    environment: Environment

    debug: bool = False
    log_level: str = "info"

    # Daily-rolling file sinks (Serilog File-sink parity — see app/logging_config.py).
    # Env vars (LOG_FILE_ENABLED, LOG_FILE_DIRECTORY, LOG_RETENTION_DAYS) override the
    # config.{env}.json values via the standard pydantic-settings precedence.
    log_file_enabled: bool = True
    log_file_directory: str = "logs"
    log_retention_days: int = 31

    # App Insights connection string — **configuration**, delivered via the tokenised
    # config file (the same way .NET/Node receive it); not secret material (P5 / PY-D7).
    azure_app_insights_connection_string: Optional[str] = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # The active environment selects which config.{env}.json is layered in.
        environment = os.environ.get("ENVIRONMENT", "development")
        json_source = JsonConfigSettingsSource(
            settings_cls, json_file=_config_file_for(environment)
        )
        # Precedence (highest first): init args > env vars > config.{env}.json.
        # No tmpfs secrets source here — secrets live in `Secrets`.
        return (init_settings, env_settings, json_source)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


class Secrets(BaseSettings):
    """Secret material — read ONLY from the CSI tmpfs file mount, never from env (PY-D6 / PY-R13)."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        # If the mount is absent (local dev, or secretProviderClass disabled) fall back to
        # no secrets source rather than erroring at import.
        secrets_dir=DEFAULT_SECRETS_MOUNT_PATH if os.path.isdir(DEFAULT_SECRETS_MOUNT_PATH) else None,
    )

    # Mapped to the Key Vault object file ``DbConnectionString`` on the tmpfs mount.
    db_connection_string: Optional[str] = Field(default=None, alias="DbConnectionString")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Deliberately EXCLUDE env vars + config files: secret material comes only from the
        # tmpfs file mount (PY-R13). `init_settings` is kept so tests can inject values.
        return (init_settings, file_secret_settings)

    @property
    def has_database_secret(self) -> bool:
        return bool(self.db_connection_string)


@lru_cache
def get_settings() -> Settings:
    """Boot-time singleton. Instantiation validates config → fail fast (PY-D21)."""
    return Settings()


@lru_cache
def get_secrets() -> Secrets:
    """Boot-time singleton reading the tmpfs CSI mount (PY-D6)."""
    return Secrets()
