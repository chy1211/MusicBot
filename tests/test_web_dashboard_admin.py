"""Owner administration integration using real temporary files and native objects."""
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import test_web_dashboard_library as library
import test_web_dashboard_discord as identity
from test_web_dashboard import BASE
from musicbot.autoplaylist import AutoPlaylist

AUTO = BASE + "admin/autoplaylist"


class AutoTests(unittest.IsolatedAsyncioTestCase):
    provider_token = identity.DiscordTests.provider_token
    provider_me = identity.DiscordTests.provider_me
    call = identity.DiscordTests.call
    login_as = identity.DiscordTests.login_as

    async def asyncSetUp(self):
        await library.LibraryTests.asyncSetUp(self)
        self.login_as(42)
        self.aplpath = Path(self.temp.name) / "default.txt"
        self.aplpath.write_text("# Keep comment\nhttps://example.test/one\nhttps://example.test/two\n")
        self.bot.filecache = NS(remove_autoplay_cachemap_entry_by_url=lambda _: None)
        self.apl = AutoPlaylist(self.aplpath, self.bot)
        await self.apl.load()
        self.bot.server_data[1] = NS(autoplaylist=self.apl)
        self.dashboard.backup_root = Path(self.temp.name) / "backups"

    async def asyncTearDown(self):
        await library.LibraryTests.asyncTearDown(self)

    async def snapshot(self):
        return await self.call(AUTO, method="GET")

    async def test_nonowner_all_methods_403_and_hidden_capability(self):
        for uid in (43, 44):
            self.login_as(uid)
            v = await self.call("/api/library", method="GET")
            self.assertFalse(v["owner"])
            for method in ("GET", "POST", "DELETE"):
                await self.call(AUTO, {}, method, 403)

    async def test_native_add_remove_backup_and_memory(self):
        original = self.aplpath.read_bytes()
        v = await self.snapshot()
        with patch.object(self.apl, "add_track", wraps=self.apl.add_track) as add:
            v = await self.call(AUTO, {"revision": v["revision"], "url": "https://example.test/three"})
            add.assert_awaited_once_with("https://example.test/three")
        backups = list((self.dashboard.backup_root / "autoplaylist").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        self.assertIn("https://example.test/three", self.apl)
        with patch.object(self.apl, "remove_track", wraps=self.apl.remove_track) as remove:
            await self.call(AUTO, {"revision": v["revision"], "index": 2}, "DELETE")
            remove.assert_awaited_once()
            self.assertTrue(remove.call_args.kwargs["delete_from_ap"])
        self.assertNotIn("https://example.test/three", self.apl)
        self.assertTrue(self.apl.rmlog_file.exists())
        self.assertIn("# Keep comment", self.aplpath.read_text())

    async def test_backup_rotation_and_current(self):
        for i in range(34):
            v = await self.snapshot()
            await self.call(AUTO, {"revision": v["revision"], "url": "https://example.test/" + str(i)})
        self.assertEqual(len(list((self.dashboard.backup_root / "autoplaylist").iterdir())), 30)
        v = await self.snapshot()
        await self.call(AUTO, {"revision": v["revision"], "current": True})
        self.assertIn(self.bot.player.current_entry.url, self.apl)

    async def test_search_pagination_validation_and_no_local_path_disclosure(self):
        for i in range(120):
            await self.apl.add_track("https://example.test/extra/" + str(i))
        await self.apl.add_track("/private/local/music.mp3")
        v = await self.call(AUTO + "?page=2", method="GET")
        self.assertEqual(len(v["tracks"]), 50)
        self.assertEqual(v["total"], 123)
        v = await self.call(AUTO + "?q=extra%2F11", method="GET")
        self.assertEqual(v["matched"], 11)
        v = await self.call(AUTO + "?page=3", method="GET")
        self.assertNotIn("/private/local", str(v))
        for page in ("0", "-1", "bad", "1000001"):
            await self.call(AUTO + "?page=" + page, method="GET", status=400)

    async def test_conflict_and_no_bulk_operations(self):
        v = await self.snapshot()
        await self.call(AUTO, {"revision": "stale", "url": "https://example.test/new"}, status=409)
        for data in ({"clear": True}, {"tracks": []}, {"url": "file:///secret"}, {"url": "https://example.test/one"}):
            await self.call(AUTO, dict(data, revision=v["revision"]), status=400)
        self.assertFalse(self.dashboard.backup_root.exists())

    async def test_write_failure_reload_memory_and_no_false_success(self):
        v = await self.snapshot()
        with patch.object(self.apl, "add_track", side_effect=AsyncMock(side_effect=lambda u: self.apl.data.append(u))):
            await self.call(AUTO, {"revision": v["revision"], "url": "https://example.test/fail"}, status=500)
        self.assertNotIn("https://example.test/fail", self.apl)

    async def test_backup_failure_aborts_native_write(self):
        v = await self.snapshot()
        with patch("musicbot.web_dashboard_admin.backup_file", side_effect=OSError()), patch.object(self.apl, "add_track") as add:
            await self.call(AUTO, {"revision": v["revision"], "url": "https://example.test/fail"}, status=500)
            add.assert_not_called()
