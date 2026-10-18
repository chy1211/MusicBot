"""No-network public playlist import, resync, provider and authorization tests."""
import asyncio
import copy
import json
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import test_web_dashboard_discord as identity
from musicbot.web_dashboard import APIError
from musicbot.web_dashboard_imports import source_url, source_diff, imported_track
from musicbot.web_dashboard_library import PlaylistStore

YTM = "https://music.youtube.com/playlist?list=PLdemo"
YT = "https://www.youtube.com/playlist?list=PLdemo"
SPOTIFY = "https://open.spotify.com/playlist/ABC123"


def video(n=1):
    return {"id": "video" + str(n).zfill(6), "title": "Video " + str(n),
            "url": "https://music.youtube.com/watch?v=video" + str(n).zfill(6), "duration": 123}


def spotify(n=1):
    return {"type": "track", "id": "track" + str(n), "name": "Song " + str(n),
            "artists": [{"name": "Artist"}], "duration_ms": 123400,
            "external_urls": {"spotify": "https://open.spotify.com/track/track" + str(n)}}


class SourceTests(unittest.TestCase):
    def test_whitelist_canonicalizes_allowed_domains_and_rejects_unsafe_urls(self):
        for host in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"):
            url, kind = source_url("http://" + host + "/watch?v=video000001&list=PLdemo")
            self.assertIn("playlist?list=PLdemo", url)
            self.assertIn(kind, ("youtube", "youtube_music"))
        self.assertEqual(source_url("https://open.spotify.com/intl-zh-TW/album/ABC123?si=ignored"),
                         ("https://open.spotify.com/album/ABC123", "spotify"))
        for bad in (None, "", "file:///tmp/a", "spotify:playlist:abc", "https://spotify.link/abc",
                    "https://youtube.com.evil.test/playlist?list=abc", "https://soundcloud.com/example/?list=abc",
                    "https://youtube.com@evil.test/?list=abc", "https://u:p@youtube.com/?list=abc",
                    "https://youtube.com:123/playlist?list=abc", "https://youtube.com:bad/?list=abc",
                    "https://youtube.com/playlist?list=abc&list=other", "https://youtube.com/watch?v=video000001",
                    "https://open.spotify.com/track/ABC123", "https://open.spotify.com/playlist/a/b",
                    "https://youtube.com/playlist?list=a%0Ab"):
            with self.subTest(bad=bad), self.assertRaises(APIError):
                source_url(bad)


    def test_account_private_aliases_are_rejected_before_extraction(self):
        for ident in ("WL", "LL", "LM"):
            with self.subTest(ident=ident), self.assertRaises(APIError):
                source_url("https://music.youtube.com/playlist?list="+ident)

    def test_provider_track_urls_titles_duration_and_invalid_entries(self):
        value = imported_track(spotify(), "spotify")
        self.assertEqual(value, {"title": "Artist - Song 1", "url": "https://open.spotify.com/track/track1", "duration": 123.4})
        self.assertEqual(imported_track(video(), "youtube")["url"], "https://www.youtube.com/watch?v=video000001")
        for row in (None, {"id": "oops"}, dict(video(), title="[Private Video]"),
                    dict(video(), url="https://evil.test/watch?v=video000001")):
            self.assertIsNone(imported_track(row, "youtube"))
        self.assertIsNone(imported_track(dict(spotify(), is_local=True), "spotify"))
        self.assertIsNone(imported_track(dict(spotify(), type="episode"), "spotify"))
        self.assertIsNone(imported_track(dict(spotify(), duration_ms=float("inf")), "spotify")["duration"])

    def test_sync_diff_counts_duplicate_occurrences_without_user_data(self):
        a, b, c = ({"url": x} for x in ("a", "b", "c"))
        self.assertEqual(source_diff([a, a, b], [a, c, c]), {"added": 2, "removed": 2})


