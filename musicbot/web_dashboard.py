"""Optional, owner-only HTTP dashboard. Never logs in to Discord on its own."""
from __future__ import annotations

import asyncio
import configparser
import hashlib
import hmac
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from aiohttp import web

from . import exceptions
from .constructs import ErrorResponse
from .i18n import _D

log = logging.getLogger(__name__)
STATIC = Path(__file__).with_name("web")


@dataclass(frozen=True)
class DashboardConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8080
    shared_secret: str = field(default="", repr=False)

    @classmethod
    def load(cls, path: Path) -> DashboardConfig:
        if not path.is_file():
            return cls()
        parser = configparser.ConfigParser(interpolation=None)
        with path.open(encoding="utf-8-sig") as stream:
            parser.read_file(stream)
        if not parser.getboolean("WebDashboard", "Enabled", fallback=False):
            return cls()
        host = parser.get("WebDashboard", "Host", fallback="127.0.0.1").strip()
        port = parser.getint("WebDashboard", "Port", fallback=8080)
        if not host or not 1 <= port <= 65535:
            raise ValueError("Invalid dashboard bind address or port")
        return cls(True, host, port, parser.get(
            "WebDashboard", "SharedSecret", fallback="").strip())


class APIError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def public_url(value) -> str:
    value = str(value or "")
    parts = urlsplit(value)
    return value if parts.scheme in ("http", "https") and not parts.username else ""


def track(entry) -> dict | None:
    if entry is None:
        return None
    return {
        "title": str(entry.title),
        "url": public_url(entry.url),
        "thumbnail": public_url(getattr(entry, "thumbnail_url", "")),
        "duration": float(getattr(entry, "duration", 0) or 0),
    }


def revision(player) -> str:
    # Object identities distinguish duplicate URLs and identical new queues.
    identities = [id(player), id(player.current_entry)]
    identities.extend(id(entry) for entry in player.playlist.entries)
    return hashlib.sha256(str(identities).encode()).hexdigest()


