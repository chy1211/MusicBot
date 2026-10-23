"""Queue state and popularity read routes."""
from __future__ import annotations

import hashlib
from aiohttp import web


class DashboardStateRoutes:
    @staticmethod
    def track_token(player):
        entry = getattr(player, "current_entry", None)
        return (hashlib.sha256(str((id(player), id(entry))).encode()).hexdigest()
                if entry is not None else "")

    def control_capabilities(self, guild, viewer):
        """Viewer-only hints; mutation handlers still authorize every request."""
        from ..web_dashboard import APIError
        result = dict.fromkeys(("pause", "resume", "skip", "seek"), False)
        if viewer is None or self.bot.get_player_in(guild) is None:
            return result
        permissions = self.bot.permissions.for_user(viewer)
        for command in result:
            try:
                self.command_permission(viewer, permissions, command)
                if self.discord_auth or command == "seek":
                    self.voice_permission(guild, viewer, permissions, command)
                elif not viewer.voice or not viewer.voice.channel:
                    continue
                self.channel_for(guild, viewer)
                result[command] = True
            except APIError:
                pass
        return result

    def snapshot(self, guild, viewer=None):
        from ..web_dashboard import track, revision
        community = {"lyrics_available": self.lyrics_store.allowed.get(guild.id, True),
                     "capabilities": self.control_capabilities(guild, viewer),
                     "listeners": self.listener_snapshot(guild),
                     "activity": self.activity_snapshot(guild)}
        player = self.bot.get_player_in(guild)
        if player is None:
            return {**community, "guild_id": str(guild.id),
                    "status": "disconnected",
                    "current": None, "progress": 0, "volume": None,
                    "repeat": "off", "queue": [], "revision": ""}
        pending = getattr(player, "_pending_seek", None)
        current = pending["entry"] if pending else player.current_entry
        entries = [entry for entry in player.playlist.entries
                   if not pending or entry is not pending["entry"]]
        known = self.queue_arrivals[guild.id]
        live = {id(entry) for entry in entries}
        known[:] = [key for key in known if key in live]
        known_ids = set(known)
        known.extend(id(entry) for entry in entries if id(entry) not in known_ids)
        return {
            **community, "guild_id": str(guild.id),
            "status": (("paused" if pending["paused"] else "playing") if pending else
                       "paused" if player.is_paused else "playing" if player.is_playing else "stopped"),
            "current": (dict(track(current, guild, viewer),
                             seekable=self.is_seekable(current),
                             track_token=self.track_token(player)) if current else None),
            "progress": max(0, float(pending["position"] if pending else player.progress)),
            "volume": round(player.volume * 100),
            "repeat": ("song" if player.repeatsong else
                       "all" if player.loopqueue else "off"),
            "queue": [dict(track(entry, guild, viewer), position=i)
                      for i, entry in enumerate(entries, 1)],
            "revision": revision(player),
        }

    async def state(self, request):
        guild, member = self.guild_owner(request)
        return web.json_response(self.snapshot(guild, member))

    async def popular(self, request):
        from ..web_dashboard import APIError, _web_text
        guild, member = self.guild_owner(request)
        period = request.query.get("period", "7")
        if period not in ("7", "30", "all"):
            raise APIError(400, _web_text('m0390'))
        try:
            tracks = await self.popularity_store.top(guild, period)
        except Exception:
            raise APIError(503, _web_text('m0391')) from None
        # Recheck membership after the asynchronous read.
        self.guild_owner(request)
        return web.json_response({"period": period, "tracks": tracks})
