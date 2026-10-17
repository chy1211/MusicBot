"""Public playlist imports using existing providers, bounded previews and private storage."""
from __future__ import annotations

import asyncio
import copy
import math
import re
import secrets
import time
from collections import Counter
from urllib.parse import parse_qs, urlsplit

from aiohttp import web


def fail(status, message):
    from .web_dashboard import APIError
    raise APIError(status, message)


def source_url(value):
    """Accept only known public playlist URLs; canonicalize before extraction."""
    if not isinstance(value, str) or len(value) > 2000 or any(c.isspace() or ord(c) < 32 for c in value):
        fail(400, "請貼上有效的公開歌單或專輯連結。")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (parsed.scheme not in ("http", "https") or parsed.username or parsed.password
                or parsed.port not in (None, 80, 443)):
            raise ValueError()
    except ValueError:
        fail(400, "來源只接受 HTTP／HTTPS 公開歌單連結。")
    if host == "open.spotify.com":
        parts = parsed.path.strip("/").split("/")
        if parts and parts[0].startswith("intl-"):
            parts = parts[1:]
        if len(parts) != 2 or parts[0] not in ("album", "playlist") or not re.fullmatch(r"[A-Za-z0-9]{1,100}", parts[1]):
            fail(400, "Spotify 請提供公開歌單或專輯連結。")
        return "https://open.spotify.com/" + "/".join(parts), "spotify"
    if host in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"):
        ids = parse_qs(parsed.query).get("list", [])
        if len(ids) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", ids[0]):
            fail(400, "YouTube／YouTube Music 請提供包含歌單的連結。")
        if ids[0] in ("WL", "LL", "LM"):
            fail(400, "私人收藏、稍後觀看與喜歡的歌不支援公開匯入。")
        # Canonical YouTube playlist prevents redirects/compound video expansion.
        return "https://www.youtube.com/playlist?list=" + ids[0], "youtube"
    fail(400, "只支援 Spotify、YouTube 與 YouTube Music 公開歌單。")


# Observed public embed/API image hosts; never allow arbitrary Spotify subdomains.
SPOTIFY_IMAGE_HOSTS = ("i.scdn.co", "mosaic.scdn.co")

def spotify_image(value):
    if isinstance(value, dict):
        for key in ("url", "sources", "images", "coverArt", "image"):
            found = spotify_image(value.get(key))
            if found: return found
    elif isinstance(value, list):
        for item in value:
            found = spotify_image(item)
            if found: return found
    elif isinstance(value, str):
        if re.fullmatch(r"spotify:image:[A-Za-z0-9]+", value):
            value = "https://i.scdn.co/image/" + value.rsplit(":", 1)[-1]
        elif value.startswith("//"): value = "https:" + value
        elif re.fullmatch(r"/image/[A-Za-z0-9]+", value):
            value = "https://i.scdn.co" + value
        try:
            p = urlsplit(value)
            if (p.scheme == "https" and p.hostname in SPOTIFY_IMAGE_HOSTS
                    and not p.username and not p.password and p.port in (None,443)
                    and not any(c.isspace() or ord(c)<32 for c in value)):
                return value
        except ValueError: pass
    return ""

def imported_track(row, kind):
    """Discard provider-only metadata; store only canonical playable sources."""
    if not isinstance(row, dict):
        return None
    if kind == "spotify":
        if row.get("is_local") or row.get("type", "track") != "track":
            return None
        ident = row.get("id")
        if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9]{1,100}", ident):
            return None
        artists = ", ".join(str(a.get("name", "")) for a in row.get("artists", []) if isinstance(a, dict) and a.get("name"))
        title = (artists + " - " if artists else "") + str(row.get("name") or "未命名歌曲")
        url = "https://open.spotify.com/track/" + ident
        milliseconds = row.get("duration_ms")
        duration = milliseconds / 1000 if type(milliseconds) in (int, float) else None
    else:
        ident = row.get("id")
        url = row.get("webpage_url") or row.get("url", "")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            parsed = urlsplit(url)
            if parsed.hostname not in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"):
                return None
            ident = (parsed.path.strip("/").split("/")[0] if parsed.hostname == "youtu.be"
                     else parse_qs(parsed.query).get("v", [ident])[0])
        elif isinstance(url, str) and re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
            ident = url
        if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", ident):
            return None
        title = str(row.get("title") or "未命名歌曲")
        if title.lower() in ("[private video]", "[deleted video]"):
            return None
        url = "https://www.youtube.com/watch?v=" + ident
        duration = row.get("duration")
    if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 <= duration <= 31536000:
        duration = None
    track = {"title": title.strip()[:300] or "未命名歌曲", "url": url, "duration": duration}
    cover = spotify_image(row.get("album", {}).get("images")) or spotify_image(row.get("images")) if kind == "spotify" else ""
    if cover: track["thumbnail"] = cover
    return track


