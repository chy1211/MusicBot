"""Member-guarded popularity API and the native enqueue observer, offline."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
import test_web_dashboard as base
from test_web_dashboard import BASE, entry
from musicbot.bot import MusicBot
from musicbot.web_dashboard_stats import PopularityStore

class PopularAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await base.DashboardTests.asyncSetUp(self)
        self.temp = tempfile.TemporaryDirectory(prefix="musicbot-webtest-stats-api-")
        self.dashboard.popularity_store = PopularityStore(Path(self.temp.name), flush_interval=0)
    async def asyncTearDown(self):
        await base.DashboardTests.asyncTearDown(self)
        self.temp.cleanup()
    call = base.DashboardTests.call

    async def test_native_entry_added_counts_batch_once_and_not_autoplay(self):
        self.bot._web_dashboard = self.dashboard
        self.bot.config.auto_playlist_autoskip = False
        self.bot.serialize_queue = AsyncMock()
        requested = entry("Requested", author=self.bot.owner, channel=self.bot.channel)
        for song in (requested, requested, entry("Another", author=self.bot.owner, channel=self.bot.channel), entry("Autoplay")):
            await MusicBot.on_player_entry_added(self.bot, self.bot.player, self.bot.player.playlist, song)
        value = await self.call(BASE+"popular?period=7", method="GET")
        self.assertEqual(sum(t["count"] for t in value["tracks"]),2)
        self.assertNotIn("owner",str(value).lower())
        self.assertEqual(set(value),{"period","tracks"})

    async def test_observer_failure_does_not_break_existing_queue_serialization(self):
        self.bot._web_dashboard=self.dashboard
        self.bot.config.auto_playlist_autoskip=False
        self.bot.serialize_queue=AsyncMock()
        song=entry("Requested",author=self.bot.owner,channel=self.bot.channel)
        with patch.object(self.dashboard.popularity_store,"record",side_effect=OSError("private")):
            await MusicBot.on_player_entry_added(self.bot,self.bot.player,self.bot.player.playlist,song)
        self.bot.serialize_queue.assert_awaited_once_with(self.bot.guild)

    async def test_period_validation_and_membership_guard(self):
        await self.call(BASE+"popular?period=180",method="GET",status=400)
        for period in ("7","30","all"):
            self.assertEqual((await self.call(BASE+"popular?period="+period,method="GET"))["period"],period)
        self.bot.guild.get_member=lambda uid:None
        await self.call(BASE+"popular",method="GET",status=403)

    async def test_stats_disk_error_returns_chinese_without_raw_details(self):
        with patch.object(self.dashboard.popularity_store,"top",side_effect=OSError("/private/path user 42")):
            value=await self.call(BASE+"popular",method="GET",status=503)
        self.assertNotIn("private",str(value))
