import os
import tempfile
import unittest
from pathlib import Path
from musicbot.cache_integrity import cache_verdict, mark_complete

class CompletionReceiptTests(unittest.TestCase):
    def test_unknown_length_needs_success_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            f, db = Path(root)/'song.opus', Path(root)/'receipts.db'
            f.write_bytes(b'valid fixture media')
            self.assertEqual(cache_verdict(f, None, database=db)[0], False)
            self.assertTrue(mark_complete(f, database=db))
            self.assertEqual(cache_verdict(f, None, database=db), (True,'unknown-size-verified'))
            self.assertTrue(cache_verdict(f, '', database=db)[0])
    def test_known_length_mismatch_is_authoritative(self):
        with tempfile.TemporaryDirectory() as root:
            f, db = Path(root)/'song', Path(root)/'receipts.db'
            f.write_bytes(b'audio');mark_complete(f, database=db)
            self.assertEqual(cache_verdict(f, 8, database=db), (False,'known-size-mismatch'))
            self.assertTrue(cache_verdict(f, 5, database=db)[0])
    def test_invalid_and_replaced_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            f, db = Path(root)/'song.opus', Path(root)/'receipts.db'
            f.write_bytes(b'first');mark_complete(f, database=db)
            f.write_bytes(b'new content')
            self.assertFalse(cache_verdict(f, None, database=db)[0])
            f.with_suffix('.part').write_bytes(b'incomplete')
            self.assertFalse(cache_verdict(f.with_suffix('.part'), None, database=db)[0])
            f.write_bytes(b'')
            self.assertFalse(cache_verdict(f, 0, database=db)[0])
