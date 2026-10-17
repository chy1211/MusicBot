"""Optional HTTP dashboard with backwards-compatible owner or Discord identity."""
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
from collections import defaultdict, deque
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from aiohttp import web
from discord import ChannelType

from . import exceptions, write_path
from .constructs import ErrorResponse, Response
from .entry import LocalFilePlaylistEntry, URLPlaylistEntry
from .web_dashboard_lyrics import LyricsClient, clean_metadata
from .i18n import _D
from .spotify import Spotify
from .utils import get_compound_link_ids
from .web_dashboard_auth import DashboardAuth, USER_KEY
from .web_dashboard_events import DashboardEvents
from .web_dashboard_stats import PopularityStore
from .web_dashboard_library import DashboardLibrary
from .web_dashboard_admin import DashboardAdmin
from .web_dashboard_activity import capture, finish

ACTIVITY_KEY = web.RequestKey("dashboard_activity", object)

log = logging.getLogger(__name__)
STATIC = Path(__file__).with_name("web")
# Scoped to one command/task; native Discord play and other guilds are unaffected.
CONFIRMED_ENTRY_CHECK = ContextVar("dashboard_confirmed_entry_check", default=None)


@dataclass(frozen=True)
class DashboardConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8080
    shared_secret: str = field(default="", repr=False)

    auth_mode: str = "owner"
    public_url: str = ""
    discord_client_id: str = ""
    discord_client_secret: str = field(default="", repr=False)
    session_secret: str = field(default="", repr=False)
    session_hours: float = 168

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
        mode = parser.get("WebDashboard", "AuthMode", fallback="owner").strip().lower()
        if mode not in ("owner", "discord"):
            raise ValueError("Invalid dashboard AuthMode")
        # Ignore Discord-only options in owner mode for backwards compatibility.
        options = {}
        if mode == "discord":
            options = {
                "public_url": parser.get("WebDashboard", "PublicURL", fallback="").strip(),
                "discord_client_id": parser.get("WebDashboard", "DiscordClientID", fallback="").strip(),
                "discord_client_secret": parser.get("WebDashboard", "DiscordClientSecret", fallback="").strip(),
                "session_secret": parser.get("WebDashboard", "SessionSecret", fallback="").strip(),
                "session_hours": parser.getfloat("WebDashboard", "SessionHours", fallback=168),
            }
        return cls(True, host, port, parser.get(
            "WebDashboard", "SharedSecret", fallback="").strip(), auth_mode=mode, **options)


@dataclass
class ConfirmedEntryCheck:
    validate: object
    enqueued: bool = False

    def __call__(self, info):
        return self.validate(info)


class APIError(Exception):
    def __init__(self, status: int, message: str, details=None):
        super().__init__(message)
        self.status = status
        self.details = details or {}


def public_url(value) -> str:
    value = str(value or "")
    try:
        parts = urlsplit(value)
        _ = parts.port
        return value if (parts.scheme in ("http", "https") and parts.hostname
                         and not parts.username and not parts.password
                         and not any(ord(c) < 32 for c in value)) else ""
    except ValueError:
        return ""


def requester(entry, guild=None):
    meta = getattr(entry, "meta", None) or {}
    author = (getattr(entry, "author", None) or getattr(entry, "member", None)
              or meta.get("author") or meta.get("member"))
    if author is None:
        # Restored entries can lose their author when the member left the guild.
        return {"name": "點播者已離開或無法取得" if getattr(entry, "channel", None)
                else "自動播放", "avatar": ""}
    uid = getattr(author, "id", None)
    member = guild.get_member(uid) if guild is not None and uid is not None else None
    person = member or author
    return {"name": str(getattr(person, "display_name", None)
                        or getattr(person, "global_name", None)
                        or getattr(person, "name", None) or "點播者已離開或無法取得")[:128],
            "avatar": public_url(getattr(getattr(person, "display_avatar", None), "url", ""))}


def track(entry, guild=None, viewer=None) -> dict | None:
    if entry is None:
        return None
    return {
        "title": str(entry.title),
        "url": public_url(entry.url),
        "thumbnail": public_url(getattr(entry, "thumbnail_url", "")),
        "duration": float(getattr(entry, "duration", 0) or 0),
        "requester": requester(entry, guild),
        "mine": bool(viewer is not None and getattr(viewer, "id", None) is not None
                     and getattr((getattr(entry, "author", None) or getattr(entry, "member", None)
                                  or (getattr(entry, "meta", None) or {}).get("author")
                                  or (getattr(entry, "meta", None) or {}).get("member")), "id", None) == viewer.id),
    }


def denial_text(message):
    """Dashboard-only Traditional Chinese fallbacks; upstream messages stay intact."""
    mappings = (
        ("You do not have the permission to remove", "你只能刪除自己點播的歌曲；刪除他人的歌曲需要移除權限。"),
        ("You have reached your enqueued song limit", "已達到可排入佇列的歌曲數量上限。"),
        ("The playlist entries will exceed", "加入清單將超過可排入佇列的歌曲數量上限。"),
        ("Queue limit reached", "已達到可排入佇列的歌曲數量上限。"),
        ("Song duration exceeds limit", "歌曲超過你的歌曲長度限制。"),
        ("You are not allowed to request playlists", "目前的權限不允許加入播放清單。"),
        ("Playlist has too many entries", "播放清單超過首數限制。"),
        ("Karaoke mode is enabled", "目前為卡拉 OK 模式，沒有點歌權限。"),
        ("This command is not allowed", "你的權限群組不允許使用這個指令。"),
        ("This command requires you to be in a Voice", "請先加入 Discord 語音頻道。"),
        ("Invalid entry number", "歌曲位置已失效，請重新整理佇列。"),
        ("You must be in the same", "請先加入機器人所在的語音頻道。"),
        ("You cannot use this command", "目前沒有使用這個指令的權限。"),
    )
    for prefix, translated in mappings:
        if message.startswith(prefix):
            return translated
    # Do not expose raw extractor details/URLs through a rejection.
    return message if any("\u3400" <= c <= "\u9fff" for c in message) else "機器人無法完成操作，請確認權限、語音頻道與歌曲限制。"


def revision(player) -> str:
    # Object identities distinguish duplicate URLs and identical new queues.
    identities = [id(player), id(player.current_entry)]
    identities.extend(id(entry) for entry in player.playlist.entries)
    return hashlib.sha256(str(identities).encode()).hexdigest()


from .web_dashboard_undo import DashboardUndo

