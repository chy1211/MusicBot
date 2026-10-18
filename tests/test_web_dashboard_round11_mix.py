"""Mix fallback and stable playlists, no network."""
import asyncio
import unittest
from unittest.mock import AsyncMock
import test_web_dashboard_imports as f

class MixTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=f.ImportTests.asyncSetUp
    asyncTearDown=f.ImportTests.asyncTearDown
    call=f.ImportTests.call
    login_as=f.ImportTests.login_as
    provider_token=f.ImportTests.provider_token
    provider_me=f.ImportTests.provider_me

    def extraction(self, failure=None):
        async def extract(url, **kw):
            if "/watch?" in url and "&list=" not in url:
                assert kw.get("public_only"), "Mix seed must be credential-free"
                return dict(f.video(1),webpage_url=f.video(1)["url"],extractor="youtube")
            if failure: raise failure
            return {"title":"Mix","entries":[f.video(i) for i in range(2,40)]+[f.video(1)]}
        self.bot.downloader.extract_info=AsyncMock(side_effect=extract)

    async def preview(self, ident="RDdemo", host="www.youtube.com"):
        return (await self.call("/api/guilds/1/resolve",{"query":"https://"+host+"/watch?v=video000001&list="+ident}))["results"][0]

    async def test_mix_seed_first_dedup_cap_default_selection(self):
        for ident in ("RDdemo","RDMMdemo","RDAMVMdemo"):
            self.extraction()
            value=await self.preview(ident)
            self.assertEqual(len(value["entries"]),25)
            self.assertIn("video000001",value["entries"][0]["url"])
            self.assertTrue(value["entries"][0]["is_requested"])
            self.assertEqual(sum(t["default_selected"] for t in value["entries"]),1)
            self.assertFalse(value["source_url"])
            self.assertTrue(value["saveable"])
            args,kw=self.bot.downloader.extract_info.call_args
            self.assertIn("/watch?",args[0]); self.assertEqual(kw["public_limit"],25)

    async def test_failed_and_timed_out_mix_returns_seed(self):
        for error in (RuntimeError("unviewable"),asyncio.TimeoutError()):
            self.extraction(error); value=await self.preview()
            self.assertEqual(len(value["entries"]),1)
            self.assertTrue(value["allowed"])

    async def test_failed_seed_still_shows_playable_canonical_single(self):
        self.bot.downloader.extract_info=AsyncMock(side_effect=RuntimeError())
        value=await self.preview()
        self.assertEqual(value["entries"][0]["title"],"video000001")
        self.assertIn("watch?v=video000001",value["entries"][0]["url"])

    async def test_mix_save_has_no_sync_source(self):
        self.extraction(); value=await self.preview()
        saved=await self.call("/api/library/import",{"preview_id":value["preview_id"],"revision":value["save_revision"],"selected_items":["1","3"],"name":"Mix"})
        playlist=saved["playlists"][-1]
        self.assertEqual(len(playlist["tracks"]),2); self.assertNotIn("source_url",playlist)
        await self.call("/api/guilds/1/library/"+playlist["id"]+"/sync/preview",{"revision":saved["revision"]},status=400)

    async def test_stable_playlists_and_rdclak_default_all_and_sync(self):
        for ident,host in (("PLdemo","www.youtube.com"),("OLAKdemo","www.youtube.com"),("PLdemo","music.youtube.com"),("RDCLAKdemo","music.youtube.com")):
            self.extraction(); value=await self.preview(ident,host)
            self.assertTrue(value["source_url"])
            self.assertFalse(value["is_mix"])
            self.assertTrue(all(t["default_selected"] for t in value["entries"]))

    async def test_rdclak_failure_is_non_syncable_single(self):
        self.extraction(RuntimeError()); value=await self.preview("RDCLAKdemo")
        self.assertTrue(value["is_mix"]); self.assertEqual(len(value["entries"]),1)
