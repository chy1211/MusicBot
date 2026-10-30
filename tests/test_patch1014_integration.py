"""Real route/provider counts and download/cache boundaries; no provider network."""
import asyncio
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from musicbot.cache_integrity import cache_verdict, mark_complete
from musicbot.entry import URLPlaylistEntry
from musicbot.web_dashboard_reuse import CompleteInfoCache
from test_dashboard_preview_reuse import install_downloader, URL
import test_dashboard_preview_reuse as preview_fixtures
import test_web_dashboard as fixtures


class CompleteMetadataRoutes(unittest.IsolatedAsyncioTestCase):
    call = fixtures.DashboardTests.call
    preview = preview_fixtures.PreviewReuseTests.preview
    add = preview_fixtures.PreviewReuseTests.add
    record = preview_fixtures.PreviewReuseTests.record
    asyncTearDown = fixtures.DashboardTests.asyncTearDown

    async def asyncSetUp(self):
        await fixtures.DashboardTests.asyncSetUp(self)
        install_downloader(self)
        self.bot.downloader._cookie_clients.options = {'format': 'bestaudio'}

    async def test_repeated_resolve_add_and_download_do_not_reextract(self):
        await self.preview()
        second = await self.preview()
        self.assertEqual(len(self.provider_calls), 1)
        await self.add(second)
        self.assertEqual(len(self.provider_calls), 1)
        self.assertEqual(len(self.bot.player.playlist.entries), 4)

    async def test_settings_change_requires_fresh_extraction(self):
        await self.preview()
        self.bot.downloader._cookie_clients.options['format'] = 'worstaudio'
        await self.preview()
        self.assertEqual(len(self.provider_calls), 2)

    async def test_cookie_generation_change_requires_fresh_extraction(self):
        await self.preview()
        old = self.bot.downloader._cookie_clients.snapshot()
        self.bot.downloader._cookie_clients.snapshot = lambda **kw: (NS(), old[1])
        await self.preview()
        self.assertEqual(len(self.provider_calls), 2)

    async def test_expired_metadata_is_refreshed(self):
        await self.preview()
        cache = self.dashboard._complete_info_cache
        cache._items = type(cache._items)((k, (time.monotonic()-1, v[1])) for k,v in cache._items.items())
        await self.preview()
        self.assertEqual(len(self.provider_calls), 2)

    async def test_cached_metadata_does_not_bypass_changed_duration_permission(self):
        item = await self.preview()
        self.bot.perms.max_song_length = 10
        await self.add(item, status=403)
        self.assertEqual(len(self.provider_calls), 1)


class DownloadReceiptBoundaries(unittest.IsolatedAsyncioTestCase):
    def entry(self, path):
        return NS(expected_filename=str(path),
                  filecache=NS(get_if_cached=lambda _: str(path) if path.exists() else None),
                  _reusable_extraction=lambda: {'formats': [{}]},
                  downloader=NS(download_from_info=AsyncMock(return_value=NS(expected_filename=str(path)))))

    async def test_unchanged_unverified_legacy_file_does_not_gain_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'song.m4a';path.write_bytes(b'legacy')
            entry=self.entry(path)
            with patch('musicbot.entry.mark_complete', return_value=True) as mark:
                await URLPlaylistEntry._really_download(entry)
            mark.assert_not_called()

    async def test_successful_new_file_gains_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'song.m4a';entry=self.entry(path)
            async def transfer(data):
                path.write_bytes(b'completed transfer')
                return NS(expected_filename=str(path), data={'__real_download': True})
            entry.downloader.download_from_info.side_effect=transfer
            with patch('musicbot.entry.mark_complete', return_value=True) as mark:
                await URLPlaylistEntry._really_download(entry)
            mark.assert_called_once()
            self.assertIn('expected_identity', mark.call_args.kwargs)

    async def test_touch_without_transfer_does_not_gain_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'song.m4a';path.write_bytes(b'legacy');entry=self.entry(path)
            async def skipped(data):
                path.touch()
                return NS(expected_filename=str(path),data={'__real_download':False})
            entry.downloader.download_from_info.side_effect=skipped
            with patch('musicbot.entry.mark_complete', return_value=True) as mark:
                await URLPlaylistEntry._really_download(entry)
            mark.assert_not_called()

    async def test_valid_unknown_length_local_cache_never_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'song.m4a';db=Path(directory)/'receipts.db'
            path.write_bytes(b'completed transfer');self.assertTrue(mark_complete(path,database=db))
            entry=NS(_is_downloading=False, _ensure_entry_info=AsyncMock(), expected_filename=str(path),
                     filecache=NS(ensure_cache_dir_exists=lambda:None,get_if_cached=lambda _:str(path)),
                     info=NS(http_header=lambda *args:None), cache_busted=False, duration=120,
                     playlist=NS(bot=NS(config=NS(use_experimental_equalization=False))),
                     _for_each_future=Mock(), _really_download=AsyncMock())
            with patch('musicbot.entry.cache_verdict',side_effect=lambda name,remote:cache_verdict(name,remote,database=db)):
                await URLPlaylistEntry._download(entry)
            entry._really_download.assert_not_called()
            self.assertEqual(entry.filename,str(path))
            self.assertTrue(entry._is_downloaded)


class ReceiptRobustness(unittest.TestCase):
    def test_corrupt_and_locked_database_fail_closed_quickly(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'song.m4a';db=Path(directory)/'receipts.db'
            path.write_bytes(b'audio');db.write_bytes(b'corrupt')
            self.assertFalse(cache_verdict(path,database=db)[0])
            db.unlink();self.assertTrue(mark_complete(path,database=db))
            with closing(sqlite3.connect(db)) as connection:
                connection.execute('BEGIN EXCLUSIVE');start=time.monotonic()
                self.assertFalse(cache_verdict(path,database=db)[0])
                self.assertLess(time.monotonic()-start,.5)

    def test_receipt_has_no_raw_media_path_and_no_stale_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'private-title.m4a';db=Path(directory)/'receipts.db'
            path.write_bytes(b'audio');self.assertTrue(mark_complete(path,database=db))
            with closing(sqlite3.connect(db)) as connection:
                self.assertNotIn('private-title', '\n'.join(connection.iterdump()))
            from musicbot.cache_integrity import _identity
            identity = _identity(path)
            with patch('musicbot.cache_integrity._identity',side_effect=[identity,(identity[0],'changed',identity[2])]):
                self.assertFalse(cache_verdict(path,database=db)[0])

    def test_generation_reference_and_configuration_partition(self):
        cache=CompleteInfoCache();client=NS()
        first=cache.scope(client,{'format':'a','http_headers':{'User-Agent':'one'}})
        self.assertEqual(first,cache.scope(client,{'format':'a','http_headers':{'User-Agent':'two'}}))
        self.assertNotEqual(first,cache.scope(client,{'format':'b'}))
        cache._items['sentinel']=(time.monotonic()+120,b'{}')
        cache.scope(NS(),{})
        self.assertFalse(cache._items)
