"""Round 9 offline regression tests for core dashboard behavior."""
import unittest
from unittest.mock import AsyncMock

import test_web_dashboard as base
from test_web_dashboard import BASE
from test_web_dashboard_round5 import seek_entry


class SeekRoundingTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = base.DashboardTests.asyncSetUp
    asyncTearDown = base.DashboardTests.asyncTearDown
    call = base.DashboardTests.call

    async def test_seek_half_up_reports_exact_integer_in_response_and_activity(self):
        for position, rounded in ((83.456, 83), (82.5, 83), (0.49, 0), (179.5, 180)):
            current = seek_entry(self.bot)
            await self.call(BASE + "seek", {"position": position})
            self.assertEqual(current.start_time, rounded)
            activity = self.dashboard.activities[1][0]
            self.assertEqual(activity["detail"], f"\u8df3\u8f49\uff1a{rounded} \u79d2")
