"""Round 5 tests: real command gates and mocked LRCLIB; no external access."""
import asyncio
import json
import unittest
from types import SimpleNamespace as NS, MethodType
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import web
from aiohttp.test_utils import TestServer

import test_web_dashboard as base
import test_web_dashboard_discord as discord
from test_web_dashboard import BASE, entry
from musicbot.bot import MusicBot
from musicbot.downloader import YtdlpResponseDict
from musicbot.entry import URLPlaylistEntry, StreamPlaylistEntry
from musicbot.exceptions import PermissionsError
from musicbot.web_dashboard import CONFIRMED_ENTRY_CHECK
from musicbot.web_dashboard_lyrics import LyricsClient, clean_metadata, parse_lrc, result


def seek_entry(bot, stream=False):
    bot.filecache = NS()
    cls = StreamPlaylistEntry if stream else URLPlaylistEntry
    current = cls(bot.player.playlist, YtdlpResponseDict(dict(
        bot.info, url="https://example.test/current", title="Singer - Song (Official MV)", duration=180)),
        author=bot.owner, channel=bot.channel)
    bot.player.current_entry = current
    bot.cmd_seek = MethodType(MusicBot.cmd_seek, bot)
    bot.cmd_playnext = MethodType(MusicBot.cmd_playnext, bot)
    return current


