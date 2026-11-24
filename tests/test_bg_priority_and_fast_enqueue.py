import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from musicbot.bg_priority import apply_background_priority


class BackgroundPriorityTests(unittest.TestCase):
    def test_apply_background_priority_calls_nice_and_ionice(self):
        with patch("musicbot.bg_priority.os.nice") as mock_nice,              patch("musicbot.bg_priority.shutil.which", return_value="/bin/ionice"),              patch("musicbot.bg_priority.subprocess.run") as mock_run:
            apply_background_priority(niceness=10, io_class="3")
        mock_nice.assert_called_once_with(10)
        mock_run.assert_called_once()
        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[:3], ["/bin/ionice", "-c", "3"])
        self.assertEqual(cmd[3], "-p")


class FastSearchEnqueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_fast_entry_attached_on_youtube_search_preview(self):
        from musicbot.dashboard_backend.resolve import DashboardResolveRoutes

        mixin = DashboardResolveRoutes()
        mixin.PREVIEW_TTL = 300
        mixin.previews = {}
        mixin.import_previews = {}
        guild = NS(id=1)
        owner = NS(id=2)
        results = [{
            "kind": "track",
            "title": "Test Song",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "duration": 212,
            "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
            "allowed": True,
        }]
        await mixin.issue_previews(guild, owner, results, "test query", "play")
        pid = results[0]["preview_id"]
        fast = mixin.previews[pid].get("fast_entry")
        self.assertIsNotNone(fast)
        self.assertEqual(fast["title"], "Test Song")
        self.assertEqual(fast["duration"], 212)
        self.assertEqual(fast["extractor"], "youtube")
        self.assertEqual(fast["__input_subject"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    async def test_fast_entry_skipped_for_zero_duration_or_non_youtube(self):
        from musicbot.dashboard_backend.resolve import DashboardResolveRoutes

        mixin = DashboardResolveRoutes()
        mixin.PREVIEW_TTL = 300
        mixin.previews = {}
        mixin.import_previews = {}
        guild = NS(id=1)
        owner = NS(id=2)
        results = [
            {"kind": "track", "title": "Live", "url": "https://www.youtube.com/watch?v=abc", "duration": 0, "allowed": True},
            {"kind": "track", "title": "SC", "url": "https://soundcloud.com/a/b", "duration": 180, "allowed": True},
        ]
        await mixin.issue_previews(guild, owner, results, "q", "play")
        for r in results:
            self.assertNotIn("fast_entry", mixin.previews[r["preview_id"]])
