"""Preview/confirmation tests with real commands, no network/Discord credentials."""
import asyncio
import time
import unittest
from unittest.mock import AsyncMock

import test_web_dashboard as fixtures
from test_web_dashboard import HEADERS, BASE, NS
from musicbot.downloader import YtdlpResponseDict
from musicbot.exceptions import PermissionsError


class ResolveTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.DashboardTests.asyncSetUp
    asyncTearDown = fixtures.DashboardTests.asyncTearDown
    call = fixtures.DashboardTests.call
    rev = fixtures.DashboardTests.rev

    async def preview(self, query="https://example.test/song"):
        body = await self.call(BASE + "resolve", {"query": query})
        return body["results"]

    @staticmethod
    def confirm(song):
        return {"query": song["url"], "preview_id": song["preview_id"]}

    async def test_single_metadata_and_no_side_effects_even_without_voice(self):
        self.bot.owner.voice = None
        before = list(self.bot.player.playlist.entries)
        songs = await self.preview()
        self.assertEqual(songs[0]["title"], "Added")
        self.assertEqual(songs[0]["duration"], 120)
        self.assertTrue(songs[0]["url"].startswith("https://"))
        self.assertTrue(songs[0]["allowed"])
        self.assertEqual(self.bot.extractions, [
            ("https://example.test/song", {"download": False, "process": True})])
        self.assertEqual(list(self.bot.player.playlist.entries), before)
        self.bot.get_player.assert_not_awaited()
        self.bot.serialize_queue.assert_not_awaited()

    async def test_preview_without_existing_player(self):
        self.bot.get_player_in = lambda _: None
        await self.preview()
        self.bot.get_player.assert_not_awaited()

    async def test_playlist_summary_caps_visible_entries_and_filters_every_item(self):
        items = [dict(self.bot.info, title=f"Song {i}", duration=60) for i in range(15)]
        items[12]["duration"] = 600
        self.bot.perms.max_song_length = 100
        self.bot.info = dict(self.bot.info, title="List", entries=items, playlist_count=15)
        song, = await self.preview("https://example.test/playlist")
        self.assertEqual((song["kind"], song["title"], song["count"]), ("playlist", "List", 15))
        self.assertEqual(len(song["entries"]), 15)
        self.assertEqual((song["checked_count"], song["eligible_count"]), (15, 14))
        self.assertTrue(song["allowed"])
        self.assertEqual(len(self.bot.player.playlist.entries), 3)

    async def test_playlist_permissions_are_existing_checks(self):
        self.bot.info = dict(self.bot.info, entries=[dict(self.bot.info)] * 2, playlist_count=2)
        for name, value in (("allow_playlists", False), ("max_playlist_length", 1)):
            setattr(self.bot.perms, name, value)
            song, = await self.preview("https://example.test/playlist")
            self.assertFalse(song["allowed"], name)
            self.assertTrue(song["reason"])
            await self.call(BASE + "play", self.confirm(song), status=403)
            setattr(self.bot.perms, name, True if name == "allow_playlists" else 0)

    async def test_keyword_returns_five_selectable_tracks_without_playlist_permission(self):
        self.bot.perms.allow_playlists = False
        self.bot.info = dict(self.bot.info, extractor="youtube:search",
                             entries=[dict(self.bot.info, title=f"Result {i}",
                                           webpage_url=f"https://example.test/{i}") for i in range(7)])
        songs = await self.preview("some song")
        self.assertEqual(len(songs), 5)
        self.assertTrue(all(s["kind"] == "track" and s["allowed"] for s in songs))
        self.assertEqual(self.bot.extractions[0][0], "ytsearch5:some song")
        self.assertEqual(len({s["preview_id"] for s in songs}), 5)

    async def test_search_item_limit_is_respected(self):
        self.bot.perms.max_search_items = 2
        await self.preview("song")
        self.assertEqual(self.bot.extractions[0][0], "ytsearch2:song")

    async def test_blocked_input_is_rejected_before_extraction(self):
        self.bot.blocked.add("https://example.test/song")
        await self.call(BASE + "resolve", {"query": "https://example.test/song"}, status=403)
        self.assertEqual(self.bot.extractions, [])

    async def test_blocked_result_is_visible_but_not_confirmable(self):
        self.bot.blocked.add("Added")
        song, = await self.preview()
        self.assertFalse(song["allowed"])
        self.assertTrue(song["reason"])
        await self.call(BASE + "play", self.confirm(song), status=403)
        self.bot.get_player.assert_not_awaited()

    async def test_song_length_uses_total_seconds_and_explains_denial(self):
        self.bot.perms.max_song_length = 100
        self.bot.info["duration"] = 86520
        song, = await self.preview()
        self.assertFalse(song["allowed"])
        self.assertIn("100", song["reason"])

    async def test_playlist_all_blocked_or_long_is_denied(self):
        self.bot.blocked.add("Added")
        self.bot.info = dict(self.bot.info, entries=[dict(self.bot.info)] * 2)
        song, = await self.preview()
        self.assertFalse(song["allowed"])
        self.assertEqual(song["eligible_count"], 0)
        self.assertFalse(song["entries"][0]["allowed"])

    async def test_unknown_duration_is_visible(self):
        self.bot.info["duration"] = None
        song, = await self.preview()
        self.assertTrue(song["warning"])
        self.assertEqual(song["duration"], 0)

    async def test_extractor_denied(self):
        def deny(_):
            raise PermissionsError("Denied")
        self.bot.perms.can_use_extractor = deny
        await self.call(BASE + "resolve", {"query": "song"}, status=403)

    async def test_queue_limit_and_karaoke_before_resolving(self):
        self.bot.perms.max_songs = 3
        await self.call(BASE + "resolve", {"query": "song"}, status=403)
        self.bot.perms.max_songs = 0
        self.bot.player.karaoke_mode = True
        self.bot.perms.bypass_karaoke_mode = False
        await self.call(BASE + "resolve", {"query": "song"}, status=403)
        self.assertFalse(self.bot.extractions)

    async def test_timeout_does_not_lock_controls_and_retains_admission_slot(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow(*_, **__):
            started.set()
            await release.wait()
            return YtdlpResponseDict(self.bot.info)
        self.bot.downloader.extract_info = slow
        self.dashboard.RESOLVE_TIMEOUT = .03
        resolving = asyncio.create_task(self.call(BASE + "resolve", {"query": "song"}, status=504))
        await started.wait()
        await asyncio.wait_for(self.call(BASE + "pause", {}), .2)
        self.assertTrue(self.bot.player.is_paused)
        await resolving
        await self.call(BASE + "resolve", {"query": "song"}, status=429)
        self.assertFalse(self.dashboard.locks[1].locked())
        release.set()
        await asyncio.sleep(.02)
        self.assertEqual(self.dashboard.resolve_tasks, {})

    async def test_same_guild_concurrent_resolve_rejected(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow(*_, **__):
            started.set()
            await release.wait()
            return YtdlpResponseDict(self.bot.info)
        self.bot.downloader.extract_info = slow
        operation = asyncio.create_task(self.preview())
        await started.wait()
        await self.call(BASE + "resolve", {"query": "other"}, status=429)
        release.set()
        await operation

    async def test_extraction_errors_are_sanitized(self):
        self.bot.downloader.extract_info = AsyncMock(side_effect=RuntimeError("sensitive upstream detail"))
        body = await self.call(BASE + "resolve", {"query": "song"}, status=502)
        self.assertNotIn("sensitive", body["error"])
        self.bot.get_player.assert_not_awaited()

    async def test_empty_search(self):
        self.bot.info = dict(self.bot.info, entries=[])
        await self.call(BASE + "resolve", {"query": "song"}, status=404)

    async def test_validation_and_scheme_denial(self):
        for query in ("", 1, "x" * 2001, "file:///tmp/private", "mbapl://private"):
            await self.call(BASE + "resolve", {"query": query}, status=400)
        self.assertFalse(self.bot.extractions)

    async def test_compound_link_gives_explicit_video_and_playlist_choices(self):
        songs = await self.preview("https://www.youtube.com/watch?v=abc12345678&list=PLexample")
        self.assertEqual(len(songs), 2)
        self.assertEqual(self.bot.extractions[0][0], "https://www.youtube.com/watch?v=abc12345678")
        self.assertEqual(self.bot.extractions[1][0], "https://www.youtube.com/playlist?list=PLexample")
        self.assertNotIn("&list=", songs[0]["url"])
        self.bot._cmd_play_compound_link.assert_not_awaited()

    async def test_confirm_uses_real_cmd_play_with_selected_canonical_url(self):
        song, = await self.preview()
        response = await self.call(BASE + "play", self.confirm(song))
        self.assertEqual(len(response["state"]["queue"]), 4)
        self.assertEqual(self.bot.extractions[-1][0], song["url"])
        self.assertIs(self.bot.player.playlist.entries[-1].author, self.bot.owner)

    async def test_concurrent_and_later_duplicate_confirm_only_add_once(self):
        song, = await self.preview()
        first, second = await asyncio.gather(
            self.call(BASE + "play", self.confirm(song)),
            self.call(BASE + "play", self.confirm(song)))
        await self.call(BASE + "play", self.confirm(song))
        self.assertEqual(len(self.bot.player.playlist.entries), 4)
        self.assertEqual(len(self.bot.extractions), 2)
        self.assertEqual(len(first["state"]["queue"]), len(second["state"]["queue"]))

    async def test_tampered_unknown_expired_or_cross_guild_token_denied(self):
        song, = await self.preview()
        await self.call(BASE + "play", dict(self.confirm(song), query="https://example.test/other"), status=403)
        await self.call(BASE + "play", dict(self.confirm(song), preview_id="unknown"), status=409)
        preview = self.dashboard.previews[song["preview_id"]]
        preview["guild_id"] = 2
        await self.call(BASE + "play", self.confirm(song), status=409)
        preview["guild_id"], preview["expires"] = 1, time.monotonic() - 1
        await self.call(BASE + "play", self.confirm(song), status=409)
        self.bot.get_player.assert_not_awaited()

    async def test_confirm_rechecks_changed_permission_and_consumes_attempt(self):
        song, = await self.preview()
        self.bot.perms.max_song_length = 100
        await self.call(BASE + "play", self.confirm(song), status=403)
        self.bot.perms.max_song_length = 0
        await self.call(BASE + "play", self.confirm(song), status=409)
        self.assertEqual(len(self.bot.player.playlist.entries), 3)

    async def test_failed_response_after_addition_never_repeats_addition(self):
        song, = await self.preview()
        real = self.bot.cmd_play
        async def partial(**kwargs):
            await real(**kwargs)
            raise RuntimeError("after enqueue")
        self.bot.cmd_play = partial
        with self.assertLogs("musicbot.web_dashboard", level="ERROR"):
            await self.call(BASE + "play", self.confirm(song), status=500)
        await self.call(BASE + "play", self.confirm(song), status=409)
        self.assertEqual(len(self.bot.player.playlist.entries), 4)

    async def test_preview_memory_is_bounded(self):
        self.dashboard.previews = {str(i): {"expires": time.monotonic() + 100} for i in range(100)}
        await self.preview()
        self.assertEqual(len(self.dashboard.previews), 100)

    async def test_confirmation_of_playlist_uses_real_import_and_filters(self):
        short = dict(self.bot.info, title="Short", duration=60, webpage_url="https://example.test/short")
        long = dict(self.bot.info, title="Long", duration=600, webpage_url="https://example.test/long")
        self.bot.info = dict(self.bot.info, entries=[short, long], playlist_count=2)
        self.bot.perms.max_song_length = 100
        song, = await self.preview("https://example.test/playlist")
        # Single canonical URLs resolve to one item, as real extractors do.
        self.bot.info = short
        result = await self.call(BASE + "play", self.confirm(song))
        self.assertEqual([item["title"] for item in result["state"]["queue"]],
                         ["One", "Two", "Three", "Short"])

    async def test_selected_second_search_result_url_is_sent_to_play(self):
        self.bot.info = dict(self.bot.info, extractor="youtube:search", entries=[
            dict(self.bot.info, webpage_url="https://example.test/first"),
            dict(self.bot.info, webpage_url="https://example.test/second")])
        songs = await self.preview("find")
        self.bot.info = dict(self.bot.info["entries"][1])
        await self.call(BASE + "play", self.confirm(songs[1]))
        self.assertEqual(self.bot.extractions[-1][0], "https://example.test/second")

    async def test_global_resolve_limit_and_shutdown_cancel_pending_tasks(self):
        guilds = {i: NS(id=i, unavailable=False, get_member=lambda _: self.bot.owner)
                  for i in (1, 2, 3)}
        self.bot.get_guild = guilds.get
        started, release = asyncio.Event(), asyncio.Event()
        async def slow(*_, **__):
            started.set()
            await release.wait()
            return YtdlpResponseDict(self.bot.info)
        self.bot.downloader.extract_info = slow
        self.dashboard.RESOLVE_TIMEOUT = .02
        await self.call(BASE + "resolve", {"query": "one"}, status=504)
        await self.call("/api/guilds/2/resolve", {"query": "two"}, status=504)
        await self.call("/api/guilds/3/resolve", {"query": "three"}, status=429)
        tasks = list(self.dashboard.resolve_tasks.values())
        await self.dashboard.close()
        self.assertTrue(all(task.cancelled() for task in tasks))
        self.assertFalse(self.dashboard.resolve_tasks)

    async def test_keyword_colon_is_not_treated_as_a_local_uri(self):
        await self.preview("artist: title")
        self.assertEqual(self.bot.extractions[0][0], "ytsearch5:artist: title")

    async def test_missing_child_extractor_inherits_checked_parent(self):
        def check(extractor):
            if not extractor.startswith("youtube"):
                raise PermissionsError("Denied")
        self.bot.perms.can_use_extractor = check
        child = dict(self.bot.info)
        child.pop("extractor")
        self.bot.info = dict(self.bot.info, extractor="youtube:search", entries=[child])
        song, = await self.preview("query")
        self.assertTrue(song["allowed"])

    async def test_disabled_music_source_is_rejected_before_resolving(self):
        await self.call(BASE + "resolve",
                        {"query": "https://open.spotify.com/track/example"}, status=403)
        self.assertFalse(self.bot.extractions)

    async def test_canonical_source_blocklist_checked_alongside_media_url(self):
        self.bot.info["url"] = "https://cdn.example.test/audio"
        self.bot.blocked.add(self.bot.info["webpage_url"])
        song, = await self.preview("search")
        self.assertFalse(song["allowed"])
