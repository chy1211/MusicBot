"""Real YoutubeDL clients, synthetic cookies only; never contact a server."""
import asyncio
import contextlib
import inspect
import io
import logging
import os
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from yt_dlp import YoutubeDL
from musicbot.downloader import Downloader
from musicbot.ytdlp_cookies import CookieYtdlClients
from musicbot.bot import MusicBot

HEADER = "# Netscape HTTP Cookie File\n"
def content(value):
    return HEADER + ".youtube.com\tTRUE\t/\tTRUE\t0\tFAKE_SESSION\t" + value + "\n"
def values(client):
    return [cookie.value for cookie in client.cookiejar]


class CookieTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="musicbot-webtest-cookies-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/"cookies.txt"
        self.path.write_text(content("FAKE_OLD"))
        self.clients = CookieYtdlClients({"quiet": True, "no_warnings": True, "cachedir": False}, self.path)

    def replace(self, value):
        other = self.path.with_suffix(".new")
        other.write_text(content(value))
        other.replace(self.path)

    def test_real_clients_reload_both_and_leave_old_generation_untouched(self):
        old = self.clients.snapshot()
        self.assertTrue(all(isinstance(c, YoutubeDL) for c in old))
        self.replace("FAKE_NEW")
        new = self.clients.snapshot(refresh=True)
        for previous, current in zip(old, new):
            self.assertIsNot(previous, current)
            self.assertEqual(values(previous), ["FAKE_OLD"])
            self.assertEqual(values(current), ["FAKE_NEW"])
            self.assertIsNone(current.params.get("cookiefile"))
        self.assertIsNot(new[0].cookiejar, new[1].cookiejar)
        self.assertIs(self.clients.snapshot(refresh=True), new)

    def test_mtime_and_size_each_trigger_reload(self):
        old = self.clients.snapshot()
        stat = self.path.stat()
        os.utime(self.path, ns=(stat.st_atime_ns, stat.st_mtime_ns+1000000))
        self.assertIsNot(self.clients.snapshot(refresh=True), old)
        old = self.clients.snapshot()
        self.path.write_text(content("FAKE_LONGER_NEW"))
        os.utime(self.path, ns=(stat.st_atime_ns, stat.st_mtime_ns+1000000))
        self.assertIsNot(self.clients.snapshot(refresh=True), old)
        self.assertEqual(values(self.clients.snapshot()[0]), ["FAKE_LONGER_NEW"])

    def test_bad_rows_keep_both_old_jars_without_disclosing_data(self):
        old = self.clients.snapshot()
        stderr, stdout = io.StringIO(), io.StringIO()
        for bad in ["FAKE_PRIVATE_INVALID_HEADER",
                    HEADER+"FAKE_PRIVATE_BAD_ROW\n",
                    HEADER+".youtube.com\tTRUE\t/\tTRUE\tFAKE_PRIVATE_EXPIRY\tN\tFAKE_PRIVATE_VALUE\n",
                    HEADER+".youtube.com\tFALSE\t/\tTRUE\t0\tN\tFAKE_PRIVATE_VALUE\n"]:
            self.path.write_text(bad)
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
                with self.assertLogs("musicbot.ytdlp_cookies", level="WARNING") as logs:
                    self.assertIs(self.clients.snapshot(refresh=True), old)
            self.assertEqual(len(logs.output), 1)
            self.assertNotIn("FAKE_PRIVATE", str(logs.output))
            # No repeated warnings or reads for the same failed signature.
            with patch("musicbot.ytdlp_cookies._load_snapshot") as load:
                self.clients.snapshot(refresh=True)
                load.assert_not_called()
        self.assertEqual(stderr.getvalue()+stdout.getvalue(), "")
        self.replace("FAKE_RECOVERED")
        self.assertEqual(values(self.clients.snapshot(refresh=True)[1]), ["FAKE_RECOVERED"])

    def test_read_failure_and_file_replacement_during_load_preserve_old(self):
        old = self.clients.snapshot()
        with patch("musicbot.ytdlp_cookies.Path.open", side_effect=PermissionError("FAKE_PRIVATE")):
            with self.assertLogs("musicbot.ytdlp_cookies", level="WARNING"):
                self.clients.enable()
        self.assertIs(self.clients.snapshot(), old)
        self.replace("FAKE_NEW")
        import musicbot.ytdlp_cookies as module
        real = module._signature
        calls = 0
        def changed(stat):
            nonlocal calls
            calls += 1
            result = real(stat)
            return (*result[:-1], -1) if calls == 3 else result
        with patch.object(module, "_signature", changed):
            with self.assertLogs("musicbot.ytdlp_cookies", level="WARNING"):
                self.clients.snapshot(refresh=True)
        self.assertIs(self.clients.snapshot(), old)

    def test_disable_clears_new_work_and_enable_forces_reload(self):
        old = self.clients.snapshot()
        self.clients.disable()
        self.assertFalse(self.clients.enabled)
        self.replace("FAKE_NEW")
        for client in self.clients.snapshot(refresh=True):
            self.assertEqual(values(client), [])
            self.assertIsNone(client.cookiejar.get_cookie_header("https://www.youtube.com/"))
        self.assertEqual(values(old[0]), ["FAKE_OLD"])
        self.clients.enable()
        self.assertTrue(self.clients.enabled)
        self.assertEqual(values(self.clients.snapshot()[0]), ["FAKE_NEW"])
        current = self.clients.snapshot()
        self.clients.enable()
        self.assertIsNot(self.clients.snapshot(), current)

    def test_failed_second_client_build_never_publishes_half_a_generation(self):
        old = self.clients.snapshot()
        self.replace("FAKE_NEW")
        real = YoutubeDL
        calls = 0
        def build(options):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("FAKE_PRIVATE_BUILD_ERROR")
            return real(options)
        with patch("musicbot.ytdlp_cookies.YoutubeDL", build):
            with self.assertLogs("musicbot.ytdlp_cookies", level="WARNING") as logs:
                self.clients.snapshot(refresh=True)
        self.assertIs(self.clients.snapshot(), old)
        self.assertNotIn("FAKE_PRIVATE", str(logs.output))

    def test_first_file_creation_is_detected_without_timer(self):
        path = self.path.with_name("initially-missing.txt")
        clients = CookieYtdlClients({"quiet": True}, path)
        self.assertFalse(clients.enabled)
        path.write_text(content("FAKE_FIRST"))
        self.assertEqual(values(clients.snapshot(refresh=True)[0]), ["FAKE_FIRST"])

    def test_inflight_extraction_keeps_jar_while_reload_and_disable_complete(self):
        started, release = threading.Event(), threading.Event()
        downloader = Downloader.__new__(Downloader)
        downloader._cookie_clients = self.clients
        def blocked(client, *args, **kwargs):
            before = values(client)
            started.set()
            if not release.wait(10):
                raise RuntimeError("test timeout")
            return before, values(client)
        with patch.object(YoutubeDL, "extract_info", blocked), ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(downloader._run_ytdl, False, "extract_info", "fake")
            self.assertTrue(started.wait(10))
            try:
                self.replace("FAKE_NEW")
                self.assertEqual(values(self.clients.snapshot(refresh=True)[0]), ["FAKE_NEW"])
                self.clients.disable()
                self.assertEqual(values(self.clients.snapshot()[0]), [])
            finally:
                release.set()
            self.assertEqual(future.result(10), (["FAKE_OLD"], ["FAKE_OLD"]))


class CookieCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="musicbot-webtest-cookie-command-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/"cookies.txt"
        self.path.write_text(content("FAKE_OLD"))
        self.downloader = Downloader.__new__(Downloader)
        self.downloader._cookie_clients = CookieYtdlClients({"quiet":True,"cachedir":False}, self.path)
        self.downloader.thread_pool = ThreadPoolExecutor(max_workers=2)
        self.addCleanup(self.downloader.thread_pool.shutdown)
        self.downloader._supported_search = ["ytsearch"]
        self.bot = NS(loop=asyncio.get_running_loop(), config=NS(cookies_path=self.path,
            disabled_cookies_path=self.path.with_suffix(".disabled")), downloader=self.downloader)
        self.downloader.bot = self.bot

    async def test_safe_unsafe_and_cached_download_check_at_worker_start(self):
        def extract(client, *args, **kwargs):
            return {"id":"fake","title":"fake","extractor":"example","cookie_seen":values(client)[0]}
        with patch.object(YoutubeDL,"extract_info",extract), patch.object(YoutubeDL,"process_ie_result",extract), patch("musicbot.downloader.log.noise",create=True):
            for run in (lambda:self.downloader.safe_extract_info("fake"),
                        lambda:self.downloader._filtered_extract_info("fake"),
                        lambda:self.downloader.download_from_info({"id":"fake","title":"fake","ext":"m4a","extractor":"example"})):
                self.path.write_text(content("FAKE_WORKER_NEW"))
                result = await run()
                self.assertEqual(result["cookie_seen"], "FAKE_WORKER_NEW")
                self.path.write_text(content("FAKE_RESET"))
                self.downloader.enable_ytdl_cookies()

    async def test_upload_on_off_use_current_real_jars_immediately(self):
        async def save(path):
            self.assertNotEqual(path, self.path)
            self.assertEqual(values(self.downloader.unsafe_ytdl), ["FAKE_OLD"])
            path.write_text(content("FAKE_UPLOADED"))
        command = inspect.unwrap(MusicBot.cmd_setcookies)
        message = NS(attachments=[NS(save=save)])
        with patch("musicbot.bot._D", side_effect=lambda text,*args:text):
            await command(self.bot,None,message)
            self.assertEqual(values(self.downloader.unsafe_ytdl), ["FAKE_UPLOADED"])
            self.assertEqual(values(self.downloader.safe_ytdl), ["FAKE_UPLOADED"])
            await command(self.bot,None,None,"off")
            self.assertFalse(self.path.exists())
            self.assertEqual(values(self.downloader.unsafe_ytdl), [])
            await command(self.bot,None,None,"on")
            self.assertTrue(self.path.exists())
            self.assertEqual(values(self.downloader.unsafe_ytdl), ["FAKE_UPLOADED"])
        self.assertEqual(list(self.path.parent.glob(".cookies-upload-*")), [])


