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
import unicodedata
from collections import OrderedDict
import aiohttp

USER_AGENT = "MusicBot-WebDashboard/12 (+https://github.com/Just-Some-Bots/MusicBot)"
LRCLIB_ROOT = "https://lrclib.net/api"
_NOISE = re.compile(r"(?:official|music\s*video|\bmv\b|\bm/v\b|lyrics?|audio|\bhd\b|\bhq\b|\b4k\b|完整版|官方|字幕)", re.I)
_COVER = re.compile(r"(?<![a-z])cover(?:ed)?(?:\s+by)?(?![a-z])|翻唱", re.I)
_VERSION = re.compile(r"remix|remaster|live|acoustic|instrumental|sped\s*up|slowed", re.I)
_BRACKETS = re.compile(r"[《〈『「【]([^》〉』」】]+)[》〉』」】]")


def _norm(value):
    return "".join(c for c in unicodedata.normalize("NFKC", str(value or "")).casefold() if c.isalnum())


def _text(value, limit):
    return re.sub(r"\s+", " ", "".join(c for c in str(value or "")[:limit]
                  if c in "|｜" or not unicodedata.category(c).startswith(("C", "S")))).strip()


def _artists(value):
    names = re.split(r"\s*(?:,|，|、|;|；|\s+&\s+|\bfeat\.?\s+|\bft\.?\s+|\bfeaturing\s+)\s*", value, flags=re.I)
    out = []
    for name in names:
        if re.search(r"records?|唱片|翻譯|translation", name, re.I):
            continue
        name = re.sub(r"(?:youtube|官方頻道|官方|(?<![\w])official(?![\w])|channel|頻道|\s*-?\s*topic\s*$|vevo)", "", name, flags=re.I).strip(" -|｜")
        name = re.sub(r"^[\W_]+", "", name)
        if _norm(name) and _norm(name) not in [_norm(n) for n in out]:
            out.append(name)
    return out[:3]


def _titles(value):
    # A CJK title followed by its English translation is a title alias,
    # not a longer song name. Keep both for conservative exact matching.
    value = value.strip()
    if _VERSION.search(value) or re.search(r"[（(\[]", value):
        return [value]
    parts = re.split(r"(?<=[\u3040-\u30ff\u3400-\u9fff。！？])\s+(?=[A-Za-z])", value, maxsplit=1)
    return list(dict.fromkeys(parts + [value]))[:3]


def metadata(title, artist=""):
    title, artist = _text(title, 300), _text(artist, 160)
    cover = bool(_COVER.search(title))
    title = _BRACKETS.sub(lambda m: "" if not _NOISE.sub("", m[1]).strip(" -/") else m[0], title)
    names = _artists(artist)
    # Drop only presentation brackets; version brackets remain meaningful.
    title = re.sub(r"[\(（\[]([^\)）\]]*)[\)）\]]",
                   lambda m: "" if (_NOISE.search(m[1]) or _COVER.search(m[1])) and not _VERSION.search(m[1]) else m[0], title)
    title = re.sub(r"\s*\b(?:official\s+(?:(?:music\s+)?video|audio|mv)|music\s+video|mv|m/v|lyric\s+video|cover)\s*$", "", title, flags=re.I)
    title = re.sub(r"\s*[|｜]\s*.*(?:official|\bMV\b|lyrics?|audio).*$", "", title, flags=re.I)
    title = re.sub(r"\s*[\(（]?\s*\b(?:feat|ft|featuring)\b\.?\s+.*$", "", title, flags=re.I)
    inferred = ""
    bracket = _BRACKETS.search(title)
    if bracket and not _NOISE.fullmatch(bracket[1].strip()):
        prefix = re.sub(r"\b(?:MV|M/V)\b", "", title[:bracket.start()], flags=re.I).strip(" -－–—|｜:：")
        if prefix:
            inferred = prefix
        title = bracket[1].strip()
    else:
        # Separators need whitespace for ASCII '-' and '/', so meaningful
        # hyphens and titles such as AC/DC are preserved.
        parts = re.split(r"\s+[\-/–—]\s+|\s*[－｜|]\s*", title, maxsplit=1)
        if len(parts) == 2:
            left, right = parts
            if cover and "/" in title:
                title, inferred = left, right
            elif not names or any(_norm(left) == _norm(n) for n in names):
                inferred, title = left, right
    if inferred:
        inferred_names = _artists(inferred)
        # Explicit title artist takes priority over an unrelated uploader.
        if inferred_names:
            names = inferred_names + [n for n in names if _norm(n) not in [_norm(x) for x in inferred_names]]
    elif names:
        for name in names:
            if title.casefold().startswith(name.casefold()) and len(title) > len(name):
                rest = title[len(name):]
                if rest[0].isspace() or rest[0] in "-－–—:：":
                    title = rest.strip(" -－–—:：")
                    break
    title = re.sub(r"^[\W_]+", "", title).strip(" -－–—|｜")
    titles = _titles(title)
    return {"title": titles[0][:200], "artist": names[0][:160] if names else "",
            "artists": names[:3], "titles": titles, "cover": cover}


