"""Round 4 offline tests use the real cmd_play and Playlist boundaries."""
import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import test_web_dashboard as base
import test_web_dashboard_discord as discord
from test_web_dashboard import BASE
from musicbot.downloader import YtdlpResponseDict
from musicbot.exceptions import PermissionsError
from musicbot.web_dashboard import CONFIRMED_ENTRY_CHECK, public_url


def playlist(bot, count=5, blocked=()):
    children = [dict(bot.info, title=f"Song {i}", duration=60,
                     webpage_url=f"https://soundcloud.com/example/song/{i}", id=str(i))
                for i in range(1, count + 1)]
    for i in blocked:
        children[i - 1]["title"] = "[Private video]"
    parent = dict(bot.info, title="Playlist", entries=children, playlist_count=count)
    async def extract(query, **kwargs):
        bot.extractions.append((query, kwargs))
        child = next((child for child in children if query == child["webpage_url"]), None)
        return YtdlpResponseDict(child or parent)
    bot.downloader.extract_info = extract
    return children


class Round4Tests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = base.DashboardTests.asyncSetUp
    asyncTearDown = base.DashboardTests.asyncTearDown
    call = base.DashboardTests.call

    async def preview(self, count=5, blocked=()):
        playlist(self.bot, count, blocked)
        return (await self.call(BASE + "resolve", {"query": "https://soundcloud.com/example/playlist"}))["results"][0]

    def selection(self, song, ids=None):
        return {"query": song["url"], "preview_id": song["preview_id"],
                "selected_items": ids if ids is not None else [
                    item["item_id"] for item in song["entries"] if item["allowed"]]}

    async def test_requester_display_name_avatar_and_minimal_fields(self):
        self.bot.owner.display_name = "顯示名稱"
        self.bot.owner.display_avatar = NS(url="https://cdn.discordapp.com/avatars/example.png")
        result = await self.call(BASE + "state", method="GET")
        for item in [result["current"], *result["queue"]]:
            self.assertEqual(item["requester"], {
                "name": "顯示名稱", "avatar": "https://cdn.discordapp.com/avatars/example.png"})
            self.assertEqual(set(item["requester"]), {"name", "avatar"})

    async def test_autoplay_requester(self):
        self.bot.player.current_entry.author = None
        self.bot.player.current_entry.channel = None
        result = await self.call(BASE + "state", method="GET")
        self.assertEqual(result["current"]["requester"]["name"], "自動播放")

    async def test_departed_member_retains_cached_display_name(self):
        left = NS(id=99, name="old", display_name="離開的成員", display_avatar=NS(url="javascript:bad"))
        self.bot.player.playlist.entries[0].author = left
        result = await self.call(BASE + "state", method="GET")
        self.assertEqual(result["queue"][0]["requester"], {"name": "離開的成員", "avatar": ""})

    async def test_restored_author_missing_and_legacy_meta_member(self):
        self.bot.player.playlist.entries[0].author = None
        self.bot.player.playlist.entries[0].channel = self.bot.channel
        self.bot.player.playlist.entries[1].author = None
        self.bot.player.playlist.entries[1].meta = {"member": NS(name="Meta member")}
        result = await self.call(BASE + "state", method="GET")
        self.assertIn("無法取得", result["queue"][0]["requester"]["name"])
        self.assertEqual(result["queue"][1]["requester"]["name"], "Meta member")

    async def test_current_queue_and_cover_links_are_filtered(self):
        for url in ("javascript:evil", "file:///secret", "//example.test/song", "https://u:p@example.test/song",
                    "http:///broken", "https://[bad", "https://example.test:bad", "https://soundcloud.com/example/\nsecret"):
            self.assertEqual(public_url(url), "", url)
            self.bot.player.current_entry.url = url
            self.bot.player.current_entry.thumbnail_url = url
            result = await self.call(BASE + "state", method="GET")
            self.assertEqual(result["current"]["url"], "")
            self.assertEqual(result["current"]["thumbnail"], "")
        self.assertEqual(public_url("https://soundcloud.com/example/song"), "https://soundcloud.com/example/song")

    async def test_playlist_all_allowed_and_partial_order_is_source_order(self):
        song = await self.preview()
        result = await self.call(BASE + "play", self.selection(song, ["5", "2", "4"]))
        self.assertEqual((result["added"], result["skipped"]), (3, 0))
        self.assertEqual([e.title for e in self.bot.player.playlist.entries][-3:],
                         ["Song 2", "Song 4", "Song 5"])

    async def test_playlist_select_all(self):
        song = await self.preview()
        result = await self.call(BASE + "play", self.selection(song))
        self.assertEqual((result["added"], result["skipped"]), (5, 0))
        self.assertEqual([item["item_id"] for item in result["results"]], ["1", "2", "3", "4", "5"])

    async def test_invalid_and_foreign_selections_rejected_before_play(self):
        song = await self.preview()
        for ids, status in ((["https://arbitrary.test"], 403), (["6"], 403), ([], 400),
                            (["1", "1"], 400), ([1], 400), ([True], 400), ("1", 400)):
            await self.call(BASE + "play", self.selection(song, ids), status=status)
        await self.call(BASE + "play", {"query": song["url"], "selected_items": ["1"]}, status=400)
        self.assertEqual(len(self.bot.player.playlist.entries), 3)

    async def test_blocked_item_rejected_even_when_other_items_allowed(self):
        song = await self.preview(blocked=(2,))
        self.assertFalse(song["entries"][1]["allowed"])
        await self.call(BASE + "play", self.selection(song, ["1", "2"]), status=403)
        self.assertEqual(len(self.bot.player.playlist.entries), 3)

    async def test_maxsongs_allows_partial_success_and_reports_reason(self):
        self.bot.perms.max_songs = 5
        song = await self.preview()
        self.assertTrue(song["allowed"])
        result = await self.call(BASE + "play", self.selection(song))
        self.assertEqual((result["added"], result["skipped"]), (2, 3))
        self.assertTrue(all(item["reason"] for item in result["results"][2:]))
        self.assertEqual(self.bot.player.playlist.count_for_user(self.bot.owner), 5)
        self.assertIn("已加入 2 首", result["message"])

    async def test_no_playlist_permission_forbids_even_one_selection(self):
        song = await self.preview()
        self.bot.perms.allow_playlists = False
        await self.call(BASE + "play", self.selection(song, ["1"]), status=403)
        self.assertEqual(len(self.bot.player.playlist.entries), 3)

    async def test_no_playlist_permission_single_entry_list_is_also_denied(self):
        self.bot.perms.allow_playlists = False
        song = await self.preview(count=1)
        self.assertFalse(song["allowed"])
        await self.call(BASE + "play", self.selection(song, ["1"]), status=403)

    async def test_changed_playlist_length_permission_rejected(self):
        song = await self.preview()
        self.bot.perms.max_playlist_length = 3
        await self.call(BASE + "play", self.selection(song, ["1"]), status=403)

    async def test_fresh_length_and_blocklist_checks_per_item(self):
        song = await self.preview()
        children = playlist(self.bot)
        children[1]["duration"] = 86520
        self.bot.perms.max_song_length = 100
        self.bot.blocked.add("Song 3")
        result = await self.call(BASE + "play", self.selection(song))
        self.assertEqual((result["added"], result["skipped"]), (3, 2))
        self.assertIn("長度", result["results"][1]["reason"])
        self.assertIn("封鎖", result["results"][2]["reason"])
        self.assertIsNone(CONFIRMED_ENTRY_CHECK.get())

    async def test_child_cannot_expand_into_another_playlist(self):
        song = await self.preview()
        self.bot.downloader.extract_info = AsyncMock(return_value=YtdlpResponseDict(
            dict(self.bot.info, entries=[dict(self.bot.info)] * 2)))
        result = await self.call(BASE + "play", self.selection(song, ["1"]))
        self.assertEqual((result["added"], result["skipped"]), (0, 1))
        self.assertIn("單曲解析成播放清單", result["results"][0]["reason"])
        self.assertEqual(len(self.bot.player.playlist.entries), 3)

    async def test_preview_caps_at_200_and_explains_truncation(self):
        song = await self.preview(205)
        self.assertEqual(len(song["entries"]), 200)
        self.assertEqual((song["count"], song["checked_count"]), (205, 200))
        self.assertTrue(song["truncated"])
        self.assertIn("200", song["warning"])
        await self.call(BASE + "play", self.selection(song, ["201"]), status=403)

    async def test_replayed_selection_idempotent_and_changed_selection_conflicts(self):
        song = await self.preview()
        data = self.selection(song, ["2", "4"])
        first = await self.call(BASE + "play", data)
        second = await self.call(BASE + "play", data)
        self.assertEqual((first["added"], second["added"]), (2, 2))
        self.assertEqual(len(self.bot.player.playlist.entries), 5)
        await self.call(BASE + "play", self.selection(song, ["1"]), status=409)

    async def test_concurrent_batch_confirmation_only_enqueues_once(self):
        song = await self.preview()
        a, b = await asyncio.gather(*[self.call(BASE + "play", self.selection(song)) for _ in range(2)])
        self.assertEqual((a["added"], b["added"]), (5, 5))
        self.assertEqual(len(self.bot.player.playlist.entries), 8)

    async def test_per_song_timeout_reports_skips_and_clears_context(self):
        song = await self.preview(2)
        self.dashboard.SONG_TIMEOUT = .01
        async def slow(**kwargs):
            await asyncio.sleep(1)
        self.bot.cmd_play = slow
        result = await self.call(BASE + "play", self.selection(song))
        self.assertEqual((result["added"], result["skipped"]), (0, 2))
        self.assertIn("逾時", result["results"][0]["reason"])
        self.assertIsNone(CONFIRMED_ENTRY_CHECK.get())

    async def test_partial_add_then_response_failure_not_repeated(self):
        song = await self.preview(2)
        real = self.bot.cmd_play
        async def fail(**kwargs):
            await real(**kwargs)
            raise RuntimeError("sensitive detail")
        self.bot.cmd_play = fail
        result = await self.call(BASE + "play", self.selection(song))
        self.assertEqual((result["added"], result["skipped"]), (2, 0))
        self.assertNotIn("sensitive", str(result))
        await self.call(BASE + "play", self.selection(song))
        self.assertEqual(len(self.bot.player.playlist.entries), 5)

    async def test_unrelated_native_addition_is_not_counted_as_selected_song(self):
        song = await self.preview(1)
        async def native_then_fail(**kwargs):
            self.bot.player.playlist.entries.append(base.entry("Native", author=self.bot.owner))
            raise RuntimeError("before selected enqueue")
        self.bot.cmd_play = native_then_fail
        result = await self.call(BASE + "play", self.selection(song))
        self.assertEqual((result["added"], result["skipped"]), (0, 1))
        self.assertEqual(self.bot.player.playlist.entries[-1].title, "Native")

    async def test_full_queue_after_extraction_is_rechecked(self):
        song = await self.preview(1)
        self.bot.perms.max_songs = 4
        real = self.bot.downloader.extract_info
        async def concurrent_add(*args, **kwargs):
            info = await real(*args, **kwargs)
            self.bot.player.playlist.entries.append(base.entry("Native", author=self.bot.owner))
            return info
        self.bot.downloader.extract_info = concurrent_add
        result = await self.call(BASE + "play", self.selection(song))
        self.assertEqual((result["added"], result["skipped"]), (0, 1))
        self.assertIn("上限", result["results"][0]["reason"])
        self.assertEqual(len(self.bot.player.playlist.entries), 4)

    async def test_native_play_outside_batch_is_unaffected(self):
        await self.preview()
        self.bot.info = dict(self.bot.info, title="Native")
        self.bot.downloader.extract_info = self.bot.extract
        await self.call(BASE + "play", {"query": "native"})
        self.assertEqual(self.bot.player.playlist.entries[-1].title, "Native")

    async def test_common_denials_are_traditional_chinese(self):
        self.bot.perms.remove = False
        self.bot.player.playlist.entries[0].author = NS(id=99)
        result = await self.call(BASE + "queue/1", {
            "revision": self.dashboard.snapshot(self.bot.guild)["revision"]}, method="DELETE", status=403)
        self.assertIn("只能刪除自己", result["error"])
        self.assertNotIn("You do not have", result["error"])