class Dashboard:
    def __init__(self, bot, config: DashboardConfig):
        self.bot = bot
        self.config = config
        self.runner = None
        self.site = None
        self.locks = defaultdict(asyncio.Lock)
        self.app = web.Application(
            middlewares=[self.guard], client_max_size=16 * 1024)
        self.app.router.add_get("/", self.index)
        self.app.router.add_get("/dashboard.css", self.asset)
        self.app.router.add_get("/dashboard.js", self.asset)
        self.app.router.add_get("/api/guilds", self.guilds)
        self.app.router.add_get("/api/guilds/{guild_id}/state", self.state)
        for action in ("play", "pause", "resume", "skip", "volume", "repeat"):
            self.app.router.add_post(
                "/api/guilds/{guild_id}/" + action, self.mutate)
        self.app.router.add_post(
            "/api/guilds/{guild_id}/queue/shuffle", self.mutate)
        self.app.router.add_post(
            "/api/guilds/{guild_id}/queue/move", self.mutate)
        self.app.router.add_delete(
            "/api/guilds/{guild_id}/queue/{position}", self.mutate)

    @web.middleware
    async def guard(self, request, handler):
        try:
            if request.path.startswith("/api/"):
                # A custom header + no CORS prevents cross-site forms/fetches,
                # including when the optional shared secret is empty.
                if request.headers.get("X-MusicBot-Dashboard") != "1":
                    raise APIError(403, "請從音樂控制台操作。")
                origin = request.headers.get("Origin")
                if origin and urlsplit(origin).netloc != request.host:
                    raise APIError(403, "不允許跨網站操作。")
                if self.config.shared_secret:
                    token = request.headers.get("Authorization", "")
                    expected = "Bearer " + self.config.shared_secret
                    if not hmac.compare_digest(token.encode(), expected.encode()):
                        raise APIError(401, "共享密鑰錯誤或尚未填寫。")
                if (not self.bot.is_ready() or not self.bot.init_ok
                        or self.bot.logout_called):
                    raise APIError(503, "機器人尚未就緒，請稍後再試。")
            response = await handler(request)
        except APIError as exc:
            log.warning("Dashboard request rejected: HTTP %d", exc.status)
            response = web.json_response({"error": str(exc)}, status=exc.status)
        except exceptions.MusicbotException as exc:
            log.warning("Dashboard command rejected (%s)", type(exc).__name__)
            try:
                guild_id = request.match_info.get("guild_id", "")
                ssd = self.bot.server_data.get(int(guild_id)) if guild_id.isdigit() else None
                message = _D(exc.message, ssd) % exc.fmt_args
                response = web.json_response(
                    {"error": "機器人拒絕操作：" + message},
                    status=403 if isinstance(exc, exceptions.PermissionsError) else 400)
            except Exception:
                log.exception("Dashboard error response formatting failed")
                response = web.json_response(
                    {"error": "操作失敗，已記錄錯誤。"}, status=500)
        except web.HTTPException as exc:
            log.warning("Dashboard HTTP error: %d", exc.status)
            response = web.json_response(
                {"error": "請求內容、路徑或方法不正確。"}, status=exc.status)
        except Exception:
            log.exception("Dashboard request failed")
            response = web.json_response(
                {"error": "操作失敗，已記錄錯誤；請重新整理後再試。"}, status=500)
        response.headers.update({
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'self'; img-src 'self' https: http:; "
                "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"),
        })
        return response

    async def index(self, _request):
        return web.Response(
            text=(STATIC / "index.html").read_text(encoding="utf-8"),
            content_type="text/html")

    async def asset(self, request):
        name = request.path.lstrip("/")
        return web.Response(
            text=(STATIC / name).read_text(encoding="utf-8"),
            content_type="text/css" if name.endswith(".css") else "text/javascript")

    def guild_owner(self, request):
        raw = request.match_info["guild_id"]
        if not raw.isdigit():
            raise APIError(400, "伺服器編號不正確。")
        guild = self.bot.get_guild(int(raw))
        if not guild or getattr(guild, "unavailable", False):
            raise APIError(404, "找不到可用的伺服器。")
        owner = guild.get_member(self.bot.config.owner_id)
        if owner is None:
            raise APIError(403, "OwnerID 本人不在這個伺服器。")
        return guild, owner

    async def guilds(self, _request):
        return web.json_response({"guilds": [
            {"id": str(g.id), "name": g.name}
            for g in self.bot.guilds
            if not getattr(g, "unavailable", False)
            and g.get_member(self.bot.config.owner_id) is not None
        ]})

    def snapshot(self, guild):
        player = self.bot.get_player_in(guild)
        if player is None:
            return {"guild_id": str(guild.id), "status": "disconnected",
                    "current": None, "progress": 0, "volume": None,
                    "repeat": "off", "queue": [], "revision": ""}
        entries = list(player.playlist.entries)
        return {
            "guild_id": str(guild.id),
            "status": ("paused" if player.is_paused else "playing"
                       if player.is_playing else "stopped"),
            "current": track(player.current_entry),
            "progress": max(0, float(player.progress)),
            "volume": round(player.volume * 100),
            "repeat": ("song" if player.repeatsong else
                       "all" if player.loopqueue else "off"),
            "queue": [dict(track(entry), position=i)
                      for i, entry in enumerate(entries, 1)],
            "revision": revision(player),
        }

    async def state(self, request):
        guild, _owner = self.guild_owner(request)
        return web.json_response(self.snapshot(guild))

    def channel_for(self, guild, owner):
        bound = self.bot.config.bound_channels
        has_bound = any(c.id in bound for c in guild.channels)
        restrict = bool(bound) and (has_bound or not self.bot.config.unbound_servers)
        candidates = ([guild.get_channel(cid) for cid in sorted(bound)]
                      + [owner.voice.channel, guild.system_channel]
                      + list(guild.text_channels))
        for channel in candidates:
            if (channel is None or getattr(channel, "guild", None) != guild
                    or not hasattr(channel, "typing")
                    or (restrict and channel.id not in bound)):
                continue
            member_perms = channel.permissions_for(owner)
            bot_perms = channel.permissions_for(guild.me)
            if (member_perms.view_channel and member_perms.send_messages
                    and bot_perms.view_channel and bot_perms.send_messages):
                return channel
        raise APIError(403, "找不到符合綁定設定且雙方都能發言的頻道。")

    async def context(self, guild, owner, command):
        permissions = self.bot.permissions.for_user(owner)
        # Match the owner command gate; do not construct permissive fake users.
        if (owner.id != self.bot.config.owner_id
                and not permissions.can_use_command(command)):
            raise APIError(403, "沒有使用這個指令的權限。")
        if not owner.voice or not owner.voice.channel:
            raise APIError(409, "請先用 OwnerID 本人加入 Discord 語音頻道。")
        if permissions.ignore_non_voice and command in permissions.ignore_non_voice:
            await self.bot._check_ignore_non_voice(
                SimpleNamespace(guild=guild, author=owner))
        channel = self.channel_for(guild, owner)
        # Only play may summon a new player. Read-only requests never join voice.
        player = await self.bot.get_player(
            owner.voice.channel, create=permissions.summonplay if command == "play" else False)
        return player, permissions, channel

    @staticmethod
    def integer(data, key, minimum, maximum):
        value = data.get(key)
        if type(value) is not int or not minimum <= value <= maximum:
            raise APIError(400, f"{key} 必須是 {minimum} 到 {maximum} 之間的整數。")
        return value

    async def mutate(self, request):
        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise APIError(400, "請提供 JSON 格式的操作內容。") from None
        if not isinstance(data, dict):
            raise APIError(400, "操作內容必須是 JSON 物件。")
        guild, owner = self.guild_owner(request)
        action = request.path.rsplit("/", 1)[-1]
        if request.method == "DELETE":
            action = "remove"
        if action == "play":
            query = data.get("query")
            if not isinstance(query, str) or not 0 < len(query.strip()) <= 2000:
                raise APIError(400, "請輸入連結或搜尋關鍵字（最多 2000 字）。")
        elif action == "volume":
            self.integer(data, "volume", 1, 100)
        elif action == "repeat" and data.get("mode") not in ("off", "song", "all"):
            raise APIError(400, "重複模式必須是 off、song 或 all。")

        async with self.locks[guild.id]:
            player, permissions, channel = await self.context(guild, owner, action)
            ssd = self.bot.server_data[guild.id]
            if action in ("remove", "move", "shuffle"):
                if not data.get("revision") or data["revision"] != revision(player):
                    raise APIError(409, "隊列已更新，請重新整理後再操作。")
            response = None
            if action == "play":
                response = await self.bot.cmd_play(
                    message=None, player=player, channel=channel, guild=guild,
                    author=owner, permissions=permissions, leftover_args=[],
                    song_url=query.strip())
            elif action in ("pause", "resume"):
                response = await getattr(self.bot, "cmd_" + action)(ssd, player)
            elif action == "skip":
                response = await self.bot.cmd_skip(
                    ssd_=ssd, guild=guild, player=player, author=owner,
                    message=None, permissions=permissions,
                    voice_channel=player.voice_client.channel, param="")
            elif action == "volume":
                response = await self.bot.cmd_volume(ssd, player, str(data["volume"]))
            elif action == "repeat":
                if not player.current_entry:
                    raise APIError(409, "目前沒有播放中的歌曲。")
                mode = data["mode"]
                if player.repeatsong and mode != "song":
                    await self.bot.cmd_repeat(ssd, player, "off")
                if player.loopqueue and mode != "all":
                    await self.bot.cmd_repeat(ssd, player, "all")
                if mode == "song" and not player.repeatsong:
                    response = await self.bot.cmd_repeat(ssd, player, "on")
                if mode == "all" and not player.loopqueue:
                    response = await self.bot.cmd_repeat(ssd, player, "all")
            elif action == "remove":
                position = request.match_info["position"]
                if not position.isdigit() or int(position) < 1:
                    raise APIError(400, "歌曲位置必須是正整數。")
                response = await self.bot.cmd_remove(
                    ssd_=ssd, user_mentions=[], author=owner,
                    permissions=permissions, player=player,
                    leftover_args=[], position=position)
            elif action == "move":
                size = len(player.playlist.entries)
                source = self.integer(data, "from", 1, size) - 1
                target = self.integer(data, "to", 1, size) - 1
                # Same Playlist primitives as cmd_move, without its awaited
                # Discord animation/message before the mutation (race window).
                entry = player.playlist.delete_entry_at_index(source)
                player.playlist.insert_entry_at_index(target, entry)
            elif action == "shuffle":
                player.playlist.shuffle()
            if isinstance(response, ErrorResponse):
                raise APIError(409, response.description or "機器人無法完成操作。")
            if action in ("remove", "move", "shuffle"):
                await self.bot.serialize_queue(guild)
            return web.json_response({"message": "已完成操作。",
                                      "state": self.snapshot(guild)})

    async def start(self):
        self.runner = web.AppRunner(self.app, access_log=None, shutdown_timeout=5)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.config.host, self.config.port)
        await self.site.start()
        log.info("Owner web dashboard started on %s:%d",
                 self.config.host, self.config.port)

    async def close(self):
        runner, self.runner = self.runner, None
        if runner:
            await runner.cleanup()
        self.site = None


async def start_dashboard(bot, config_path: Path):
    """Fail closed; a missing/disabled/broken dashboard must not stop MusicBot."""
    dashboard = None
    try:
        config = DashboardConfig.load(config_path)
        if not config.enabled:
            return None
        dashboard = Dashboard(bot, config)
        await dashboard.start()
        return dashboard
    except Exception as exc:
        # Config parse errors can include a secret line: log only the type.
        log.error("Dashboard startup failed (%s); MusicBot will continue",
                  type(exc).__name__)
        if dashboard is not None:
            try:
                await dashboard.close()
            except Exception:
                log.exception("Dashboard cleanup after failed startup failed")
        return None
