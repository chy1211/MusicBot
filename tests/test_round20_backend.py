"""R20 regressions: run with `python -m unittest tests/test_round20_backend.py`.

No live provider, Discord or network calls. Tests use the genuine module when
run in a complete MusicBot checkout.
"""
import asyncio
import contextvars
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from musicbot.web_dashboard_library import PlaylistStore
from musicbot.web_dashboard_lyrics_store import LyricsStore
from musicbot.web_dashboard_spotify import SpotifyLookup
from musicbot.downloader import guarded_media_subject
from musicbot.exceptions import ExtractionError


class PlaylistTransactions(unittest.IsolatedAsyncioTestCase):
    async def test_disk_write_runs_off_loop_but_authorization_stays_on_loop(self):
        with tempfile.TemporaryDirectory() as root:
            store = PlaylistStore(root)
            main_thread = threading.get_ident()
            worker_thread = []
            authorized_thread = []
            locale = contextvars.ContextVar('r20_locale', default='default')
            copied_context = []
            original = store.read

            def read(uid):
                worker_thread.append(threading.get_ident())
                copied_context.append(locale.get())
                return original(uid)

            with patch.object(store, 'read', side_effect=read):
                token = locale.set('request-context')
                try:
                    await store.transact(42, authorize=lambda: authorized_thread.append(threading.get_ident()))
                finally:
                    locale.reset(token)
            self.assertEqual(authorized_thread, [main_thread])
            self.assertEqual(copied_context, ['request-context'])
            self.assertTrue(worker_thread)
            self.assertNotEqual(worker_thread[0], main_thread)

    async def test_slow_fsync_does_not_block_other_coroutines(self):
        with tempfile.TemporaryDirectory() as root:
            store = PlaylistStore(root)
            from musicbot import web_dashboard_library as module
            writing, release = threading.Event(), threading.Event()
            original = module.atomic_write

            def blocked_write(path, content):
                writing.set()
                if not release.wait(2):
                    raise TimeoutError('test worker not released')
                return original(path, content)

            with patch.object(module, 'atomic_write', side_effect=blocked_write):
                task = asyncio.create_task(store.transact(42, lambda value: None))
                try:
                    self.assertTrue(await asyncio.wait_for(asyncio.to_thread(writing.wait, 1), 1.5))
                    tick = asyncio.create_task(asyncio.sleep(0))
                    await asyncio.wait_for(tick, 0.15)
                    self.assertFalse(task.done())
                finally:
                    release.set()
                await asyncio.wait_for(task, 2)

    async def test_cancelled_request_keeps_lock_until_worker_finished(self):
        with tempfile.TemporaryDirectory() as root:
            store = PlaylistStore(root)
            from musicbot import web_dashboard_library as module
            writing, release = threading.Event(), threading.Event()
            original = module.atomic_write
            def held_write(path, content):
                writing.set()
                if not release.wait(2):
                    raise TimeoutError('test worker not released')
                return original(path, content)
            def add_a(value):
                value['playlists'].append({'id':'a'*24, 'name':'A', 'tracks':[]})
            def add_b(value):
                value['playlists'].append({'id':'b'*24, 'name':'B', 'tracks':[]})
            with patch.object(module, 'atomic_write', side_effect=held_write):
                first = asyncio.create_task(store.transact(42, add_a))
                self.assertTrue(await asyncio.to_thread(writing.wait, 1))
                first.cancel()
                second = asyncio.create_task(store.transact(42, add_b))
                try:
                    await asyncio.sleep(0)
                    self.assertFalse(second.done())
                finally:
                    release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await first
                await asyncio.wait_for(second, 2)
            self.assertEqual(len((await store.transact(42))['playlists']), 3)

    async def test_revision_conflict_under_concurrent_writes(self):
        with tempfile.TemporaryDirectory() as root:
            store = PlaylistStore(root)
            initial = await store.transact(42)
            revision = initial['revision']
            def add(value):
                value['playlists'].append({'id': 'a' * 24, 'name': 'Test', 'tracks': []})
            completed = await asyncio.gather(
                store.transact(42, add, revision),
                store.transact(42, add, revision),
                return_exceptions=True,
            )
            self.assertEqual(sum(isinstance(x, dict) for x in completed), 1)
            self.assertEqual(sum(isinstance(x, Exception) for x in completed), 1)
            final = await store.transact(42)
            self.assertEqual(len(final['playlists']), 2)


class NativeUrlSafety(unittest.TestCase):
    def test_rejects_internal_and_unsupported_urls_before_extraction(self):
        for subject in ('http://127.0.0.1:8080/private',
                        'http://[::1]/',
                        'http://localhost/admin',
                        'http://169.254.169.254/latest/meta-data',
                        'https://example.com/untrusted',
                        'ftp://internal.example/private'):
            with self.subTest(subject=subject):
                with self.assertRaises(ExtractionError):
                    guarded_media_subject(subject)

    def test_preserves_search_and_known_media(self):
        self.assertEqual(guarded_media_subject('ytsearch1:Artist Song'),
                         'ytsearch1:Artist Song')
        self.assertEqual(guarded_media_subject('Some Artist - Song'),
                         'Some Artist - Song')
        value = 'https://www.youtube.com/watch?v=FoufxW6WE4U'
        self.assertEqual(guarded_media_subject(value), value)


class LyricsPrune(unittest.IsolatedAsyncioTestCase):
    async def test_prune_does_not_run_after_every_write(self):
        with tempfile.TemporaryDirectory() as root:
            store = LyricsStore(root)
            with patch.object(store, 'prune', wraps=store.prune) as prune:
                for index in range(18):
                    await store.put(f'{index:011d}', {'status': 'plain', 'plain_lyrics': 'Test'}, 600)
                self.assertEqual(prune.call_count, 2)

    async def test_manual_prune_remains_available(self):
        with tempfile.TemporaryDirectory() as root:
            store = LyricsStore(root)
            await store.put('00000000001', {'status': 'plain', 'plain_lyrics': 'Test'}, 600)
            await asyncio.to_thread(store.prune)
            self.assertIsNotNone(await store.get('00000000001'))


class SpotifyCandidates(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def track(name, artist, id, duration=180000):
        return {'name':name,'artists':[{'name':artist}], 'duration_ms':duration,
                'external_urls':{'spotify':f'https://open.spotify.com/track/{id}'}}

    async def test_second_candidate_used_when_first_is_wrong(self):
        songs = [self.track('Different', 'Someone', 'a'), self.track('Song', 'Artist', 'b')]
        class Provider:
            async def make_api_req(self, path):
                assert 'limit=5' in path
                return {'tracks': {'items': songs}}
        value = await SpotifyLookup().search(Provider(), 'Song', 'Artist', 180,
                                            ('song','artist',180), {'mode':'search','query':'Song'})
        self.assertEqual(value['url'], 'https://open.spotify.com/track/b')

    async def test_ambiguous_identical_candidates_fall_back(self):
        songs = [self.track('Song', 'Artist', 'a'), self.track('Song','Artist','b')]
        class Provider:
            async def make_api_req(self, path):
                return {'tracks':{'items':songs}}
        fallback={'mode':'search','query':'Song'}
        value=await SpotifyLookup().search(Provider(),'Song','Artist',180,('song','artist',180),fallback)
        self.assertEqual(value, fallback)


if __name__ == '__main__':
    unittest.main()
