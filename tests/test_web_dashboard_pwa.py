"""Public static PWA resources without credentials or live network."""
import json
import struct
import unittest
import test_web_dashboard as base


class PWATests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = base.DashboardTests.asyncSetUp
    asyncTearDown = base.DashboardTests.asyncTearDown

    async def test_manifest(self):
        response = await self.client.get("/manifest.webmanifest")
        self.assertEqual(response.status, 200)
        self.assertIn("application/manifest+json", response.headers["Content-Type"])
        value = await response.json(content_type=None)
        self.assertEqual(value["name"], "Music dashboard")
        self.assertEqual((value["start_url"], value["scope"], value["display"]), ("/", "/", "standalone"))
        self.assertEqual({icon["sizes"] for icon in value["icons"]}, {"any", "192x192", "512x512"})

    async def test_icons_dimensions_and_size(self):
        for filename, size in (("icon-192.png", 192), ("icon-512.png", 512), ("apple-touch-icon.png", 180)):
            response = await self.client.get("/" + filename)
            raw = await response.read()
            self.assertEqual(response.status, 200)
            self.assertEqual(raw[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", raw[16:24]), (size, size))
            self.assertLess(len(raw), 5000)
        self.assertEqual((await self.client.get("/favicon.svg")).status, 200)

    async def test_html_worker_and_offline_assets(self):
        page = await (await self.client.get("/")).text()
        for item in ("apple-mobile-web-app-capable", "apple-touch-icon", "manifest.webmanifest", "/pwa.js"):
            self.assertIn(item, page)
        for path in ("/sw.js", "/pwa.js", "/offline.html", "/library.js", "/admin.js", "/permissions.js"):
            response = await self.client.get(path)
            self.assertEqual(response.status, 200)
        self.assertIn("You are offline", await (await self.client.get("/offline.html")).text())
        self.assertEqual((await self.client.get("/secret.png")).status, 404)
