"""Health route tests (P2 / PY-D12): one word from the last health test, and no request line."""

import asyncio
import logging
import time

import pytest

from app.health_tester import HealthCheck, HealthTester

PATHS = ["/health/startup", "/health/live", "/health/ready"]


def answers(client) -> dict[str, str]:
    """What each health route answered, as '<status> <content type> <body>'."""
    answered = {}
    for path in PATHS:
        r = client.get(path, headers={"accept": "application/json"})
        answered[path] = f"{r.status_code} {r.headers['content-type']} {r.text}"
    return answered


def test_the_app_runs_its_first_health_test_as_it_starts(client):
    tester = client.app.state.health_tester
    deadline = time.monotonic() + 5
    while not tester.started() and time.monotonic() < deadline:
        time.sleep(0.01)

    assert answers(client) == {
        "/health/startup": "200 text/plain; charset=utf-8 Healthy",
        "/health/live": "200 text/plain; charset=utf-8 Healthy",
        "/health/ready": "200 text/plain; charset=utf-8 Healthy",
    }


def test_before_the_first_test_every_route_answers_unhealthy(client):
    client.app.state.health_tester = HealthTester([])

    assert answers(client) == {
        "/health/startup": "503 text/plain; charset=utf-8 Unhealthy",
        "/health/live": "503 text/plain; charset=utf-8 Unhealthy",
        "/health/ready": "503 text/plain; charset=utf-8 Unhealthy",
    }


def test_after_a_failed_test_live_and_ready_answer_unhealthy_with_no_reason(client):
    # A failed test keeps the app started, so Kubernetes does not kill it while it starts, and
    # the answer is one word with no reason: anyone can call these routes.
    async def test() -> None:
        raise ConnectionError("Login failed for user orders-api")

    tester = HealthTester([HealthCheck(name="database", test=test)])
    asyncio.run(tester.test())
    client.app.state.health_tester = tester

    assert answers(client) == {
        "/health/startup": "200 text/plain; charset=utf-8 Healthy",
        "/health/live": "503 text/plain; charset=utf-8 Unhealthy",
        "/health/ready": "503 text/plain; charset=utf-8 Unhealthy",
    }


def test_health_is_at_root_not_under_api(client):
    # The proxy bypasses auth+metering on the root /health/* paths only — there must be no
    # /api-prefixed variant (PY-D12).
    assert client.get("/api/health/startup").status_code == 404


@pytest.fixture
def request_lines(caplog):
    """The request lines the app writes."""
    caplog.set_level(logging.INFO, logger="app.http")
    return lambda: [record for record in caplog.records if record.name == "app.http"]


@pytest.mark.parametrize("path", [*PATHS, "/health/ready?probe=1"])
def test_a_call_to_a_health_route_writes_no_request_line(client, request_lines, path):
    # Kubernetes calls the health routes once a minute and the health test writes its own line.
    client.get(path)

    assert request_lines() == []


def test_a_route_that_only_starts_like_a_health_route_keeps_its_line(client, request_lines):
    client.get("/health/readyz")

    assert [record.RequestPath for record in request_lines()] == ["/health/readyz"]
