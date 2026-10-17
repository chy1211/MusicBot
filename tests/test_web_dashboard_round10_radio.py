"""Offline radio tests: native finish hook, fake Mix/playlist and temporary JSON."""
import asyncio
import json
import logging
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import test_web_dashboard as base
import test_web_dashboard_discord as identity
from musicbot.bot import MusicBot
from musicbot.downloader import YtdlpResponseDict
from musicbot.web_dashboard import requester
from musicbot.web_dashboard_radio import RadioService, EmptyQueueStore, DEFAULT, is_radio
from musicbot.web_dashboard_stats import PopularityStore
from test_web_dashboard import BASE

logging.Logger.everything = logging.Logger.debug
logging.Logger.noise = logging.Logger.debug


def mix(items=None):
    return YtdlpResponseDict({"_type":"playlist","entries":items if items is not None else [
        {"id":f"track{i:06d}","url":f"https://youtu.be/track{i:06d}",
         "title":f"Song {i}","duration":180} for i in range(8)]})


class RadioTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="musicbot-webtest-radio-")
        self.bot=base.FakeBot()
        self.bot.loop=asyncio.get_running_loop()
        self.bot.config.leave_after_queue_empty=False
        self.bot.config.delete_nowplaying=False
        self.bot.config.auto_playlist=True
        self.bot.config.auto_playlist_random=False
        self.player=self.bot.player
        self.player.current_entry=None
        self.player.playlist.entries.clear()
        self.player.voice_client.guild=self.bot.guild
        self.player.voice_client.is_connected=lambda:True
        self.player.is_dead=False
        self.player.autoplaylist=[]
        self.player.play=Mock()
        self.bot.server_data[1]=NS(current_playing_url="",last_np_msg=None,
            autoplaylist=["https://www.youtube.com/watch?v=legacy00001"])
        self.bot.downloader.extract_public_playlist=AsyncMock(return_value=mix())
        self.bot.downloader.extract_info=AsyncMock(return_value=YtdlpResponseDict({
            "title":"Legacy","url":"https://www.youtube.com/watch?v=legacy00001",
            "webpage_url":"https://www.youtube.com/watch?v=legacy00001","duration":180,"extractor":"youtube"}))
        async def add(info,*,author,channel,**kwargs):
            song=NS(title=info.title,url=info.webpage_url,duration=info.duration,info=info,
                author=author,channel=channel,from_auto_playlist=author is None and channel is None)
            self.player.playlist.entries.append(song)
            return song,len(self.player.playlist.entries)
        self.player.playlist.add_entry_from_info=add
        self.service=self.bot._dashboard_radio=RadioService(self.bot,Path(self.temp.name)/"settings")
        self.seed=base.entry(author=self.bot.owner);self.seed.url="https://www.youtube.com/watch?v=seed0000001"
        await self.service.remember(self.bot.guild,self.seed)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def mode(self,value="radio",low=0,high=0):
        return await self.service.store.put(self.bot.guild,dict(empty_queue=value,
            radio_min_seconds=low,radio_max_seconds=high))

    async def finish(self):
        await MusicBot.on_player_finished_playing(self.bot,self.player)

    async def test_missing_default_is_identical_legacy_flow(self):
        self.assertEqual(await self.service.store.get(self.bot.guild),DEFAULT)
        await self.finish()
        self.bot.downloader.extract_public_playlist.assert_not_awaited()
        self.bot.downloader.extract_info.assert_awaited_once()
        self.assertEqual([e.title for e in self.player.playlist.entries],["Legacy"])
        self.assertFalse(self.service.store.root.exists())

    async def test_radio_adds_three_and_skips_legacy_stats_and_names_radio(self):
        await self.mode(low=60,high=300)
        await self.finish()
        rows=list(self.player.playlist.entries)
        self.assertEqual(len(rows),3)
        self.bot.downloader.extract_public_playlist.assert_awaited_once_with(
            "https://www.youtube.com/watch?v=seed0000001&list=RDseed0000001")
        self.bot.downloader.extract_info.assert_not_awaited()
        store=PopularityStore(Path(self.temp.name)/"stats",flush_interval=0)
        for song in rows:
            self.assertTrue(song.from_auto_playlist)
            self.assertTrue(is_radio(song))
            self.assertEqual(requester(song)["name"],"電台")
            self.assertFalse(await store.record(self.bot.guild,song))
        self.assertEqual(await store.top(self.bot.guild),[])
        await store.close()
        self.player.play.assert_called_once_with(_continue=True)

    async def test_recent_fifty_seek_dedup_duration_and_blocklist_filter(self):
        await self.mode(low=60,high=300)
        for i in range(51):
            song=base.entry();song.url=f"https://www.youtube.com/watch?v=track{i:06d}"
            await self.service.remember(self.bot.guild,song)
            await self.service.remember(self.bot.guild,song)
        self.assertEqual(len(self.service.recent[1]),50)
        self.bot.blocked={"Blocked"}
        items=[{"id":"track000000","title":"Old outside 50","duration":180},
               {"id":"track000001","title":"Recent","duration":180},
               {"id":"fresh000001","title":"Short","duration":59},
               {"id":"fresh000002","title":"Long","duration":301},
               {"id":"fresh000003","title":"Unknown"},
               {"id":"fresh000004","title":"Blocked","duration":180},
               {"id":"fresh000005","title":"Good","duration":60},
               {"id":"fresh000005","title":"Duplicate","duration":60},
               {"id":"fresh000006","title":"Good 2","duration":300}]
        self.bot.downloader.extract_public_playlist.return_value=mix(items)
        await self.finish()
        self.assertCountEqual([e.title for e in self.player.playlist.entries],["Old outside 50","Good","Good 2"])

    async def test_off_matches_disabled_autoplay_without_global_mutation(self):
        await self.mode("off")
        await self.finish()
        self.assertTrue(self.bot.config.auto_playlist)
        self.bot.downloader.extract_info.assert_not_awaited()
        self.bot.downloader.extract_public_playlist.assert_not_awaited()
        self.player.play.assert_not_called()

    async def test_failure_and_hook_exception_fall_back(self):
        await self.mode()
        self.bot.downloader.extract_public_playlist.side_effect=RuntimeError("PRIVATE_PROVIDER")
        with self.assertLogs("musicbot.web_dashboard_radio",level="WARNING") as logs:
            await self.finish()
        self.assertNotIn("PRIVATE_PROVIDER"," ".join(logs.output))
        self.assertEqual([e.title for e in self.player.playlist.entries],["Legacy"])
        self.player.playlist.entries.clear();self.player.autoplaylist=[]
        with patch.object(self.service,"fill",side_effect=RuntimeError("PRIVATE_HOOK")):
            await self.finish()
        self.assertEqual(self.bot.downloader.extract_info.await_count,2)

    async def test_three_failures_pause_ten_minutes_then_recover(self):
        settings=await self.mode()
        self.bot.downloader.extract_public_playlist.side_effect=RuntimeError()
        for _ in range(3):
            self.assertFalse(await self.service.fill(self.player,settings))
        self.assertEqual(self.service.failures[1],3)
        self.assertGreater(self.service.suspended[1]-time.monotonic(),599)
        self.assertFalse(await self.service.fill(self.player,settings))
        self.assertEqual(self.bot.downloader.extract_public_playlist.await_count,3)
        self.service.suspended[1]=time.monotonic()-1
        self.bot.downloader.extract_public_playlist.side_effect=None
        self.assertTrue(await self.service.fill(self.player,settings))
        self.assertEqual(self.service.failures[1],0)

    async def test_native_fallback_is_coalesced_for_concurrent_finish_events(self):
        await self.mode()
        entered,release=asyncio.Event(),asyncio.Event()
        async def failing(_url):
            entered.set();await release.wait();raise RuntimeError()
        self.bot.downloader.extract_public_playlist.side_effect=failing
        first=asyncio.create_task(self.finish())
        await entered.wait()
        await self.finish()
        release.set();await first
        self.assertEqual(self.bot.downloader.extract_info.await_count,1)
        self.assertEqual(len(self.player.playlist.entries),1)

    async def test_new_user_queue_or_off_change_during_lookup_wins(self):
        await self.mode()
        async def changed(_url):
            await self.mode("off");return mix()
        self.bot.downloader.extract_public_playlist.side_effect=changed
        await self.finish()
        self.assertFalse(self.player.playlist.entries)
        self.bot.downloader.extract_info.assert_not_awaited()
        await self.mode()
        async def queued(_url):
            self.player.playlist.entries.append(base.entry("User request"));return mix()
        self.bot.downloader.extract_public_playlist.side_effect=queued
        await self.finish()
        self.assertEqual([e.title for e in self.player.playlist.entries],["User request"])

    async def test_no_seed_empty_mix_and_twenty_second_timeout(self):
        settings=await self.mode()
        self.service.seeds.clear()
        self.assertFalse(await self.service.fill(self.player,settings))
        self.bot.downloader.extract_public_playlist.assert_not_awaited()
        self.service.seeds[1].append({"url":self.seed.url,"title":self.seed.title})
        self.bot.downloader.extract_public_playlist.return_value=mix([])
        self.assertFalse(await self.service.fill(self.player,settings))
        async def timeout(coro,seconds):
            self.assertEqual(seconds,20);coro.close();raise asyncio.TimeoutError()
        with patch("musicbot.web_dashboard_radio.asyncio.wait_for",side_effect=timeout):
            self.assertFalse(await self.service.fill(self.player,settings))

    async def test_corrupt_settings_fallback_without_overwrite(self):
        path=self.service.store.path(self.bot.guild);path.parent.mkdir()
        path.write_text("broken")
        self.assertEqual(await self.service.store.get(self.bot.guild),DEFAULT)
        self.assertEqual(path.read_text(),"broken")


