"""Bounded, anonymous and timeout-safe LRCLIB adapter."""
from __future__ import annotations
import asyncio
import difflib
import json
import math
import re
import random
from email.utils import parsedate_to_datetime
import time
from collections import OrderedDict
import aiohttp

USER_AGENT = "MusicBot-WebDashboard/12 (+https://github.com/Just-Some-Bots/MusicBot)"
LRCLIB_ROOT = "https://lrclib.net/api"
_NOISE = re.compile(r"(?:official|music\s*video|\bmv\b|\bm/v\b|lyrics?|audio|\bhd\b|\bhq\b|\b4k\b|完整版|官方|字幕)", re.I)


def clean_metadata(title, artist=""):
    """Remove presentation labels while preserving meaningful song-name brackets."""
    title, artist = str(title or "")[:300], str(artist or "")[:160]
    title = re.sub(r"[\x00-\x1f\x7f]", "", title)
    artist = re.sub(r"[\x00-\x1f\x7f]", "", artist)
    title = re.sub(r"[\(（\[【]([^\)）\]】]*)[\)）\]】]",
                   lambda m: "" if _NOISE.search(m.group(1)) else m.group(0), title)
    title = re.sub(r"\s*[|｜]\s*.*(?:official|\bMV\b|lyrics?|audio).*$", "", title, flags=re.I)
    title = re.sub(r"\s*\b(?:official\s+(?:(?:music\s+)?video|audio|mv)|music\s+video|mv|m/v|lyric\s+video)\s*$", "", title, flags=re.I)
    if not artist:
        labeled = re.fullmatch(r"\s*(.+?)[【「『](.+)[】」』]\s*", title)
        if labeled:
            artist, title = labeled.groups()
    if not artist:
        parts = re.split(r"\s+[-–—]\s+", title, maxsplit=1)
        if len(parts) == 2:
            artist, title = parts
    if artist:
        norm = lambda value: re.sub(r"[\W_]", "", str(value).casefold())
        parts = re.split(r"\s+[-–—]\s+", title, maxsplit=1)
        if len(parts) == 2 and norm(parts[0]) and norm(parts[0]) == norm(artist):
            title = parts[1]
        labeled = re.fullmatch(r"\s*(.+?)[【「『](.+)[】」』]\s*", title)
        if labeled and norm(labeled[1]) == norm(artist):
            title = labeled[2]
    title = re.sub(r"\s*[\(（]?\s*\b(?:feat|ft|featuring)\b\.?\s+.*$", "", title, flags=re.I)
    artist = re.sub(r"\s*\b(?:feat|ft|featuring)\b\.?\s+.*$", "", artist, flags=re.I)
    return (re.sub(r"\s+", " ", title).strip(" -–—|｜")[:200],
            re.sub(r"\s+", " ", artist).strip(" -–—|｜")[:160])


def parse_lrc(value):
    lines = []
    for row in str(value or "")[:100000].splitlines():
        stamps = re.findall(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]", row)
        text = re.sub(r"\[[^\]]*\]", "", row).strip()[:1000]
        for minute, second, fraction in stamps:
            if int(second) >= 60:
                continue
            stamp = int(minute) * 60 + int(second)
            if fraction:
                stamp += int(fraction) / (10 ** len(fraction))
            lines.append({"time": stamp, "text": text})
            if len(lines) >= 2000:
                return sorted(lines, key=lambda line: line["time"])
    return sorted(lines, key=lambda line: line["time"])


def result(title, artist, item=None, status="not_found"):
    item = item or {}
    lines = parse_lrc(item.get("syncedLyrics", ""))
    plain = str(item.get("plainLyrics") or "")[:60000]
    return {"status": "instrumental" if item.get("instrumental") is True else "synced" if lines else "plain" if plain.strip() else status,
            "duration": item.get("duration") if type(item.get("duration")) in (int, float) else None,
            "title": str(item.get("trackName") or title)[:200],
            "artist": str(item.get("artistName") or artist)[:160],
            "plain_lyrics": plain, "lines": lines}


