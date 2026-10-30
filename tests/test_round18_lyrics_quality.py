"""Round18 lyrics regressions; run inside a complete MusicBot checkout."""
import unittest
from types import SimpleNamespace

from musicbot.web_dashboard_lyrics import LyricsClient, result
from musicbot.web_dashboard_lyrics_alignment import AlignmentService


class LyricMatchingTests(unittest.TestCase):
    def test_manual_duration_tolerance_does_not_relax_auto(self):
        row = {'id': 7281, 'trackName': 'Real Song', 'artistName': 'Singer',
               'duration': 250, 'plainLyrics': 'A genuine line'}
        self.assertIsNone(LyricsClient._choose([row], 'Real Song', 'Singer', 180))
        self.assertIs(LyricsClient._choose([row], 'Real Song', 'Singer', 180, True), row)
        self.assertIsNone(LyricsClient._choose([row], 'Other Song', 'Singer', 180, True))
        self.assertIsNone(LyricsClient._choose([row], 'Real Song (Live)', 'Singer', 180, True))

    def test_record_provenance_is_bounded(self):
        row = {'id': 7281, 'trackName': 'Real Song', 'artistName': 'Singer',
               'duration': 180, 'plainLyrics': 'One full line'}
        got = result('Real Song', 'Singer', row)
        self.assertEqual(got['lrclib_record_id'], 7281)
        self.assertEqual(got['match_strategy_version'], 2)
        self.assertEqual(len(got['metadata_fingerprint']), 16)
        got = result('Real Song', 'Singer', dict(row,id='untrusted'))
        self.assertIsNone(got['lrclib_record_id'])


class AlignmentConfidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_length_match_is_assumption_not_verified_alignment(self):
        class Store:
            def __init__(self): self.writes=[]
            async def get(self,*args): return None
            async def put(self,*args): self.writes.append(args)
        store = Store()
        service = AlignmentService(store)
        bot = SimpleNamespace()
        entry = SimpleNamespace(url='https://www.youtube.com/watch?v=abcdefghijk', duration=180)
        value = await service.request(bot, entry, {'duration':181})
        self.assertEqual(value['source'], 'duration_assumed')
        self.assertLess(value['confidence'], 1)
        self.assertEqual(store.writes[0][2], 3600)


if __name__=='__main__': unittest.main()
