"""Correlation-id middleware (PY-D7 parity — the .NET LogContextEnrichment equivalent).

Honours an inbound ``X-Correlation-Id`` header (or mints a UUID), stores it in a
``contextvars.ContextVar`` so the logging filter stamps it on every record produced within
the request (console, files, and the App Insights export alike), echoes it on the response,
and emits one structured line per request — the same request log the .NET/Go/Node/Java
scaffolds produce.

The request line's ``extra`` attribute names are a CONTRACT with the Pellerex portal's
Logs tab: its KQL reads customDimensions.RequestMethod / RequestPath / StatusCode /
Elapsed / CorrelationId / Environment / UserAgent / ClientIPAddress / ClientPort / Port /
MachineName by exact name. Renaming any of them blanks the matching column in the portal.
They must live on the record itself (``extra``), not in a handler filter — the App
Insights handler attaches at the ``app`` logger and runs before the root handlers, so
handler-level filters never reach the exported record.
"""

from __future__ import annotations

import logging
import socket
import time
import uuid
from contextvars import ContextVar

from fastapi import Request

from app.config import get_settings

CORRELATION_ID_HEADER = "X-Correlation-Id"

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")

logger = logging.getLogger("app.http")

MACHINE_NAME = socket.gethostname()


def get_correlation_id() -> str:
    """The current request's correlation id ('' outside a request context)."""
    return correlation_id_var.get()


async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get(CORRELATION_ID_HEADER) or str(uuid.uuid4())
    token = correlation_id_var.set(correlation_id)
    start = time.perf_counter()
    status_code = 500  # reported if call_next raises (the 500 handler responds)
    try:
        response = await call_next(request)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        status_code = response.status_code
        return response
    finally:
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
        correlation_id_var.reset(token)
