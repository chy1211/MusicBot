"""Synthetic autoplaylists only: upstream disable flow and radio isolation."""
import unittest
from unittest.mock import AsyncMock
import test_web_dashboard_round10_radio as fixtures
from musicbot.bot import MusicBot
from musicbot.exceptions import ExtractionError

class MemoryAutoplaylist(list):
    async def remove_track(self, url, **_kwargs):
        if url in self: self.remove(url)

class Round16AutoplayTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.RadioTests.asyncSetUp
    asyncTearDown = fixtures.RadioTests.asyncTearDown
    mode = fixtures.RadioTests.mode
    finish = fixtures.RadioTests.finish

    async def test_empty_list_reproduces_both_upstream_warnings(self):
        self.bot.server_data[1].autoplaylist = MemoryAutoplaylist()
        with self.assertLogs("musicbot.bot", level="WARNING") as logs:
            await self.finish()
        self.assertIn("No playable songs in the Guild autoplaylist, disabling.", " ".join(logs.output))
        self.assertIn("No playable songs in the autoplaylist, disabling.", " ".join(logs.output))
        self.assertFalse(self.bot.config.auto_playlist)
        self.bot.downloader.extract_info.assert_not_awaited()

    async def test_last_failed_native_song_disables_without_dashboard(self):
        self.bot.server_data[1].autoplaylist = MemoryAutoplaylist(["https://example.test/unplayable"])
        self.bot.config.song_blocklist_enabled = False
        self.bot.config.remove_ap = False
        self.bot.downloader.extract_info.side_effect = ExtractionError("synthetic failure")
        with self.assertLogs("musicbot.bot", level="WARNING") as logs:
            await self.finish()
        self.assertIn("No playable songs in the autoplaylist, disabling.", " ".join(logs.output))
        self.assertEqual(self.bot.server_data[1].autoplaylist, [])
        self.assertFalse(self.bot.config.auto_playlist)

    async def test_successful_legacy_play_keeps_configured_list(self):
        self.bot.config.song_blocklist_enabled = False
        before = list(self.bot.server_data[1].autoplaylist)
        await self.finish()
        self.assertEqual(list(self.bot.server_data[1].autoplaylist), before)
        self.assertTrue(self.bot.config.auto_playlist)

    async def test_failed_radio_song_does_not_prune_overlapping_autoplaylist_url(self):
        await self.mode()
        await self.finish()
        song = self.player.playlist.entries[0]
        self.assertTrue(song.from_auto_playlist)
        apl = MemoryAutoplaylist([song.url])
        apl.remove_track = AsyncMock(wraps=apl.remove_track)
        self.bot.server_data[1].autoplaylist = apl
        self.player.is_dead = True
        with self.assertLogs("musicbot.bot", level="ERROR"):
            await MusicBot.on_player_error(self.bot, self.player, song, RuntimeError("synthetic failure"))
        apl.remove_track.assert_not_awaited()
        self.assertEqual(apl, [song.url])
        self.assertTrue(self.bot.config.auto_playlist)

    async def test_native_autoplay_error_still_prunes_native_track(self):
        self.bot.config.song_blocklist_enabled = False
        self.bot.config.remove_ap = False
        await self.finish()
        song = self.player.playlist.entries[0]
        apl = MemoryAutoplaylist([song.url])
        apl.remove_track = AsyncMock(wraps=apl.remove_track)
        self.bot.server_data[1].autoplaylist = apl
        self.player.is_dead = True
        with self.assertLogs("musicbot.bot", level="ERROR"):
            await MusicBot.on_player_error(self.bot, self.player, song, RuntimeError("synthetic failure"))
        apl.remove_track.assert_awaited_once()
        self.assertEqual(apl, [])
