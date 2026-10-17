"""Per-guild empty-queue policy and bounded YouTube radio, independent of HTTP."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import re
import unicodedata
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from aiohttp import web
from . import write_path
from .downloader import YtdlpResponseDict
from .web_dashboard_stats import atomic_write, normalized_url

log = logging.getLogger(__name__)
DEFAULT = {"empty_queue": "autoplaylist", "radio_min_seconds": 0, "radio_max_seconds": 0}


def validate_settings(data):
    if not isinstance(data, dict) or set(data) != set(DEFAULT):
        raise ValueError()
    if data["empty_queue"] not in ("autoplaylist", "radio", "off"):
        raise ValueError()
    low, high = data["radio_min_seconds"], data["radio_max_seconds"]
    if any(type(n) is not int or not 0 <= n <= 31536000 for n in (low, high)):
        raise ValueError()
    if high and low > high:
        raise ValueError()
    return dict(data)


def is_radio(entry):
    info = getattr(entry, "info", None) or {}
    return getattr(entry, "_dashboard_radio_source", False) or info.get("__web_dashboard_source") == "radio"


class EmptyQueueStore:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = asyncio.Lock()

    def path(self, guild):
        gid = getattr(guild, "id", guild)
        if type(gid) is not int or gid <= 0:
            raise ValueError()
        return self.root/(str(gid)+".json")

    def read(self, guild):
        try:
            with self.path(guild).open("rb") as stream:
                raw = stream.read(4097)
            if len(raw) > 4096:
                raise ValueError()
            return validate_settings(json.loads(raw))
        except FileNotFoundError:
            return dict(DEFAULT)
        except (ValueError, TypeError, OSError):
            log.warning("Empty-queue settings unavailable; using legacy autoplay")
            return dict(DEFAULT)

    async def get(self, guild):
        async with self.lock:
            return await asyncio.to_thread(self.read, guild)

    async def put(self, guild, data):
        value = validate_settings(data)
        async with self.lock:
            await asyncio.to_thread(atomic_write, self.path(guild), value)
        return value


def normalized_title(value):
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    value = re.sub(r"[\(\[【「『][^\)\]】」』]*[\)\]】」』]", " ", value)
    value = re.sub(r"\b(?:official|music|video|mv|m/v|lyrics?|audio|live|cover|hd|hq|4k|remastered)\b", " ", value)
    value = re.sub(r"(?:官方|完整版|字幕版|現場版|現場演唱|翻唱版|歌詞版|動態歌詞)", " ", value)
    parts = re.split(r"\s+[-–—]\s+", value, maxsplit=1)
    if len(parts) == 2:
        value = parts[1]
    return "".join(c for c in value if c.isalnum())[:300]


def artist_keys(item):
    def norm(value):
        value = unicodedata.normalize("NFKC", str(value or "")).casefold()
        value = re.sub(r"\b(?:official|topic|vevo|channel)\b", "", value)
        return "".join(c for c in value if c.isalnum())[:200]
    artist = item.get("artist") or item.get("creator")
    if not artist:
        parts = re.split(r"\s+[-–—]\s+", str(item.get("title", "")), maxsplit=1)
        artist = parts[0] if len(parts) == 2 else ""
    channel = item.get("channel_id") or item.get("channel") or item.get("uploader_id") or item.get("uploader")
    return {kind+":"+key for kind, value in (("artist", artist), ("channel", channel)) if (key := norm(value))}


class RadioService:
    TIMEOUT = 20

    def __init__(self, bot, root=None, *, rng=None):
        self.bot = bot
        self.store = EmptyQueueStore(root or write_path("data/web_dashboard/settings"))
        self.state_root = self.store.root.parent / "radio"
        self.locks = defaultdict(asyncio.Lock)
        self.state_locks = defaultdict(asyncio.Lock)
        self.recent = defaultdict(lambda: deque(maxlen=50))
        self.seeds = defaultdict(lambda: deque(maxlen=5))
        self.cursor = defaultdict(int)
        self.loaded = set()
        self.rng = rng or random.SystemRandom()
        self.failures = defaultdict(int)
        self.suspended = defaultdict(float)
        self.marker = object()
        self.popularity = None

    def state_path(self, guild):
        return self.state_root / self.store.path(guild).name

    def read_state(self, guild):
        try:
            path = self.state_path(guild)
            with path.open("rb") as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError()
            data = json.loads(raw)
            if (not isinstance(data, dict) or data.get("version") != 1
                    or type(data.get("next")) is not int or not 0 <= data["next"] < 10**15):
                raise ValueError()
            for name, limit in (("seeds", 5), ("recent", 50)):
                rows = data[name]
                if not isinstance(rows, list) or len(rows) > limit:
                    raise ValueError()
                for row in rows:
                    if (not isinstance(row, dict) or set(row) != {"url", "title"}
                            or not row["url"] or normalized_url(row["url"]) != row["url"]
                            or not isinstance(row["title"], str) or len(row["title"]) > 300):
                        raise ValueError()
            return data
        except (OSError, ValueError, TypeError, KeyError):
            return {"version": 1, "seeds": [], "recent": [], "next": 0}

    async def load_locked(self, guild):
        if guild.id not in self.loaded:
            data = await asyncio.to_thread(self.read_state, guild)
            self.seeds[guild.id].extend(data["seeds"])
            self.recent[guild.id].extend(data["recent"])
            self.cursor[guild.id] = data["next"]
            self.loaded.add(guild.id)

    async def save_locked(self, guild):
        data = {"version": 1, "seeds": list(self.seeds[guild.id]),
                "recent": list(self.recent[guild.id]), "next": self.cursor[guild.id]}
        try:
            await asyncio.to_thread(atomic_write, self.state_path(guild), data)
        except OSError:
            log.warning("Radio state persistence unavailable")

    async def remember(self, guild, entry):
        if entry is None:
            return
        async with self.state_locks[guild.id]:
            await self.load_locked(guild)
            if getattr(entry, "_radio_history_marker", None) == (self.marker, guild.id):
                return
            entry._radio_history_marker = (self.marker, guild.id)
            url = normalized_url(getattr(entry, "url", ""))
            if not url:
                return
            row = {"url": url, "title": str(getattr(entry, "title", ""))[:300]}
            self.recent[guild.id].append(row)
            meta = getattr(entry, "meta", None) or {}
            author = (getattr(entry, "author", None) or getattr(entry, "member", None)
                      or meta.get("author") or meta.get("member"))
            if (url.startswith("https://www.youtube.com/watch?v=") and author is not None
                    and not getattr(author, "bot", False) and not is_radio(entry)
                    and not getattr(entry, "from_auto_playlist", False)):
                pool = self.seeds[guild.id]
                # Replayed human requests refresh recency without duplicate seeds.
                self.seeds[guild.id] = deque((x for x in pool if x["url"] != url), maxlen=5)
                self.seeds[guild.id].append(row)
            await self.save_locked(guild)

    async def seed_rows(self, guild):
        async with self.state_locks[guild.id]:
            await self.load_locked(guild)
            return list(self.seeds[guild.id])

    async def next_seed(self, guild):
        rows = await self.seed_rows(guild)
        if not rows:
            from .web_dashboard_stats import PopularityStore
            dashboard = getattr(self.bot, "_web_dashboard", None)
            store = getattr(dashboard, "popularity_store", None)
            if store is None:
                if self.popularity is None:
                    self.popularity = PopularityStore(self.store.root.parent / "stats", flush_interval=0)
                store = self.popularity
            rows = [row for row in await store.top(guild, "all")
                    if row["url"].startswith("https://www.youtube.com/watch?v=")][:5]
        if not rows:
            return None
        async with self.state_locks[guild.id]:
            row = rows[self.cursor[guild.id] % len(rows)]
            self.cursor[guild.id] = (self.cursor[guild.id] + 1) % (10**14)
            await self.save_locked(guild)
            return row["url"]

    def failed(self, guild):
        self.failures[guild.id] += 1
        if self.failures[guild.id] >= 3:
            self.suspended[guild.id] = time.monotonic()+600
        log.warning("Radio unavailable; falling back to legacy autoplay")

    def alive(self, player):
        return (not getattr(self.bot, "logout_called", False)
                and not getattr(player, "is_dead", False)
                and player.voice_client.is_connected())

    async def fill(self, player, settings):
        """Return True if handled; False requests original autoplay fallback."""
        guild = player.voice_client.guild
        if settings["empty_queue"] == "off":
            return True
        if settings["empty_queue"] != "radio":
            return False
        if time.monotonic() < self.suspended[guild.id]:
            log.info("Radio cooling down; falling back to legacy autoplay")
            return False
        if self.suspended[guild.id]:
            self.failures[guild.id] = 0
            self.suspended[guild.id] = 0
        seed = await self.next_seed(guild)
        if not seed:
            self.failed(guild)
            return False
        queued = 0
        try:
            video = parse_qs(urlsplit(seed).query)["v"][0]
            mix = seed+"&list=RD"+video
            info = await asyncio.wait_for(self.bot.downloader.extract_public_playlist(mix), self.TIMEOUT)
            # User requests or policy changes while extraction was in flight
            # take precedence over this automatic batch.
            current = await self.store.get(guild)
            if (current["empty_queue"] != "radio" or player.current_entry
                    or player.playlist.entries or not self.alive(player)):
                return True
            seen = {row["url"] for row in self.recent[guild.id]}
            titles = {normalized_title(row["title"]) for row in self.recent[guild.id]} - {""}
            artists = set()
            candidates, candidate_urls = [], set()
            for rank, item in enumerate(info.get_entries_objects()[:25]):
                candidate_url = normalized_url(item.get("webpage_url") or item.get("url") or
                    ("https://www.youtube.com/watch?v="+str(item.get("id", ""))))
                if candidate_url and candidate_url not in candidate_urls:
                    candidates.append((rank, item))
                    candidate_urls.add(candidate_url)
            # Weighted sampling without replacement retains rank preference while
            # allowing every one of the first 25 candidates to be selected.
            while candidates:
                chosen = self.rng.choices(range(len(candidates)), weights=[1/(rank+1) for rank, _ in candidates], k=1)[0]
                _, item = candidates.pop(chosen)
                url = normalized_url(item.get("webpage_url") or item.get("url") or "")
                # Flat entries sometimes expose only the video ID.
                if not url and isinstance(item.get("id"), str):
                    url = normalized_url("https://www.youtube.com/watch?v="+item["id"])
                title_key = normalized_title(item.title)
                keys = artist_keys(item)
                duration = item.get("duration")
                if (not url.startswith("https://www.youtube.com/watch?v=") or url in seen or title_key and title_key in titles or keys & artists
                        or type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0
                        or duration < current["radio_min_seconds"]
                        or current["radio_max_seconds"] and duration > current["radio_max_seconds"]):
                    continue
                try:
                    self.bot._do_song_blocklist_check(url)
                    self.bot._do_song_blocklist_check(item.title)
                except Exception:
                    continue
                # Recheck immediately before each side effect, without accepting
                # provider URLs as an arbitrary fetch/redirect destination.
                current = await self.store.get(guild)
                if current["empty_queue"] != "radio" or not self.alive(player):
                    return True
                if queued == 0 and (player.current_entry or player.playlist.entries):
                    return True
                if duration < current["radio_min_seconds"] or current["radio_max_seconds"] and duration > current["radio_max_seconds"]:
                    continue
                data = YtdlpResponseDict({"_type": "url", "id": parse_qs(urlsplit(url).query)["v"][0],
                    "url": url, "webpage_url": url, "__input_subject": url,
                    "title": item.title, "duration": duration, "extractor": "youtube",
                    "__web_dashboard_source": "radio"})
                entry, _ = await player.playlist.add_entry_from_info(data, author=None, channel=None, head=False)
                entry._dashboard_radio_source = True
                seen.add(url)
                if title_key: titles.add(title_key)
                artists.update(keys)
                queued += 1
                if queued == 3:
                    break
        except Exception:
            # No provider exception or URL belongs in this warning.
            if not queued:
                self.failed(guild)
                return False
            log.warning("Radio batch stopped after partial success")
        if queued:
            self.failures[guild.id] = 0
            self.suspended[guild.id] = 0
            return True
        self.failed(guild)
        return False


def radio_for(bot):
    service = getattr(bot, "_dashboard_radio", None)
    if service is None:
        service = bot._dashboard_radio = RadioService(bot)
    return service


class DashboardRadio:
    def init_radio(self):
        self.radio_service = radio_for(self.bot)
        path = "/api/guilds/{guild_id}/admin/empty-queue"
        self.app.router.add_get(path, self.admin_empty_queue)
        self.app.router.add_post(path, self.admin_empty_queue)

    async def admin_empty_queue(self, request):
        from .web_dashboard import APIError
        guild, _ = self.require_owner(request)
        if request.method == "GET":
            settings = await self.radio_service.store.get(guild)
        else:
            data = await self.payload(request)
            try:
                settings = validate_settings(data)
            except (ValueError, TypeError):
                raise APIError(400, "佇列空時設定不正確；最低與最高秒數須為非負整數，最高 0 表示不限。") from None
            async with self.admin_lock:
                if self.discord_auth:
                    self.authenticate(request)
                guild, _ = self.require_owner(request)
                settings = await self.radio_service.store.put(guild, settings)
        if self.discord_auth:
            self.authenticate(request)
        self.require_owner(request)
        seeds = await self.radio_service.seed_rows(guild)
        return web.json_response({**settings,
            "seed_titles": [row["title"] for row in seeds], "seed_count": len(seeds),
            "radio_failures": self.radio_service.failures[guild.id],
            "radio_suspended_seconds": max(0, math.ceil(self.radio_service.suspended[guild.id]-time.monotonic()))})
