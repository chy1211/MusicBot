"""One-use, actor-bound queue undo records. No client-supplied song data."""
from .web_dashboard_i18n import message as _web_text
import asyncio
import secrets
import time
from aiohttp import web
from .downloader import YtdlpResponseDict
from .constructs import Response
from .i18n import _D
from .web_dashboard_media import media_url
from .web_dashboard_activity import capture, finish

class DashboardUndo:
    def init_undo(self):
        self.undo_records = {}
        self.undo_timers = {}
        self.app.router.add_post("/api/guilds/{guild_id}/queue/undo", self.undo_remove)
        async def cleanup(_app):
            for timer in self.undo_timers.values(): timer.cancel()
            self.undo_records.clear(); self.undo_timers.clear()
        self.app.on_cleanup.append(cleanup)

    def remember_removal(self, guild, member, entry, position):
        key=(guild.id,member.id); token=secrets.token_urlsafe(24)
        self.undo_records[key]={"token":token,"entry":entry,"position":position,"expires":time.monotonic()+10}
        old=self.undo_timers.pop(key,None)
        if old: old.cancel()
        def expire():
            if self.undo_records.get(key,{}).get("token")==token: self.undo_records.pop(key,None)
            self.undo_timers.pop(key,None)
        self.undo_timers[key]=asyncio.get_running_loop().call_later(10,expire)
        return {"undo_token":token,"undo_expires_in":10,"removed_title":str(entry.title)}

    async def undo_remove(self, request):
        from .web_dashboard import APIError
        guild,member=self.guild_owner(request)
        data=await self.payload(request)
        self.user_rate_limit(member)
        if set(data)!={"undo_token"} or not isinstance(data["undo_token"],str):
            raise APIError(400,_web_text('m0578'))
        async with self.locks[guild.id]:
            if self.discord_auth: self.authenticate(request)
            guild,member=self.guild_owner(request)
            key=(guild.id,member.id); pending=self.undo_records.get(key)
            if not pending or not secrets.compare_digest(pending["token"],data["undo_token"]):
                raise APIError(403,_web_text('m0579'))
            self.undo_records.pop(key,None)
            self.undo_timers.pop(key).cancel()
            if pending["expires"] <= time.monotonic():
                raise APIError(409,_web_text('m0580'))
            player,perms,channel=await self.context(guild,member,"remove")
            self.command_permission(member,perms,"play")
            if player is None: raise APIError(409,_web_text('m0395'))
            self.addition_checks(player,member,perms)
            entry=pending["entry"]
            url=media_url(entry.url) or entry.url
            if any((media_url(e.url) or e.url)==url for e in [*player.playlist.entries, player.current_entry] if e is not None):
                raise APIError(409,_web_text('m0581'))
            info=getattr(entry,"info",None) or YtdlpResponseDict({
                "__input_subject":entry.url,"title":entry.title,"url":entry.url,"webpage_url":entry.url,
                "duration":entry.duration,"extractor":""})
            reason=self.restriction(info,perms)
            if reason: raise APIError(403,reason)
            original=getattr(entry,"author",None)
            if original is not None:
                original_perms=self.bot.permissions.for_user(original)
                if original_perms.max_songs and player.playlist.count_for_user(original)>=original_perms.max_songs:
                    raise APIError(403,_web_text('m0582'))
                self.check_blocked(original)
                reason=self.restriction(info,original_perms)
                if reason: raise APIError(403,reason)
            value=capture(self,guild,member,"undo","web")
            try:
                # No await between final checks and inserting the very same object.
                player.playlist.insert_entry_at_index(min(pending["position"],len(player.playlist.entries)),entry)
                await self.bot.serialize_queue(guild)
                await self.send_web_response(request,guild,member,Response(_D("Restored %(title)s", self.bot.server_data[guild.id]) % {"title":str(entry.title)}),"undo")
                finish(value,True)
            except BaseException:
                finish(value,False);raise
            return web.json_response({"message":_web_text("message.restored",p0=str(entry.title)),"state":self.snapshot(guild,member)})
