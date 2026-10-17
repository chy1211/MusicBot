"""Discord identify-only login. All credentials stay out of responses and logs."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import re
import secrets
import time
from urllib.parse import urlencode, urlsplit

import aiohttp
from aiohttp import web
from . import write_path
from .web_dashboard_sessions import SessionStore

USER_KEY = web.RequestKey("dashboard_user", dict)
SESSION_KEY = web.RequestKey("session_nonce", str)

OAUTH_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
OAUTH_TOKEN_URL = "https://discord.com/api/oauth2/token"
OAUTH_USER_URL = "https://discord.com/api/v10/users/@me"


class DashboardAuth:
    STATE_TTL = 300
    AUTH_LIMIT = 1024
    OAUTH_TIMEOUT = 10
    SESSION_TTL = 30 * 86400
    SESSION_RENEW_INTERVAL = 86400
    SESSIONS_PER_USER = 10

    def init_auth(self):
        from .web_dashboard import APIError
        self.auth_error = APIError
        self.sessions = {}
        self.oauth_states = {}
        self.login_attempts = []
        self.session_store = None
        self.session_cleanup_at = 0
        if self.config.auth_mode not in ("owner", "discord"):
            raise ValueError("Invalid AuthMode")
        if not self.discord_auth:
            return
        parts = urlsplit(self.config.public_url)
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username or parts.password or parts.query or parts.fragment
                or parts.path not in ("", "/")):
            raise ValueError("PublicURL must be an absolute root origin")
        # Public cookies must not travel over plaintext; HTTP is for local demos only.
        if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("PublicURL requires HTTPS except on loopback")
        _ = parts.port  # Validate malformed port without including the URL in logs.
        if not self.config.discord_client_secret:
            raise ValueError("DiscordClientSecret is required")
        self.client_id = (self.config.discord_client_id
                          or str(getattr(self.bot, "application_id", "") or "")
                          or str(getattr(getattr(self.bot, "cached_app_info", None), "id", "") or "")
                          or str(getattr(getattr(self.bot, "user", None), "id", "") or ""))
        if not re.fullmatch(r"[0-9]{1,20}", self.client_id) or int(self.client_id) <= 0:
            raise ValueError("DiscordClientID or bot application ID is required")
        if not math.isfinite(self.config.session_hours) or self.config.session_hours <= 0:
            raise ValueError("SessionHours must be positive and finite")
        self.session_store = SessionStore(getattr(self, "session_store_root", write_path("data/web_dashboard/sessions")))
        self.sessions = self.session_store.read()
        self.prune_sessions(force=True)


    @property
    def discord_auth(self):
        return self.config.auth_mode == "discord"

    @property
    def secure_cookie(self):
        return urlsplit(self.config.public_url).scheme == "https"

    @property
    def session_cookie(self):
        return ("__Host-" if self.secure_cookie else "") + "musicbot_session"

    @property
    def state_cookie(self):
        return ("__Host-" if self.secure_cookie else "") + "musicbot_oauth"

    @property
    def public_origin(self):
        return self.config.public_url.rstrip("/")

    def set_cookie(self, response, name, value, max_age):
        response.set_cookie(name, value, max_age=max_age, path="/",
                            httponly=True, secure=self.secure_cookie, samesite="Lax")

    def clear_cookie(self, response, name):
        self.set_cookie(response, name, "", 0)

    async def auth_lifecycle(self, _app):
        async def cleanup():
            while True:
                await asyncio.sleep(86400)
                try: self.prune_sessions(force=True)
                except self.auth_error: pass
        task = asyncio.create_task(cleanup())
        try: yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    @staticmethod
    def session_digest(token):
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def save_sessions(self):
        try:
            self.session_store.write(self.sessions)
        except OSError:
            raise self.auth_error(503, "登入資料暫時無法儲存，請稍後再試。") from None

    def prune_sessions(self, force=False):
        now = time.time()
        if not force and now < self.session_cleanup_at: return
        self.session_cleanup_at = now + 86400
        expired = [key for key, item in self.sessions.items() if item["expires"] <= now]
        # Enforce caps even for an otherwise valid pre-existing file.
        users = {}
        for key, item in self.sessions.items():
            users.setdefault(item["user"]["id"], []).append(key)
        for keys in users.values():
            keys.sort(key=lambda key:self.sessions[key]["created"])
            expired.extend(keys[:-self.SESSIONS_PER_USER])
        for key in set(expired): self.sessions.pop(key, None)
        if expired: self.save_sessions()

    def prune_auth(self):
        now = time.monotonic()
        for key in list(self.oauth_states):
            if self.oauth_states[key]["expires"] <= now: self.oauth_states.pop(key)
        if self.discord_auth: self.prune_sessions()

    def new_session(self, user):
        self.prune_auth()
        uid = str(user["id"])
        owned = sorted((key for key, item in self.sessions.items() if item["user"]["id"] == uid),
                       key=lambda key:self.sessions[key]["created"])
        for key in owned[:max(0, len(owned) - self.SESSIONS_PER_USER + 1)]:
            self.sessions.pop(key)
        if len(self.sessions) >= self.AUTH_LIMIT:
            raise self.auth_error(503, "登入人數已達上限，請稍後再試。")
        token = secrets.token_urlsafe(32)
        now = time.time()
        self.sessions[self.session_digest(token)] = {
            "user": {"id":uid, "name":str(user["name"])[:128], "avatar":str(user.get("avatar",""))[:512]},
            "created":now, "last_seen":now, "expires":now+self.SESSION_TTL}
        self.save_sessions()
        return token

    def revoke_session(self, request, all_devices=False):
        digest = request.get(SESSION_KEY)
        session = self.sessions.get(digest)
        if not session: return
        uid = session["user"]["id"]
        keys = [key for key, item in self.sessions.items()
                if key == digest or (all_devices and item["user"]["id"] == uid)]
        for key in keys: self.sessions.pop(key, None)
        self.save_sessions()

    def session_user(self, request):
        self.prune_auth()
        token = request.cookies.get(self.session_cookie, "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token): return None
        digest = self.session_digest(token)
        session = self.sessions.get(digest)
        if not session: return None
        if session["expires"] <= time.time():
            self.sessions.pop(digest, None); self.save_sessions(); return None
        request[SESSION_KEY] = digest
        uid = int(session["user"]["id"])
        members = [guild.get_member(uid) for guild in self.bot.guilds]
        try:
            for member in members:
                if member is not None: self.check_blocked(member)
            if not any(member is not None for member in members) and not any(
                    getattr(guild, "unavailable",False) for guild in self.bot.guilds):
                raise self.auth_error(403, "你目前不是機器人所在伺服器的成員。")
        except self.auth_error:
            self.revoke_session(request)
            if request.path == "/auth/session": return None
            raise
        return session["user"]

    def renew_session(self, request, response):
        # Renew only successful, same-origin responses, at most once per day.
        if (not self.discord_auth or response.prepared or response.status >= 400
                or request.path in ("/auth/logout","/auth/logout-all")
                or request.host.lower() != urlsplit(self.public_origin).netloc.lower()
                or request.headers.get("Origin") not in (None,self.public_origin)
                or request.headers.get("Sec-Fetch-Site") not in (None,"same-origin","none")):
            return
        session = self.sessions.get(request.get(SESSION_KEY))
        if session is None or session["last_seen"] > time.time()-self.SESSION_RENEW_INTERVAL:
            return
        now = time.time()
        previous = session["last_seen"], session["expires"]
        session["last_seen"], session["expires"] = now, now + self.SESSION_TTL
        try: self.save_sessions()
        except self.auth_error:
            session["last_seen"], session["expires"] = previous
            return
        self.set_cookie(response,self.session_cookie,request.cookies[self.session_cookie],self.SESSION_TTL)

    async def auth_session(self, request):
        if not self.discord_auth:
            return web.json_response({"auth_mode": "owner", "authenticated": True, "user": None})
        user = self.session_user(request)
        return web.json_response({"auth_mode": "discord", "authenticated": user is not None,
                                  "user": user})

    async def auth_login(self, request):
        if not self.discord_auth:
            raise self.auth_error(404, "未啟用 Discord 登入。")
        self.prune_auth()
        now = time.monotonic()
        self.login_attempts = [t for t in self.login_attempts if t > now - 60]
        # Fixed memory and OAuth admission bounds, also before authentication.
        if len(self.oauth_states) >= self.AUTH_LIMIT or len(self.login_attempts) >= 60:
            raise self.auth_error(429, "登入請求過於頻繁，請稍後再試。")
        self.login_attempts.append(now)
        state = secrets.token_urlsafe(32)
        self.oauth_states[state] = {"expires": now + self.STATE_TTL}
        location = OAUTH_AUTHORIZE_URL + "?" + urlencode({
            "client_id": self.client_id, "redirect_uri": self.public_origin + "/auth/callback",
            "response_type": "code", "scope": "identify", "state": state})
        response = web.HTTPFound(location=location)
        self.set_cookie(response, self.state_cookie, state, self.STATE_TTL)
        raise response

    async def oauth_identity(self, code):
        # A dedicated, short-lived session avoids accidental bot Authorization headers.
        # Never retain access/refresh tokens, provider responses, code or exception text.
        async def body(response):
            if response.status != 200:
                raise ValueError("OAuth provider rejected request")
            data = bytearray()
            async for chunk in response.content.iter_chunked(4096):
                data.extend(chunk)
                if len(data) > 16384:
                    raise ValueError("OAuth response too large")
            result = json.loads(data)
            if not isinstance(result, dict):
                raise ValueError("OAuth response must be an object")
            return result
        try:
            async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=self.OAUTH_TIMEOUT),
                    trust_env=False) as http:
                async with http.post(OAUTH_TOKEN_URL, data={
                        "client_id": self.client_id,
                        "client_secret": self.config.discord_client_secret,
                        "grant_type": "authorization_code", "code": code,
                        "redirect_uri": self.public_origin + "/auth/callback"},
                        allow_redirects=False) as response:
                    token_data = await body(response)
                access_token = token_data.get("access_token")
                if not isinstance(access_token, str) or not access_token or len(access_token) > 4096:
                    raise ValueError("OAuth token missing")
                async with http.get(OAUTH_USER_URL,
                                    headers={"Authorization": "Bearer " + access_token},
                                    allow_redirects=False) as response:
                    identity = await body(response)
            uid = str(identity.get("id", ""))
            if not re.fullmatch(r"[0-9]{1,20}", uid) or int(uid) <= 0:
                raise ValueError("OAuth user ID missing")
            name = identity.get("global_name") or identity.get("username")
            if not isinstance(name, str) or not name:
                raise ValueError("OAuth user name missing")
            avatar_hash = identity.get("avatar")
            avatar = ""
            if isinstance(avatar_hash, str) and re.fullmatch(r"(?:a_)?[0-9a-f]{32}", avatar_hash):
                avatar = f"https://cdn.discordapp.com/avatars/{uid}/{avatar_hash}.png?size=64"
            return {"id": uid, "name": name[:128], "avatar": avatar}
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError, KeyError):
            raise self.auth_error(502, "Discord 登入失敗，請重新登入或稍後再試。") from None

    async def auth_callback(self, request):
        if not self.discord_auth:
            raise self.auth_error(404, "未啟用 Discord 登入。")
        state = request.query.get("state", "")
        cookie = request.cookies.get(self.state_cookie, "")
        self.prune_auth()
        if (not state or len(state) > 128 or not cookie
                or not hmac.compare_digest(state.encode(), cookie.encode())
                or state not in self.oauth_states):
            raise self.auth_error(403, "登入驗證已失效，請重新登入。")
        # Consume before any await, including failed exchanges; no replay.
        self.oauth_states.pop(state)
        code = request.query.get("code", "")
        if request.query.get("error") or not code or len(code) > 2048:
            raise self.auth_error(400, "Discord 登入未完成，請重新登入。")
        user = await self.oauth_identity(code)
        old_nonce = request.get(SESSION_KEY)
        if old_nonce:
            self.revoke_session(request)
        response = web.HTTPFound(location="/")
        self.set_cookie(response, self.session_cookie, self.new_session(user),
                        self.SESSION_TTL)
        self.clear_cookie(response, self.state_cookie)
        request[USER_KEY] = user
        raise response

    async def auth_logout(self, request):
        if not self.discord_auth:
            raise self.auth_error(404, "未啟用 Discord 登入。")
        self.revoke_session(request, all_devices=request.path == "/auth/logout-all")
        # Invalidate pending login from this browser as well.
        state = request.cookies.get(self.state_cookie, "")
        self.oauth_states.pop(state, None)
        response = web.json_response({"message": "已登出所有裝置。" if request.path == "/auth/logout-all" else "已登出。"})
        self.clear_cookie(response, self.session_cookie)
        self.clear_cookie(response, self.state_cookie)
        return response
