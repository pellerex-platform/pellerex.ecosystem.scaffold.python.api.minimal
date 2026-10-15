"""The app's health test (P2 / PY-D12).

Straight away and then once a minute it tests every check the app cannot work without, at the
same time, writes one log line saying what was tested and how long each part took, and keeps
whether all of them passed. The health routes (:mod:`app.routers.health`) answer from that
result, so no number of calls to them costs the checked dependencies anything.

Tenant apps test once a minute, not every 30 seconds as the platform services do: the databases
Pellerex creates for them share one pool, so every test of every app adds to it. The chart's
Kubernetes checks call once a minute too (``infrastructure/Helm/templates/deployment.yaml``).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

# How often the test runs.
TEST_INTERVAL_SECONDS = 60
# How long one check may take. A check that has not answered by then has failed.
CHECK_TIME_LIMIT_SECONDS = 10

logger = logging.getLogger("app.health")


@dataclass(frozen=True)
class HealthCheck:
    """One thing the app cannot work without, such as its database.

    ``test`` returns when the thing works and raises, saying why, when it does not. It is given
    10 seconds, then it has failed and is cancelled. It runs on the app's event loop, so a call
    that blocks goes through ``asyncio.to_thread``.
    """

    name: str
    test: Callable[[], Awaitable[object]]


@dataclass(frozen=True)
class _CheckResult:
    """What one check of one test found: how long it took and, when it failed, why."""

    name: str
    milliseconds: int
    failure: str | None

    def describe(self) -> str:
        """``database 12 ms``, or ``database failed after 12 ms (why)``."""
        if self.failure is None:
            return f"{self.name} {self.milliseconds} ms"
        return f"{self.name} failed after {self.milliseconds} ms ({self.failure})"


class HealthTester:
    """Runs the health test and keeps its last result. Built once, in the app's lifespan."""

    def __init__(
        self,
        checks: list[HealthCheck],
        interval_seconds: float = TEST_INTERVAL_SECONDS,
        time_limit_seconds: float = CHECK_TIME_LIMIT_SECONDS,
    ) -> None:
        self._checks = list(checks)
        self._interval_seconds = interval_seconds
        self._time_limit_seconds = time_limit_seconds
        self._finished = False
        self._passed = False

    async def run(self) -> None:
        """Tests straight away and then once a minute, until cancelled."""
        while True:
            await self.test()
            await asyncio.sleep(self._interval_seconds)

    async def test(self) -> None:
        """One health test: every check at the same time, one log line, the result kept."""
        results = await asyncio.gather(*(self._test_check(check) for check in self._checks))
        passed = all(result.failure is None for result in results)
        summary = ", ".join(result.describe() for result in results) or "nothing to test"

        if passed:
            logger.info("Health test passed: %s", summary)
        else:
            logger.warning("Health test failed: %s", summary)

        self._passed = passed
        self._finished = True

    def started(self) -> bool:
        """Whether the first test has finished, whatever it found."""
        return self._finished

    def healthy(self) -> bool:
        """Whether the last test passed. Before the first test has finished it is False."""
        return self._finished and self._passed

    async def _test_check(self, check: HealthCheck) -> _CheckResult:
        """Runs one check. The check reaches something outside the app, such as its database,
        so what it raises is its answer, not an error of the app."""
        start = time.perf_counter()
        failure: str | None = None
        time_limit = asyncio.timeout(self._time_limit_seconds)
        try:
            async with time_limit:
                await check.test()
        except asyncio.CancelledError as error:
            # The app's shutdown cancels a running test, and that ends it. A check that raises
            # CancelledError of its own, such as from a connection its pool closed, has failed.
            if asyncio.current_task().cancelling():
                raise
            failure = str(error) or type(error).__name__
        except Exception as error:
            # Only the time limit running out means the check did not answer. A check can raise
            # TimeoutError of its own sooner, such as a driver's login timeout, and keeps its
            # own reason.
            if time_limit.expired():
                failure = f"did not answer within {round(self._time_limit_seconds * 1000)} ms"
            else:
                failure = str(error) or type(error).__name__
        milliseconds = int((time.perf_counter() - start) * 1000)
        return _CheckResult(check.name, milliseconds, failure)
