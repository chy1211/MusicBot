import time
import unittest
import test_web_dashboard_discord as fixtures
from test_web_dashboard import BASE, entry

class UndoTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.DiscordTests.asyncSetUp
    asyncTearDown=fixtures.DiscordTests.asyncTearDown
    call=fixtures.DiscordTests.call
    login_as=fixtures.DiscordTests.login_as
    provider_token=fixtures.DiscordTests.provider_token
    provider_me=fixtures.DiscordTests.provider_me

    async def remove(self):
        self.bot.member_perms.remove=True
        rev=(await self.call(BASE+"state",method="GET"))["revision"]
        target=self.bot.player.playlist.entries[1]
        result=await self.call(BASE+"queue/2",{"revision":rev},method="DELETE")
        return target,result["undo_token"]

    async def test_restore_same_object_position_requester_once_and_audit(self):
        target,token=await self.remove()
        await self.call(BASE+"queue/undo",{"undo_token":token})
        self.assertIs(self.bot.player.playlist.entries[1],target)
        self.assertIs(target.author,self.bot.owner)
        self.assertEqual(self.dashboard.activities[1][0]["action"],"undo")
        await self.call(BASE+"queue/undo",{"undo_token":token},status=403)

    async def test_only_deleter_expiry_and_no_client_song_payload(self):
        target,token=await self.remove()
        self.login_as(42)
        await self.call(BASE+"queue/undo",{"undo_token":token},status=403)
        self.login_as(43)
        await self.call(BASE+"queue/undo",{"undo_token":token,"entry":{"title":"Tampered"}},status=400)
        self.dashboard.undo_records[(1,43)]["expires"]=time.monotonic()-1
        await self.call(BASE+"queue/undo",{"undo_token":token},status=409)

    async def test_duplicate_limits_and_permission_rechecked(self):
        target,token=await self.remove()
        self.bot.player.playlist.entries.append(target)
        result=await self.call(BASE+"queue/undo",{"undo_token":token},status=409)
        self.assertIn("已在佇列",result["error"])
        self.bot.player.playlist.entries.remove(target)
        target,token=await self.remove()
        self.bot.member_perms.max_songs=1
        self.bot.player.playlist.entries.append(entry("Mine",author=self.bot.member))
        await self.call(BASE+"queue/undo",{"undo_token":token},status=403)
