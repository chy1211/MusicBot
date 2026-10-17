"""Buffered, anonymous member-request popularity for the dashboard.

Only the entry-added observer calls ``record``. Playback/resume/seek are not
requests. Requester data is used to distinguish members from autoplay in memory
and is never copied into the persisted document or public result.
"""
from __future__ import annotations

import asyncio
import copy
import datetime as dt
import ipaddress
import json
import logging
import math
import os
import re
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

log = logging.getLogger(__name__)
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"}
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")


def normalized_url(value):
    """Canonical public HTTP media URL; YouTube variants share one video key."""
    if not isinstance(value, str) or len(value) > 2000 or any(c.isspace() or ord(c) < 32 for c in value):
        return ""
    try:
        parts = urlsplit(value)
        host, port = (parts.hostname or "").lower(), parts.port
        if parts.scheme.lower() not in ("http", "https") or not host or parts.username or parts.password:
            return ""
        if host == "localhost" or host.endswith((".localhost", ".local")) or "." not in host:
            return ""
        try:
            if not ipaddress.ip_address(host).is_global:
                return ""
        except ValueError:
            pass
        if host in YOUTUBE_HOSTS:
            if port not in (None, 80, 443):
                return ""
            segments = parts.path.strip("/").split("/")
            video = segments[0] if host.endswith("youtu.be") else (
                dict(parse_qsl(parts.query)).get("v", "") if parts.path.rstrip("/") == "/watch"
                else segments[1] if len(segments) == 2 and segments[0] in ("shorts", "live", "embed") else "")
            return "https://www.youtube.com/watch?v=" + video if VIDEO_ID.fullmatch(video) else ""
        host = host.encode("idna").decode("ascii")
        authority = host + (":" + str(port) if port is not None and port != (443 if parts.scheme == "https" else 80) else "")
        query = [(key, item) for key, item in parse_qsl(parts.query, keep_blank_values=True)
                 if not key.lower().startswith("utm_") and key.lower() not in {"si", "fbclid", "gclid", "feature"}]
        return urlunsplit((parts.scheme.lower(), authority, parts.path or "/", urlencode(sorted(query)), ""))
    except (ValueError, UnicodeError):
        return ""


def _duration(value):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 31536000:
        raise ValueError("invalid duration")
    return value


