"""Offline lyric matching, bounded storage and owner policy regression."""
import asyncio
import json
import math
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import test_web_dashboard as base
import test_web_dashboard_discord as identity
from musicbot.web_dashboard_lyrics import LyricsClient, result
from musicbot.web_dashboard_lyrics_store import LyricsStore, video_id
from test_web_dashboard import BASE

KEY="abcdefghijk"

class StoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="musicbot-webtest-lyrics-")
        self.store=LyricsStore(self.temp.name)
    async def asyncTearDown(self):
        self.temp.cleanup()
    async def test_disk_result_restart_expiry_negative_day_and_no_identity(self):
        value=result("Song","Singer")
        await self.store.put(KEY,value,86400)
        fresh=LyricsStore(self.temp.name)
        self.assertEqual(await fresh.get(KEY),value)
        raw=json.loads(self.store.path("cache",KEY).read_text())
        self.assertGreater(raw["expires"]-time.time(),10790)
        await self.store.put(KEY,value,-1)
        self.assertIsNone(await fresh.get(KEY))
    async def test_bounded_cache_oldest_count_and_bytes_and_corruption(self):
        self.store.CACHE_LIMIT=2
        for key in ("aaaaaaaaaaa","bbbbbbbbbbb","ccccccccccc"):
            await self.store.put(key,{"plain_lyrics":"x"*200},60)
        self.assertFalse(self.store.path("cache","aaaaaaaaaaa").exists())
        self.assertEqual(len(list((self.store.root/"cache").glob("*.json"))),2)
        self.store.MAX_BYTES=100
        await self.store.put(KEY,{"plain_lyrics":"x"*200},60)
        self.assertEqual(list((self.store.root/"cache").glob("*.json")),[])
        path=self.store.path("cache",KEY);path.write_text("broken")
        self.assertIsNone(await self.store.get(KEY))
    async def test_offsets_are_shared_per_guild_and_bounded_manual_priority(self):
        await self.store.set_manual(1,KEY,7.5)
        self.assertEqual(await LyricsStore(self.temp.name).manual(1,KEY),7.5)
        self.assertIsNone(await self.store.manual(2,KEY))
        for value in (-30.1,60.1,True,float("nan"),float("inf"),"7"):
            with self.assertRaises(ValueError):await self.store.set_manual(1,KEY,value)
        await self.store.set_manual(1,KEY,None)
        self.assertIsNone(await self.store.manual(1,KEY))
        for key in ("../x","bad","../../etc"):
            with self.assertRaises(ValueError):self.store.path("cache",key)
    async def test_settings_persist_default_allowed_and_invalid_is_default(self):
        self.assertTrue(await self.store.enabled(1))
        await self.store.set_enabled(1,False)
        self.assertFalse(await LyricsStore(self.temp.name).enabled(1))
        self.assertTrue(await self.store.enabled(2))

class MatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_get_is_validated_and_wrong_match_rejected(self):
        client=LyricsClient();client.MIN_INTERVAL=0
        client._request=AsyncMock(side_effect=lambda session,path,params: {"trackName":"Other Song","artistName":"Other","duration":180,"plainLyrics":"Wrong"} if path == "/get" else [])
        self.assertEqual((await client.lookup("Song","Singer",180))["status"],"not_found")
        self.assertEqual(client._request.await_count,4)
    async def test_instrumental_and_confident_mv_duration_and_multi_candidate(self):
        client=LyricsClient();client.MIN_INTERVAL=0
        client._request=AsyncMock(return_value={"trackName":"Song","artistName":"Singer","duration":180,"instrumental":True})
        self.assertEqual((await client.lookup("Song","Singer",187))["status"],"instrumental")
        right={"trackName":"Song","artistName":"Singer","duration":180,"syncedLyrics":"[00:02]Hello"}
        wrong=dict(right,artistName="Someone else")
        self.assertIs(LyricsClient._choose([wrong,right],"Song","Singer",187),right)
        self.assertIsNone(LyricsClient._choose([right],"Song","Other",187))
        self.assertIsNone(LyricsClient._choose([dict(right,trackName="Song Part Two")],"Song","Singer",187))
        self.assertIsNone(LyricsClient._choose([right],"Song","",187))
    async def test_ambiguous_artists_and_versions_rejected(self):
        a={"trackName":"Song","artistName":"Singer","duration":180,"plainLyrics":"One"}
        b=dict(a,artistName="Singers")
        self.assertIsNone(LyricsClient._choose([a,b],"Song","",180))

