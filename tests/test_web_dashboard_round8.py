"""Viewer-specific control hints; all real mutation authorization remains active."""
import unittest
from types import SimpleNamespace as NS
from dataclasses import replace
from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer
from musicbot.web_dashboard import Dashboard, DashboardConfig
from tests import test_web_dashboard_discord as fixtures
BASE = fixtures.BASE


class CapabilitiesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = fixtures.DiscordBot()
        self.dashboard = Dashboard(self.bot, DashboardConfig(
            auth_mode="discord", public_url="http://localhost",
            discord_client_id="123", discord_client_secret="demo-not-a-credential"))
        self.client = TestClient(TestServer(self.dashboard.app), cookie_jar=CookieJar(unsafe=True))
        await self.client.start_server()
        self.origin = str(self.client.make_url("/")).rstrip("/")
        self.dashboard.config = replace(self.dashboard.config, public_url=self.origin)

    async def asyncTearDown(self):
        await self.client.close()
        await self.dashboard.close()

    login_as = fixtures.DiscordTests.login_as
    call = fixtures.DiscordTests.call
    async def test_capabilities_only_describe_current_viewer(self):
        self.login_as(43)
        self.bot.member_perms.can_use_command.side_effect = lambda command, sub="": command != "seek"
        result = await self.call(BASE + "state", method="GET")
        self.assertEqual(result["capabilities"], {"pause": True, "resume": True, "skip": True, "seek": False})
        self.assertTrue(all(type(v) is bool for v in result["capabilities"].values()))
        self.assertFalse(self.bot.get_player.called)
        await self.call(BASE + "seek", {"position": 10}, status=403)

    async def test_voice_and_live_command_revocation_disable_capabilities(self):
        self.login_as(43)
        self.bot.member.voice = None
        result = await self.call(BASE + "state", method="GET")
        self.assertFalse(any(result["capabilities"].values()))
        self.bot.member.voice = NS(channel=self.bot.channel)
        self.bot.member_perms.can_use_command.return_value = False
        result = await self.call(BASE + "state", method="GET")
        self.assertFalse(any(result["capabilities"].values()))

    async def test_owner_bypass_and_sse_use_same_capabilities(self):
        self.login_as(42)
        self.bot.perms.can_use_command.return_value = False
        expected = {"pause": True, "resume": True, "skip": True, "seek": True}
        result = await self.call(BASE + "state", method="GET")
        self.assertEqual(result["capabilities"], expected)
        self.assertEqual(self.dashboard.event_snapshot(self.bot.guild, self.bot.owner)["state"]["capabilities"], expected)
