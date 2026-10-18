"""Credential-free fake-login demo integration; all HTTP stays on loopback."""
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock

from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer

from musicbot.web_dashboard import DashboardConfig
from tools.dashboard_demo import DemoBot, DemoDashboard

HEADERS = {"X-MusicBot-Dashboard": "1", "X-Dashboard-Language": "zh-TW"}
BASE = "/api/guilds/1/"


class DemoTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = DemoBot("http://127.0.0.1")
        self.dashboard = DemoDashboard(self.bot, DashboardConfig(
            auth_mode="discord", public_url="http://127.0.0.1",
            discord_client_id="1000", discord_client_secret="not-a-credential"))
        self.client = TestClient(TestServer(self.dashboard.app), headers={"Accept-Language":"zh-TW"}, cookie_jar=CookieJar(unsafe=True))
        await self.client.start_server()
        self.dashboard.config = replace(self.dashboard.config,
                                        public_url=str(self.client.make_url("/")).rstrip("/"))
        self.dashboard.oauth_identity = AsyncMock(side_effect=AssertionError("No OAuth in demo"))

    async def asyncTearDown(self):
        self.dashboard.oauth_identity.assert_not_awaited()
        await self.client.close()

    async def login(self, user):
        response = await self.client.post("/demo-login/" + user, allow_redirects=False)
        self.assertEqual(response.status, 302)
        profile = await (await self.client.get("/auth/session")).json()
        self.assertTrue(profile["authenticated"])
        return profile["user"]

    async def call(self, path, data=None, method="POST", status=200):
        response = await self.client.request(method, path, json=data, headers=HEADERS)
        body = await response.json()
        self.assertEqual(response.status, status, body)
        return body

    async def test_default_is_unauthenticated_with_picker(self):
        await self.call("/api/guilds", method="GET", status=401)
        page = await (await self.client.get("/auth/login")).text()
        for user in ("owner", "member", "away", "denied"):
            self.assertIn("/demo-login/" + user, page)
        await self.call(BASE + "state", method="GET", status=401)

    async def test_owner_and_member_see_distinct_permissions(self):
        self.assertEqual((await self.login("owner"))["id"], "42")
        owner = await self.call(BASE + "resolve", {"query": "https://soundcloud.com/example/playlist"})
        self.assertTrue(owner["results"][0]["allowed"])
        await self.call("/auth/logout", {})
        self.assertEqual((await self.login("member"))["id"], "43")
        member = await self.call(BASE + "resolve", {"query": "https://soundcloud.com/example/playlist"})
        self.assertFalse(member["results"][0]["allowed"])

    async def test_away_member_can_read_but_cannot_pause(self):
        await self.login("away")
        await self.call(BASE + "state", method="GET")
        await self.call(BASE + "pause", {}, status=409)

    async def test_denied_member_sees_reason_and_can_read(self):
        await self.login("denied")
        await self.call(BASE + "state", method="GET")
        await self.call(BASE + "resolve", {"query": "song"}, status=403)
        await self.call(BASE + "pause", {}, status=403)

    async def test_member_cannot_remove_owner_but_can_remove_own(self):
        await self.login("member")
        state = await self.call(BASE + "state", method="GET")
        await self.call(BASE + "queue/1", {"revision": state["revision"]}, "DELETE", 403)
        await self.call(BASE + "queue/2", {"revision": state["revision"]}, "DELETE")
        self.assertEqual(len(self.bot.players[1].playlist.entries), 3)

    async def test_real_skip_vote_is_not_instant(self):
        await self.login("member")
        current = self.bot.players[1].current_entry
        result = await self.call(BASE + "skip", {})
        self.assertIs(self.bot.players[1].current_entry, current)
        self.assertEqual(self.bot.players[1].skip_state.skippers, {43})
        self.assertIn("跳過請求", result["message"])

    async def test_explicit_fake_login_and_owner_mode(self):
        self.dashboard.fake_login = "away"
        response = await self.client.get("/auth/login", allow_redirects=False)
        self.assertEqual(response.status, 302)
        profile = await (await self.client.get("/auth/session")).json()
        self.assertEqual(profile["user"]["id"], "44")
        self.dashboard.config = replace(self.dashboard.config, auth_mode="owner")
        self.client.session.cookie_jar.clear()
        await self.call("/api/guilds", method="GET")
        await self.call(BASE + "pause", {})

    async def test_seek_uses_real_command_and_updates_fake_clock(self):
        await self.login("owner")
        current = self.bot.players[1].current_entry
        result = await self.call(BASE + "seek", {"position": 62.5})
        self.assertIs(self.bot.players[1].current_entry, current)
        self.assertAlmostEqual(result["state"]["progress"], 63, delta=.2)
        self.assertTrue(result["state"]["current"]["seekable"])

    async def test_playnext_inserts_before_existing_queue(self):
        await self.login("owner")
        player = self.bot.players[1]
        current = player.current_entry
        old = list(player.playlist.entries)
        preview = await self.call(BASE + "resolve", {
            "query": "https://soundcloud.com/example/track/0", "action": "playnext"})
        choice = preview["results"][0]
        await self.call(BASE + "playnext", {
            "query": choice["url"], "preview_id": choice["preview_id"]})
        self.assertIs(player.current_entry, current)
        self.assertEqual(list(player.playlist.entries)[1:], old)
        self.assertIn("夜色慢行", player.playlist.entries[0].title)

    async def test_recent_seed_has_multiple_requesters_and_records_skip(self):
        await self.login("owner")
        before = await self.call(BASE + "history", method="GET")
        names = {item["requester"]["name"] for item in before["history"]}
        self.assertTrue({"Owner", "一般成員"} <= names)
        self.assertTrue(all(set(item["requester"]) == {"name", "avatar"}
                            for item in before["history"]))
        await self.call(BASE + "skip", {})
        after = await self.call(BASE + "history", method="GET")
        self.assertIn("窗邊的午後", after["history"][0]["title"])

    async def test_fake_lyrics_cover_synced_plain_and_not_found(self):
        from tools.dashboard_demo import FakeLyricsClient
        self.assertIsInstance(self.dashboard.lyrics_client, FakeLyricsClient)
        await self.login("owner")
        synced = await self.call(BASE + "lyrics", method="GET")
        self.assertEqual(synced["status"], "synced")
        self.assertGreater(len(synced["lines"]), 1)
        self.assertIn("\n", synced["plain_lyrics"])
        plain = await self.call("/api/guilds/2/lyrics", method="GET")
        self.assertEqual(plain["status"], "plain")
        self.assertFalse(plain["lines"])
        await self.call(BASE + "skip", {})
        await self.call(BASE + "skip", {})
        missing = await self.call(BASE + "lyrics", method="GET")
        self.assertEqual(missing["status"], "not_found")
        manual = await self.call(BASE + "lyrics?query=夜色慢行", method="GET")
        self.assertEqual(manual["status"], "synced")

    async def test_demo_seek_denies_away_and_denied_users(self):
        await self.login("away")
        await self.call(BASE + "seek", {"position": 60}, status=409)
        await self.call("/auth/logout", {})
        await self.login("denied")
        await self.call(BASE + "seek", {"position": 60}, status=403)

    async def test_recent_replay_uses_callers_current_restrictions(self):
        await self.login("member")
        history = await self.call(BASE + "history", method="GET")
        long_song = next(item for item in history["history"] if item["duration"] > 210)
        result = await self.call(BASE + "resolve", {"query": long_song["url"]})
        self.assertFalse(result["results"][0]["allowed"])

    async def test_demo_empty_switch_preserves_history_and_existing_play_flow(self):
        await self.login("owner")
        page = await (await self.client.get("/?demo-queue=empty")).text()
        self.assertIn("還原示範佇列", page)
        self.dashboard.demo_tick()
        state = await self.call(BASE + "state", method="GET")
        self.assertEqual(state["queue"], [])
        history = await self.call(BASE + "history", method="GET")
        self.assertGreaterEqual(len(history["history"]), 5)
        song = next(s for s in history["history"] if s["url"] != state["current"]["url"])
        preview = await self.call(BASE + "resolve", {"query": song["url"]})
        item = preview["results"][0]
        await self.call(BASE + "play", {"query": item["url"], "preview_id": item["preview_id"]})
        self.assertEqual(len(self.bot.players[1].playlist.entries), 1)
        await self.client.get("/?demo-queue=filled")
        self.assertEqual(len(self.bot.players[1].playlist.entries), 4)

    async def test_demo_duplicate_examples_are_local_and_selectable(self):
        await self.login("owner")
        page = await (await self.client.get("/?demo-queue=filled&demo-query=duplicate")).text()
        self.assertIn('value="https://soundcloud.com/example/track/1"', page)
        self.assertIn("重複歌單範例", page)
        self.dashboard.demo_tick()
        before = await self.call(BASE + "state", method="GET")
        preview = await self.call(BASE + "resolve", {"query": "https://soundcloud.com/example/track/1"})
        item = preview["results"][0]
        self.assertTrue(item["allowed"])
        self.assertEqual(item["url"], before["queue"][0]["url"])
        page = await (await self.client.get("/?demo-queue=filled&demo-query=batch")).text()
        self.assertIn('value="https://soundcloud.com/example/playlist"', page)
        preview = await self.call(BASE + "resolve", {"query": "https://soundcloud.com/example/playlist"})
        self.assertTrue(preview["results"][0]["allowed"])
        urls = {entry["url"] for entry in preview["results"][0]["entries"]}
        self.assertIn(before["queue"][0]["url"], urls)