def clean_metadata(title, artist=""):
    value = metadata(title, artist)
    return value["title"], value["artist"]


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
        meta = metadata(title, artist)
        title, artist = meta["title"], meta["artist"]
        try:
            duration = float(duration or 0)
        except (TypeError, ValueError):
            duration = 0
        if not math.isfinite(duration):
            duration = 0
        key = (title.casefold(), tuple(meta["artists"]), meta["cover"], round(duration), query.casefold())
        cached = self.cache.get(key)
        if cached and cached[0] > time.monotonic():
            self.cache.move_to_end(key)
            return cached[1]
        if not title and not query:
            return result(title, artist)
        task = self.pending.get(key)
        if task is None:
            task = asyncio.create_task(self._lookup_bounded(key, title, artist, duration, query, meta))
            self.pending[key] = task
            task.add_done_callback(lambda done: self.pending.pop(key, None))
        return await asyncio.shield(task)

    def _cache(self, key, value, ttl):
        self.cache[key] = (time.monotonic() + ttl, value)
        self.cache.move_to_end(key)
        while len(self.cache) > self.CACHE_LIMIT:
            self.cache.popitem(last=False)
        return value

    async def _lookup_bounded(self, key, title, artist, duration, query, meta):
        try:
            value = await asyncio.wait_for(self._lookup(title, artist, duration, query, meta), self.TIMEOUT)
        except (asyncio.TimeoutError, aiohttp.ClientError, ValueError, TypeError, KeyError):
            value = result(title, artist, status="unavailable")
        ttl = self.FAILURE_TTL if value["status"] == "unavailable" else self.NOT_FOUND_TTL if value["status"] == "not_found" else self.CACHE_TTL
        return self._cache(key, value, ttl)

    async def _lookup(self, title, artist, duration, query, meta):
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            trust_env=False) as session:
            failed, pool = False, []
            async def collect(path, params):
                nonlocal failed
                try:
                    value = await self._request(session, path, params)
                    if value is None:
                        return []
                    if path == "/get":
                        if not isinstance(value, dict):
                            raise ValueError("invalid lyric item")
                        return [value]
                    if not isinstance(value, list):
                        raise ValueError("invalid lyric search")
                    return value
                except (asyncio.TimeoutError, aiohttp.ClientError, ValueError, TypeError):
                    failed = True
                    return []

            def choose():
                for variant in meta["titles"]:
                    for name in meta["artists"] or [""]:
                        found = self._choose(pool, variant, name, duration)
                        if found:
                            return found, "matched"
                if meta["cover"]:
                    found = self._choose(pool, title, "", duration)
                    if found:
                        return found, "cover_original"
                return None, ""

            if query:
                title, artist = clean_metadata(query)
                pool = await collect("/search", {"q": query})
                item = self._choose(pool, title, artist, duration, True)
                return result(title, artist, item, status="unavailable" if failed else "not_found")
            if artist:
                params = {"track_name": title, "artist_name": artist}
                if 1 <= duration <= 3600:
                    params["duration"] = str(round(duration))
                responses = await asyncio.gather(
                    collect("/get", params),
                    collect("/search", {"track_name": title, "artist_name": artist}))
                pool = [item for response in responses for item in response]
            else:
                pool = await collect("/search", {"track_name": title})
            item, match = choose()
            if not item and artist:
                responses = await asyncio.gather(
                    collect("/search", {"track_name": title}),
                    collect("/search", {"q": " ".join((artist, title))}))
                pool.extend(item for response in responses for item in response)
                item, match = choose()
            # Secondary credited artists are candidates, not an artistless bypass.
            if not item and len(meta["artists"]) > 1:
                pool.extend(await collect("/search", {"track_name": title, "artist_name": meta["artists"][1]}))
                item, match = choose()
            if not item and len(meta["titles"]) > 1 and not re.search(r"[…]|\\.\\.\\.", meta["titles"][1]):
                params = {"track_name": meta["titles"][1]}
                if artist:
                    params["artist_name"] = artist
                pool.extend(await collect("/search", params))
                item, match = choose()
            value = result(title, artist, item, status="unavailable" if failed else "not_found")
            if match == "cover_original":
                value["match"] = match
            return value

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
        def aliases(value):
            parts = [value] + re.findall(r"[A-Za-z][A-Za-z .'-]*|[\u3040-\u30ff\u3400-\u9fff]+", value)
            return {_norm(x) for x in parts if len(_norm(x)) >= 3} or {_norm(value)}
        expected_titles = {_norm(x) for x in _titles(title)}
        expected_artist = _norm(artist)
        choices, seen = [], set()
        for item in candidates[:200]:
            if not isinstance(item, dict) or not (item.get("syncedLyrics") or item.get("plainLyrics") or item.get("instrumental") is True):
                continue
            # Public provider records can contain obvious placeholder text even
            # when identity fields are correct; never show that as song lyrics.
            samples = [re.sub(r"\[[^\]]*\]", "", line).strip()
                       for line in str(item.get("syncedLyrics") or item.get("plainLyrics") or "").splitlines()]
            text = " ".join(line for line in samples if line).strip()
            if re.fullmatch(r"(?:probe|test(?:ing)?(?: lyrics?)?|placeholder|lyrics? (?:not found|unavailable))", text, re.I):
                continue
            found_titles = {_norm(x) for x in _titles(str(item.get("trackName") or ""))}
            if not expected_titles.intersection(found_titles) or not _norm(title):
                continue
            # Versions such as remix/live must never silently become the studio recording.
            if set(x.casefold() for x in _VERSION.findall(title)) != set(x.casefold() for x in _VERSION.findall(str(item.get("trackName") or ""))):
                continue
            artist_score = 0
            if expected_artist:
                left, right = aliases(artist), aliases(str(item.get("artistName") or ""))
                artist_score = 1 if left.intersection(right) else 0
                if artist_score < .90:
                    continue
            try:
                candidate_duration = float(item.get("duration") or 0)
                if not math.isfinite(candidate_duration) or candidate_duration <= 0:
                    continue
                delta = abs(candidate_duration - duration)
                # Preserve MV intro allowance only with a known matching artist.
                if duration > 0 and delta > (60 if expected_artist else 2):
                    continue
                if not expected_artist and duration <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            identity = (_norm(item.get("trackName")), _norm(item.get("artistName")), candidate_duration)
            if identity in seen:
                continue
            seen.add(identity)
            score = .60 + artist_score * .30 + max(0, 1-delta/60) * .10
            choices.append((score, item))
        choices.sort(key=lambda pair: pair[0], reverse=True)
        if len(choices) > 1 and choices[0][0]-choices[1][0] < .025:
            first, second = choices[0][1], choices[1][1]
            same_recording = (_norm(first.get("trackName")), _norm(first.get("artistName"))) == (
                _norm(second.get("trackName")), _norm(second.get("artistName")))
            if not same_recording or abs(float(first["duration"])-float(second["duration"])) > 2:
                return None
        return choices[0][1] if choices else None
