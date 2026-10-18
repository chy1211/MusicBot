"""Offline web extraction security regressions; never contact a provider."""
import asyncio
import socket
import unittest
from unittest.mock import patch, Mock

from yt_dlp.extractor.common import InfoExtractor
from musicbot.web_dashboard_extraction import (
    WEB_EXTRACTION, DashboardYoutubeDL, UnsupportedDashboardURL, normalize_query,
)
import test_web_dashboard as fixtures
from test_web_dashboard import BASE

# These are test-only addresses, not deployment/network discovery targets.
UNSAFE = (
    'http://127.0.0.1/song', 'http://localhost/song', 'http://10.1.2.3/song',
    'http://172.16.0.1/song', 'http://192.168.1.1/song',
    'http://169.254.169.254/latest/meta-data/', 'http://100.64.0.1/song',
    'http://224.0.0.1/song', 'http://240.0.0.1/song', 'http://0.0.0.0/song',
    'http://[::1]/song', 'http://[fc00::1]/song', 'http://[fe80::1]/song',
    'http://[::ffff:127.0.0.1]/song', 'http://2130706433/song',
    'https://media.example/song.mp3', 'https://rebind.example/song',
)


class FakeServiceIE(InfoExtractor):
    IE_NAME = 'security-test-service'
    _VALID_URL = r'https://video\.example/(?P<id>[a-z]+)'
    target = None

    def _real_extract(self, url):
        if self.target:
            return {'_type': 'url', 'url': self.target, 'ie_key': 'Generic'}
        return {'id': 'song', 'title': 'Public song', 'url': 'https://cdn.example/song.mp3',
                'ext': 'mp3'}


class ExtractionPolicyTests(unittest.TestCase):
    def test_non_public_and_generic_inputs_never_resolve_dns(self):
        # Simulated rebinding resolver: first public answer, then loopback.
        resolver = Mock(side_effect=[[(socket.AF_INET, 1, 6, '', ('203.0.113.10', 80))],
                                    [(socket.AF_INET, 1, 6, '', ('127.0.0.1', 80))]])
        with patch('socket.getaddrinfo', resolver):
            for url in UNSAFE:
                with self.subTest(url=url), self.assertRaises(UnsupportedDashboardURL):
                    normalize_query(url)
        resolver.assert_not_called()

    def test_normalize_known_services_without_network(self):
        for url in ('https://www.youtube.com/watch?v=abc12345678',
                    'https://music.youtube.com/watch?v=abc12345678',
                    'https://youtu.be/abc12345678',
                    'https://open.spotify.com/track/1234567890',
                    'https://soundcloud.com/example/song',
                    'https://artist.bandcamp.com/track/song'):
            with self.subTest(url=url):
                self.assertEqual(normalize_query(url), url)
        self.assertEqual(normalize_query(' <HTTPS://SOUNDCLOUD.COM/example/song#t=3> '),
                         'https://soundcloud.com/example/song')
        self.assertEqual(normalize_query('music.youtube.com/watch?v=abc12345678'),
                         'https://music.youtube.com/watch?v=abc12345678')

    def test_credentials_schemes_ports_and_host_spoofing(self):
        for url in ('https://soundcloud.com@localhost/song', 'file:///etc/passwd',
                    'https://soundcloud.com:9000/example/song',
                    'https://soundcloud.com.evil.example/example/song',
                    'https://soundcloud.com\\@localhost/song', 'https://[::1/song'):
            with self.subTest(url=url), self.assertRaises(UnsupportedDashboardURL):
                normalize_query(url)

    def test_generic_redirect_to_internal_never_makes_initial_request(self):
        # A generic redirect endpoint is rejected before GET, HEAD or download.
        with patch.object(DashboardYoutubeDL, 'urlopen', side_effect=AssertionError('network')) as network:
            with DashboardYoutubeDL({'quiet': True}) as client:
                for download in (False, True):
                    with self.assertRaises(UnsupportedDashboardURL):
                        client.extract_info('https://redirect.example/to-private', download=download)
                self.assertNotIn('Generic', client._ies)
        network.assert_not_called()

    def test_dedicated_nested_generic_redirect_is_denied(self):
        for target in UNSAFE:
            with self.subTest(target=target), patch(
                    'musicbot.web_dashboard_extraction.dedicated_extractors', return_value=(FakeServiceIE,)):
                with DashboardYoutubeDL({'quiet': True}) as client:
                    fake = FakeServiceIE(); fake.target = target
                    client.add_info_extractor(fake)
                    with patch.object(client, 'urlopen', side_effect=AssertionError('network')) as network:
                        with self.assertRaises(UnsupportedDashboardURL):
                            client.extract_info('https://video.example/redirect', download=False)
                        network.assert_not_called()

    def test_normal_public_service_extracts_with_mock(self):
        with patch('musicbot.web_dashboard_extraction.dedicated_extractors', return_value=(FakeServiceIE,)):
            with DashboardYoutubeDL({'quiet': True}) as client:
                client.add_info_extractor(FakeServiceIE())
                with patch.object(client, 'urlopen', side_effect=AssertionError('network')):
                    info = client.extract_info('https://video.example/song', download=False)
                self.assertEqual(info['title'], 'Public song')

    def test_native_discord_runner_keeps_original_client_and_generic(self):
        from musicbot.downloader import Downloader
        client = Mock()
        owner = Mock(); owner._cookie_clients.snapshot.return_value = (client, client)
        token = WEB_EXTRACTION.set(False)
        try:
            Downloader._run_ytdl(owner, False, 'extract_info', 'https://generic.example/song')
        finally:
            WEB_EXTRACTION.reset(token)
        client.extract_info.assert_called_once_with('https://generic.example/song')


class WebEntrySecurityTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.DashboardTests.asyncSetUp
    asyncTearDown = fixtures.DashboardTests.asyncTearDown
    call = fixtures.DashboardTests.call

    async def test_resolve_and_unconfirmed_play_reject_generic_before_downloader(self):
        for action in ('resolve', 'play', 'playnext'):
            for url in UNSAFE:
                with self.subTest(action=action, url=url):
                    result = await self.call(BASE + action, {'query': url}, status=400)
                    self.assertTrue(result['error'])
        self.assertFalse(self.bot.extractions)
        self.bot.get_player.assert_not_awaited()

    async def test_errors_are_localized(self):
        for language, expected in [('en', 'not supported'), ('zh-TW', '\u4e0d\u652f\u63f4')]:
            result = await self.call(BASE + 'resolve', {'query': UNSAFE[0]}, status=400,
                headers={'X-MusicBot-Dashboard': '1', 'X-Dashboard-Language': language})
            self.assertIn(expected, result['error'])

    async def test_web_context_is_scoped_and_normal_public_resolution_works(self):
        seen = []
        original = self.bot.downloader.extract_info
        async def extract(*args, **kwargs):
            seen.append(WEB_EXTRACTION.get())
            return await original(*args, **kwargs)
        self.bot.downloader.extract_info = extract
        await self.call(BASE + 'resolve', {'query': 'https://soundcloud.com/example/song'})
        await self.call(BASE + 'play', {'query': 'https://soundcloud.com/example/song'})
        self.assertEqual(seen, [True, True, True])
        self.assertFalse(WEB_EXTRACTION.get())


import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from aiohttp import web
from aiohttp.test_utils import TestServer
from yt_dlp.networking.common import Response
from musicbot.web_dashboard_extraction import (
    BudgetResponse, ExtractionBudget, ExtractionBudgetExceeded, RESOLUTION_BUDGET,
    run_extraction_process, bounded_json,
)
from musicbot.web_dashboard import DashboardConfig
from musicbot.downloader import YtdlpResponseDict


