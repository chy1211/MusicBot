import json,unittest,asyncio
from pathlib import Path
from aiohttp.test_utils import TestClient,TestServer
from musicbot.web_dashboard import Dashboard,DashboardConfig
from musicbot.web_dashboard_i18n import LANGUAGE,message
from tools.check_dashboard_i18n import check
from test_web_dashboard import FakeBot
class CatalogTests(unittest.TestCase):
    def test_catalogs(self):self.assertGreater(check(),500)
    def test_parameter_text_is_never_formatted_again(self):
        token=LANGUAGE.set("en")
        try:self.assertEqual(message("m0399",p0="{p1}",p1=0,p2=10),"{p1} must be an integer between 0 and 10.")
        finally:LANGUAGE.reset(token)
    def test_unknown_exception_is_hidden(self):
        from musicbot.web_dashboard import denial_text
        self.assertNotIn("FAKE_SECRET",denial_text("FAKE_SECRET 中文 extractor URL"))
    def test_gettext_notifications_and_summon_in_both_languages(self):
        import tempfile,gettext
        from tools.po2mo import parse_po,write_mo
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="musicbot-webtest-gettext-") as tmp:
            target=Path(tmp)/"messages.mo"
            write_mo(list(parse_po((root/"i18n/zh_TW/LC_MESSAGES/musicbot_messages.po").read_text())),target)
            with target.open("rb") as stream: zh=gettext.GNUTranslations(stream)
            self.assertEqual(zh.gettext("Web dashboard: %(url)s") % {"url":"https://music.example.com"},"網頁控制台：https://music.example.com")
            self.assertIn("網頁控制台點歌",zh.gettext("%(name)s requested music via the web dashboard"))
            self.assertEqual(gettext.NullTranslations().gettext("Web dashboard: %(url)s"),"Web dashboard: %(url)s")
class LanguageAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_request_languages_and_public_defaults(self):
        bot=FakeBot();dash=Dashboard(bot,DashboardConfig())
        async with TestClient(TestServer(dash.app)) as client:
            r=await client.get("/ui-config")
            self.assertEqual(await r.json(),{"default_language":"en","time_zone":"UTC"})
            for locale,needle in [("en","Please use"),("zh-TW","請從")]:
                r=await client.get("/api/guilds",headers={"X-Dashboard-Language":locale})
                self.assertEqual(r.status,403);self.assertIn(needle,(await r.json())["error"])
                self.assertEqual(r.headers["Content-Language"],locale)
            r=await client.get("/api/guilds")
            self.assertIn("Please use",(await r.json())["error"])
            r=await client.get("/i18n/../../config/options.ini")
            self.assertGreaterEqual(r.status,400)