class Dashboard(DashboardAuth, DashboardEvents, DashboardLibrary, DashboardAdmin, DashboardUndo):
    def __init__(self, bot, config: DashboardConfig):
        self.bot = bot
        self.config = config
        self.runner = None
        self.site = None
        self.locks = defaultdict(asyncio.Lock)
        self.resolve_tasks = {}
        self.previews = {}
        self.rate_limits = {}
        self.lyrics_rate_limits = {}
        self.lyrics_client = LyricsClient()
        self.recent_history = defaultdict(lambda: deque(maxlen=50))
        self.history_marker = secrets.token_urlsafe(16)
        self.history_last_source = {}
        self.last_requested_guild = {}
        self.activities = defaultdict(lambda: deque(maxlen=100))
        self.queue_arrivals = defaultdict(list)
        self.init_auth()
        self.app = web.Application(
            middlewares=[self.guard], client_max_size=16 * 1024)
        self.init_events()
        self.init_library()
        self.init_admin()
        self.init_undo()
        self.popularity_store = PopularityStore(write_path("data/web_dashboard/stats"))
        async def cleanup_popularity(_app):
            try:
                await self.popularity_store.close()
            except Exception:
                log.warning("Dashboard popularity final flush failed")
        self.app.on_cleanup.append(cleanup_popularity)

        self.app.router.add_get("/", self.index)
        for path in ("manifest.webmanifest", "sw.js", "pwa.js", "offline.html",
                     "icon-192.png", "icon-512.png", "apple-touch-icon.png"):
            self.app.router.add_get("/" + path, self.pwa_asset)
        self.app.router.add_get("/favicon.svg", self.favicon)
        self.app.router.add_get("/favicon.ico", self.favicon)
        self.app.router.add_get("/auth/session", self.auth_session)
        self.app.router.add_get("/auth/login", self.auth_login)
        self.app.router.add_get("/auth/callback", self.auth_callback)
        self.app.router.add_post("/auth/logout", self.auth_logout)
        self.app.router.add_get("/dashboard.css", self.asset)
        self.app.router.add_get("/dashboard.js", self.asset)
        self.app.router.add_get("/library.js", self.asset)
        self.app.router.add_get("/admin.js", self.asset)
        self.app.router.add_get("/permissions.js", self.asset)
        self.app.router.add_get("/popular.js", self.asset)
        self.app.router.add_get("/api/guilds", self.guilds)
        self.app.router.add_get("/api/guilds/{guild_id}/state", self.state)
        self.app.router.add_get("/api/guilds/{guild_id}/listeners", self.listeners)
        self.app.router.add_get("/api/guilds/{guild_id}/activity", self.activity)
        self.app.router.add_get("/api/guilds/{guild_id}/events", self.events,
                                name="dashboard_events", allow_head=False)
        self.app.router.add_get("/api/guilds/{guild_id}/history", self.history)
        self.app.router.add_get("/api/guilds/{guild_id}/popular", self.popular)
        self.app.router.add_get("/api/guilds/{guild_id}/lyrics", self.lyrics)
        self.app.router.add_post(
            "/api/guilds/{guild_id}/resolve", self.resolve)
        for action in ("play", "playnext", "seek", "pause", "resume", "skip", "volume", "repeat"):
            self.app.router.add_post(
                "/api/guilds/{guild_id}/" + action, self.mutate)
        self.app.router.add_post(
            "/api/guilds/{guild_id}/queue/shuffle", self.mutate)
        self.app.router.add_post(
            "/api/guilds/{guild_id}/queue/move", self.mutate)
        self.app.router.add_delete(
            "/api/guilds/{guild_id}/queue/{position}", self.mutate)

    def authenticate(self, request):
        if not self.discord_auth:
            return
        user = self.session_user(request)
        if user is None:
            raise APIError(401, "請先用 Discord 登入。")
        request[USER_KEY] = user

    def request_action(self, request):
        if request.path == "/api/guilds":
            return "guilds"
        if request.method == "DELETE" and "position" in request.match_info:
            return "remove"
        action = request.path.rsplit("/", 1)[-1]
        return action if action in {
            "state", "listeners", "activity", "events", "history", "lyrics", "resolve", "play", "playnext", "seek", "pause", "resume", "skip",
            "volume", "repeat", "move", "shuffle", "logout", "login", "callback",
        } else "unknown"

    @web.middleware
    async def guard(self, request, handler):
        api = request.path.startswith("/api/")
        logout = request.path == "/auth/logout"
        events = request.method == "GET" and request.match_info.route.name == "dashboard_events"
        try:
            if self.discord_auth and (api or logout):
                # Authentication first: all unauthenticated APIs are uniformly 401.
                self.authenticate(request)
            elif self.discord_auth:
                user = self.session_user(request)
                if user is not None:
                    request[USER_KEY] = user
            if self.discord_auth and (api or request.path.startswith("/auth/")):
                # Never infer trust from Forwarded headers supplied by a client.
                if request.host.lower() != urlsplit(self.public_origin).netloc.lower():
                    raise APIError(403, "公開網址不符，請從控制台網址操作。")
                origin = request.headers.get("Origin")
                if origin and origin != self.public_origin:
                    raise APIError(403, "不允許跨網站操作。")
            if api or logout:
                if events:
                    if request.headers.get("Sec-Fetch-Site") not in (None, "same-origin"):
                        raise APIError(403, "不允許跨網站即時連線。")
                    # EventSource cannot send Bearer headers. Never put the secret
                    # in a URL or silently bypass legacy owner protection.
                    if not self.discord_auth and self.config.shared_secret:
                        raise APIError(403, "共享密鑰模式請使用一般更新。")
                elif request.headers.get("X-MusicBot-Dashboard") != "1":
                    raise APIError(403, "請從音樂控制台操作。")
                origin = request.headers.get("Origin")
                if (not self.discord_auth and origin
                        and urlsplit(origin).netloc != request.host):
                    raise APIError(403, "不允許跨網站操作。")
                # Discord sessions replace the owner-mode optional shared secret.
                if not self.discord_auth and self.config.shared_secret:
                    token = request.headers.get("Authorization", "")
                    expected = "Bearer " + self.config.shared_secret
                    if not hmac.compare_digest(token.encode(), expected.encode()):
                        raise APIError(401, "共享密鑰錯誤或尚未填寫。")
                if api and (not self.bot.is_ready() or not self.bot.init_ok
                            or self.bot.logout_called):
                    raise APIError(503, "機器人尚未就緒，請稍後再試。")
            response = await handler(request)
        except APIError as exc:
            response = web.json_response({"error": str(exc), **exc.details}, status=exc.status)
        except exceptions.MusicbotException as exc:
            try:
                guild_id = request.match_info.get("guild_id", "")
                ssd = self.bot.server_data.get(int(guild_id)) if guild_id.isdigit() else None
                message = denial_text(_D(exc.message, ssd) % exc.fmt_args)
                response = web.json_response(
                    {"error": "機器人拒絕操作：" + message},
                    status=403 if isinstance(exc, exceptions.PermissionsError) else 400)
            except Exception as formatting_error:
                log.error("Dashboard error formatting failed (%s)", type(formatting_error).__name__)
                response = web.json_response(
                    {"error": "操作失敗，已記錄錯誤。"}, status=500)
        except web.HTTPRedirection as exc:
            response = exc
        except web.HTTPException as exc:
            if (exc.status == 404 and request.method == "GET"
                    and request.path not in ("/api", "/auth")
                    and not request.path.startswith(("/api/", "/auth/", "/static/", "/assets/"))
                    and not Path(request.path).suffix):
                response = web.HTTPFound(location="/")
            else:
                response = web.json_response(
                    {"error": "請求內容、路徑或方法不正確。"}, status=exc.status)
        except Exception as exc:
            # Exceptions can contain URLs, authorization codes or provider tokens.
            log.error("Dashboard request failed (%s)", type(exc).__name__)
            response = web.json_response(
                {"error": "操作失敗，已記錄錯誤；請重新整理後再試。"}, status=500)
        if api or logout or request.path in ("/auth/login", "/auth/callback"):
            uid = (request.get(USER_KEY) or {}).get("id")
            if uid is None and not self.discord_auth:
                uid = str(self.bot.config.owner_id)
            raw_gid = request.match_info.get("guild_id", "")
            gid = raw_gid if raw_gid.isascii() and raw_gid.isdigit() and len(raw_gid) <= 20 else "-"
            log.info("Dashboard operation user=%s guild=%s action=%s status=%d",
                     uid or "-", gid, self.request_action(request), response.status)
        if api and request.method in ("POST", "DELETE") and self.request_action(request) in {
                "play", "playnext", "seek", "pause", "resume", "skip", "volume", "repeat", "remove", "move", "shuffle"}:
            try:
                value = request.get(ACTIVITY_KEY)
                if value is None:
                    guild, member = self.guild_owner(request)
                    value = capture(self, guild, member, self.request_action(request), "web")
                finish(value, response.status < 400)
            except Exception as exc:
                log.warning("Dashboard activity failed (%s)", type(exc).__name__)
        response.headers.update({
            "Cache-Control": "no-cache" if events and response.prepared else "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'self'; img-src 'self' https: http:; "
                "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"),
        })
        if isinstance(response, web.HTTPException):
            raise response
        return response

    async def pwa_asset(self, request):
        name = request.path.lstrip("/")
        types = {".webmanifest": "application/manifest+json", ".png": "image/png",
                 ".html": "text/html", ".js": "text/javascript"}
        return web.Response(body=(STATIC / name).read_bytes(),
                            content_type=types[Path(name).suffix])

    async def favicon(self, _request):
        return web.Response(text=(STATIC / "favicon.svg").read_text(encoding="utf-8"),
                            content_type="image/svg+xml")

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
        uid = int(request[USER_KEY]["id"]) if self.discord_auth else self.bot.config.owner_id
        owner = guild.get_member(uid)
        if owner is None:
            raise APIError(403, "你不是這個伺服器的成員。" if self.discord_auth
                           else "OwnerID 本人不在這個伺服器。")
        self.check_blocked(owner)
        return guild, owner

    def check_blocked(self, member):
        if not self.discord_auth or member.id == self.bot.config.owner_id:
            return
        blocklist = getattr(self.bot.config, "user_blocklist", None)
        if blocklist is not None and blocklist.is_blocked(member):
            raise APIError(403, "你已被機器人的使用者封鎖清單擋下。")

    async def guilds(self, request):
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
        item = track(entry, guild)
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
        item["played_at"] = moment
        self.recent_history[guild.id].appendleft(item)

    async def history(self, request):
        guild, _member = self.guild_owner(request)
        return web.json_response(self.history_snapshot(guild))

    def history_snapshot(self, guild):
        rows = []
        for item in self.recent_history.get(guild.id, ()):
            public = {key: item[key] for key in
                      ("title", "url", "thumbnail", "duration", "played_at")}
            person = guild.get_member(item["requester_id"]) if item["requester_id"] else None
            public["requester"] = requester(SimpleNamespace(
                author=person, channel=True if item["requested"] else None), guild)
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
                    url = public_url(url)
                    if url and url not in known and len(rows) < 50:
                        rows.append({"title": "較早播放的歌曲（僅保留來源連結）",
                                     "url": url, "thumbnail": "", "duration": 0,
                                     "played_at": None,
                                     "requester": {"name": "點播者無法取得", "avatar": ""}})
                        known.add(url)
        elif getattr(config, "enable_queue_history_global", False):
            # Never disclose the global URL pool to a member of one guild.
            source = "dashboard_memory_global_history_unscoped"
        return {"history": rows[:50], "source": source, "resets_on_restart": True}

    LYRICS_REQUESTS_PER_MINUTE = 12

    def lyrics_rate_limit(self, member):
        now = time.monotonic()
        self.lyrics_rate_limits = {
            uid: [stamp for stamp in stamps if stamp > now - 60]
            for uid, stamps in self.lyrics_rate_limits.items()
            if stamps and stamps[-1] > now - 60}
        stamps = self.lyrics_rate_limits.setdefault(member.id, [])
        if len(stamps) >= self.LYRICS_REQUESTS_PER_MINUTE:
            raise APIError(429, "歌詞查詢過於頻繁，每人每分鐘最多 12 次，請稍後再試。")
        if len(self.lyrics_rate_limits) > 1024:
            self.lyrics_rate_limits.pop(next(iter(self.lyrics_rate_limits)))
        stamps.append(now)

    async def lyrics(self, request):
        guild, member = self.guild_owner(request)
        query = request.query.get("query", "").strip()
        if len(query) > 160 or any(ord(char) < 32 for char in query):
            raise APIError(400, "歌詞搜尋最多 160 字，且不可包含控制字元。")
        self.lyrics_rate_limit(member)
        player = self.bot.get_player_in(guild)
        entry = getattr(player, "current_entry", None)
        if entry is None:
            raise APIError(409, "目前沒有播放中的歌曲。")
        info = getattr(entry, "info", {}) or {}
        title, artist = clean_metadata(entry.title, info.get("artist") or info.get("creator") or "")
        track_key = hashlib.sha256(str((entry.url, entry.title, entry.duration)).encode()).hexdigest()
        value = await self.lyrics_client.lookup(title, artist, entry.duration, query=query)
        # An expired session/removed member must not receive data after a slow lookup.
        if self.discord_auth:
            self.authenticate(request)
        self.guild_owner(request)
        return web.json_response(dict(value, track_key=track_key))

    @staticmethod
    def track_token(player):
        entry = getattr(player, "current_entry", None)
        return (hashlib.sha256(str((id(player), id(entry))).encode()).hexdigest()
                if entry is not None else "")

    def control_capabilities(self, guild, viewer):
        """Viewer-only hints; mutation handlers still authorize every request."""
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
        community = {"capabilities": self.control_capabilities(guild, viewer),
                     "listeners": self.listener_snapshot(guild),
                     "activity": self.activity_snapshot(guild)}
        player = self.bot.get_player_in(guild)
        if player is None:
            return {**community, "guild_id": str(guild.id), "status": "disconnected",
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
        guild, member = self.guild_owner(request)
        period = request.query.get("period", "7")
        if period not in ("7", "30", "all"):
            raise APIError(400, "統計期間只接受近 7 天、近 30 天或全部。")
        try:
            tracks = await self.popularity_store.top(guild, period)
        except Exception:
            raise APIError(503, "暫時無法讀取熱門點播，請稍後再試。") from None
        # Recheck membership after the asynchronous read.
        self.guild_owner(request)
        return web.json_response({"period": period, "tracks": tracks})

    def note_queue_entry(self, guild, entry):
        """Observe member requests/insertion order; never mutate the playlist."""
        author = getattr(entry, "author", None)
        if (author is not None and getattr(author, "id", None) is not None
                and not getattr(author, "bot", False)
                and not getattr(entry, "from_auto_playlist", False)):
            # Runtime-only identity is never returned to another viewer.
            # Bound the cache and preserve recency of active members.
            self.last_requested_guild.pop(author.id, None)
            self.last_requested_guild[author.id] = guild.id
            while len(self.last_requested_guild) > 5000:
                self.last_requested_guild.pop(next(iter(self.last_requested_guild)))
        player = self.bot.get_player_in(guild)
        entries = list(player.playlist.entries) if player else []
        live = {id(item) for item in entries}
        known = self.queue_arrivals[guild.id]
        known[:] = [key for key in known if key in live and key != id(entry)]
        known_ids = set(known)
        known.extend(id(item) for item in entries
                     if id(item) != id(entry) and id(item) not in known_ids)
        if id(entry) in live:
            known.append(id(entry))

    def channel_for(self, guild, owner):
        bound = self.bot.config.bound_channels
        has_bound = any(c.id in bound for c in guild.channels)
        restrict = bool(bound) and (has_bound or not self.bot.config.unbound_servers)
        player = self.bot.get_player_in(guild)
        current = getattr(player, "current_entry", None)
        # Queue order can be moved/shuffled. Object identity insertion order is
        # tracked below, so "latest requested" does not mean "last in queue".
        entries = list(player.playlist.entries) if player else []
        known = self.queue_arrivals[guild.id]
        live = {id(entry) for entry in entries}
        known[:] = [key for key in known if key in live]
        known_ids = set(known)
        known.extend(id(entry) for entry in entries if id(entry) not in known_ids)
        by_id = {id(entry): entry for entry in entries}
        latest = by_id.get(known[-1]) if known else None
        voice = getattr(getattr(owner, "voice", None), "channel", None)
        candidates = ([getattr(current, "channel", None), getattr(latest, "channel", None)]
                      + [guild.get_channel(cid) for cid in sorted(bound)]
                      + [guild.system_channel] + list(guild.text_channels) + [voice])
        # An older web request may itself have stored a voice chat as
        # entry.channel. Voice chat remains the last fallback in that case too.
        preferred = [channel for channel in candidates[:-1]
                     if channel is not None
                     and getattr(channel, "type", None) not in (ChannelType.voice, ChannelType.stage_voice)
                     and getattr(channel, "id", None) != getattr(voice, "id", None)]
        candidates = preferred + [voice]
        seen = set()
        for channel in candidates:
            if channel is not None and channel.id in seen:
                continue
            if channel is not None:
                seen.add(channel.id)
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

    def command_permission(self, member, permissions, command, sub=""):
        if (member.id != self.bot.config.owner_id
                and not permissions.can_use_command(command, sub)):
            raise APIError(403, "沒有使用這個指令的權限。")

    def bot_voice_channel(self, guild):
        voice = getattr(getattr(guild, "me", None), "voice", None)
        if voice and voice.channel:
            return voice.channel
        player = self.bot.get_player_in(guild)
        client = getattr(player, "voice_client", None)
        if client and getattr(client, "is_connected", lambda: True)():
            return client.channel
        return None

    def voice_permission(self, guild, member, permissions, command):
        if not member.voice or not member.voice.channel:
            raise APIError(409, "請先加入 Discord 語音頻道。")
        bot_channel = self.bot_voice_channel(guild)
        if bot_channel is not None:
            if bot_channel.id != member.voice.channel.id:
                raise APIError(403, "你不在機器人的語音頻道。")
        elif command not in ("play", "playnext"):
            raise APIError(409, "機器人尚未加入語音頻道。")
        elif not permissions.summonplay:
            raise APIError(403, "沒有 summonplay 權限，無法把機器人叫進語音頻道。")

    async def context(self, guild, owner, command, sub=""):
        permissions = self.bot.permissions.for_user(owner)
        self.command_permission(owner, permissions, command, sub)
        if self.discord_auth or command in ("seek", "playnext"):
            self.voice_permission(guild, owner, permissions, command)
        elif not owner.voice or not owner.voice.channel:
            raise APIError(409, "請先用 OwnerID 本人加入 Discord 語音頻道。")
        if permissions.ignore_non_voice and command in permissions.ignore_non_voice:
            await self.bot._check_ignore_non_voice(
                SimpleNamespace(guild=guild, author=owner))
        channel = self.channel_for(guild, owner)
        player = await self.bot.get_player(
            owner.voice.channel, create=permissions.summonplay if command in ("play", "playnext") else False)
        if self.discord_auth:
            # Membership, roles and voice may change while a connection is awaited.
            owner = guild.get_member(owner.id)
            if owner is None:
                raise APIError(403, "你不是這個伺服器的成員。")
            self.check_blocked(owner)
            permissions = self.bot.permissions.for_user(owner)
            self.command_permission(owner, permissions, command, sub)
            self.voice_permission(guild, owner, permissions, command)
            channel = self.channel_for(guild, owner)
            if not player or not getattr(player, "voice_client", None):
                raise APIError(409, "機器人尚未加入語音頻道。")
        return player, permissions, channel

    @staticmethod
    def repeat_commands(player, mode):
        subs = []
        if player.repeatsong and mode != "song":
            subs.append("off")
        if player.loopqueue and mode != "all":
            subs.append("all")
        if mode == "song" and not player.repeatsong:
            subs.append("on")
        if mode == "all" and not player.loopqueue:
            subs.append("all")
        return subs

    USER_REQUESTS_PER_MINUTE = 12

    def user_rate_limit(self, member):
        if not self.discord_auth:
            return
        now = time.monotonic()
        self.rate_limits = {uid: [t for t in times if t > now - 60]
                            for uid, times in self.rate_limits.items()
                            if times and times[-1] > now - 60}
        times = self.rate_limits.setdefault(member.id, [])
        if len(times) >= self.USER_REQUESTS_PER_MINUTE:
            raise APIError(429, "點歌與解析過於頻繁，每人每分鐘最多 12 次，請稍後再試。")
        times.append(now)

    @staticmethod
    def integer(data, key, minimum, maximum):
        value = data.get(key)
        if type(value) is not int or not minimum <= value <= maximum:
            raise APIError(400, f"{key} 必須是 {minimum} 到 {maximum} 之間的整數。")
        return value

    RESOLVE_TIMEOUT = 20
    PREVIEW_TTL = 300
    PREVIEW_LIMIT = 200
    BATCH_TIMEOUT = 120
    SONG_TIMEOUT = 20
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
        if (not self.discord_auth and owner.id != self.bot.config.owner_id
                and not permissions.can_use_command("play")):
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

    async def resolve_options(self, guild, owner, query, action="play"):
        permissions = self.bot.permissions.for_user(owner)
        player = self.preview_player(guild)
        self.addition_checks(player, owner, permissions)
        if self.discord_auth:
            self.command_permission(owner, permissions, action, query.split()[0])
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
            imported = None
            from .web_dashboard_imports import source_url
            try:
                canonical, kind = source_url(subject)
            except APIError:
                canonical = None
                # Never resolve account-private aliases through bot cookies.
                if urlsplit(subject).hostname in ("youtube.com", "www.youtube.com", "music.youtube.com", "m.youtube.com") and any(
                        item in ("WL", "LL", "LM") for item in parse_qs(urlsplit(subject).query).get("list", [])):
                    raise
            if canonical:
                imported = await self.import_source(canonical, kind)
                extractor = "spotify:musicbot" if kind == "spotify" else "youtube"
                from .downloader import YtdlpResponseDict
                info = YtdlpResponseDict({"title": imported["title"], "extractor": extractor,
                    "playlist_count": imported["count"], "entries": [
                        dict(item, webpage_url=item["url"], extractor=extractor) for item in imported["tracks"]]})
                subject = canonical
            else:
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
                count = max(info.playlist_count or 0, info.entry_count)
                reason = ("下一首播放目前只支援單曲，請選取單曲來源。"
                          if action == "playnext" else self.playlist_restriction(permissions, count))
                # Only retain/check the bounded subset we actually offer for selection.
                children = info.get_entries_objects()[:self.PREVIEW_LIMIT]
                items = [dict(self.preview_track(item, permissions, playlist=True,
                                                extractor=info.extractor),
                              item_id=str(i))
                         for i, item in enumerate(children, 1)]
                eligible = sum(item["allowed"] for item in items)
                if not eligible and not reason:
                    reason = "清單內沒有通過封鎖或歌曲長度檢查的歌曲。"
                results.append({
                    "kind": "playlist", "title": info.title, "url": subject,
                    "source_url": imported["source_url"] if imported else "",
                    "source_type": imported["source_type"] if imported else "",
                    "count_is_minimum": imported.get("count_is_minimum", False) if imported else False,
                    "thumbnail": public_url(info.thumbnail_url), "duration": 0,
                    "count": count, "checked_count": len(items), "eligible_count": eligible,
                    "entries": items, "allowed": not reason, "reason": reason,
                    "truncated": count > len(items), "limit": self.PREVIEW_LIMIT,
                    "warning": (f"來源至少 {count} 首、目前只讀得到 {len(items)} 首。" if imported and imported.get("count_is_minimum") else "") +
                               (f"僅提供前 {self.PREVIEW_LIMIT} 首，超過的歌曲未加入預覽。" if count > len(items) else "") +
                               "確認時會逐首重新檢查；佇列額滿時回報部分成功。",
                })
            else:
                results.append(dict(self.preview_track(info, permissions), kind="track"))
        if not results:
            raise APIError(404, "沒有找到可用的歌曲。")
        return results

    async def resolve(self, request):
        data = await self.payload(request)
        query = self.query(data)
        action = data.get("action", "play")
        if action not in ("play", "playnext"):
            raise APIError(400, "點歌用途必須是 play 或 playnext。")
        guild, owner = self.guild_owner(request)
        self.user_rate_limit(owner)
        # Admission is separate from mutation locks; timed-out extractions retain
        # their slot until the coroutine completes (executor work cannot be killed).
        if guild.id in self.resolve_tasks or len(self.resolve_tasks) >= 2:
            raise APIError(429, "解析仍在進行，請稍後再查詢。播放控制仍可使用。")
        task = asyncio.create_task(self.resolve_options(guild, owner, query, action))
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
        if self.discord_auth:
            self.authenticate(request)
            guild, owner = self.guild_owner(request)
            self.command_permission(owner, self.bot.permissions.for_user(owner), action, query.split()[0])
        await self.issue_previews(guild, owner, results, query, action)
        return web.json_response({"results": results, "expires_in": self.PREVIEW_TTL})

    async def issue_previews(self, guild, owner, results, query, action):
        now = time.monotonic()
        self.previews = {key: value for key, value in self.previews.items()
                         if value.get("retain_until", value["expires"]) > now}
        for item in results:
            token = secrets.token_urlsafe(24)
            item["preview_id"] = token
            self.previews[token] = {
                "guild_id": guild.id, "owner_id": owner.id, "url": item["url"],
                "allowed": item["allowed"], "expires": now + self.PREVIEW_TTL,
                "retain_until": now + 3600, "original_query": query, "action": action,
                "status": "ready", "kind": item["kind"],
                "count": item.get("count", 1),
                "entries": [dict(child) for child in item.get("entries", [])],
            }
            if item.get("source_url"):
                value = await self.playlist_store.transact(owner.id)
                item["save_revision"] = value["revision"]
                self.import_previews[token] = {
                    "owner_id": owner.id, "guild_id": guild.id, "playlist_id": None,
                    "revision": value["revision"], "expires": now + self.PREVIEW_TTL,
                    "tracks": [dict(child) for child in item["entries"]],
                    "source_url": item["source_url"], "source_type": item["source_type"]}
        # Bounded memory even when many queries are made within the TTL.
        while len(self.previews) > 100:
            self.previews.pop(next(iter(self.previews)))
        return results

    def confirmed_preview(self, data, guild, owner):
        if "preview_id" not in data:
            return None  # First-version API compatibility; the UI always confirms.
        token = data["preview_id"]
        preview = self.previews.get(token) if isinstance(token, str) else None
        if (not preview or preview.get("retain_until", preview["expires"]) <= time.monotonic()
                or preview["guild_id"] != guild.id or preview["owner_id"] != owner.id):
            raise APIError(409, "預覽已過期或不屬於這個伺服器，請重新查詢。")
        if data["query"].strip() != preview["url"] or not preview["allowed"]:
            raise APIError(403, "這個選項無法加入，請重新查詢。")
        if preview.get("kind") == "playlist":
            selected = data.get("selected_items")
            if selected is None:
                selected = [item["item_id"] for item in preview["entries"] if item["allowed"]]
            if (not isinstance(selected, list) or not selected
                    or len(selected) > self.PREVIEW_LIMIT
                    or any(not isinstance(i, str) for i in selected)
                    or len(set(selected)) != len(selected)):
                raise APIError(400, "請選取至少一首歌曲，項目不可重複。")
            available = {item["item_id"]: item for item in preview["entries"]}
            if any(i not in available or (not available[i]["allowed"] and preview["status"] != "done") for i in selected):
                raise APIError(403, "選取的歌曲不在這份預覽內，或已被限制擋下。")
            canonical = [item["item_id"] for item in preview["entries"]
                         if item["item_id"] in selected]
            if preview["status"] == "done" and canonical != preview["selection"]:
                raise APIError(409, "這份預覽已完成另一組選擇，請重新查詢。")
            data["selected_items"] = canonical
        elif "selected_items" in data:
            raise APIError(400, "單曲預覽不接受清單項目。")
        if preview["status"] == "done":
            return preview
        if preview["status"] != "ready":
            raise APIError(409, "這個選項已送出；請先查看佇列，需再次點播時請重新查詢。")
        return preview

    async def renew_preview(self, request, data, preview, guild, owner, action):
        if preview["status"] != "ready" or preview["expires"] > time.monotonic():
            return
        query = preview.get("original_query")
        if not query:
            raise APIError(409, "預覽已過期，請重新搜尋。")
        self.user_rate_limit(owner)
        if guild.id in self.resolve_tasks or len(self.resolve_tasks) >= 2:
            raise APIError(429, "解析仍在進行，請稍後再試。")
        task = asyncio.create_task(self.resolve_options(guild, owner, query, action))
        self.resolve_tasks[guild.id] = task
        task.add_done_callback(lambda done: self.resolve_tasks.pop(guild.id, None))
        try:
            results = await asyncio.wait_for(task, self.RESOLVE_TIMEOUT)
        except asyncio.TimeoutError:
            raise APIError(504, "重新搜尋逾時，請稍後再試。") from None
        if self.discord_auth: self.authenticate(request)
        guild, owner = self.guild_owner(request)
        await self.issue_previews(guild, owner, results, query, action)
        from .web_dashboard_media import media_url
        def same(a, b):
            return (media_url(a) or public_url(a)) == (media_url(b) or public_url(b))
        match = next((item for item in results if item["kind"] == preview["kind"]
                      and same(item["url"], preview["url"])), None)
        if match is None or (preview["kind"] == "track" and not match["allowed"]):
            raise APIError(409, "預覽已過期，這首目前搜尋不到，請重新搜尋",
                           {"results": results, "expires_in": self.PREVIEW_TTL})
        if preview["kind"] == "playlist":
            refreshed = []
            for old in preview["entries"]:
                new = next((item for item in match["entries"] if same(item["url"], old["url"])), None)
                refreshed.append(dict(new, item_id=old["item_id"]) if new else
                                 dict(old, allowed=False, reason="這首已不在來源中。"))
            preview["entries"] = refreshed
            preview["count"] = match["count"]
            preview["fresh_reason"] = match["reason"]
        preview["expires"] = time.monotonic() + self.PREVIEW_TTL

    @staticmethod
    def playlist_restriction(permissions, count):
        # AllowPlaylists applies to the whole preview, even a one-item selection.
        if not permissions.allow_playlists:
            return "目前的權限不允許加入播放清單。"
        if permissions.max_playlist_length and count > permissions.max_playlist_length:
            return f"清單超過首數限制（{count} > {permissions.max_playlist_length}）。"
        return ""

    async def play_selection(self, request, data, preview, guild, owner):
        permissions = self.bot.permissions.for_user(owner)
        reason = self.playlist_restriction(permissions, preview["count"])
        if reason:
            raise APIError(403, reason)
        chosen = [item for item in preview["entries"]
                  if item["item_id"] in data["selected_items"]]
        preview["status"], preview["selection"] = "submitted", data["selected_items"]
        results = []
        first_response = None
        deadline = time.monotonic() + self.BATCH_TIMEOUT
        for item in chosen:
            error = ""
            success = False
            def validate(info):
                # Called inside _cmd_play AFTER extraction and before queue mutation.
                candidate = info
                if info.has_entries:
                    # Native Spotify processing searches for one matching video.
                    # Downloader merges that video into the parent but retains
                    # the one-child search entries. Accept only its already
                    # flattened video shape; genuine/nested playlists still fail.
                    source = urlsplit(item["url"])
                    parts = source.path.strip("/").split("/")
                    children = info.get_entries_objects()
                    spotify_single = (
                        source.hostname == "open.spotify.com" and len(parts) == 2
                        and parts[0] == "track" and info.ytdl_type == "video"
                        and len(children) == 1 and not children[0].has_entries
                        and children[0].extractor == info.extractor
                    )
                    if not spotify_single:
                        raise APIError(403, "選取的單曲解析成播放清單，請重新查詢。")
                    candidate = children[0]
                if self.discord_auth:
                    self.authenticate(request)
                current_guild, member = self.guild_owner(request)
                perms = self.bot.permissions.for_user(member)
                self.command_permission(member, perms, "play", item["url"])
                if self.discord_auth:
                    self.voice_permission(current_guild, member, perms, "play")
                why = self.playlist_restriction(perms, preview["count"])
                player = self.bot.get_player_in(current_guild)
                self.addition_checks(player, member, perms)
                why = (why or self.restriction(info, perms, playlist=True)
                       or self.restriction(candidate, perms, playlist=True))
                if why:
                    raise APIError(403, why)
                return perms
            check = ConfirmedEntryCheck(validate)
            try:
                if not item.get("allowed", True):
                    raise APIError(403, item.get("reason") or "歌曲目前不允許加入。")
                if preview.get("fresh_reason"):
                    raise APIError(403, preview["fresh_reason"])
                if self.discord_auth:
                    self.authenticate(request)
                guild, owner = self.guild_owner(request)
                player, permissions, channel = await self.context(
                    guild, owner, "play", item["url"])
                reason = self.playlist_restriction(permissions, preview["count"])
                if reason:
                    raise APIError(403, reason)
                self.addition_checks(player, owner, permissions)
                self.bot._do_song_blocklist_check(preview["url"])
                self.bot._do_song_blocklist_check(item["url"])
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                token = CONFIRMED_ENTRY_CHECK.set(check)
                try:
                    response = await asyncio.wait_for(self.bot.cmd_play(
                        message=None, player=player, channel=channel, guild=guild,
                        author=owner, permissions=permissions, leftover_args=[],
                        song_url=item["url"]), min(self.SONG_TIMEOUT, remaining))
                finally:
                    CONFIRMED_ENTRY_CHECK.reset(token)
                if isinstance(response, ErrorResponse):
                    raise APIError(409, denial_text(response.description or ""))
                if first_response is None:
                    first_response = response
                success = True
            except APIError as exc:
                error = str(exc)
            except exceptions.MusicbotException as exc:
                error = denial_text(_D(exc.message, self.bot.server_data[guild.id]) % exc.fmt_args)
            except asyncio.TimeoutError:
                error = "加入逾時，這份預覽不會重複送出，請先查看佇列。"
            except Exception as exc:
                log.warning("Dashboard selected play failed (%s)", type(exc).__name__)
                error = "加入失敗，請先查看佇列後再重新查詢。"
            # The command records the actual enqueue before preparing its response.
            # Other Discord/web requests cannot be mistaken for this selection.
            added = success or check.enqueued
            results.append({"item_id": item["item_id"], "title": item["title"],
                            "added": bool(added), "reason": error})
        added = sum(item["added"] for item in results)
        summary = {"added": added, "skipped": len(results) - added, "results": results}
        preview["summary"], preview["status"] = summary, "done"
        if added and first_response is not None:
            from .bot import build_play_response
            response = build_play_response(
                self.bot.server_data[guild.id], number=added, track="",
                position=getattr(first_response, "queue_position_text", ""), playlist=True)
            await self.send_web_response(request, guild, owner, response, "play")
        return summary

    async def send_web_response(self, request, guild, owner, response, command):
        """Reuse the native Response and safe sender, including auto deletion."""
        if not hasattr(self.bot, "safe_send_message"):
            return
        try:
            if self.discord_auth:
                self.authenticate(request)
                guild, owner = self.guild_owner(request)
            channel = self.channel_for(guild, owner)
            import discord
            name = str(getattr(owner, "display_name", None) or owner.name).replace("\n", " ").replace("\r", " ")[:128]
            name = discord.utils.escape_mentions(discord.utils.escape_markdown(name))
            operation = "點歌" if command in ("play", "playnext") else "操作"
            plain = Response(f"-# {name} 透過網頁控制台{operation}\n" + response.content,
                             force_text=True, delete_after=response.delete_after)
            plain.dashboard_no_mentions = True
            await asyncio.wait_for(self.bot.safe_send_message(channel, plain), 10)
        except Exception as exc:
            log.warning("Dashboard Discord response failed (%s)", type(exc).__name__)

    async def mutate(self, request):
        data = await self.payload(request)
        guild, owner = self.guild_owner(request)
        action = request.path.rsplit("/", 1)[-1]
        if request.method == "DELETE":
            action = "remove"
        if action in ("play", "playnext"):
            if "selected_items" in data and "preview_id" not in data:
                raise APIError(400, "選歌加入必須提供預覽憑證。")
            self.user_rate_limit(owner)
            query = self.query(data)
        elif action == "seek":
            position = data.get("position")
            try:
                valid = (not isinstance(position, bool) and isinstance(position, (int, float))
                         and math.isfinite(float(position)) and position >= 0)
            except (ValueError, TypeError, OverflowError):
                valid = False
            if not valid:
                raise APIError(400, "跳轉位置必須是大於或等於 0 的有限秒數。")
            # Normalize once before permissions, queue mutation and reporting.
            # Non-negative values use conventional half-up rather than bankers rounding.
            data["position"] = math.floor(float(position) + 0.5)
            # Capture before the guild lock: native Discord playback is not
            # serialized by this lock, and context() may await a voice lookup.
            seek_player = self.bot.get_player_in(guild)
            seek_entry = getattr(seek_player, "current_entry", None)
            if ("track_token" in data
                    and data["track_token"] != self.track_token(seek_player)):
                raise APIError(409, "播放中的歌曲已更新，請重新整理後再跳轉。")
        elif action == "volume":
            self.integer(data, "volume", 1, 100)
        elif action == "repeat" and data.get("mode") not in ("off", "song", "all"):
            raise APIError(400, "重複模式必須是 off、song 或 all。")

        async with self.locks[guild.id]:
            request[ACTIVITY_KEY] = capture(self, guild, owner, action, "web")
            if action == "seek" and request[ACTIVITY_KEY] is not None:
                request[ACTIVITY_KEY].target_position = data["position"]
            if self.discord_auth:
                # Requests can queue behind another command; re-check current membership/session.
                self.authenticate(request)
                guild, owner = self.guild_owner(request)
            sub = ""
            if self.discord_auth:
                sub = (query.split()[0] if action in ("play", "playnext") else
                       str(data.get("position", "")) if action == "seek" else
                       str(data.get("volume", "")) if action == "volume" else
                       {"song": "on", "all": "all", "off": "off"}.get(data.get("mode"), "") if action == "repeat" else
                       str(data.get("from", "")) if action == "move" else
                       request.match_info.get("position", "") if action == "remove" else "")
            preview = self.confirmed_preview(data, guild, owner) if action in ("play", "playnext") else None
            if preview:
                await self.renew_preview(request, data, preview, guild, owner, action)
            if action == "playnext" and (data.get("selected_items") is not None or (preview and preview.get("kind") == "playlist")):
                raise APIError(400, "下一首播放目前只支援單曲，請選取單曲來源。")
            if preview and preview["status"] == "done" and not self.discord_auth:
                return web.json_response({"message": "這個選項已加入，未重複點播。",
                                          "state": self.snapshot(guild, owner), **(preview.get("summary") or {})})
            if self.discord_auth and action == "repeat":
                current = self.bot.get_player_in(guild)
                if current is not None:
                    subs = self.repeat_commands(current, data["mode"])
                    sub = subs[0] if subs else sub
            player, permissions, channel = await self.context(guild, owner, action, sub)
            if action == "seek" and (player is not seek_player or player.current_entry is not seek_entry):
                raise APIError(409, "播放中的歌曲已更新，請重新整理後再跳轉。")
            if self.discord_auth:
                self.authenticate(request)
                guild, owner = self.guild_owner(request)
            if preview and preview["status"] == "done":
                return web.json_response({"message": "這個選項已加入，未重複點播。",
                                          "state": self.snapshot(guild, owner), **(preview.get("summary") or {})})
            ssd = self.bot.server_data[guild.id]
            if action in ("remove", "move", "shuffle"):
                if not data.get("revision") or data["revision"] != revision(player):
                    raise APIError(409, "隊列已更新，請重新整理後再操作。")
            response = None
            summary = {}
            if action == "play" and preview and preview.get("kind") == "playlist":
                summary = await self.play_selection(request, data, preview, guild, owner)
                reasons = list(dict.fromkeys(item["reason"] for item in summary["results"] if item["reason"]))
                response = Response(f"已加入 {summary['added']} 首，略過 {summary['skipped']} 首。" +
                                    (" " + "；".join(reasons) if reasons else ""))
            elif action in ("play", "playnext"):
                if preview:
                    preview["status"] = "submitted"
                def validate_next(info):
                    if info.has_entries and (info.entry_count > 1 or "search" not in str(info.extractor)):
                        raise APIError(403, "下一首播放目前只支援單曲，請選取單曲來源。")
                    if self.discord_auth:
                        self.authenticate(request)
                    current_guild, member = self.guild_owner(request)
                    perms = self.bot.permissions.for_user(member)
                    self.command_permission(member, perms, action, query.split()[0])
                    if self.discord_auth:
                        self.voice_permission(current_guild, member, perms, action)
                    self.addition_checks(self.bot.get_player_in(current_guild), member, perms)
                    # Native duration_td.seconds drops complete days and fractions.
                    # Check the fresh selected track using its full duration before
                    # _cmd_play can enqueue; search wrappers may retain child data.
                    candidate = info
                    if info.has_entries:
                        children = info.get_entries_objects()
                        if not children or children[0].has_entries:
                            raise APIError(403, "沒有可確認的單曲，請重新查詢。")
                        candidate = children[0]
                    reason = self.restriction(candidate, perms, extractor=info.extractor)
                    if reason:
                        raise APIError(403, reason)
                    return perms
                check_token = CONFIRMED_ENTRY_CHECK.set(ConfirmedEntryCheck(validate_next)) if action == "playnext" or preview else None
                try:
                    response = await getattr(self.bot, "cmd_" + action)(
                        message=None, player=player, channel=channel, guild=guild,
                        author=owner, permissions=permissions, leftover_args=[],
                        song_url=query.strip())
                finally:
                    if check_token is not None:
                        CONFIRMED_ENTRY_CHECK.reset(check_token)
            elif action == "seek":
                if not player.current_entry:
                    raise APIError(409, "目前沒有播放中的歌曲。")
                if not self.is_seekable(player.current_entry):
                    raise APIError(400, "直播或長度未知的歌曲無法跳轉。")
                if position > player.current_entry.duration or data["position"] > player.current_entry.duration:
                    raise APIError(400, "跳轉位置超過歌曲長度。")
                response = await self.bot.cmd_seek(
                    ssd_=ssd, guild=guild, player=player, leftover_args=[],
                    seek_time=str(data["position"]))
                # Native seek intentionally accepts fractional Discord arguments;
                # dashboard reporting shares the activity log integer format.
                response = Response(f"\u8df3\u8f49\uff1a{data['position']} \u79d2")
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
                if self.discord_auth:
                    # Target mode may require multiple original repeat subcommands.
                    for repeat_sub in self.repeat_commands(player, mode):
                        self.command_permission(owner, permissions, "repeat", repeat_sub)
                if player.repeatsong and mode != "song":
                    response = await self.bot.cmd_repeat(ssd, player, "off")
                if player.loopqueue and mode != "all":
                    response = await self.bot.cmd_repeat(ssd, player, "all")
                if mode == "song" and not player.repeatsong:
                    response = await self.bot.cmd_repeat(ssd, player, "on")
                if mode == "all" and not player.loopqueue:
                    response = await self.bot.cmd_repeat(ssd, player, "all")
            elif action == "remove":
                position = request.match_info["position"]
                if not position.isdigit() or int(position) < 1:
                    raise APIError(400, "歌曲位置必須是正整數。")
                index = int(position) - 1
                if index >= len(player.playlist.entries):
                    raise APIError(400, "歌曲位置已失效，請重新整理。")
                removed = player.playlist.entries[index]
                response = await self.bot.cmd_remove(
                    ssd_=ssd, user_mentions=[], author=owner,
                    permissions=permissions, player=player,
                    leftover_args=[], position=position)
                if not isinstance(response, ErrorResponse):
                    summary = self.remember_removal(guild, owner, removed, index)
                    response = Response("已移除〈" + str(removed.title) + "〉")
            elif action == "move":
                if self.discord_auth and not player.current_entry:
                    raise APIError(409, "目前沒有播放中的歌曲。")
                size = len(player.playlist.entries)
                source = self.integer(data, "from", 1, size) - 1
                target = self.integer(data, "to", 1, size) - 1
                # Same Playlist primitives as cmd_move, without its awaited
                # Discord animation/message before the mutation (race window).
                entry = player.playlist.delete_entry_at_index(source)
                player.playlist.insert_entry_at_index(target, entry)
                if self.discord_auth:
                    response = Response(f"已將第 {source + 1} 首移到第 {target + 1} 首。")
            elif action == "shuffle":
                player.playlist.shuffle()
                if self.discord_auth:
                    response = Response("已將佇列洗牌。")
            if isinstance(response, ErrorResponse):
                raise APIError(409, denial_text(response.description or "機器人無法完成操作。"))
            if self.discord_auth:
                self.authenticate(request)
                guild, owner = self.guild_owner(request)
            if action in ("remove", "move", "shuffle"):
                await self.bot.serialize_queue(guild)
            if preview:
                preview["status"] = "done"
            message = response.content if summary else "已完成操作。"
            if response is not None and (not summary or action == "remove"):
                message = getattr(response, "content", "") or message
                await self.send_web_response(request, guild, owner, response, action)
            return web.json_response({"message": message, "state": self.snapshot(guild, owner), **summary})

    async def start(self):
        # Capture a song already playing when an optional dashboard starts.
        for guild in self.bot.guilds:
            player = self.bot.get_player_in(guild)
            entry = getattr(player, "current_entry", None)
            if entry is not None and not self.recent_history.get(guild.id):
                self.record_play(guild, entry)
        self.runner = web.AppRunner(self.app, access_log=None, shutdown_timeout=5)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.config.host, self.config.port)
        await self.site.start()
        log.info("%s web dashboard started on %s:%d",
                 self.config.auth_mode, self.config.host, self.config.port)

    async def close(self):
        await self.shutdown_events()
        tasks = list(self.resolve_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        runner, self.runner = self.runner, None
        if runner:
            await runner.cleanup()
        self.site = None
        self.sessions.clear()
        self.oauth_states.clear()
        self.rate_limits.clear()
        self.lyrics_rate_limits.clear()
        self.recent_history.clear()
        self.history_last_source.clear()
        self.last_requested_guild.clear()
        self.activities.clear()
        self.queue_arrivals.clear()


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
            except Exception as cleanup_error:
                log.error("Dashboard cleanup failed (%s)", type(cleanup_error).__name__)
        return None
