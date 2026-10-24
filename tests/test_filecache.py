"""Regression tests for AudioFileCache.get_if_cached path handling."""
import tempfile
import unittest
from pathlib import Path

from musicbot.filecache import AudioFileCache

class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = AudioFileCache.__new__(AudioFileCache)
        self.cache.cache_path = Path(self.temp.name)/'audio_cache'
        self.cache.cache_path.mkdir()
        (self.cache.cache_path/'demo.webm').touch()

    def test_exact_preferred_over_other_extension_and_sibling(self):
        (self.cache.cache_path/'demo.m4a').touch()
        (self.cache.cache_path.parent/'demo.webm').touch()
        self.assertEqual(self.cache.get_if_cached('/somewhere/demo.webm'), str(self.cache.cache_path/'demo.webm'))

    def test_extension_fallback(self):
        self.assertEqual(self.cache.get_if_cached('demo.m4a'), str(self.cache.cache_path/'demo.webm'))

    def test_missing(self):
        self.assertEqual(self.cache.get_if_cached('absent.webm'), '')

    def test_strict_extension_returns_cache_path(self):
        self.assertEqual(self.cache.get_if_cached('/somewhere/demo.webm', False), str(self.cache.cache_path/'demo.webm'))
        self.assertEqual(self.cache.get_if_cached('demo.m4a', False), '')

    def test_glob_literal_and_directory(self):
        (self.cache.cache_path/'[x].webm').touch()
        (self.cache.cache_path/'directory.webm').mkdir()
        self.assertEqual(self.cache.get_if_cached('[x].m4a'), str(self.cache.cache_path/'[x].webm'))
        self.assertEqual(self.cache.get_if_cached('directory.webm'), '')


if __name__ == "__main__":
    unittest.main()
