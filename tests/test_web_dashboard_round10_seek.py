"""Exercise native seek transitions without audio, Discord, or network."""
import asyncio
import logging
logging.Logger.noise = logging.Logger.debug
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from musicbot.bot import MusicBot
from musicbot.player import MusicPlayer, MusicPlayerState, SourcePlaybackCounter
from musicbot.playlist import Playlist
import test_web_dashboard as base
from test_web_dashboard import BASE, entry
from test_web_dashboard_round5 import seek_entry

class SeekTimeTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = base.DashboardTests.asyncSetUp
    asyncTearDown = base.DashboardTests.asyncTearDown
    call = base.DashboardTests.call

    async def prepare(self, paused=False):
        self.bot.player = base.FakePlayer(self.bot, self.bot.channel)
        current = seek_entry(self.bot)
        self.bot.config.default_volume = .15
        self.bot.config.save_videos = True
        self.bot.loop = asyncio.get_running_loop()
        from collections import defaultdict
        self.bot.player.playlist._events = defaultdict(list)
        self.bot.player.playlist.entries.clear()
        self.bot.player.playlist.entries.extend([entry('One'), entry('Two')])
        voice = NS(channel=self.bot.channel, stop=lambda: None)
        native = MusicPlayer(self.bot, voice, self.bot.player.playlist)
        # These state/ETA tests simulate the replacement source below.
        # Scheduling/cleanup is exercised with real tasks in patch2_races.
        native.play = Mock()
        self.bot.player = native
        native._current_entry = current
        native._source = SourcePlaybackCounter(NS(cleanup=lambda: None), start_time=20)
        native._source._num_reads = 500
        native.state = MusicPlayerState.PAUSED if paused else MusicPlayerState.PLAYING
        return native, current

    async def test_web_and_discord_forward_backward_and_paused_seek_use_new_position(self):
        for web in (True, False):
            for paused in (False, True):
                for target in (10, 100):
                    player, current = await self.prepare(paused)
                    before = list(player.playlist.entries)
                    if web:
                        body = await self.call(BASE + "seek", {"position": target})
                    else:
                        await MusicBot.cmd_seek(self.bot, None, self.bot.guild, player, [], str(target))
                        body = {"state": self.dashboard.snapshot(self.bot.guild, self.bot.owner)}
                    view = body["state"]
                    self.assertEqual(view["progress"], target)
                    self.assertEqual(view["status"], "paused" if paused else "playing")
                    self.assertEqual(len(view["queue"]), len(before))
                    # Queue time must count remaining audio exactly once.
                    self.assertEqual(view["queue"][0]["title"], before[0].title)
                    self.assertEqual((await Playlist.estimate_time_until(player.playlist, 1, player)).total_seconds(), 180-target)
                    # Simulate audio source restart: full duration stays unchanged.
                    player._source = SourcePlaybackCounter(NS(cleanup=lambda: None), start_time=target)
                    player._pending_seek = None
                    self.assertEqual(player.progress, target)
                    self.assertEqual(current.duration, 180)
                    self.bot.player = player

    async def test_seek_does_not_duplicate_current_entry_with_repeat_modes(self):
        for mode in ("song", "all", "off"):
            player, current = await self.prepare()
            player.repeatsong, player.loopqueue = mode == "song", mode == "all"
            await MusicBot.cmd_seek(self.bot, None, self.bot.guild, player, [], "100")
            with patch("musicbot.player.log.noise", create=True):
                player._playback_finished()
            self.assertEqual(sum(item is current for item in player.playlist.entries), 1)

    async def test_pause_resume_counter_and_native_remaining_time(self):
        player, current = await self.prepare()
        player._source = SourcePlaybackCounter(NS(cleanup=lambda: None), start_time=100)
        player._source._num_reads = 250
        # Voice only reads frames while playing; wall time cannot advance pause.
        with patch("musicbot.player.log.noise", create=True):
            player.pause()
        self.assertEqual(player.progress, 105)
        self.assertEqual((await Playlist.estimate_time_until(player.playlist, 1, player)).total_seconds(), 75)
        player._current_player = NS(resume=lambda: None)
        with patch("musicbot.player.log.noise", create=True):
            player.resume()
        player._source._num_reads += 50
        self.assertEqual((await Playlist.estimate_time_until(player.playlist, 1, player)).total_seconds(), 74)
