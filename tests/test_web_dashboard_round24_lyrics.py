"""Offline retries and failure isolation. Local fake provider only."""
import asyncio
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
from aiohttp import web, ClientConnectionError
from aiohttp.test_utils import TestServer
from musicbot.web_dashboard_lyrics import LyricsClient, result
from musicbot.web_dashboard_lyrics_store import LyricsStore

class ReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_503_then_success_and_retry_after_does_not_block_other_song(self):
        calls = []
        async def provider(request):
            song = request.query.get("q")
            calls.append(song)
            if song == "Retry" and calls.count(song) == 1:
                return web.Response(status=503, headers={"Retry-After": "0"})
            if song == "Blocked":
                return web.Response(status=429, headers={"Retry-After": "60"})
            return web.json_response([{"trackName":song,"duration":180,"plainLyrics":"First line"}])
        app = web.Application(); app.router.add_get("/api/search", provider)
        async with TestServer(app) as server:
            with patch("musicbot.web_dashboard_lyrics.LRCLIB_ROOT", str(server.make_url("/api"))):
                client = LyricsClient(); client.MIN_INTERVAL = 0
                self.assertEqual((await client.lookup("Retry","",180))["status"], "plain")
                self.assertEqual(calls.count("Retry"), 2)
                self.assertEqual((await client.lookup("Blocked","",180))["status"], "unavailable")
                start = time.monotonic()
                self.assertEqual((await client.lookup("Healthy","",180))["status"], "plain")
                self.assertLess(time.monotonic()-start, 1)
                client.cache.clear()
                await client.lookup("Blocked","",180)
                self.assertEqual(calls.count("Blocked"), 1)

    async def test_timeout_empty_and_partial_failure_are_distinct(self):
        client = LyricsClient(); client.TIMEOUT = .01
        async def slow(*args): await asyncio.sleep(.1)
        client._request = slow
        self.assertEqual((await client.lookup("Slow","",180))["status"], "unavailable")
        client._request = AsyncMock(return_value=[])
        self.assertEqual((await client.lookup("Missing","",180))["status"], "not_found")
        client._request = AsyncMock(side_effect=[ClientConnectionError(), []])
        self.assertEqual((await client.lookup("Partial","Artist",180))["status"], "unavailable")

    async def test_store_never_persists_unavailable_and_bounds_negative_ttl(self):
        with tempfile.TemporaryDirectory() as root:
            store = LyricsStore(root)
            await store.put("abcdefghijk", result("Song","",status="unavailable"), 600)
            self.assertFalse(store.path("cache","abcdefghijk").exists())
            await store.put("abcdefghijk", result("Song",""), 86400)
            raw = store.read(store.path("cache","abcdefghijk"))
            self.assertLessEqual(raw["expires"] - time.time(), 10800)

    def test_retry_after_date_and_invalid_values(self):
        self.assertEqual(LyricsClient._retry_delay("0"), 0)
        self.assertIsNone(LyricsClient._retry_delay("bad"))
        self.assertIsNone(LyricsClient._retry_delay("nan"))
        self.assertGreater(LyricsClient._retry_delay("Thu, 01 Jan 2099 00:00:00 GMT"), 1)
