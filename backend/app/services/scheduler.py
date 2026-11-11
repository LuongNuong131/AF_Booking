"""Independent asyncio jobs, immediate startup catch-up, no overlapping job runs."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Job:
    name: str
    callback: Callable[[], Awaitable[None]]
    interval: float
    timeout: float


class Scheduler:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.status = {}
        self.running = False

    def add_job(
        self,
        name: str,
        callback: Callable[[], Awaitable[None]],
        *,
        interval: float,
        timeout: float = 120,
    ) -> None:
        if name in self.jobs or interval <= 0 or timeout <= 0:
            raise ValueError("Jobs need a unique name and positive interval/deadline")
        self.jobs[name] = Job(name, callback, interval, timeout)
        self.status[name] = dict(
            name=name,
            running=False,
            last_started_at=None,
            last_finished_at=None,
            duration_ms=None,
            last_error=None,
        )
        if self.running:
            self.tasks[name] = asyncio.create_task(self._run(self.jobs[name]), name=f"job:{name}")

    async def _run(self, job: Job) -> None:
        while True:
            start = asyncio.get_running_loop().time()
            state = self.status[job.name]
            state.update(running=True, last_started_at=datetime.now(UTC))
            try:
                async with asyncio.timeout(job.timeout):
                    await job.callback()
                    state["last_error"] = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                state["last_error"] = type(exc).__name__
                logger.warning("Scheduled job %s failed (%s)", job.name, type(exc).__name__)
            finally:
                state.update(
                    running=False,
                    last_finished_at=datetime.now(UTC),
                    duration_ms=(asyncio.get_running_loop().time() - start) * 1000,
                )
            elapsed = asyncio.get_running_loop().time() - start
            # Missed intervals coalesce into one catch-up; never spin on a failed job.
            await asyncio.sleep(max(0.01, job.interval - elapsed))

    def start(self) -> None:
        if not self.running:
            self.running = True
            for job in self.jobs.values():
                self.tasks[job.name] = asyncio.create_task(self._run(job), name=f"job:{job.name}")

    async def stop(self) -> None:
        self.running = False
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