def source_diff(old, new):
    before, after = Counter(t["url"] for t in old), Counter(t["url"] for t in new)
    return {"added": sum((after - before).values()), "removed": sum((before - after).values())}


# Public embed fallback contains no authentication and never follows redirects.
SPOTIFY_EMBED_LIMIT = 3 * 1024 * 1024
SPOTIFY_UNREADABLE = "這個 Spotify 歌單目前讀不到，可能是私人歌單"

def parse_spotify_embed(content, ident):
    import json
    from html.parser import HTMLParser
    if len(content) > SPOTIFY_EMBED_LIMIT:
        raise ValueError(SPOTIFY_UNREADABLE)
    class Scripts(HTMLParser):
        def __init__(self):
            super().__init__(); self.active = False; self.parts = []
        def handle_starttag(self, tag, attrs):
            self.active = tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__"
        def handle_endtag(self, tag):
            if tag == "script": self.active = False
        def handle_data(self, data):
            if self.active: self.parts.append(data)
    parser = Scripts()
    parser.feed(content.decode("utf-8") if isinstance(content, bytes) else content)
    data = json.loads("".join(parser.parts))
    entity = data["props"]["pageProps"]["state"]["data"]["entity"]
    rows = entity.get("trackList")
    if not isinstance(rows, list):
        raise ValueError(SPOTIFY_UNREADABLE)
    cover = spotify_image(entity.get("coverArt")) or spotify_image(entity.get("visualIdentity", {}).get("image"))
    tracks, seen = [], set()
    for row in rows[:200]:
        if not isinstance(row, dict): continue
        uri = row.get("uri") or row.get("trackUri") or ""
        match = re.fullmatch(r"spotify:track:([A-Za-z0-9]{1,100})", uri)
        title = row.get("title")
        duration = row.get("duration")
        if isinstance(duration, dict): duration = duration.get("totalMilliseconds")
        if (not match or not isinstance(title, str) or not title.strip()
                or type(duration) not in (int, float) or not math.isfinite(duration)
                or not 0 < duration <= 31536000000):
            continue
        tid = match[1]
        if tid in seen: continue
        seen.add(tid)
        subtitle = row.get("subtitle")
        tracks.append({"track": {"id": tid, "type": "track", "name": title[:300],
                       "artists": [{"name": subtitle[:300]}] if isinstance(subtitle, str) else [],
                       "duration_ms": duration,
                       "album": {"images": [{"url": spotify_image(row.get("coverArt")) or spotify_image(row.get("image")) or cover}]},
                       "external_urls": {"spotify": "https://open.spotify.com/track/" + tid}}})
    if not tracks:
        raise ValueError(SPOTIFY_UNREADABLE)
    # Embed is a partial view. Never claim it is the entire source.
    total = entity.get("totalTracks")
    total = max(len(tracks), total if type(total) is int else 0)
    return {"id": ident, "type": "playlist", "name": str(entity.get("name") or entity.get("title") or "Spotify 歌單")[:300],
            "external_urls": {"spotify": "https://open.spotify.com/playlist/" + ident},
            "tracks": {"items": tracks, "next": None, "total": total},
            "images": [{"url": cover}] if cover else [], "_embed_partial": True}

