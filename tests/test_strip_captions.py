"""Unused caption payloads never reach previews or restored queues."""
import asyncio
import copy
import json
import logging
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from musicbot.downloader import Downloader, YtdlpResponseDict, strip_caption_data
from musicbot.entry import URLPlaylistEntry, StreamPlaylistEntry, LocalFilePlaylistEntry
from musicbot.web_dashboard_preview import save_extraction, load_extraction, PreviewExtraction

logging.Logger.noise = logging.Logger.debug
URL = "https://www.youtube.com/watch?v=AbcDeFg1234"
CAPTIONS = ("automatic_captions", "subtitles", "requested_subtitles")


def large_info():
    return dict(title="DemoUser", duration=180, extractor="youtube", _type="video",
                webpage_url=URL, url="https://media.example.test/audio", ext="m4a",
                formats=[dict(format_id="140", url="https://media.example.test/" + "f"*100000)],
                automatic_captions={"en": [{"url": "https://caption.example.test/" + "c"*500000}]},
                subtitles={"en": [{"url": "https://caption.example.test/manual"}]},
                requested_subtitles={"en": {"url": "https://caption.example.test/requested"}},
                __input_subject=URL, __extracted_at=time.time(), __expected_filename="demo.m4a")


class StripCaptionsTests(unittest.IsolatedAsyncioTestCase):
    def downloader(self, data):
        downloader = Downloader.__new__(Downloader)
        downloader.bot = NS(loop=asyncio.get_running_loop())
        client = NS(sanitize_info=lambda result: copy.deepcopy(result),
                    prepare_filename=lambda result: "demo.m4a")
        downloader._cookie_clients = NS(snapshot=lambda **kw: (client, client))
        downloader._extract_with_client = AsyncMock(return_value=data)
        downloader._supported_search = []
        downloader.thread_pool = None
        downloader._run_ytdl = lambda *args, **kw: data
        return downloader

    def clean(self, data):
        for key in CAPTIONS:
            self.assertNotIn(key, data)
        for entry in data.get("entries", []):
            if isinstance(entry, dict):
                self.clean(entry)

    async def test_extraction_preserves_formats_and_other_metadata(self):
        original = large_info()
        result = await self.downloader(original)._filtered_extract_info(URL, download=False)
        self.clean(result)
        self.assertEqual(result, {k: v for k, v in original.items() if k not in CAPTIONS})
        self.assertIn("automatic_captions", original)

    async def test_nested_playlist_entries_are_cleaned(self):
        data = dict(large_info(), entries=[large_info(), dict(large_info(), entries=[large_info()])])
        result = await self.downloader(data)._filtered_extract_info(URL)
        self.clean(result)
        self.assertEqual(result["entries"][0]["formats"], data["formats"])

    async def test_download_from_info_is_cleaned_after_sanitize(self):
        original = large_info()
        result = await self.downloader(original).download_from_info(original)
        self.clean(result.data)
        self.assertEqual(result["formats"], original["formats"])
        self.assertEqual(result["__expected_filename"], original["__expected_filename"])

    async def test_legacy_queue_roundtrip_all_entry_types(self):
        bot = NS(downloader=NS(), filecache=NS(),
                 config=NS(save_videos=False, default_speed=1.0))
        for cls in (URLPlaylistEntry, StreamPlaylistEntry, LocalFilePlaylistEntry):
            with self.subTest(entry=cls.__name__):
                # JSON roundtrip models the info field inside a saved queue entry.
                raw = json.loads(json.dumps(dict(version=cls.SERIAL_VERSION, info=large_info(),
                    downloaded=False, filename="demo.m4a", author_id=None, channel_id=None)))
                restored = cls._deserialize(raw, playlist=NS(bot=bot))
                self.assertIsNotNone(restored)
                saved = json.loads(restored.serialize())
                self.clean(saved["data"]["info"])
                self.assertEqual(saved["data"]["info"]["formats"], raw["info"]["formats"])

    async def test_large_preview_is_saved_and_add_reuses_it(self):
        data = large_info()
        self.assertGreater(len(json.dumps(data)), 600000)
        self.assertEqual(save_extraction(YtdlpResponseDict(data), URL, URL)[1], "result-too-large")
        data = await self.downloader(data)._filtered_extract_info(URL)
        blob, reason = save_extraction(YtdlpResponseDict(data), URL, URL)
        self.assertEqual(reason, "")
        self.assertLess(len(blob), 110000)
        preview = dict(kind="track", expires=time.monotonic()+60, url=URL, extraction=blob)
        loaded, reason = load_extraction(preview, URL)
        self.assertEqual(reason, "")
        reuse = PreviewExtraction(loaded, AsyncMock())
        with self.assertLogs("musicbot.web_dashboard_preview", level="INFO") as logs:
            result = await reuse.extract(None, URL, (), dict(download=False, process=True))
        self.assertIn("Dashboard add reused preview extraction", logs.output[0])
        self.clean(result.data)
        reuse.close()
