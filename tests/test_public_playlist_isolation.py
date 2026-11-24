import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from musicbot.downloader import Downloader
from musicbot.web_dashboard_extraction import WEB_EXTRACTION


class PublicPlaylistIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_isolation_routes_public_playlist_to_dashboard_extract(self):
        downloader = NS(
            _dashboard_extract=AsyncMock(return_value={"title": "Mix", "entries": []}),
        )
        token = WEB_EXTRACTION.set(False)
        try:
            with patch.dict(os.environ, {"MUSICBOT_NATIVE_YTDLP_ISOLATION": "1"}):
                result = await Downloader.extract_public_playlist(
                    downloader,
                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ",
                    limit=25,
                )
        finally:
            WEB_EXTRACTION.reset(token)

        downloader._dashboard_extract.assert_awaited_once_with(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ",
            {"download": False, "process": False},
            public=True,
            limit=25,
        )
        self.assertEqual(
            result.data["__input_subject"],
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ",
        )
