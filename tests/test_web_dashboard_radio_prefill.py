"""Radio last-track prefill regressions: run with MusicBot's normal unittest suite."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import test_web_dashboard_round33_radio_priority as existing
from musicbot.web_dashboard_radio import RadioService


class RadioLastTrackPrefillTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = existing.base.FakeBot()
        self.queue = existing.install_playlist(self.bot)
        self.player = self.bot.player
        self.player.current_entry = NS(title="Last song")
        self.player._stop_requested = False
        self.player._play_generation = 0
        self.player.is_dead = False
        self.player.voice_client.guild = self.bot.guild
        self.player.voice_client.is_connected = lambda: True
        self.bot.logout_called = False
        self.bot.downloader.extract_public_playlist = AsyncMock(
            return_value=existing.batch("Radio1", "Radio2", "Radio3"))
        self.tmp = tempfile.TemporaryDirectory(prefix="musicbot-prefill-")
        self.addCleanup(self.tmp.cleanup)
        self.service = RadioService(self.bot, Path(self.tmp.name))
        self.service.next_seed = AsyncMock(return_value="https://www.youtube.com/watch?v=seed0000001")
        self.service.rng = NS(choices=lambda *args, **kwargs: [0])
        self.settings = await self.service.store.put(self.bot.guild, {
            "empty_queue": "radio", "radio_min_seconds": 0, "radio_max_seconds": 0})

    def titles(self):
        return [entry.title for entry in self.queue.entries]

    async def test_last_song_prefills_radio_while_current_is_playing(self):
        last = self.player.current_entry
        self.service.schedule_prefill(self.player, last)
        await self.service.wait_prefill(self.player)
        self.assertIs(self.player.current_entry, last)
        self.assertEqual(self.titles(), ["Radio1", "Radio2", "Radio3"])
        self.bot.downloader.extract_public_playlist.assert_awaited_once()

    async def test_user_request_is_inserted_before_prefilled_radio(self):
        self.service.schedule_prefill(self.player, self.player.current_entry)
        await self.service.wait_prefill(self.player)
        await self.queue.add_entry_from_info(
            existing.info("User1"), author=self.bot.owner, channel=self.bot.channel)
        self.assertEqual(self.titles(), ["User1", "Radio1", "Radio2", "Radio3"])

    async def test_user_request_while_extraction_pending_prevents_stale_insertion(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow(_):
            started.set()
            await release.wait()
            return existing.batch("Radio1", "Radio2")
        self.bot.downloader.extract_public_playlist.side_effect = slow
        self.service.schedule_prefill(self.player, self.player.current_entry)
        await asyncio.wait_for(started.wait(), 2)
        await self.queue.add_entry_from_info(
            existing.info("User1"), author=self.bot.owner, channel=self.bot.channel)
        release.set()
        await self.service.wait_prefill(self.player)
        self.assertEqual(self.titles(), ["User1"])

    async def test_multiple_events_share_one_inflight_prefill(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow(_):
            started.set()
            await release.wait()
            return existing.batch("Radio1", "Radio2")
        self.bot.downloader.extract_public_playlist.side_effect = slow
        current = self.player.current_entry
        self.service.schedule_prefill(self.player, current)
        await asyncio.wait_for(started.wait(), 2)
        self.service.schedule_prefill(self.player, current)
        release.set()
        await self.service.wait_prefill(self.player)
        self.bot.downloader.extract_public_playlist.assert_awaited_once()
        self.assertEqual(self.titles(), ["Radio1", "Radio2"])

    async def test_natural_end_waiting_on_prefill_reuses_provider_result(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow(_):
            started.set()
            await release.wait()
            return existing.batch("Radio1")
        self.bot.downloader.extract_public_playlist.side_effect = slow
        self.service.schedule_prefill(self.player, self.player.current_entry)
        await asyncio.wait_for(started.wait(), 2)
        # Natural completion clears current_entry but does not bump generation.
        self.player.current_entry = None
        release.set()
        await self.service.wait_prefill(self.player)
        self.assertEqual(self.titles(), ["Radio1"])
        self.bot.downloader.extract_public_playlist.assert_awaited_once()

    async def test_skip_generation_change_prevents_stale_prefill(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow(_):
            started.set()
            await release.wait()
            return existing.batch("Radio1")
        self.bot.downloader.extract_public_playlist.side_effect = slow
        self.service.schedule_prefill(self.player, self.player.current_entry)
        await asyncio.wait_for(started.wait(), 2)
        self.player.current_entry = None
        self.player._play_generation += 1
        release.set()
        await self.service.wait_prefill(self.player)
        self.assertEqual(self.titles(), [])

    async def test_stop_during_extraction_does_not_append_radio(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow(_):
            started.set()
            await release.wait()
            return existing.batch("Radio1")
        self.bot.downloader.extract_public_playlist.side_effect = slow
        self.service.schedule_prefill(self.player, self.player.current_entry)
        await asyncio.wait_for(started.wait(), 2)
        self.player._stop_requested = True
        release.set()
        await self.service.wait_prefill(self.player)
        self.assertEqual(self.titles(), [])

    async def test_replaced_current_track_does_not_append_radio(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow(_):
            started.set()
            await release.wait()
            return existing.batch("Radio1")
        self.bot.downloader.extract_public_playlist.side_effect = slow
        self.service.schedule_prefill(self.player, self.player.current_entry)
        await asyncio.wait_for(started.wait(), 2)
        self.player.current_entry = NS(title="Replacement")
        release.set()
        await self.service.wait_prefill(self.player)
        self.assertEqual(self.titles(), [])

    async def test_radio_off_does_not_call_provider(self):
        await self.service.store.put(self.bot.guild, {
            "empty_queue": "off", "radio_min_seconds": 0, "radio_max_seconds": 0})
        self.service.schedule_prefill(self.player, self.player.current_entry)
        await self.service.wait_prefill(self.player)
        self.bot.downloader.extract_public_playlist.assert_not_awaited()
        self.assertEqual(self.titles(), [])

    async def test_looping_song_does_not_schedule_prefill(self):
        self.player.repeatsong = True
        self.service.schedule_prefill(self.player, self.player.current_entry)
        await self.service.wait_prefill(self.player)
        self.bot.downloader.extract_public_playlist.assert_not_awaited()

    async def test_existing_queue_does_not_schedule_prefill(self):
        await self.queue.add_entry_from_info(
            existing.info("User1"), author=self.bot.owner, channel=self.bot.channel)
        self.service.schedule_prefill(self.player, self.player.current_entry)
        await self.service.wait_prefill(self.player)
        self.bot.downloader.extract_public_playlist.assert_not_awaited()


    async def test_skip_does_not_wait_for_obsolete_provider(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow(_):
            started.set()
            await release.wait()
            return existing.batch("Radio1")
        self.bot.downloader.extract_public_playlist.side_effect = slow
        self.service.schedule_prefill(self.player, self.player.current_entry)
        await asyncio.wait_for(started.wait(), 2)
        self.player._play_generation += 1
        try:
            await asyncio.wait_for(self.service.wait_prefill(self.player), .3)
        finally:
            task = self.service.prefill_tasks.get(self.bot.guild.id)
            release.set()
            if task: await task
        self.assertEqual(self.titles(), [])
