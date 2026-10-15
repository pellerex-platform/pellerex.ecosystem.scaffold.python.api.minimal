"""Health routes (P2 / PY-D12).

``/health/{startup,live,ready}`` at the **root** (no ``/api`` prefix). The platform depends on
these exact paths: the Dockerfile HEALTHCHECK hits ``/health/startup``, the proxy bypasses auth +
metering on exactly these three paths, and the chart's Kubernetes checks call them.

Each answers one word from the last result of the health test (:mod:`app.health_tester`):
``Healthy`` (200) or ``Unhealthy`` (503). Anyone can call them, so what failed and why goes to the
health test's log line only. The words are ASP.NET Core's own, which the .NET scaffold answers
with, so an app answers the same in every language.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["health"])


def _answer(healthy: bool) -> PlainTextResponse:
    if healthy:
        return PlainTextResponse("Healthy")
    return PlainTextResponse("Unhealthy", status_code=503)


@router.get("/health/startup", response_class=PlainTextResponse)
async def startup(request: Request) -> PlainTextResponse:
    """Healthy once the first health test has finished, whatever it found."""
    return _answer(request.app.state.health_tester.started())


@router.get("/health/live", response_class=PlainTextResponse)
async def live(request: Request) -> PlainTextResponse:
    """Healthy when the last health test passed."""
    return _answer(request.app.state.health_tester.healthy())


@router.get("/health/ready", response_class=PlainTextResponse)
async def ready(request: Request) -> PlainTextResponse:
    """Healthy when the last health test passed."""
    return _answer(request.app.state.health_tester.healthy())
