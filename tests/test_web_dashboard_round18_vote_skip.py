"""Round18: fictional IDs, real skip dispatch, isolated atomic settings."""
import asyncio
import builtins
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import discord
import test_web_dashboard_discord as identity
from test_web_dashboard import BASE, HEADERS, entry
from musicbot.bot import MusicBot
from musicbot.constructs import ErrorResponse, SkipState
from musicbot.slash_commands import SlashCommands
from musicbot.web_dashboard_activity import player_view, capture, finish
from musicbot.web_dashboard_guild_settings import VoteSkipStore, validate_vote_skip, vote_skip_enabled

API = BASE + "admin/vote-skip"


class VoteSkipStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="musicbot-webtest-vote-")
        self.addCleanup(self.temp.cleanup)
        self.store = VoteSkipStore(Path(self.temp.name) / "vote_skip")

    async def test_default_corrupt_oversized_and_unreadable(self):
        self.assertEqual(self.store.read(1), {"enabled": True})
        p = self.store.path(1)
        p.parent.mkdir()
        for raw in ("{", "[]", '{"enabled":0}', '{"enabled":false,"extra":1}', " " * 4097):
            with self.subTest(raw=raw[:30]):
                p.write_text(raw)
                self.assertEqual(self.store.read(1), {"enabled": True})
        with patch.object(Path, "open", side_effect=PermissionError()):
            self.assertEqual(self.store.read(1), {"enabled": True})

    async def test_atomic_roundtrip_modes_isolation_and_file_removal(self):
        await self.store.put(1, {"enabled": False})
        self.assertEqual(self.store.path(1).read_text(), '{"enabled":false}')
        self.assertEqual(self.store.path(1).stat().st_mode & 0o777, 0o600)
        os.chmod(self.store.path(1), 0o640)
        await self.store.put(1, {"enabled": True})
        self.assertEqual(self.store.path(1).stat().st_mode & 0o777, 0o640)
        reloaded = VoteSkipStore(self.store.root)
        await self.store.put(2, {"enabled": False})
        self.assertEqual(reloaded.read(1), {"enabled": True})
        self.assertEqual(reloaded.read(2), {"enabled": False})
        self.store.path(2).unlink()
        self.assertEqual(reloaded.read(2), {"enabled": True})
        self.assertEqual([p.name for p in self.store.root.iterdir()], ["1.json"])

    async def test_replace_failure_preserves_previous_and_cleans_temp(self):
        await self.store.put(1, {"enabled": False})
        with patch("musicbot.web_dashboard_stats.os.replace", side_effect=OSError("fixture")):
            with self.assertRaises(OSError):
                await self.store.put(1, {"enabled": True})
        self.assertEqual(self.store.read(1), {"enabled": False})
        self.assertEqual([p.name for p in self.store.root.iterdir()], ["1.json"])

    async def test_strict_schema_and_guild_path(self):
        for value in (None, [], {}, {"enabled": 1}, {"enabled": "false"},
                      {"enabled": None}, {"enabled": False, "extra": 1}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_vote_skip(value)
        for gid in (True, 0, -1, "../1"):
            with self.assertRaises(ValueError):
                self.store.path(gid)

    async def test_native_without_dashboard_and_write_dir_reads_same_file(self):
        bot = NS(_web_dashboard=None)
        with patch("musicbot.web_dashboard_guild_settings.write_path", return_value=self.store.root) as resolve:
            self.assertTrue(vote_skip_enabled(bot, NS(id=1)))
            await self.store.put(1, {"enabled": False})
            self.assertFalse(vote_skip_enabled(bot, NS(id=1)))
            self.assertTrue(vote_skip_enabled(bot, NS(id=2)))
            resolve.assert_called_with("data/web_dashboard/vote_skip")


class VoteSkipTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = identity.DiscordTests.asyncTearDown
    login_as = identity.DiscordTests.login_as
    call = identity.DiscordTests.call
    provider_token = identity.DiscordTests.provider_token
    provider_me = identity.DiscordTests.provider_me

    async def asyncSetUp(self):
        await identity.DiscordTests.asyncSetUp(self)
        self.temp = tempfile.TemporaryDirectory(prefix="musicbot-webtest-vote-")
        self.addCleanup(self.temp.cleanup)
        self.dashboard.vote_skip_store.root = Path(self.temp.name) / "vote_skip"
        self.bot._web_dashboard = self.dashboard
        self.bot.config.allow_author_skip = False
        self.bot.config.legacy_skip = False

    async def disable(self, guild=1):
        await self.dashboard.vote_skip_store.put(guild, {"enabled": False})

    async def core_skip(self, *, guild=None, perms=None, param="", author=None):
        return await self.bot.cmd_skip(None, guild or self.bot.guild, self.bot.player,
            author or self.bot.member, None, perms or self.bot.member_perms, self.bot.channel, param)

    def reset_player(self):
        self.bot.player.current_entry = entry("Current", author=self.bot.owner, channel=self.bot.channel)
        self.bot.player.skip_state = SkipState()
        self.bot.player.repeatsong = False

    async def test_owner_get_save_reload_clear_and_operation_log(self):
        self.login_as(42)
        self.assertEqual(await self.call(API, method="GET"), {"enabled": True})
        with self.assertLogs("musicbot.web_dashboard", level="INFO") as logs:
            self.assertEqual(await self.call(API, {"enabled": False}), {"enabled": False})
        self.assertIn("admin_vote_skip", "\n".join(logs.output))
        self.assertNotIn("unknown", "\n".join(logs.output))
        self.assertEqual(await self.call(API, method="GET"), {"enabled": False})
        self.assertEqual(await self.call(API, method="DELETE"), {"enabled": True})
        self.assertEqual(await self.call(API, method="GET"), {"enabled": True})
        await self.call(BASE + "skip", {})
        self.assertEqual(self.bot.player.skip_state.skippers, {42})

    async def test_nonowner_get_post_delete_403(self):
        for method, data in (("GET", None), ("POST", {"enabled": False}), ("DELETE", None)):
            await self.call(API, data, method=method, status=403)
        self.assertFalse(self.dashboard.vote_skip_store.path(1).exists())

    async def test_owner_schema_and_same_origin_checks(self):
        self.login_as(42)
        for value in ([], {}, {"enabled": 0}, {"enabled": "false"}, {"enabled": None},
                      {"enabled": False, "extra": 1}):
            await self.call(API, value, status=400)
        await self.call(API, {"enabled": False}, headers=dict(HEADERS, Origin="https://example.test"), status=403)
        await self.call(API, {"enabled": False}, headers={"Origin": self.origin}, status=403)
        self.assertTrue(self.dashboard.vote_skip_store.read(1)["enabled"])

    async def test_existing_owner_blocklist_exemption_and_membership(self):
        self.login_as(42)
        self.bot.blocked_users.add(42)
        await self.call(API, {"enabled": False})
        self.bot.blocked_users.clear()
        self.bot.members.pop(42)
        await self.call(API, {"enabled": False}, status=403)

    async def test_failed_save_503_preserves_settings(self):
        self.login_as(42)
        await self.call(API, {"enabled": False})
        with patch("musicbot.web_dashboard_stats.os.replace", side_effect=OSError("fixture")):
            result = await self.call(API, {"enabled": True}, status=503)
        self.assertNotIn("fixture", json.dumps(result))
        self.assertFalse(self.dashboard.vote_skip_store.read(1)["enabled"])

    async def test_queued_request_rechecks_owner(self):
        self.login_as(42)
        await self.dashboard.admin_lock.acquire()
        try:
            task = asyncio.create_task(self.call(API, {"enabled": False}, status=403))
            await asyncio.sleep(.02)
            self.bot.members.pop(42)
        finally:
            self.dashboard.admin_lock.release()
        await task
        self.assertFalse(self.dashboard.vote_skip_store.path(1).exists())

    async def test_enabled_web_votes_deduplicate_threshold_and_reply(self):
        await self.call(BASE + "skip", {})
        await self.call(BASE + "skip", {})
        self.assertEqual(self.bot.player.skip_state.skippers, {43})
        self.assertIsNotNone(self.bot.player.current_entry)
        self.assertIn("more vote", self.bot.safe_send_message.await_args.args[1].content)
        self.login_as(44)
        await self.call(BASE + "skip", {})
        self.assertEqual(self.bot.player.skip_state.skippers, {43, 44})
        self.assertIsNone(self.bot.player.current_entry)
        self.assertIn("passed", self.bot.safe_send_message.await_args.args[1].content)

    async def test_enabled_instaskip_needs_force_or_legacy_as_before(self):
        for param, legacy, immediate in (("", False, False), ("force", False, True), ("", True, True)):
            with self.subTest(param=param, legacy=legacy):
                self.reset_player()
                self.bot.config.legacy_skip = legacy
                result = await self.core_skip(author=self.bot.owner, perms=self.bot.perms, param=param)
                self.assertEqual(self.bot.player.current_entry is None, immediate)
                self.assertEqual(bool(self.bot.player.skip_state.skippers), not immediate)
                self.assertIn("Force skipped" if immediate else "more vote", result.content)

    async def test_enabled_force_denied_for_ordinary_member(self):
        from musicbot.exceptions import PermissionsError
        with self.assertRaises(PermissionsError):
            await self.core_skip(param="force")
        self.assertFalse(self.bot.player.skip_state.skippers)

    async def test_disabled_web_immediate_without_votes_or_threshold_reply(self):
        await self.disable()
        result = await self.call(BASE + "skip", {})
        self.assertIsNone(self.bot.player.current_entry)
        self.assertFalse(self.bot.player.skip_state.skippers)
        text = self.bot.safe_send_message.await_args.args[1].content
        self.assertIn("Force skipped", text)
        self.assertNotIn("vote", text.lower())
        self.assertNotIn("vote", json.dumps(result).lower())
        row = self.dashboard.activities[1][0]
        self.assertNotIn("\u6295\u7968", row["detail"])
        self.assertEqual(row["source"], "web")

    async def test_disabled_web_missing_skip_permission_is_denied(self):
        await self.disable()
        self.bot.member_perms.can_use_command.return_value = False
        await self.call(BASE + "skip", {}, status=403)
        self.assertIsNotNone(self.bot.player.current_entry)
        self.assertFalse(self.bot.player.skip_state.skippers)

    async def test_disabled_skip_looped_denied_and_allowed(self):
        from musicbot.exceptions import PermissionsError
        await self.disable()
        self.bot.player.repeatsong = True
        self.bot.member_perms.skip_looped = False
        await self.call(BASE + "skip", {}, status=403)
        self.assertTrue(self.bot.player.repeatsong)
        self.assertFalse(self.bot.player.skip_state.skippers)
        self.bot.member_perms.skip_looped = True
        await self.call(BASE + "skip", {})
        self.assertFalse(self.bot.player.repeatsong)
        self.assertIsNone(self.bot.player.current_entry)
        self.assertFalse(self.bot.player.skip_state.skippers)

    async def test_other_guild_keeps_voting(self):
        await self.disable()
        second = NS(id=2)
        result = await self.core_skip(guild=second)
        self.assertIn("more vote", result.content)
        self.assertIsNotNone(self.bot.player.current_entry)
        self.assertEqual(self.bot.player.skip_state.skippers, {43})
        self.assertFalse(vote_skip_enabled(self.bot, self.bot.guild))

    async def test_api_second_guild_retains_default(self):
        second = NS(**vars(self.bot.guild))
        second.id, second.name = 2, "Fixture second guild"
        self.bot.guilds.append(second)
        self.bot.get_guild = lambda gid: {1:self.bot.guild, 2:second}.get(gid)
        self.login_as(42)
        await self.call(API, {"enabled": False})
        self.assertEqual(await self.call("/api/guilds/2/admin/vote-skip", method="GET"), {"enabled": True})
        await self.call("/api/guilds/2/admin/vote-skip", {"enabled": False})
        await self.call(API, method="DELETE")
        self.assertEqual(await self.call("/api/guilds/2/admin/vote-skip", method="GET"), {"enabled": False})

    async def test_disabled_bypasses_counting_and_keeps_voice_gate(self):
        await self.disable()
        self.bot.member.voice = None
        await self.call(BASE + "skip", {}, status=409)
        self.bot.member.voice = NS(channel=self.bot.channel)
        with patch("musicbot.bot.count_members_in_voice", side_effect=AssertionError("no vote counting")):
            await self.call(BASE + "skip", {})
        self.assertIsNone(self.bot.player.current_entry)
        self.assertFalse(self.bot.player.skip_state.skippers)

    async def test_stale_votes_hidden_in_activity_even_before_player_advances(self):
        self.bot.player.skip_state.add_skipper(44, None)
        self.assertEqual(player_view(self.bot, self.bot.guild)["votes"], 1)
        await self.disable()
        self.assertEqual(player_view(self.bot, self.bot.guild)["votes"], 0)
        observation = capture(self.dashboard, self.bot.guild, self.bot.member, "skip", "web")
        with patch.object(self.bot.player, "skip"):
            result = await self.core_skip()
        finish(observation, True)
        self.assertIn("Force skipped", result.content)
        self.assertEqual(self.bot.player.skip_state.skippers, {44})
        row = self.dashboard.activities[1][0]
        self.assertNotIn("\u6295\u7968", row["detail"])
        self.assertNotIn("m0472", json.dumps(row))

    async def text_skip(self, *, denied=False):
        bot = self.bot
        channel = Mock(spec=discord.TextChannel)
        channel.guild, channel.id = bot.guild, 10
        member = Mock(spec=discord.Member)
        member.id, member.name, member.display_name = 43, "Friend", "Friend"
        member.bot, member.voice = False, NS(channel=bot.channel)
        bot.user = NS(id=999)
        bot.wait_until_ready = AsyncMock()
        bot.server_data[1] = NS(command_prefix="!")
        bot.config.commands_via_mention = bot.config.delete_invoking = bot.config.debug_mode = False
        bot.config.usealias = True
        bot.member_perms.can_use_command.return_value = not denied
        msg = Mock(spec=discord.Message)
        msg.channel, msg.guild, msg.author = channel, bot.guild, member
        msg.content, msg.attachments, msg.id = "!skip", [], 501
        with patch.object(builtins, "_L", lambda text: text, create=True):
            await MusicBot.on_message(bot, msg)
        return bot.safe_send_message.await_args.args[1]

    async def test_text_dispatch_disabled_immediate(self):
        await self.disable()
        result = await self.text_skip()
        self.assertIn("Force skipped", result.content)
        self.assertIsNone(self.bot.player.current_entry)
        self.assertFalse(self.bot.player.skip_state.skippers)
        self.assertEqual(self.dashboard.activities[1][0]["source"], "discord_text")

    async def test_text_dispatch_disabled_without_skip_denied(self):
        await self.disable()
        self.assertIsInstance(await self.text_skip(denied=True), ErrorResponse)
        self.assertIsNotNone(self.bot.player.current_entry)
        self.assertFalse(self.bot.player.skip_state.skippers)

    async def test_text_dispatch_enabled_votes(self):
        result = await self.text_skip()
        self.assertIn("more vote", result.content)
        self.assertEqual(self.bot.player.skip_state.skippers, {43})

    async def slash_skip(self, *, denied=False, force=None):
        member = Mock(spec=discord.Member)
        member.id, member.name, member.display_name = 43, "Friend", "Friend"
        member.voice, member.bot = NS(channel=self.bot.channel), False
        self.bot.member_perms.can_use_command.return_value = not denied
        cog = SlashCommands(self.bot)
        cog._reply = AsyncMock()
        interaction = NS(guild=self.bot.guild, user=member, response=NS(defer=AsyncMock()))
        await SlashCommands.slash_skip.callback(cog, interaction, force)
        return cog._reply.await_args

    async def test_slash_dispatch_disabled_immediate_even_force(self):
        await self.disable()
        for force in (None, True):
            with self.subTest(force=force):
                self.reset_player()
                reply = await self.slash_skip(force=force)
                self.assertIn("Force skipped", reply.args[1])
                self.assertIsNone(self.bot.player.current_entry)
                self.assertFalse(self.bot.player.skip_state.skippers)
                self.assertEqual(self.dashboard.activities[1][0]["source"], "discord_slash")

    async def test_slash_dispatch_disabled_without_skip_denied(self):
        await self.disable()
        reply = await self.slash_skip(denied=True)
        self.assertTrue(reply.kwargs["ephemeral"])
        self.assertIsNotNone(self.bot.player.current_entry)
        self.assertFalse(self.bot.player.skip_state.skippers)

    async def test_slash_dispatch_enabled_votes(self):
        reply = await self.slash_skip()
        self.assertIn("more vote", reply.args[1])
        self.assertEqual(self.bot.player.skip_state.skippers, {43})
