"""Legacy autoplay priority through native Discord and HTTP command routes."""
import unittest
from types import MethodType
from musicbot.bot import MusicBot
from test_web_dashboard_round33_radio_priority import info, install_playlist
import test_web_dashboard as base
import test_web_dashboard_discord as identity


class LegacyDiscordTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = base.FakeBot()
        self.queue = install_playlist(self.bot)
        self.bot.cmd_playnext = MethodType(MusicBot.cmd_playnext, self.bot)

    async def request(self, title, next=False):
        command = MusicBot.cmd_playnext if next else MusicBot.cmd_play
        self.bot.info = info(title).data
        return await command(
            self.bot, message=None, player=self.bot.player, channel=self.bot.channel,
            guild=self.bot.guild, author=self.bot.owner, permissions=self.bot.perms,
            leftover_args=[], song_url="https://example.com/music")

    async def test_discord_play_and_playnext_precede_legacy_and_keep_current(self):
        current = self.bot.player.current_entry
        await self.queue.add_entry_from_info(info("Legacy"))
        reply = await self.request("User1")
        await self.request("User2")
        await self.request("Next", next=True)
        self.assertEqual([e.title for e in self.queue], ["Next", "User1", "User2", "Legacy"])
        self.assertTrue(reply.queue_position_text.startswith("1 -"))
        self.assertIs(self.bot.player.current_entry, current)

    async def test_round_robin_preserves_pending_legacy(self):
        self.bot.config.round_robin_queue = True
        await self.queue.add_entry_from_info(info("Legacy"))
        await self.request("User1")
        await self.request("User2")
        self.assertEqual([e.title for e in self.queue], ["User1", "User2", "Legacy"])


class LegacyDashboardTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = identity.DiscordTests.asyncTearDown
    call = identity.DiscordTests.call
    login_as = identity.DiscordTests.login_as
    provider_token = identity.DiscordTests.provider_token
    provider_me = identity.DiscordTests.provider_me

    async def asyncSetUp(self):
        await identity.DiscordTests.asyncSetUp(self)
        self.bot.member.name = "DemoUser"
        self.bot.friend.name = "DemoUser"
        self.queue = install_playlist(self.bot)
        self.bot.cmd_playnext = MethodType(MusicBot.cmd_playnext, self.bot)

    async def test_web_play_and_playnext_precede_pending_legacy(self):
        current = self.bot.player.current_entry
        await self.queue.add_entry_from_info(info("Legacy"))
        for action, title in (("play", "User1"), ("play", "User2"), ("playnext", "Next")):
            self.bot.info = info(title).data
            await self.call(base.BASE + action, {"query": "https://soundcloud.com/example/song"})
        state = await self.call(base.BASE + "state", method="GET")
        self.assertEqual([row["title"] for row in state["queue"]],
                         ["Next", "User1", "User2", "Legacy"])
        self.assertIs(self.bot.player.current_entry, current)
