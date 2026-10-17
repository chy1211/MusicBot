"""Offline stream admission and disconnected-transport regressions."""
import asyncio
import unittest
from test_web_dashboard import BASE
import test_web_dashboard_round6 as fixtures

class Round16EventsTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.Round6Tests.asyncSetUp
    asyncTearDown = fixtures.Round6Tests.asyncTearDown
    login_as = fixtures.Round6Tests.login_as
    provider_token = fixtures.Round6Tests.provider_token
    provider_me = fixtures.Round6Tests.provider_me
    stream = fixtures.Round6Tests.stream
    frame = fixtures.Round6Tests.frame

    async def test_two_tabs_and_three_users_same_guild_same_ip(self):
        responses = []
        try:
            for uid in [43, 43, 42, 44]:
                self.login_as(uid)
                response = await self.stream()
                await self.frame(response)
                responses.append(response)
            self.assertEqual(len(self.dashboard.stream_users), 4)
            self.assertEqual(list(self.dashboard.stream_users.values()).count(43), 2)
        finally:
            for response in responses: response.close()

    async def test_idle_disconnected_stream_releases_before_heartbeat(self):
        response = await self.stream()
        self.dashboard.HEARTBEAT_INTERVAL = 3600
        await self.frame(response)
        response.close()
        for _ in range(50):
            if not self.dashboard.stream_users: break
            await asyncio.sleep(.01)
        self.assertFalse(self.dashboard.stream_users)
        self.assertFalse(self.dashboard.stream_transports)

    async def test_reconnect_churn_does_not_exhaust_slots(self):
        self.dashboard.HEARTBEAT_INTERVAL = 3600
        for _ in range(12):
            response = await self.stream()
            await self.frame(response)
            response.close()
            await asyncio.sleep(.01)
        self.assertLessEqual(len(self.dashboard.stream_users), 1)
