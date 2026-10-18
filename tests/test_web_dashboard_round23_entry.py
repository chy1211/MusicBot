"""Web entry authorization regressions with fake providers and real commands."""
import asyncio
import unittest
from types import MethodType
from musicbot.bot import MusicBot

import test_web_dashboard_discord as fixtures
from test_web_dashboard import BASE, HEADERS, NS


class EntryAuthorization(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.DiscordTests.asyncSetUp
    asyncTearDown = fixtures.DiscordTests.asyncTearDown
    call = fixtures.DiscordTests.call
    login_as = fixtures.DiscordTests.login_as
    provider_token = fixtures.DiscordTests.provider_token
    provider_me = fixtures.DiscordTests.provider_me

    async def reject_during_resolution(self, action, mode, change):
        self.bot.cmd_playnext = MethodType(MusicBot.cmd_playnext, self.bot)
        query = "https://soundcloud.com/example/song"
        data = {"query": query}
        if mode == "confirmed":
            song = (await self.call(BASE + "resolve", {"query": query, "action": action}))["results"][0]
            data = {"query": song["url"], "preview_id": song["preview_id"]}
        before = list(self.bot.player.playlist.entries)
        started, release = asyncio.Event(), asyncio.Event()
        original = self.bot.downloader.extract_info
        calls = 0
        async def extract(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == (2 if mode == "legacy_confirmation" else 1):
                started.set()
                await release.wait()
            return await original(*args, **kwargs)
        self.bot.downloader.extract_info = extract
        pending = asyncio.create_task(self.client.post(BASE + action, json=data,
            headers=dict(HEADERS, Origin=self.origin)))
        try:
            await asyncio.wait_for(started.wait(), 2)
            if change == "logout":
                await self.call("/auth/logout-all", {})
                expected = 401
            elif change == "membership":
                self.bot.members.pop(43)
                expected = 403
            elif change == "permission":
                self.bot.member_perms.can_use_command.return_value = False
                expected = 403
            else:
                self.bot.member.voice.channel = NS(id=11)
                expected = 403
            release.set()
            response = await asyncio.wait_for(pending, 2)
            body = await response.json()
            self.assertEqual(response.status, expected, body)
            self.assertEqual(list(self.bot.player.playlist.entries), before)
            self.bot.serialize_queue.assert_not_awaited()
            self.assertFalse(self.dashboard.resolve_tasks)
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


def authorization_case(action, mode, change):
    async def test(self):
        await self.reject_during_resolution(action, mode, change)
    return test


for _action in ("play", "playnext"):
    for _mode in ("legacy_preview", "legacy_confirmation", "confirmed"):
        for _change in ("logout", "membership", "permission", "voice"):
            setattr(EntryAuthorization, "test_" + "_".join((_action, _mode, _change)),
                    authorization_case(_action, _mode, _change))
