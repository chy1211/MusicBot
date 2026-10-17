import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
from musicbot.web_dashboard_spotify import SpotifyLookup,metadata
import test_web_dashboard_discord as fixtures
from test_web_dashboard import entry,BASE

class LookupTests(unittest.IsolatedAsyncioTestCase):
    def bot(self):
        return NS(config=NS(spotify_enabled=True),spotify=NS(make_api_req=AsyncMock(return_value={"tracks":{"items":[{
            "name":"Song","artists":[{"name":"Singer"}],"duration_ms":180000,"external_urls":{"spotify":"https://open.spotify.com/track/abc123"}}]}})))
    async def test_native_track_direct_without_search(self):
        bot=self.bot();song=entry();song.info={"__input_subject":"https://open.spotify.com/track/native123?si=a"}
        value=await SpotifyLookup().lookup(bot,song)
        self.assertEqual(value["url"],"https://open.spotify.com/track/native123")
        bot.spotify.make_api_req.assert_not_awaited()
    async def test_title_cleanup_match_and_one_hour_cache(self):
        bot=self.bot();song=entry("Singer - Song (Official Video) 【Lyrics】")
        lookup=SpotifyLookup();self.assertEqual(metadata(song),("Song","Singer"))
        value=await lookup.lookup(bot,song);self.assertEqual(value["mode"],"track")
        self.assertEqual(await lookup.lookup(bot,song),value)
        bot.spotify.make_api_req.assert_awaited_once()
    async def test_low_confidence_unconfigured_and_failure_cooldown_fallback(self):
        bot=self.bot();song=entry("Other - Different MV")
        lookup=SpotifyLookup()
        value=await lookup.lookup(bot,song);self.assertEqual(value["mode"],"search")
        bot.config.spotify_enabled=False
        self.assertIn("/search/",(await SpotifyLookup().lookup(bot,song))["url"])
        bot.config.spotify_enabled=True;bot.spotify.make_api_req.side_effect=RuntimeError("secret")
        lookup=SpotifyLookup()
        self.assertEqual((await lookup.lookup(bot,entry("Singer - Song")))["mode"],"search")
        count=bot.spotify.make_api_req.await_count
        await lookup.lookup(bot,entry("Singer - Another Song"))
        self.assertEqual(bot.spotify.make_api_req.await_count,count)

    async def test_timeout_malformed_and_concurrent_cache(self):
        bot=self.bot(); song=entry("Singer - Song")
        lookup=SpotifyLookup()
        values=await asyncio.gather(*(lookup.lookup(bot,song) for _ in range(5)))
        self.assertTrue(all(value["mode"]=="track" for value in values))
        bot.spotify.make_api_req.assert_awaited_once()
        bot.spotify.make_api_req.return_value={"tracks":None}
        self.assertEqual((await SpotifyLookup().lookup(bot,song))["mode"],"search")
        async def timeout(coro, seconds):
            self.assertEqual(seconds,8);coro.close();raise asyncio.TimeoutError()
        with patch("musicbot.web_dashboard_spotify.asyncio.wait_for",side_effect=timeout):
            self.assertEqual((await SpotifyLookup().lookup(bot,song))["mode"],"search")
        with patch("musicbot.web_dashboard_spotify.time.monotonic",return_value=100):
            lookup=SpotifyLookup();bot=self.bot()
            await lookup.lookup(bot,song)
            self.assertEqual(next(iter(lookup.cache.values()))[0],3700)

class LookupAPITests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.DiscordTests.asyncSetUp
    asyncTearDown=fixtures.DiscordTests.asyncTearDown
    call=fixtures.DiscordTests.call
    login_as=fixtures.DiscordTests.login_as
    provider_token=fixtures.DiscordTests.provider_token
    provider_me=fixtures.DiscordTests.provider_me
    async def test_member_auth_and_rate_limit(self):
        for _ in range(12):
            value=await self.call(BASE+"spotify",method="GET")
            self.assertEqual(value["mode"],"search")
        await self.call(BASE+"spotify",method="GET",status=429)
        self.bot.guild.get_member=lambda uid:None
        await self.call(BASE+"spotify",method="GET",status=403)


    async def test_protection_and_no_internal_errors(self):
        await self.call(BASE+"spotify",method="GET",headers={},status=403)
        await self.call(BASE+"spotify",method="GET",headers={"X-MusicBot-Dashboard":"1","Origin":"https://evil.test"},status=403)
        self.bot.config.spotify_enabled=True
        self.bot.spotify=NS(make_api_req=AsyncMock(side_effect=RuntimeError("PRIVATE_ERROR")))
        value=await self.call(BASE+"spotify",method="GET")
        self.assertNotIn("PRIVATE_ERROR",str(value))
        await self.call("/auth/logout",{})
        await self.call(BASE+"spotify",method="GET",status=401)