class RadioAPITests(unittest.IsolatedAsyncioTestCase):
    provider_token=identity.DiscordTests.provider_token
    provider_me=identity.DiscordTests.provider_me
    call=identity.DiscordTests.call
    login_as=identity.DiscordTests.login_as
    async def asyncSetUp(self):
        await identity.DiscordTests.asyncSetUp(self)
        self.temp=tempfile.TemporaryDirectory(prefix="musicbot-webtest-radio-api-")
        self.dashboard.radio_service.store.root=Path(self.temp.name)/"settings"
    async def asyncTearDown(self):
        await identity.DiscordTests.asyncTearDown(self)
        self.temp.cleanup()
    async def test_owner_only_validation_and_atomic_persistence(self):
        url=BASE+"admin/empty-queue"
        await self.call(url,method="GET",status=403)
        await self.call(url,dict(DEFAULT),status=403)
        self.login_as(42)
        self.assertEqual((await self.call(url,method="GET"))["empty_queue"],"autoplaylist")
        data=dict(DEFAULT,empty_queue="radio",radio_min_seconds=60,radio_max_seconds=600)
        self.assertEqual((await self.call(url,data))["empty_queue"],"radio")
        path=self.dashboard.radio_service.store.path(self.bot.guild)
        self.assertEqual(json.loads(path.read_text()),data)
        self.assertEqual(list(path.parent.iterdir()),[path])
        for bad in (dict(data,empty_queue="bad"),dict(data,radio_max_seconds=30),
                    dict(data,radio_min_seconds=True),{"empty_queue":"off"},dict(data,extra="x")):
            await self.call(url,bad,status=400)
        await self.call(url,dict(data,empty_queue="off"),headers={},status=403)
        self.assertEqual(json.loads(path.read_text()),data)
