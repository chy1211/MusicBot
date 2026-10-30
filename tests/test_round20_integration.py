"""R20 adversarial boundaries against genuine modules, with offline providers."""
import asyncio
import tempfile
import threading
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from musicbot.downloader import Downloader, guarded_media_subject
from musicbot.exceptions import ExtractionError
from musicbot.web_dashboard_library import PlaylistStore
from musicbot.web_dashboard_lyrics_store import LyricsStore
from musicbot.web_dashboard_spotify import SpotifyLookup

class NativePreflightTests(unittest.IsolatedAsyncioTestCase):
    async def test_unsafe_keyword_url_never_reaches_provider(self):
        provider=Mock(return_value={})
        fake=NS(bot=NS(loop=asyncio.get_running_loop()),unsafe_ytdl=NS(extract_info=provider))
        with patch('musicbot.downloader.log'):
            with self.assertRaises(ExtractionError):
                await Downloader.safe_extract_info(fake,url='http://127.0.0.1/private')
        provider.assert_not_called()

    async def test_supported_provider_url_and_search_forms_remain_available(self):
        urls=['https://www.youtube.com/watch?v=abcdefghijk',
              'https://open.spotify.com/track/0123456789ABCDEFGHIJKL',
              'https://soundcloud.com/example-artist/example-song',
              'https://example-artist.bandcamp.com/track/example-song']
        for url in urls:self.assertTrue(guarded_media_subject(url).startswith('https://'))
        for query in ['ytsearch1:Song https://example.test/reference','Artist - Song','Song with https://example.test/reference',
                      'spotify:track:0123456789ABCDEFGHIJKL']:
            self.assertEqual(guarded_media_subject(query),query)

    async def test_scheme_tricks_and_shorthand_internal_urls_are_rejected(self):
        for value in ['http:127.0.0.1/private','data:text/plain,secret','javascript:alert(1)',
                      '127.0.0.1:8080/private','[::1]/private','localhost/private','service.internal/private','www.example.test/untrusted']:
            with self.subTest(value=value),self.assertRaises(ExtractionError):guarded_media_subject(value)

class CapacityTests(unittest.IsolatedAsyncioTestCase):
    async def test_count_pressure_prunes_before_periodic_threshold(self):
        with tempfile.TemporaryDirectory() as root:
            store=LyricsStore(root);store.CACHE_LIMIT=2
            for index in range(6):
                await store.put(f'{index:011d}',{'status':'plain','plain_lyrics':'text'},60)
                self.assertLessEqual(len(list(store.root.rglob('*.json'))),2)

    async def test_byte_pressure_prunes_before_sixteen_writes(self):
        with tempfile.TemporaryDirectory() as root:
            store=LyricsStore(root);store.MAX_BYTES=500
            for index in range(5):
                await store.put(f'{index:011d}',{'status':'plain','plain_lyrics':'x'*200},60)
                self.assertLessEqual(sum(f.stat().st_size for f in store.root.rglob('*.json')),500)

class SpotifyCandidateTests(unittest.IsolatedAsyncioTestCase):
    def row(self,title='Long Original Song',identity='good',**kwargs):
        return dict({'name':title,'artists':[{'name':'Singer'}],'duration_ms':180000,
                     'external_urls':{'spotify':'https://open.spotify.com/track/'+identity}},**kwargs)
    async def search(self,rows,title='Long Original Song'):
        client=NS(make_api_req=Mock())
        async def api(_):return {'tracks':{'items':rows}}
        client.make_api_req=api
        return await SpotifyLookup().search(client,title,'Singer',180,('key',),{'mode':'search','query':'fixture'})
    async def test_malformed_first_rows_do_not_hide_valid_later_candidate(self):
        value=await self.search([self.row(artists=None),self.row(external_urls=None),self.row()])
        self.assertEqual(value['mode'],'track')
    async def test_duplicate_identity_is_not_an_ambiguous_recording(self):
        value=await self.search([self.row(),self.row()]);self.assertEqual(value['mode'],'track')
    async def test_live_suffix_is_rejected_even_with_high_title_similarity(self):
        title='A Very Long Original Song Name With Many Words To Keep Similarity High '*2
        value=await self.search([self.row(title+' (Live)')],title)
        self.assertEqual(value['mode'],'search')

class TransactionIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_different_user_can_finish_while_first_user_worker_is_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            store=PlaylistStore(root);original=store._transact_on_worker
            entered,release=threading.Event(),threading.Event()
            def worker(uid,*args):
                if uid==42:
                    entered.set()
                    if not release.wait(2):raise TimeoutError('unreleased test worker')
                return original(uid,*args)
            with patch.object(store,'_transact_on_worker',side_effect=worker):
                first=asyncio.create_task(store.transact(42))
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait,1))
                    value=await asyncio.wait_for(store.transact(43),.5)
                    self.assertIn('revision',value);self.assertFalse(first.done())
                finally:release.set()
                await first

    async def test_repeated_cancellation_keeps_same_user_lock_until_worker_finishes(self):
        with tempfile.TemporaryDirectory() as root:
            store=PlaylistStore(root);original=store._transact_on_worker
            entered,release=threading.Event(),threading.Event();calls=[]
            def worker(uid,*args):
                calls.append(uid)
                if len(calls)==1:
                    entered.set()
                    if not release.wait(2):raise TimeoutError('unreleased test worker')
                return original(uid,*args)
            with patch.object(store,'_transact_on_worker',side_effect=worker):
                first=asyncio.create_task(store.transact(42))
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait,1));first.cancel()
                    await asyncio.sleep(0);first.cancel()
                    second=asyncio.create_task(store.transact(42));await asyncio.sleep(.02)
                    self.assertEqual(calls,[42]);self.assertFalse(second.done())
                finally:release.set()
                with self.assertRaises(asyncio.CancelledError):await first
                await second
