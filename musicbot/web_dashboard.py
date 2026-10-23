"""Optional HTTP dashboard with backwards-compatible owner or Discord identity."""
from __future__ import annotations
from .web_dashboard_i18n import message as _web_text, localized_request, DASHBOARD_KEY, catalog, LANGUAGE

import asyncio
import configparser
import hashlib
import hmac
import json
import logging
import math
import re
import secrets
import time
from collections import defaultdict, deque
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from aiohttp import web
from discord import ChannelType

from . import exceptions, write_path
from .constructs import ErrorResponse, Response
from .entry import LocalFilePlaylistEntry, URLPlaylistEntry
from .web_dashboard_lyrics import LyricsClient, clean_metadata, metadata as lyrics_metadata
from .web_dashboard_lyrics_store import LyricsStore, video_id
from .web_dashboard_lyrics_alignment import AlignmentService, UNCERTAIN
from .i18n import _D
from .spotify import Spotify
from .utils import get_compound_link_ids
from .web_dashboard_auth import DashboardAuth, USER_KEY
from .web_dashboard_events import DashboardEvents
from .web_dashboard_stats import PopularityStore
from .web_dashboard_library import DashboardLibrary
from .web_dashboard_admin import DashboardAdmin
from .web_dashboard_activity import capture, finish
from .web_dashboard_extraction import (WEB_EXTRACTION, WEB_LIMITS, RESOLUTION_BUDGET,
    ExtractionBudget, ExtractionBudgetExceeded, UnsupportedDashboardURL, normalize_query,
    WEB_POOL, DashboardExtractionPool, youtube_playlist_subject)

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
    session_hours: float = 720

    default_language: str = "en"
    time_zone: str = "UTC"
    resolve_timeout_seconds: float = 20
    resolve_max_response_bytes: int = 8 * 1024 * 1024
    resolve_max_total_bytes: int = 32 * 1024 * 1024

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
        language = parser.get("WebDashboard", "DefaultLanguage", fallback="en").strip()
        zone = parser.get("WebDashboard", "TimeZone", fallback="UTC").strip()
        if language not in ("en", "zh-TW"): raise ValueError("Invalid DefaultLanguage")
        from zoneinfo import ZoneInfo
        ZoneInfo(zone)
        timeout = parser.getfloat("WebDashboard", "ResolveTimeoutSeconds", fallback=20)
        response = parser.getint("WebDashboard", "ResolveMaxResponseBytes", fallback=8388608)
        total = parser.getint("WebDashboard", "ResolveMaxTotalBytes", fallback=33554432)
        if (not math.isfinite(timeout) or not 1 <= timeout <= 120
                or not 1024 <= response <= 64 * 1024 * 1024
                or not response <= total <= 256 * 1024 * 1024):
            raise ValueError("Invalid dashboard extraction limits")
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
            "WebDashboard", "SharedSecret", fallback="").strip(), auth_mode=mode, default_language=language, time_zone=zone,
            resolve_timeout_seconds=timeout, resolve_max_response_bytes=response,
            resolve_max_total_bytes=total, **options)


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


def summon_dashboard_url(bot) -> str:
    """Public member-login URL to announce on summon, or empty when not shareable."""
    config = getattr(getattr(bot, "_web_dashboard", None), "config", None)
    if config is None or getattr(config, "auth_mode", "") != "discord":
        return ""
    url = str(getattr(config, "public_url", "") or "").strip().rstrip("/")
    return url + "/" if url.startswith("https://") else ""


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
    if is_radio(entry):
        return {"name": _web_text('m0338'), "avatar": ""}
    meta = getattr(entry, "meta", None) or {}
    author = (getattr(entry, "author", None) or getattr(entry, "member", None)
              or meta.get("author") or meta.get("member"))
    if author is None:
        # Restored entries can lose their author when the member left the guild.
        return {"name": _web_text('m0339') if getattr(entry, "channel", None)
                else _web_text('m0045'), "avatar": ""}
    uid = getattr(author, "id", None)
    member = guild.get_member(uid) if guild is not None and uid is not None else None
    person = member or author
    return {"name": str(getattr(person, "display_name", None)
                        or getattr(person, "global_name", None)
                        or getattr(person, "name", None) or _web_text('m0339'))[:128],
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
        ("You do not have the permission to remove", _web_text('m0340')),
        ("You have reached your enqueued song limit", _web_text('m0341')),
        ("The playlist entries will exceed", _web_text('m0342')),
        ("Queue limit reached", _web_text('m0341')),
        ("Song duration exceeds limit", _web_text('m0343')),
        ("You are not allowed to request playlists", _web_text('m0344')),
        ("Playlist has too many entries", _web_text('m0345')),
        ("Karaoke mode is enabled", _web_text('m0346')),
        ("This command is not allowed", _web_text('m0347')),
        ("This command requires you to be in a Voice", _web_text('m0348')),
        ("Invalid entry number", _web_text('m0349')),
        ("You must be in the same", _web_text('m0350')),
        ("You cannot use this command", _web_text('m0351')),
    )
    for prefix, translated in mappings:
        if message.startswith(prefix):
            return translated
    # Do not expose raw extractor details/URLs through a rejection.
    for key, value in catalog("zh-TW").items():
        if message == value:
            return _web_text(key)
    return _web_text('m0354')


