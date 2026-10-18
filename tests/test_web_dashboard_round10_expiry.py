import asyncio
import time
import unittest
from unittest.mock import AsyncMock
import test_web_dashboard as base
from musicbot.downloader import YtdlpResponseDict

class ExpiryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=base.DashboardTests.asyncSetUp
    asyncTearDown=base.DashboardTests.asyncTearDown
    call=base.DashboardTests.call
    def expire(self, value):
        self.dashboard.previews[value["preview_id"]]["expires"]=time.monotonic()-1
    async def preview(self, query="keywords"):
        return (await self.call(base.BASE+"resolve",{"query":query}))["results"][0]
    async def test_same_track_auto_resolves_and_double_click_enqueues_once(self):
        value=await self.preview()
        self.expire(value)
        initial=len(self.bot.player.playlist.entries)
        data={"query":value["url"],"preview_id":value["preview_id"]}
        one,two=await asyncio.gather(self.call(base.BASE+"play",data),self.call(base.BASE+"play",data))
        self.assertEqual(len(self.bot.player.playlist.entries),initial+1)
        self.assertEqual(len(self.bot.extractions),3) # original resolve, renewal, actual enqueue
        self.assertEqual(self.bot.extractions[1][0],"ytsearch5:keywords")

    async def test_missing_same_track_never_substitutes_fresh_search_choice(self):
        value=await self.preview();self.expire(value)
        self.bot.info=dict(self.bot.info,webpage_url="https://soundcloud.com/example/different")
        count=len(self.bot.player.playlist.entries)
        result=await self.call(base.BASE+"play",{"query":value["url"],"preview_id":value["preview_id"]},status=409)
        self.assertIn("目前搜尋不到",result["error"])
        self.assertIn("preview_id",result["results"][0])
        self.assertEqual(len(self.bot.player.playlist.entries),count)

    async def test_playlist_renewal_counts_missing_and_only_adds_existing_selection(self):
        single=dict(self.bot.info)
        rows=[dict(single,title="One",webpage_url="https://soundcloud.com/example/one"),
              dict(single,title="Two",webpage_url="https://soundcloud.com/example/two")]
        self.bot.info=dict(single,entries=rows,playlist_count=2)
        value=await self.preview("https://soundcloud.com/example/list");self.expire(value)
        self.bot.downloader.extract_info=AsyncMock(side_effect=[
            YtdlpResponseDict(dict(single,entries=rows[1:],playlist_count=1)),
            YtdlpResponseDict(rows[1])])
        result=await self.call(base.BASE+"play",{"query":value["url"],"preview_id":value["preview_id"],"selected_items":["1","2"]})
        self.assertEqual((result["added"],result["skipped"]),(1,1))
        self.assertEqual(self.bot.player.playlist.entries[-1].title,"Two")

    async def test_renewal_rechecks_blocklist_length_and_rate(self):
        value=await self.preview();self.expire(value)
        self.bot.blocked.add("keywords")
        await self.call(base.BASE+"play",{"query":value["url"],"preview_id":value["preview_id"]},status=403)
        self.bot.blocked.clear()
        self.bot.perms.max_song_length=1
        await self.call(base.BASE+"play",{"query":value["url"],"preview_id":value["preview_id"]},status=409)


import test_web_dashboard_discord as identity
class ExpiryRateTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=identity.DiscordTests.asyncSetUp
    asyncTearDown=identity.DiscordTests.asyncTearDown
    call=identity.DiscordTests.call
    login_as=identity.DiscordTests.login_as
    provider_token=identity.DiscordTests.provider_token
    provider_me=identity.DiscordTests.provider_me

    async def test_real_per_person_limit_includes_expiry_reresolve(self):
        value=(await self.call(base.BASE+"resolve",{"query":"keywords"}))["results"][0]
        self.dashboard.previews[value["preview_id"]]["expires"]=time.monotonic()-1
        self.dashboard.rate_limits[self.bot.member.id]=[time.monotonic()]*11
        await self.call(base.BASE+"play",{"query":value["url"],"preview_id":value["preview_id"]},status=429)
        self.assertEqual(len(self.bot.extractions),1)
