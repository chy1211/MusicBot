"""Run native yt-dlp operations outside the main Python interpreter.

Called by existing Downloader ThreadPoolExecutor workers, so waiting for the
child releases the GIL; a child gen2 GC cannot pause Discord audio threads.
IPC is a private pipe, never command-line arguments, logs, or temp files.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from typing import Any

from yt_dlp.utils import DownloadError, UnsupportedError
from yt_dlp.networking.exceptions import NoSupportingHandlers

MAX_JOB = 32 * 1024 * 1024
MAX_RESULT = 64 * 1024 * 1024
OMIT_OPTIONS = frozenset({
    "logger", "progress_hooks", "postprocessor_hooks",
    "cookiefile", "cookiesfrombrowser",
})


def _cookie_snapshot(client: Any) -> list[dict[str, Any]]:
    cookies = []
    for cookie in client.cookiejar:
        fields = dict(vars(cookie))
        fields["rest"] = fields.pop("_rest", {})
        cookies.append(fields)
    return cookies


def _encode_job(client: Any, safe: bool, method: str, args: tuple, kwargs: dict) -> bytes:
    if method not in {"extract_info", "process_ie_result"}:
        raise ValueError("method not supported by native isolation")
    options = {key: value for key, value in client.params.items()
               if key not in OMIT_OPTIONS}
    job = {
        "method": method, "safe": safe, "options": options,
        "cookies": _cookie_snapshot(client),
        "args": args, "kwargs": kwargs,
    }
    def encode_special(value: Any) -> list[str]:
        if isinstance(value, set):
            return sorted(value)
        raise TypeError(f"Unsupported IPC value type: {type(value).__name__}")

    payload = json.dumps(job, ensure_ascii=False, default=encode_special).encode("utf-8")
    if len(payload) > MAX_JOB:
        raise RuntimeError("native yt-dlp request exceeds IPC limit")
    return payload


def _decode_result(raw: bytes) -> Any:
    if len(raw) > MAX_RESULT:
        raise RuntimeError("native yt-dlp response exceeds IPC limit")
    try:
        response = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("invalid native yt-dlp worker response") from exc
    if not isinstance(response, dict):
        raise RuntimeError("invalid native yt-dlp response shape")
    if "error" in response:
        if response["error"] == "download_error":
            raise DownloadError("yt-dlp extraction failed in isolated process")
        if response["error"] == "unsupported":
            cause = UnsupportedError("isolated media subject")
            raise DownloadError("Unsupported extractor in isolated process",
                                (UnsupportedError, cause, None))
        if response["error"] == "no_handler":
            raise NoSupportingHandlers([], [])
        raise RuntimeError("native yt-dlp worker failed")
    if "data" not in response:
        raise RuntimeError("missing native yt-dlp result")
    return response["data"]


def run_native_ytdlp(client: Any, safe: bool, method: str, *args: Any,
                     timeout: int = 240, **kwargs: Any) -> Any:
    """A synchronous worker function, called only from Downloader's executor."""
    request = _encode_job(client, safe, method, args, kwargs)
    process = subprocess.Popen(
        [sys.executable, "-m", "musicbot.native_ytdlp_worker"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )
    try:
        try:
            stdout, _ = process.communicate(request, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("native yt-dlp worker timed out") from exc
        if process.returncode != 0:
            raise RuntimeError("native yt-dlp worker exited abnormally")
        return _decode_result(stdout)
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.communicate()
