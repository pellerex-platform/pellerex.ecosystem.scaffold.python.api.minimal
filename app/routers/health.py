"""Health routes (P2 / PY-D12).

``/health/{startup,live,ready}`` at the **root** (no ``/api`` prefix), each returning 200.
The platform depends on these exact paths: the Dockerfile HEALTHCHECK hits
``/health/startup`` and the proxy bypasses auth + metering on exactly these three paths.
There are intentionally **no Kubernetes probes** in the chart (minimal contract) — readiness
is proven through ProxyApi.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.config import get_secrets, get_settings

router = APIRouter(tags=["health"])


@router.get("/health/startup")
async def startup() -> dict:
    """Liveness of the process once it has finished starting."""
    return {"status": "started"}


@router.get("/health/live")
async def live() -> dict:
    """Basic responsiveness — no external dependencies."""
    return {"status": "alive"}


@router.get("/health/ready")
async def ready() -> dict:
    """Readiness — verifies configuration loaded (and that the secret mount is reachable)."""
    settings = get_settings()
    secrets = get_secrets()
    return {
        "status": "ready",
        "checks": {
            "config": "ok",
            "environment": settings.environment,
            "secret_mount": "loaded" if secrets.has_database_secret else "absent",
        },
    }
