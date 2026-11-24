"""Single-use native yt-dlp child. Never expose cookies or URLs in logs."""
from __future__ import annotations

from http.cookiejar import Cookie
import json
import sys


def execute(raw: bytes) -> bytes:
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError, UnsupportedError
    from yt_dlp.networking.exceptions import NoSupportingHandlers

    if len(raw) > 32 * 1024 * 1024:
        return b'{"error":"invalid"}'
    try:
        job = json.loads(raw)
        method = job["method"]
        if method not in ("extract_info", "process_ie_result"):
            return b'{"error":"invalid"}'
        options = job["options"]
        for option in ("remote_components", "compat_opts"):
            if isinstance(options.get(option), list):
                options[option] = set(options[option])
        options["ignoreerrors"] = bool(job["safe"])
        with YoutubeDL(options) as client:
            for fields in job.get("cookies", []):
                client.cookiejar.set_cookie(Cookie(**fields))
            result = getattr(client, method)(*job["args"], **job["kwargs"])
            result = client.sanitize_info(result)
        output = json.dumps({"data": result}, ensure_ascii=False).encode("utf-8")
        if len(output) > 64 * 1024 * 1024:
            return b'{"error":"oversize"}'
        return output
    except DownloadError as exc:
        if exc.exc_info and exc.exc_info[0] is UnsupportedError:
            return b'{"error":"unsupported"}'
        return b'{"error":"download_error"}'
    except NoSupportingHandlers:
        return b'{"error":"no_handler"}'
    except Exception:
        return b'{"error":"provider"}'


def main() -> None:
    from .bg_priority import apply_background_priority
    apply_background_priority()
    output = sys.stdout.buffer
    sys.stdout = sys.stderr  # Prevent yt-dlp output from corrupting JSON IPC.
    raw = sys.stdin.buffer.read(32 * 1024 * 1024 + 1)
    result = execute(raw)
    output.write(result)
    output.flush()


if __name__ == "__main__":
    main()
