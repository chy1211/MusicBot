"""Only the pre-paint theme bootstrap is permitted as an inline script."""
import base64
import hashlib
import re
import unittest
from pathlib import Path
import test_web_dashboard as base


class ThemeBootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from dashboard_static_fixture import dashboard_static
        self.static = self.enterContext(dashboard_static())
        await base.DashboardTests.asyncSetUp(self)
    asyncTearDown = base.DashboardTests.asyncTearDown

    async def test_bootstrap_hash_matches_source_and_served_html(self):
        response = await self.client.get("/")
        self.assertEqual(response.status, 200)
        html = await response.text()
        source = (Path(__file__).resolve().parents[1] / "frontend/index.html").read_text()
        script = re.search(r"<script>(.*?)</script>", source, re.S).group(1)
        self.assertIn("<script>" + script + "</script>", html)
        digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        csp = response.headers["Content-Security-Policy"]
        self.assertIn("script-src 'self' 'sha256-" + digest + "'", csp)
        self.assertNotIn("'unsafe-inline'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertLess(html.index("<script>" + script), html.index('type="module"'))
