"""Offline Discord OAuth and per-member authorization tests; no real credentials."""
import asyncio
import copy
import dataclasses
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS, MethodType
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, urlsplit

from aiohttp import CookieJar, web
from aiohttp.test_utils import TestClient, TestServer

import test_web_dashboard as fixtures
from test_web_dashboard import BASE, HEADERS
from musicbot.constructs import SkipState
from musicbot.exceptions import PermissionsError
from musicbot.permissions import PermissionGroup
from musicbot.web_dashboard import Dashboard, DashboardConfig, start_dashboard

SECRET = "FAKE-ONLY-CLIENT-SECRET"
TOKEN = "FAKE-ONLY-ACCESS-TOKEN"
REFRESH = "FAKE-ONLY-REFRESH-TOKEN"


class DiscordBot(fixtures.FakeBot):
    def __init__(self):
        super().__init__()
        self.application_id = 123
        self.member = NS(id=43, name="Friend", bot=False, guild=self.guild)
        self.friend = NS(id=44, name="Other", bot=False, guild=self.guild)
        self.members = {42: self.owner, 43: self.member, 44: self.friend}
        for person in self.members.values():
            person.bot = False
            person.voice = NS(channel=self.channel, deaf=False, self_deaf=False)
        self.member_perms = copy.copy(self.perms)
        self.member_perms.remove = self.member_perms.instaskip = False
        self.member_perms.name = "Default"
        self.member_perms.can_use_command = Mock(return_value=True)
        self.perms.can_use_command = Mock(return_value=True)
        self.permissions.for_user = Mock(
            side_effect=lambda person: self.perms if person.id == 42 else self.member_perms)
        self.guild.get_member = self.members.get
        self.guild.me.voice = NS(channel=self.channel)
        self.channel.members = list(self.members.values())
        self.player.skip_state = SkipState()
        self.config.skips_required, self.config.skip_ratio_required = 2, 1.0
        self.config.bot_exception_ids = set()
        self.blocked_users = set()
        self.config.user_blocklist = NS(
            is_blocked=lambda person: person.id in self.blocked_users)
        self.config.user_blocklist_enabled = True
        self.safe_send_message = AsyncMock()


class DiscordTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = DiscordBot()
        self.auth_temp = tempfile.TemporaryDirectory(prefix="musicbot-webtest-auth-")
        self.auth_path_patch = patch("musicbot.web_dashboard_auth.write_path",return_value=Path(self.auth_temp.name))
        self.auth_path_patch.start()
        self.addCleanup(self.auth_temp.cleanup)
        self.addCleanup(self.auth_path_patch.stop)
        self.dashboard = Dashboard(self.bot, DashboardConfig(
            auth_mode="discord", public_url="http://127.0.0.1",
            discord_client_id="123", discord_client_secret=SECRET,
            session_secret="FAKE-ONLY-SESSION-SECRET", session_hours=168))
        self.client = TestClient(TestServer(self.dashboard.app), headers={"Accept-Language":"zh-TW"},
                                 cookie_jar=CookieJar(unsafe=True))
        await self.client.start_server()
        self.origin = str(self.client.make_url("/")).rstrip("/")
        self.dashboard.config = dataclasses.replace(self.dashboard.config, public_url=self.origin)
        self.login_as(43)
        self.oauth_calls, self.provider_mode = [], ""
        app = web.Application()
        app.router.add_post("/token", self.provider_token)
        app.router.add_get("/me", self.provider_me)
        self.provider = TestServer(app)
        await self.provider.start_server()
        self.token_patch = patch("musicbot.web_dashboard_auth.OAUTH_TOKEN_URL",
                                 str(self.provider.make_url("/token")))
        self.user_patch = patch("musicbot.web_dashboard_auth.OAUTH_USER_URL",
                                str(self.provider.make_url("/me")))
        self.token_patch.start()
        self.user_patch.start()

    async def asyncTearDown(self):
        self.token_patch.stop()
        self.user_patch.stop()
        await self.provider.close()
        await self.client.close()
        await self.dashboard.close()

    def login_as(self, uid):
        person = self.bot.members.get(uid, NS(name="Outsider"))
        token = self.dashboard.new_session({"id": str(uid), "name": person.name, "avatar": ""})
        self.client.session.cookie_jar.update_cookies(
            {self.dashboard.session_cookie: token}, response_url=self.client.make_url("/"))
        return token

    async def call(self, path, data=None, method="POST", status=200, headers=None):
        response = await self.client.request(method, path, json=data,
            headers=dict(HEADERS, Origin=self.origin) if headers is None else headers)
        body = await response.json()
        self.assertEqual(response.status, status, body)
        return body

    async def rev(self):
        return (await self.call(BASE + "state", method="GET"))["revision"]

    async def provider_token(self, request):
        self.oauth_calls.append(("token", dict(await request.post())))
        if self.provider_mode == "token_failure":
            return web.json_response({"error_description": SECRET + TOKEN}, status=400)
        if self.provider_mode == "token_timeout":
            await asyncio.sleep(.08)
        if self.provider_mode == "missing_token":
            return web.json_response({"refresh_token": REFRESH})
        if self.provider_mode == "token_nonjson":
            return web.Response(text=SECRET)
        return web.json_response({"access_token": TOKEN, "refresh_token": REFRESH})

    async def provider_me(self, request):
        self.oauth_calls.append(("me", request.headers.get("Authorization")))
        if self.provider_mode == "user_failure":
            return web.json_response({"error": TOKEN}, status=503)
        if self.provider_mode == "user_timeout":
            await asyncio.sleep(.08)
        if self.provider_mode == "bad_identity":
            return web.json_response({"id": "../not-an-id", "username": "bad"})
        if self.provider_mode == "user_list":
            return web.json_response([{"id": "43", "username": "Friend"}])
        return web.json_response({"id": "43", "username": "friend",
                                  "global_name": "Friend", "avatar": "a" * 32})

    async def begin_oauth(self):
        response = await self.client.get("/auth/login", allow_redirects=False)
        self.assertEqual(response.status, 302)
        query = parse_qs(urlsplit(response.headers["Location"]).query)
        return response, query, query["state"][0]

    async def finish_oauth(self, state):
        return await self.client.get("/auth/callback",
            params={"state": state, "code": "FAKE-CODE"}, allow_redirects=False)

    async def test_anonymous_api_routes_401_without_information(self):
        self.client.session.cookie_jar.clear()
        self.bot.init_ok = False
        for path, method in (("/api/guilds", "GET"), (BASE + "state", "GET"),
                              (BASE + "play", "POST"), ("/api/absent", "GET")):
            with self.subTest(path=path):
                response = await self.client.request(method, path)
                self.assertEqual(response.status, 401)
                text = await response.text()
                for private in ("Test Guild", "Current", "One", "https://example.test"):
                    self.assertNotIn(private, text)

    async def test_session_identity_and_anonymous_home(self):
        from dashboard_static_fixture import dashboard_static
        with dashboard_static():
            body = await (await self.client.get("/auth/session")).json()
            self.assertEqual((body["auth_mode"], body["authenticated"], body["user"]["id"]),
                             ("discord", True, "43"))
            self.client.session.cookie_jar.clear()
            body = await (await self.client.get("/auth/session")).json()
            self.assertFalse(body["authenticated"])
            self.assertIsNone(body["user"])
            response = await self.client.get("/")
            self.assertEqual(response.status, 200)
            self.assertNotIn("Test Guild", await response.text())
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
            self.assertEqual(response.headers["Cache-Control"], "no-store")

    async def test_login_identify_state_cookie_and_exact_redirect(self):
        self.client.session.cookie_jar.clear()
        response, query, state = await self.begin_oauth()
        self.assertEqual(query["scope"], ["identify"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["client_id"], ["123"])
        self.assertEqual(query["redirect_uri"], [self.origin + "/auth/callback"])
        cookie = response.cookies[self.dashboard.state_cookie]
        self.assertEqual(cookie.value, state)
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(cookie["path"], "/")
        self.assertFalse(cookie["secure"])
        self.assertIn(state, self.dashboard.oauth_states)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")

    async def test_callback_success_discards_provider_tokens(self):
        self.client.session.cookie_jar.clear()
        _, _, state = await self.begin_oauth()
        response = await self.finish_oauth(state)
        self.assertEqual(response.status, 302)
        self.assertEqual(response.headers["Location"], "/")
        cookie = response.cookies[self.dashboard.session_cookie]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(int(cookie["max-age"]), 30 * 86400)
        self.assertNotIn(state, self.dashboard.oauth_states)
        identity = await (await self.client.get("/auth/session")).json()
        self.assertEqual(identity["user"]["id"], "43")
        self.assertEqual(identity["user"]["name"], "Friend")
        self.assertIn("/avatars/43/", identity["user"]["avatar"])
        self.assertEqual(self.oauth_calls[0][1]["grant_type"], "authorization_code")
        self.assertEqual(self.oauth_calls[0][1]["redirect_uri"], self.origin + "/auth/callback")
        self.assertEqual(self.oauth_calls[1], ("me", "Bearer " + TOKEN))
        retained = repr((self.dashboard.sessions, self.dashboard.oauth_states,
                         response.headers, identity))
        for secret in (TOKEN, REFRESH, SECRET):
            self.assertNotIn(secret, retained)

    async def test_callback_missing_wrong_state_never_calls_provider(self):
        self.client.session.cookie_jar.clear()
        await self.begin_oauth()
        for params in ({"code": "FAKE-CODE"}, {"state": "wrong", "code": "FAKE-CODE"}):
            response = await self.client.get("/auth/callback", params=params)
            self.assertEqual(response.status, 403)
        self.assertFalse(self.oauth_calls)

    async def test_callback_requires_matching_browser_cookie(self):
        self.client.session.cookie_jar.clear()
        _, _, state = await self.begin_oauth()
        self.client.session.cookie_jar.clear()
        self.assertEqual((await self.finish_oauth(state)).status, 403)
        self.assertFalse(self.oauth_calls)

    async def test_callback_state_expires(self):
        self.client.session.cookie_jar.clear()
        _, _, state = await self.begin_oauth()
        self.dashboard.oauth_states[state]["expires"] = time.monotonic() - 1
        self.assertEqual((await self.finish_oauth(state)).status, 403)
        self.assertFalse(self.oauth_calls)

    async def test_state_consumed_once_even_failed_exchange(self):
        self.client.session.cookie_jar.clear()
        _, _, state = await self.begin_oauth()
        self.provider_mode = "token_failure"
        self.assertEqual((await self.finish_oauth(state)).status, 502)
        self.assertEqual((await self.finish_oauth(state)).status, 403)
        self.assertEqual(len(self.oauth_calls), 1)

    async def test_callback_missing_code_and_provider_denial(self):
        self.client.session.cookie_jar.clear()
        for params in ({}, {"error": "access_denied"}):
            _, _, state = await self.begin_oauth()
            response = await self.client.get("/auth/callback", params=dict(state=state, **params))
            self.assertEqual(response.status, 400)
            self.assertNotIn(state, self.dashboard.oauth_states)
        self.assertFalse(self.oauth_calls)

    async def test_provider_failures_sanitized_create_no_session(self):
        self.client.session.cookie_jar.clear()
        self.dashboard.sessions.clear()
        for mode in ("token_failure", "missing_token", "token_nonjson", "user_failure",
                     "bad_identity", "user_list"):
            with self.subTest(mode=mode):
                self.provider_mode = mode
                _, _, state = await self.begin_oauth()
                with patch("musicbot.web_dashboard.log") as captured:
                    response = await self.finish_oauth(state)
                self.assertEqual(response.status, 502)
                output = (await response.text()) + repr(captured.mock_calls)
                for secret in (SECRET, TOKEN, REFRESH, "FAKE-CODE"):
                    self.assertNotIn(secret, output)
                self.assertFalse(self.dashboard.sessions)
                self.assertFalse((await (await self.client.get("/auth/session")).json())["authenticated"])

    async def test_token_and_user_timeouts_fail_closed(self):
        self.client.session.cookie_jar.clear()
        self.dashboard.sessions.clear()
        self.dashboard.OAUTH_TIMEOUT = .02
        for mode in ("token_timeout", "user_timeout"):
            with self.subTest(mode=mode):
                self.provider_mode = mode
                _, _, state = await self.begin_oauth()
                self.assertEqual((await self.finish_oauth(state)).status, 502)
                self.assertFalse(self.dashboard.sessions)

    async def test_session_expiry_and_signature_tamper_401(self):
        token = self.login_as(43)
        self.dashboard.sessions[self.dashboard.session_digest(token)]["expires"] = time.monotonic() - 1
        await self.call("/api/guilds", method="GET", status=401)
        token = self.login_as(43)
        self.client.session.cookie_jar.update_cookies(
            {self.dashboard.session_cookie: token + "tampered"},
            response_url=self.client.make_url("/"))
        await self.call("/api/guilds", method="GET", status=401)

    async def test_logout_invalidates_replayed_cookie_and_requires_post(self):
        token = self.login_as(43)
        await self.call("/auth/logout", {})
        await self.call("/api/guilds", method="GET", status=401)
        self.client.session.cookie_jar.update_cookies(
            {self.dashboard.session_cookie: token}, response_url=self.client.make_url("/"))
        await self.call("/api/guilds", method="GET", status=401)
        self.login_as(43)
        response = await self.client.get("/auth/logout", headers=dict(HEADERS, Origin=self.origin))
        self.assertEqual(response.status, 405)
        await self.call("/api/guilds", method="GET")

    async def test_logout_requires_header_and_same_origin(self):
        await self.call("/auth/logout", {}, headers={}, status=403)
        await self.call("/auth/logout", {}, headers=dict(HEADERS, Origin="https://other.test"),
                        status=403)
        await self.call("/api/guilds", method="GET")

    async def test_shared_secret_not_substitute_for_discord_login(self):
        self.dashboard.config = dataclasses.replace(
            self.dashboard.config, shared_secret="FAKE-OPTIONAL-SECRET")
        await self.call("/api/guilds", method="GET")
        self.client.session.cookie_jar.clear()
        await self.call("/api/guilds", method="GET", status=401,
                        headers=dict(HEADERS, Authorization="Bearer FAKE-OPTIONAL-SECRET"))

    async def test_authenticated_requires_header_origin_and_public_host(self):
        for headers in ({}, dict(HEADERS, Origin="https://other.test"),
                        dict(HEADERS, Origin="null"),
                        dict(HEADERS, Origin=self.origin, Host="evil.test")):
            await self.call("/api/guilds", method="GET", headers=headers, status=403)

    async def test_https_proxy_canonical_origin_and_secure_host_cookies(self):
        self.dashboard.config = dataclasses.replace(
            self.dashboard.config, public_url="https://music.example.test")
        token = self.dashboard.new_session({"id": "43", "name": "Friend", "avatar": ""})
        headers = dict(HEADERS, Host="music.example.test",
                       Origin="https://music.example.test",
                       Cookie=self.dashboard.session_cookie + "=" + token,
                       **{"X-Forwarded-Proto": "https"})
        await self.call("/api/guilds", method="GET", headers=headers)
        await self.call("/api/guilds", method="GET",
                        headers=dict(headers, Origin="http://music.example.test"), status=403)
        response = await self.client.get("/auth/login",
            headers={"Host": "music.example.test", "X-Forwarded-Proto": "https"},
            allow_redirects=False)
        self.assertEqual(response.status, 302)
        self.assertTrue(self.dashboard.state_cookie.startswith("__Host-"))
        cookie = response.cookies[self.dashboard.state_cookie]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertFalse(cookie["domain"])
        state = parse_qs(urlsplit(response.headers["Location"]).query)["state"][0]
        response = await self.client.get("/auth/callback",
            params={"state": state, "code": "FAKE-CODE"},
            headers={"Host": "music.example.test", "X-Forwarded-Proto": "https",
                     "Cookie": self.dashboard.state_cookie + "=" + state},
            allow_redirects=False)
        self.assertEqual(response.status, 302)
        self.assertTrue(response.cookies[self.dashboard.session_cookie]["secure"])

    async def test_guild_list_only_user_memberships(self):
        self.bot.guilds.append(NS(id=2, name="Hidden Guild", unavailable=False,
            get_member=lambda uid: self.bot.owner if uid == 42 else None))
        body = await self.call("/api/guilds", method="GET")
        self.assertEqual(body["guilds"], [{"id": "1", "name": "Test Guild"}])

    async def test_nonmember_403_membership_rechecked_each_request(self):
        self.login_as(999)
        await self.call(BASE + "state", method="GET", status=403)
        await self.call(BASE + "pause", {}, status=401)
        await self.call("/api/guilds", method="GET", status=401)
        self.login_as(43)
        await self.call(BASE + "state", method="GET")
        self.bot.members.pop(43)
        await self.call(BASE + "state", method="GET", status=403)

    async def test_blocked_users_readonly_denied_owner_exempt(self):
        self.bot.blocked_users.update({42, 43})
        await self.call("/api/guilds", method="GET", status=403)
        await self.call(BASE + "state", method="GET", status=401)
        await self.call(BASE + "pause", {}, status=401)
        self.login_as(42)
        await self.call(BASE + "state", method="GET")

    async def test_state_member_outside_voice_allowed(self):
        self.bot.member.voice = None
        await self.call(BASE + "state", method="GET")
        self.bot.get_player.assert_not_awaited()

    async def test_all_mutations_require_same_bot_voice(self):
        self.bot.member.voice = NS(channel=NS(id=99))
        revision = await self.rev()
        for path, data, method in (
            ("play", {"query": "song"}, "POST"), ("pause", {}, "POST"),
            ("resume", {}, "POST"), ("skip", {}, "POST"), ("volume", {"volume": 30}, "POST"),
            ("repeat", {"mode": "song"}, "POST"),
            ("queue/1", {"revision": revision}, "DELETE"),
            ("queue/move", {"from": 1, "to": 2, "revision": revision}, "POST"),
            ("queue/shuffle", {"revision": revision}, "POST")):
            with self.subTest(action=path):
                response = await self.client.request(method, BASE + path, json=data,
                    headers=dict(HEADERS, Origin=self.origin))
                self.assertIn(response.status, (403, 409), await response.text())
        self.assertEqual(len(self.bot.player.playlist.entries), 3)
        self.assertFalse(self.bot.player.is_paused)
        self.bot.get_player.assert_not_awaited()

    async def test_no_voice_cannot_mutate(self):
        self.bot.member.voice = None
        await self.call(BASE + "pause", {}, status=409)
        self.bot.get_player.assert_not_awaited()

    async def test_ignore_non_voice_preserved(self):
        self.bot.member_perms.ignore_non_voice = {"pause"}
        self.bot._check_ignore_non_voice = AsyncMock(side_effect=PermissionsError("Voice rule"))
        await self.call(BASE + "pause", {}, status=403)
        self.bot._check_ignore_non_voice.assert_awaited_once()

    async def test_summonplay_required_when_bot_disconnected(self):
        self.bot.get_player_in = lambda guild: None
        self.bot.guild.me.voice = None
        self.bot.member_perms.summonplay = False
        await self.call(BASE + "play", {"query": "song"}, status=403)
        self.bot.get_player.assert_not_awaited()
        self.bot.member_perms.summonplay = True
        await self.call(BASE + "play", {"query": "song"})
        self.bot.get_player.assert_awaited_with(self.bot.channel, create=True)
        self.assertIs(self.bot.player.playlist.entries[-1].author, self.bot.member)

    async def test_all_command_permissions_and_move_name(self):
        self.bot.member_perms.can_use_command.return_value = False
        revision = await self.rev()
        for path, command, data, method in (
            ("resolve", "play", {"query": "song"}, "POST"),
            ("play", "play", {"query": "song"}, "POST"),
            ("pause", "pause", {}, "POST"), ("resume", "resume", {}, "POST"),
            ("skip", "skip", {}, "POST"), ("volume", "volume", {"volume": 40}, "POST"),
            ("repeat", "repeat", {"mode": "song"}, "POST"),
            ("queue/1", "remove", {"revision": revision}, "DELETE"),
            ("queue/move", "move", {"from": 1, "to": 2, "revision": revision}, "POST"),
            ("queue/shuffle", "shuffle", {"revision": revision}, "POST")):
            with self.subTest(action=path):
                self.bot.member_perms.can_use_command.reset_mock()
                await self.call(BASE + path, data, method, status=403)
                self.assertEqual(self.bot.member_perms.can_use_command.call_args.args[0], command)
        self.assertFalse(self.bot.extractions)

    async def test_owner_retains_command_permission_bypass(self):
        self.login_as(42)
        self.bot.perms.can_use_command.return_value = False
        await self.call(BASE + "play", {"query": "song"})
        self.assertIs(self.bot.player.playlist.entries[-1].author, self.bot.owner)

    async def test_play_member_author_permissions_response_channel(self):
        self.bot.cmd_play = AsyncMock(side_effect=self.bot.cmd_play)
        await self.call(BASE + "play", {"query": "friend song"})
        kwargs = self.bot.cmd_play.call_args.kwargs
        self.assertIs(kwargs["author"], self.bot.member)
        self.assertIs(kwargs["permissions"], self.bot.member_perms)
        self.assertIs(self.bot.player.playlist.entries[-1].author, self.bot.member)
        self.bot.safe_send_message.assert_awaited()
        self.assertIs(self.bot.safe_send_message.call_args.args[0], self.bot.channel)

    async def test_bound_channels_restrict_member_response(self):
        self.bot.config.bound_channels = {999}
        await self.call(BASE + "play", {"query": "song"}, status=403)
        self.assertFalse(self.bot.extractions)

    async def test_resolve_without_voice_member_limits_never_summons(self):
        self.bot.member.voice = None
        self.bot.member_perms.max_song_length = 100
        body = await self.call(BASE + "resolve", {"query": "song"})
        self.assertFalse(body["results"][0]["allowed"])
        self.assertTrue(body["results"][0]["reason"])
        self.bot.get_player.assert_not_awaited()
        self.bot.permissions.for_user.assert_any_call(self.bot.member)

    async def test_member_queue_limit_counts_own_songs(self):
        self.bot.member_perms.max_songs = 1
        await self.call(BASE + "play", {"query": "first"})
        await self.call(BASE + "resolve", {"query": "second"}, status=403)
        await self.call(BASE + "play", {"query": "second"}, status=403)
        self.assertEqual(len(self.bot.player.playlist.entries), 4)

    async def test_member_playlist_restriction_rechecked_on_confirmation(self):
        self.bot.info = dict(self.bot.info, entries=[dict(self.bot.info)] * 2, playlist_count=2)
        self.bot.member_perms.allow_playlists = False
        body = await self.call(BASE + "resolve", {"query": "https://soundcloud.com/example/list"})
        song = body["results"][0]
        self.assertFalse(song["allowed"])
        await self.call(BASE + "play", {"query": song["url"], "preview_id": song["preview_id"]},
                        status=403)
        self.assertEqual(len(self.bot.player.playlist.entries), 3)

    async def test_member_extractor_song_blocklist_preserved(self):
        self.bot.blocked.add("ytsearch5:blocked")
        await self.call(BASE + "resolve", {"query": "blocked"}, status=403)
        def deny(_):
            raise PermissionsError("Extractor denied")
        self.bot.member_perms.can_use_extractor = deny
        await self.call(BASE + "play", {"query": "song"}, status=403)

    async def test_preview_is_bound_to_user(self):
        song = (await self.call(BASE + "resolve", {"query": "song"}))["results"][0]
        self.login_as(44)
        response = await self.client.post(BASE + "play",
            json={"query": song["url"], "preview_id": song["preview_id"]},
            headers=dict(HEADERS, Origin=self.origin))
        self.assertIn(response.status, (403, 409), await response.text())
        self.assertEqual(len(self.bot.player.playlist.entries), 3)

    async def test_remove_other_song_denied_own_song_allowed(self):
        await self.call(BASE + "queue/1", {"revision": await self.rev()}, "DELETE", status=403)
        self.bot.player.playlist.entries[0].author = self.bot.member
        await self.call(BASE + "queue/1", {"revision": await self.rev()}, "DELETE")
        self.assertEqual(len(self.bot.player.playlist.entries), 2)
        self.bot.serialize_queue.assert_awaited_once_with(self.bot.guild)

    async def test_remove_other_song_with_remove_permission(self):
        self.bot.member_perms.remove = True
        await self.call(BASE + "queue/1", {"revision": await self.rev()}, "DELETE")
        self.assertEqual(len(self.bot.player.playlist.entries), 2)

    async def test_skip_real_votes_deduplicate_and_pass(self):
        first = await self.call(BASE + "skip", {})
        self.assertIsNotNone(self.bot.player.current_entry)
        self.assertEqual(self.bot.player.skip_state.skippers, {43})
        self.assertIn("acknowledged", self.bot.safe_send_message.call_args.args[1].content)
        await self.call(BASE + "skip", {})
        self.assertEqual(self.bot.player.skip_state.skippers, {43})
        self.assertIsNotNone(self.bot.player.current_entry)
        self.login_as(44)
        result = await self.call(BASE + "skip", {})
        self.assertIsNone(self.bot.player.current_entry)
        self.assertEqual(self.bot.player.skip_state.skippers, {43, 44})
        self.assertIn("passed", self.bot.safe_send_message.call_args.args[1].content)

    async def test_song_author_skip_original_semantics(self):
        self.bot.player.current_entry.author = self.bot.member
        await self.call(BASE + "skip", {})
        self.assertIsNone(self.bot.player.current_entry)
        self.assertFalse(self.bot.player.skip_state.skippers)

    async def test_rate_limit_shared_play_resolve_sessions_guilds(self):
        self.dashboard.USER_REQUESTS_PER_MINUTE = 3
        await self.call(BASE + "resolve", {"query": "one"})
        await self.call(BASE + "play", {"query": "two"})
        await self.call(BASE + "resolve", {"query": "three"})
        self.login_as(43)
        await self.call(BASE + "play", {"query": "four"}, status=429)
        guild2 = NS(id=2, name="Second", unavailable=False, get_member=self.bot.members.get)
        self.bot.guilds.append(guild2)
        self.bot.get_guild = lambda gid: {1: self.bot.guild, 2: guild2}.get(gid)
        await self.call("/api/guilds/2/resolve", {"query": "five"}, status=429)
        await self.call(BASE + "state", method="GET")
        self.login_as(44)
        await self.call(BASE + "resolve", {"query": "independent"})

    async def test_audit_logs_actor_guild_action_without_secrets(self):
        with self.assertLogs("musicbot.web_dashboard", level="INFO") as captured:
            await self.call(BASE + "play", {"query": "search words"})
            self.bot.member_perms.can_use_command.return_value = False
            await self.call(BASE + "pause", {}, status=403)
        output = "\n".join(captured.output)
        for value in ("43", "1", "play", "pause"):
            self.assertIn(value, output)
        for secret in (SECRET, TOKEN, REFRESH, "FAKE-ONLY-SESSION-SECRET"):
            self.assertNotIn(secret, output)
        self.assertNotIn("Friend", output)

    async def test_get_player_await_rechecks_membership_before_mutation(self):
        async def leave_guild(*args, **kwargs):
            self.bot.members.pop(43)
            return self.bot.player
        self.bot.get_player.side_effect = leave_guild
        await self.call(BASE + "pause", {}, status=403)
        self.assertFalse(self.bot.player.is_paused)
        self.bot.safe_send_message.assert_not_awaited()

    async def test_get_player_await_rechecks_replaced_permissions(self):
        async def change_roles(*args, **kwargs):
            changed = copy.copy(self.bot.member_perms)
            changed.can_use_command = Mock(return_value=False)
            self.bot.member_perms = changed
            return self.bot.player
        self.bot.get_player.side_effect = change_roles
        await self.call(BASE + "pause", {}, status=403)
        self.assertFalse(self.bot.player.is_paused)
        self.bot.safe_send_message.assert_not_awaited()

    async def test_resolve_await_rechecks_session_expiry_and_logout(self):
        for reason in ("expiry", "logout"):
            with self.subTest(reason=reason):
                token = self.login_as(43)
                started, release = asyncio.Event(), asyncio.Event()
                async def delayed(*args, **kwargs):
                    started.set()
                    await release.wait()
                    return fixtures.YtdlpResponseDict(self.bot.info)
                self.bot.downloader.extract_info = delayed
                operation = asyncio.create_task(
                    self.call(BASE + "resolve", {"query": "song"}, status=401))
                await asyncio.wait_for(started.wait(), 1)
                try:
                    if reason == "expiry":
                        self.dashboard.sessions[self.dashboard.session_digest(token)]["expires"] = time.monotonic() - 1
                    else:
                        await self.call("/auth/logout", {})
                finally:
                    release.set()
                await operation
                self.assertFalse(self.dashboard.previews)

    async def test_resolve_await_rechecks_membership(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def delayed(*args, **kwargs):
            started.set()
            await release.wait()
            return fixtures.YtdlpResponseDict(self.bot.info)
        self.bot.downloader.extract_info = delayed
        operation = asyncio.create_task(
            self.call(BASE + "resolve", {"query": "song"}, status=403))
        await asyncio.wait_for(started.wait(), 1)
        self.bot.members.pop(43)
        release.set()
        await operation
        self.assertFalse(self.dashboard.previews)

    async def test_resolve_await_rechecks_replaced_play_permissions(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def delayed(*args, **kwargs):
            started.set()
            await release.wait()
            return fixtures.YtdlpResponseDict(self.bot.info)
        self.bot.downloader.extract_info = delayed
        operation = asyncio.create_task(
            self.call(BASE + "resolve", {"query": "song"}, status=403))
        await asyncio.wait_for(started.wait(), 1)
        changed = copy.copy(self.bot.member_perms)
        changed.can_use_command = Mock(return_value=False)
        self.bot.member_perms = changed
        release.set()
        await operation
        self.assertFalse(self.dashboard.previews)

    async def test_repeat_subcommand_denial_is_atomic_before_any_toggle(self):
        self.bot.player.repeatsong = self.bot.player.loopqueue = True
        self.bot.member_perms.can_use_command.side_effect = (
            lambda command, sub="": (command, sub) != ("repeat", "all"))
        await self.call(BASE + "repeat", {"mode": "off"}, status=403)
        self.assertTrue(self.bot.player.repeatsong)
        self.assertTrue(self.bot.player.loopqueue)
        self.bot.safe_send_message.assert_not_awaited()


    def use_real_command_lists(self, whitelist=(), blacklist=(), advanced=False):
        perms = self.bot.member_perms
        perms.command_whitelist, perms.command_blacklist = set(whitelist), set(blacklist)
        perms.advanced_commandlists = advanced
        perms.can_use_command = MethodType(PermissionGroup.can_use_command, perms)

    async def test_real_subcommand_permission_lists_for_volume_move_and_play(self):
        self.use_real_command_lists(whitelist={"volume_30", "move_1", "play_song"}, advanced=True)
        await self.call(BASE + "volume", {"volume": 30})
        await self.call(BASE + "volume", {"volume": 31}, status=403)
        await self.call(BASE + "queue/move", {"from": 1, "to": 2, "revision": await self.rev()})
        await self.call(BASE + "queue/move",
                        {"from": 2, "to": 1, "revision": await self.rev()}, status=403)
        await self.call(BASE + "resolve", {"query": "song words"})
        await self.call(BASE + "play", {"query": "other words"}, status=403)

    async def test_repeat_all_to_off_checks_only_actual_all_subcommand(self):
        self.bot.player.loopqueue = True
        self.use_real_command_lists(whitelist={"repeat_all"}, blacklist={"repeat_off"}, advanced=True)
        result = await self.call(BASE + "repeat", {"mode": "off"})
        self.assertFalse(self.bot.player.loopqueue)
        self.assertIn("no longer repeating", self.bot.safe_send_message.call_args.args[1].content)
        self.bot.safe_send_message.assert_awaited_once()

    async def test_repeat_song_off_sends_existing_response(self):
        self.bot.player.repeatsong = True
        result = await self.call(BASE + "repeat", {"mode": "off"})
        self.assertFalse(self.bot.player.repeatsong)
        self.assertIn("no longer", self.bot.safe_send_message.call_args.args[1].content)
        self.assertTrue(self.bot.safe_send_message.call_args.args[1].description.startswith("-# Friend used the web dashboard"))

    async def test_move_without_current_entry_does_not_mutate(self):
        self.bot.player.current_entry = None
        before = list(self.bot.player.playlist.entries)
        await self.call(BASE + "queue/move",
                        {"from": 1, "to": 2, "revision": await self.rev()}, status=409)
        self.assertEqual(list(self.bot.player.playlist.entries), before)
        self.bot.serialize_queue.assert_not_awaited()

    async def test_plaintext_response_retains_caller_attribution(self):
        self.bot.config.embeds = False
        result = await self.call(BASE + "volume", {"volume": 30})
        response = self.bot.safe_send_message.call_args.args[1]
        self.assertTrue(response.to_markdown().startswith("-# Friend used the web dashboard"))
        self.assertNotIn("<@", response.to_markdown())
        self.assertEqual(result["message"], "已完成操作。")
        self.assertIn("Updated volume", response.content)

    async def test_get_player_await_rechecks_voice_and_session(self):
        for change, status in (("voice", 403), ("session", 401)):
            with self.subTest(change=change):
                token = self.login_as(43)
                self.bot.member.voice = NS(channel=self.bot.channel)
                async def changed(*args, **kwargs):
                    if change == "voice":
                        self.bot.member.voice = NS(channel=NS(id=99))
                    else:
                        self.dashboard.sessions.pop(self.dashboard.session_digest(token))
                    return self.bot.player
                self.bot.get_player.side_effect = changed
                await self.call(BASE + "pause", {}, status=status)
                self.assertFalse(self.bot.player.is_paused)
        self.bot.safe_send_message.assert_not_awaited()

    async def test_queued_operation_rechecks_revoked_session(self):
        async with self.dashboard.locks[1]:
            started = asyncio.Event()
            old_payload = self.dashboard.payload
            async def payload(request):
                data = await old_payload(request)
                started.set()
                return data
            self.dashboard.payload = payload
            operation = asyncio.create_task(self.call(BASE + "pause", {}, status=401))
            await asyncio.wait_for(started.wait(), 1)
            await self.call("/auth/logout", {})
        await operation
        self.assertFalse(self.bot.player.is_paused)
        self.bot.get_player.assert_not_awaited()

    async def test_rate_limit_allows_again_after_rolling_window(self):
        self.dashboard.USER_REQUESTS_PER_MINUTE = 1
        await self.call(BASE + "resolve", {"query": "first"})
        await self.call(BASE + "play", {"query": "second"}, status=429)
        self.dashboard.rate_limits[43] = [time.monotonic() - 61]
        await self.call(BASE + "play", {"query": "third"})

    async def test_new_login_rotates_existing_session_and_replay_fails(self):
        old = self.login_as(43)
        _, _, state = await self.begin_oauth()
        response = await self.finish_oauth(state)
        self.assertEqual(response.status, 302)
        self.assertNotIn(self.dashboard.session_digest(old), self.dashboard.sessions)
        self.client.session.cookie_jar.update_cookies(
            {self.dashboard.session_cookie: old}, response_url=self.client.make_url("/"))
        await self.call("/api/guilds", method="GET", status=401)

    async def test_login_audit_never_contains_provider_credentials(self):
        self.client.session.cookie_jar.clear()
        with self.assertLogs("musicbot.web_dashboard", level="INFO") as captured:
            _, _, state = await self.begin_oauth()
            self.assertEqual((await self.finish_oauth(state)).status, 302)
        output = "\n".join(captured.output)
        self.assertIn("action=callback status=302", output)
        self.assertIn("user=43", output)
        for secret in (SECRET, TOKEN, REFRESH, state, "FAKE-CODE"):
            self.assertNotIn(secret, output)



class DiscordConfigTests(unittest.IsolatedAsyncioTestCase):
    def config(self):
        return DashboardConfig(auth_mode="discord", public_url="https://music.example.test",
            discord_client_id="123", discord_client_secret=SECRET,
            session_secret="FAKE-ONLY-SESSION-SECRET")

    async def test_required_configs_fail_closed_without_stopping_bot(self):
        bot = DiscordBot()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "web_dashboard.ini"
            for extra in ("", "PublicURL=https://music.example.test\n",
                "PublicURL=http://public.example.test\nDiscordClientSecret=" + SECRET,
                "PublicURL=https://music.example.test/path\nDiscordClientSecret=" + SECRET,
                "PublicURL=https://music.example.test\nDiscordClientSecret=" + SECRET +
                "\nSessionHours=nan"):
                path.write_text("[WebDashboard]\nEnabled=yes\nAuthMode=discord\n" + extra)
                with self.assertLogs("musicbot.web_dashboard", level="ERROR") as captured:
                    self.assertIsNone(await start_dashboard(bot, path))
                self.assertNotIn(SECRET, repr(captured.output))
                self.assertFalse(bot.logout_called)

    async def test_empty_client_id_uses_bot_application(self):
        bot = DiscordBot()
        dashboard = Dashboard(bot, dataclasses.replace(self.config(), discord_client_id=""))
        self.assertEqual(dashboard.client_id, "123")
        await dashboard.close()

    async def test_opaque_sessions_need_no_signing_key_and_repr_redacts_legacy_secret(self):
        bot = DiscordBot()
        config = dataclasses.replace(self.config(), session_secret="")
        first, second = Dashboard(bot, config), Dashboard(bot, config)
        self.assertFalse(hasattr(first, "session_key"))
        self.assertFalse(hasattr(second, "session_key"))
        self.assertNotIn(SECRET, repr(config))
        self.assertNotIn("FAKE-ONLY-SESSION-SECRET", repr(self.config()))
        await first.close()
        await second.close()


if __name__ == "__main__":
    unittest.main()
