"""Structured logging with Serilog-equivalent sinks (PY-D7 parity with the .NET scaffold).

Three sinks, all stdlib — no extra dependencies:

1. **Console** — JSON to stdout (always; collected by the platform).
2. **Files** — daily-rolling ``log-<date>.log`` (text) + ``log-<date>.json`` (JSON) under
   ``settings.log_file_directory``, pruned after ``settings.log_retention_days``. In-cluster
   the directory is a writable ``emptyDir`` (``/var/log/app``) mounted by the Helm chart, so
   the read-only root filesystem stays intact.
3. **Azure Application Insights** — NOT a handler here: ``configure_azure_monitor`` (see
   :mod:`app.telemetry`) attaches the first-party OTel exporter to the ``app`` logger, so
   every record logged under ``app.*`` also lands in App Insights (in-process, no collector).

Every record is enriched with ``service.name`` / ``service.version`` /
``deployment.environment`` and, within a request, ``correlation_id`` (see
:mod:`app.middleware`). The minimum level is config-driven (``log_level`` /
``LOG_LEVEL``).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

from app.middleware import get_correlation_id

SERVICE_NAME = "RepoUniqueNormalisedIdentifier"
SERVICE_VERSION = "1.0.0"

DATE_FORMAT = "%Y%m%d"
FILE_PREFIX = "log-"


class CorrelationIdFilter(logging.Filter):
    """Stamps the request-scoped correlation id onto every record (empty outside requests).

    ``CorrelationId`` (PascalCase) matches the .NET/Serilog property name the portal's
    Logs tab reads. Records that already carry it (the middleware request line sets it
    via ``extra`` so the App Insights export sees it too) are left untouched.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "CorrelationId", ""):
            record.CorrelationId = get_correlation_id()
        return True


# LogRecord attributes that are logging-machinery internals, not caller-supplied
# fields — everything else on a record (``extra`` keys, CorrelationId) is emitted.
# ``color_message`` is uvicorn's ANSI-coloured duplicate of msg — noise, not data.
_STANDARD_ATTRS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()
) | {"message", "asctime", "taskName", "color_message"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line — the console + ``.json`` file shape.

    Caller-supplied ``extra`` fields (e.g. the request line's portal-contract keys —
    RequestMethod, RequestPath, StatusCode, …) are included, mirroring what the App
    Insights export puts in customDimensions.
    """

    def __init__(self, environment: str) -> None:
        super().__init__()
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "service.name": SERVICE_NAME,
            "service.version": SERVICE_VERSION,
            "deployment.environment": self.environment,
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and key not in payload and value != "":
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable line for the ``.log`` file (mirrors the .NET/Java text sinks)."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        correlation_id = getattr(record, "CorrelationId", "")
        line = f"{ts} [{record.levelname}] {record.name} - {record.getMessage()}"
        if correlation_id:
            line += f" {correlation_id}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


class DailyRotatingFileHandler(logging.Handler):
    """Daily-rolling file sink — ``<dir>/log-<YYYYMMDD><suffix>`` with retention pruning.

    Same semantics as the Go/Node scaffolds' writers and the .NET Serilog File sink
    (``rollingInterval: Day``): the active file is named for the current date, rolls at the
    date change, and files older than ``retention_days`` are removed best-effort.
    """

    def __init__(self, directory: str, suffix: str, retention_days: int) -> None:
        super().__init__()
        self.directory = directory
        self.suffix = suffix
        self.retention_days = retention_days
        self.day = ""
        self.stream = None
        os.makedirs(directory, exist_ok=True)
        self._rotate(self._today())

    @staticmethod
    def _today() -> str:
        return date.today().strftime(DATE_FORMAT)

    def _rotate(self, day: str) -> None:
        if self.stream is not None:
            self.stream.close()
        self.day = day
        path = os.path.join(self.directory, f"{FILE_PREFIX}{day}{self.suffix}")
        self.stream = open(path, "a", encoding="utf-8")
        self._prune()

    def _prune(self) -> None:
        if self.retention_days <= 0:
            return
        cutoff = (date.today() - timedelta(days=self.retention_days)).strftime(DATE_FORMAT)
        pattern = re.compile(rf"^{FILE_PREFIX}(\d{{8}}){re.escape(self.suffix)}$")
        try:
            for name in os.listdir(self.directory):
                match = pattern.match(name)
                if match and match.group(1) < cutoff:
                    try:
                        os.remove(os.path.join(self.directory, name))
                    except OSError:
                        pass
        except OSError:
            pass

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self._today() != self.day:
                self._rotate(self._today())
            self.stream.write(self.format(record) + "\n")
            self.stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        super().close()


def configure_logging(settings) -> None:
    """Wire the root logger to the Serilog-equivalent sinks (idempotent).

    Root-level wiring means every logger (``app.*``, ``uvicorn.*``) flows through the same
    sinks. uvicorn's own plain-text handlers are removed so its records are structured too;
    ``uvicorn.access`` is silenced because the correlation middleware already emits one
    structured line per request (the .NET request-logging equivalent).
    """
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    correlation_filter = CorrelationIdFilter()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(JsonFormatter(settings.environment))
    handlers: list[logging.Handler] = [console]

    if settings.log_file_enabled and settings.log_file_directory:
        try:
            text_file = DailyRotatingFileHandler(
                settings.log_file_directory, ".log", settings.log_retention_days
            )
            text_file.setFormatter(TextFormatter())
            json_file = DailyRotatingFileHandler(
                settings.log_file_directory, ".json", settings.log_retention_days
            )
            json_file.setFormatter(JsonFormatter(settings.environment))
            handlers += [text_file, json_file]
        except OSError:
            logging.getLogger("app").warning(
                "file logging disabled: cannot open log directory %s",
                settings.log_file_directory,
            )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = handlers
    for handler in handlers:
        handler.addFilter(correlation_filter)

    # Route uvicorn's lifecycle logs through the structured root sinks; drop its access
    # log (the middleware's request line replaces it, with correlation id).
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False
