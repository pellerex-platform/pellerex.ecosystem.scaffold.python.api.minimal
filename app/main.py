"""FastAPI application entry point (P1).

Run with::

    uvicorn app.main:app --host 0.0.0.0 --port <port-number>   # PY-D5

Health routes are served at the **root** (``/health/{startup,live,ready}``) with no ``/api``
prefix — the proxy bypasses auth + metering on exactly those three paths (P2 / PY-D12).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_secrets, get_settings
from app.logging_config import configure_logging
from app.middleware import correlation_id_middleware
from app.telemetry import configure_telemetry

# Instantiating the settings validates configuration at boot → fail fast (PY-D21).
settings = get_settings()

# Serilog-equivalent sinks: JSON console + daily-rolling files; App Insights export
# is attached to the "app" logger by configure_telemetry below (PY-D7 parity).
configure_logging(settings)
logger = logging.getLogger("app")

# Telemetry must be configured BEFORE the FastAPI app is created so the Azure Monitor
# distro auto-instruments it (P5 / PY-D7).
configure_telemetry(settings.azure_app_insights_connection_string, logger_name="app")

# Routers are imported after telemetry is configured.
from app.routers import health, hello  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    logger.info("Starting up (environment=%s)", settings.environment)
    # Acquire shared resources here (DB pools, HTTP clients, ...). Touching get_secrets()
    # at startup surfaces a missing/misconfigured secret mount early rather than per-request.
    _ = get_secrets()
    yield
    # --- Shutdown (P10 / PY-D13) ---
    # uvicorn stops accepting connections and drains in-flight requests on SIGTERM, then runs
    # this block. Release the resources acquired above here.
    logger.info("Shutting down; releasing resources.")


app = FastAPI(
    title="RepoUniqueNormalisedIdentifier",
    description="A minimal, parity-complete FastAPI Managed API scaffold.",
    version="1.0.0",
    debug=False,  # never leak stack traces in prod (P15 / PY-D21)
    lifespan=lifespan,
)

# Correlation id + one structured request log line per request (PY-D7 parity).
app.middleware("http")(correlation_id_middleware)

# Routes (all at root — no /api prefix; PY-D12).
app.include_router(health.router)
app.include_router(hello.router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Pydantic request models validate input automatically; surface a clean 422 (PY-D21 / J3).
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Global handler — generic 500 envelope, NO stack trace in the response (P15 / PY-D21 / J4).
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "message": "An unexpected error occurred."},
    )
