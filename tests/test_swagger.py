"""Swagger (/docs and /redoc) and the API description it reads (/openapi.json) answer only when
the app runs on the developer's own computer (ENVIRONMENT=development), never in
qualityassurance, staging or production."""

import importlib

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings

SWAGGER_PATHS = ["/docs", "/redoc", "/openapi.json"]


@pytest.fixture(params=["qualityassurance", "staging", "production"])
def app_outside_development(request, monkeypatch):
    """The app as it is built in another environment.

    The app is built when app.main is imported, from the cached settings, so the cache is
    cleared and the module loaded again for that environment. Afterwards both are done once
    more for development, so the other tests get the app they expect. The lifespan is not run:
    it reads the mounted secrets, and the calls these tests make do not need it.
    """
    main = importlib.import_module("app.main")

    try:
        with monkeypatch.context() as patched:
            patched.setenv("ENVIRONMENT", request.param)
            # The config files of these environments write log files to /var/log/app and, in an
            # app made from this template, carry a real App Insights connection string. A test
            # needs neither.
            patched.setenv("LOG_FILE_ENABLED", "false")
            patched.setenv("AZURE_APP_INSIGHTS_CONNECTION_STRING", "")
            get_settings.cache_clear()

            yield importlib.reload(main).app
    finally:
        get_settings.cache_clear()
        importlib.reload(main)


@pytest.mark.parametrize("path", SWAGGER_PATHS)
def test_swagger_is_served_when_the_app_runs_on_the_developers_own_computer(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", SWAGGER_PATHS)
def test_swagger_is_not_served_when_the_app_runs_in_another_environment(
    app_outside_development, path
):
    test_client = TestClient(app_outside_development)

    assert test_client.get(path).status_code == 404
    # The same app answers its own routes, so the 404 is Swagger being off, not a broken app.
    assert test_client.get("/v1/hello").status_code == 200
