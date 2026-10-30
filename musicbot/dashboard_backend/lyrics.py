"""Lyrics routes and per-user synchronization controls."""
from __future__ import annotations

import hashlib
import asyncio
import math
import re
import time
from aiohttp import web


class DashboardLyricsRoutes:

    def lyrics_rate_limit(self, member):
        from ..web_dashboard import APIError, _web_text
        now = time.monotonic()
        self.lyrics_rate_limits = {
            uid: [stamp for stamp in stamps if stamp > now - 60]
            for uid, stamps in self.lyrics_rate_limits.items()
            if stamps and stamps[-1] > now - 60}
        stamps = self.lyrics_rate_limits.setdefault(member.id, [])
        if len(stamps) >= self.LYRICS_REQUESTS_PER_MINUTE:
            raise APIError(429, _web_text('m0374'))
        if len(self.lyrics_rate_limits) > 1024:
            self.lyrics_rate_limits.pop(next(iter(self.lyrics_rate_limits)))
        stamps.append(now)

    async def admin_lyrics(self, request):
        from ..web_dashboard import APIError, _web_text
        guild, _ = self.require_owner(request)
        if request.method == "POST":
            data = await self.payload(request)
            if not isinstance(data, dict) or set(data) != {"enabled"} or type(data["enabled"]) is not bool:
                raise APIError(400, _web_text('m0375'))
            async with self.admin_lock:
                if self.discord_auth: self.authenticate(request)
                guild, _ = self.require_owner(request)
                await self.lyrics_store.set_enabled(guild, data["enabled"])
        if self.discord_auth: self.authenticate(request)
        self.require_owner(request)
        return web.json_response({"enabled": await self.lyrics_store.enabled(guild)})

    async def lyrics(self, request):
        from ..web_dashboard import APIError, _web_text, video_id, lyrics_metadata
        guild, member = self.guild_owner(request)
        if not await self.lyrics_store.enabled(guild):
            raise APIError(403, _web_text('m0376'))
        query = request.query.get("query", "").strip()
        if len(query) > 160 or any(ord(char) < 32 for char in query):
            raise APIError(400, _web_text('m0377'))
        self.lyrics_rate_limit(member)
        player = self.bot.get_player_in(guild)
        entry = getattr(player, "current_entry", None)
        if entry is None:
            raise APIError(409, _web_text('m0378'))
        token = self.track_token(player)
        info = getattr(entry, "info", {}) or {}
        title, artist = entry.title, info.get("artist") or info.get("creator") or ""
        track_key = hashlib.sha256(str((entry.url, entry.title, entry.duration)).encode()).hexdigest()
        key = video_id(entry.url)
        # Check the verified, per-video persistent cache before remote Spotify.
        # A manual query still bypasses this video cache as before.
        value = await self.lyrics_store.get(key) if key and not query else None
        if value is None:
            if not query:
                # Cap auxiliary metadata lookup so slow Spotify cannot starve LRCLIB.
                try:
                    matched = await asyncio.wait_for(self.spotify_lookup.lookup(self.bot, entry), timeout=3.0)
                except Exception:
                    matched = {}
                if (matched.get("mode") == "track" and matched.get("title")
                        and matched.get("artist") and not lyrics_metadata(title, artist)["cover"]):
                    title, artist = matched["title"], matched["artist"]
            if not artist:
                artist = str(info.get("channel") or info.get("uploader") or "")
                artist = re.sub(r"\s*(?:-\s*Topic|VEVO|Official(?: Channel)?)\s*$", "", artist, flags=re.I).strip()[:160]
            value = await self.lyrics_client.lookup(title, artist, entry.duration, query=query)
            if key and not query and value["status"] != "unavailable":
                ttl = 3*3600 if value["status"] == "not_found" else 7*86400
                await self.lyrics_store.put(key, value, ttl)
        # An expired session/removed member must not receive data after a slow lookup.
        if self.discord_auth:
            self.authenticate(request)
        self.guild_owner(request)
        if not await self.lyrics_store.enabled(guild):
            raise APIError(403, _web_text('m0376'))
        if token != self.track_token(self.bot.get_player_in(guild)):
            raise APIError(409, _web_text('m0379'))
        offset = {}
        if key and value.get("status") == "synced":
            await self.lyrics_alignment.request(self.bot, entry, value)
            offset = await self.lyric_offset_value(guild, key)
        return web.json_response(dict(value, track_key=track_key, video_id=key,
            track_token=token, **offset))

    async def lyric_offset_value(self, guild, key):
        from ..web_dashboard import UNCERTAIN
        automatic = await self.lyrics_store.get(key, "analysis") or dict(UNCERTAIN)
        manual = await self.lyrics_store.manual(guild, key)
        return {"offset": manual if manual is not None else automatic.get("offset", 0),
                "offset_source": "manual" if manual is not None else automatic.get("source", "uncertain"),
                "analysis_pending": key in self.lyrics_alignment.tasks}

    async def lyrics_offset(self, request):
        from ..web_dashboard import APIError, _web_text, video_id
        guild, member = self.guild_owner(request)
        if not await self.lyrics_store.enabled(guild):
            raise APIError(403, _web_text('m0376'))
        now = time.monotonic()
        rates = self.lyrics_offset_rates = {uid:[stamp for stamp in stamps if stamp>now-60]
            for uid,stamps in self.lyrics_offset_rates.items() if stamps and stamps[-1]>now-60}
        stamps = rates.setdefault(member.id, [])
        if len(stamps) >= 60:
            raise APIError(429, _web_text('m0380'))
        stamps.append(now)
        if len(rates)>1024: rates.pop(next(iter(rates)))
        player = self.bot.get_player_in(guild)
        entry = getattr(player, "current_entry", None)
        key = video_id(entry.url) if entry else ""
        if not key: raise APIError(409, _web_text('m0381'))
        token = self.track_token(player)
        if request.method == "POST":
            self.lyrics_rate_limit(member)
            data = await self.payload(request)
            action = data.get("action")
            fields = {"set":{"action","offset","track_token"}, "adjust":{"action","delta","track_token"},
                      "sync":{"action","position","track_token"}, "reset":{"action","track_token"}}
            if action not in fields or set(data) != fields[action]:
                raise APIError(400, _web_text('m0382'))
            if data["track_token"] != self.track_token(player):
                raise APIError(409, _web_text('m0383'))
            async with self.lyrics_offset_locks[(guild.id, key)]:
                if self.discord_auth: self.authenticate(request)
                guild, member = self.guild_owner(request)
                if not await self.lyrics_store.enabled(guild):
                    raise APIError(403, _web_text('m0376'))
                if data["track_token"] != self.track_token(self.bot.get_player_in(guild)):
                    raise APIError(409, _web_text('m0383'))
                value = None
                if action == "set": value = data["offset"]
                elif action == "adjust":
                    delta = data["delta"]
                    if type(delta) not in (int,float) or delta not in (-.5,.5):
                        raise APIError(400, _web_text('m0384'))
                    value = (await self.lyric_offset_value(guild,key))["offset"] + delta
                elif action == "sync":
                    lyrics = await self.lyrics_store.get(key)
                    lines = [line for line in lyrics.get("lines",[]) if str(line.get("text","")).strip()] if lyrics else []
                    position = data["position"]
                    if (not lines or type(position) not in (int,float) or not math.isfinite(position)
                            or not 0 <= position <= (entry.duration or 0)):
                        raise APIError(400, _web_text('m0385'))
                    value = position - lines[0]["time"]
                if action != "reset" and (type(value) not in (int,float) or not math.isfinite(value) or not -30 <= value <= 60):
                    raise APIError(400, _web_text('m0386'))
                await self.lyrics_store.set_manual(guild,key,round(value,2) if value is not None else None)
                self.record_activity(guild, getattr(member,"display_name",None) or member.name,
                    "lyrics_offset","web",_web_text('m0387') + (_web_text('m0388') if value is None else _web_text('m0389', p0=format(value, '+.1f'))),_web_text('m0024'))
        if self.discord_auth: self.authenticate(request)
        self.guild_owner(request)
        value = await self.lyric_offset_value(guild,key)
        if token != self.track_token(self.bot.get_player_in(guild)):
            raise APIError(409, _web_text('m0383'))
        return web.json_response(dict(value,video_id=key,track_token=token))