class ReadBudgetTests(unittest.TestCase):
    def response(self, data, budget, headers=None):
        return BudgetResponse(Response(io.BytesIO(data), 'https://video.example/song', headers or {}), budget)

    def test_content_length_rejected_before_read(self):
        source = Response(io.BytesIO(b'x'), 'https://video.example/song', {'Content-Length': '101'})
        with self.assertRaises(ExtractionBudgetExceeded):
            BudgetResponse(source, ExtractionBudget(max_response=100))
        self.assertTrue(source.closed)

    def test_chunked_unbounded_read_stops_at_limit_plus_one(self):
        budget = ExtractionBudget(max_response=100, max_total=1000)
        response = self.response(b'x' * 10000, budget)
        with self.assertRaises(ExtractionBudgetExceeded):
            response.read()
        self.assertEqual(budget.used, 101)
        self.assertTrue(response.closed)

    def test_total_is_shared_across_responses(self):
        budget = ExtractionBudget(max_response=100, max_total=150)
        with self.response(b'x' * 100, budget) as first:
            self.assertEqual(len(first.read()), 100)
        with self.response(b'y' * 100, budget) as second:
            with self.assertRaises(ExtractionBudgetExceeded):
                second.read()
        self.assertEqual(budget.used, 151)

    def test_partial_reads_iteration_and_decoded_bytes(self):
        budget = ExtractionBudget(max_response=100)
        with self.response(b'hello\nworld', budget, {'Content-Encoding': 'gzip'}) as response:
            self.assertEqual(response.read(3), b'hel')
            self.assertEqual(response.readline(), b'lo\n')
            self.assertEqual(response.read(), b'world')
        self.assertEqual(budget.used, 11)

    def test_config_defaults_custom_limits_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'example.ini'
            prefix = '[WebDashboard]\nEnabled=yes\n'
            path.write_text(prefix)
            config = DashboardConfig.load(path)
            self.assertEqual((config.resolve_timeout_seconds, config.resolve_max_response_bytes,
                config.resolve_max_total_bytes), (20, 8388608, 33554432))
            path.write_text(prefix + 'ResolveTimeoutSeconds=9\nResolveMaxResponseBytes=4096\nResolveMaxTotalBytes=8192\n')
            self.assertEqual(DashboardConfig.load(path).resolve_timeout_seconds, 9)
            for invalid in ('ResolveTimeoutSeconds=nan', 'ResolveTimeoutSeconds=0',
                            'ResolveTimeoutSeconds=121', 'ResolveMaxResponseBytes=0',
                            'ResolveMaxTotalBytes=1024'):
                path.write_text(prefix + invalid + '\n')
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    DashboardConfig.load(path)


class ProcessBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_worker_success_with_mock_provider_and_startup_cost(self):
        # Same module/IPC as deployment, with the provider method replaced in the
        # child process. No internet, credentials, config or external services.
        code = """
from yt_dlp.extractor.youtube import YoutubeIE
def fake(self, url):
    assert any(c.name == 'test_cookie' and c.value == 'fake_value' for c in self._downloader.cookiejar)
    return {'id':'abc12345678','title':'Public song','url':'https://cdn.example/song.mp3','ext':'mp3'}
YoutubeIE._real_extract = fake
from musicbot.web_dashboard_extract_worker import main
main()
"""
        budget = ExtractionBudget(timeout=5)
        started = time.monotonic()
        info = await run_extraction_process({'subject':'https://www.youtube.com/watch?v=abc12345678',
            'options':{}, 'kwargs':{'download':False}, 'limits':[5,8388608,33554432],
            'cookies':[dict(version=0,name='test_cookie',value='fake_value',port=None,
                port_specified=False,domain='.youtube.com',domain_specified=True,
                domain_initial_dot=True,path='/',path_specified=True,secure=True,
                expires=None,discard=True,comment=None,comment_url=None,rest={},rfc2109=False)]}, budget,
            command=[sys.executable, '-c', code])
        elapsed = time.monotonic() - started
        self.assertEqual(info['title'], 'Public song')
        self.assertLess(elapsed, 2.0)
        print('Mock provider worker startup + extraction: %.3fs' % elapsed)

    async def test_worker_metadata_output_is_bounded_and_reaped(self):
        with self.assertRaises(ExtractionBudgetExceeded):
            await run_extraction_process({}, ExtractionBudget(timeout=5, max_response=100),
                command=[sys.executable, '-c', "import sys;sys.stdin.read();sys.stdout.write('x'*100000);sys.stdout.flush()"])

    async def test_cancellation_kills_worker_and_child_before_return(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'pids'
            code = "import os,subprocess,sys,time; child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);open(sys.argv[1],'w').write(str(os.getpid())+' '+str(child.pid));time.sleep(60)"
            task = asyncio.create_task(run_extraction_process({}, ExtractionBudget(timeout=5),
                command=[sys.executable, '-c', code, str(path)]))
            for _ in range(100):
                if path.exists(): break
                await asyncio.sleep(.01)
            self.assertTrue(path.exists())
            pids = path.read_text().split()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            for pid in pids:
                proc = Path('/proc') / pid / 'stat'
                self.assertTrue(not proc.exists() or proc.read_text().split()[2] == 'Z')

    async def test_async_spotify_read_budget_and_native_behavior(self):
        async def body(_):
            return web.Response(body=b'"' + b'x' * 5000 + b'"')
        app = web.Application(); app.router.add_get('/', body)
        async with TestServer(app) as server:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                token = WEB_EXTRACTION.set(True)
                budget_token = RESOLUTION_BUDGET.set(ExtractionBudget(max_response=100))
                try:
                    async with session.get(server.make_url('/')) as response:
                        with self.assertRaises(ExtractionBudgetExceeded):
                            await bounded_json(response)
                finally:
                    RESOLUTION_BUDGET.reset(budget_token); WEB_EXTRACTION.reset(token)


class HardDeadlineEntryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.DashboardTests.asyncSetUp
    asyncTearDown = fixtures.DashboardTests.asyncTearDown
    call = fixtures.DashboardTests.call

    async def test_slow_local_source_is_killed_and_both_entries_release_slot(self):
        # The only real HTTP contact is this test container's own fake service.
        started = asyncio.Event()
        async def slow(request):
            response = web.StreamResponse(); await response.prepare(request)
            started.set()
            try:
                while True:
                    await response.write(b'x'); await asyncio.sleep(.02)
            except (ConnectionError, asyncio.CancelledError):
                pass
            return response
        app = web.Application(); app.router.add_get('/', slow)
        with tempfile.TemporaryDirectory() as folder:
            pidfile = Path(folder) / 'pid'
            async with TestServer(app) as server:
                code = "import os,sys,urllib.request;open(sys.argv[1],'w').write(str(os.getpid()));urllib.request.urlopen(sys.argv[2]).read()"
                async def extract(*args, **kwargs):
                    await run_extraction_process({}, RESOLUTION_BUDGET.get(),
                        command=[sys.executable, '-c', code, str(pidfile), str(server.make_url('/'))])
                from types import MethodType
                from musicbot.bot import MusicBot
                self.bot.cmd_playnext = MethodType(MusicBot.cmd_playnext, self.bot)
                self.bot.downloader.extract_info = extract
                self.dashboard.RESOLVE_TIMEOUT = .5
                for action in ('resolve', 'play', 'playnext'):
                    started.clear()
                    await self.call(BASE + action, {'query':'https://soundcloud.com/example/song'}, status=504)
                    self.assertTrue(started.is_set())
                    pid = int(pidfile.read_text())
                    with self.assertRaises(ProcessLookupError): os.kill(pid, 0)
                    self.assertFalse(self.dashboard.resolve_tasks)
                self.bot.downloader.extract_info = self.bot.extract
                await self.call(BASE + 'resolve', {'query':'https://soundcloud.com/example/song'})

    async def test_slot_is_retained_until_cancellation_cleanup_finishes(self):
        entered, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def extract(*args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup.set()
                await release.wait()
        self.bot.downloader.extract_info = extract
        self.dashboard.RESOLVE_TIMEOUT = .03
        task = asyncio.create_task(self.call(BASE + 'resolve', {'query':'song'}, status=504))
        await entered.wait(); await cleanup.wait()
        await self.call(BASE + 'resolve', {'query':'next'}, status=429)
        self.assertFalse(task.done())
        release.set(); await task
        self.assertFalse(self.dashboard.resolve_tasks)


class WarmWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_warm_workers_reuse_success_and_replace_timeout_without_blocking_next_job(self):
        from musicbot.web_dashboard_extraction import DashboardExtractionPool
        import musicbot.web_dashboard_extraction as module
        code = """
import time
from yt_dlp.extractor.youtube import YoutubeIE
def fake(self, url):
    if 'slow0000000' in url: time.sleep(60)
    return {'id':'abc12345678','title':'Public song','url':'https://cdn.example/song.mp3','ext':'mp3'}
YoutubeIE._real_extract = fake
from musicbot.web_dashboard_extract_worker import main
main()
"""
        real_spawn = asyncio.create_subprocess_exec
        async def spawn(*args, **kwargs):
            return await real_spawn(sys.executable, '-c', code, '--serve', **kwargs)
        pool = DashboardExtractionPool()
        job = {'subject':'https://www.youtube.com/watch?v=abc12345678',
               'options':{}, 'kwargs':{'download':False}, 'limits':[5,8388608,33554432]}
        with patch.object(module.asyncio, 'create_subprocess_exec', side_effect=spawn):
            try:
                await pool.start()
                original_pids = {p.pid for p in pool.workers}
                started = time.monotonic()
                for _ in range(3):
                    info = await pool.run(job, ExtractionBudget(timeout=5))
                    self.assertEqual(info['title'], 'Public song')
                overhead = (time.monotonic() - started) / 3
                print('Warm mock provider extraction mean: %.3fs' % overhead)
                self.assertLess(overhead, 1.0)
                self.assertEqual(original_pids, {p.pid for p in pool.workers})
                with self.assertRaises(asyncio.TimeoutError):
                    await pool.run(dict(job, subject='https://www.youtube.com/watch?v=slow0000000'),
                                   ExtractionBudget(timeout=.1))
                killed = original_pids - {p.pid for p in pool.workers}
                self.assertEqual(len(killed), 1)
                for pid in killed:
                    with self.assertRaises(ProcessLookupError): os.kill(pid, 0)
                self.assertEqual((await pool.run(job, ExtractionBudget(timeout=5)))['title'], 'Public song')
            finally:
                await pool.close()
        self.assertFalse(pool.workers)
        self.assertFalse(pool.replacements)


class WorkerRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_import_payload_excludes_normal_client_and_credentials(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from musicbot.downloader import Downloader
        from musicbot.web_dashboard_extraction import WEB_POOL
        pool = SimpleNamespace(run=AsyncMock(return_value={'title':'Public'}))
        token = WEB_POOL.set(pool)
        try:
            # No ordinary client/bot/cookie attributes exist: touching one fails.
            await Downloader._dashboard_extract(SimpleNamespace(),
                'https://www.youtube.com/playlist?list=PLdemo',
                {'download':False,'process':False}, public=True, limit=25)
        finally:
            WEB_POOL.reset(token)
        payload, budget = pool.run.call_args.args
        self.assertEqual(payload['cookies'], [])
        self.assertEqual(payload['limit'], 25)
        self.assertNotIn('http_headers', payload['options'])
        self.assertNotIn('cookiefile', payload['options'])
        self.assertNotIn('usenetrc', payload['options'])


class PlaybackContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_media_download_does_not_inherit_web_parse_deadline(self):
        from types import SimpleNamespace
        from musicbot.entry import BasePlaylistEntry
        from musicbot.web_dashboard_extraction import WEB_POOL
        seen = []
        async def download():
            seen.append((WEB_EXTRACTION.get(), RESOLUTION_BUDGET.get(), WEB_POOL.get()))
            for future in entry._waiting_futures:
                future.set_result('ready')
        entry = SimpleNamespace(is_downloaded=False, _waiting_futures=[], _task_pool=set(),
                                _download=download)
        token = WEB_EXTRACTION.set(True)
        budget_token = RESOLUTION_BUDGET.set(ExtractionBudget(timeout=.001))
        pool_token = WEB_POOL.set(object())
        try:
            self.assertEqual(await BasePlaylistEntry.get_ready_future(entry), 'ready')
            self.assertEqual(seen, [(False, None, None)])
            self.assertTrue(WEB_EXTRACTION.get())
        finally:
            WEB_POOL.reset(pool_token)
            RESOLUTION_BUDGET.reset(budget_token)
            WEB_EXTRACTION.reset(token)
