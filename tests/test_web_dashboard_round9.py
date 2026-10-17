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


class RecommendedGuildTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = base.DashboardTests.asyncSetUp
    asyncTearDown = base.DashboardTests.asyncTearDown
    call = base.DashboardTests.call

    def add_second_guild(self):
        second = NS(id=2, name="Second", unavailable=False, me=NS(voice=None),
                    get_member=lambda uid: self.bot.owner if uid == 42 else None)
        voice = NS(id=20, guild=second)
        player = NS(voice_client=NS(channel=voice),
                    playlist=NS(entries=[]), current_entry=None)
        self.bot.guilds.append(second)
        self.bot.get_guild = {1: self.bot.guild, 2: second}.get
        self.bot.get_player_in = lambda guild: self.bot.player if guild.id == 1 else player
        return second, voice

    async def test_shared_voice_precedes_last_request(self):
        second, voice = self.add_second_guild()
        self.dashboard.note_queue_entry(second, entry("Queued", author=self.bot.owner))
        result = await self.call("/api/guilds", method="GET")
        self.assertEqual(result["recommended_guild_id"], "1")
        self.bot.owner.voice.channel = voice
        self.assertEqual((await self.call("/api/guilds", method="GET"))["recommended_guild_id"], "2")

    async def test_last_member_request_precedes_browser_fallback_and_auto_is_ignored(self):
        second, voice = self.add_second_guild()
        self.bot.owner.voice = None
        self.assertIsNone((await self.call("/api/guilds", method="GET"))["recommended_guild_id"])
        self.dashboard.note_queue_entry(second, entry("Queued", author=self.bot.owner))
        auto = entry("Automatic", author=self.bot.owner)
        auto.from_auto_playlist = True
        self.dashboard.note_queue_entry(self.bot.guild, auto)
        self.assertEqual((await self.call("/api/guilds", method="GET"))["recommended_guild_id"], "2")
        self.dashboard.note_queue_entry(self.bot.guild, entry("Discord request", author=self.bot.owner))
        self.assertEqual((await self.call("/api/guilds", method="GET"))["recommended_guild_id"], "1")

    async def test_other_user_and_inaccessible_guild_never_exposed(self):
        second, voice = self.add_second_guild()
        self.bot.owner.voice = None
        self.dashboard.note_queue_entry(second, entry("Other request", author=NS(id=99)))
        self.assertIsNone((await self.call("/api/guilds", method="GET"))["recommended_guild_id"])
        self.dashboard.note_queue_entry(second, entry("Mine", author=self.bot.owner))
        second.get_member = lambda uid: None
        result = await self.call("/api/guilds", method="GET")
        self.assertIsNone(result["recommended_guild_id"])
        self.assertEqual(set(result), {"guilds", "recommended_guild_id"})


import test_web_dashboard_discord as identity
import test_web_dashboard_library as library_fixtures
from musicbot.bot import build_play_response
from musicbot.downloader import YtdlpResponseDict
from types import MethodType


class NativeNotificationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = identity.DiscordTests.asyncSetUp
    asyncTearDown = identity.DiscordTests.asyncTearDown
    call = identity.DiscordTests.call
    login_as = identity.DiscordTests.login_as
    provider_token = identity.DiscordTests.provider_token
    provider_me = identity.DiscordTests.provider_me

    async def test_web_single_reuses_real_discord_response_content_and_metadata(self):
        initial = list(self.bot.player.playlist.entries)
        native = await self.bot.cmd_play(
            message=None, player=self.bot.player, channel=self.bot.channel,
            guild=self.bot.guild, author=self.bot.member,
            permissions=self.bot.member_perms, leftover_args=[], song_url="same song")
        expected = native.content
        self.bot.player.playlist.entries.clear()
        self.bot.player.playlist.entries.extend(initial)
        await self.call(BASE + "play", {"query": "same song"})
        self.bot.safe_send_message.assert_awaited_once()
        channel, sent = self.bot.safe_send_message.call_args.args
        self.assertIs(channel, self.bot.channel)
        self.assertEqual(sent.content, "-# Friend 透過網頁控制台點歌\n" + expected)
        self.assertEqual(sent.description, sent.content)
        self.assertIsNone(sent.title)
        self.assertTrue(sent.force_text)
        self.assertTrue(sent.dashboard_no_mentions)
        self.assertIsNone(sent.author.name)
        self.assertEqual(sent.delete_after, native.delete_after)

    async def test_seek_notification_uses_same_integer_as_activity(self):
        seek_entry(self.bot)
        await self.call(BASE + "seek", {"position": 82.5})
        sent = self.bot.safe_send_message.call_args.args[1]
        self.assertEqual(sent.content.split("\n")[1], "\u8df3\u8f49\uff1a83 \u79d2")
        self.assertEqual(self.dashboard.activities[1][0]["detail"], "\u8df3\u8f49\uff1a83 \u79d2")

    async def test_playnext_original_response_and_plain_attribution(self):
        seek_entry(self.bot)
        self.bot.config.embeds = False
        await self.call(BASE + "playnext", {"query": "next song"})
        sent = self.bot.safe_send_message.call_args.args[1]
        self.assertTrue(sent.content.startswith("-# Friend 透過網頁控制台點歌\nEnqueued"))
        self.assertIn("Position in queue:", sent.content)
        self.assertEqual(self.bot.player.playlist.entries[0].title, "Added")
        self.assertNotIn("<@", sent.content)
        self.bot.safe_send_message.assert_awaited_once()

    async def test_batch_uses_native_playlist_formatter_once_and_retry_never_resends(self):
        self.bot.member_perms.allow_playlists = True
        info = dict(self.bot.info)
        self.bot.info = dict(info, entries=[
            dict(info, title="One", webpage_url="https://example.test/one"),
            dict(info, title="Two", webpage_url="https://example.test/two")], playlist_count=2)
        preview = (await self.call(BASE + "resolve", {"query": "https://example.test/list"}))["results"][0]
        self.bot.info = info
        data = {"query": preview["url"], "preview_id": preview["preview_id"]}
        result = await self.call(BASE + "play", data)
        self.assertEqual(result["added"], 2)
        self.bot.safe_send_message.assert_awaited_once()
        sent = self.bot.safe_send_message.call_args.args[1]
        expected = build_play_response(None, number=2, track="",
            position="4 - estimated time until playing: `00:00`", playlist=True)
        self.assertEqual(sent.content, "-# Friend 透過網頁控制台點歌\n" + expected.content)
        await self.call(BASE + "play", data)
        self.bot.safe_send_message.assert_awaited_once()

    async def test_bound_channel_and_missing_send_permission_never_notify(self):
        self.bot.config.bound_channels = {999}
        await self.call(BASE + "play", {"query": "song"}, status=403)
        self.bot.safe_send_message.assert_not_awaited()
        self.bot.config.bound_channels = set()
        self.bot.channel.permissions_for = lambda member: NS(view_channel=True, send_messages=False)
        await self.call(BASE + "play", {"query": "song"}, status=403)
        self.bot.safe_send_message.assert_not_awaited()

    async def test_no_send_if_permission_disappears_after_enqueue(self):
        original = self.bot.cmd_play
        async def revoke(**kwargs):
            response = await original(**kwargs)
            self.bot.channel.permissions_for = lambda member: NS(view_channel=True, send_messages=False)
            return response
        self.bot.cmd_play = revoke
        await self.call(BASE + "play", {"query": "song"})
        self.bot.safe_send_message.assert_not_awaited()


class LibraryNotificationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = library_fixtures.LibraryTests.asyncSetUp
    asyncTearDown = library_fixtures.LibraryTests.asyncTearDown
    call = identity.DiscordTests.call
    login_as = identity.DiscordTests.login_as
    provider_token = identity.DiscordTests.provider_token
    provider_me = identity.DiscordTests.provider_me
    get = library_fixtures.LibraryTests.get
    add = library_fixtures.LibraryTests.add

    async def test_personal_playlist_uses_one_native_summary(self):
        value = await self.add()
        value = await self.add(track={"title": "Other", "url": "https://example.test/other", "duration": 1})
        result = await self.call(BASE + "library/favorites/play", {"revision": value["revision"]})
        self.assertEqual(result["added"], 2)
        self.bot.safe_send_message.assert_awaited_once()
        sent = self.bot.safe_send_message.call_args.args[1]
        self.assertIn("Enqueued **2** songs to be played.", sent.content)
        self.assertIn("Position in queue: 4", sent.content)


