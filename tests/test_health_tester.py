"""The health test: what it tests, the one line it writes, and the result it keeps."""

import asyncio
import logging
import re

import pytest

from app.health_tester import (
    CHECK_TIME_LIMIT_SECONDS,
    TEST_INTERVAL_SECONDS,
    HealthCheck,
    HealthTester,
)


@pytest.fixture
def lines(caplog):
    """Every line the health test writes so far."""
    caplog.set_level(logging.INFO, logger="app.health")
    return lambda: [record for record in caplog.records if record.name == "app.health"]


def only_line(lines) -> logging.LogRecord:
    written = lines()
    assert len(written) == 1, "one line per test"
    return written[0]


def passing(name: str) -> HealthCheck:
    async def test() -> None:
        return None

    return HealthCheck(name=name, test=test)


def failing(name: str, reason: str) -> HealthCheck:
    async def test() -> None:
        raise ConnectionError(reason)

    return HealthCheck(name=name, test=test)


def test_before_the_first_test_the_app_is_neither_started_nor_healthy(lines):
    tester = HealthTester([])

    assert not tester.started()
    assert not tester.healthy()
    assert lines() == []


def test_a_new_app_has_nothing_to_test_and_is_healthy(lines):
    tester = HealthTester([])

    asyncio.run(tester.test())

    assert tester.started()
    assert tester.healthy()
    assert only_line(lines).levelno == logging.INFO
    assert only_line(lines).getMessage() == "Health test passed: nothing to test"


def test_passing_checks_are_written_with_how_long_each_took(lines):
    tester = HealthTester([passing("database"), passing("cache")])

    asyncio.run(tester.test())

    assert tester.healthy()
    assert only_line(lines).levelno == logging.INFO
    assert re.fullmatch(
        r"Health test passed: database \d+ ms, cache \d+ ms", only_line(lines).getMessage()
    )


def test_one_failed_check_makes_the_app_unhealthy_and_says_why(lines):
    tester = HealthTester([failing("database", "connection refused"), passing("cache")])

    asyncio.run(tester.test())

    assert tester.started(), "started once the first test has finished, whatever it found"
    assert not tester.healthy()
    assert only_line(lines).levelno == logging.WARNING
    assert re.fullmatch(
        r"Health test failed: database failed after \d+ ms \(connection refused\), cache \d+ ms",
        only_line(lines).getMessage(),
    )


def test_a_check_that_raises_before_it_can_be_awaited_has_failed(lines):
    def test():
        raise RuntimeError("no connection string")

    tester = HealthTester([HealthCheck(name="database", test=test)])

    asyncio.run(tester.test())

    assert not tester.healthy()
    assert re.fullmatch(
        r"Health test failed: database failed after \d+ ms \(no connection string\)",
        only_line(lines).getMessage(),
    )


def test_a_failure_with_no_message_is_named_by_its_kind(lines):
    tester = HealthTester([failing("database", "")])

    asyncio.run(tester.test())

    assert re.fullmatch(
        r"Health test failed: database failed after \d+ ms \(ConnectionError\)",
        only_line(lines).getMessage(),
    )


def test_a_check_that_does_not_answer_has_failed_and_is_cancelled(lines):
    cancelled = []

    async def hang() -> None:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    tester = HealthTester([HealthCheck(name="database", test=hang)], time_limit_seconds=0.05)

    asyncio.run(tester.test())

    assert not tester.healthy()
    assert re.fullmatch(
        r"Health test failed: database failed after \d+ ms \(did not answer within 50 ms\)",
        only_line(lines).getMessage(),
    )
    assert cancelled, "the hung check was cancelled"


def test_a_check_that_times_out_on_its_own_keeps_its_reason(lines):
    # A database driver raises TimeoutError when its login takes too long: that is the check's
    # answer, well inside the check's own time limit.
    async def test() -> None:
        raise TimeoutError("login timed out")

    tester = HealthTester([HealthCheck(name="database", test=test)])

    asyncio.run(tester.test())

    assert not tester.healthy()
    assert re.fullmatch(
        r"Health test failed: database failed after \d+ ms \(login timed out\)",
        only_line(lines).getMessage(),
    )


def test_a_check_that_raises_cancelled_error_of_its_own_has_failed_and_testing_goes_on(lines):
    tests = []

    async def test() -> None:
        tests.append(True)
        raise asyncio.CancelledError("pool closed")

    tester = HealthTester([HealthCheck(name="database", test=test)], interval_seconds=0.01)

    async def run_for_a_while() -> None:
        running = asyncio.create_task(tester.run())
        await asyncio.sleep(0.1)
        assert not running.done(), "the test goes on after a check raised CancelledError"
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)

    asyncio.run(run_for_a_while())

    assert len(tests) >= 3
    assert tester.started()
    assert not tester.healthy()
    assert re.fullmatch(
        r"Health test failed: database failed after \d+ ms \(pool closed\)",
        lines()[0].getMessage(),
    )


def test_shutdown_stops_a_test_that_is_waiting_on_a_check(lines):
    cancelled = []

    async def hang() -> None:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    tester = HealthTester([HealthCheck(name="database", test=hang)])

    async def shut_down_during_the_check() -> bool:
        running = asyncio.create_task(tester.run())
        await asyncio.sleep(0.05)
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)
        return running.cancelled()

    assert asyncio.run(shut_down_during_the_check()), "run stops when cancelled"
    assert cancelled, "the check was cancelled"
    assert not tester.started(), "a test cut short keeps no result"
    assert lines() == []


def test_the_app_is_healthy_again_once_its_checks_pass(lines):
    database_up = False

    async def test() -> None:
        if not database_up:
            raise ConnectionError("connection refused")

    tester = HealthTester([HealthCheck(name="database", test=test)])

    asyncio.run(tester.test())
    assert not tester.healthy()

    database_up = True
    asyncio.run(tester.test())
    assert tester.healthy()


def test_run_tests_straight_away_then_on_every_interval_until_cancelled(lines):
    tests = []

    async def test() -> None:
        tests.append(True)

    tester = HealthTester([HealthCheck(name="database", test=test)], interval_seconds=0.01)

    async def run_for_a_while() -> bool:
        running = asyncio.create_task(tester.run())
        await asyncio.sleep(0.1)
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)
        return running.cancelled()

    assert asyncio.run(run_for_a_while()), "run stops when cancelled"
    assert len(tests) >= 3


def test_the_test_runs_once_a_minute_and_a_check_has_ten_seconds():
    # The chart's Kubernetes checks count failed tests by these, so a change must fail a test.
    assert TEST_INTERVAL_SECONDS == 60
    assert CHECK_TIME_LIMIT_SECONDS == 10
