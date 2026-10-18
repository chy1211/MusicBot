"""Preserve provenance and verify harmless cache variants without network."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
import test_web_dashboard_imports as fixtures
from musicbot.downloader import YtdlpResponseDict
from musicbot.entry import URLPlaylistEntry

class Round16ImportWarningsTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ImportTests.asyncSetUp
    asyncTearDown = fixtures.ImportTests.asyncTearDown
    call = fixtures.ImportTests.call
    login_as = fixtures.ImportTests.login_as
    provider_token = fixtures.ImportTests.provider_token
    provider_me = fixtures.ImportTests.provider_me
    spotify_provider = fixtures.ImportTests.spotify_provider

    async def test_youtube_and_spotify_preview_keep_parent_and_track_subjects(self):
        self.spotify_provider([fixtures.spotify()])
        for url in [fixtures.YTM, fixtures.SPOTIFY]:
            with patch("musicbot.downloader.log.warning") as warning, patch.object(
                    self.dashboard, "preview_track", wraps=self.dashboard.preview_track) as track:
                response = await self.call("/api/guilds/1/resolve", {"query":url})
            warning.assert_not_called()
            self.assertTrue(track.call_args_list)
            for call in track.call_args_list:
                info = call.args[0]
                self.assertTrue(info.input_subject.startswith("https://"))
                self.assertEqual(info.input_subject, info.webpage_url)
            self.assertTrue(response["results"][0]["entries"])

    async def test_missing_provenance_still_warns(self):
        with self.assertLogs("musicbot.downloader", level="WARNING") as captured:
            YtdlpResponseDict({"title":"synthetic missing provenance"})
        self.assertIn("Missing __input_subject", " ".join(captured.output))

class Round16CacheWarningsTests(unittest.IsolatedAsyncioTestCase):
    async def cached(self, remote_size):
        with tempfile.TemporaryDirectory(prefix="musicbot-webtest-cache-") as directory:
            cached = Path(directory)/"song.m4a"; cached.write_bytes(b"abc")
            info = YtdlpResponseDict({"__input_subject":"https://soundcloud.com/example/song",
                "__expected_filename":str(Path(directory)/"song.webm"),
                "__header_data":{"CONTENT-LENGTH":str(remote_size)},
                "title":"Synthetic", "duration":180, "extractor":"example"})
            cache = NS(ensure_cache_dir_exists=Mock(), get_if_cached=Mock(return_value=str(cached)))
            bot = NS(filecache=cache, downloader=NS(), config=NS(use_experimental_equalization=False))
            entry = URLPlaylistEntry(NS(bot=bot), info)
            entry._ensure_entry_info = AsyncMock()
            entry._really_download = AsyncMock()
            with self.assertLogs("musicbot.entry", level="DEBUG") as captured:
                await entry._download()
            self.assertTrue(any("different extension" in row.getMessage() and row.levelname == "DEBUG"
                                for row in captured.records))
            self.assertFalse(any(row.levelname == "WARNING" for row in captured.records))
            return entry, entry._really_download.await_count, str(cached)

    async def test_extension_variant_cache_hit_is_debug_and_reused(self):
        entry, downloads, cached = await self.cached(3)
        self.assertEqual(downloads, 0)
        self.assertEqual(entry.filename, cached)
        self.assertTrue(entry.is_downloaded)

    async def test_extension_variant_still_redownloads_size_mismatch(self):
        _entry, downloads, _cached = await self.cached(9)
        self.assertEqual(downloads, 1)