import asyncio
import copy
from musicbot.downloader import Downloader


class SpotifyNativeSelectionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = library_fixtures.LibraryTests.asyncSetUp
    asyncTearDown = library_fixtures.LibraryTests.asyncTearDown
    call = identity.DiscordTests.call
    login_as = identity.DiscordTests.login_as
    provider_token = identity.DiscordTests.provider_token
    provider_me = identity.DiscordTests.provider_me
    get = library_fixtures.LibraryTests.get
    add = library_fixtures.LibraryTests.add

    async def set_real_spotify_extraction(self, raw=None):
        self.bot.config.spotify_enabled = True
        self.bot.loop = asyncio.get_running_loop()
        self.bot.spotify = NS(get_spotify_ytdl_data=AsyncMock(return_value={
            "_type": "url", "search_terms": "Artist Song"}))
        raw = raw or {
            "_type": "playlist", "extractor": "youtube:search", "playlist_count": 1,
            "entries": [{"_type": "video", "extractor": "youtube", "id": "abcdefghijk",
                         "title": "Found", "duration": 90,
                         "url": "https://media.example.test/audio",
                         "webpage_url": "https://www.youtube.com/watch?v=abcdefghijk"}]}
        native = NS(bot=self.bot, thread_pool=None, _supported_search=["ytsearch"],
            unsafe_ytdl=NS(extract_info=lambda *a, **kw: copy.deepcopy(raw)),
            ytdl=NS(sanitize_info=lambda value: value))
        async def extract(query, **kwargs):
            with patch("musicbot.downloader.log.noise", create=True):
                value = await Downloader._filtered_extract_info(native, query, **kwargs)
            value["__input_subject"] = query
            return YtdlpResponseDict(value)
        self.bot.downloader.extract_info = extract
        return raw

    async def test_imported_spotify_real_native_search_wrapper_is_playable(self):
        value = await self.add(track={"title": "Artist - Song",
            "url": "https://open.spotify.com/track/ABC123", "duration": 90})
        await self.set_real_spotify_extraction()
        result = await self.call(BASE + "library/favorites/play", {"revision": value["revision"]})
        self.assertEqual(result["added"], 1)
        self.bot.spotify.get_spotify_ytdl_data.assert_awaited_once_with(
            "https://open.spotify.com/track/ABC123", True)
        self.assertEqual(self.bot.player.playlist.entries[-1].title, "Found")
        self.bot.safe_send_message.assert_awaited_once()

    async def test_real_spotify_wrapper_rechecks_full_duration_and_extractor(self):
        value = await self.add(track={"title": "Artist - Song",
            "url": "https://open.spotify.com/track/ABC123", "duration": 1})
        await self.set_real_spotify_extraction()
        self.bot.member_perms.max_song_length = 30
        result = await self.call(BASE + "library/favorites/play", {"revision": value["revision"]})
        self.assertEqual(result["added"], 0)
        self.bot.safe_send_message.assert_not_awaited()

    async def test_spotify_true_multiple_and_nested_playlists_remain_denied(self):
        value = await self.add(track={"title": "Artist - Song",
            "url": "https://open.spotify.com/track/ABC123", "duration": 90})
        raw = await self.set_real_spotify_extraction()
        for altered in (
            dict(raw, entries=raw["entries"] * 2, playlist_count=2),
            dict(raw, entries=[dict(raw["entries"][0], _type="playlist", entries=raw["entries"])]),
        ):
            await self.set_real_spotify_extraction(altered)
            result = await self.call(BASE + "library/favorites/play", {"revision": value["revision"]})
            self.assertEqual(result["added"], 0)
        self.bot.safe_send_message.assert_not_awaited()
