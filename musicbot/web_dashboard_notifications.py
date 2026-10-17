"""Owner-configured fallback destinations; request channels always take priority."""
from __future__ import annotations

import asyncio

from aiohttp import web
from discord import ChannelType

from . import write_path
from .web_dashboard_i18n import message as _web_text
from .web_dashboard_library import fail
from .web_dashboard_guild_settings import GuildSettingsStore


def validate_notification(data):
    if not isinstance(data, dict) or set(data) != {"channel_id"}:
        raise ValueError()
    cid = data["channel_id"]
    if cid is not None and (
            not isinstance(cid, str) or not cid.isascii() or not cid.isdigit()
            or len(cid) > 20 or not 0 < int(cid) < 2**64 or str(int(cid)) != cid):
        raise ValueError()
    return {"channel_id": cid}


class NotificationChannelStore(GuildSettingsStore):
    def __init__(self, root):
        super().__init__(root, validate_notification, {"channel_id": None})


class DashboardNotifications:
    def init_notifications(self):
        self.notification_store = NotificationChannelStore(
            write_path("data/web_dashboard/notification_channels"))
        path = "/api/guilds/{guild_id}/admin/notification-channel"
        self.app.router.add_get(path, self.admin_notification_channel)
        self.app.router.add_post(path, self.admin_notification_channel)

    @staticmethod
    def notification_text_channel(guild, channel):
        return (channel is not None and getattr(channel, "guild", None) == guild
                and getattr(channel, "type", None) in (ChannelType.text, ChannelType.news))

    @staticmethod
    def notification_can_send(channel, member):
        perms = channel.permissions_for(member)
        return perms.view_channel and perms.send_messages

    def notification_channel(self, guild):
        cid = self.notification_store.read(guild)["channel_id"]
        channel = guild.get_channel(int(cid)) if cid is not None else None
        return channel if self.notification_text_channel(guild, channel) else None

    def notification_status(self, guild, owner, value):
        channels = [channel for channel in guild.text_channels
                    if self.notification_text_channel(guild, channel)
                    and self.notification_can_send(channel, guild.me)]
        cid = value["channel_id"]
        channel = guild.get_channel(int(cid)) if cid is not None else None
        bound = self.bot.config.bound_channels
        restrict = bool(bound) and (any(c.id in bound for c in guild.channels)
                                   or not self.bot.config.unbound_servers)
        unavailable = cid is not None and (
            not self.notification_text_channel(guild, channel)
            or not self.notification_can_send(channel, guild.me)
            or not self.notification_can_send(channel, owner)
            or (restrict and channel.id not in bound))
        return {**value, "channels": [{"id": str(c.id), "name": c.name} for c in channels],
                "unavailable": bool(unavailable)}

    async def admin_notification_channel(self, request):
        self.require_owner(request)
        async with self.admin_lock:
            if self.discord_auth:
                self.authenticate(request)
            guild, owner = self.require_owner(request)
            if request.method == "POST":
                try:
                    value = validate_notification(await self.payload(request))
                except (ValueError, TypeError):
                    fail(400, _web_text("notify.invalid"))
                cid = value["channel_id"]
                channel = guild.get_channel(int(cid)) if cid is not None else None
                if cid is not None and (
                        not self.notification_text_channel(guild, channel)
                        or not self.notification_can_send(channel, guild.me)):
                    fail(400, _web_text("notify.invalid"))
                try:
                    value = await self.notification_store.put(guild, value)
                except OSError:
                    fail(503, _web_text("notify.save_failed"))
            else:
                value = await asyncio.to_thread(self.notification_store.read, guild)
            # A file operation may have yielded; recheck membership and identity.
            if self.discord_auth:
                self.authenticate(request)
            guild, owner = self.require_owner(request)
            return web.json_response(self.notification_status(guild, owner, value))
