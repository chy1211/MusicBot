"""Round 9 offline regression tests for core dashboard behavior."""
import unittest
from types import SimpleNamespace as NS
from musicbot.bot import MusicBot
from musicbot.player import MusicPlayer, MusicPlayerState
from test_web_dashboard import entry
from unittest.mock import AsyncMock, patch

import test_web_dashboard as base
from test_web_dashboard import BASE
from test_web_dashboard_round5 import seek_entry


class SeekRoundingTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = base.DashboardTests.asyncSetUp
    asyncTearDown = base.DashboardTests.asyncTearDown
    call = base.DashboardTests.call

    async def test_seek_half_up_reports_exact_integer_in_response_and_activity(self):
        for position, rounded in ((83.456, 83), (82.5, 83), (0.49, 0), (179.5, 180)):
            current = seek_entry(self.bot)
            await self.call(BASE + "seek", {"position": position})
            self.assertEqual(current.start_time, rounded)
            activity = self.dashboard.activities[1][0]
            self.assertEqual(activity["detail"], f"\u8df3\u8f49\uff1a{rounded} \u79d2")


class HistoryDedupTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = base.DashboardTests.asyncSetUp
    asyncTearDown = base.DashboardTests.asyncTearDown
    call = base.DashboardTests.call

    async def play_event(self, current):
        class StopAfterObserver(Exception):
            pass
        self.bot._web_dashboard = self.dashboard
        self.bot._handle_guild_auto_pause = AsyncMock(side_effect=StopAfterObserver)
        with self.assertRaises(StopAfterObserver):
            await MusicBot.on_player_play(self.bot, self.bot.player, current)

    async def test_real_seek_requeues_same_entry_but_play_event_records_once(self):
        current = seek_entry(self.bot)
        await self.play_event(current)
        await self.call(BASE + "seek", {"position": 83.456})
        self.assertIs(self.bot.player.playlist.entries[0], current)
        await self.play_event(current)
        await self.play_event(current)
        self.assertEqual(len(self.dashboard.recent_history[1]), 1)

    async def test_entry_identity_guard_outlives_short_duplicate_window(self):
        current = entry("Same")
        self.dashboard.record_play(self.bot.guild, current, played_at=1000)
        self.dashboard.record_play(self.bot.guild, current, played_at=2000)
        self.assertEqual(len(self.dashboard.recent_history[1]), 1)

    async def test_reconstructed_same_url_within_ten_seconds_then_new_request(self):
        for timestamp in (1000, 1001, 1009, 1010):
            self.dashboard.record_play(self.bot.guild, entry("Same"), played_at=timestamp)
        self.assertEqual([row["played_at"] for row in self.dashboard.recent_history[1]], [1010, 1000])

    async def test_resume_uses_distinct_event_and_does_not_create_history(self):
        current = entry("Same")
        self.dashboard.record_play(self.bot.guild, current)
        emitted = []
        # Exercise the native resume boundary without Discord or FFmpeg.
        player = NS(guild_or_net_unavailable=False, is_paused=True,
                    _current_player=NS(resume=lambda: None), current_entry=current,
                    emit=lambda name, **kwargs: emitted.append((name, kwargs)),
                    state=MusicPlayerState.PAUSED)
        with patch("musicbot.player.log.noise", create=True):
            MusicPlayer.resume(player)
        self.assertEqual([name for name, kwargs in emitted], ["resume"])
        self.assertEqual(len(self.dashboard.recent_history[1]), 1)

    async def test_loaded_guild_history_urls_do_not_duplicate_observed_track(self):
        class Loaded(list):
            loaded = True
        self.bot.config.enable_queue_history_guilds = True
        self.bot.playlist_mgr = NS(_playlists={"history-1": Loaded(["https://example.test/Same"] * 3)})
        self.dashboard.record_play(self.bot.guild, entry("Same"))
        self.assertEqual(len(self.dashboard.history_snapshot(self.bot.guild)["history"]), 1)
