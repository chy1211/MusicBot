"""On-demand cookie generations. No background polling or cookie writeback."""
from __future__ import annotations

import copy
import logging
import os
import threading
from http.cookiejar import Cookie
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.cookies import YoutubeDLCookieJar

log = logging.getLogger(__name__)
MAX_COOKIE_BYTES = 4 * 1024 * 1024


def _signature(stat):
    return (stat.st_mtime_ns, stat.st_size, stat.st_ino, stat.st_ctime_ns)


def _load_snapshot(path, expected):
    # Read one descriptor and reject a replacement/in-place write during loading.
    with path.open("rb") as stream:
        before = _signature(os.fstat(stream.fileno()))
        raw = stream.read(MAX_COOKIE_BYTES + 1)
        after = _signature(os.fstat(stream.fileno()))
    if before != expected or after != before or _signature(path.stat()) != before:
        raise ValueError("Cookie file changed while loading")
    if len(raw) > MAX_COOKIE_BYTES:
        raise ValueError("Cookie file too large")
    lines = raw.decode("utf-8-sig").splitlines()
    if not lines or lines[0] not in ("# Netscape HTTP Cookie File", "# HTTP Cookie File"):
        raise ValueError("Invalid Netscape header")

    # yt-dlp's permissive loader prints malformed rows (including values).
    # Parse strictly here so even invalid files can never reach that logger.
    jar = YoutubeDLCookieJar()
    for line in lines[1:]:
        http_only = line.startswith("#HttpOnly_")
        if http_only:
            line = line[len("#HttpOnly_"):]
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            raise ValueError("Invalid Netscape row")
        domain, subdomains, path_value, secure, expiry, name, value = fields
        if (not domain or not path_value.startswith("/") or
                subdomains not in ("TRUE", "FALSE") or secure not in ("TRUE", "FALSE") or
                (subdomains == "TRUE") != domain.startswith(".") or
                (expiry and (not expiry.isascii() or not expiry.isdigit()))):
            raise ValueError("Invalid Netscape fields")
        expires = int(expiry) if expiry else 0
        if expires > 253402300799:
            raise ValueError("Invalid cookie expiry")
        # Netscape's empty-name convention matches MozillaCookieJar.
        if not name:
            name, value = value, None
        jar.set_cookie(Cookie(
            version=0, name=name, value=value, port=None, port_specified=False,
            domain=domain, domain_specified=subdomains == "TRUE",
            domain_initial_dot=domain.startswith("."), path=path_value,
            path_specified=False, secure=secure == "TRUE",
            expires=expires or None, discard=not expires, comment=None,
            comment_url=None, rest={"HTTPOnly": ""} if http_only else {},
            rfc2109=False))
    return jar


class CookieYtdlClients:
    """Publish both clients atomically; never mutate a published cookie jar.

    The lock protects stat/load/build/publication, never an extraction. A worker
    takes a strong reference to its generation before releasing the lock, so
    reload/disable cannot change or close the client it is already using.
    """

    def __init__(self, options, path):
        self.options = dict(options)
        self.options.pop("cookiefile", None)
        self.options.pop("cookiesfrombrowser", None)
        self.path = Path(path)
        self._lock = threading.RLock()
        self._watch_enabled = True
        self._active = False
        self._attempted = None
        self._pair = self._build_pair(YoutubeDLCookieJar())
        self.refresh()

    def _build_pair(self, jar):
        clients = []
        for safe in (False, True):
            options = copy.deepcopy(self.options)
            options["ignoreerrors"] = safe
            client = YoutubeDL(options)
            # No filename: neither close() nor save_cookies() may overwrite the
            # synchronized file. Each generation/client owns its own jar.
            client.cookiejar = YoutubeDLCookieJar()
            for cookie in jar:
                client.cookiejar.set_cookie(copy.deepcopy(cookie))
            clients.append(client)
        return tuple(clients)

    @property
    def enabled(self):
        with self._lock:
            return self._active

    def refresh(self, force=False):
        with self._lock:
            if not self._watch_enabled:
                return
            try:
                signature = _signature(self.path.stat())
            except OSError:
                signature = ("unavailable",)
            if not force and signature == self._attempted:
                return
            self._attempted = signature
            # Missing at startup is ordinary; deletion after a load is a failure.
            if signature == ("unavailable",) and not self._active and not force:
                return
            try:
                jar = _load_snapshot(self.path, signature)
                pair = self._build_pair(jar)
            except Exception:
                # Never log the exception, row, cookie value or traceback.
                log.warning("Cookie reload failed; retaining previous cookie generation.")
                return
            self._pair = pair
            self._active = True
            log.info("Cookie generation reloaded for both yt-dlp clients.")

    def snapshot(self, refresh=False):
        with self._lock:
            if refresh:
                self.refresh()
            return self._pair

    def enable(self):
        with self._lock:
            self._watch_enabled = True
            self.refresh(force=True)

    def disable(self):
        with self._lock:
            pair = self._build_pair(YoutubeDLCookieJar())
            self._pair = pair
            self._watch_enabled = False
            self._active = False
            self._attempted = None
