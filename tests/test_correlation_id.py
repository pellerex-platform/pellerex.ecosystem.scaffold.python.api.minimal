"""A request's correlation id: the caller's when it is safe to log, a new one otherwise. It is
echoed on the response and stamped on every record written while the request is served."""

import logging
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import telemetry
from app.logging_config import CorrelationIdFilter
from app.middleware import correlation_id_middleware, correlation_id_var, get_correlation_id

# Written out on purpose: the platform's proxy sends the header and the portal's Logs tab reads
# the log field by these exact names, so a rename must fail a test.
HEADER = "X-Correlation-Id"
LOG_FIELD = "CorrelationId"

NEW_ID = re.compile(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}")

IDS_NOT_SAFE_TO_LOG = [
    "",
    " ",
    "a" * 129,
    "abc def",
    "abc,abc",
    "abc\ndef",
    "abc\n",
    "abcïdef",
    "<script>",
    # The characters just outside each range an id may hold
    "abc/def",
    "abc:def",
    "abc@def",
    "abc[def",
    "abc`def",
    "abc{def",
]


class Sink(logging.Handler):
    """Stands in for a log sink: keeps the correlation id each record carried on arrival."""

    def __init__(self) -> None:
        super().__init__()
        self.addFilter(CorrelationIdFilter())
        self.arrived: list[tuple[str, str | None]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.arrived.append((record.getMessage(), getattr(record, LOG_FIELD, None)))

    def id_on(self, message_start: str) -> str | None:
        for message, carried in self.arrived:
            if message.startswith(message_start):
                return carried
        raise AssertionError(f"no record starting with {message_start!r} reached the sink")


@pytest.fixture
def served():
    """A small app behind the real middleware, whose one route writes a log record, and a sink
    that receives every record written under the ``app`` logger."""
    sink = Sink()
    app_logger = logging.getLogger("app")
    level_before = app_logger.level
    app_logger.addHandler(sink)
    app_logger.setLevel(logging.INFO)

    api = FastAPI()
    api.middleware("http")(correlation_id_middleware)

    @api.get("/work")
    async def work():
        logging.getLogger("app.work").info("working")
        return {"id": get_correlation_id()}

    with TestClient(api) as test_client:
        yield test_client, sink

    app_logger.removeHandler(sink)
    app_logger.setLevel(level_before)


def call(test_client: TestClient, sent: str | None):
    # Sent as bytes, the way a header arrives, so an id outside ASCII can be sent at all
    headers = {} if sent is None else {HEADER: sent.encode("latin-1")}
    return test_client.get("/work", headers=headers)


def test_the_callers_id_is_returned_and_carried_by_every_record_of_the_request(served):
    test_client, sink = served
    # One of every kind of character an id may hold, with both ends of each range
    sent = "azAZ09-_.Order-42"

    response = call(test_client, sent)

    assert response.headers[HEADER] == sent
    assert response.json()["id"] == sent
    assert sink.id_on("working") == sent
    assert sink.id_on("HTTP GET /work") == sent


def test_a_call_without_an_id_is_given_a_new_one(served):
    test_client, sink = served

    response = call(test_client, None)

    returned = response.headers[HEADER]
    assert NEW_ID.fullmatch(returned)
    assert response.json()["id"] == returned
    assert sink.id_on("working") == returned
    assert sink.id_on("HTTP GET /work") == returned


def test_the_longest_id_taken_as_sent_has_128_characters(served):
    test_client, _ = served
    sent = "a" * 128

    assert call(test_client, sent).headers[HEADER] == sent


@pytest.mark.parametrize("sent", IDS_NOT_SAFE_TO_LOG)
def test_an_id_that_is_not_safe_to_log_is_replaced(served, sent):
    test_client, sink = served

    response = call(test_client, sent)

    returned = response.headers[HEADER]
    assert NEW_ID.fullmatch(returned)
    assert response.json()["id"] == returned
    assert sink.id_on("working") == returned
    assert sink.id_on("HTTP GET /work") == returned


def test_the_real_app_returns_the_callers_id(client):
    response = client.get("/v1/hello", headers={HEADER: "order-42"})

    assert response.headers[HEADER] == "order-42"


def test_a_record_written_outside_a_request_gets_no_id():
    record = logging.LogRecord("app", logging.INFO, __file__, 0, "started", (), None)

    CorrelationIdFilter().filter(record)

    assert not hasattr(record, LOG_FIELD)


def test_the_app_insights_handler_stamps_the_id_on_the_records_it_ships(monkeypatch):
    shipped: list[str | None] = []

    class Exporter(logging.Handler):
        """Stands in for the handler the Azure Monitor distro attaches to the named logger."""

        def emit(self, record: logging.LogRecord) -> None:
            shipped.append(getattr(record, LOG_FIELD, None))

    def attach_exporter(connection_string: str, logger_name: str) -> None:
        logging.getLogger(logger_name).addHandler(Exporter())

    monkeypatch.setattr("azure.monitor.opentelemetry.configure_azure_monitor", attach_exporter)
    exported_logger = logging.getLogger("app.exported-in-this-test")
    exported_logger.setLevel(logging.INFO)

    try:
        assert telemetry.configure_telemetry(
            "InstrumentationKey=00000000-0000-0000-0000-000000000000",
            logger_name=exported_logger.name,
        )

        token = correlation_id_var.set("order-42")
        try:
            logging.getLogger(f"{exported_logger.name}.child").info("saved")
        finally:
            correlation_id_var.reset(token)
        logging.getLogger(f"{exported_logger.name}.child").info("started")
    finally:
        exported_logger.handlers = []

    assert shipped == ["order-42", None]
