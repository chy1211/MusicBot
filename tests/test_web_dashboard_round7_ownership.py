import tempfile
import unittest
from pathlib import Path
from unittest import mock

from musicbot.web_dashboard_library import atomic_write


class AtomicWriteOwnershipTests(unittest.TestCase):
    def test_existing_file_keeps_owner_and_group(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "permissions.ini")
            path.write_text("old", encoding="utf-8")
            stat = path.stat()
            with mock.patch("musicbot.web_dashboard_library.os.fchown") as fchown:
                atomic_write(path, b"new")
            fchown.assert_called_once()
            self.assertEqual(fchown.call_args.args[1:], (stat.st_uid, stat.st_gid))
            self.assertEqual(path.read_bytes(), b"new")

    def test_chown_failure_does_not_block_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "list.json")
            path.write_text("old", encoding="utf-8")
            with mock.patch("musicbot.web_dashboard_library.os.fchown",
                            side_effect=PermissionError()):
                atomic_write(path, b"new")
            self.assertEqual(path.read_bytes(), b"new")


if __name__ == "__main__":
    unittest.main()