async def fetch_spotify_embed(session, ident):
    import aiohttp
    if not re.fullmatch(r"[A-Za-z0-9]{1,100}", ident):
        raise ValueError(SPOTIFY_UNREADABLE)
    url = "https://open.spotify.com/embed/playlist/" + ident
    async with session.get(url, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=10)) as response:
        actual = urlsplit(str(response.url))
        if (response.status != 200 or actual.scheme != "https" or actual.hostname != "open.spotify.com"
                or actual.username or actual.password or actual.port not in (None, 443)):
            raise ValueError(SPOTIFY_UNREADABLE)
        if response.content_length and response.content_length > SPOTIFY_EMBED_LIMIT:
            raise ValueError(SPOTIFY_UNREADABLE)
        chunks, size = [], 0
        async for chunk in response.content.iter_chunked(65536):
            size += len(chunk)
            if size > SPOTIFY_EMBED_LIMIT: raise ValueError(SPOTIFY_UNREADABLE)
            chunks.append(chunk)
    return parse_spotify_embed(b"".join(chunks), ident)

async def spotify_playlist(spotify, ident, api=None):
    """API first; the existing authenticated client remains the only API client."""
    original = None
    try:
        value = await (api() if api else spotify.get_playlist(ident))
        if isinstance(value.get("tracks"), dict) and isinstance(value["tracks"].get("items"), list):
            return value
    except Exception as exc:
        original = exc
    try:
        return await fetch_spotify_embed(spotify.aiosession, ident)
    except Exception:
        if original is not None: raise original
        raise ValueError(SPOTIFY_UNREADABLE) from None

