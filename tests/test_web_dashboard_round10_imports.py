"""Unified homepage playlist resolve/save with server-owned selections."""
import unittest
import test_web_dashboard_imports as fixtures
from musicbot.web_dashboard_library import PlaylistStore

class UnifiedTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ImportTests.asyncSetUp
    asyncTearDown = fixtures.ImportTests.asyncTearDown
    call = fixtures.ImportTests.call
    login_as = fixtures.ImportTests.login_as
    provider_token = fixtures.ImportTests.provider_token
    provider_me = fixtures.ImportTests.provider_me

    async def test_homepage_resolve_selected_save_remembers_source(self):
        self.bot.downloader.extract_info.return_value = {"title":"Public list","entries":[fixtures.video(1),fixtures.video(2)]}
        result = await self.call("/api/guilds/1/resolve", {"query":fixtures.YTM})
        value = result["results"][0]
        self.assertEqual(len(value["entries"]), 2)
        self.assertEqual(value["source_url"], fixtures.YT)
        saved = await self.call("/api/library/import", {"preview_id":value["preview_id"],
            "revision":value["save_revision"], "name":"Selected","selected_items":["2"]})
        self.assertEqual(len(saved["playlists"][-1]["tracks"]),1)
        self.assertEqual(saved["playlists"][-1]["tracks"][0]["url"], fixtures.video(2)["url"].replace("music.youtube.com","www.youtube.com"))
        self.assertEqual(saved["playlists"][-1]["source_url"],fixtures.YT)
        await self.call("/api/library/import", {"preview_id":value["preview_id"],
            "revision":value["save_revision"],"name":"Replay","selected_items":["2"]},status=409)

    async def test_unsafe_selection_and_other_user_cannot_save(self):
        value = (await self.call("/api/guilds/1/resolve", {"query":fixtures.YTM}))["results"][0]
        data = {"preview_id":value["preview_id"],"revision":value["save_revision"],"name":"Bad","selected_items":["999"]}
        await self.call("/api/library/import", data,status=400)
        self.login_as(42)
        data["selected_items"]=["1"]
        await self.call("/api/library/import", data,status=409)
