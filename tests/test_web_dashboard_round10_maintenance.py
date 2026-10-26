"""Owner-only metadata tests; all cookies/logs/host files are synthetic."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import test_web_dashboard_discord as identity
from test_web_dashboard import BASE
from musicbot.web_dashboard_maintenance import cookie_status, host_status, last_stop

URL = BASE+"admin/maintenance"
SECRET = "FAKE_COOKIE_VALUE_MUST_NOT_ESCAPE"


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="musicbot-webtest-meta-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_cookie_only_expiry_names_warning_and_no_value(self):
        now = 1800000000
        path = self.root/"cookies.txt"
        path.write_text("# Netscape HTTP Cookie File\n"
            f".youtube.com\tTRUE\t/\tTRUE\t{now+5*86400}\tSAPISID\t{SECRET}\n"
            f"#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t{now+20*86400}\tLOGIN_INFO\t{SECRET}\n"
            f".youtube.com\tTRUE\t/\tTRUE\t{now+3*86400}\tSAPISID\t{SECRET}\n"
            f".youtube.com\tTRUE\t/\tTRUE\t0\t__Secure-3PSID\t{SECRET}\n"
            f".youtube.com\tTRUE\t/\tTRUE\t1\tUNKNOWN\t{SECRET}\n")
        result = cookie_status(path,now)
        self.assertEqual(result["remaining_days"],3)
        self.assertTrue(result["warning"])
        self.assertEqual([x["name"] for x in result["cookies"]],["LOGIN_INFO","SAPISID"])
        self.assertNotIn(SECRET,json.dumps(result))
        # Instrument mmap slices: the value column must never be materialized.
        import mmap
        real = mmap.mmap
        slices = []
        class Map:
            def __init__(self,*args,**kwargs):self.inner=real(*args,**kwargs)
            def __enter__(self):return self
            def __exit__(self,*_):self.inner.close()
            def __len__(self):return len(self.inner)
            def find(self,*args):return self.inner.find(*args)
            def __getitem__(self,key):
                value=self.inner[key];slices.append(value);return value
        with patch("musicbot.web_dashboard_maintenance.mmap.mmap",Map):
            self.assertEqual(cookie_status(path,now),result)
        self.assertTrue(slices)
        self.assertTrue(all(SECRET.encode() not in value for value in slices))

    def test_missing_empty_malformed_and_expired_cookie(self):
        path = self.root/"cookies.txt"
        self.assertEqual(cookie_status(path)["status"],"unused")
        path.write_text("bad\n# comment\n")
        self.assertEqual(cookie_status(path)["cookies"],[])
        path.write_text("")
        self.assertEqual(cookie_status(path)["status"],"ok")
        path.write_text(".youtube.com\tTRUE\t/\tTRUE\t100\tSAPISID\tx")
        self.assertLess(cookie_status(path,200)["remaining_days"],0)

    def test_host_missing_corrupt_bounded_and_allowlisted(self):
        path = self.root/"host_status.json"
        self.assertEqual(host_status(path)["status"],"missing")
        for bad in ("{", "[]", '{"cookie_sync":null}', "x"*32769):
            path.write_text(bad)
            self.assertEqual(host_status(path)["status"],"unavailable")
        path.write_text(json.dumps({"written_at":"2026-10-17T06:00:00Z",
            "secret":SECRET, "ytdlp_update":{"channel":"nightly","yt-dlp":"2026.10.17","other":SECRET},
            "cookie_sync":{"result":"success","last_run":"not a date","next_run":"2026-10-18T00:00:00Z"}}))
        value=host_status(path)
        self.assertEqual(value["cookie_sync"]["result"],"success")
        self.assertIsNone(value["cookie_sync"]["last_run"])
        self.assertNotIn(SECRET,json.dumps(value))

    def test_tail_classifies_and_never_returns_log_text(self):
        self.assertIsNone(last_stop(self.root))
        old=self.root/"musicbot.ended-2026-001-000000.log"
        old.write_text("Traceback\nPRIVATE_OLD_LOG")
        os.utime(old,(100,100))
        path=self.root/"musicbot.ended-2026-002-000000.log"
        path.write_text("Disconnecting and closing down MusicBot...\nAll done.\n"+SECRET)
        self.assertEqual(last_stop(self.root)["classification"],"正常")
        self.assertNotIn(SECRET,str(last_stop(self.root)))
        path.write_text("Error starting bot\nAll done.\n"+SECRET)
        self.assertEqual(last_stop(self.root)["classification"],"異常")
        path.write_text("MusicBot is now doing shutdown steps...\nTraceback")
        self.assertEqual(last_stop(self.root)["classification"],"異常")
        path.write_text("All done.")
        self.assertEqual(last_stop(self.root)["classification"],"異常")


class MaintenanceAPITests(unittest.IsolatedAsyncioTestCase):
    provider_token=identity.DiscordTests.provider_token
    provider_me=identity.DiscordTests.provider_me
    call=identity.DiscordTests.call
    login_as=identity.DiscordTests.login_as

    async def asyncSetUp(self):
        await identity.DiscordTests.asyncSetUp(self)
        self.temp=tempfile.TemporaryDirectory(prefix="musicbot-webtest-maintenance-")
        root=Path(self.temp.name)
        self.dashboard.maintenance_root=root/"data";self.dashboard.maintenance_root.mkdir()
        self.dashboard.maintenance_logs=root/"logs";self.dashboard.maintenance_logs.mkdir()

    async def asyncTearDown(self):
        await identity.DiscordTests.asyncTearDown(self)
        self.temp.cleanup()

    async def test_owner_only_and_read_only(self):
        for uid in (43,44):
            self.login_as(uid)
            await self.call(URL,method="GET",status=403)
        self.login_as(42)
        value=await self.call(URL,method="GET")
        self.assertEqual(value["cookie"]["status"],"unused")
        self.assertEqual(value["host_status"]["status"],"missing")
        self.assertEqual(value["dashboard_version"], value["build_info"]["commit"])
        self.assertEqual(set(value["build_info"]), {"commit", "time", "branch"})
        self.assertIsNone(value["last_stop"])
        await self.call(URL,{},status=405)
        await self.call(URL,method="GET",headers={},status=403)

    async def test_cookie_value_absent_from_response_and_logs(self):
        self.login_as(42)
        now=int(time.time())
        (self.dashboard.maintenance_root/"cookies.txt").write_text(
            f".youtube.com\tTRUE\t/\tTRUE\t{now+86400}\tSAPISID\t{SECRET}\n")
        with self.assertLogs("musicbot.web_dashboard",level="INFO") as logs:
            value=await self.call(URL,method="GET")
        self.assertTrue(value["cookie"]["warning"])
        self.assertNotIn(SECRET,json.dumps(value))
        self.assertNotIn(SECRET," ".join(logs.output))
        self.assertEqual(value["viewers"],1)

    async def test_bad_host_is_tolerated_and_no_raw_message(self):
        self.login_as(42)
        path=self.dashboard.maintenance_root/"web_dashboard";path.mkdir()
        (path/"host_status.json").write_text("{"+SECRET)
        value=await self.call(URL,method="GET")
        self.assertEqual(value["host_status"]["status"],"unavailable")
        self.assertNotIn(SECRET,str(value))

    async def test_live_viewer_count_expires_and_deduplicates(self):
        await self.call(BASE+"state",method="GET")
        self.login_as(42)
        value=await self.call(URL,method="GET")
        self.assertEqual(value["viewers"],2)
        self.dashboard.web_viewers[43]=time.monotonic()-46
        value=await self.call(URL,method="GET")
        self.assertEqual(value["viewers"],1)
