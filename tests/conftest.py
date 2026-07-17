"""Shared test fixtures."""

import os

# The app validates ENVIRONMENT at boot (PY-D21); set it before importing the app.
os.environ.setdefault("ENVIRONMENT", "development")

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    # Importing inside the fixture keeps app import after the env var is set.
    from app.main import app

    # The context manager runs the lifespan startup/shutdown (exercises P10).
    with TestClient(app) as test_client:
        yield test_client
