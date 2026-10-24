"""Split-module and built-static regressions using only disposable fixtures."""
import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import test_web_dashboard as base
from musicbot.web_dashboard import Dashboard, APIError, DashboardConfig, CONFIRMED_ENTRY_CHECK

class ModuleTests(unittest.TestCase):
    def test_route_methods_are_extracted_and_original_exports_remain(self):
        expected={"index":"static","guilds":"identity_history","lyrics":"lyrics","snapshot":"state","resolve":"resolve","mutate":"mutation"}
        for method,module in expected.items():
            self.assertEqual(getattr(Dashboard,method).__module__,"musicbot.dashboard_backend."+module)
        self.assertIs(importlib.import_module("musicbot.web_dashboard").APIError,APIError)
        self.assertTrue(callable(DashboardConfig.load))
        self.assertEqual(CONFIRMED_ENTRY_CHECK.get(),None)
    def test_management_and_all_original_capabilities_are_inherited(self):
        for method in ("init_admin","init_library","init_auth","events","mutate","resolve","lyrics_offset","start","close"):
            self.assertTrue(callable(getattr(Dashboard,method)),method)

class BuiltStaticTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=base.DashboardTests.asyncSetUp
    asyncTearDown=base.DashboardTests.asyncTearDown
    async def test_built_entry_and_hashed_assets_are_immutable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);built=root/"dist";assets=built/"assets";assets.mkdir(parents=True)
            (root/"index.html").write_text("legacy")
            (built/"index.html").write_text("vue fixture")
            (assets/"index-r27.js").write_text("export {}")
            with patch("musicbot.web_dashboard.STATIC",root):
                response=await self.client.get("/")
                self.assertEqual(response.status,200);self.assertEqual(await response.text(),"vue fixture")
                response=await self.client.get("/assets/index-r27.js")
                self.assertEqual(response.status,200);self.assertIn("immutable",response.headers["Cache-Control"])
                self.assertIn("javascript",response.headers["Content-Type"])
                self.assertEqual((await self.client.get("/assets/not-found.js")).status,404)
                for name in ("dashboard.js", "admin.js", "library.js", "popular.js", "permissions.js"):
                    self.assertFalse((built/name).exists())
                    response=await self.client.get("/"+name)
                    self.assertEqual(response.status,200)
                    self.assertIn("javascript",response.headers["Content-Type"])
                    self.assertIn("location.replace('/')",await response.text())
    async def test_worker_and_offline_resources_use_correct_headers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);built=root/"dist";built.mkdir()
            for name,text in {"index.html":"vue","sw.js":"/* worker */","offline.js":"/* language */","offline.css":"body {}"}.items():
                (built/name).write_text(text)
            with patch("musicbot.web_dashboard.STATIC",root):
                response=await self.client.get("/sw.js")
                self.assertEqual(response.status,200);self.assertEqual(response.headers["Cache-Control"],"no-cache")
                for url,kind in (("/offline.js","javascript"),("/offline.css","text/css")):
                    response=await self.client.get(url)
                    self.assertEqual(response.status,200);self.assertIn(kind,response.headers["Content-Type"])
    async def test_asset_traversal_never_reads_outside_built_assets(self):
        for url in ("/assets/%2e%2e%2fweb_dashboard.py","/assets/%2fetc%2fpasswd","/assets/no-file.js"):
            response=await self.client.get(url)
            self.assertEqual(response.status,404,url)
            self.assertNotIn("root:",await response.text())

    async def test_missing_dist_returns_503_even_with_unbuilt_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "index.html").write_text("unbuilt source must never be served")
            (root / "dashboard.js").write_text("unbuilt script must never be served")
            with patch("musicbot.web_dashboard.STATIC", root):
                response = await self.client.get("/")
                self.assertEqual(response.status, 503)
                self.assertEqual(await response.text(), "dashboard frontend is not built\n")
                self.assertIn("text/plain", response.headers["Content-Type"])
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertEqual((await self.client.get("/dashboard.js")).status, 404)
                self.assertEqual((await self.client.get("/healthz")).status, 200)

    async def test_catalogs_are_available_without_dist_and_match_public_source(self):
        import json
        with tempfile.TemporaryDirectory() as temporary:
            with patch("musicbot.web_dashboard.STATIC", Path(temporary)):
                for locale in ("en", "zh-TW"):
                    response = await self.client.get("/i18n/" + locale + ".json")
                    self.assertEqual(response.status, 200)
                    source = Path(__file__).resolve().parents[1] / "frontend/public/i18n" / (locale + ".json")
                    self.assertEqual(await response.json(), json.loads(source.read_text()))
