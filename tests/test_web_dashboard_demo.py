"""Credential-free fake-login demo integration; all HTTP stays on loopback."""
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock

from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer

from musicbot.web_dashboard import DashboardConfig
from tools.dashboard_demo import DemoBot, DemoDashboard

HEADERS = {"X-MusicBot-Dashboard": "1"}
BASE = "/api/guilds/1/"


class DemoTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = DemoBot("http://127.0.0.1")
        self.dashboard = DemoDashboard(self.bot, DashboardConfig(
            auth_mode="discord", public_url="http://127.0.0.1",
            discord_client_id="1000", discord_client_secret="not-a-credential"))
        self.client = TestClient(TestServer(self.dashboard.app), cookie_jar=CookieJar(unsafe=True))
        await self.client.start_server()
        self.dashboard.config = replace(self.dashboard.config,
                                        public_url=str(self.client.make_url("/")).rstrip("/"))
        self.dashboard.oauth_identity = AsyncMock(side_effect=AssertionError("No OAuth in demo"))

    async def asyncTearDown(self):
        self.dashboard.oauth_identity.assert_not_awaited()
        await self.client.close()

    async def login(self, user):
        response = await self.client.post("/demo-login/" + user, allow_redirects=False)
        self.assertEqual(response.status, 302)
        profile = await (await self.client.get("/auth/session")).json()
        self.assertTrue(profile["authenticated"])
        return profile["user"]

    async def call(self, path, data=None, method="POST", status=200):
        response = await self.client.request(method, path, json=data, headers=HEADERS)
        body = await response.json()
        self.assertEqual(response.status, status, body)
        return body

    async def test_default_is_unauthenticated_with_picker(self):
        await self.call("/api/guilds", method="GET", status=401)
        page = await (await self.client.get("/auth/login")).text()
        for user in ("owner", "member", "away", "denied"):
            self.assertIn("/demo-login/" + user, page)
        await self.call(BASE + "state", method="GET", status=401)

    async def test_owner_and_member_see_distinct_permissions(self):
        self.assertEqual((await self.login("owner"))["id"], "42")
        owner = await self.call(BASE + "resolve", {"query": "https://example.test/playlist"})
        self.assertTrue(owner["results"][0]["allowed"])
        await self.call("/auth/logout", {})
        self.assertEqual((await self.login("member"))["id"], "43")
        member = await self.call(BASE + "resolve", {"query": "https://example.test/playlist"})
        self.assertFalse(member["results"][0]["allowed"])

    async def test_away_member_can_read_but_cannot_pause(self):
        await self.login("away")
        await self.call(BASE + "state", method="GET")
        await self.call(BASE + "pause", {}, status=409)

    async def test_denied_member_sees_reason_and_can_read(self):
        await self.login("denied")
        await self.call(BASE + "state", method="GET")
        await self.call(BASE + "resolve", {"query": "song"}, status=403)
        await self.call(BASE + "pause", {}, status=403)

    async def test_member_cannot_remove_owner_but_can_remove_own(self):
        await self.login("member")
        state = await self.call(BASE + "state", method="GET")
        await self.call(BASE + "queue/1", {"revision": state["revision"]}, "DELETE", 403)
        await self.call(BASE + "queue/2", {"revision": state["revision"]}, "DELETE")
        self.assertEqual(len(self.bot.players[1].playlist.entries), 3)

    async def test_real_skip_vote_is_not_instant(self):
        await self.login("member")
        current = self.bot.players[1].current_entry
        result = await self.call(BASE + "skip", {})
        self.assertIs(self.bot.players[1].current_entry, current)
        self.assertEqual(self.bot.players[1].skip_state.skippers, {43})
        self.assertIn("vote", result["message"])

    async def test_explicit_fake_login_and_owner_mode(self):
        self.dashboard.fake_login = "away"
        response = await self.client.get("/auth/login", allow_redirects=False)
        self.assertEqual(response.status, 302)
        profile = await (await self.client.get("/auth/session")).json()
        self.assertEqual(profile["user"]["id"], "44")
        self.dashboard.config = replace(self.dashboard.config, auth_mode="owner")
        self.client.session.cookie_jar.clear()
        await self.call("/api/guilds", method="GET")
        await self.call(BASE + "pause", {})
