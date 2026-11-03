"""Regression: public Spotify playlist selection enqueues through native track resolution."""
import unittest

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