class Round9DemoTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = DemoTests.asyncSetUp
    asyncTearDown = DemoTests.asyncTearDown
    login = DemoTests.login
    call = DemoTests.call

    async def test_fake_public_import_resync_and_large_preview_without_provider_access(self):
        await self.login("owner")
        for url in ("https://open.spotify.com/playlist/DemoRound9",
                    "https://music.youtube.com/playlist?list=DemoRound9"):
            preview = await self.call(BASE+"library/import/preview",{"url":url})
            value = await self.call("/api/library/import",{"preview_id":preview["preview_id"],
                "revision":preview["revision"],"name":"demo"})
            pid = value["playlists"][-1]["id"]
            sync = await self.call(BASE+"library/"+pid+"/sync/preview",{"revision":value["revision"]})
            self.assertEqual(sync["diff"],{"added":2,"removed":1})
        large = await self.call(BASE+"library/import/preview",
            {"url":"https://music.youtube.com/playlist?list=DemoLarge"})
        self.assertTrue(large["truncated"]); self.assertEqual(large["import_count"],200)
        self.assertTrue(str(self.dashboard.popularity_store.root).startswith(self.dashboard.demo_temp.name))

    async def test_fake_popular_and_discord_seek_enqueue_preview(self):
        await self.login("owner")
        popular = await self.call(BASE+"popular?period=7",method="GET")
        self.assertEqual(len(popular["tracks"]),5)
        await self.call(BASE+"seek",{"position":83.456})
        self.assertIn("Seek: 83 seconds", self.bot.discord_messages[-1]["response"]["description"])
        await self.call(BASE+"play",{"query":"https://soundcloud.com/example/track/2"})
        self.assertIn("requested music via the web dashboard",self.bot.discord_messages[-1]["response"]["description"])
        self.assertEqual(self.bot.discord_messages[-1]["channel"],"點歌文字頻道")

    async def test_fake_spotify_match_no_network(self):
        await self.login("owner")
        value=await self.call(BASE+"spotify",method="GET")
        self.assertEqual(value["mode"],"track")
        self.assertEqual(value["url"],"https://open.spotify.com/track/DemoLookup000001")
