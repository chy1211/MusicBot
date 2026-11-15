import json
import sys
import types
import unittest
from unittest.mock import patch

import yt_dlp
from yt_dlp.utils import DownloadError, UnsupportedError
from yt_dlp.networking.exceptions import NoSupportingHandlers

from musicbot.native_ytdlp_process import (
    _decode_result, _encode_job, run_native_ytdlp,
)
from musicbot.native_ytdlp_worker import execute


class FakeCookie:
    def __init__(self):
        self.version = 0
        self.name = "test"
        self.value = "secret-cookie"
        self.port = None
        self.port_specified = False
        self.domain = "example.com"
        self.domain_specified = True
        self.domain_initial_dot = False
        self.path = "/"
        self.path_specified = True
        self.secure = True
        self.expires = None
        self.discard = True
        self.comment = None
        self.comment_url = None
        self._rest = {}
        self.rfc2109 = False


class FakeCookieJar:
    def __init__(self):
        self.cookies = []
    def set_cookie(self, cookie):
        self.cookies.append(cookie)


class FakeYtdl:
    def __init__(self, options):
        self.params = options
        self.cookiejar = FakeCookieJar()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def extract_info(self, *args, **kwargs):
        return {"title": "example", "cookie_count": len(self.cookiejar.cookies)}
    def sanitize_info(self, data):
        return data


class NativeWorkerTests(unittest.TestCase):
    def test_ipc_preserves_cookie_but_omits_unserializable_hooks(self):
        client = types.SimpleNamespace(
            params={"extract_flat": False, "logger": object(), "progress_hooks": [object()]},
            cookiejar=[FakeCookie()],
        )
        raw = _encode_job(client, False, "extract_info", ("ytsearch:test",), {"download": False})
        self.assertIn(b"secret-cookie", raw)
        job = json.loads(raw)
        self.assertNotIn("logger", job["options"])
        self.assertNotIn("progress_hooks", job["options"])
        self.assertEqual(job["cookies"][0]["rest"], {})
        with patch.object(yt_dlp, "YoutubeDL", FakeYtdl, create=True):
            result = json.loads(execute(raw))
        self.assertEqual(result["data"]["cookie_count"], 1)

    def test_result_and_error_handling(self):
        self.assertEqual(_decode_result(b'{"data":{"title":"song"}}'), {"title": "song"})
        with self.assertRaises(DownloadError):
            _decode_result(b'{"error":"download_error"}')
        with self.assertRaises(DownloadError) as unsupported:
            _decode_result(b'{"error":"unsupported"}')
        self.assertIs(unsupported.exception.exc_info[0], UnsupportedError)
        with self.assertRaises(NoSupportingHandlers):
            _decode_result(b'{"error":"no_handler"}')
        with self.assertRaises(RuntimeError):
            _decode_result(b'{"error":"provider"}')
        with self.assertRaises(RuntimeError):
            _decode_result(b'garbage')
        with self.assertRaises(ValueError):
            _encode_job(types.SimpleNamespace(params={}, cookiejar=[]),
                        False, "unknown", (), {})

    def test_private_worker_command_and_sync_return(self):
        client = types.SimpleNamespace(params={}, cookiejar=[])
        process = types.SimpleNamespace(
            communicate=lambda input=None, timeout=None: (b'{"data":{"ok":true}}', b""),
            poll=lambda: 0,
            returncode=0,
        )
        with patch("musicbot.native_ytdlp_process.subprocess.Popen", return_value=process) as spawn:
            result = run_native_ytdlp(client, False, "extract_info", "ytsearch:test", download=False)
        self.assertEqual(result, {"ok": True})
        args, kwargs = spawn.call_args
        self.assertIn("musicbot.native_ytdlp_worker", args[0])
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(kwargs["stderr"], __import__("subprocess").DEVNULL)


if __name__ == "__main__":
    unittest.main()