class LyricsPolicyTests(unittest.IsolatedAsyncioTestCase):
    provider_token=identity.DiscordTests.provider_token
    provider_me=identity.DiscordTests.provider_me
    call=identity.DiscordTests.call
    login_as=identity.DiscordTests.login_as
    async def asyncSetUp(self):
        await identity.DiscordTests.asyncSetUp(self)
        self.temp=tempfile.TemporaryDirectory(prefix="musicbot-webtest-lyric-api-")
        self.dashboard.lyrics_store.root=Path(self.temp.name)
        self.dashboard.lyrics_client=NS(lookup=AsyncMock(return_value=result("Song","Singer")))
    async def asyncTearDown(self):
        await identity.DiscordTests.asyncTearDown(self);self.temp.cleanup()
    async def test_owner_can_disable_and_member_cannot_query_or_toggle(self):
        await self.call(BASE+"admin/lyrics",{"enabled":False},status=403)
        self.login_as(42)
        self.assertTrue((await self.call(BASE+"admin/lyrics",method="GET"))["enabled"])
        await self.call(BASE+"admin/lyrics",{"enabled":False})
        self.login_as(43)
        await self.call(BASE+"lyrics",method="GET",status=403)
        self.dashboard.lyrics_client.lookup.assert_not_awaited()
        self.login_as(42)
        for value in ({"enabled":1},{"enabled":False,"x":1},{}):
            await self.call(BASE+"admin/lyrics",value,status=400)
    async def test_video_id_cache_stops_provider_after_restart(self):
        self.bot.player.current_entry.url="https://www.youtube.com/watch?v="+KEY
        await self.call(BASE+"lyrics",method="GET")
        self.dashboard.lyrics_client.lookup.assert_awaited_once()
        self.dashboard.lyrics_store=LyricsStore(self.temp.name)
        await self.call(BASE+"lyrics",method="GET")
        self.dashboard.lyrics_client.lookup.assert_awaited_once()

    async def test_shared_manual_adjust_sync_reset_range_and_stale_identity(self):
        entry=self.bot.player.current_entry
        entry.url="https://www.youtube.com/watch?v="+KEY
        token=self.dashboard.track_token(self.bot.player)
        await self.dashboard.lyrics_store.put(KEY,
            {"status":"synced","lines":[{"time":0,"text":""},{"time":5,"text":"First"}]},86400)
        await self.dashboard.lyrics_store.put(KEY,{"offset":13,"source":"matched"},86400,"analysis")
        url=BASE+"lyrics/offset"
        value=await self.call(url,{"action":"set","offset":7,"track_token":token})
        self.assertEqual(value["offset"],7);self.assertEqual(value["offset_source"],"manual")
        self.login_as(42)
        self.assertEqual((await self.call(url,method="GET"))["offset"],7)
        self.login_as(43)
        value=await self.call(url,{"action":"adjust","delta":.5,"track_token":token})
        self.assertEqual(value["offset"],7.5)
        value=await self.call(url,{"action":"sync","position":12.25,"track_token":token})
        self.assertEqual(value["offset"],7.25)
        value=await self.call(url,{"action":"reset","track_token":token})
        self.assertEqual(value["offset"],13);self.assertEqual(value["offset_source"],"matched")
        for value in (-31,61,True,"7",float("nan"),None):
            await self.call(url,{"action":"set","offset":value,"track_token":token},status=400)
        await self.call(url,{"action":"set","offset":7,"track_token":"old"},status=409)
        records=self.dashboard.activity_snapshot(self.bot.guild)["activity"]
        self.assertTrue(any("調整歌詞位移" in row["detail"] for row in records))
