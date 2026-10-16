"""Optional, owner-only HTTP dashboard. Never logs in to Discord on its own."""
from __future__ import annotations

import asyncio
import configparser
import hashlib
import hmac
import json
import logging
import math
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from aiohttp import web

from . import exceptions
from .constructs import ErrorResponse
from .i18n import _D
from .spotify import Spotify
from .utils import get_compound_link_ids

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
        self.resolve_tasks = {}
        self.previews = {}
        self.app = web.Application(
            middlewares=[self.guard], client_max_size=16 * 1024)
        self.app.router.add_get("/", self.index)
        self.app.router.add_get("/dashboard.css", self.asset)
        self.app.router.add_get("/dashboard.js", self.asset)
        self.app.router.add_get("/api/guilds", self.guilds)
        self.app.router.add_get("/api/guilds/{guild_id}/state", self.state)
        self.app.router.add_post(
            "/api/guilds/{guild_id}/resolve", self.resolve)
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

    RESOLVE_TIMEOUT = 20
    PREVIEW_TTL = 300
    PREVIEW_LIMIT = 10
    SEARCH_LIMIT = 5

    @staticmethod
    async def payload(request):
        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise APIError(400, "請提供 JSON 格式的操作內容。") from None
        if not isinstance(data, dict):
            raise APIError(400, "操作內容必須是 JSON 物件。")
        return data

    @staticmethod
    def query(data):
        value = data.get("query")
        if not isinstance(value, str) or not 0 < len(value.strip()) <= 2000:
            raise APIError(400, "請輸入連結或搜尋關鍵字（最多 2000 字）。")
        return value.strip()

    def preview_player(self, guild):
        # No get_player/context here: resolving must never summon or join voice.
        return self.bot.get_player_in(guild) or SimpleNamespace(
            karaoke_mode=False, playlist=SimpleNamespace(count_for_user=lambda _: 0))

    def addition_checks(self, player, owner, permissions):
        if owner.id != self.bot.config.owner_id and not permissions.can_use_command("play"):
            raise APIError(403, "沒有點歌權限。")
        if (permissions.max_songs and
                player.playlist.count_for_user(owner) >= permissions.max_songs):
            raise APIError(403, "已達到可排入佇列的歌曲數量上限。")
        if player.karaoke_mode and not permissions.bypass_karaoke_mode:
            raise APIError(403, "目前為卡拉 OK 模式，沒有點歌權限。")

    @staticmethod
    def info_duration(info):
        try:
            value = float(info.get("duration") or 0)
            return max(0, value) if math.isfinite(value) else 0
        except (TypeError, ValueError):
            return 0

    def restriction(self, info, permissions, *, playlist=False, extractor=""):
        # Same blocklist/extractor gates as _cmd_play and Playlist.import_from_info.
        try:
            self.bot._do_song_blocklist_check(info.url)
            self.bot._do_song_blocklist_check(info.webpage_url or info.get_playable_url())
            self.bot._do_song_blocklist_check(info.title)
        except exceptions.MusicbotException:
            return "歌曲被封鎖清單擋下。"
        try:
            permissions.can_use_extractor(info.extractor or extractor)
        except exceptions.MusicbotException:
            return "沒有使用這個來源解析器的權限。"
        duration = self.info_duration(info)
        if permissions.max_song_length and duration > permissions.max_song_length:
            return f"超過歌曲長度限制（{duration:g} > {permissions.max_song_length} 秒）。"
        if playlist and info.title.lower() in ("[private video]", "[deleted video]"):
            return "影片已刪除或未公開。"
        if not public_url(info.webpage_url or info.get_playable_url()):
            return "找不到可確認的來源網址。"
        return ""

    def preview_track(self, info, permissions, *, playlist=False, extractor=""):
        reason = self.restriction(info, permissions, playlist=playlist, extractor=extractor)
        return dict(title=info.title, duration=self.info_duration(info),
                    thumbnail=public_url(info.thumbnail_url),
                    url=public_url(info.webpage_url or info.get_playable_url()),
                    allowed=not reason, reason=reason,
                    warning="" if self.info_duration(info) else "長度未知，加入時會重新檢查。")

    async def resolve_options(self, guild, owner, query):
        permissions = self.bot.permissions.for_user(owner)
        player = self.preview_player(guild)
        self.addition_checks(player, owner, permissions)
        parsed = urlsplit(query)
        if (parsed.scheme and parsed.scheme not in ("http", "https")
                and ("://" in query or parsed.scheme in ("file", "data", "javascript", "spotify"))):
            raise APIError(400, "預覽僅接受 HTTP／HTTPS 網址或搜尋關鍵字。")
        valid_url = self.bot.downloader.get_url_or_none(query)
        # Split combined links into explicit choices, eliminating reaction prompts.
        playlist_id, video_id = get_compound_link_ids(query)
        if playlist_id:
            subjects = [("https://www.youtube.com/watch?v=" + video_id, False),
                        ("https://www.youtube.com/playlist?list=" + playlist_id, False)]
        elif valid_url:
            subjects = [(valid_url, False)]
        else:
            limit = getattr(permissions, "max_search_items", self.SEARCH_LIMIT)
            limit = min(self.SEARCH_LIMIT, limit) if limit > 0 else self.SEARCH_LIMIT
            subjects = [(f"{self.bot.config.default_search_service}{limit}:{query}", True)]
        results = []
        for subject, search in subjects:
            try:
                self.bot._do_song_blocklist_check(query)
                self.bot._do_song_blocklist_check(subject)
            except exceptions.MusicbotException:
                raise APIError(403, "查詢內容被封鎖清單擋下。") from None
            if "open.spotify.com" in subject.lower():
                if not self.bot.config.spotify_enabled:
                    raise APIError(403, "尚未啟用這個音樂來源。")
                if not Spotify.is_url_supported(subject):
                    raise APIError(400, "這個音樂來源網址格式不受支援。")
            info = await self.bot.downloader.extract_info(
                subject, download=False, process=True)
            if not info or ("entries" in info and not info.entry_count):
                raise APIError(404, "沒有找到可用的歌曲。")
            try:
                permissions.can_use_extractor(info.extractor)
            except exceptions.MusicbotException:
                raise APIError(403, "沒有使用這個來源解析器的權限。") from None
            if search:
                choices = info.get_entries_objects() if info.has_entries else [info]
                results.extend(dict(self.preview_track(item, permissions, extractor=info.extractor), kind="track")
                               for item in choices[:limit])
            elif info.has_entries:
                reason = ""
                try:
                    await self.bot._do_playlist_checks(
                        self.preview_player(guild), owner, info)
                except exceptions.MusicbotException:
                    count = info.playlist_count or info.entry_count
                    if not permissions.allow_playlists:
                        reason = "目前的權限不允許加入播放清單。"
                    elif permissions.max_playlist_length and count > permissions.max_playlist_length:
                        reason = f"清單超過首數限制（{count} > {permissions.max_playlist_length}）。"
                    else:
                        reason = f"加入清單將超過佇列上限（最多 {permissions.max_songs} 首）。"
                items = [self.preview_track(item, permissions, playlist=True, extractor=info.extractor)
                         for item in info.get_entries_objects()]
                eligible = sum(item["allowed"] for item in items)
                if not eligible and not reason:
                    reason = "清單內沒有通過封鎖或歌曲長度檢查的歌曲。"
                results.append({
                    "kind": "playlist", "title": info.title, "url": subject,
                    "thumbnail": public_url(info.thumbnail_url), "duration": 0,
                    "count": info.playlist_count or info.entry_count,
                    "checked_count": len(items), "eligible_count": eligible,
                    "entries": items[:self.PREVIEW_LIMIT],
                    "allowed": not reason, "reason": reason,
                    "warning": "僅列前 10 首；不合規歌曲將略過，加入時會重新解析及檢查。",
                })
            else:
                results.append(dict(self.preview_track(info, permissions), kind="track"))
        if not results:
            raise APIError(404, "沒有找到可用的歌曲。")
        return results

    async def resolve(self, request):
        data = await self.payload(request)
        query = self.query(data)
        guild, owner = self.guild_owner(request)
        # Admission is separate from mutation locks; timed-out extractions retain
        # their slot until the coroutine completes (executor work cannot be killed).
        if guild.id in self.resolve_tasks or len(self.resolve_tasks) >= 2:
            raise APIError(429, "解析仍在進行，請稍後再查詢。播放控制仍可使用。")
        task = asyncio.create_task(self.resolve_options(guild, owner, query))
        self.resolve_tasks[guild.id] = task
        def finished(done):
            self.resolve_tasks.pop(guild.id, None)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)
        try:
            results = await asyncio.wait_for(asyncio.shield(task), self.RESOLVE_TIMEOUT)
        except asyncio.TimeoutError:
            raise APIError(504, "解析逾時，請稍後再試。播放控制仍可使用。") from None
        except (APIError, exceptions.MusicbotException):
            raise
        except Exception:
            log.warning("Dashboard preview extraction failed")
            raise APIError(502, "無法解析這個來源，請檢查連結或稍後再試。") from None
        now = time.monotonic()
        self.previews = {key: value for key, value in self.previews.items()
                         if value["expires"] > now}
        for item in results:
            token = secrets.token_urlsafe(24)
            item["preview_id"] = token
            self.previews[token] = {
                "guild_id": guild.id, "owner_id": owner.id, "url": item["url"],
                "allowed": item["allowed"], "expires": now + self.PREVIEW_TTL,
                "status": "ready",
            }
        # Bounded memory even when many queries are made within the TTL.
        while len(self.previews) > 100:
            self.previews.pop(next(iter(self.previews)))
        return web.json_response({"results": results, "expires_in": self.PREVIEW_TTL})

    def confirmed_preview(self, data, guild, owner):
        if "preview_id" not in data:
            return None  # First-version API compatibility; the UI always confirms.
        token = data["preview_id"]
        preview = self.previews.get(token) if isinstance(token, str) else None
        if (not preview or preview["expires"] <= time.monotonic()
                or preview["guild_id"] != guild.id or preview["owner_id"] != owner.id):
            raise APIError(409, "預覽已過期或不屬於這個伺服器，請重新查詢。")
        if data["query"].strip() != preview["url"] or not preview["allowed"]:
            raise APIError(403, "這個選項無法加入，請重新查詢。")
        if preview["status"] == "done":
            return preview
        if preview["status"] != "ready":
            raise APIError(409, "這個選項已送出；請先查看佇列，需再次點播時請重新查詢。")
        return preview

    async def mutate(self, request):
        data = await self.payload(request)
        guild, owner = self.guild_owner(request)
        action = request.path.rsplit("/", 1)[-1]
        if request.method == "DELETE":
            action = "remove"
        if action == "play":
            query = self.query(data)
        elif action == "volume":
            self.integer(data, "volume", 1, 100)
        elif action == "repeat" and data.get("mode") not in ("off", "song", "all"):
            raise APIError(400, "重複模式必須是 off、song 或 all。")

        async with self.locks[guild.id]:
            preview = self.confirmed_preview(data, guild, owner) if action == "play" else None
            if preview and preview["status"] == "done":
                return web.json_response({"message": "這個選項已加入，未重複點播。",
                                          "state": self.snapshot(guild)})
            player, permissions, channel = await self.context(guild, owner, action)
            ssd = self.bot.server_data[guild.id]
            if action in ("remove", "move", "shuffle"):
                if not data.get("revision") or data["revision"] != revision(player):
                    raise APIError(409, "隊列已更新，請重新整理後再操作。")
            response = None
            if action == "play":
                if preview:
                    preview["status"] = "submitted"
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
            if preview:
                preview["status"] = "done"
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
        tasks = list(self.resolve_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
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
