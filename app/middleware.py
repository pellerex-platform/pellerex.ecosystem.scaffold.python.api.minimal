"""Correlation-id middleware (PY-D7 parity — the .NET LogContextEnrichment equivalent).

Takes an inbound ``X-Correlation-Id`` header as sent when it is safe to log (or mints a
UUID), stores it in a ``contextvars.ContextVar`` so the logging filter stamps it on every
record produced within the request (console, files, and the App Insights export alike),
echoes it on the response, and emits one structured line per request: the same request log
the .NET/Go/Node/Java scaffolds produce. Requests to the health routes write no line.

The request line's ``extra`` attribute names are a CONTRACT with the Pellerex portal's
Logs tab: its KQL reads customDimensions.RequestMethod / RequestPath / StatusCode /
Elapsed / CorrelationId / Environment / UserAgent / ClientIPAddress / ClientPort / Port /
MachineName by exact name. Renaming any of them blanks the matching column in the portal.
They must live on the record itself (``extra``), not in a filter on the root handlers: the
App Insights handler attaches at the ``app`` logger and runs before the root handlers, so
their filters never reach the exported record.
"""

from __future__ import annotations

import logging
import re
import socket
import time
import uuid
from contextvars import ContextVar

from fastapi import Request

from app.config import get_settings

CORRELATION_ID_HEADER = "X-Correlation-Id"

# A caller's correlation id is taken as sent only when it matches this. The id comes from
# outside and is written to the logs and to the reply, so only a run of at most 128 ASCII
# letters, digits, hyphens, underscores and dots is. Any other is replaced with a new one.
ACCEPTABLE_CORRELATION_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")

# The health routes (:mod:`app.routers.health`). Kubernetes calls them once a minute and the
# health test writes its own line, so a request line for them would only repeat it.
HEALTH_PATHS = frozenset({"/health/startup", "/health/live", "/health/ready"})

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")

logger = logging.getLogger("app.http")

MACHINE_NAME = socket.gethostname()


def get_correlation_id() -> str:
    """The current request's correlation id ('' outside a request context)."""
    return correlation_id_var.get()


async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get(CORRELATION_ID_HEADER, "")
    if not ACCEPTABLE_CORRELATION_ID.fullmatch(correlation_id):
        correlation_id = str(uuid.uuid4())
    token = correlation_id_var.set(correlation_id)
    start = time.perf_counter()
    status_code = 500  # reported if call_next raises (the 500 handler responds)
    try:
        response = await call_next(request)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        status_code = response.status_code
        return response
    finally:
        if request.url.path not in HEALTH_PATHS:
            _write_request_line(request, status_code, start, correlation_id)
        correlation_id_var.reset(token)


def _write_request_line(
    request: Request, status_code: int, start: float, correlation_id: str
) -> None:
    """The request line, with the names the portal's Logs tab reads."""
    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    settings = get_settings()
    client = request.client
    server = request.scope.get("server")  # (host, port) of the serving socket
    logger.info(
        "HTTP %s %s responded %d in %s ms",
        request.method,
        request.url.path,
        status_code,
        elapsed_ms,
        extra={
            "StatusCode": status_code,
            "RequestMethod": request.method,
            "RequestPath": request.url.path,
            "Elapsed": elapsed_ms,
            "CorrelationId": correlation_id,
            "Environment": settings.environment,
            "UserAgent": request.headers.get("user-agent", ""),
            "ClientIPAddress": client.host if client else "",
            "ClientPort": str(client.port) if client else "",
            "Port": str(server[1]) if server and server[1] else "",
            "MachineName": MACHINE_NAME,
        },
    )
