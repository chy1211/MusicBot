import unittest
from aiohttp.test_utils import TestClient,TestServer
from test_web_dashboard_discord import DiscordBot
from musicbot.web_dashboard import Dashboard,DashboardConfig
class HealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_healthz_is_public_constant_and_not_bot_readiness(self):
        bot=DiscordBot()
        dash=Dashboard(bot,DashboardConfig(auth_mode="discord",public_url="http://localhost",
                         discord_client_id="123",discord_client_secret="FAKE_HEALTH_SECRET"))
        async with TestClient(TestServer(dash.app)) as client:
            r=await client.get("/healthz")
            self.assertEqual(r.status,200);self.assertEqual(await r.json(),{"status":"ok"})
            self.assertNotIn("Set-Cookie",r.headers)
            self.assertNotIn("FAKE_HEALTH_SECRET",await r.text())
            bot.init_ok=False;bot.logout_called=True
            r=await client.get("/healthz")
            self.assertEqual(r.status,200);self.assertEqual(await r.json(),{"status":"ok"})
