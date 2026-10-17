import json
import unittest
import test_web_dashboard_library as fixtures
from musicbot.web_dashboard_library import song

class FavoritesTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.LibraryTests.asyncSetUp
    asyncTearDown=fixtures.LibraryTests.asyncTearDown
    call=fixtures.LibraryTests.call
    login_as=fixtures.LibraryTests.login_as
    provider_token=fixtures.LibraryTests.provider_token
    provider_me=fixtures.LibraryTests.provider_me
    get=fixtures.LibraryTests.get
    add=fixtures.LibraryTests.add

    async def test_youtube_identity_dedup_and_url_removal(self):
        first = await self.add(track=dict(fixtures.TRACK,url="https://youtu.be/video000001?t=3"))
        value = await self.add(track=dict(fixtures.TRACK,url="https://music.youtube.com/watch?v=video000001&si=abc"))
        self.assertEqual(len(value["playlists"][0]["tracks"]),1)
        self.assertEqual(value["message"],"已在收藏中")
        value = await self.call("/api/library/favorites",{"revision":value["revision"],"action":"remove_url",
            "url":"https://www.youtube.com/watch?v=video000001"},"PATCH")
        self.assertEqual(value["playlists"][0]["tracks"],[])
        self.assertEqual(value["message"],"已取消收藏")

    async def test_other_user_cannot_remove_and_legacy_duplicates_read_then_clean(self):
        await self.add()
        store=self.dashboard.playlist_store
        value=store.read(43)
        value["playlists"][0]["tracks"] *= 2
        store.path(43).write_text(json.dumps(value))
        self.assertEqual(len((await self.get())["playlists"][0]["tracks"]),2)
        self.login_as(42)
        v=await self.get()
        await self.call("/api/library/favorites",{"revision":v["revision"],"action":"remove_url","url":fixtures.TRACK["url"]},"PATCH")
        self.assertEqual(len(store.read(43)["playlists"][0]["tracks"]),2)
        self.login_as(43)
        result=await self.add()
        self.assertEqual(len(result["playlists"][0]["tracks"]),1)
