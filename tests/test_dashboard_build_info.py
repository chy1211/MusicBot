"""Image metadata works without git and fails closed for missing or invalid files."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from musicbot.web_dashboard_maintenance import build_info, inspect_status


class BuildInfoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r42-build-info-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "BUILD_INFO.json"
        self.unknown = dict(commit="unknown", time="unknown", branch="unknown")

    def test_full_sha_is_shortened_and_timestamp_is_utc(self):
        self.path.write_text(json.dumps(dict(commit="abcdef1234567890abcdef1234567890abcdef1234",
            time="2026-10-26T12:34:56+08:00", branch="feature/round42-real-version")))
        self.assertEqual(build_info(self.path), dict(commit="abcdef123456",
            time="2026-10-26T04:34:56+00:00", branch="feature/round42-real-version"))

    def test_missing_corrupt_oversized_or_wrong_shape_is_unknown(self):
        self.assertEqual(build_info(self.path), self.unknown)
        for raw in ("{", "[]", "null", "x" * 4097, "{}",
                    '{"commit": null, "time": [], "branch": {}}',
                    '{"commit": "not-a-sha", "time": "yesterday", "branch": "bad\\nbranch"}'):
            with self.subTest(raw=raw[:60]):
                self.path.write_text(raw)
                self.assertEqual(build_info(self.path), self.unknown)
        self.path.unlink()
        self.path.mkdir()
        self.assertEqual(build_info(self.path), self.unknown)

    def test_build_args_unknown_and_valid_short_sha(self):
        self.path.write_text(json.dumps(self.unknown))
        self.assertEqual(build_info(self.path), self.unknown)
        self.path.write_text('{"commit":"3aeb06fb","time":"2026-10-26T04:34:56Z"}')
        self.assertEqual(build_info(self.path), dict(commit="3aeb06fb",
            time="2026-10-26T04:34:56+00:00", branch="unknown"))

    def test_maintenance_reads_image_file(self):
        expected = dict(commit="3aeb06fb", time="2026-10-26T04:34:56+00:00", branch="dev")
        self.path.write_text(json.dumps(expected))
        with patch("musicbot.web_dashboard_maintenance.BUILD_INFO_PATH", self.path):
            status = inspect_status(self.root / "absent-cookie", self.root / "absent-host", self.root)
        self.assertEqual(status["build_info"], expected)
        self.assertEqual(status["dashboard_version"], expected["commit"])
