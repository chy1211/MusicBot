"""Offline personal library storage and real batch-command integration."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from test_web_dashboard import BASE
import test_web_dashboard_discord as identity
from musicbot.web_dashboard import APIError, CONFIRMED_ENTRY_CHECK
from musicbot.web_dashboard_library import PlaylistStore, song

TRACK = {"title": "Saved", "url": "https://example.test/saved", "duration": 1}


class StoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PlaylistStore(self.temp.name)

    async def test_atomic_fsync_replace_and_no_identifier(self):
        with patch("musicbot.web_dashboard_library.os.fsync", wraps=__import__("os").fsync) as sync, patch(
                "musicbot.web_dashboard_library.os.replace", wraps=__import__("os").replace) as replace:
            result = await self.store.transact(42, lambda v: v["playlists"][0]["tracks"].append(song(TRACK)))
        self.assertEqual(sync.call_count, 2)
        replace.assert_called_once()
        self.assertNotIn("user_id", json.dumps(result))
        self.assertEqual(set(result["playlists"][0]["tracks"][0]), {"title", "url", "duration", "added_at"})
        self.assertEqual(len(list(Path(self.temp.name).iterdir())), 1)

    async def test_isolated_and_serialized(self):
        await asyncio.gather(*(self.store.transact(42, lambda v: v["playlists"][0]["tracks"].append(song(TRACK))) for _ in range(20)))
        self.assertEqual(len((await self.store.transact(42))["playlists"][0]["tracks"]), 1)
        self.assertEqual((await self.store.transact(43))["playlists"][0]["tracks"], [])

    async def test_corruption_quarantines_original_and_does_not_write_new(self):
        raw = b"{broken"
        self.store.path(42).write_bytes(raw)
        with self.assertRaises(APIError):
            await self.store.transact(42, lambda _: None)
        self.assertFalse(self.store.path(42).exists())
        self.assertEqual(next(Path(self.temp.name).glob("*.corrupt-*")).read_bytes(), raw)

    async def test_replace_failure_preserves_original_and_cleans_temp(self):
        await self.store.transact(42, lambda _: None)
        raw = self.store.path(42).read_bytes()
        with patch("musicbot.web_dashboard_library.os.replace", side_effect=OSError("failure")):
            with self.assertRaises(OSError):
                await self.store.transact(42, lambda v: v["playlists"][0]["tracks"].append(song(TRACK)))
        self.assertEqual(self.store.path(42).read_bytes(), raw)
        self.assertEqual(len(list(Path(self.temp.name).iterdir())), 1)

    async def test_url_and_duration_validation(self):
        for url in ("file:///bad", "javascript:bad", "https://u:p@example.test", "https://example.test/\nsecret",
                    "http://", "https://example.test/" + "x"*2000):
            with self.assertRaises(APIError):
                song(dict(TRACK, url=url))
        for length in (-1, True, float("nan"), float("inf"), "1"):
            with self.assertRaises(APIError):
                song(dict(TRACK, duration=length))
        self.assertIsNone(song(dict(TRACK, duration=None))["duration"])


class LibraryTests(unittest.IsolatedAsyncioTestCase):
    provider_token = identity.DiscordTests.provider_token
    provider_me = identity.DiscordTests.provider_me
    call = identity.DiscordTests.call
    login_as = identity.DiscordTests.login_as

    async def asyncSetUp(self):
        await identity.DiscordTests.asyncSetUp(self)
        self.temp = tempfile.TemporaryDirectory()
        self.dashboard.playlist_store = PlaylistStore(self.temp.name)
        self.bot.member_perms.allow_playlists = True

    async def asyncTearDown(self):
        await identity.DiscordTests.asyncTearDown(self)
        self.temp.cleanup()

    async def get(self):
        return await self.call("/api/library", method="GET")

    async def add(self, pid="favorites", track=None):
        value = await self.get()
        return await self.call("/api/library/" + pid + "/tracks",
                               {"revision": value["revision"], "track": track or TRACK})

    async def test_crud_reorder_favorites_and_minimal_fields(self):
        v = await self.call("/api/library", {"name": "Study"})
        pid = v["playlists"][1]["id"]
        await self.add(pid)
        v = await self.add(pid, dict(TRACK, title="Second"))
        v = await self.call("/api/library/" + pid, {"revision": v["revision"], "action": "move", "index": 1, "to": 0}, "PATCH")
        self.assertEqual(v["playlists"][1]["tracks"][0]["title"], "Second")
        v = await self.call("/api/library/" + pid, {"revision": v["revision"], "name": "Renamed"}, "PATCH")
        self.assertEqual(v["playlists"][1]["name"], "Renamed")
        v = await self.call("/api/library/" + pid, {"revision": v["revision"], "action": "remove", "index": 0}, "PATCH")
        self.assertEqual(len(v["playlists"][1]["tracks"]), 1)
        v = await self.call("/api/library/" + pid, {"revision": v["revision"]}, "DELETE")
        self.assertEqual(len(v["playlists"]), 1)
        await self.call("/api/library/favorites", {"revision": v["revision"]}, "DELETE", 400)
        await self.call("/api/library/favorites", {"revision": v["revision"], "name": "No"}, "PATCH", 400)

    async def test_limits_and_conflict(self):
        await self.call("/api/library", {"name": "x"*61}, status=400)
        for i in range(20):
            await self.call("/api/library", {"name": str(i)})
        await self.call("/api/library", {"name": "overflow"}, status=400)
        store = self.dashboard.playlist_store
        await store.transact(43, lambda v: v["playlists"][0].update(tracks=[song(dict(TRACK,url=f"https://example.test/saved/{i}")) for i in range(200)]))
        v = await self.get()
        await self.call("/api/library/favorites/tracks", {"revision": v["revision"], "track": TRACK}, status=400)
        await self.call("/api/library/favorites", {"revision": "stale", "action": "remove", "index": 0}, "PATCH", 409)

    async def test_other_user_cannot_read_write_and_server_generates_filename(self):
        v = await self.call("/api/library", {"name": "Private"})
        pid = v["playlists"][1]["id"]
        self.login_as(44)
        other = await self.get()
        self.assertEqual(len(other["playlists"]), 1)
        await self.call("/api/library/" + pid, {"revision": other["revision"], "name": "Stolen"}, "PATCH", 404)
        await self.call("/api/library", {"name": "No", "user_id": "43"}, status=400)
        self.assertNotIn("43", json.dumps(other))
        self.assertNotIn("user_id", other)

    async def test_header_origin_session_membership_blocklist(self):
        await self.call("/api/library", method="GET", status=403, headers={})
        await self.call("/api/library", {"name": "No"}, status=403, headers={"X-MusicBot-Dashboard": "1", "Origin": "https://foreign.test"})
        self.bot.blocked_users.add(43)
        await self.call("/api/library", method="GET", status=403)
        self.bot.blocked_users.clear()
        self.login_as(43)
        self.bot.members.pop(43)
        await self.call("/api/library", method="GET", status=403)
        self.client.session.cookie_jar.clear()
        await self.call("/api/library", method="GET", status=401)

    async def test_full_partial_real_hook_maxsongs_and_length(self):
        await self.add()
        v = await self.add(track=dict(TRACK, title="Second", url="https://example.test/second"))
        self.bot.member_perms.max_songs = 1
        result = await self.call(BASE + "library/favorites/play", {"revision": v["revision"]})
        self.assertEqual((result["added"], result["skipped"]), (1, 1))
        self.assertIn("上限", result["results"][1]["reason"])
        self.assertIsNone(CONFIRMED_ENTRY_CHECK.get())
        self.bot.member_perms.max_songs = 0
        self.bot.member_perms.max_song_length = 10
        result = await self.call(BASE + "library/favorites/play", {"revision": v["revision"], "selected_items": ["1"]})
        self.assertEqual((result["added"], result["skipped"]), (0, 1))
        self.assertIn("長度", result["results"][0]["reason"])

    async def test_command_voice_playlist_limits_and_expansion(self):
        v = await self.add()
        self.bot.member_perms.can_use_command.return_value = False
        r = await self.call(BASE + "library/favorites/play", {"revision": v["revision"]})
        self.assertEqual(r["added"], 0)
        self.bot.member_perms.can_use_command.return_value = True
        self.bot.member_perms.allow_playlists = False
        await self.call(BASE + "library/favorites/play", {"revision": v["revision"]}, status=403)
        self.bot.member_perms.allow_playlists = True
        self.bot.member.voice = None
        r = await self.call(BASE + "library/favorites/play", {"revision": v["revision"]})
        self.assertEqual(r["added"], 0)

    async def test_cross_guild_same_library_checks_target_membership(self):
        v = await self.add()
        self.bot.get_guild = lambda gid: NS(id=2, unavailable=False, get_member=lambda uid: None) if gid == 2 else self.bot.guild
        await self.call("/api/guilds/2/library/favorites/play", {"revision": v["revision"]}, status=403)

    async def test_invalid_selection_and_stale_revision(self):
        v = await self.add()
        for selected in ([], ["99"], ["0", "0"], [0], "0"):
            await self.call(BASE + "library/favorites/play", {"revision": v["revision"], "selected_items": selected}, status=400)
        await self.call(BASE + "library/favorites/play", {"revision": "stale"}, status=409)
