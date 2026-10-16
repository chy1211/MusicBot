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

USER_KEY = web.RequestKey("dashboard_user", dict)
SESSION_KEY = web.RequestKey("session_nonce", str)

OAUTH_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
OAUTH_TOKEN_URL = "https://discord.com/api/oauth2/token"
OAUTH_USER_URL = "https://discord.com/api/v10/users/@me"


class DashboardAuth:
    STATE_TTL = 300
    AUTH_LIMIT = 1024
    OAUTH_TIMEOUT = 10

    def init_auth(self):
        from .web_dashboard import APIError
        self.auth_error = APIError
        self.sessions = {}
        self.oauth_states = {}
        self.login_attempts = []
        self.session_key = (self.config.session_secret.encode()
                            if self.config.session_secret else secrets.token_bytes(32))
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

    def prune_auth(self):
        now = time.monotonic()
        for records in (self.sessions, self.oauth_states):
            for key in list(records):
                if records[key]["expires"] <= now:
                    del records[key]

    def new_session(self, user):
        self.prune_auth()
        if len(self.sessions) >= self.AUTH_LIMIT:
            raise self.auth_error(503, "登入人數已達上限，請稍後再試。")
        nonce = secrets.token_urlsafe(32)
        signature = hmac.new(self.session_key, nonce.encode(), hashlib.sha256).hexdigest()
        self.sessions[nonce] = {"user": dict(user),
                                "expires": time.monotonic() + self.config.session_hours * 3600}
        return nonce + "." + signature

    def session_user(self, request):
        cookie = request.cookies.get(self.session_cookie, "")
        if len(cookie) > 160 or "." not in cookie:
            return None
        nonce, signature = cookie.rsplit(".", 1)
        expected = hmac.new(self.session_key, nonce.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature.encode(), expected.encode()):
            return None
        session = self.sessions.get(nonce)
        if not session:
            return None
        if session["expires"] <= time.monotonic():
            self.sessions.pop(nonce, None)
            return None
        request[SESSION_KEY] = nonce
        return session["user"]

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
            self.sessions.pop(old_nonce, None)
        response = web.HTTPFound(location="/")
        self.set_cookie(response, self.session_cookie, self.new_session(user),
                        int(self.config.session_hours * 3600))
        self.clear_cookie(response, self.state_cookie)
        request[USER_KEY] = user
        raise response

    async def auth_logout(self, request):
        if not self.discord_auth:
            raise self.auth_error(404, "未啟用 Discord 登入。")
        nonce = request.get(SESSION_KEY)
        if nonce:
            self.sessions.pop(nonce, None)
        # Invalidate pending login from this browser as well.
        state = request.cookies.get(self.state_cookie, "")
        self.oauth_states.pop(state, None)
        response = web.json_response({"message": "已登出。"})
        self.clear_cookie(response, self.session_cookie)
        self.clear_cookie(response, self.state_cookie)
        return response
