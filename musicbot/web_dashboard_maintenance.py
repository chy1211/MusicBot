"""Owner-only maintenance metadata. Never deserialize cookie values or log tails."""
from __future__ import annotations
from .web_dashboard_i18n import message as _web_text

import asyncio
import importlib
import importlib.metadata
import json
import math
import mmap
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web
from . import write_path

LOGIN_COOKIES = {b"__Secure-3PSID", b"__Secure-1PSID", b"SAPISID", b"LOGIN_INFO",
                 b"SID", b"HSID", b"SSID", b"APISID",
                 b"__Secure-1PAPISID", b"__Secure-3PAPISID"}


def timestamp(value):
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def cookie_status(path, now=None):
    """Only slice Netscape expiry (field 4) and name (field 5).

    mmap.find locates separators without building a line or decoding its value.
    The value column is never sliced, retained, returned or logged.
    """
    now = time.time() if now is None else now
    try:
        with Path(path).open("rb") as stream:
            stat = Path(path).stat()
            result = {"status": "ok", "updated_at": timestamp(stat.st_mtime),
                      "earliest_expiry": None, "remaining_days": None,
                      "warning": False, "cookies": []}
            if stat.st_size > 4 * 1024 * 1024:
                return {"status": "unavailable"}
            if not stat.st_size:
                return result
            expiries = {}
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                start = 0
                while start < len(data):
                    end = data.find(b"\n", start)
                    if end < 0:
                        end = len(data)
                    # Comments, including HttpOnly prefixes, contain no values
                    # that we need. HttpOnly records still use six tab separators.
                    positions = []
                    cursor = start
                    for _ in range(6):
                        tab = data.find(b"\t", cursor, end)
                        if tab < 0:
                            break
                        positions.append(tab)
                        cursor = tab + 1
                    if len(positions) == 6:
                        name = data[positions[4]+1:positions[5]]
                        if name in LOGIN_COOKIES:
                            expiry = data[positions[3]+1:positions[4]]
                            if expiry.isdigit() and len(expiry) <= 12:
                                number = int(expiry)
                                if number > 0 and timestamp(number):
                                    expiries[name] = min(expiries.get(name, number), number)
                    start = end + 1
            for name, expiry in sorted(expiries.items()):
                result["cookies"].append({"name": name.decode("ascii"),
                    "expires_at": timestamp(expiry), "remaining_days": math.floor((expiry-now)/86400)})
            if expiries:
                earliest = min(expiries.values())
                result.update(earliest_expiry=timestamp(earliest),
                              remaining_days=math.floor((earliest-now)/86400),
                              warning=earliest-now <= 7*86400)
            return result
    except FileNotFoundError:
        return {"status": "unused"}
    except (OSError, ValueError):
        return {"status": "unavailable"}


def iso_date(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else None
    except ValueError:
        return None


def version_text(value):
    return value if isinstance(value, str) and re.fullmatch(r"[0-9][A-Za-z0-9.+_-]{0,63}", value) else None


def host_status(path):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(32769)
        if len(raw) > 32768:
            raise ValueError()
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError()
        update, sync = data.get("ytdlp_update", {}), data.get("cookie_sync", {})
        if not isinstance(update, dict) or not isinstance(sync, dict):
            raise ValueError()
        return {"status": "ok", "written_at": iso_date(data.get("written_at")),
            "ytdlp_update": {"updated": iso_date(update.get("updated")),
                "channel": update.get("channel") if update.get("channel") in ("stable", "nightly") else "unknown",
                **{key: version_text(update.get(key)) for key in ("yt-dlp", "yt-dlp-ejs", "bgutil-plugin")}},
            "cookie_sync": {"last_run": iso_date(sync.get("last_run")),
                "next_run": iso_date(sync.get("next_run")),
                "result": sync.get("result") if sync.get("result") in ("success", "failure", "running") else "unknown"}}
    except FileNotFoundError:
        return {"status": "missing"}
    except (OSError, ValueError, TypeError):
        return {"status": "unavailable"}


def last_stop(root):
    try:
        # Rotation filenames identify ended runs. mtime avoids the legacy
        # filename formatter's month/minute ambiguity and uses a real UTC time.
        paths = (p for p in Path(root).glob("musicbot.ended-*.log") if p.is_file())
        latest = max(paths, key=lambda p: p.stat().st_mtime, default=None)
        if latest is None:
            return None
        with latest.open("rb") as stream:
            stream.seek(max(0, latest.stat().st_size-16384))
            tail = b"\n".join(stream.read(16384).splitlines()[-40:]).lower()
        # A generic "All done" also follows startup failures; it is not proof
        # of a normal exit. Prefer explicit errors over clean-shutdown markers.
        abnormal = any(word in tail for word in
                       (b"traceback", b"error starting bot", b"critical", b"start up failed", b"exception thrown"))
        normal = any(word in tail for word in
                     (b"now doing shutdown steps", b"disconnecting and closing down musicbot",
                      b"doing a full process restart", b"caught a signal from the os"))
        return {"time": timestamp(latest.stat().st_mtime),
                "classification": _web_text('m0556') if normal and not abnormal else _web_text('m0557')}
    except OSError:
        return None


def loaded_versions():
    values = {}
    try:
        values["yt-dlp"] = version_text(importlib.import_module("yt_dlp.version").__version__)
    except (ImportError, AttributeError):
        values["yt-dlp"] = None
    try:
        importlib.import_module("yt_dlp_ejs")
        values["yt-dlp-ejs"] = version_text(importlib.metadata.version("yt-dlp-ejs"))
    except (ImportError, importlib.metadata.PackageNotFoundError):
        values["yt-dlp-ejs"] = None
    return values


def inspect_status(cookie, host, logs, sw):
    try:
        match = re.search(r'const VERSION = "([A-Za-z0-9._-]+)"', Path(sw).read_text(encoding="utf-8"))
        version = match[1] if match else None
    except OSError:
        version = None
    return {"cookie": cookie_status(cookie), "versions": loaded_versions(),
            "host_status": host_status(host), "last_stop": last_stop(logs),
            "dashboard_version": version}


class DashboardMaintenance:
    def init_maintenance(self):
        self.web_viewers = {}
        self.maintenance_root = write_path("data")
        self.maintenance_logs = write_path("logs")
        self.dashboard_started_at = time.time()
        self.maintenance_lock = asyncio.Lock()
        self.maintenance_cached = None
        self.app.router.add_get("/api/guilds/{guild_id}/admin/maintenance", self.admin_maintenance)

    async def admin_maintenance(self, request):
        self.require_owner(request)
        async with self.maintenance_lock:
            if self.discord_auth:
                self.authenticate(request)
            self.require_owner(request)
            now = time.monotonic()
            if self.maintenance_cached is None or self.maintenance_cached[0] <= now:
                value = await asyncio.to_thread(inspect_status,
                    self.maintenance_root/"cookies.txt",
                    self.maintenance_root/"web_dashboard/host_status.json",
                    self.maintenance_logs, Path(__file__).with_name("web")/"sw.js")
                self.maintenance_cached = (now+15, value)
            if self.discord_auth:
                self.authenticate(request)
            self.require_owner(request)
            value = dict(self.maintenance_cached[1])
        cutoff = time.monotonic()-45
        self.web_viewers = {uid: at for uid, at in self.web_viewers.items() if at > cutoff}
        value.update(started_at=timestamp(getattr(self.bot, "_init_time", self.dashboard_started_at)),
                     viewers=len(self.web_viewers), viewer_window_seconds=45)
        return web.json_response(value)
