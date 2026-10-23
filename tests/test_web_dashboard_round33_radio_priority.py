"""Offline radio-priority regressions using the real Playlist insertion paths."""
import asyncio
import datetime
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import test_web_dashboard as base
import test_web_dashboard_discord as identity
from musicbot.downloader import YtdlpResponseDict
from musicbot.playlist import Playlist
from musicbot.web_dashboard_radio import RadioService, is_radio

logging.Logger.noise = logging.Logger.debug
logging.Logger.everything = logging.Logger.debug


def info(title, **extra):
    return YtdlpResponseDict({
        "title": title, "url": "https://www.youtube.com/watch?v=" + title[:11].ljust(11, "0"),
        "webpage_url": "https://www.youtube.com/watch?v=" + title[:11].ljust(11, "0"),
        "__input_subject": "https://www.youtube.com/watch?v=" + title[:11].ljust(11, "0"),
        "duration": 180, "extractor": "youtube", "id": title, **extra,
    })


def batch(*titles):
    return YtdlpResponseDict({"_type": "playlist", "extractor": "youtube:playlist", "__input_subject": "https://example.com/playlist",
                              "entries": [info(title).data for title in titles]})


def install_playlist(bot):
    bot.loop = asyncio.get_running_loop()
    bot.filecache = NS()
    bot.config.round_robin_queue = False
    bot.player.playlist = Playlist(bot)
    # Keep response ETA deterministic; insertion and entries stay real.
    bot.player.playlist.estimate_time_until = AsyncMock(
        return_value=datetime.timedelta(seconds=0))
    return bot.player.playlist


class RadioPriorityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = base.FakeBot()
        self.queue = install_playlist(self.bot)

    async def add(self, title, **kwargs):
        return await self.queue.add_entry_from_info(
            info(title), author=self.bot.owner, channel=self.bot.channel, **kwargs)

    async def radios(self):
        for i in range(1, 4):
            await self.queue.add_entry_from_info(
                info(f"Radio{i}", __web_dashboard_source="radio"))

    def titles(self):
        return [entry.title for entry in self.queue.entries]

    async def test_01_first_request_precedes_three_radio_tracks(self):
        await self.radios()
        await self.add("User1")
        self.assertEqual(self.titles(), ["User1", "Radio1", "Radio2", "Radio3"])

    async def test_02_second_request_preserves_request_and_radio_order(self):
        await self.radios()
        await self.add("User1")
        await self.add("User2")
        self.assertEqual(self.titles(), ["User1", "User2", "Radio1", "Radio2", "Radio3"])

    async def test_03_playlist_import_keeps_batch_before_radio(self):
        await self.radios()
        await self.add("Existing")
        entries, position = await self.queue.import_from_info(
            batch("User1", "User2", "User3"), head=False,
            author=self.bot.owner, channel=self.bot.channel)
        self.assertEqual(self.titles(),
                         ["Existing", "User1", "User2", "User3", "Radio1", "Radio2", "Radio3"])
        self.assertEqual([entry.title for entry in entries], ["User1", "User2", "User3"])
        self.assertEqual(position, 2)

    async def test_04_playnext_and_head_playlist_still_go_first(self):
        await self.add("Existing")
        await self.radios()
        _, position = await self.add("Next", head=True)
        self.assertEqual(position, 1)
        entries, position = await self.queue.import_from_info(
            batch("Head1", "Head2"), head=True, author=self.bot.owner)
        self.assertEqual(position, 1)
        self.assertEqual([entry.title for entry in entries], ["Head1", "Head2"])
        self.assertEqual(self.titles(),
                         ["Head1", "Head2", "Next", "Existing", "Radio1", "Radio2", "Radio3"])

    async def test_05_without_radio_tail_and_legacy_autoplay_are_unchanged(self):
        await self.queue.add_entry_from_info(info("Legacy"))
        first, position = await self.add("User1")
        self.assertEqual(position, 2)
        self.assertFalse(is_radio(self.queue.entries[0]))
        entries, position = await self.queue.import_from_info(
            batch("User2", "User3"), head=False, author=self.bot.owner)
        self.assertEqual(position, 3)
        self.assertEqual(self.titles(), ["Legacy", "User1", "User2", "User3"])
        self.assertIs(self.queue.entries[1], first)
        self.assertIs(self.queue.entries[2], entries[0])

    async def test_06_real_radio_fill_appends_in_provider_order(self):
        player = self.bot.player
        player.current_entry = None
        player.is_dead = False
        player.voice_client.guild = self.bot.guild
        player.voice_client.is_connected = lambda: True
        self.bot.downloader.extract_public_playlist = AsyncMock(
            return_value=batch("Radio1", "Radio2", "Radio3"))
        with tempfile.TemporaryDirectory(prefix="musicbot-r33-") as root:
            service = RadioService(self.bot, Path(root))
            service.next_seed = AsyncMock(return_value="https://www.youtube.com/watch?v=seed0000001")
            service.rng = NS(choices=lambda *args, **kwargs: [0])
            settings = await service.store.put(self.bot.guild, {
                "empty_queue": "radio", "radio_min_seconds": 0, "radio_max_seconds": 0})
            at_insertion = []
            self.queue.on("entry-added", lambda **event:
                          at_insertion.append(event["entry"] is self.queue.entries[-1]))
            self.assertTrue(await service.fill(player, settings))
        self.assertEqual(self.titles(), ["Radio1", "Radio2", "Radio3"])
        self.assertEqual(at_insertion, [True, True, True])
        self.assertTrue(all(is_radio(entry) for entry in self.queue.entries))
        await self.add("User1")
        radio, position = await self.queue.add_entry_from_info(
            info("Radio4", __web_dashboard_source="radio"))
        self.assertIs(self.queue.entries[-1], radio)
        self.assertEqual(position, 5)

    async def test_07_single_batch_and_discord_reply_positions_match_queue(self):
        await self.radios()
        song, position = await self.add("User1")
        self.assertEqual(position, 1)
        self.assertIs(self.queue.entries[position - 1], song)
        entries, position = await self.queue.import_from_info(
            batch("User2", "User3"), head=False, author=self.bot.owner)
        self.assertEqual(position, 2)
        self.assertIs(self.queue.entries[position - 1], entries[0])
        response = await self.bot.cmd_play(
            message=None, player=self.bot.player, channel=self.bot.channel,
            guild=self.bot.guild, author=self.bot.owner, permissions=self.bot.perms,
            leftover_args=[], song_url="Added")
        self.assertTrue(response.queue_position_text.startswith("4 -"), response.content)
        self.assertEqual(self.queue.entries[3].title, "Added")

    async def test_stream_and_local_entry_positions_and_head(self):
        for add_method in (self.queue.add_stream_from_info, self.queue.add_local_file_entry):
            for head in (False, True):
                with self.subTest(method=add_method.__name__, head=head):
                    self.queue.clear()
                    await self.radios()
                    await self.add("Existing")
                    song, position = await add_method(
                        info("Special"), author=self.bot.owner, head=head)
                    self.assertEqual(position, 1 if head else 2)
                    self.assertIs(self.queue.entries[position - 1], song)
                    self.assertEqual(self.titles(),
                                     (["Special", "Existing"] if head else ["Existing", "Special"])
                                     + ["Radio1", "Radio2", "Radio3"])

    async def test_batch_returned_position_matches_first_added_entry(self):
        await self.radios()
        entries, position = await self.queue.import_from_info(
            batch("User1", "User2"), head=False, author=self.bot.owner)
        self.assertEqual(position, 1)
        self.assertIs(self.queue.entries[position - 1], entries[0])

    async def test_native_single_and_playlist_replies_report_actual_positions(self):
        for extracted in (info("Added"), batch("User1", "User2")):
            with self.subTest(playlist=extracted.has_entries):
                self.queue.clear()
                await self.radios()
                self.bot.info = extracted.data
                response = await self.bot.cmd_play(
                    message=None, player=self.bot.player, channel=self.bot.channel,
                    guild=self.bot.guild, author=self.bot.owner, permissions=self.bot.perms,
                    leftover_args=[], song_url="https://example.com/music")
                self.assertTrue(response.queue_position_text.startswith("1 -"), response.content)
                self.assertEqual(self.queue.entries[0].title,
                                 "User1" if extracted.has_entries else "Added")

    async def test_round_robin_with_radio_preserves_radio_and_request_fifo(self):
        self.bot.config.round_robin_queue = True
        await self.radios()
        for title, author in (("User1", self.bot.owner), ("User2", self.bot.owner),
                              ("User3", NS(id=43, name="DemoUser"))):
            await self.queue.add_entry_from_info(info(title), author=author)
        self.assertEqual(self.titles(),
                         ["User1", "User2", "User3", "Radio1", "Radio2", "Radio3"])

    async def test_round_robin_without_radio_keeps_existing_behavior(self):
        self.bot.config.round_robin_queue = True
        await self.add("User1")
        await self.add("User2")
        await self.queue.add_entry_from_info(info("User3"), author=NS(id=43, name="DemoUser"))
        self.assertEqual(self.titles(), ["User1", "User3", "User2"])

    async def test_attribute_only_radio_marker_is_respected(self):
        song, _ = await self.queue.add_entry_from_info(info("Radio1"))
        song._dashboard_radio_source = True
        await self.add("User1")
        self.assertEqual(self.titles(), ["User1", "Radio1"])


class RadioPriorityDashboardTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = identity.DiscordTests.asyncTearDown
    call = identity.DiscordTests.call
    login_as = identity.DiscordTests.login_as
    provider_token = identity.DiscordTests.provider_token
    provider_me = identity.DiscordTests.provider_me

    async def asyncSetUp(self):
        await identity.DiscordTests.asyncSetUp(self)
        self.bot.member.name = "DemoUser"
        self.bot.friend.name = "DemoUser"
        self.queue = install_playlist(self.bot)
        self.bot.player.current_entry = base.entry("PlayingRadio")
        self.bot.player.current_entry._dashboard_radio_source = True
        for i in range(1, 4):
            await self.queue.add_entry_from_info(
                info(f"Radio{i}", __web_dashboard_source="radio"))

    async def test_08_remove_new_request_at_actual_position_and_undo_preserves_radio(self):
        await self.call(base.BASE + "play", {"query": "Added"})
        state = await self.call(base.BASE + "state", method="GET")
        self.assertEqual([row["title"] for row in state["queue"]],
                         ["Added", "Radio1", "Radio2", "Radio3"])
        self.assertEqual([row["position"] for row in state["queue"]], [1, 2, 3, 4])
        song, *radios = self.queue.entries
        result = await self.call(base.BASE + "queue/1", {"revision": state["revision"]}, method="DELETE")
        self.assertEqual(list(self.queue.entries), radios)
        restored = await self.call(base.BASE + "queue/undo", {"undo_token": result["undo_token"]})
        self.assertIs(self.queue.entries[0], song)
        self.assertEqual(list(self.queue.entries)[1:], radios)
        self.assertEqual(restored["state"]["queue"][0]["title"], "Added")
        self.assertEqual(restored["state"]["queue"][0]["position"], 1)

    async def test_web_reply_and_drag_positions_follow_real_queue(self):
        await self.call(base.BASE + "play", {"query": "Added"})
        sent = self.bot.safe_send_message.call_args.args[1].content
        self.assertIn("Position in queue: 1 -", sent)
        state = await self.call(base.BASE + "state", method="GET")
        await self.call(base.BASE + "queue/move", {"from": 1, "to": 2, "revision": state["revision"]})
        state = await self.call(base.BASE + "state", method="GET")
        self.assertEqual([row["title"] for row in state["queue"]],
                         ["Radio1", "Added", "Radio2", "Radio3"])
        self.assertEqual([row["position"] for row in state["queue"]], [1, 2, 3, 4])