class SyncScriptTests(unittest.TestCase):
    def test_no_restart_by_default_and_explicit_legacy_opt_in(self):
        # Run a COPY in a temporary fake layout. Production JS is never copied
        # or executed; node and docker are inert PATH stubs.
        with tempfile.TemporaryDirectory(prefix="musicbot-webtest-sync-") as temp:
            root = Path(temp); (root/"tools").mkdir(); (root/"data").mkdir(); (root/"bin").mkdir()
            script = root/"tools"/"sync_cookies.sh"
            script.write_bytes(Path("tools/sync_cookies.sh").read_bytes())
            calls = root/"calls"
            for name in ("node","docker"):
                stub = root/"bin"/name
                stub.write_text('#!/bin/sh\nprintf "%s\\n" "'+name+' $*" >> "$CALLS"\n')
                stub.chmod(0o700)
            for setting, restart in [(None,False),("0",False),("1",True),("true",False)]:
                calls.write_text("")
                env = dict(os.environ, PATH=str(root/"bin")+os.pathsep+os.environ["PATH"],
                           CALLS=str(calls), MUSICBOT_DIR=str(root), CONTAINER_NAME="musicbot-webtest-fake")
                env.pop("MUSICBOT_COOKIE_RESTART",None)
                if setting is not None: env["MUSICBOT_COOKIE_RESTART"] = setting
                result = subprocess.run(["sh",str(script)],env=env,capture_output=True,text=True,check=True)
                lines = calls.read_text().splitlines()
                self.assertTrue(lines[0].startswith("node sync_cookies.js "))
                self.assertEqual(any(line.startswith("docker restart ") for line in lines), restart)
                if not restart: self.assertIn("hot reload",result.stdout)
