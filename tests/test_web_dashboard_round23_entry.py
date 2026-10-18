"""Web entry authorization regressions with fake providers and real commands."""
import asyncio
import unittest
from types import MethodType
from musicbot.bot import MusicBot

import test_web_dashboard_discord as fixtures
from test_web_dashboard import BASE, HEADERS, NS


class EntryAuthorization(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.DiscordTests.asyncSetUp
    asyncTearDown = fixtures.DiscordTests.asyncTearDown
    call = fixtures.DiscordTests.call
    login_as = fixtures.DiscordTests.login_as
    provider_token = fixtures.DiscordTests.provider_token
    provider_me = fixtures.DiscordTests.provider_me

    async def reject_during_resolution(self, action, mode, change):
        self.bot.cmd_playnext = MethodType(MusicBot.cmd_playnext, self.bot)
        query = "https://soundcloud.com/example/song"
        data = {"query": query}
        if mode == "confirmed":
            song = (await self.call(BASE + "resolve", {"query": query, "action": action}))["results"][0]
            data = {"query": song["url"], "preview_id": song["preview_id"]}
        before = list(self.bot.player.playlist.entries)
        started, release = asyncio.Event(), asyncio.Event()
        original = self.bot.downloader.extract_info
        calls = 0
        async def extract(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == (2 if mode == "legacy_confirmation" else 1):
                started.set()
                await release.wait()
            return await original(*args, **kwargs)
        self.bot.downloader.extract_info = extract
        pending = asyncio.create_task(self.client.post(BASE + action, json=data,
            headers=dict(HEADERS, Origin=self.origin)))
        try:
            await asyncio.wait_for(started.wait(), 2)
            if change == "logout":
                await self.call("/auth/logout-all", {})
                expected = 401
            elif change == "membership":
                self.bot.members.pop(43)
                expected = 403
            elif change == "permission":
                self.bot.member_perms.can_use_command.return_value = False
                expected = 403
            else:
                self.bot.member.voice.channel = NS(id=11)
                expected = 403
            release.set()
            response = await asyncio.wait_for(pending, 2)
            body = await response.json()
            self.assertEqual(response.status, expected, body)
            self.assertEqual(list(self.bot.player.playlist.entries), before)
            self.bot.serialize_queue.assert_not_awaited()
            self.assertFalse(self.dashboard.resolve_tasks)
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


def authorization_case(action, mode, change):
    async def test(self):
        await self.reject_during_resolution(action, mode, change)
    return test


for _action in ("play", "playnext"):
    for _mode in ("legacy_preview", "legacy_confirmation", "confirmed"):
        for _change in ("logout", "membership", "permission", "voice"):
            setattr(EntryAuthorization, "test_" + "_".join((_action, _mode, _change)),
                    authorization_case(_action, _mode, _change))


import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from musicbot.downloader import Downloader
from musicbot.exceptions import MusicbotException
from musicbot.web_dashboard import APIError
from musicbot.web_dashboard_extraction import (
    WEB_EXTRACTION, WEB_POOL, DashboardYoutubeDL, UnsupportedDashboardURL,
    check_subject, normalize_query,
)
from musicbot.web_dashboard_imports import source_url
import test_web_dashboard_library as library_fixtures


class LocalMediaBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="musicbot-webtest-local-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.media = self.root / "media"
        self.media.mkdir()
        self.outside = self.root / "media-adjacent"
        self.outside.mkdir()
        self.downloader = Downloader.__new__(Downloader)
        self.downloader.bot = NS(config=NS(media_file_dir=self.media))

    def media_info(self, path):
        return self.downloader._return_local_media("file://" + str(path))

    def test_in_root_relative_absolute_and_symlink_still_work(self):
        target = self.media / "song.mp3"
        target.write_bytes(b"fake audio")
        link = self.media / "inside.mp3"
        link.symlink_to(target)
        for path in (Path("song.mp3"), target, link):
            with self.subTest(path=path):
                self.assertEqual(self.media_info(path)["__expected_filename"], str(target.resolve()))

    def test_adjacent_same_prefix_is_rejected_even_with_inside_namesake(self):
        (self.media / "song.mp3").write_bytes(b"inside")
        target = self.outside / "song.mp3"
        target.write_bytes(b"outside")
        with self.assertRaises(MusicbotException):
            self.media_info(target)

    def test_file_symlink_outside_is_rejected(self):
        target = self.outside / "song.mp3"
        target.write_bytes(b"outside")
        link = self.media / "link.mp3"
        link.symlink_to(target)
        with self.assertRaises(MusicbotException):
            self.media_info(link)

    def test_directory_symlink_outside_is_rejected(self):
        target = self.outside / "song.mp3"
        target.write_bytes(b"outside")
        (self.media / "escape").symlink_to(self.outside, target_is_directory=True)
        with self.assertRaises(MusicbotException):
            self.media_info(Path("escape/song.mp3"))

    def test_parent_traversal_is_rejected(self):
        target = self.outside / "song.mp3"
        target.write_bytes(b"outside")
        with self.assertRaises(MusicbotException):
            self.media_info(Path("../media-adjacent/song.mp3"))


ALIASES = ("WL", "LL", "LM", "HL", "FL", "FV", "FAVORITES")
HOSTS = ("www.youtube.com", "music.youtube.com", "m.youtube.com", "youtu.be",
         "www.youtu.be", "www.youtube-nocookie.com", "YOUTUBE.COM.")
LOCAL_INPUTS = (
    "file:///tmp/song.mp3", "FILE:/tmp/song.mp3", "<file://song.mp3>",
    "file:relative.mp3", "mbapl://saved", "data:audio/mp3;base64,ZmFrZQ==",
    "/tmp/song.mp3", "./song.mp3", "../media/song.mp3", "~/song.mp3",
    r"C:\media\song.mp3", "C:/media/song.mp3", "C:relative.mp3",
    r"\\server\share\song.mp3", "media/song.mp3", "song.mp3",
)


class EntrySourcePolicy(unittest.TestCase):
    def test_local_schemes_and_paths_are_never_searches(self):
        for value in LOCAL_INPUTS:
            with self.subTest(value=value), self.assertRaises(UnsupportedDashboardURL):
                normalize_query(value)

    def test_aliases_all_hosts_watch_short_and_repeated_list_parameters(self):
        for host in HOSTS:
            for ident in ALIASES:
                for path in ("/playlist?list=", "/watch?v=video000001&list=",
                             "/video000001?list=", "/playlist?list=PLpublic&list="):
                    url = "https://" + host + path + ident
                    with self.subTest(url=url), self.assertRaises(UnsupportedDashboardURL):
                        check_subject(url)
                    with self.assertRaises(APIError):
                        source_url(url)

    def test_account_feed_aliases_are_rejected(self):
        for path in ("history", "watch_later", "liked_videos", "library", "you",
                     "playlists", "subscriptions"):
            with self.subTest(path=path), self.assertRaises(UnsupportedDashboardURL):
                normalize_query("https://www.youtube.com/feed/" + path)

    def test_nested_aliases_are_rejected_before_provider_access(self):
        with DashboardYoutubeDL({"quiet": True}) as client:
            with patch.object(client, "urlopen", side_effect=AssertionError("network")) as network:
                for ident in ALIASES:
                    with self.assertRaises(UnsupportedDashboardURL):
                        client.extract_info("https://youtu.be/video000001?list=" + ident,
                                            download=False)
            network.assert_not_called()


class WebSourceEntries(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = library_fixtures.LibraryTests.asyncSetUp
    asyncTearDown = library_fixtures.LibraryTests.asyncTearDown
    call = fixtures.DiscordTests.call
    login_as = fixtures.DiscordTests.login_as
    provider_token = fixtures.DiscordTests.provider_token
    provider_me = fixtures.DiscordTests.provider_me

    async def reject_query(self, action, confirmed=False):
        self.dashboard.USER_REQUESTS_PER_MINUTE = 10000
        self.bot.config.enable_local_media = True
        original = self.bot.downloader.extract_info
        self.bot.downloader.extract_info = AsyncMock(side_effect=AssertionError("provider"))
        before = list(self.bot.player.playlist.entries)
        for value in (*LOCAL_INPUTS, *(
                "https://" + host + "/watch?v=video000001&list=" + ident
                for host in HOSTS for ident in ALIASES)):
            with self.subTest(value=value, action=action, confirmed=confirmed):
                data = {"query": value}
                if confirmed:
                    data["preview_id"] = "invalid-preview-cannot-bypass-source-check"
                await self.call(BASE + action, data, status=400)
                self.assertEqual(list(self.bot.player.playlist.entries), before)
        self.bot.downloader.extract_info.assert_not_awaited()
        self.bot.downloader.extract_info = original

    async def test_resolve_rejects_local_and_private_inputs(self):
        await self.reject_query("resolve")

    async def test_legacy_play_rejects_local_and_private_inputs(self):
        await self.reject_query("play")

    async def test_legacy_playnext_rejects_local_and_private_inputs(self):
        await self.reject_query("playnext")

    async def test_confirmed_play_rejects_local_and_private_inputs(self):
        await self.reject_query("play", confirmed=True)

    async def test_confirmed_playnext_rejects_local_and_private_inputs(self):
        await self.reject_query("playnext", confirmed=True)

    async def test_public_import_preview_rejects_aliases_before_provider(self):
        self.bot.downloader.extract_info = AsyncMock(side_effect=AssertionError("provider"))
        for value in (*LOCAL_INPUTS, *(
                "https://" + host + "/playlist?list=" + ident
                for host in HOSTS for ident in ALIASES)):
            with self.subTest(value=value):
                await self.call(BASE + "library/import/preview", {"url": value}, status=400)
        self.bot.downloader.extract_info.assert_not_awaited()

    async def test_saved_batch_checks_all_urls_before_first_enqueue(self):
        self.dashboard.USER_REQUESTS_PER_MINUTE = 10000
        self.bot.downloader.extract_info = AsyncMock(side_effect=AssertionError("provider"))
        before = list(self.bot.player.playlist.entries)
        for url in (*LOCAL_INPUTS, *("https://youtu.be/video000001?list=" + i for i in ALIASES)):
            value = {"revision": "fake-revision", "playlists": [{"id": "favorites", "tracks": [
                {"title": "Safe", "url": "https://soundcloud.com/example/song", "duration": 1},
                {"title": "Rejected", "url": url, "duration": 1}]}]}
            self.dashboard.playlist_store.transact = AsyncMock(return_value=value)
            with self.subTest(url=url):
                await self.call(BASE + "library/favorites/play", {"revision": "fake-revision"}, status=400)
                self.assertEqual(list(self.bot.player.playlist.entries), before)
        self.bot.downloader.extract_info.assert_not_awaited()

    async def test_sync_preview_rejects_private_source_before_provider(self):
        self.bot.downloader.extract_info = AsyncMock(side_effect=AssertionError("provider"))
        for ident in ALIASES:
            value = {"revision": "fake-revision", "playlists": [{"id": "saved",
                "source_url": "https://music.youtube.com/playlist?list=" + ident,
                "source_type": "youtube", "tracks": []}]}
            self.dashboard.playlist_store.transact = AsyncMock(return_value=value)
            with self.subTest(ident=ident):
                await self.call(BASE + "library/saved/sync/preview", {"revision": "fake-revision"}, status=400)
        self.bot.downloader.extract_info.assert_not_awaited()


class PublicPlaylistCredentials(unittest.IsolatedAsyncioTestCase):
    async def test_native_web_playlist_fallback_has_no_credentials(self):
        pool = NS(run=AsyncMock(return_value={"title": "Public", "entries": []}))
        # The helper must work without a bot or ordinary cookie clients.
        pool_token = WEB_POOL.set(pool)
        try:
            await Downloader._dashboard_extract(NS(),
                "https://www.youtube.com/playlist?list=PLpublic",
                {"download": False, "process": True})
        finally:
            WEB_POOL.reset(pool_token)
        job = pool.run.call_args.args[0]
        self.assertEqual(job["cookies"], [])
        for key in ("cookiefile", "cookiesfrombrowser", "usenetrc", "username",
                    "password", "http_headers", "extractor_args"):
            self.assertNotIn(key, job["options"])

    async def test_private_alias_never_snapshots_credentials_or_starts_worker(self):
        clients = NS(snapshot=Mock(side_effect=AssertionError("credentials")))
        pool = NS(run=AsyncMock(side_effect=AssertionError("worker")))
        pool_token = WEB_POOL.set(pool)
        try:
            for ident in ALIASES:
                with self.assertRaises(UnsupportedDashboardURL):
                    await Downloader._dashboard_extract(NS(_cookie_clients=clients),
                        "https://www.youtube.com/playlist?list=" + ident,
                        {"download": False, "process": True})
        finally:
            WEB_POOL.reset(pool_token)
        clients.snapshot.assert_not_called()
        pool.run.assert_not_awaited()

    async def test_public_playlist_still_uses_credential_free_client_outside_web_context(self):
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        from musicbot.downloader import YtdlpResponseDict
        with ThreadPoolExecutor(max_workers=1) as executor:
            downloader = NS(bot=NS(loop=asyncio.get_running_loop()), thread_pool=executor)
            with patch("musicbot.downloader.DashboardYoutubeDL") as client_class:
                client_class.return_value.__enter__.return_value.extract_info.return_value = {
                    "title": "Public", "entries": []}
                await Downloader.extract_public_playlist(downloader,
                    "https://www.youtube.com/playlist?list=PLpublic")
        options = client_class.call_args.args[0]
        self.assertIsNone(options["cookiefile"])
        self.assertIsNone(options["cookiesfrombrowser"])
        self.assertFalse(options["usenetrc"])
        for key in ("username", "password", "http_headers", "extractor_args"):
            self.assertNotIn(key, options)