def revision(player) -> str:
    # Object identities distinguish duplicate URLs and identical new queues.
    identities = [id(player), id(player.current_entry)]
    identities.extend(id(entry) for entry in player.playlist.entries)
    return hashlib.sha256(str(identities).encode()).hexdigest()


from .web_dashboard_undo import DashboardUndo
from .web_dashboard_spotify import DashboardSpotify
from .web_dashboard_maintenance import DashboardMaintenance
from .web_dashboard_radio import DashboardRadio, is_radio
from .dashboard_backend.static import DashboardStaticRoutes
from .dashboard_backend.identity_history import DashboardIdentityHistory
from .dashboard_backend.lyrics import DashboardLyricsRoutes
from .dashboard_backend.state import DashboardStateRoutes
from .dashboard_backend.request_support import DashboardRequestSupport
from .dashboard_backend.resolve import DashboardResolveRoutes
from .dashboard_backend.mutation import DashboardMutationRoutes

class Dashboard(
    DashboardAuth, DashboardEvents, DashboardStaticRoutes, DashboardIdentityHistory,
    DashboardLyricsRoutes, DashboardStateRoutes, DashboardRequestSupport,
    DashboardResolveRoutes, DashboardMutationRoutes, DashboardLibrary, DashboardAdmin,
    DashboardUndo, DashboardSpotify, DashboardMaintenance, DashboardRadio
):
    def __init__(self, bot, config: DashboardConfig):
        self.bot = bot
        self.config = config
        self.runner = None
        self.site = None
        self.locks = defaultdict(asyncio.Lock)
        self.extraction_pool = DashboardExtractionPool()
        self.resolve_tasks = {}
        self.RESOLVE_TIMEOUT = config.resolve_timeout_seconds
        self.previews = {}
        self.rate_limits = {}
        self.lyrics_rate_limits = {}
        self.lyrics_client = LyricsClient()
        self.lyrics_store = LyricsStore(write_path("data/web_dashboard/lyrics"))
        self.lyrics_alignment = AlignmentService(self.lyrics_store)
        self.lyrics_offset_locks = defaultdict(asyncio.Lock)
        self.lyrics_offset_rates = {}
        self.recent_history = defaultdict(lambda: deque(maxlen=50))
        self.history_marker = secrets.token_urlsafe(16)
        self.history_last_source = {}
        self.last_requested_guild = {}
        self.activities = defaultdict(lambda: deque(maxlen=100))
        self.queue_arrivals = defaultdict(list)
        self.init_auth()
        self.app = web.Application(
            middlewares=[localized_request, self.guard], client_max_size=16 * 1024)
        self.app[DASHBOARD_KEY] = self
        if self.discord_auth: self.app.cleanup_ctx.append(self.auth_lifecycle)
        self.init_events()
        self.init_library()
        self.init_admin()
        self.init_undo()
        self.init_spotify_lookup()
        self.init_maintenance()
        self.init_radio()
        async def lyric_lifecycle(_app):
            for guild in self.bot.guilds:
                await self.lyrics_store.enabled(guild)
            yield
        self.app.cleanup_ctx.append(lyric_lifecycle)
        async def cleanup_alignment(_app):
            await self.lyrics_alignment.close()
        self.app.on_cleanup.append(cleanup_alignment)
        self.app.router.add_get("/api/guilds/{guild_id}/lyrics/offset", self.lyrics_offset)
        self.app.router.add_post("/api/guilds/{guild_id}/lyrics/offset", self.lyrics_offset)
        self.app.router.add_get("/api/guilds/{guild_id}/admin/lyrics", self.admin_lyrics)
        self.app.router.add_post("/api/guilds/{guild_id}/admin/lyrics", self.admin_lyrics)
        self.popularity_store = PopularityStore(write_path("data/web_dashboard/stats"))
        async def cleanup_popularity(_app):
            try:
                await self.popularity_store.close()
            except Exception:
                log.warning("Dashboard popularity final flush failed")
        self.app.on_cleanup.append(cleanup_popularity)

        self.app.router.add_get("/healthz", self.healthz)
        self.app.router.add_get("/ui-config", self.ui_config)
        self.app.router.add_get("/i18n/{locale}.json", self.language_catalog)
        self.app.router.add_get("/i18n.js", self.asset)
        self.app.router.add_get("/", self.index)
        for path in ("manifest.webmanifest", "sw.js", "pwa.js", "offline.html", "offline.css", "offline.js",
                     "icon-192.png", "icon-512.png", "apple-touch-icon.png"):
            self.app.router.add_get("/" + path, self.pwa_asset)
        self.app.router.add_get("/favicon.svg", self.favicon)
        self.app.router.add_get("/assets/{name}", self.hashed_asset)
        self.app.router.add_get("/favicon.ico", self.favicon)
        self.app.router.add_get("/auth/session", self.auth_session)
        self.app.router.add_get("/auth/login", self.auth_login)
        self.app.router.add_get("/auth/callback", self.auth_callback)
        self.app.router.add_post("/auth/logout", self.auth_logout)
        self.app.router.add_post("/auth/logout-all", self.auth_logout)
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
            raise APIError(401, _web_text('m0355'))
        request[USER_KEY] = user

    # Canonical route templates only: never log URL/query values or headers.
    NO_OPERATION_ROUTES = frozenset({
        "/", "/healthz", "/ui-config", "/i18n/{locale}.json", "/i18n.js",
        "/dashboard.css", "/dashboard.js", "/library.js", "/admin.js",
        "/permissions.js", "/popular.js", "/favicon.svg", "/favicon.ico",
        "/manifest.webmanifest", "/sw.js", "/pwa.js", "/offline.html", "/offline.css", "/offline.js",
        "/icon-192.png", "/icon-512.png", "/apple-touch-icon.png", "/auth/session", "/assets/{name}",
    })
    OPERATION_ROUTES = {
        "/auth/login": "login", "/auth/callback": "callback",
        "/auth/logout": "logout", "/auth/logout-all": "logout_all",
        "/api/guilds": "guilds",
        **{"/api/guilds/{guild_id}/" + action: action for action in (
            "state", "listeners", "activity", "events", "history", "popular",
            "lyrics", "resolve", "play", "playnext", "seek", "pause", "resume",
            "skip", "volume", "repeat", "spotify")},
        "/api/guilds/{guild_id}/lyrics/offset": "lyrics_offset",
        "/api/guilds/{guild_id}/admin/lyrics": "admin_lyrics",
        "/api/guilds/{guild_id}/admin/notification-channel": "admin_notification_channel",
        "/api/guilds/{guild_id}/admin/autoplaylist": "admin_autoplaylist",
        "/api/guilds/{guild_id}/admin/permissions": "admin_permissions",
        "/api/guilds/{guild_id}/admin/vote-skip": "admin_vote_skip",
        "/api/guilds/{guild_id}/admin/maintenance": "admin_maintenance",
        "/api/guilds/{guild_id}/admin/empty-queue": "admin_empty_queue",
        "/api/guilds/{guild_id}/queue/shuffle": "shuffle",
        "/api/guilds/{guild_id}/queue/move": "move",
        "/api/guilds/{guild_id}/queue/{position}": "remove",
        "/api/guilds/{guild_id}/queue/undo": "queue_undo",
        "/api/library": "library",
        "/api/library/{playlist_id}": "library_update",
        "/api/library/{playlist_id}/tracks": "library_tracks",
        "/api/library/sources": "library_sources",
        "/api/library/import": "library_import",
        "/api/library/{playlist_id}/sync": "library_sync",
        "/api/guilds/{guild_id}/library/{playlist_id}/play": "library_play",
        "/api/guilds/{guild_id}/library/import/preview": "library_import_preview",
        "/api/guilds/{guild_id}/library/{playlist_id}/sync/preview": "library_sync_preview",
    }

    def request_action(self, request):
        resource = request.match_info.route.resource
        path = resource.canonical if resource is not None else ""
        if path in self.NO_OPERATION_ROUTES:
            return None
        return self.OPERATION_ROUTES.get(path, "unmatched")

    @web.middleware
    async def guard(self, request, handler):
        api = request.path.startswith("/api/")
        logout = request.path in ("/auth/logout", "/auth/logout-all")
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
                    raise APIError(403, _web_text('m0356'))
                origin = request.headers.get("Origin")
                if origin and origin != self.public_origin:
                    raise APIError(403, _web_text('m0357'))
            if api or logout:
                if events:
                    if request.headers.get("Sec-Fetch-Site") not in (None, "same-origin"):
                        raise APIError(403, _web_text('m0358'))
                    # EventSource cannot send Bearer headers. Never put the secret
                    # in a URL or silently bypass legacy owner protection.
                    if not self.discord_auth and self.config.shared_secret:
                        raise APIError(403, _web_text('m0359'))
                elif request.headers.get("X-MusicBot-Dashboard") != "1":
                    raise APIError(403, _web_text('m0360'))
                origin = request.headers.get("Origin")
                if (not self.discord_auth and origin
                        and urlsplit(origin).netloc != request.host):
                    raise APIError(403, _web_text('m0357'))
                # Discord sessions replace the owner-mode optional shared secret.
                if not self.discord_auth and self.config.shared_secret:
                    token = request.headers.get("Authorization", "")
                    expected = "Bearer " + self.config.shared_secret
                    if not hmac.compare_digest(token.encode(), expected.encode()):
                        raise APIError(401, _web_text('m0361'))
                if api and (not self.bot.is_ready() or not self.bot.init_ok
                            or self.bot.logout_called):
                    raise APIError(503, _web_text('m0362'))
            token = WEB_EXTRACTION.set(self.request_action(request) in {
                "resolve", "play", "playnext", "library_play", "library_import",
                "library_sync", "library_import_preview", "library_sync_preview"})
            pool_token = WEB_POOL.set(self.extraction_pool if self.extraction_pool.started else None)
            limits_token = WEB_LIMITS.set((self.RESOLVE_TIMEOUT,
                self.config.resolve_max_response_bytes, self.config.resolve_max_total_bytes))
            try:
                response = await handler(request)
            finally:
                WEB_POOL.reset(pool_token)
                WEB_LIMITS.reset(limits_token)
                WEB_EXTRACTION.reset(token)
        except ExtractionBudgetExceeded:
            response = web.json_response({"error": _web_text('m0607')}, status=502)
        except UnsupportedDashboardURL:
            response = web.json_response({"error": _web_text('m0606')}, status=400)
        except APIError as exc:
            response = web.json_response({"error": str(exc), **exc.details}, status=exc.status)
        except exceptions.MusicbotException as exc:
            try:
                guild_id = request.match_info.get("guild_id", "")
                ssd = self.bot.server_data.get(int(guild_id)) if guild_id.isdigit() else None
                message = denial_text(exc.message % exc.fmt_args)
                response = web.json_response(
                    {"error": _web_text('m0363') + message},
                    status=403 if isinstance(exc, exceptions.PermissionsError) else 400)
            except Exception as formatting_error:
                log.error("Dashboard error formatting failed (%s)", type(formatting_error).__name__)
                response = web.json_response(
                    {"error": _web_text('m0364')}, status=500)
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
                    {"error": _web_text('m0365')}, status=exc.status)
        except Exception as exc:
            # Exceptions can contain URLs, authorization codes or provider tokens.
            log.error("Dashboard request failed (%s)", type(exc).__name__)
            response = web.json_response(
                {"error": _web_text('m0366')}, status=500)
        action = self.request_action(request)
        if action is not None and (api or logout or request.path in ("/auth/login", "/auth/callback")):
            uid = (request.get(USER_KEY) or {}).get("id")
            if uid is None and not self.discord_auth:
                uid = str(self.bot.config.owner_id)
            raw_gid = request.match_info.get("guild_id", "")
            gid = raw_gid if raw_gid.isascii() and raw_gid.isdigit() and len(raw_gid) <= 20 else "-"
            log.info("Dashboard operation user=%s guild=%s action=%s status=%d",
                     uid or "-", gid, action, response.status)
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
        self.renew_session(request, response)
        response.headers.update({
            "Cache-Control": (
                "no-cache" if request.path == "/sw.js" or (events and response.prepared)
                else "public, max-age=31536000, immutable"
                if request.path.startswith("/assets/") and response.status < 400 else "no-store"),
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'self'; img-src 'self' https://i.ytimg.com https://img.youtube.com https://cdn.discordapp.com https://media.discordapp.net https://i.scdn.co https://mosaic.scdn.co; "
                "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"),
        })
        if isinstance(response, web.HTTPException):
            raise response
        return response















    LYRICS_REQUESTS_PER_MINUTE = 12



















    USER_REQUESTS_PER_MINUTE = 12



    RESOLVE_TIMEOUT = 20
    PREVIEW_TTL = 300
    PREVIEW_LIMIT = 200
    BATCH_TIMEOUT = 120
    SONG_TIMEOUT = 20
    SEARCH_LIMIT = 5



















    async def start(self):
        await self.extraction_pool.start()
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
        await self.extraction_pool.close()
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
