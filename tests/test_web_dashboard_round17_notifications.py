"""Round17: fictional guild/channel IDs and isolated notification settings."""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from discord import ChannelType
import test_web_dashboard_discord as identity
from test_web_dashboard import BASE, entry
from musicbot.web_dashboard import APIError
from musicbot.web_dashboard_notifications import NotificationChannelStore, validate_notification

API = BASE + "admin/notification-channel"


class NotificationStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="musicbot-webtest-notify-")
        self.addCleanup(self.temp.cleanup)
        self.store = NotificationChannelStore(Path(self.temp.name) / "notification_channels")

    async def test_missing_and_corrupt_settings_use_default(self):
        self.assertEqual(self.store.read(1), {"channel_id": None})
        path = self.store.path(1)
        path.parent.mkdir()
        for raw in ("{", "[]", '{"channel_id":42}', '{"channel_id":"../1"}', " " * 4097):
            with self.subTest(raw=raw[:30]):
                path.write_text(raw)
                self.assertEqual(self.store.read(1), {"channel_id": None})
        with patch.object(Path, "open", side_effect=PermissionError()):
            self.assertEqual(self.store.read(1), {"channel_id": None})

    async def test_atomic_persistence_clear_and_guild_isolation(self):
        await self.store.put(1, {"channel_id": "101"})
        await self.store.put(2, {"channel_id": "201"})
        reloaded = NotificationChannelStore(self.store.root)
        self.assertEqual(reloaded.read(1), {"channel_id": "101"})
        self.assertEqual(reloaded.read(2), {"channel_id": "201"})
        self.assertEqual(self.store.path(1).stat().st_mode & 0o777, 0o600)
        os.chmod(self.store.path(1), 0o640)
        await self.store.put(1, {"channel_id": None})
        self.assertEqual(self.store.path(1).stat().st_mode & 0o777, 0o640)
        self.assertEqual(reloaded.read(1), {"channel_id": None})
        self.assertEqual(reloaded.read(2), {"channel_id": "201"})
        self.assertEqual(sorted(p.name for p in self.store.root.iterdir()), ["1.json", "2.json"])

    async def test_failed_replace_preserves_previous_file_and_removes_temporary(self):
        await self.store.put(1, {"channel_id": "101"})
        with patch("musicbot.web_dashboard_stats.os.replace", side_effect=OSError("fixture")):
            with self.assertRaises(OSError):
                await self.store.put(1, {"channel_id": "102"})
        self.assertEqual(self.store.read(1), {"channel_id": "101"})
        self.assertEqual([p.name for p in self.store.root.iterdir()], ["1.json"])

    async def test_strict_ids_payload_and_path_validation(self):
        for value in (None, [], {}, {"channel_id": True}, {"channel_id": 101},
                      {"channel_id": ""}, {"channel_id": "0"}, {"channel_id": "-1"},
                      {"channel_id": "001"}, {"channel_id": "../1"},
                      {"channel_id": "1" * 21}, {"channel_id": str(2**64)},
                      {"channel_id": "\u0661"}, {"channel_id": None, "extra": True}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_notification(value)
        for value in (0, -1, True, "../1"):
            with self.assertRaises(ValueError):
                self.store.path(value)


class NotificationTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = identity.DiscordTests.asyncTearDown
    login_as = identity.DiscordTests.login_as
    call = identity.DiscordTests.call
    provider_token = identity.DiscordTests.provider_token
    provider_me = identity.DiscordTests.provider_me

    async def asyncSetUp(self):
        await identity.DiscordTests.asyncSetUp(self)
        self.temp = tempfile.TemporaryDirectory(prefix="musicbot-webtest-notify-")
        self.addCleanup(self.temp.cleanup)
        self.dashboard.notification_store.root = Path(self.temp.name) / "notification_channels"
        self.bot.channel.type = ChannelType.voice
        self.channels = {10: self.bot.channel}
        self.system = self.text_channel(102)
        self.fallback = self.text_channel(101)
        self.bound = self.text_channel(103)
        self.bot.guild.get_channel = self.channels.get
        self.bot.guild.system_channel = self.system
        self.bot.guild.text_channels = [self.system, self.fallback, self.bound]
        self.bot.guild.channels = list(self.channels.values())
        self.bot.player.current_entry.channel = None
        for item in self.bot.player.playlist.entries:
            item.channel = None

    def text_channel(self, cid):
        channel = NS(id=cid, name="Fixture text", guild=self.bot.guild, type=ChannelType.text,
                     typing=self.bot.channel.typing,
                     permissions_for=lambda _: NS(view_channel=True, send_messages=True))
        self.channels[cid] = channel
        return channel

    async def configure(self, cid="101", guild=1):
        await self.dashboard.notification_store.put(guild, {"channel_id": cid})

    def destination(self):
        return self.dashboard.channel_for(self.bot.guild, self.bot.member)

    async def test_current_request_channel_precedes_fallback(self):
        await self.configure()
        self.bot.player.current_entry.channel = self.bound
        self.assertIs(self.destination(), self.bound)

    async def test_latest_request_channel_precedes_fallback_after_reorder(self):
        await self.configure()
        newest = entry("Fixture request", channel=self.bound)
        self.bot.player.playlist.entries.appendleft(newest)
        self.dashboard.note_queue_entry(self.bot.guild, newest)
        self.bot.player.playlist.entries.rotate(2)
        self.assertIs(self.destination(), self.bound)

    async def test_fallback_precedes_bound_and_system_without_request_channel(self):
        await self.configure()
        self.bot.config.bound_channels = {101, 103}
        self.assertIs(self.destination(), self.fallback)

    async def test_invalid_request_channels_fall_to_fallback(self):
        await self.configure()
        self.bot.player.current_entry.channel = self.bound
        self.bound.permissions_for = lambda _: NS(view_channel=True, send_messages=False)
        self.bot.player.playlist.entries[-1].channel = self.system
        self.system.permissions_for = lambda _: NS(view_channel=False, send_messages=True)
        self.assertIs(self.destination(), self.fallback)

    async def test_restrict_skips_unbound_fallback(self):
        await self.configure()
        self.bot.config.bound_channels = {103}
        self.assertIs(self.destination(), self.bound)

    async def test_unbound_server_exception_still_allows_fallback(self):
        await self.configure()
        self.bot.config.bound_channels = {999}
        self.bot.config.unbound_servers = True
        self.assertIs(self.destination(), self.fallback)

    async def test_deleted_fallback_uses_bound_then_system(self):
        await self.configure()
        del self.channels[101]
        self.bot.config.bound_channels = {103}
        self.assertIs(self.destination(), self.bound)
        self.bot.config.bound_channels = set()
        self.assertIs(self.destination(), self.system)

    async def test_view_and_send_permissions_on_both_sides_are_required(self):
        await self.configure()
        for denied in (self.bot.member, self.bot.guild.me):
            for flag in ("view_channel", "send_messages"):
                with self.subTest(denied=denied is self.bot.member, flag=flag):
                    self.fallback.permissions_for = lambda member: NS(**{
                        "view_channel": not (member is denied and flag == "view_channel"),
                        "send_messages": not (member is denied and flag == "send_messages")})
                    self.assertIs(self.destination(), self.system)

    async def test_foreign_or_nontext_saved_channel_is_skipped(self):
        await self.configure()
        for kind in (ChannelType.voice, ChannelType.stage_voice, ChannelType.forum,
                     ChannelType.category, ChannelType.public_thread):
            with self.subTest(kind=kind):
                self.fallback.type = kind
                self.assertIs(self.destination(), self.system)
        self.fallback.type = ChannelType.text
        self.fallback.guild = NS(id=2)
        self.assertIs(self.destination(), self.system)

    async def test_no_player_can_use_fallback(self):
        await self.configure()
        self.bot.get_player_in = lambda _: None
        self.assertIs(self.destination(), self.fallback)

    async def test_unset_preserves_entire_legacy_order(self):
        self.bot.player.current_entry.channel = self.fallback
        self.assertIs(self.destination(), self.fallback)
        self.bot.player.current_entry.channel = None
        self.bot.player.playlist.entries[-1].channel = self.bound
        self.assertIs(self.destination(), self.bound)
        self.bot.player.playlist.entries[-1].channel = None
        self.bot.config.bound_channels = {103}
        self.assertIs(self.destination(), self.bound)
        self.bot.config.bound_channels = set()
        self.assertIs(self.destination(), self.system)
        self.bot.guild.system_channel = None
        self.assertIs(self.destination(), self.system)
        self.bot.guild.text_channels = []
        self.assertIs(self.destination(), self.bot.channel)
        self.bot.config.bound_channels = {999}
        with self.assertRaises(APIError) as failure:
            self.destination()
        self.assertEqual(failure.exception.status, 403)

    async def test_guild_settings_do_not_leak(self):
        await self.configure("201", guild=2)
        self.assertIs(self.destination(), self.system)

    async def test_web_volume_notification_uses_fallback_context(self):
        await self.configure()
        await self.call(BASE + "volume", {"volume": 60})
        self.assertIs(self.bot.safe_send_message.await_args.args[0], self.fallback)

    async def test_owner_only_api_rejects_all_other_members(self):
        for uid in (43, 44):
            self.login_as(uid)
            for method in ("GET", "POST"):
                await self.call(API, {"channel_id": "101"}, method=method, status=403)
        self.assertFalse(self.dashboard.notification_store.root.exists())

    async def test_api_lists_only_bot_visible_sendable_text_channels(self):
        self.login_as(42)
        self.system.permissions_for = lambda _: NS(view_channel=False, send_messages=True)
        self.bound.permissions_for = lambda _: NS(view_channel=True, send_messages=False)
        value = await self.call(API, method="GET")
        self.assertEqual(value, {"channel_id": None,
                                "channels": [{"id": "101", "name": "Fixture text"}],
                                "unavailable": False})

    async def test_api_rejects_foreign_deleted_voice_and_other_nontext_channels(self):
        self.login_as(42)
        foreign = self.text_channel(201)
        foreign.guild = NS(id=2)
        for cid in ("201", "999", "10"):
            await self.call(API, {"channel_id": cid}, status=400)
        for kind in (ChannelType.stage_voice, ChannelType.forum, ChannelType.category,
                     ChannelType.public_thread):
            self.fallback.type = kind
            await self.call(API, {"channel_id": "101"}, status=400)
        self.assertFalse(self.dashboard.notification_store.root.exists())

    async def test_api_rejects_invalid_payloads(self):
        self.login_as(42)
        for data in ({}, {"channel_id": 101}, {"channel_id": True}, {"channel_id": ""},
                     {"channel_id": "../101"}, {"channel_id": "00101"},
                     {"channel_id": None, "extra": True}):
            await self.call(API, data, status=400)

    async def test_api_save_and_clear_persist(self):
        self.login_as(42)
        value = await self.call(API, {"channel_id": "101"})
        self.assertEqual(value["channel_id"], "101")
        self.assertFalse(value["unavailable"])
        self.assertIs(self.destination(), self.fallback)
        self.assertEqual(json.loads(self.dashboard.notification_store.path(1).read_text()),
                         {"channel_id": "101"})
        value = await self.call(API, {"channel_id": None})
        self.assertIsNone(value["channel_id"])
        self.assertIs(self.destination(), self.system)
        self.assertEqual(self.dashboard.notification_store.read(1), {"channel_id": None})

    async def test_api_warning_for_deleted_channel_and_clear(self):
        self.login_as(42)
        await self.call(API, {"channel_id": "101"})
        del self.channels[101]
        self.bot.guild.text_channels.remove(self.fallback)
        value = await self.call(API, method="GET")
        self.assertTrue(value["unavailable"])
        self.assertEqual(value["channel_id"], "101")
        self.assertIs(self.destination(), self.system)
        value = await self.call(API, {"channel_id": None})
        self.assertFalse(value["unavailable"])

    async def test_api_warning_for_lost_permissions_and_binding(self):
        self.login_as(42)
        await self.configure()
        for denied in (self.bot.owner, self.bot.guild.me):
            self.fallback.permissions_for = lambda member: NS(view_channel=True, send_messages=member is not denied)
            value = await self.call(API, method="GET")
            self.assertTrue(value["unavailable"])
            if denied is self.bot.guild.me:
                self.assertNotIn("101", [row["id"] for row in value["channels"]])
        self.fallback.permissions_for = lambda _: NS(view_channel=True, send_messages=True)
        self.bot.config.bound_channels = {103}
        self.assertTrue((await self.call(API, method="GET"))["unavailable"])

    async def test_api_cannot_save_channel_bot_cannot_use(self):
        self.login_as(42)
        for flag in ("view_channel", "send_messages"):
            self.fallback.permissions_for = lambda _: NS(**{
                "view_channel": flag != "view_channel", "send_messages": flag != "send_messages"})
            await self.call(API, {"channel_id": "101"}, status=400)

    async def test_api_announcements_are_text_channels(self):
        self.login_as(42)
        self.fallback.type = ChannelType.news
        await self.call(API, {"channel_id": "101"})
        self.assertIs(self.destination(), self.fallback)

    async def test_api_logs_have_named_action_and_no_channel_name(self):
        self.login_as(42)
        self.fallback.name = "FIXTURE-PRIVATE-NAME"
        with self.assertLogs("musicbot.web_dashboard", level="INFO") as captured:
            await self.call(API, {"channel_id": "101"})
        logs = "\n".join(captured.output)
        self.assertIn("action=admin_notification_channel status=200", logs)
        self.assertNotIn("unknown", logs)
        self.assertNotIn("FIXTURE-PRIVATE-NAME", logs)

    async def test_api_write_failure_preserves_setting_and_reports_503(self):
        self.login_as(42)
        await self.configure()
        with patch("musicbot.web_dashboard_stats.os.replace", side_effect=OSError("PRIVATE")):
            result = await self.call(API, {"channel_id": "102"}, status=503)
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertEqual(self.dashboard.notification_store.read(1)["channel_id"], "101")

    async def test_api_rechecks_owner_after_waiting_for_admin_lock(self):
        self.login_as(42)
        await self.dashboard.admin_lock.acquire()
        pending = asyncio.create_task(self.call(API, {"channel_id": "101"}, status=403))
        try:
            await asyncio.sleep(.02)
            self.bot.guild.get_member = lambda _: None
        finally:
            self.dashboard.admin_lock.release()
        await pending
        self.assertFalse(self.dashboard.notification_store.root.exists())