def atomic_write(path, document):
    """Write a sibling temporary file, fsync, atomically replace, fsync parent."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        if path.exists():
            stat = path.stat()
            os.fchmod(fd, stat.st_mode & 0o777)
            try:
                os.fchown(fd, stat.st_uid, stat.st_gid)
            except OSError:
                pass
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class PopularityStore:
    """One cache and asyncio lock per server; no synchronous writes per request.

    Pass a server-generated guild object or positive integer, never a body path.
    The default clock uses UTC calendar dates. ``close`` flushes pending changes.
    """
    def __init__(self, root, *, flush_interval=30, clock=None):
        self.root = Path(root)
        self.flush_interval = flush_interval
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc).date())
        self.locks = defaultdict(asyncio.Lock)
        self.cache = {}
        self.dirty = set()
        self._task = None
        self._closed = False
        self._stop = asyncio.Event()
        self._token = object()

    @staticmethod
    def guild_id(guild):
        gid = getattr(guild, "id", guild)
        if type(gid) is not int or not 0 < gid < 10**20:
            raise ValueError("invalid server")
        return gid

    def path(self, guild):
        return self.root / (str(self.guild_id(guild)) + ".json")

    @staticmethod
    def fresh():
        return {"version": 1, "tracks": {}}

    def _read(self, gid):
        path = self.path(gid)
        if not path.exists():
            return self.fresh()
        try:
            if path.stat().st_size > 32 * 1024 * 1024:
                raise ValueError("oversized statistics")
            document = json.loads(path.read_text(encoding="utf-8"))
            if type(document) is not dict or set(document) != {"version", "tracks"} or document["version"] != 1 or type(document["tracks"]) is not dict:
                raise ValueError("invalid document")
            for url, track in document["tracks"].items():
                if not url or normalized_url(url) != url or type(track) is not dict or set(track) != {"url", "title", "duration", "days"} or track["url"] != url:
                    raise ValueError("invalid track")
                if not isinstance(track["title"], str) or not 1 <= len(track["title"]) <= 300 or any(ord(c) < 32 for c in track["title"]):
                    raise ValueError("invalid title")
                _duration(track["duration"])
                if type(track["days"]) is not dict:
                    raise ValueError("invalid days")
                for day, count in track["days"].items():
                    if dt.date.fromisoformat(day).isoformat() != day or type(count) is not int or not 0 < count < 10**15:
                        raise ValueError("invalid count")
            return document
        except OSError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError):
            # A hard-link fails if the unique quarantine name somehow exists:
            # never overwrite an earlier recovery copy, even on a collision.
            while True:
                quarantine = path.with_name(path.name + ".corrupt-" + str(time.time_ns()))
                try:
                    os.link(path, quarantine)
                    break
                except FileExistsError:
                    continue
            path.unlink()
            log.warning("Dashboard popularity statistics quarantined")
            return self.fresh()

    async def _load(self, gid):
        if gid not in self.cache:
            self.cache[gid] = await asyncio.to_thread(self._read, gid)
        return self.cache[gid]

    def _prune(self, gid, document):
        today = self.clock()
        cutoff = today - dt.timedelta(days=179)
        changed = False
        for url, track in list(document["tracks"].items()):
            keep = {day: count for day, count in track["days"].items()
                    if cutoff <= dt.date.fromisoformat(day) <= today}
            if keep != track["days"]:
                changed = True
                track["days"] = keep
            if not keep:
                del document["tracks"][url]
                changed = True
        if changed:
            self.dirty.add(gid)

    def _start(self):
        if self.flush_interval > 0 and not self._closed and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._periodic(), name="dashboard-popularity-flush")

    async def record(self, guild, entry):
        """Count one distinct member-request entry; repeated events do not count."""
        if self._closed or entry is None or getattr(entry, "from_auto_playlist", False):
            return False
        meta = getattr(entry, "meta", None) or {}
        author = (getattr(entry, "author", None) or getattr(entry, "member", None)
                  or meta.get("author") or meta.get("member"))
        if author is None or getattr(author, "bot", False):
            return False
        url = normalized_url(getattr(entry, "url", ""))
        if not url:
            return False
        title = str(getattr(entry, "title", "") or "Unknown")
        title = "".join(c for c in title if ord(c) >= 32).strip()[:300] or "Unknown"
        duration = _duration(getattr(entry, "duration", None))
        gid = self.guild_id(guild)
        async with self.locks[gid]:
            if self._closed:
                return False
            if getattr(entry, "_dashboard_popularity_observed", None) == (self._token, gid):
                return False
            document = await self._load(gid)
            self._prune(gid, document)
            track = document["tracks"].setdefault(url, {"url": url, "title": title, "duration": duration, "days": {}})
            track.update(title=title, duration=duration)
            day = self.clock().isoformat()
            track["days"][day] = track["days"].get(day, 0) + 1
            # Entry metadata is not persisted by this store. Real entry classes
            # and dashboard fixtures permit attributes; this avoids retaining
            # every played entry forever in an identity cache.
            entry._dashboard_popularity_observed = (self._token, gid)
            self.dirty.add(gid)
            self._start()
        return True

    async def top(self, guild, period="7"):
        if period not in ("7", "30", "all"):
            raise ValueError("invalid period")
        gid = self.guild_id(guild)
        async with self.locks[gid]:
            document = await self._load(gid)
            self._prune(gid, document)
            cutoff = self.clock() - dt.timedelta(days={"7": 6, "30": 29, "all": 179}[period])
            rows = []
            for track in document["tracks"].values():
                count = sum(count for day, count in track["days"].items() if dt.date.fromisoformat(day) >= cutoff)
                if count:
                    rows.append({"url": track["url"], "title": track["title"], "duration": track["duration"], "count": count})
            self._start()
            return sorted(rows, key=lambda row: (-row["count"], row["title"].casefold(), row["url"]))[:20]

    async def flush(self):
        for gid in list(self.dirty):
            async with self.locks[gid]:
                if gid not in self.dirty:
                    continue
                document = self.cache[gid]
                self._prune(gid, document)
                await asyncio.to_thread(atomic_write, self.path(gid), copy.deepcopy(document))
                self.dirty.discard(gid)

    async def _periodic(self):
        while not self._closed:
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.flush_interval)
                return
            except asyncio.TimeoutError:
                pass
            try:
                await self.flush()
            except Exception:
                # Keep dirty entries for the next interval; do not leak paths,
                # media URLs, or filesystem exception text in normal logs.
                log.warning("Dashboard popularity statistics flush failed")

    async def close(self):
        self._closed = True
        task, self._task = self._task, None
        self._stop.set()
        if task is not None:
            # Let an in-flight to_thread atomic write finish. Cancelling that
            # await would release its lock while the worker can still replace
            # the file, racing the final flush with an older snapshot.
            await task
        # A request can already hold a lock while awaiting its first disk load.
        # Wait for those accepted observations before taking the dirty snapshot.
        for gid in list(self.locks):
            async with self.locks[gid]:
                pass
        await self.flush()