class Round4DiscordTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = discord.DiscordTests.asyncSetUp
    asyncTearDown = discord.DiscordTests.asyncTearDown
    call = discord.DiscordTests.call
    login_as = discord.DiscordTests.login_as
    provider_token = discord.DiscordTests.provider_token
    provider_me = discord.DiscordTests.provider_me

    async def test_batch_counts_as_one_play_rate_limit_attempt(self):
        self.dashboard.USER_REQUESTS_PER_MINUTE = 2
        playlist(self.bot, 5)
        song = (await self.call(BASE + "resolve", {"query": "https://soundcloud.com/example/playlist"}))["results"][0]
        result = await self.call(BASE + "play", {"query": song["url"],
            "preview_id": song["preview_id"], "selected_items": ["1", "2", "3", "4", "5"]})
        self.assertEqual(result["added"], 5)
        self.assertEqual(len(self.dashboard.rate_limits[43]), 2)
        await self.call(BASE + "play", {"query": "another"}, status=429)

    async def test_session_revoked_during_batch_does_not_return_state(self):
        playlist(self.bot, 2)
        song = (await self.call(BASE + "resolve", {"query": "https://soundcloud.com/example/playlist"}))["results"][0]
        real = self.bot.downloader.extract_info
        async def revoked(*args, **kwargs):
            self.dashboard.sessions.clear()
            return await real(*args, **kwargs)
        self.bot.downloader.extract_info = revoked
        await self.call(BASE + "play", {"query": song["url"],
            "preview_id": song["preview_id"], "selected_items": ["1", "2"]}, status=401)
        self.assertEqual(len(self.bot.player.playlist.entries), 3)
