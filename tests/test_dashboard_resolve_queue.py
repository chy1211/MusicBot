"""Offline queue scheduling, lifecycle, request-context and private status tests."""
import asyncio
import contextvars
import inspect
import json
import unittest
from types import SimpleNamespace as NS

from musicbot.dashboard_backend.resolve import DashboardResolveRoutes
from musicbot.dashboard_backend.resolution_queue import ResolutionQueue
from musicbot.web_dashboard import APIError, RESOLUTION_BUDGET, CONFIRMED_ENTRY_CHECK
from musicbot.web_dashboard_i18n import LANGUAGE, message
import test_web_dashboard_imports as imports


class Host(DashboardResolveRoutes):
    RESOLVE_TIMEOUT = 1
    def __init__(self):
        self.config = NS(resolve_max_response_bytes=1024, resolve_max_total_bytes=4096)
        self.resolve_tasks = {}
        self.resolution_queue = ResolutionQueue(self)


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.host = Host()
        self.guild = NS(id=1)
        self.tasks = []
        self.started = []
        self.releases = {}

    async def asyncTearDown(self):
        for task in self.tasks:
            if not task.done(): task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.host.resolution_queue.close()
        self.assertEqual(self.host.resolve_tasks, {})
        self.assertEqual(self.host.resolution_queue.waiting, [])
        self.assertEqual(self.host.resolution_queue.jobs, [])

    async def until(self, predicate):
        async def spin():
            while not predicate(): await asyncio.sleep(0)
        await asyncio.wait_for(spin(), 1)

    def submit(self, uid, label, priority='lookup', request=None, operation=None):
        release = self.releases[label] = asyncio.Event()
        async def fake():
            self.started.append(label)
            await release.wait()
            return label
        task = asyncio.create_task(self.host.run_resolution(self.guild,
            operation if operation is not None else fake(), owner=NS(id=uid),
            priority=priority, request=request))
        self.tasks.append(task)
        return task

    async def full(self):
        self.submit(1, 'first'); self.submit(2, 'second')
        await self.until(lambda: len(self.started) == 2)

    async def test_same_guild_two_people_start_immediately(self):
        await self.full()
        self.assertEqual(self.started, ['first', 'second'])
        self.assertEqual(len(self.host.resolve_tasks), 2)
        for release in self.releases.values(): release.set()
        self.assertEqual(await asyncio.gather(*self.tasks), ['first', 'second'])

    async def test_third_queues_then_automatically_succeeds(self):
        await self.full()
        third = self.submit(3, 'third')
        await self.until(lambda: len(self.host.resolution_queue.waiting) == 1)
        self.assertNotIn('third', self.started)
        self.releases['first'].set()
        await self.until(lambda: 'third' in self.started)
        self.releases['second'].set(); self.releases['third'].set()
        self.assertEqual(await asyncio.gather(*self.tasks), ['first', 'second', 'third'])
        self.assertEqual(await third, 'third')

    async def test_add_priority_and_fifo_within_each_class(self):
        await self.full()
        for uid, label, priority in [(3,'lookup1','lookup'),(4,'lookup2','lookup'),
                                     (5,'add1','add'),(6,'add2','add')]:
            self.submit(uid, label, priority)
        await self.until(lambda: len(self.host.resolution_queue.waiting) == 4)
        for previous, expected in [('first','add1'),('add1','add2'),('add2','lookup1'),('lookup1','lookup2')]:
            self.releases[previous].set()
            await self.until(lambda: expected in self.started)
        self.assertEqual(self.started, ['first','second','add1','add2','lookup1','lookup2'])
        for release in self.releases.values(): release.set()
        await asyncio.gather(*self.tasks)

    async def test_same_person_fifo_does_not_take_someone_elses_place(self):
        await self.full()
        self.submit(1,'own_lookup'); self.submit(1,'own_add','add'); self.submit(3,'other')
        await self.until(lambda: len(self.host.resolution_queue.waiting) == 3)
        self.releases['second'].set()
        await self.until(lambda: 'other' in self.started)
        self.assertNotIn('own_lookup', self.started)
        self.releases['first'].set()
        await self.until(lambda: 'own_lookup' in self.started)
        self.assertNotIn('own_add', self.started)
        self.releases['own_lookup'].set()
        await self.until(lambda: 'own_add' in self.started)
        for release in self.releases.values(): release.set()
        await asyncio.gather(*self.tasks)

    async def test_queue_timeout_new_message_and_no_leak(self):
        self.assertEqual(self.host.RESOLVE_QUEUE_TIMEOUT, 15)
        await self.full()
        self.host.RESOLVE_QUEUE_TIMEOUT = .02
        task = self.submit(3, 'expired')
        with self.assertRaises(APIError) as caught: await task
        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(str(caught.exception), message('resolve.queueTimeout'))
        self.assertNotIn('expired', self.started)
        self.assertFalse(self.host.resolution_queue.waiting)
        self.releases['first'].set()
        self.host.RESOLVE_QUEUE_TIMEOUT = 1
        next_task = self.submit(4, 'next')
        await self.until(lambda: 'next' in self.started)
        self.releases['next'].set()
        self.assertEqual(await next_task, 'next')

    async def test_resolution_timeout_and_budget_start_after_queue_wait(self):
        await self.full()
        self.host.RESOLVE_TIMEOUT = .04
        async def delayed():
            self.started.append('delayed')
            self.assertIsNotNone(RESOLUTION_BUDGET.get())
            await asyncio.sleep(.01)
            return 'ok'
        task = self.submit(3,'delayed',operation=delayed())
        await self.until(lambda: len(self.host.resolution_queue.waiting) == 1)
        await asyncio.sleep(.06)  # Longer than provider timeout, less than queue timeout.
        self.assertFalse(task.done())
        self.releases['first'].set()
        self.assertEqual(await task, 'ok')
        timeout = self.submit(4,'timeout')
        self.releases['second'].set()
        with self.assertRaises(APIError) as caught: await timeout
        self.assertEqual(caught.exception.status, 504)

    async def test_queued_cancellation_closes_coroutine_and_frees_queue(self):
        await self.full()
        async def never(): self.fail('cancelled queued operation ran')
        operation = never()
        task = self.submit(3, 'cancelled', operation=operation)
        await self.until(lambda: len(self.host.resolution_queue.waiting) == 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(inspect.getcoroutinestate(operation), inspect.CORO_CLOSED)
        self.assertFalse(self.host.resolution_queue.waiting)
        next_task = self.submit(4,'next')
        self.releases['first'].set()
        await self.until(lambda: 'next' in self.started)
        self.releases['next'].set()
        self.assertEqual(await next_task, 'next')

    async def test_running_repeated_cancellation_holds_slot_until_reap(self):
        reaping, reaped = asyncio.Event(), asyncio.Event()
        async def provider():
            self.started.append('provider')
            try: await asyncio.Event().wait()
            finally:
                reaping.set()
                await reaped.wait()
        running = self.submit(1,'provider',operation=provider())
        self.submit(2,'second')
        await self.until(lambda: len(self.started) == 2)
        third = self.submit(3,'third')
        await self.until(lambda: len(self.host.resolution_queue.waiting) == 1)
        running.cancel(); await reaping.wait(); running.cancel()
        await asyncio.sleep(0)
        self.assertEqual(len(self.host.resolve_tasks), 2)
        self.assertNotIn('third', self.started)
        reaped.set()
        with self.assertRaises(asyncio.CancelledError): await running
        await self.until(lambda: 'third' in self.started)
        self.releases['third'].set()
        self.assertEqual(await third, 'third')

    async def test_same_person_across_guilds_still_has_only_one_active_job(self):
        first = self.submit(1,'first')
        self.guild = NS(id=2)
        second = self.submit(1,'second')
        other = self.submit(2,'other')
        await self.until(lambda: 'other' in self.started)
        self.assertEqual(self.started, ['first','other'])
        self.assertEqual(len(self.host.resolve_tasks), 2)
        self.releases['first'].set()
        await self.until(lambda: 'second' in self.started)
        for event in self.releases.values(): event.set()
        self.assertEqual(await asyncio.gather(first,second,other), ['first','second','other'])

    async def test_cancel_before_execute_first_turn_closes_unstarted_operation(self):
        async def never(): self.fail('unstarted provider ran')
        operation = never()
        # Grant synchronously while deliberately cancelling before the new task
        # can execute its first instruction (the execute() finally cannot run).
        from musicbot.dashboard_backend.resolution_queue import ResolutionJob
        loop = asyncio.get_running_loop()
        job = ResolutionJob(1,1,'',1,loop.time()+15,loop.create_future(),
            operation,contextvars.copy_context(),1,'m0423')
        queue = self.host.resolution_queue
        queue.jobs.append(job);queue.waiting.append(job);queue.dispatch()
        job.task.cancel()
        await asyncio.gather(job.task,return_exceptions=True)
        self.assertEqual(inspect.getcoroutinestate(operation),inspect.CORO_CLOSED)
        self.assertFalse(self.host.resolve_tasks)
        self.assertFalse(queue.jobs)

    async def test_real_http_disconnect_cancels_waiting_request(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        await self.full()
        entered = asyncio.Event()
        async def handler(request):
            entered.set()
            result = await self.host.run_resolution(self.guild, asyncio.sleep(0),
                owner=NS(id=3), request=request)
            return web.json_response({'result':result})
        app = web.Application();app.router.add_post('/resolve',handler)
        async with TestClient(TestServer(app,handler_cancellation=True)) as client:
            pending = asyncio.create_task(client.post('/resolve',json={}))
            await entered.wait()
            await self.until(lambda: len(self.host.resolution_queue.waiting)==1)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError): await pending
            await self.until(lambda: not self.host.resolution_queue.waiting)
            self.assertEqual(len(self.host.resolve_tasks),2)
        next_task=self.submit(4,'next')
        self.releases['first'].set()
        await self.until(lambda: 'next' in self.started)
        self.releases['next'].set()
        self.assertEqual(await next_task,'next')

    async def test_exception_frees_both_slots_and_future_requests_work(self):
        async def explode(): raise RuntimeError('synthetic failure')
        task = self.submit(1,'bad',operation=explode())
        with self.assertRaisesRegex(RuntimeError, 'synthetic failure'): await task
        self.assertFalse(self.host.resolve_tasks)
        good = self.submit(1,'good')
        await self.until(lambda: 'good' in self.started)
        self.releases['good'].set()
        self.assertEqual(await good, 'good')

    async def test_queued_job_retains_its_own_context(self):
        marker = contextvars.ContextVar('request_check', default='none')
        await self.full()
        check = object()
        async def read_context(): return marker.get(), LANGUAGE.get(), CONFIRMED_ENTRY_CHECK.get()
        token = marker.set('own-confirmed-entry-check'); lang = LANGUAGE.set('en')
        confirmed = CONFIRMED_ENTRY_CHECK.set(check)
        try: queued = self.submit(3,'context',operation=read_context())
        finally: marker.reset(token); LANGUAGE.reset(lang); CONFIRMED_ENTRY_CHECK.reset(confirmed)
        await self.until(lambda: len(self.host.resolution_queue.waiting) == 1)
        self.releases['first'].set()
        self.assertEqual(await queued, ('own-confirmed-entry-check','en',check))

    async def test_private_status_only_matches_person_guild_and_request(self):
        request = NS(headers={'X-MusicBot-Request-ID':'abc123'}, query={'request_id':'abc123'})
        self.host.guild_owner = lambda _: (self.guild, NS(id=1))
        task = self.submit(1,'private',request=request)
        await self.until(lambda: 'private' in self.started)
        self.assertEqual(json.loads((await self.host.resolution_status(request)).text), {'state':'resolving'})
        self.host.guild_owner = lambda _: (self.guild, NS(id=99))
        self.assertEqual(json.loads((await self.host.resolution_status(request)).text), {'state':None})
        self.host.guild_owner = lambda _: (NS(id=2), NS(id=1))
        self.assertEqual(json.loads((await self.host.resolution_status(request)).text), {'state':None})
        self.host.guild_owner = lambda _: (self.guild, NS(id=1))
        request.query['request_id']='wrong'
        self.assertEqual(json.loads((await self.host.resolution_status(request)).text), {'state':None})
        self.releases['private'].set(); await task
        request.query['request_id']='abc123'
        self.assertEqual(json.loads((await self.host.resolution_status(request)).text), {'state':None})

    async def test_shutdown_cancels_queued_and_running_without_leaks(self):
        await self.full()
        self.submit(3,'waiting')
        await self.until(lambda: len(self.host.resolution_queue.waiting) == 1)
        await self.host.resolution_queue.close()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.assertFalse(self.host.resolve_tasks)
        self.assertFalse(self.host.resolution_queue.jobs)
        operation = asyncio.sleep(0)
        with self.assertRaises(APIError):
            await self.host.run_resolution(self.guild, operation, owner=NS(id=4))
        self.assertEqual(inspect.getcoroutinestate(operation), inspect.CORO_CLOSED)


class ImportQueueTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = imports.ImportTests.asyncSetUp
    asyncTearDown = imports.ImportTests.asyncTearDown
    call = imports.ImportTests.call
    login_as = imports.ImportTests.login_as
    provider_me = imports.ImportTests.provider_me
    provider_token = imports.ImportTests.provider_token

    async def test_import_preview_uses_the_same_queue_and_private_http_status(self):
        release = asyncio.Event()
        async def blocker(): await release.wait()
        tasks = [asyncio.create_task(self.dashboard.run_resolution(self.bot.guild,
            blocker(), owner=NS(id=uid))) for uid in (700,701)]
        pending = None
        try:
            for _ in range(100):
                if len(self.dashboard.resolve_tasks) == 2: break
                await asyncio.sleep(.001)
            headers={'X-MusicBot-Dashboard':'1','X-MusicBot-Request-ID':'import123'}
            pending = asyncio.create_task(self.call('/api/guilds/1/library/import/preview',
                {'url':imports.YTM}, headers=headers))
            for _ in range(100):
                if self.dashboard.resolution_queue.waiting: break
                await asyncio.sleep(.001)
            self.assertEqual(len(self.dashboard.resolution_queue.waiting), 1)
            status = await self.call('/api/guilds/1/resolution-status?request_id=import123', method='GET')
            self.assertEqual(status, {'state':'queued'})
            self.bot.downloader.extract_info.assert_not_awaited()
            release.set()
            result = await pending
            self.assertIn('preview_id', result)
            self.bot.downloader.extract_info.assert_awaited_once()
            self.assertFalse(self.dashboard.resolution_queue.jobs)
            self.client.session.cookie_jar.clear()
            await self.call('/api/guilds/1/resolution-status?request_id=import123', method='GET', status=401)
        finally:
            release.set()
            if pending: await asyncio.gather(pending, return_exceptions=True)
            await asyncio.gather(*tasks, return_exceptions=True)


class AdditionQueueTests(unittest.IsolatedAsyncioTestCase):
    import test_web_dashboard as fixtures
    asyncSetUp = fixtures.DashboardTests.asyncSetUp
    asyncTearDown = fixtures.DashboardTests.asyncTearDown
    call = fixtures.DashboardTests.call

    async def test_two_people_add_in_same_guild_without_blocking_controls(self):
        from musicbot.downloader import YtdlpResponseDict
        members = {key:NS(**dict(vars(self.bot.owner),id=uid,name='DemoUser'))
                   for key,uid in [('one',101),('two',102)]}
        self.dashboard.guild_owner = lambda request:(self.bot.guild,
            members[request.headers.get('X-Demo-User','one')])
        payloads={}
        for key,owner in members.items():
            item={'kind':'track','title':'Demo track','url':'https://soundcloud.com/example/song','allowed':True}
            await self.dashboard.issue_previews(self.bot.guild,owner,[item],item['url'],'play')
            payloads[key]={'query':item['url'],'preview_id':item['preview_id']}
        started,release=asyncio.Event(),asyncio.Event()
        count=0
        async def slow(*args,**kwargs):
            nonlocal count
            count+=1
            if count==2:started.set()
            await release.wait()
            return YtdlpResponseDict(self.bot.info)
        self.bot.downloader.extract_info=slow
        initial=len(self.bot.player.playlist.entries)
        calls=[asyncio.create_task(self.call('/api/guilds/1/play',payloads[key],
            headers={'X-MusicBot-Dashboard':'1','X-Demo-User':key})) for key in members]
        try:
            await asyncio.wait_for(started.wait(),1)
            self.assertEqual(len(self.dashboard.resolve_tasks),2)
            await asyncio.wait_for(self.call('/api/guilds/1/pause',{}),.2)
            self.assertFalse(self.dashboard.locks[1].locked())
            release.set()
            await asyncio.gather(*calls)
            self.assertEqual(len(self.bot.player.playlist.entries),initial+2)
            self.assertFalse(self.dashboard.resolution_queue.jobs)
        finally:
            release.set()
            await asyncio.gather(*calls,return_exceptions=True)
