"""Put this file in MusicBot/tests/ before running unittest discovery.

Exercise the actual Dashboard snapshot plus real MusicPlayer handoff control flow,
using existing repository test fixtures (no Discord server required).
"""
import asyncio
import unittest

from musicbot.web_dashboard import Dashboard, DashboardConfig
from test_web_dashboard import FakeBot
import test_musicbot_patch2_races as races


class PreparingDashboardSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = FakeBot()
        self.dashboard = Dashboard(self.bot, DashboardConfig())

    def snapshot(self):
        return self.dashboard.snapshot(self.bot.guild, self.bot.owner)

    async def test_known_next_track_visible_before_dequeue(self):
        player = self.bot.player
        selected = player.playlist.peek()
        player.current_entry = None
        player.is_playing, player.is_paused, player.is_stopped = False, False, True
        player._transitioning_to_next = True
        player._preparing_entry = None
        player._stop_requested = False

        snapshot = self.snapshot()
        self.assertEqual(snapshot['status'], 'preparing')
        self.assertEqual(snapshot['current']['title'], selected.title)
        self.assertEqual(snapshot['current']['thumbnail'], selected.thumbnail_url)
        self.assertFalse(snapshot['current']['seekable'])
        self.assertEqual(snapshot['current']['track_token'], '')
        self.assertEqual(snapshot['progress'], 0)
        self.assertEqual(snapshot['queue'][0]['title'], selected.title)

    async def test_selected_dequeued_track_remains_visible(self):
        player = self.bot.player
        selected = player.playlist.entries.popleft()
        player.current_entry = None
        player.is_playing, player.is_paused, player.is_stopped = False, False, True
        player._transitioning_to_next = True
        player._preparing_entry = selected
        player._stop_requested = False
        snapshot = self.snapshot()
        self.assertEqual(snapshot['status'], 'preparing')
        self.assertEqual(snapshot['current']['title'], selected.title)
        self.assertEqual(snapshot['queue'][0]['title'], 'Two')
        self.assertNotIn(selected.title, [song['title'] for song in snapshot['queue']])

    async def test_explicit_stop_never_displays_phantom_preparing(self):
        player = self.bot.player
        player.current_entry = None
        player.is_playing, player.is_paused, player.is_stopped = False, False, True
        player._stop_requested = True
        player._transitioning_to_next = True
        player._preparing_entry = player.playlist.peek()
        state = self.snapshot()
        self.assertEqual(state['status'], 'stopped')
        self.assertIsNone(state['current'])

    async def test_pending_paused_seek_is_not_overwritten_by_preparing(self):
        player = self.bot.player
        current = player.current_entry
        player._pending_seek = {'entry': current, 'position': 48, 'paused': True}
        player._transitioning_to_next = True
        player._preparing_entry = player.playlist.peek()
        state = self.snapshot()
        self.assertEqual(state['status'], 'paused')
        self.assertEqual(state['current']['title'], 'Current')
        self.assertEqual(state['progress'], 48)

    async def test_no_known_next_song_keeps_idle_behavior(self):
        player = self.bot.player
        player.playlist.entries.clear()
        player.current_entry = None
        player.is_playing, player.is_paused, player.is_stopped = False, False, True
        player._transitioning_to_next = True
        player._preparing_entry = None
        player._stop_requested = False
        state = self.snapshot()
        self.assertEqual(state['status'], 'stopped')
        self.assertIsNone(state['current'])

    async def test_disconnected_or_dead_player_does_not_show_preparing(self):
        player = self.bot.player
        player.current_entry = None
        player.is_playing, player.is_paused, player.is_stopped = False, False, True
        player._transitioning_to_next = True
        player._preparing_entry = player.playlist.peek()
        for attribute in ('is_dead', 'guild_or_net_unavailable'):
            with self.subTest(attribute=attribute):
                setattr(player, attribute, True)
                state = self.snapshot()
                self.assertEqual(state['status'], 'stopped')
                self.assertIsNone(state['current'])
                setattr(player, attribute, False)
        self.bot.guild.me.voice = None
        player.voice_client = None
        state = self.snapshot()
        self.assertNotEqual(state['status'], 'preparing')
        self.assertIsNone(state['current'])


class PreparingPlayerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    # Reuse the real MusicPlayer mock VoiceClient + FFmpeg fixtures without
    # inheriting (and redundantly running) the original race test cases.
    setUp = races.PlaybackGenerationRaceTests.setUp
    asyncTearDown = races.PlaybackGenerationRaceTests.asyncTearDown
    fixture = races.PlaybackGenerationRaceTests.fixture
    paused_download = races.PlaybackGenerationRaceTests.paused_download
    paused_probe = races.PlaybackGenerationRaceTests.paused_probe
    run_player = races.PlaybackGenerationRaceTests.run_player
    until = races.PlaybackGenerationRaceTests.until

    async def test_download_handoff_keeps_selected_metadata_until_play(self):
        player, entry, voice = self.fixture()
        task, _release = await self.paused_download(player)
        self.assertIs(player._preparing_entry, entry)
        self.assertTrue(player._transitioning_to_next)
        self.assertIsNone(player.current_entry)
        player.stop()
        await asyncio.wait_for(task, 1)
        self.assertIsNone(player._preparing_entry)
        self.assertFalse(player._transitioning_to_next)
        voice.play.assert_not_called()

    async def test_natural_finish_shows_next_before_scheduling_it(self):
        player, _, voice = self.fixture()
        await self.run_player(player)
        callback = voice.play.call_args.kwargs['after']
        callback(None)
        self.assertTrue(player._transitioning_to_next)
        self.assertIsNone(player._preparing_entry)
        self.assertIsNone(player.current_entry)
        self.assertEqual(player.playlist.peek().title, 'Following queued track')
        player.play(_continue=True)
        await self.until(lambda: voice.play.call_count == 2)
        self.assertFalse(player._transitioning_to_next)
        self.assertIsNone(player._preparing_entry)
        self.assertEqual(player.current_entry.title, 'Following queued track')

    async def test_stop_after_finish_clears_preparing_hint(self):
        player, _, voice = self.fixture()
        await self.run_player(player)
        voice.play.call_args.kwargs['after'](None)
        self.assertTrue(player._transitioning_to_next)
        player.stop()
        self.assertFalse(player._transitioning_to_next)
        self.assertIsNone(player._preparing_entry)
        self.assertEqual(player.playlist.peek().title, 'Following queued track')

    async def test_probe_handoff_clears_on_disconnect(self):
        player, entry, voice = self.fixture()
        task, release = await self.paused_probe(player)
        self.assertIs(player._preparing_entry, entry)
        voice.is_connected.return_value = False
        release.set()
        await asyncio.wait_for(task, 1)
        self.assertIsNone(player._preparing_entry)
        self.assertFalse(player._transitioning_to_next)
        voice.play.assert_not_called()
        self.assertIs(player.playlist.peek(), entry)

    async def test_download_error_clears_hint(self):
        player, _, voice = self.fixture()
        task, release = await self.paused_download(player, fail=True)
        release.set()
        await asyncio.wait_for(task, 1)
        self.assertIsNone(player._preparing_entry)
        self.assertFalse(player._transitioning_to_next)
        voice.play.assert_not_called()

    async def test_cancelled_old_download_cannot_clear_replacement_hint(self):
        player, _, voice = self.fixture()
        task, release = await self.paused_download(player, suppress_cancel=True)
        player.skip()
        await self.until(lambda: player._preparing_entry is player.playlist.peek()
                         or voice.play.called)
        release.set()
        await asyncio.wait_for(task, 1)
        await self.until(lambda: voice.play.called)
        self.assertEqual(player.current_entry.title, 'Following queued track')
        self.assertFalse(player._transitioning_to_next)
        self.assertIsNone(player._preparing_entry)


if __name__ == '__main__':
    unittest.main()
