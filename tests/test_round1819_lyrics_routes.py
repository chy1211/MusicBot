"""Real synthetic HTTP routes; no Spotify/LRCLIB/YouTube traffic."""
import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import test_web_dashboard_round12_lyrics as original
from musicbot.web_dashboard_lyrics import result
from musicbot.web_dashboard_lyrics_alignment import AlignmentService

class LyricsRouteTests(unittest.IsolatedAsyncioTestCase):
    provider_token=original.LyricsPolicyTests.provider_token
    provider_me=original.LyricsPolicyTests.provider_me
    call=original.LyricsPolicyTests.call
    login_as=original.LyricsPolicyTests.login_as
    asyncSetUp=original.LyricsPolicyTests.asyncSetUp
    asyncTearDown=original.LyricsPolicyTests.asyncTearDown

    async def test_video_cache_hit_skips_spotify_and_lrclib(self):
        self.bot.player.current_entry.url='https://www.youtube.com/watch?v='+original.KEY
        cached=result('Cached Song','Singer',{'plainLyrics':'cached lyrics','duration':180})
        await self.dashboard.lyrics_store.put(original.KEY,cached,3600)
        self.dashboard.spotify_lookup.lookup=AsyncMock(side_effect=AssertionError('cache hit must skip Spotify'))
        value=await self.call(original.BASE+'lyrics',method='GET')
        self.assertEqual(value['plain_lyrics'],'cached lyrics')
        self.dashboard.spotify_lookup.lookup.assert_not_awaited()
        self.dashboard.lyrics_client.lookup.assert_not_awaited()

    async def test_manual_query_skips_spotify_but_still_uses_lyrics_provider(self):
        self.dashboard.spotify_lookup.lookup=AsyncMock(side_effect=AssertionError('manual metadata'))
        await self.call(original.BASE+'lyrics?query=Fixture',method='GET')
        self.dashboard.spotify_lookup.lookup.assert_not_awaited()
        self.assertEqual(self.dashboard.lyrics_client.lookup.await_args.kwargs['query'],'Fixture')

    async def test_spotify_timeout_falls_back_without_cancelling_lyrics_lookup(self):
        self.dashboard.spotify_lookup.lookup=AsyncMock()
        real_wait_for=asyncio.wait_for;timeouts=[]
        async def timed(coro,timeout):
            if timeout!=3.0:return await real_wait_for(coro,timeout)
            timeouts.append(timeout);coro.close();raise asyncio.TimeoutError
        with patch('musicbot.dashboard_backend.lyrics.asyncio.wait_for',side_effect=timed):
            await self.call(original.BASE+'lyrics',method='GET')
        self.assertIn(3.0,timeouts)
        self.dashboard.lyrics_client.lookup.assert_awaited_once()

class LegacyAlignmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_duration_guess_is_downgraded_once(self):
        class Store:
            value={'offset':0.0,'source':'duration','confidence':1.0}
            def __init__(self):self.writes=[]
            async def get(self,*args):return self.value
            async def put(self,key,value,ttl,kind):self.writes.append((ttl,kind));self.value=value
        store=Store();service=AlignmentService(store)
        entry=NS(url='https://www.youtube.com/watch?v=abcdefghijk',duration=180)
        for _ in range(2):
            value=await service.request(NS(),entry,{'duration':180})
            self.assertEqual(value['source'],'duration_assumed');self.assertEqual(value['confidence'],.25)
        self.assertEqual(store.writes,[(3600,'analysis')])