class ImportTests(unittest.IsolatedAsyncioTestCase):
    provider_token = identity.DiscordTests.provider_token
    provider_me = identity.DiscordTests.provider_me
    call = identity.DiscordTests.call
    login_as = identity.DiscordTests.login_as

    async def asyncSetUp(self):
        await identity.DiscordTests.asyncSetUp(self)
        self.temp = tempfile.TemporaryDirectory(prefix="musicbot-webtest-imports-")
        self.dashboard.playlist_store = PlaylistStore(self.temp.name)
        self.bot.member_perms.allow_playlists = True
        self.bot.downloader.extract_info = AsyncMock(return_value={"title": "Demo", "entries": [video()]})

    async def asyncTearDown(self):
        await identity.DiscordTests.asyncTearDown(self)
        self.temp.cleanup()


    async def test_private_aliases_never_reach_cookie_bearing_downloader(self):
        for ident in ("WL", "LL", "LM"):
            await self.preview("https://www.youtube.com/playlist?list="+ident,status=400)
        self.bot.downloader.extract_info.assert_not_awaited()

    async def test_nonpublic_provider_availability_never_reaches_preview(self):
        for availability in ("private", "needs_auth", "premium_only", "subscriber_only"):
            self.bot.downloader.extract_info.return_value = {"title":"Secret","availability":availability,"entries":[video()]}
            value = await self.preview(status=403)
            self.assertNotIn("Secret",str(value))


    async def test_unknown_youtube_total_is_marked_as_lower_bound(self):
        self.bot.downloader.extract_info.return_value = {"title":"Public","entries":[video(i) for i in range(201)]}
        value=await self.preview()
        self.assertEqual(value["count"],201)
        self.assertEqual(value["import_count"],200)
        self.assertTrue(value["count_is_minimum"])
        self.assertTrue(value["truncated"])

    async def test_unknown_spotify_total_with_more_pages_still_warns_truncation(self):
        self.spotify_provider([spotify(i) for i in range(200)])
        tracks=self.bot.spotify.get_playlist.return_value["tracks"]
        tracks.pop("total")
        tracks["next"]="https://api.spotify.com/v1/playlists/ABC123/tracks?offset=200"
        value=await self.preview(SPOTIFY)
        self.assertEqual(value["count"],201)
        self.assertTrue(value["count_is_minimum"])
        self.assertTrue(value["truncated"])
        self.bot.spotify.make_api_req.assert_not_awaited()

    async def library(self):
        return await self.call("/api/library", method="GET")

    async def preview(self, url=YTM, status=200):
        return await self.call("/api/guilds/1/library/import/preview", {"url": url}, status=status)

    async def confirm(self, preview, status=200):
        return await self.call("/api/library/import", {"preview_id": preview["preview_id"],
            "revision": preview["revision"], "name": "Imported"}, status=status)

    def spotify_provider(self, rows, total=None):
        self.bot.config.spotify_enabled = True
        self.bot.spotify = NS(API_BASE="https://api.spotify.com/v1/",
            get_playlist=AsyncMock(return_value={"name": "Spotify demo", "tracks": {"items": [{"track": r} for r in rows],
                "total": total or len(rows), "next": None}}),
            get_album=AsyncMock(return_value={"name": "Album", "tracks": {"items": rows, "total": len(rows)}}),
            make_api_req=AsyncMock(), api_safe_url=lambda url: url.removeprefix("https://api.spotify.com/v1/"))

    async def test_ytm_preview_import_truncation_source_roundtrip_and_one_use(self):
        self.bot.downloader.extract_info.return_value = {"title": "<img> Public list", "entries": [video(i) for i in range(205)], "playlist_count": 205}
        preview = await self.preview()
        self.assertEqual((preview["count"], preview["import_count"], len(preview["tracks"]), preview["truncated"]), (205, 200, 5, True))
        self.assertTrue(preview["warning"])
        self.bot.downloader.extract_info.assert_awaited_once()
        args, kwargs = self.bot.downloader.extract_info.call_args
        self.assertIn("playlist?list=PLdemo", args[0])
        self.assertEqual(kwargs, {"download": False, "process": False, "public_only": True})
        value = await self.confirm(preview)
        playlist = value["playlists"][-1]
        self.assertEqual(len(playlist["tracks"]), 200)
        self.assertEqual(playlist["source_url"], preview["source_url"])
        self.assertEqual(playlist["source_type"], preview["source_type"])
        self.assertEqual((await self.library())["playlists"][-1], playlist)
        await self.confirm(preview, 409)
        self.assertNotIn("owner_id", json.dumps(value))
        self.assertNotIn("guild_id", json.dumps(value))

    async def test_spotify_unavailable_capability_and_mock_playlist_album(self):
        sources = await self.call("/api/library/sources", method="GET")
        self.assertFalse(sources["spotify"])
        await self.preview(SPOTIFY, 503)
        self.bot.downloader.extract_info.assert_not_awaited()
        self.spotify_provider([spotify()])
        self.assertTrue((await self.library())["sources"]["spotify"])
        preview = await self.preview(SPOTIFY)
        self.assertEqual(preview["tracks"][0]["title"], "Artist - Song 1")
        self.assertEqual(preview["tracks"][0]["url"], "https://open.spotify.com/track/track1")
        value = await self.confirm(preview)
        self.assertEqual(value["playlists"][-1]["source_type"], "spotify")
        album = await self.preview("https://open.spotify.com/album/ABC123")
        self.assertEqual(album["title"], "Album")
        self.bot.spotify.get_album.assert_awaited_once_with("ABC123")

    async def test_spotify_bounded_pagination_and_invalid_page_url(self):
        self.spotify_provider([spotify(i) for i in range(50)], total=1000)
        self.bot.spotify.get_playlist.return_value["tracks"]["next"] = "https://api.spotify.com/v1/playlists/ABC123/tracks?offset=50"
        self.bot.spotify.make_api_req.side_effect = [
            {"items": [{"track": spotify(i)} for i in range(50, 100)], "next": "https://api.spotify.com/v1/page2"},
            {"items": [{"track": spotify(i)} for i in range(100, 150)], "next": "https://api.spotify.com/v1/page3"},
            {"items": [{"track": spotify(i)} for i in range(150, 200)], "next": "https://api.spotify.com/v1/page4"}]
        preview = await self.preview(SPOTIFY)
        self.assertEqual(preview["import_count"], 200)
        self.assertTrue(preview["truncated"])
        self.assertEqual(self.bot.spotify.make_api_req.await_count, 3)
        self.bot.spotify.get_playlist.return_value["tracks"]["next"] = "https://evil.test/api"
        await self.preview(SPOTIFY, 502)

    async def test_resync_preview_diff_revision_replacement_and_source_persists(self):
        self.bot.downloader.extract_info.return_value = {"title": "Demo", "entries": [video(1), video(1), video(2)]}
        initial = await self.confirm(await self.preview())
        pid = initial["playlists"][-1]["id"]
        self.bot.downloader.extract_info.return_value = {"title": "Updated", "entries": [video(1), video(3)]}
        preview = await self.call("/api/guilds/1/library/" + pid + "/sync/preview", {"revision": initial["revision"]})
        self.assertEqual(preview["diff"], {"added": 1, "removed": 2})
        self.assertEqual(len((await self.library())["playlists"][-1]["tracks"]), 3)
        result = await self.call("/api/library/" + pid + "/sync", {"preview_id": preview["preview_id"], "revision": preview["revision"]})
        self.assertEqual([t["title"] for t in result["playlists"][-1]["tracks"]], ["Video 1", "Video 3"])
        self.assertEqual(result["playlists"][-1]["name"], "Imported")
        self.assertEqual(result["playlists"][-1]["source_url"], preview["source_url"])
        await self.call("/api/guilds/1/library/" + pid + "/sync/preview", {"revision": initial["revision"]}, status=409)
        await self.call("/api/guilds/1/library/favorites/sync/preview", {"revision": result["revision"]}, status=400)

    async def test_import_limit_revision_conflict_and_source_schema_corrupt_quarantine(self):
        pending = await self.preview()
        await self.call("/api/library", {"name": "Concurrent"})
        await self.confirm(pending, 409)
        for i in range(19):
            await self.call("/api/library", {"name": "List " + str(i)})
        await self.preview(status=400)
        store = self.dashboard.playlist_store
        with store.path(43).open(encoding="utf-8") as stream:
            raw = json.load(stream)
        raw["playlists"][-1].update(source_url="https://evil.test/", source_type="youtube")
        store.path(43).write_text(json.dumps(raw), encoding="utf-8")
        await self.call("/api/library", method="GET", status=409)
        self.assertEqual(len(list(store.root.glob("*.corrupt-*"))), 1)

    async def test_preview_confirm_ownership_session_header_origin_and_blocked(self):
        pending = await self.preview()
        self.login_as(44)
        await self.confirm(pending, 409)
        self.login_as(43)
        await self.call("/api/library/import", {"preview_id": pending["preview_id"], "revision": pending["revision"], "name": "No"},
            status=403, headers={"X-MusicBot-Dashboard": "1", "Origin": "https://evil.test"})
        self.bot.blocked_users.add(43)
        await self.confirm(pending, 403)
        self.bot.blocked_users.clear()
        self.login_as(43)
        self.bot.members.pop(43)
        await self.confirm(pending, 403)
        self.client.session.cookie_jar.clear()
        await self.preview(status=401)

    async def test_preview_fields_whitelist_blocklist_errors_and_privacy(self):
        await self.preview("https://evil.test/list", 400)
        self.bot.downloader.extract_info.assert_not_awaited()
        await self.call("/api/guilds/1/library/import/preview", {"url": YTM, "path": "/secret"}, status=400)
        normalized, _ = source_url(YTM)
        self.bot.blocked.add(normalized)
        await self.preview(status=403)
        self.bot.blocked.clear()
        self.bot.downloader.extract_info.side_effect = RuntimeError("PRIVATE INTERNAL EXCEPTION")
        result = await self.preview(status=502)
        self.assertNotIn("PRIVATE", json.dumps(result))
        await self.call("/api/library/sources", method="GET", headers={}, status=403)

    async def test_resolve_and_import_share_rate_admission_and_timeout_slots(self):
        await self.preview()
        before = sum(len(v) for v in self.dashboard.rate_limits.values())
        self.assertEqual(before, 1)
        self.dashboard.user_rate_limit(self.bot.member)
        self.assertEqual(sum(len(v) for v in self.dashboard.rate_limits.values()), 2)
        waiting = asyncio.Event()
        async def delay(*args, **kwargs):
            await waiting.wait()
            return {"title": "Demo", "entries": [video()]}
        self.bot.downloader.extract_info.side_effect = delay
        self.dashboard.RESOLVE_TIMEOUT = 0.01
        await self.preview(status=504)
        self.assertNotIn(1, self.dashboard.resolve_tasks)
        await self.preview(status=504)
        self.assertNotIn(1, self.dashboard.resolve_tasks)
        waiting.set()
        self.dashboard.RESOLVE_TIMEOUT = 1
        await self.preview()
        self.assertNotIn(1, self.dashboard.resolve_tasks)

    async def test_spotify_stored_url_reaches_existing_cmd_play_and_permission_rechecked(self):
        self.spotify_provider([spotify()])
        value = await self.confirm(await self.preview(SPOTIFY))
        pid = value["playlists"][-1]["id"]
        # FakeBot uses MusicBot.cmd_play/_cmd_play with extraction mocked offline.
        self.bot.downloader.extract_info = self.bot.extract
        result = await self.call("/api/guilds/1/library/" + pid + "/play", {"revision": value["revision"]})
        self.assertEqual(result["added"], 1)
        self.assertTrue(any(q == "https://open.spotify.com/track/track1" for q, _ in self.bot.extractions))
        self.bot.member_perms.can_use_command.return_value = False
        result = await self.call("/api/guilds/1/library/" + pid + "/play", {"revision": value["revision"]})
        self.assertEqual(result["added"], 0)

    async def test_expired_preview_and_changed_membership_after_async_provider(self):
        preview = await self.preview()
        self.dashboard.import_previews[preview["preview_id"]]["expires"] = 0
        await self.confirm(preview, 409)
        async def leave(*args, **kwargs):
            self.bot.members.pop(43)
            return {"title": "Demo", "entries": [video()]}
        self.bot.downloader.extract_info.side_effect = leave
        await self.preview(status=403)

class PublicDownloaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_branch_never_uses_normal_credentials_headers_or_spotify(self):
        from musicbot.downloader import Downloader
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool:
            regular = AsyncMock(side_effect=AssertionError("Ordinary extraction forbidden"))
            headers = AsyncMock(side_effect=AssertionError("Ordinary headers forbidden"))
            downloader = NS(thread_pool=pool,_filtered_extract_info=regular,get_url_headers=headers)
            downloader.extract_public_playlist = lambda url, limit=201: Downloader.extract_public_playlist(downloader,url,limit)
            class FakePublic:
                def __init__(self, options):
                    self.options = options
                    captured.update(options)
                def __enter__(self): return self
                def __exit__(self,*_args): pass
                def extract_info(self,url,**kwargs):
                    self.asserted = kwargs
                    assert kwargs=={"download":False,"process":False}
                    return {"title":"Public","playlist_count":999999,"entries":(video(i) for i in range(999999))}
                def sanitize_info(self,value): return value
            captured={}
            with patch("musicbot.downloader.DashboardYoutubeDL",FakePublic):
                value=await Downloader.extract_info(downloader,YT,download=False,process=False,public_only=True)
            regular.assert_not_awaited();headers.assert_not_awaited()
            self.assertIsNone(captured["cookiefile"]);self.assertIsNone(captured["cookiesfrombrowser"])
            self.assertFalse(captured["usenetrc"]);self.assertFalse(captured["cachedir"])
            self.assertEqual(len(value.data["entries"]),201)
            self.assertEqual(captured["playlistend"],201)
            with patch("musicbot.downloader.DashboardYoutubeDL",FakePublic):
                mix=await Downloader.extract_info(downloader,YT,download=False,process=False,public_only=True,public_limit=25)
            self.assertEqual(len(mix.data["entries"]),25)
            self.assertEqual(captured["playlistend"],25)
            self.assertIsNone(captured["cookiefile"])


    async def test_default_extraction_does_not_enter_public_branch(self):
        from musicbot.downloader import Downloader
        called=AsyncMock(side_effect=AssertionError("Default path reached"))
        public=AsyncMock(side_effect=AssertionError("Public branch must be opt-in"))
        downloader=NS(bot=NS(config=NS(enable_local_media=False)),_filtered_extract_info=called,extract_public_playlist=public)
        with self.assertRaisesRegex(AssertionError,"Default path reached"):
            await Downloader.extract_info(downloader,YT,download=False,process=False)
        called.assert_awaited_once();public.assert_not_awaited()
