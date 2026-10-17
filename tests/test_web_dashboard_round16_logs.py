"""Every registered route has an explicit operation-log policy."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from test_web_dashboard_discord import DiscordTests as Fixtures

class Round16LogTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = Fixtures.asyncSetUp
    asyncTearDown = Fixtures.asyncTearDown
    login_as = Fixtures.login_as
    provider_token = Fixtures.provider_token
    provider_me = Fixtures.provider_me

    async def test_every_registered_route_is_named_or_explicitly_excluded(self):
        dashboard = self.dashboard
        registered = set()
        for route in dashboard.app.router.routes():
            path = route.resource.canonical
            registered.add(path)
            request = NS(match_info=NS(route=route))
            action = dashboard.request_action(request)
            if path in dashboard.NO_OPERATION_ROUTES:
                self.assertIsNone(action, (route.method, path))
            else:
                self.assertIn(path, dashboard.OPERATION_ROUTES, (route.method, path))
                self.assertNotIn(action, (None, "unknown", "unmatched"))
        self.assertEqual(registered, set(dashboard.OPERATION_ROUTES) | dashboard.NO_OPERATION_ROUTES)
        self.assertFalse(set(dashboard.OPERATION_ROUTES) & dashboard.NO_OPERATION_ROUTES)

    async def test_noise_routes_do_not_create_operation_logs(self):
        with patch("musicbot.web_dashboard.log.info") as info:
            for path in ["/", "/healthz", "/ui-config", "/auth/session", "/dashboard.js", "/i18n/en.json"]:
                response = await self.client.get(path)
                await response.read()
            info.assert_not_called()

    async def test_operation_names_do_not_include_query_cookie_or_token(self):
        with self.assertLogs("musicbot.web_dashboard", level="INFO") as captured:
            response = await self.client.get("/api/library?token=PRIVATE_QUERY", headers={
                "X-MusicBot-Dashboard":"1", "Authorization":"Bearer PRIVATE_TOKEN"})
            await response.read()
        text = "\n".join(captured.output)
        self.assertIn("action=library status=200", text)
        self.assertNotIn("PRIVATE", text)
        self.assertNotIn(self.dashboard.session_cookie, text)
        self.assertNotIn("unknown", text)
