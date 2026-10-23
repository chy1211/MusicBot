"""Viewer authorization and bounded playback history routes."""
from __future__ import annotations

import math
import time
from types import SimpleNamespace
from aiohttp import web
from ..entry import LocalFilePlaylistEntry, URLPlaylistEntry
from ..web_dashboard_auth import USER_KEY
from ..web_dashboard_radio import is_radio


class DashboardIdentityHistory:

    def _dashboard_compat(self):
        # Resolve public facade helpers at call time to preserve monkeypatches.
        from .. import web_dashboard
        return web_dashboard


    def guild_owner(self, request):
        from ..web_dashboard import APIError, _web_text
        raw = request.match_info["guild_id"]
        if not raw.isdigit():
            raise APIError(400, _web_text('m0367'))
        guild = self.bot.get_guild(int(raw))
        if not guild or getattr(guild, "unavailable", False):
            raise APIError(404, _web_text('m0368'))
        uid = int(request[USER_KEY]["id"]) if self.discord_auth else self.bot.config.owner_id
        owner = guild.get_member(uid)
        if owner is None:
            if self.discord_auth: self.revoke_session(request)
            raise APIError(403, _web_text('m0369') if self.discord_auth
                           else _web_text('m0370'))
        self.check_blocked(owner)
        now = time.monotonic()
        self.web_viewers = {uid: at for uid, at in self.web_viewers.items() if at > now-45}
        self.web_viewers[owner.id] = now
        return guild, owner

    def check_blocked(self, member):
        from ..web_dashboard import APIError, _web_text
        if not self.discord_auth or member.id == self.bot.config.owner_id:
            return
        blocklist = getattr(self.bot.config, "user_blocklist", None)
        if blocklist is not None and blocklist.is_blocked(member):
            raise APIError(403, _web_text('m0371'))

    async def guilds(self, request):
        from ..web_dashboard import APIError, _web_text
        uid = int(request[USER_KEY]["id"]) if self.discord_auth else self.bot.config.owner_id
        result = []
        for guild in self.bot.guilds:
            member = guild.get_member(uid)
            if not getattr(guild, "unavailable", False) and member is not None:
                self.check_blocked(member)
                result.append({"id": str(guild.id), "name": guild.name})
        # Return only this viewer's recommendation, without other requesters.
        visible = {row["id"] for row in result}
        recommended = None
        for guild in self.bot.guilds:
            if str(guild.id) not in visible:
                continue
            member = guild.get_member(uid)
            voice = getattr(getattr(member, "voice", None), "channel", None)
            player = self.bot.get_player_in(guild)
            bot_voice = (getattr(getattr(player, "voice_client", None), "channel", None)
                         or getattr(getattr(getattr(guild, "me", None), "voice", None), "channel", None))
            if voice is not None and bot_voice is not None and voice.id == bot_voice.id:
                recommended = str(guild.id)
                break
        if recommended is None:
            recent = self.last_requested_guild.get(uid)
            if recent is not None and str(recent) in visible:
                recommended = str(recent)
        return web.json_response({"guilds": result, "recommended_guild_id": recommended})
    @staticmethod
    def is_seekable(entry):
        return (isinstance(entry, (URLPlaylistEntry, LocalFilePlaylistEntry))
                and getattr(entry, "duration", 0) is not None
                and float(entry.duration) > 0
                and math.isfinite(float(entry.duration)))

    def record_play(self, guild, entry, played_at=None):
        """Called by the real playback event, independently of browser polling."""
        if entry is None:
            return
        # A "play" event represents an audio-source start, not a new request.
        # Native seek requeues the same object; reconnect may reconstruct it.
        marker = (self.history_marker, guild.id)
        if getattr(entry, "_dashboard_history_marker", None) == marker:
            return
        setattr(entry, "_dashboard_history_marker", marker)
        item = self._dashboard_compat().track(entry, guild)
        moment = float(played_at if played_at is not None else time.time())
        last = self.history_last_source.get(guild.id)
        if last and last[0] == item["url"] and 0 <= moment - last[1] < 10:
            return
        self.history_last_source[guild.id] = (item["url"], moment)
        meta = getattr(entry, "meta", None) or {}
        author = (getattr(entry, "author", None) or getattr(entry, "member", None)
                  or meta.get("author") or meta.get("member"))
        # Retain only the Discord id; resolve the display name/avatar on read.
        item.pop("requester", None)
        item["requester_id"] = getattr(author, "id", None)
        item["requested"] = bool(author or getattr(entry, "channel", None))
        item["radio"] = bool(is_radio(entry))
        item["played_at"] = moment
        self.recent_history[guild.id].appendleft(item)

    async def history(self, request):
        guild, _member = self.guild_owner(request)
        return web.json_response(self.history_snapshot(guild))

    def history_snapshot(self, guild):
        from ..web_dashboard import _web_text
        rows = []
        for item in self.recent_history.get(guild.id, ()):
            public = {key: item[key] for key in
                      ("title", "url", "thumbnail", "duration", "played_at")}
            person = guild.get_member(item["requester_id"]) if item["requester_id"] else None
            public["requester"] = self._dashboard_compat().requester(SimpleNamespace(
                author=person, channel=True if item["requested"] else None), guild)
            if item.get("radio"):
                public["requester"] = {"name": _web_text('m0338'), "avatar": ""}
            rows.append(public)
        source = "dashboard_memory"
        config = self.bot.config
        # Existing histories contain URLs only. Reuse an already loaded guild
        # playlist without file I/O, lazy file creation or extracting old URLs.
        if getattr(config, "enable_queue_history_guilds", False):
            source = "guild_queue_history+dashboard_metadata"
            manager = getattr(self.bot, "playlist_mgr", None)
            playlist = getattr(manager, "_playlists", {}).get(f"history-{guild.id}")
            if playlist is not None and getattr(playlist, "loaded", False):
                known = {item["url"] for item in rows}
                for url in reversed(list(playlist)[-50:]):
                    url = self._dashboard_compat().public_url(url)
                    if url and url not in known and len(rows) < 50:
                        rows.append({"title": _web_text('m0372'),
                                     "url": url, "thumbnail": "", "duration": 0,
                                     "played_at": None,
                                     "requester": {"name": _web_text('m0373'), "avatar": ""}})
                        known.add(url)
        elif getattr(config, "enable_queue_history_global", False):
            # Never disclose the global URL pool to a member of one guild.
            source = "dashboard_memory_global_history_unscoped"
        return {"history": rows[:50], "source": source, "resets_on_restart": True}
