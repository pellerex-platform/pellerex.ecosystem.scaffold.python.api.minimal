"""Azure Monitor (Application Insights) telemetry wiring (P5 / PY-D7).

Uses the first-party ``azure-monitor-opentelemetry`` distro — the same App Insights
resource the .NET/Node services use. ``configure_azure_monitor`` auto-instruments FastAPI
(the FastAPI OpenTelemetry instrumentation ships with the distro), so it must run **before**
the FastAPI app is created (see :mod:`app.main`). The connection string comes from the
tokenised config value ``<azure-app-insights-connection-string-in-{env}>``.

opencensus is intentionally NOT used (the Django scaffold's deprecated path) — PY-D7.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("app")


def _looks_configured(connection_string: str | None) -> bool:
    """True only for a real, substituted connection string.

    Guards against running locally (no value) or against an unsubstituted token /
    ``*-placeholder>`` left by the tokeniser, so the app still boots without telemetry.
    """
    if not connection_string:
        return False
    cs = connection_string.strip()
    if not cs or cs.startswith("<") or cs.endswith("-placeholder>"):
        return False
    return "InstrumentationKey=" in cs or "IngestionEndpoint=" in cs


def configure_telemetry(connection_string: str | None, logger_name: str = "app") -> bool:
    """Configure Azure Monitor if a real connection string is present. Returns whether it did.

    Never raises — telemetry wiring must not stop the app from serving traffic.
    """
    if not _looks_configured(connection_string):
        logger.info("Azure Monitor telemetry not configured (no connection string); skipping.")
        return False
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(connection_string=connection_string, logger_name=logger_name)
        logger.info("Azure Monitor telemetry configured.")
        return True
    except Exception:  # pragma: no cover - defensive; never crash on telemetry wiring
        logger.exception("Failed to configure Azure Monitor telemetry.")
        return False
