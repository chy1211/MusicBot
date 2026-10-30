"""Dashboard-only, two-slot priority queue with per-person FIFO admission."""
from __future__ import annotations

import asyncio
import contextvars
import logging
from dataclasses import dataclass


@dataclass(eq=False)
class ResolutionJob:
    owner_id: int
    guild_id: int
    request_id: str
    priority: int
    deadline: float
    ready: asyncio.Future
    operation: object
    context: contextvars.Context
    timeout: float
    timeout_key: str
    task: asyncio.Task | None = None


class ResolutionQueue:
    def __init__(self, dashboard):
        self.dashboard = dashboard
        self.waiting = []
        self.jobs = []
        self.closed = False

    def dispatch(self):
        active = self.dashboard.resolve_tasks
        while not self.closed and len(active) < 2:
            # Only the oldest pending job per person is eligible, regardless of
            # priority. A second click never jumps over that person's first.
            seen = set(active)
            eligible = []
            for job in self.waiting:
                if job.owner_id not in seen:
                    eligible.append(job)
                seen.add(job.owner_id)
            if not eligible:
                return
            job = min(eligible, key=lambda value: value.priority)
            self.waiting.remove(job)
            if job.deadline <= asyncio.get_running_loop().time():
                from ..web_dashboard import APIError, _web_text
                job.ready.set_exception(APIError(429, job.context.run(_web_text, 'resolve.queueTimeout')))
                continue
            # Preserve the submitting request's language, CONFIRMED_ENTRY_CHECK,
            # extraction flags and pool even when another user's job frees a slot.
            task = job.context.run(asyncio.create_task, self.execute(job))
            job.task = task
            active[job.owner_id] = task
            task.add_done_callback(lambda task, job=job: self.finished(job, task))
            job.ready.set_result(task)

    async def execute(self, job):
        from ..web_dashboard import APIError, ExtractionBudget, RESOLUTION_BUDGET, _web_text
        entered = False
        async def bounded():
            nonlocal entered
            entered = True
            config = self.dashboard.config
            token = RESOLUTION_BUDGET.set(ExtractionBudget(job.timeout,
                config.resolve_max_response_bytes, config.resolve_max_total_bytes))
            try:
                return await job.operation
            finally:
                RESOLUTION_BUDGET.reset(token)
        try:
            # This clock and ExtractionBudget start only after admission.
            return await asyncio.wait_for(bounded(), job.timeout)
        except asyncio.TimeoutError:
            raise APIError(504, _web_text(job.timeout_key)) from None
        finally:
            if not entered:
                job.operation.close()

    def finished(self, job, task):
        job.operation.close()  # Includes tasks cancelled before their first turn.
        # execute() cannot finish until wait_for has cancelled and reaped its
        # provider. Keep both the global and personal slot until that point.
        if self.dashboard.resolve_tasks.get(job.owner_id) is task:
            self.dashboard.resolve_tasks.pop(job.owner_id)
        if job in self.jobs:
            self.jobs.remove(job)
        if not task.cancelled():
            task.exception()  # Also consume exceptions if its HTTP waiter left.
        self.dispatch()

    @staticmethod
    async def cancel_and_reap(task):
        if not task.done() and not task.cancelling():
            task.cancel()
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                # Repeated HTTP cancellation must not interrupt provider reaping.
                pass
            except Exception:
                break

    async def run(self, guild, owner, operation, *, priority, request, timeout, timeout_key):
        from ..web_dashboard import APIError, _web_text
        if self.closed:
            operation.close()
            raise APIError(503, _web_text('m0362'))
        loop = asyncio.get_running_loop()
        queued_at = loop.time()
        request_id = request.headers.get('X-MusicBot-Request-ID', '') if request is not None else ''
        if not (request_id.isascii() and request_id.isalnum() and len(request_id) <= 64):
            request_id = ''
        job = ResolutionJob(owner.id, guild.id, request_id, 0 if priority == 'add' else 1,
            loop.time() + self.dashboard.RESOLVE_QUEUE_TIMEOUT, loop.create_future(),
            operation, contextvars.copy_context(), timeout, timeout_key)
        self.jobs.append(job)
        self.waiting.append(job)
        self.dispatch()
        try:
            try:
                task = await asyncio.wait_for(asyncio.shield(job.ready),
                    max(0, job.deadline - loop.time()))
            except asyncio.TimeoutError:
                raise APIError(429, _web_text('resolve.queueTimeout')) from None
            admitted_at = loop.time()
            try:
                return await asyncio.shield(task)
            finally:
                logging.getLogger(__name__).info(
                    'Dashboard resolution timing: wait=%.3fs active=%.3fs',
                    admitted_at - queued_at, loop.time() - admitted_at)
        finally:
            if job.task is not None:
                if not job.task.done():
                    await self.cancel_and_reap(job.task)
            else:
                if job in self.waiting:
                    self.waiting.remove(job)
                if job in self.jobs:
                    self.jobs.remove(job)
                if not job.ready.done():
                    job.ready.cancel()
                elif not job.ready.cancelled():
                    job.ready.exception()
                operation.close()
                self.dispatch()

    async def close(self):
        self.closed = True
        for job in list(self.waiting):
            job.ready.cancel()
        await asyncio.gather(*(self.cancel_and_reap(task)
            for task in list(self.dashboard.resolve_tasks.values())))
