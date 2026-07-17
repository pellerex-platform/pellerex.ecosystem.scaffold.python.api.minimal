"""Config validation tests (P3 / PY-D21 — validate at boot / fail fast)."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_load_and_validate():
    s = Settings()  # ENVIRONMENT=development (set in conftest)
    assert s.environment == "development"
    assert s.debug is True  # from config.development.json


def test_invalid_environment_fails_fast():
    with pytest.raises(ValidationError):
        Settings(environment="not-a-real-env")


def test_missing_environment_fails_fast(monkeypatch):
    # No ENVIRONMENT env var and no value supplied → required field missing → ValidationError
    # (fail fast at boot, test J6). settings_customise_sources falls back to the development
    # config file, which deliberately does NOT carry an `environment` key.
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
