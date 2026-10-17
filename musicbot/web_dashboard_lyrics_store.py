"""Atomic bounded lyric results and server-wide calibration; no requester data."""
from __future__ import annotations
import asyncio
import json
import math
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from .web_dashboard_stats import atomic_write, normalized_url

VIDEO = re.compile(r"[A-Za-z0-9_-]{11}\Z")

def video_id(url):
    url = normalized_url(url)
    if not url.startswith("https://www.youtube.com/watch?v="):
        return ""
    value = parse_qs(urlsplit(url).query).get("v", [""])[0]
    return value if VIDEO.fullmatch(value) else ""

class LyricsStore:
    CACHE_LIMIT = 2000
    MAX_BYTES = 50 * 1024 * 1024
    MAX_FILE = 1024 * 1024
    def __init__(self, root):
        self.root = Path(root)
        self.lock = asyncio.Lock()
        self.allowed = {}

    @staticmethod
    def guild_id(guild):
        gid = getattr(guild, "id", guild)
        if type(gid) is not int or not 0 < gid < 10**20:
            raise ValueError()
        return str(gid)

    def path(self, area, key):
        if area not in ("cache", "analysis") or not VIDEO.fullmatch(key):
            raise ValueError()
        return self.root / area / (key+".json")

    def read(self, path):
        try:
            with path.open("rb") as stream:
                raw = stream.read(self.MAX_FILE+1)
            if len(raw) > self.MAX_FILE:
                return None
            value = json.loads(raw)
            return value if isinstance(value, dict) else None
        except (ValueError, OSError, TypeError):
            return None

    def prune(self):
        files = []
        for area in ("cache", "analysis"):
            for path in (self.root / area).glob("*.json"):
                try:
                    stat = path.stat()
                    files.append((stat.st_mtime_ns, path, stat.st_size))
                except OSError:
                    pass
        files.sort(key=lambda row: row[0])
        size, count = sum(row[2] for row in files), len(files)
        for _, path, length in files:
            if count <= self.CACHE_LIMIT and size <= self.MAX_BYTES:
                break
            try:
                path.unlink()
                size -= length; count -= 1
            except OSError:
                pass

    async def get(self, key, area="cache"):
        async with self.lock:
            row = await asyncio.to_thread(self.read, self.path(area, key))
            if row and type(row.get("expires")) in (int, float) and row["expires"] > time.time() and isinstance(row.get("value"), dict):
                return row["value"]
            return None

    async def put(self, key, value, ttl, area="cache"):
        async with self.lock:
            await asyncio.to_thread(atomic_write, self.path(area, key),
                                    {"expires": time.time()+ttl, "value": value})
            await asyncio.to_thread(self.prune)

    async def enabled(self, guild):
        gid = int(self.guild_id(guild))
        if gid not in self.allowed:
            row = await asyncio.to_thread(self.read, self.root / "settings" / (str(gid)+".json"))
            self.allowed[gid] = row.get("enabled", True) if row and type(row.get("enabled")) is bool else True
        return self.allowed[gid]

    async def set_enabled(self, guild, enabled):
        if type(enabled) is not bool:
            raise ValueError()
        async with self.lock:
            await asyncio.to_thread(atomic_write, self.root / "settings" / (self.guild_id(guild)+".json"), {"enabled": enabled})
            self.allowed[int(self.guild_id(guild))] = enabled

    def offset_path(self, guild, key):
        if not VIDEO.fullmatch(key):
            raise ValueError()
        return self.root / "offsets" / self.guild_id(guild) / (key+".json")

    async def manual(self, guild, key):
        row = await asyncio.to_thread(self.read, self.offset_path(guild, key))
        value = row.get("offset") if row else None
        return float(value) if type(value) in (int, float) and math.isfinite(value) and -30 <= value <= 60 else None

    async def set_manual(self, guild, key, value):
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not -30 <= value <= 60):
            raise ValueError()
        async with self.lock:
            await asyncio.to_thread(atomic_write, self.offset_path(guild, key), {"offset": value})
