"""Patch #9 regression tests. Copy into MusicBot/tests/ and run with unittest."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from musicbot.loudnorm_cache import lookup_loudnorm, store_loudnorm
from musicbot.loudness import LOUDNORM_TARGET
from musicbot.entry import BasePlaylistEntry


OPTS = (LOUDNORM_TARGET + ':linear=true:measured_I=-18.0:measured_LRA=3.0:'
        'measured_TP=-2.0:measured_thresh=-28.0:offset=0.0')


class CacheTests(TestCase):
    def test_cache_identity_survives_new_object_but_not_changed_file(self):
        with TemporaryDirectory() as td:
            f, db = Path(td)/'track.opus', Path(td)/'metadata.sqlite3'
            f.write_bytes(b'first file')
            self.assertIsNone(lookup_loudnorm(str(f), database=db))
            self.assertTrue(store_loudnorm(str(f), OPTS, database=db))
            self.assertEqual(lookup_loudnorm(str(f), database=db), OPTS)
            f.write_bytes(b'changed file content')
            self.assertIsNone(lookup_loudnorm(str(f), database=db))

    def test_cache_rejects_unsafe_filter_strings(self):
        with TemporaryDirectory() as td:
            f, db = Path(td)/'track', Path(td)/'db'
            f.write_bytes(b'audio')
            self.assertFalse(store_loudnorm(str(f), 'volume=999,evil=foo', database=db))
            self.assertIsNone(lookup_loudnorm(str(f), database=db))

    def test_policy_first_vs_predownload(self):
        entry = BasePlaylistEntry()
        player = SimpleNamespace(is_playing=False, is_paused=False)
        playlist = SimpleNamespace(bot=SimpleNamespace(players={1:player}))
        entry.playlist = playlist
        player.playlist = playlist
        self.assertFalse(entry.should_wait_for_loudness())
        player.is_playing = True
        self.assertTrue(entry.should_wait_for_loudness())
        player.is_playing = False
        player.is_paused = True
        self.assertTrue(entry.should_wait_for_loudness())


class ReadinessTests(IsolatedAsyncioTestCase):
    async def test_first_track_does_not_run_full_file_scan(self):
        obj = BasePlaylistEntry()
        with patch('musicbot.entry.lookup_loudnorm', return_value=None), \
             patch('musicbot.entry.run_command', new_callable=AsyncMock) as scan:
            result = await obj.get_mean_volume('/does/not/exist', allow_analysis=False)
            self.assertEqual(result, 'one_pass')
            self.assertFalse(obj.has_audio_filter('loudnorm'))
            scan.assert_not_awaited()

    async def test_cached_results_work_without_scanning(self):
        obj = BasePlaylistEntry()
        with patch('musicbot.entry.lookup_loudnorm', return_value=OPTS), \
             patch('musicbot.entry.run_command', new_callable=AsyncMock) as scan:
            self.assertEqual(await obj.get_mean_volume('/unused', allow_analysis=False), 'cached')
            self.assertEqual(obj._a_filters['loudnorm'], OPTS)
            scan.assert_not_awaited()

    async def test_uncached_following_song_still_measures(self):
        obj = BasePlaylistEntry()
        import json
        values = {'input_i':'-18.0','input_lra':'3.0','input_tp':'-2.0',
                  'input_thresh':'-28.0','target_offset':'0.0'}
        with patch('musicbot.entry.lookup_loudnorm', return_value=None), \
             patch('musicbot.entry.store_loudnorm', return_value=True), \
             patch('musicbot.entry.run_command', new_callable=AsyncMock, return_value=json.dumps(values).encode()) as scan, \
             patch('musicbot.entry.shutil.which', return_value='/usr/bin/ffmpeg'):
            self.assertEqual(await obj.get_mean_volume('/unused', allow_analysis=True), 'measured')
            self.assertIn('measured_I', obj._a_filters['loudnorm'])
            scan.assert_awaited_once()

import math
import os
from pathlib import Path
import sqlite3
import time
from unittest.mock import AsyncMock, patch

import musicbot.entry as runtime
from musicbot.loudnorm_cache import loudnorm_fingerprint


class CacheRobustnessTests(TestCase):
    # Separate loader below avoids inheriting the original cases twice.
    def test_replaced_inode_invalidates_same_size_file(self):
        with TemporaryDirectory() as td:
            path, db = Path(td)/'audio', Path(td)/'cache'
            path.write_bytes(b'first')
            original = path.stat()
            self.assertTrue(store_loudnorm(str(path), OPTS, database=db))
            other = Path(td)/'replacement'
            other.write_bytes(b'other')
            os.utime(other, ns=(original.st_atime_ns, original.st_mtime_ns))
            os.replace(other, path)
            self.assertIsNone(lookup_loudnorm(str(path), database=db))

    def test_cache_is_bounded_and_does_not_contain_plain_paths(self):
        with TemporaryDirectory() as td:
            path, db = Path(td)/'media-private-name', Path(td)/'cache'
            path.write_bytes(b'audio')
            for tick in range(515):
                os.utime(path, ns=(tick+1000000000, tick+1000000000))
                self.assertTrue(store_loudnorm(str(path), OPTS, database=db))
            with sqlite3.connect(db) as connection:
                self.assertEqual(connection.execute('select count(*) from measurements').fetchone()[0],512)
                dump='\n'.join(connection.iterdump())
            self.assertNotIn(str(path), dump)
            self.assertNotIn('media-private-name', dump)
            if os.name!='nt':
                self.assertEqual(db.stat().st_mode&0o777,0o600)

    def test_corrupt_or_busy_cache_fails_open_promptly(self):
        with TemporaryDirectory() as td:
            path, db = Path(td)/'audio', Path(td)/'cache'
            path.write_bytes(b'audio')
            db.write_bytes(b'not a sqlite database')
            self.assertIsNone(lookup_loudnorm(str(path),database=db))
            self.assertFalse(store_loudnorm(str(path),OPTS,database=db))
            db.unlink()
            self.assertTrue(store_loudnorm(str(path),OPTS,database=db))
            with sqlite3.connect(db) as lock:
                lock.execute('BEGIN EXCLUSIVE')
                started=time.monotonic()
                self.assertIsNone(lookup_loudnorm(str(path),database=db))
                self.assertLess(time.monotonic()-started,.5)

    def test_non_finite_and_changed_fingerprint_are_rejected(self):
        with TemporaryDirectory() as td:
            path, db = Path(td)/'audio', Path(td)/'cache'
            path.write_bytes(b'audio')
            key=loudnorm_fingerprint(str(path))
            path.write_bytes(b'changed')
            self.assertFalse(store_loudnorm(str(path),OPTS,database=db,expected_fingerprint=key))
            self.assertFalse(store_loudnorm(str(path),OPTS.replace('measured_I=-18.0','measured_I=1e999'),database=db))


class AnalysisMutationTests(IsolatedAsyncioTestCase):
    async def test_file_changed_during_analysis_does_not_save_or_apply_measurements(self):
        obj=BasePlaylistEntry()
        values={'input_i':'-18.0','input_lra':'3.0','input_tp':'-2.0','input_thresh':'-28.0','target_offset':'0.0'}
        import json
        with TemporaryDirectory() as td:
            path=Path(td)/'audio'
            path.write_bytes(b'original')
            async def scan(*args,**kwargs):
                path.write_bytes(b'changed data')
                return json.dumps(values).encode()
            with patch('musicbot.entry.lookup_loudnorm',return_value=None), \
                 patch('musicbot.entry.run_command',new=AsyncMock(side_effect=scan)), \
                 patch('musicbot.entry.store_loudnorm') as store, \
                 patch('musicbot.entry.shutil.which',return_value='/usr/bin/ffmpeg'):
                self.assertEqual(await obj.get_mean_volume(str(path)), 'one_pass')
                self.assertFalse(obj.has_audio_filter('loudnorm'))
                store.assert_not_called()