class DashboardImports:
    def init_imports(self):
        self.import_previews = {}
        self.import_locks = {}
        self.app.router.add_get("/api/library/sources", self.library_sources)
        self.app.router.add_post("/api/guilds/{guild_id}/library/import/preview", self.library_import_preview)
        self.app.router.add_post("/api/library/import", self.library_import_confirm)
        self.app.router.add_post("/api/guilds/{guild_id}/library/{playlist_id}/sync/preview", self.library_import_preview)
        self.app.router.add_post("/api/library/{playlist_id}/sync", self.library_import_confirm)

    def spotify_import_enabled(self):
        return bool(getattr(self.bot.config, "spotify_enabled", False) and getattr(self.bot, "spotify", None))

    def import_authorize(self, request, uid):
        if self.discord_auth:
            self.authenticate(request)
        if self.library_identity(request) != uid:
            fail(403, "登入身分已變更，請重新登入。")

    async def library_sources(self, request):
        self.library_identity(request)
        return web.json_response({"spotify": self.spotify_import_enabled(), "youtube": True,
                                  "spotify_message": "" if self.spotify_import_enabled() else "目前無法讀取 Spotify 歌單"})

    async def import_source(self, url, kind):
        """Resolve public content only; no login, download or alternative credentials."""
        tracks = []
        count_is_minimum = False
        if kind == "spotify":
            if not self.spotify_import_enabled():
                fail(503, "目前無法讀取 Spotify 歌單")
            spotify = self.bot.spotify
            category, ident = urlsplit(url).path.strip("/").split("/")
            # Existing Spotify API/session owns credentials and token handling.
            try:
                value = await (spotify.get_album(ident) if category == "album" else spotify_playlist(spotify, ident))
            except Exception:
                fail(400, SPOTIFY_UNREADABLE if category == "playlist" else "這個 Spotify 專輯目前讀不到，請稍後再試。")
            count_is_minimum = bool(value.get("_embed_partial"))
            container = value.get("tracks", {})
            rows = list(container.get("items") or [])
            total = container.get("total", len(rows))
            next_url = container.get("next")
            # Fetch only pages needed for the bounded first 200 source entries.
            while len(rows) < 200 and next_url:
                if not isinstance(next_url, str) or not next_url.startswith(spotify.API_BASE):
                    fail(502, "來源回傳無效的歌單內容，請稍後再試。")
                page = await spotify.make_api_req(spotify.api_safe_url(next_url))
                more = page.get("items") or []
                if not more:
                    break
                rows.extend(more)
                next_url = page.get("next")
            title = value.get("name") or "Spotify 歌單"
            for item in rows[:200]:
                track = imported_track(item.get("track") if category == "playlist" and isinstance(item, dict) else item, kind)
                if track:
                    if kind == "spotify" and not track.get("thumbnail"):
                        cover = spotify_image(value.get("images"))
                        if cover: track["thumbnail"] = cover
                    tracks.append(track)
            count = max(len(rows), total if type(total) is int else 0)
            if type(container.get("total")) is not int and next_url:
                count = max(count, len(rows) + 1)
                count_is_minimum = True
        else:
            info = await self.bot.downloader.extract_info(url, download=False, process=False, public_only=True)
            value = getattr(info, "data", info)
            if not isinstance(value, dict) or "entries" not in value:
                fail(400, "來源不是可讀取的公開歌單。")
            if value.get("availability") in ("private", "needs_auth", "premium_only", "subscriber_only"):
                fail(403, "只支援不需登入的公開歌單。")
            rows = list(value.get("entries") or [])
            title = value.get("title") or "YouTube 歌單"
            total = value.get("playlist_count") or value.get("n_entries")
            count = max(len(rows), total if type(total) is int else 0)
            count_is_minimum = type(total) is not int and len(rows) > 200
            for item in rows[:200]:
                track = imported_track(getattr(item, "data", item), kind)
                if track:
                    tracks.append(track)
        if not tracks:
            fail(404, "歌單內沒有可匯入的公開歌曲。")
        return {"title": str(title)[:300], "tracks": tracks, "count": count,
                "truncated": count > len(tracks) or count_is_minimum, "count_is_minimum": count_is_minimum,
                "source_url": url, "source_type": kind}

    async def library_import_preview(self, request):
        uid = self.library_identity(request)
        guild, member = self.guild_owner(request)
        data = await self.payload(request)
        pid = request.match_info.get("playlist_id")
        value = await self.playlist_store.transact(uid, authorize=lambda: self.import_authorize(request, uid))
        target = None
        if pid is not None:
            if set(data) != {"revision"}:
                fail(400, "重新同步預覽只接受歌單版本。")
            if data["revision"] != value["revision"]:
                fail(409, "歌單已更新，請重新整理後再操作。")
            target = next((p for p in value["playlists"] if p["id"] == pid), None)
            if target is None:
                fail(404, "找不到你的歌單。")
            if not target.get("source_url"):
                fail(400, "這份歌單沒有可重新同步的來源。")
            url, kind = source_url(target["source_url"])
        else:
            if set(data) != {"url"}:
                fail(400, "匯入預覽只接受來源連結。")
            if len(value["playlists"]) >= 21:
                fail(400, "自訂歌單最多 20 份。")
            url, kind = source_url(data["url"])
        if kind == "spotify" and not self.spotify_import_enabled():
            fail(503, "目前無法讀取 Spotify 歌單")
        from . import exceptions
        from .web_dashboard import APIError
        try:
            self.bot._do_song_blocklist_check(url)
        except exceptions.MusicbotException:
            fail(403, "查詢內容被封鎖清單擋下。")
        self.user_rate_limit(member)
        if guild.id in self.resolve_tasks or len(self.resolve_tasks) >= 2:
            fail(429, "解析仍在進行，請稍後再查詢。播放控制仍可使用。")
        task = asyncio.create_task(self.import_source(url, kind))
        self.resolve_tasks[guild.id] = task
        def finished(done):
            self.resolve_tasks.pop(guild.id, None)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)
        try:
            preview = await asyncio.wait_for(asyncio.shield(task), self.RESOLVE_TIMEOUT)
        except asyncio.TimeoutError:
            fail(504, "解析逾時，請稍後再試。播放控制仍可使用。")
        except APIError:
            raise
        except Exception:
            fail(502, "無法讀取這份公開歌單，請檢查連結或稍後再試。")
        self.import_authorize(request, uid)
        self.guild_owner(request)
        now = time.monotonic()
        self.import_previews = {k: v for k, v in self.import_previews.items() if v["expires"] > now}
        token = secrets.token_urlsafe(24)
        pending = dict(copy.deepcopy(preview), owner_id=uid, guild_id=guild.id,
                       playlist_id=pid, revision=value["revision"], expires=now + self.PREVIEW_TTL)
        if target is not None:
            pending["diff"] = source_diff(target["tracks"], preview["tracks"])
        self.import_previews[token] = pending
        while len(self.import_previews) > 100:
            self.import_previews.pop(next(iter(self.import_previews)))
        return web.json_response({"preview_id": token, "revision": value["revision"], "title": preview["title"],
            "source_url": url, "source_type": kind, "count": preview["count"],
            "import_count": len(preview["tracks"]), "tracks": preview["tracks"][:5],
            "count_is_minimum": preview.get("count_is_minimum", False),
            "truncated": preview["truncated"],
            "warning": "超過 200 首，只會匯入來源前 200 首中的可用歌曲。" if preview["truncated"] else "",
            "diff": pending.get("diff"), "expires_in": self.PREVIEW_TTL})

    async def library_import_confirm(self, request):
        uid = self.library_identity(request)
        data = await self.payload(request)
        pid = request.match_info.get("playlist_id")
        allowed = {"preview_id", "revision"} if pid is not None else {"preview_id", "revision", "name"}
        if set(data) not in (allowed, allowed | {"selected_items"}) or (pid is not None and "selected_items" in data):
            fail(400, "匯入確認欄位不正確，請重新預覽。")
        token = data.get("preview_id")
        if not isinstance(token, str):
            fail(409, "匯入預覽已過期，請重新預覽。")
        lock = self.import_locks.setdefault(uid, asyncio.Lock())
        async with lock:
            pending = self.import_previews.get(token)
            if (not pending or pending["expires"] <= time.monotonic() or pending["owner_id"] != uid
                    or pending["playlist_id"] != pid or pending["revision"] != data.get("revision")):
                fail(409, "匯入預覽已過期或歌單已更新，請重新預覽。")
            guild = self.bot.get_guild(pending["guild_id"])
            member = guild.get_member(uid) if guild and not getattr(guild, "unavailable", False) else None
            if member is None:
                fail(403, "你目前不是來源伺服器的成員。")
            self.check_blocked(member)
            def authorize():
                self.import_authorize(request, uid)
                current = self.bot.get_guild(pending["guild_id"])
                person = current.get_member(uid) if current and not getattr(current, "unavailable", False) else None
                if person is None:
                    fail(403, "你目前不是來源伺服器的成員。")
                self.check_blocked(person)
            from .web_dashboard_library import name, song
            tracks = pending["tracks"]
            if "selected_items" in data:
                selected = data["selected_items"]
                available = {t.get("item_id", str(i + 1)): t for i, t in enumerate(tracks)}
                if (not isinstance(selected, list) or not selected or len(selected) > 200
                        or any(type(i) is not str or i not in available or not available[i].get("allowed", True) for i in selected)
                        or len(set(selected)) != len(selected)):
                    fail(400, "請勾選有效且允許的歌曲。")
                tracks = [t for i, t in available.items() if i in selected]
            def change(value):
                if pid is None:
                    if len(value["playlists"]) >= 21:
                        fail(400, "自訂歌單最多 20 份。")
                    target = {"id": secrets.token_hex(12), "name": name(data["name"])}
                    value["playlists"].append(target)
                else:
                    target = next((p for p in value["playlists"] if p["id"] == pid), None)
                    if target is None:
                        fail(404, "找不到你的歌單。")
                target.update(tracks=[song(t) for t in tracks],
                              source_url=pending["source_url"], source_type=pending["source_type"])
            result = await self.playlist_store.transact(uid, change, pending["revision"],
                authorize=authorize)
            self.import_previews.pop(token, None)
        return web.json_response(dict(result, owner=uid == self.bot.config.owner_id,
            message="已從來源重新同步。" if pid else "已匯入新的個人歌單。"))
