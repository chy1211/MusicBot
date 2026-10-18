"""Offline retries and failure isolation. Local fake provider only."""
import asyncio
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
from aiohttp import web, ClientConnectionError
from aiohttp.test_utils import TestServer
from musicbot.web_dashboard_lyrics import LyricsClient, result, clean_metadata, metadata
from musicbot.web_dashboard_lyrics_store import LyricsStore

class ReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_503_then_success_and_retry_after_does_not_block_other_song(self):
        calls = []
        async def provider(request):
            song = request.query.get("track_name") or request.query.get("q")
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
        async def partial(session, path, params):
            if path == "/get": raise ClientConnectionError()
            return []
        client._request = partial
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


class MetadataTests(unittest.TestCase):
    def test_title_formats_and_channel_cleanup(self):
        cases = [
            ("歌手《歌名》","歌手",("歌名","歌手")),
            ("Singer - Song【Official Music Video】","Singer",("Song","Singer")),
            ("歌手〈歌名〉","",("歌名","歌手")),
            ("歌手『歌名』Official Music Video","歌手",("歌名","歌手")),
            ("ハチ MV「マトリョシカ」HACHI / MATORYOSHKA","Kenshi Yonezu 米津玄師",("マトリョシカ","ハチ")),
            ("溫蒂漫步 Wendy Wander【你怎麼捨得我難過 How can you allow …】","滾石唱片 ROCK RECORDS",("你怎麼捨得我難過","溫蒂漫步 Wendy Wander")),
            ("美秀集團 Amazing Show－愛情的大壞蛋 Bastards of Love","美秀集團 Amazing Show",("愛情的大壞蛋","美秀集團 Amazing Show")),
            ("Singer - Song (Official MV)","SingerVEVO",("Song","Singer")),
            ("歌手｜歌名","歌手",("歌名","歌手")),
            ("少女レイ / 星街すいせい(Cover)","Suisei Channel",("少女レイ","星街すいせい")),
            ("Singer — Song","Singer - Topic",("Song","Singer")),
            ("Song","Label Records",("Song","")),
            ("Song","Singer Official Channel",("Song","Singer")),
            ("Song (Remix)","Singer",("Song (Remix)","Singer")),
            ("浴室 (DJ锦先森 ProgHouse Remix)","Deca joins",("浴室 (DJ锦先森 ProgHouse Remix)","Deca joins")),
            ("氣息","溫蒂漫步, 俞曾妮, 俞曾妮",("氣息","溫蒂漫步")),
            ("🧠 :: 歌手『歌名』","歌手",("歌名","歌手")),
            ("Official髭男dism - Pretender (Official Video)","Official髭男dism",("Pretender","Official髭男dism")),
        ]
        for title,artist,expected in cases:
            with self.subTest(title=title): self.assertEqual(clean_metadata(title,artist),expected)
        self.assertEqual(metadata("Song","Singer, Guest, Guest")["artists"],["Singer","Guest"])

    def test_similar_titles_versions_and_artistless_safety(self):
        row={"trackName":"Somewhere Only We Know","artistName":"Keane","duration":237,"plainLyrics":"First"}
        self.assertIsNone(LyricsClient._choose([row],"Somewhere Only You Know","Keane",237))
        self.assertIsNone(LyricsClient._choose([dict(row,artistName="Keanes")],"Somewhere Only We Know","Keane",237))
        self.assertIsNone(LyricsClient._choose([dict(row,plainLyrics="probe")],"Somewhere Only We Know","Keane",237))
        self.assertIsNone(LyricsClient._choose([row],"Somewhere Only We Know (Remix)","Keane",237))
        self.assertIsNone(LyricsClient._choose([row],"Somewhere Only We Know","",250))
        self.assertIsNone(LyricsClient._choose([row],"Somewhere Only We Know","",0))
        self.assertIs(LyricsClient._choose([row],"Somewhere Only We Know","Keane",290),row)
        self.assertIsNone(LyricsClient._choose([row,dict(row,artistName="Another")],"Somewhere Only We Know","",237))

class StrategyTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_structured_search_can_rescue_failed_get(self):
        client=LyricsClient()
        started=asyncio.Event()
        async def request(session,path,params):
            if path=="/get":
                await asyncio.wait_for(started.wait(),.1)
                raise ClientConnectionError()
            started.set()
            return [{"trackName":"Song","artistName":"Singer","duration":180,"plainLyrics":"First"}]
        client._request=request
        self.assertEqual((await client.lookup("Song","Singer",180))["status"],"plain")

    async def test_cover_original_is_labelled_only_with_close_duration(self):
        async def request(session,path,params):
            return None if path=="/get" else [{"trackName":"Song","artistName":"Original","duration":180,"plainLyrics":"First"}]
        for duration,status in ((180,"plain"),(190,"not_found"),(0,"not_found")):
            client=LyricsClient();client._request=request
            value=await client.lookup("Song / Cover Singer (Cover)","Cover Singer Channel",duration)
            self.assertEqual(value["status"],status)
            self.assertEqual(value.get("match"),"cover_original" if status=="plain" else None)

    async def test_secondary_artist_and_title_only_search_keep_identity_checks(self):
        calls=[]
        async def request(session,path,params):
            calls.append((path,params))
            if path=="/get": return None
            return [{"trackName":"Song","artistName":"Guest","duration":180,"plainLyrics":"First"}]
        client=LyricsClient();client._request=request
        self.assertEqual((await client.lookup("Song","Singer, Guest, Guest",180))["status"],"plain")


class RecordedFixtureTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_34_songs_replay_offline_with_recorded_results(self):
        from tools.evaluate_lyrics_round24 import evaluate
        from pathlib import Path
        import json
        value=await evaluate()
        expected=json.loads((Path(__file__).parent/"fixtures/lyrics_round24_expected.json").read_text())
        self.assertEqual(value,expected)
        self.assertEqual(len(value["songs"]),34)
        self.assertLessEqual(value["http_calls"],150)

    async def test_connection_error_retries_are_bounded(self):
        class Session:
            def __init__(self): self.calls=0
            def get(self,*args,**kwargs):
                self.calls+=1
                raise ClientConnectionError()
        session=Session(); client=LyricsClient();client.MIN_INTERVAL=0
        with patch("asyncio.sleep",new=AsyncMock()):
            with self.assertRaises(ClientConnectionError):
                await client._request(session,"/search",{"track_name":"Song"})
        self.assertEqual(session.calls,3)


class LegacyStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_negative_day_is_expired_after_three_hours(self):
        import json,os
        with tempfile.TemporaryDirectory() as root:
            store=LyricsStore(root);path=store.path("cache","abcdefghijk")
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"expires":time.time()+86400,"value":result("Song","")}))
            os.utime(path,(time.time()-10801,time.time()-10801))
            self.assertIsNone(await store.get("abcdefghijk"))


class BilingualStrategyTests(unittest.IsolatedAsyncioTestCase):
    async def test_english_translation_is_a_known_artist_alias_candidate(self):
        async def request(session,path,params):
            return None if path=="/get" else [{"trackName":"English Title","artistName":"Singer","duration":180,"plainLyrics":"A first lyric line"}]
        client=LyricsClient();client._request=request
        self.assertEqual((await client.lookup("Singer【中文歌名 English Title】","Singer",180))["status"],"plain")

    async def test_translation_search_is_attempted_after_primary_exhaustion(self):
        calls=[]
        async def request(session,path,params):
            calls.append(params)
            if path=="/get":return None
            return [{"trackName":"English Title","artistName":"Singer","duration":180,"plainLyrics":"A first lyric line"}] if params.get("track_name")=="English Title" else []
        client=LyricsClient();client._request=request
        self.assertEqual((await client.lookup("Singer【中文歌名 English Title】","Singer",180))["status"],"plain")
        self.assertIn({"track_name":"English Title","artist_name":"Singer"},calls)


class FastSuccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_get_is_not_lost_to_slow_parallel_search(self):
        cancelled=asyncio.Event()
        async def request(session,path,params):
            if path=="/get":
                return {"trackName":"Song","artistName":"Singer","duration":180,"plainLyrics":"A valid first lyric line"}
            try: await asyncio.sleep(1)
            finally: cancelled.set()
        client=LyricsClient();client.TIMEOUT=.05;client._request=request
        self.assertEqual((await client.lookup("Song","Singer",180))["status"],"plain")
        self.assertTrue(cancelled.is_set())
        self.assertEqual(client.pending,{})
