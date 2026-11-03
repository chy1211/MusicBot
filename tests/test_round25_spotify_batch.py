"""Regression: public Spotify playlist selection enqueues through native track resolution."""
import unittest
from unittest.mock import AsyncMock

from musicbot.downloader import YtdlpResponseDict
from musicbot.exceptions import PermissionsError
import test_web_dashboard_imports as imports
from test_web_dashboard import BASE
from test_web_dashboard_round9 import SpotifyNativeSelectionTests


class SpotifyBatchSelectionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = imports.ImportTests.asyncSetUp
    asyncTearDown = imports.ImportTests.asyncTearDown
    call = imports.ImportTests.call
    spotify_provider = imports.ImportTests.spotify_provider
    login_as = imports.ImportTests.login_as
    provider_token = imports.ImportTests.provider_token
    provider_me = imports.ImportTests.provider_me

    async def test_spotify_batch_selected_tracks_enqueue(self):
        self.spotify_provider([imports.spotify(i) for i in range(1, 4)])
        response = await self.call(BASE + "resolve", {"query": imports.SPOTIFY})
        song = response["results"][0]
        self.assertEqual(song["kind"], "playlist")
        self.assertTrue(song["allowed"], song.get("reason"))
        self.assertTrue(all(child["allowed"] for child in song["entries"]), song["entries"])
        self.assertEqual(len(song["entries"]), 3)
        wrapper = {
            "_type": "playlist", "extractor": "youtube:search", "playlist_count": 1,
            "entries": [{"extractor": "youtube", "id": "abcdefghijk",
                         "title": "Found", "duration": 90,
                         "url": "https://media.example.test/audio",
                         "webpage_url": "https://www.youtube.com/watch?v=abcdefghijk"}],
        }
        await SpotifyNativeSelectionTests.set_real_spotify_extraction(self, raw=wrapper)
        data = {"query": song["url"], "preview_id": song["preview_id"],
                "selected_items": [child["item_id"] for child in song["entries"]]}
        result = await self.call(BASE + "play", data)
        self.assertEqual(result["added"], 3, result)
        self.assertEqual(result["skipped"], 0, result)
        self.assertEqual(len(self.bot.player.playlist.entries), 6)

    async def test_spotify_batch_accepts_unflattened_single_youtube_search_result(self):
        self.spotify_provider([imports.spotify(i) for i in range(1, 10)])
        response = await self.call(BASE + "resolve", {"query": imports.SPOTIFY})
        preview = response["results"][0]
        # yt-dlp can return a one-child search playlist without flattening it.
        # The playlist's own ID and URL are search metadata, not the video.
        raw = {
            "_type": "playlist", "extractor": "youtube:search",
            "playlist_count": 0, "id": "Artist - Song",
            "webpage_url": "ytsearch:Artist - Song",
            "entries": [{"extractor": "youtube", "id": "abcdefghijk",
                         "title": "Found", "duration": 90,
                         "url": "https://media.example.test/audio",
                         "webpage_url": "https://www.youtube.com/watch?v=abcdefghijk"}],
        }
        await SpotifyNativeSelectionTests.set_real_spotify_extraction(self, raw=raw)
        result = await self.call(BASE + "play", {
            "query": preview["url"], "preview_id": preview["preview_id"],
            "selected_items": [item["item_id"] for item in preview["entries"]],
        })
        self.assertEqual(result["added"], 9, result)
        self.assertEqual(result["skipped"], 0, result)
        self.assertEqual(len(self.bot.player.playlist.entries), 12)
        self.assertEqual(self.bot.player.playlist.entries[-1].title, "Found")

    async def test_spotify_batch_rejects_unplayable_or_nested_search_children(self):
        for bad_child in (
            {"extractor": "youtube", "id": "abcdefghijk",
             "title": "Found", "duration": 90, "url": "https://media.example.test/audio",
             "webpage_url": "https://www.youtube.com/watch?v=not_the_id"},
            {"extractor": "youtube:playlist", "id": "abcdefghijk",
             "title": "Found", "duration": 90, "url": "https://media.example.test/audio",
             "webpage_url": "https://www.youtube.com/watch?v=abcdefghijk"},
            {"extractor": "youtube", "id": "abcdefghijk", "_type": "playlist",
             "entries": [{"id": "another", "extractor": "youtube"}],
             "title": "Found", "duration": 90, "url": "https://media.example.test/audio",
             "webpage_url": "https://www.youtube.com/watch?v=abcdefghijk"},
        ):
            with self.subTest(bad_child=bad_child.get("extractor"),
                              page=bad_child.get("webpage_url"),
                              nested=bool(bad_child.get("entries"))):
                self.spotify_provider([imports.spotify(1)])
                response = await self.call(BASE + "resolve", {"query": imports.SPOTIFY})
                preview = response["results"][0]
                raw = {"_type": "playlist", "extractor": "youtube:search",
                       "playlist_count": 0, "id": "Artist - Song",
                       "entries": [bad_child]}
                await SpotifyNativeSelectionTests.set_real_spotify_extraction(self, raw=raw)
                result = await self.call(BASE + "play", {
                    "query": preview["url"], "preview_id": preview["preview_id"],
                    "selected_items": [preview["entries"][0]["item_id"]],
                })
                self.assertEqual(result["added"], 0, result)
                self.assertEqual(result["skipped"], 1, result)

    async def test_spotify_batch_uses_previewed_metadata_without_requerying_each_track(self):
        self.spotify_provider([imports.spotify(i) for i in range(1, 10)])
        response = await self.call(BASE + "resolve", {"query": imports.SPOTIFY})
        song = response["results"][0]
        self.assertEqual(len(song["entries"]), 9)
        self.bot.spotify.get_spotify_ytdl_data = AsyncMock(
            side_effect=AssertionError("Should reuse previewed Spotify track metadata"))
        self.bot.downloader.extract_info = AsyncMock(return_value=YtdlpResponseDict({
            "_type": "video", "extractor": "youtube", "id": "abcdefghijk",
            "title": "Found", "duration": 90,
            "webpage_url": "https://www.youtube.com/watch?v=abcdefghijk",
            "url": "https://www.youtube.com/watch?v=abcdefghijk",
            "__input_subject": "ytsearch:Artist - Song",
        }))
        result = await self.call(BASE + "play", {
            "query": song["url"], "preview_id": song["preview_id"],
            "selected_items": [item["item_id"] for item in song["entries"]],
        })
        self.assertEqual(result["added"], 9, result)
        self.assertEqual(result["skipped"], 0, result)
        self.assertEqual(len(self.bot.player.playlist.entries), 12)
        subjects = [call.args[0] for call in self.bot.downloader.extract_info.await_args_list]
        self.assertEqual(subjects, [f"ytsearch:Artist - Song {i}" for i in range(1, 10)])
        self.bot.spotify.get_spotify_ytdl_data.assert_not_awaited()

    async def test_spotify_batch_rechecks_source_permission_after_preview(self):
        self.spotify_provider([imports.spotify(1)])
        response = await self.call(BASE + "resolve", {"query": imports.SPOTIFY})
        song = response["results"][0]
        def extractor_permission(extractor):
            if extractor == "spotify:musicbot":
                raise PermissionsError("Spotify revoked")
        self.bot.member_perms.can_use_extractor = extractor_permission
        self.bot.downloader.extract_info = AsyncMock()
        result = await self.call(BASE + "play", {
            "query": song["url"], "preview_id": song["preview_id"],
            "selected_items": [song["entries"][0]["item_id"]],
        })
        self.assertEqual(result["added"], 0)
        self.assertEqual(result["skipped"], 1)
        self.bot.downloader.extract_info.assert_not_awaited()