class LyricsClient:
    TIMEOUT = 20
    REQUEST_TIMEOUT = 6
    ATTEMPTS = 3
    FAILURE_TTL = 5
    NOT_FOUND_TTL = 3 * 3600
    CACHE_TTL = 3600
    CACHE_LIMIT = 200
    MAX_BODY = 1024 * 1024
    MIN_INTERVAL = .2

    def __init__(self):
        self.cache = OrderedDict()
        self.lock = asyncio.Lock()
        self.last_request = 0
        self.pending = {}
        self.retry_after = {}

    async def lookup(self, title, artist, duration, query=""):
        title, artist = clean_metadata(title, artist)
        try:
            duration = float(duration or 0)
        except (TypeError, ValueError):
            duration = 0
        if not math.isfinite(duration):
            duration = 0
        key = (title.casefold(), artist.casefold(), round(duration), query.casefold())
        cached = self.cache.get(key)
        if cached and cached[0] > time.monotonic():
            self.cache.move_to_end(key)
            return cached[1]
        if not title and not query:
            return result(title, artist)
        task = self.pending.get(key)
        if task is None:
            task = asyncio.create_task(self._lookup_bounded(key, title, artist, duration, query))
            self.pending[key] = task
            task.add_done_callback(lambda done: self.pending.pop(key, None))
        return await asyncio.shield(task)

    def _cache(self, key, value, ttl):
        self.cache[key] = (time.monotonic() + ttl, value)
        self.cache.move_to_end(key)
        while len(self.cache) > self.CACHE_LIMIT:
            self.cache.popitem(last=False)
        return value

    async def _lookup_bounded(self, key, title, artist, duration, query):
        try:
            value = await asyncio.wait_for(self._lookup(title, artist, duration, query), self.TIMEOUT)
        except (asyncio.TimeoutError, aiohttp.ClientError, ValueError, TypeError, KeyError):
            value = result(title, artist, status="unavailable")
        ttl = self.FAILURE_TTL if value["status"] == "unavailable" else self.NOT_FOUND_TTL if value["status"] == "not_found" else self.CACHE_TTL
        return self._cache(key, value, ttl)

    async def _lookup(self, title, artist, duration, query):
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            trust_env=False) as session:
            item, failed = None, False
            if artist and not query:
                params = {"track_name": title, "artist_name": artist}
                if 1 <= duration <= 3600:
                    params["duration"] = str(round(duration))
                try:
                    item = await self._request(session, "/get", params)
                    if item is not None and not isinstance(item, dict):
                        raise ValueError("invalid lyric item")
                    item = self._choose([item] if item else [], title, artist, duration)
                except (asyncio.TimeoutError, aiohttp.ClientError, ValueError, TypeError):
                    failed = True
            if not item:
                try:
                    candidates = await self._request(session, "/search", {"q": query or " ".join((artist, title)).strip()})
                    if candidates is not None and not isinstance(candidates, list):
                        raise ValueError("invalid lyric search")
                    query_title, query_artist = clean_metadata(query) if query else (title, artist)
                    item = self._choose(candidates or [], query_title, query_artist, duration, bool(query))
                except (asyncio.TimeoutError, aiohttp.ClientError, ValueError, TypeError):
                    failed = True
            return result(title, artist, item, status="unavailable" if failed else "not_found")

    @staticmethod
    def _retry_delay(value):
        try:
            delay = float(value)
        except (ValueError, TypeError):
            try:
                delay = parsedate_to_datetime(value).timestamp() - time.time()
            except (ValueError, TypeError, OverflowError):
                return None
        return max(0, delay) if math.isfinite(delay) else None

    async def _request(self, session, path, params):
        # Retry-After defers this exact query, never all songs.
        request_key = (path, tuple(sorted(params.items())))
        if self.retry_after.get(request_key, 0) > time.monotonic():
            raise ValueError("request deferred")
        for attempt in range(self.ATTEMPTS):
            retry_delay = None
            async with self.lock:
                delay = self.MIN_INTERVAL - (time.monotonic() - self.last_request)
                if delay > 0:
                    await asyncio.sleep(delay)
                self.last_request = time.monotonic()
            try:
                async with session.get(LRCLIB_ROOT + path, params=params, allow_redirects=False) as response:
                    if response.status == 404:
                        return None
                    if response.status in (408, 429, 500, 502, 503, 504):
                        retry_delay = self._retry_delay(response.headers.get("Retry-After"))
                        if retry_delay is not None:
                            self.retry_after = {k:v for k,v in self.retry_after.items() if v > time.monotonic()}
                            if len(self.retry_after) >= self.CACHE_LIMIT:
                                self.retry_after.pop(next(iter(self.retry_after)))
                            self.retry_after[request_key] = time.monotonic() + retry_delay
                        raise aiohttp.ClientConnectionError("temporary provider failure")
                    if response.status != 200:
                        raise ValueError("provider failure")
                    if response.content_type != "application/json" and not response.content_type.endswith("+json"):
                        raise ValueError("provider content type")
                    chunks, size = [], 0
                    async for chunk in response.content.iter_chunked(16384):
                        size += len(chunk)
                        if size > self.MAX_BODY:
                            raise ValueError("provider body too large")
                        chunks.append(chunk)
                    return json.loads(b"".join(chunks))
            except (asyncio.TimeoutError, aiohttp.ClientError):
                if attempt + 1 == self.ATTEMPTS or retry_delay is not None and retry_delay > 2:
                    raise
                # Never shorten Retry-After or sleep beyond the lookup budget.
                await asyncio.sleep(max(retry_delay or 0, .4 * 2**attempt + random.uniform(0, .2)))
        raise ValueError("provider attempts exhausted")

    @staticmethod
    def _choose(candidates, title, artist, duration, manual=False):
        def norm(value):
            import unicodedata
            return "".join(c for c in unicodedata.normalize("NFKC", str(value or "")).casefold() if c.isalnum())
        choices = []
        for item in candidates[:30]:
            if not isinstance(item, dict) or not (item.get("syncedLyrics") or item.get("plainLyrics") or item.get("instrumental") is True):
                continue
            expected, found = norm(title), norm(item.get("trackName"))
            if not expected or not found:
                continue
            similarity = difflib.SequenceMatcher(None, expected, found).ratio()
            expected_artist, found_artist = norm(artist), norm(item.get("artistName"))
            artist_score = difflib.SequenceMatcher(None, expected_artist, found_artist).ratio() if expected_artist else 0
            if similarity < (.90 if expected_artist else .98) or expected_artist and artist_score < .85:
                continue
            try:
                candidate_duration = float(item.get("duration") or 0)
                if not math.isfinite(candidate_duration) or candidate_duration <= 0:
                    continue
                delta = abs(candidate_duration - duration)
                # MV intros can differ by up to 60s, but an unknown artist is
                # accepted only with an almost-exact title and a 2s duration.
                if duration > 0 and delta > (60 if expected_artist else 2):
                    continue
                if not expected_artist and duration <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            score = similarity * .60 + artist_score * .30 + max(0, 1-delta/60) * .10
            choices.append((score, item))
        choices.sort(key=lambda pair: pair[0], reverse=True)
        if len(choices) > 1 and choices[0][0]-choices[1][0] < .025:
            first, second = choices[0][1], choices[1][1]
            same_recording = (norm(first.get("trackName")), norm(first.get("artistName"))) == (
                    norm(second.get("trackName")), norm(second.get("artistName")))
            if not same_recording or abs(float(first["duration"])-float(second["duration"])) > 2:
                return None
        return choices[0][1] if choices else None