class Round5API(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = base.DashboardTests.asyncSetUp
    asyncTearDown = base.DashboardTests.asyncTearDown
    call = base.DashboardTests.call

    async def test_seek_real_command_fractional_and_edge_positions(self):
        for position in (0, 70.25, 180):
            current = seek_entry(self.bot)
            await self.call(BASE + "seek", {"position": position})
            self.assertEqual(current.start_time, int(position + 0.5))
            self.assertIs(self.bot.player.playlist.entries[0], current)

    async def test_seek_rejects_track_change_during_context_and_lock_wait_without_token(self):
        original = seek_entry(self.bot)
        async def switch_during_context(*args, **kwargs):
            seek_entry(self.bot)
            return self.bot.player
        self.bot.get_player.side_effect = switch_during_context
        await self.call(BASE + "seek", {"position": 30}, status=409)
        self.assertEqual(original.start_time, 0)
        self.assertEqual(self.bot.player.current_entry.start_time, 0)
        self.assertEqual(len(self.bot.player.playlist.entries), 3)

        entered, release = asyncio.Event(), asyncio.Event()
        class WaitingLock:
            async def __aenter__(self):
                entered.set()
                await release.wait()
            async def __aexit__(self, *args):
                return False
        self.dashboard.locks[1] = WaitingLock()
        self.bot.get_player.side_effect = lambda *args, **kwargs: self.bot.player
        task = asyncio.create_task(self.call(BASE + "seek", {"position": 40}, status=409))
        await asyncio.wait_for(entered.wait(), 1)
        switched = seek_entry(self.bot)
        release.set()
        await task
        self.assertEqual(switched.start_time, 0)
        self.assertEqual(len(self.bot.player.playlist.entries), 3)

    async def test_seek_stale_token_rejected_same_url_new_entry_has_new_token(self):
        original = seek_entry(self.bot)
        token = (await self.call(BASE + "state", method="GET"))["current"]["track_token"]
        replacement = seek_entry(self.bot)
        self.assertEqual(original.url, replacement.url)
        fresh_token = (await self.call(BASE + "state", method="GET"))["current"]["track_token"]
        self.assertNotEqual(token, fresh_token)
        self.assertEqual(len(fresh_token), 64)
        await self.call(BASE + "seek", {"position": 30, "track_token": token}, status=409)
        self.bot.get_player.assert_not_awaited()
        await self.call(BASE + "seek", {"position": 30, "track_token": fresh_token})
        self.assertEqual(replacement.start_time, 30)

    async def test_seek_rejects_invalid_numeric_and_out_of_bounds(self):
        current = seek_entry(self.bot)
        for position in (True, False, None, "30", -1, 180.01, float("nan"), float("inf"), 10 ** 400):
            await self.call(BASE + "seek", {"position": position}, status=400)
        self.assertEqual(current.start_time, 0)

    async def test_seek_stream_unknown_duration_no_song(self):
        seek_entry(self.bot, stream=True)
        await self.call(BASE + "seek", {"position": 0}, status=400)
        current = seek_entry(self.bot)
        current.duration = 0
        await self.call(BASE + "seek", {"position": 0}, status=400)
        self.bot.player.current_entry = None
        await self.call(BASE + "seek", {"position": 0}, status=409)

    async def test_seek_state_reports_seekable(self):
        seek_entry(self.bot)
        self.assertTrue((await self.call(BASE + "state", method="GET"))["current"]["seekable"])
        seek_entry(self.bot, stream=True)
        self.assertFalse((await self.call(BASE + "state", method="GET"))["current"]["seekable"])

    async def test_playnext_real_command_front_and_play_appends(self):
        seek_entry(self.bot)
        await self.call(BASE + "playnext", {"query": "https://example.test/next"})
        self.assertEqual(self.bot.player.playlist.entries[0].title, "Added")
        await self.call(BASE + "play", {"query": "https://example.test/last"})
        self.assertEqual(self.bot.player.playlist.entries[-1].title, "Added")
        self.assertIsNone(CONFIRMED_ENTRY_CHECK.get())

    async def test_playnext_all_native_queue_length_karaoke_limits(self):
        seek_entry(self.bot)
        self.bot.perms.max_song_length = 100
        await self.call(BASE + "playnext", {"query": "song"}, status=403)
        self.bot.perms.max_song_length = 0
        self.bot.perms.max_songs = 3
        await self.call(BASE + "playnext", {"query": "song"}, status=403)
        self.bot.perms.max_songs = 0
        self.bot.player.karaoke_mode, self.bot.perms.bypass_karaoke_mode = True, False
        await self.call(BASE + "playnext", {"query": "song"}, status=403)
        self.assertEqual(len(self.bot.player.playlist.entries), 3)

    async def test_playnext_full_duration_rejects_days_fractions_and_fresh_preview_change(self):
        seek_entry(self.bot)
        self.bot.perms.max_song_length = 210
        for duration in (86500, 210.5):
            self.bot.info["duration"] = duration
            body = await self.call(BASE + "playnext", {"query": "song"}, status=403)
            self.assertIn("長度", body["error"])
            self.assertEqual(len(self.bot.player.playlist.entries), 3)
        self.bot.info["duration"] = 100
        preview = (await self.call(BASE + "resolve", {"query": "https://example.test/song"}))["results"][0]
        self.bot.info["duration"] = 86500
        await self.call(BASE + "playnext", {"query": preview["url"], "preview_id": preview["preview_id"]}, status=403)
        self.assertEqual(len(self.bot.player.playlist.entries), 3)
        self.assertIsNone(CONFIRMED_ENTRY_CHECK.get())

    async def test_playnext_search_wrapper_checks_selected_child_duration_blocklist_extractor(self):
        seek_entry(self.bot)
        self.bot.perms.max_song_length = 210
        original = dict(self.bot.info)
        child = dict(original, duration=86500)
        self.bot.info = dict(original, extractor="youtube:search", duration=100, entries=[child])
        await self.call(BASE + "playnext", {"query": "song"}, status=403)
        child["duration"], child["title"] = 100, "Blocked child"
        self.bot.blocked.add("Blocked child")
        await self.call(BASE + "playnext", {"query": "song"}, status=403)
        self.bot.blocked.clear()
        child["extractor"] = "forbidden-child"
        def allowed_extractor(extractor):
            if extractor == "forbidden-child":
                raise PermissionsError("Blocked extractor")
        self.bot.perms.can_use_extractor = allowed_extractor
        await self.call(BASE + "playnext", {"query": "song"}, status=403)
        self.assertEqual(len(self.bot.player.playlist.entries), 3)
        self.assertIsNone(CONFIRMED_ENTRY_CHECK.get())

    async def test_playnext_rejects_playlist_after_fresh_extraction(self):
        seek_entry(self.bot)
        preview = (await self.call(BASE + "resolve", {"query": "https://example.test/song"}))["results"][0]
        self.bot.info = dict(self.bot.info, entries=[dict(self.bot.info)] * 2)
        await self.call(BASE + "playnext", {"query": preview["url"], "preview_id": preview["preview_id"]}, status=403)
        self.assertIsNone(CONFIRMED_ENTRY_CHECK.get())
        self.assertEqual(len(self.bot.player.playlist.entries), 3)

    async def test_playnext_accepts_play_preview_and_is_idempotent(self):
        seek_entry(self.bot)
        preview = (await self.call(BASE + "resolve", {"query": "https://example.test/song"}))["results"][0]
        data = {"query": preview["url"], "preview_id": preview["preview_id"]}
        await self.call(BASE + "playnext", data)
        await self.call(BASE + "playnext", data)
        self.assertEqual(len(self.bot.player.playlist.entries), 4)

    async def test_playnext_playlist_preview_explicitly_disabled(self):
        self.bot.info = dict(self.bot.info, entries=[dict(self.bot.info)] * 2)
        preview = (await self.call(BASE + "resolve", {"query": "https://example.test/list", "action": "playnext"}))["results"][0]
        self.assertFalse(preview["allowed"])
        self.assertIn("單曲", preview["reason"])
        await self.call(BASE + "resolve", {"query": "song", "action": "playnow"}, status=400)

    async def test_history_event_record_limit_50_order_and_minimal_fields(self):
        for number in range(60):
            self.dashboard.record_play(self.bot.guild, entry(f"Track {number}", author=self.bot.owner),
                                       played_at=1000 + number)
        rows = (await self.call(BASE + "history", method="GET"))["history"]
        self.assertEqual(len(rows), 50)
        self.assertEqual((rows[0]["title"], rows[-1]["title"]), ("Track 59", "Track 10"))
        self.assertEqual(rows[0]["played_at"], 1059)
        self.assertEqual(set(rows[0]), {"title", "url", "thumbnail", "duration", "requester", "played_at"})
        self.assertEqual(set(rows[0]["requester"]), {"name", "avatar"})
        self.assertNotIn("requester_id", json.dumps(rows))
        self.assertEqual(rows[0]["requester"]["name"], "Owner")

    async def test_history_guild_isolation_and_live_member_display(self):
        self.dashboard.record_play(self.bot.guild, entry("First", author=self.bot.owner))
        guild2 = NS(id=2, unavailable=False, get_member=lambda uid: self.bot.owner)
        self.bot.get_guild = lambda gid: {1: self.bot.guild, 2: guild2}.get(gid)
        self.dashboard.record_play(guild2, entry("Second", author=self.bot.owner))
        self.bot.owner.display_name = "New display name"
        rows = (await self.call(BASE + "history", method="GET"))["history"]
        self.assertEqual([row["title"] for row in rows], ["First"])
        self.assertEqual(rows[0]["requester"]["name"], "New display name")
        self.assertEqual((await self.call("/api/guilds/2/history", method="GET"))["history"][0]["title"], "Second")

    async def test_history_loaded_guild_urls_reused_but_global_never_disclosed(self):
        class Loaded(list):
            loaded = True
        self.bot.config.enable_queue_history_guilds = True
        self.bot.playlist_mgr = NS(_playlists={"history-1": Loaded(["https://example.test/old"])})
        body = await self.call(BASE + "history", method="GET")
        self.assertIn("guild_queue_history", body["source"])
        self.assertEqual(body["history"][0]["url"], "https://example.test/old")
        self.assertIsNone(body["history"][0]["played_at"])
        self.bot.config.enable_queue_history_guilds = False
        self.bot.config.enable_queue_history_global = True
        self.bot.playlist_mgr.global_history = Loaded(["https://example.test/private-other-guild"])
        body = await self.call(BASE + "history", method="GET")
        self.assertEqual(body["history"], [])

    async def test_real_play_event_records_without_poll_and_failures_are_isolated(self):
        class StopAfterObserver(Exception):
            pass
        self.bot._web_dashboard = self.dashboard
        self.bot._handle_guild_auto_pause = AsyncMock(side_effect=StopAfterObserver)
        with self.assertRaises(StopAfterObserver):
            await MusicBot.on_player_play(self.bot, self.bot.player, self.bot.player.current_entry)
        self.assertEqual(self.dashboard.recent_history[1][0]["title"], "Current")
        self.bot._web_dashboard = NS(record_play=Mock(side_effect=ValueError("bad history")))
        with self.assertRaises(StopAfterObserver):
            await MusicBot.on_player_play(self.bot, self.bot.player, self.bot.player.current_entry)

    async def test_lyrics_api_only_sends_clean_metadata_and_no_identity(self):
        seek_entry(self.bot)
        lookup = AsyncMock(return_value=result("Song", "Singer", {"plainLyrics": "One\nTwo"}))
        self.dashboard.lyrics_client = NS(lookup=lookup)
        body = await self.call(BASE + "lyrics", method="GET")
        self.assertEqual(body["status"], "plain")
        self.assertTrue(body["track_key"])
        lookup.assert_awaited_once_with("Song", "Singer", 180, query="")
        await self.call(BASE + "lyrics?query=manual%20song", method="GET")
        self.assertEqual(lookup.call_args.kwargs, {"query": "manual song"})

    async def test_lyrics_api_rate_limit_and_invalid_query(self):
        self.dashboard.lyrics_client = NS(lookup=AsyncMock(return_value=result("Current", "")))
        for _ in range(12):
            await self.call(BASE + "lyrics", method="GET")
        await self.call(BASE + "lyrics", method="GET", status=429)
        await self.call(BASE + "lyrics?query=" + "x" * 161, method="GET", status=400)

    async def test_lyrics_no_song_and_unavailable_do_not_break_playback(self):
        self.dashboard.lyrics_client = NS(lookup=AsyncMock(return_value=result("Current", "", status="unavailable")))
        self.assertEqual((await self.call(BASE + "lyrics", method="GET"))["status"], "unavailable")
        await self.call(BASE + "pause", {})
        self.bot.player.current_entry = None
        await self.call(BASE + "lyrics", method="GET", status=409)


class Round5Discord(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = discord.DiscordTests.asyncSetUp
    asyncTearDown = discord.DiscordTests.asyncTearDown
    login_as = discord.DiscordTests.login_as
    call = discord.DiscordTests.call
    provider_token = discord.DiscordTests.provider_token
    provider_me = discord.DiscordTests.provider_me

    async def test_seek_uses_seek_command_permission(self):
        seek_entry(self.bot)
        self.bot.member_perms.can_use_command.return_value = False
        await self.call(BASE + "seek", {"position": 30}, status=403)
        self.assertEqual(self.bot.member_perms.can_use_command.call_args.args, ("seek", "30"))

    async def test_seek_requires_same_voice_and_voice_membership(self):
        seek_entry(self.bot)
        self.bot.member.voice = None
        await self.call(BASE + "seek", {"position": 30}, status=409)
        self.bot.member.voice = NS(channel=NS(id=999))
        await self.call(BASE + "seek", {"position": 30}, status=403)

    async def test_playnext_permission_is_independent_of_play(self):
        seek_entry(self.bot)
        self.bot.member_perms.can_use_command.side_effect = lambda command, sub: command == "playnext"
        preview = (await self.call(BASE + "resolve", {"query": "https://example.test/song", "action": "playnext"}))["results"][0]
        await self.call(BASE + "play", {"query": preview["url"]}, status=403)
        await self.call(BASE + "playnext", {"query": preview["url"], "preview_id": preview["preview_id"]})
        self.assertEqual(self.bot.player.playlist.entries[0].author.id, 43)

    async def test_playnext_revalidates_permissions_after_extraction(self):
        seek_entry(self.bot)
        async def extract(*args, **kwargs):
            self.bot.member_perms.can_use_command.return_value = False
            return YtdlpResponseDict(self.bot.info)
        self.bot.downloader.extract_info = extract
        await self.call(BASE + "playnext", {"query": "https://example.test/song"}, status=403)
        self.assertEqual(len(self.bot.player.playlist.entries), 3)

    async def test_history_nonmember_403_and_replay_checks_current_member_play_permission(self):
        self.dashboard.record_play(self.bot.guild, entry("History", author=self.bot.member))
        body = await self.call(BASE + "history", method="GET")
        self.assertEqual(body["history"][0]["requester"]["name"], "Friend")
        self.bot.member_perms.can_use_command.return_value = False
        await self.call(BASE + "play", {"query": body["history"][0]["url"]}, status=403)
        self.login_as(99)
        await self.call(BASE + "history", method="GET", status=403)
        await self.call(BASE + "lyrics", method="GET", status=403)

    async def test_lyrics_removed_member_rechecked_after_await(self):
        async def lookup(*args, **kwargs):
            self.bot.members.pop(43)
            return result("Track", "", {"plainLyrics": "Private"})
        self.dashboard.lyrics_client = NS(lookup=lookup)
        await self.call(BASE + "lyrics", method="GET", status=403)


class LyricsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = LyricsClient()
        self.client.MIN_INTERVAL = 0

    async def test_synced_get_and_one_hour_cache(self):
        self.client._request = AsyncMock(return_value={
            "trackName": "Song", "artistName": "Singer", "duration": 180,
            "plainLyrics": "One\nTwo", "syncedLyrics": "[00:01.50]One\n[00:04]Two"})
        body = await self.client.lookup("Singer - Song (Official MV)", "", 180)
        self.assertEqual(body["status"], "synced")
        self.assertEqual(body["lines"], [{"time": 1.5, "text": "One"}, {"time": 4, "text": "Two"}])
        await self.client.lookup("Song", "Singer", 180)
        self.client._request.assert_awaited_once()
        self.assertEqual(self.client._request.call_args.args[1], "/get")
        self.assertEqual(self.client._request.call_args.args[2]["duration"], "180")
        key = next(iter(self.client.cache))
        expiry, value = self.client.cache[key]
        self.client.cache[key] = (expiry - 3601, value)
        await self.client.lookup("Song", "Singer", 180)
        self.assertEqual(self.client._request.await_count, 2)

    async def test_plain_search_and_not_found(self):
        self.client._request = AsyncMock(side_effect=[None, [
            {"trackName": "Song", "artistName": "Singer", "plainLyrics": "Plain only", "duration": 180}]])
        body = await self.client.lookup("Song", "Singer", 180)
        self.assertEqual(body["status"], "plain")
        self.assertEqual(self.client._request.call_args.args[1:], ("/search", {"q": "Singer Song"}))
        self.client._request = AsyncMock(return_value=[])
        body = await self.client.lookup("Missing", "", 60)
        self.assertEqual(body["status"], "not_found")

    async def test_timeout_and_malformed_provider_are_unavailable(self):
        self.client.TIMEOUT = .01
        async def slow(*args):
            await asyncio.sleep(.1)
        self.client._request = slow
        self.assertEqual((await self.client.lookup("Song", "", 180))["status"], "unavailable")
        self.client = LyricsClient()
        self.client._request = AsyncMock(return_value={"unexpected": "not a list"})
        self.assertEqual((await self.client.lookup("Song", "", 180))["status"], "unavailable")

    async def test_manual_query_and_duration_matching(self):
        self.client._request = AsyncMock(return_value=[
            {"trackName": "Different", "plainLyrics": "Manual", "duration": 180}])
        body = await self.client.lookup("Song", "Singer", 180, query="Different")
        self.assertEqual(body["plain_lyrics"], "Manual")
        self.assertEqual(self.client._request.call_args.args[1:], ("/search", {"q": "Different"}))
        chosen = LyricsClient._choose([
            {"trackName": "Song", "artistName": "Singer", "duration": 400, "plainLyrics": "Wrong"},
            {"trackName": "Song", "artistName": "Singer", "duration": 180, "plainLyrics": "Right"}],
            "Song", "Singer", 180, False)
        self.assertEqual(chosen["plainLyrics"], "Right")
        self.assertIsNone(LyricsClient._choose([
            {"trackName": "Song", "artistName": "Singer", "duration": 400, "plainLyrics": "Wrong"}],
            "Song", "Singer", 180, False))
        self.assertIsNone(LyricsClient._choose([
            {"trackName": "Song", "artistName": "Other performer", "duration": 180, "plainLyrics": "Wrong"}],
            "Song", "Singer", 180, False))

    async def test_cache_bound_and_parallel_coalescing(self):
        self.client.CACHE_LIMIT = 2
        self.client._request = AsyncMock(return_value=[])
        await asyncio.gather(*[self.client.lookup("Song", "", 180) for _ in range(4)])
        self.assertEqual(self.client._request.await_count, 1)
        await self.client.lookup("Two", "", 180)
        await self.client.lookup("Three", "", 180)
        self.assertEqual(len(self.client.cache), 2)

    async def test_http_user_agent_anonymous_fixed_params_and_provider_cooldown(self):
        calls = []
        async def provider(request):
            calls.append((dict(request.query), dict(request.headers)))
            return web.Response(status=429, headers={"Retry-After": "60"})
        app = web.Application()
        app.router.add_get("/api/search", provider)
        server = TestServer(app)
        await server.start_server()
        try:
            with patch("musicbot.web_dashboard_lyrics.LRCLIB_ROOT", str(server.make_url("/api"))):
                self.assertEqual((await self.client.lookup("Song", "", 180))["status"], "unavailable")
                self.assertEqual((await self.client.lookup("Another", "", 180))["status"], "unavailable")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], {"q": "Song"})
            self.assertIn("MusicBot-WebDashboard", calls[0][1]["User-Agent"])
            self.assertNotIn("Authorization", calls[0][1])
            self.assertNotIn("Cookie", calls[0][1])
        finally:
            await server.close()

    async def test_provider_chunked_read_content_type_size_and_negative_cache(self):
        mode, calls = ["chunked"], []
        async def provider(request):
            calls.append(request.path)
            if mode[0] == "html":
                return web.Response(text="<html>wrong</html>", content_type="text/html")
            if mode[0] == "large":
                return web.Response(body=b"x" * 1025, content_type="application/json")
            response = web.StreamResponse(headers={"Content-Type": "application/json"})
            await response.prepare(request)
            await response.write(b'[{"trackName":"Song","duration":180,')
            await asyncio.sleep(.001)
            await response.write(b'"plainLyrics":"Complete"}]')
            await response.write_eof()
            return response
        app = web.Application()
        app.router.add_get("/api/search", provider)
        server = TestServer(app)
        await server.start_server()
        try:
            with patch("musicbot.web_dashboard_lyrics.LRCLIB_ROOT", str(server.make_url("/api"))):
                self.assertEqual((await self.client.lookup("Song", "", 180))["plain_lyrics"], "Complete")
                for bad in ("html", "large"):
                    mode[0] = bad
                    self.client = LyricsClient()
                    self.client.MIN_INTERVAL, self.client.MAX_BODY = 0, 1024
                    before = len(calls)
                    self.assertEqual((await self.client.lookup(bad, "", 180))["status"], "unavailable")
                    self.assertEqual((await self.client.lookup(bad, "", 180))["status"], "unavailable")
                    self.assertEqual(len(calls), before + 1)
        finally:
            await server.close()

    def test_title_cleaning_feat_mv_noise_preserves_song_brackets(self):
        self.assertEqual(clean_metadata("Singer - Song (Official MV) feat. Other"), ("Song", "Singer"))
        self.assertEqual(clean_metadata("Singer — Song【MV】"), ("Song", "Singer"))
        self.assertEqual(clean_metadata("Song (Remix)", "Singer feat. Guest"), ("Song (Remix)", "Singer"))
        self.assertEqual(clean_metadata("Song [Live at home]", "Singer"), ("Song [Live at home]", "Singer"))
        self.assertEqual(clean_metadata("Left Behind", "Daft Punk"), ("Left Behind", "Daft Punk"))
        self.assertEqual(clean_metadata("Singer - Song Official MV"), ("Song", "Singer"))
        self.assertEqual(clean_metadata("Singer【Song】Official MV"), ("Song", "Singer"))

    def test_lrc_multiple_timestamps_sort_and_bounds(self):
        self.assertEqual(parse_lrc("[00:05.1][00:01]Text\n[ar:Artist]\n[00:99]Bad"),
                         [{"time": 1, "text": "Text"}, {"time": 5.1, "text": "Text"}])
