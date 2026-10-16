"""Permissions edit transaction, byte preservation, native reload and rollback."""
import ast
import os
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import test_web_dashboard_admin as admin
import test_web_dashboard_discord as identity
from test_web_dashboard import BASE
from musicbot.permissions import Permissions
from musicbot.web_dashboard_permissions import replace_value

PERMS = BASE + "admin/permissions"
RAW = (b"# Keep this exact\r\n[Default]\r\n  MaxSongs  =  3  \r\n"
       b"# duration comment\r\nMaxSongLength = 210\r\nAllowPlaylists = no\r\n"
       b"\r\n[Friends]\r\nMaxSongs = 7\r\nGrantToRoles = 555 556\r\n"
       b"UserList = 43 999\r\n# Ending stays\r\n")


class PermissionTests(unittest.IsolatedAsyncioTestCase):
    provider_token = identity.DiscordTests.provider_token
    provider_me = identity.DiscordTests.provider_me
    call = identity.DiscordTests.call
    login_as = identity.DiscordTests.login_as

    async def asyncSetUp(self):
        await admin.AutoTests.asyncSetUp(self)
        self.path = Path(self.temp.name) / "permissions.ini"
        self.path.write_bytes(RAW)
        self.bot._perms_file = self.path
        self.bot.permissions = Permissions(self.path)
        self.bot.permissions.set_owner_id(42)
        for member in self.bot.members.values():
            member.roles = []
        self.bot.guild.get_role = lambda rid: NS(name="Music friends") if rid == 555 else None

    async def asyncTearDown(self):
        await admin.AutoTests.asyncTearDown(self)

    async def edit(self, field="MaxSongs", value=4, old=3, group="Default", status=200):
        return await self.call(PERMS, {"group": group, "field": field, "value": value, "old_value": old}, "PATCH", status)

    async def test_read_fields_names_no_ids_and_nonowner_403(self):
        result = await self.call(PERMS, method="GET")
        friends = next(item for item in result["groups"] if item["name"] == "Friends")["values"]
        self.assertEqual(friends["GrantToRoles"], ["Music friends", "未知角色"])
        self.assertEqual(friends["UserList"], ["Friend", "未知成員"])
        self.assertNotIn("555", str(result))
        self.assertNotIn("999", str(result))
        self.assertEqual(set(friends), {"MaxSongs", "MaxSongLength", "MaxPlaylistLength", "MaxSearchItems",
            "AllowPlaylists", "InstaSkip", "SkipLooped", "Remove", "SkipWhenAbsent", "BypassKaraokeMode",
            "SummonNoVoice", "Extractors", "CommandWhitelist", "CommandBlacklist", "GrantToRoles", "UserList"})
        self.login_as(43)
        await self.call(PERMS, method="GET", status=403)
        await self.edit(status=403)

    async def test_only_target_value_changes_bytes_and_reload_replaces_object(self):
        old = self.bot.permissions
        result = await self.edit()
        self.assertEqual(self.path.read_bytes(), RAW.replace(b"MaxSongs  =  3", b"MaxSongs  =  4", 1))
        self.assertIsNot(self.bot.permissions, old)
        self.assertEqual(self.bot.permissions.default_group.max_songs, 4)
        self.assertEqual(self.bot.permissions.owner_group.user_list, {42})
        copies = list((self.dashboard.backup_root / "permissions").iterdir())
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].read_bytes(), RAW)
        self.assertIn("Default MaxSongs 3→4", result["activity"][0]["detail"])
        self.assertEqual(list(self.path.parent.glob("*.bak*")), [])
        self.assertEqual(list(self.path.parent.glob(".permissions-web-*")), [])
        # Management records never enter the shared activity stream.
        shared = await self.call(BASE + "activity", method="GET")
        self.assertNotIn("修改權限", str(shared))

    async def test_missing_field_inserted_in_target_group_and_all_four_allowed(self):
        await self.edit("MaxPlaylistLength", 8, 0)
        expected = RAW.replace(b"\r\n[Friends]", b"\r\nMaxPlaylistLength = 8\r\n[Friends]")
        self.assertEqual(self.path.read_bytes(), expected)
        await self.edit("AllowPlaylists", True, False)
        await self.edit("MaxSongLength", 86400, 210)
        await self.edit("MaxSongs", 10000, 3)
        self.assertTrue(self.bot.permissions.default_group.allow_playlists)

    async def test_only_existing_groups_and_four_fields_and_values(self):
        for field in ("UserList", "GrantToRoles", "CommandWhitelist", "InstaSkip", "__dict__", "max_songs"):
            await self.edit(field=field, status=400)
        for value in (-1, True, None, "4", 3.1, 10001):
            await self.edit(value=value, status=400)
        await self.edit("MaxSongLength", 86401, 210, status=400)
        for value in ("yes", 1, None):
            await self.edit("AllowPlaylists", value, False, status=400)
        await self.edit(group="New group", status=400)
        await self.edit(group="Owner (auto)", old=0, status=400)
        await self.edit(old=99, status=409)
        self.assertEqual(self.path.read_bytes(), RAW)

    async def test_parser_failure_keeps_file_memory_and_drops_temp(self):
        old = self.bot.permissions
        with patch("musicbot.web_dashboard_permissions.Permissions", side_effect=ValueError("SECRET PATH")):
            result = await self.edit(status=400)
        self.assertNotIn("SECRET", str(result))
        self.assertEqual(self.path.read_bytes(), RAW)
        self.assertIs(self.bot.permissions, old)
        self.assertEqual(list(self.path.parent.glob(".permissions-web-*")), [])

    async def test_final_parse_failure_restores_file_and_memory(self):
        old = self.bot.permissions
        count = 0
        def parse(path):
            nonlocal count
            count += 1
            if count == 2:
                raise ValueError("do not expose")
            return Permissions(path)
        with patch("musicbot.web_dashboard_permissions.Permissions", side_effect=parse):
            await self.edit(status=500)
        self.assertEqual(count, 2)
        self.assertEqual(self.path.read_bytes(), RAW)
        self.assertIs(self.bot.permissions, old)

    async def test_async_reload_failure_restores(self):
        old = self.bot.permissions
        with patch.object(Permissions, "async_validate", new=AsyncMock(side_effect=RuntimeError())):
            await self.edit(status=500)
        self.assertEqual(self.path.read_bytes(), RAW)
        self.assertIs(self.bot.permissions, old)

    async def test_replace_failure_keeps_original_and_memory(self):
        old = self.bot.permissions
        with patch("musicbot.web_dashboard_permissions.os.replace", side_effect=OSError()):
            await self.edit(status=500)
        self.assertEqual(self.path.read_bytes(), RAW)
        self.assertIs(self.bot.permissions, old)

    async def test_directory_sync_failure_after_replace_rolls_back(self):
        real = os.fsync
        calls = 0
        def fsync(fd):
            nonlocal calls
            calls += 1
            # backup fsync, candidate fsync, directory fsync
            if calls == 3:
                raise OSError()
            return real(fd)
        with patch("musicbot.web_dashboard_permissions.os.fsync", side_effect=fsync):
            await self.edit(status=500)
        self.assertEqual(self.path.read_bytes(), RAW)

    async def test_external_edit_detected_without_overwrite(self):
        edited = RAW + b"# external\r\n"
        def parse(path):
            value = Permissions(path)
            self.path.write_bytes(edited)
            return value
        with patch("musicbot.web_dashboard_permissions.Permissions", side_effect=parse):
            await self.edit(status=409)
        self.assertEqual(self.path.read_bytes(), edited)

    async def test_backup_failure_aborts_before_edit(self):
        with patch("musicbot.web_dashboard_admin.backup_file", side_effect=OSError()):
            await self.edit(status=500)
        self.assertEqual(self.path.read_bytes(), RAW)


class TextEditTests(unittest.TestCase):
    def test_inline_comments_whitespace_and_other_groups_unchanged(self):
        raw = b"# heading\n[A]\n  MaxSongs = 3  ; keep inline\n# still here\n[B]\nMaxSongs=9\n"
        self.assertEqual(replace_value(raw, "A", "MaxSongs", 5), raw.replace(b"3  ;", b"5  ;"))
        self.assertEqual(replace_value(b"[A]\n# end", "A", "AllowPlaylists", False), b"[A]\n# end\nAllowPlaylists = no\n")

    def test_no_save_command_or_configuration_serializer_paths(self):
        root = Path(__file__).parents[1]
        for filename in ("web_dashboard.py", "web_dashboard_library.py", "web_dashboard_admin.py", "web_dashboard_permissions.py"):
            tree = ast.parse((root / "musicbot" / filename).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, {"cmd_setperms", "cmd_config", "save", "write_default_ini", "save_group"})
        for filename in ("bot.py", "permissions.py", "autoplaylist.py"):
            self.assertTrue((root / "musicbot" / filename).exists())
