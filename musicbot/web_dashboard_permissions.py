"""Surgical permissions.ini editing. Never serializes live configuration."""
from __future__ import annotations
import asyncio
import os
import re
import tempfile
import time
from pathlib import Path

from aiohttp import web
from .permissions import Permissions
from .web_dashboard_library import fail, atomic_write

FIELDS = {
    "MaxSongs": ("max_songs", 10000), "MaxSongLength": ("max_song_length", 86400),
    "MaxPlaylistLength": ("max_playlist_length", 10000), "AllowPlaylists": ("allow_playlists", None),
}
READ_FIELDS = {
    **{key: val[0] for key, val in FIELDS.items()}, "MaxSearchItems": "max_search_items",
    "InstaSkip": "instaskip", "SkipLooped": "skip_looped", "Remove": "remove",
    "SkipWhenAbsent": "skip_when_absent", "BypassKaraokeMode": "bypass_karaoke_mode",
    "SummonNoVoice": "summonplay", "Extractors": "extractors",
    "CommandWhitelist": "command_whitelist", "CommandBlacklist": "command_blacklist",
}
SECTION = re.compile(r"^[ \t]*\[([^\]\r\n]+)\]")


def sections(text):
    return [(i, match.group(1)) for i, line in enumerate(text.splitlines(keepends=True))
            if (match := SECTION.match(line))]


def replace_value(raw, group, field, value):
    """Replace one value span, preserving every other byte including line ends."""
    text = raw.decode("utf-8")
    lines = text.splitlines(keepends=True)
    bounds = sections(text)
    matches = [j for j, (_, label) in enumerate(bounds) if label == group]
    if len(matches) != 1:
        fail(400, "只能修改檔案中既有的權限群組。")
    j = matches[0]
    start, end = bounds[j][0] + 1, bounds[j+1][0] if j+1 < len(bounds) else len(lines)
    option = re.compile(r"^([ \t]*" + re.escape(field) + r"[ \t]*[=:][ \t]*)(.*?)([ \t]*(?:[;#].*)?)(\r?\n)?$")
    found = [(i, m) for i in range(start, end) if (m := option.match(lines[i]))]
    rendered = ("yes" if value else "no") if type(value) is bool else str(value)
    if len(found) > 1:
        fail(400, "目標欄位重複，請先檢查權限檔案。")
    if found:
        i, m = found[0]
        lines[i] = m[1] + rendered + m[3] + (m[4] or "")
    else:
        newline = "\r\n" if "\r\n" in text else "\n"
        if end and not lines[end-1].endswith(("\n", "\r")):
            lines[end-1] += newline
        lines.insert(end, field + " = " + rendered + newline)
    return "".join(lines).encode("utf-8")


class DashboardPermissions:
    def init_permissions_admin(self):
        path = "/api/guilds/{guild_id}/admin/permissions"
        self.app.router.add_get(path, self.admin_permissions)
        self.app.router.add_patch(path, self.admin_permissions)

    def permissions_view(self, guild):
        path = Path(self.bot._perms_file)
        existing = {label for _, label in sections(path.read_text(encoding="utf-8"))}
        result = []
        for label, group in self.bot.permissions.groups.items():
            values = {}
            for key, attr in READ_FIELDS.items():
                value = getattr(group, attr)
                values[key] = sorted(value) if isinstance(value, set) else value
            values["GrantToRoles"] = [getattr(role, "name", "未知角色") if role else "未知角色"
                                     for rid in sorted(group.granted_to_roles)
                                     for role in [getattr(guild, "get_role", lambda _: None)(rid)]]
            values["UserList"] = [str(getattr(member, "display_name", None) or getattr(member, "name", "未知成員")) if member else "未知成員"
                                  for uid in sorted(group.user_list) for member in [guild.get_member(uid)]]
            result.append({"name": label, "values": values,
                           "editable": list(FIELDS) if label in existing else []})
        return {"groups": result, "limits": {key: limit for key, (_, limit) in FIELDS.items()},
                "activity": list(self.admin_records)}

    async def admin_permissions(self, request):
        from .web_dashboard_admin import backup_file
        guild, owner = self.require_owner(request)
        async with self.admin_lock:
            if self.discord_auth:
                self.authenticate(request)
            guild, owner = self.require_owner(request)
            if request.method == "GET":
                return web.json_response(self.permissions_view(guild))
            data = await self.payload(request)
            if set(data) != {"group", "field", "value", "old_value"}:
                fail(400, "修改權限須提供群組、欄位、舊值與新值。")
            group, field, value = data["group"], data["field"], data["value"]
            if not isinstance(group, str) or not isinstance(field, str) or field not in FIELDS:
                fail(400, "只能修改 MaxSongs、MaxSongLength、MaxPlaylistLength、AllowPlaylists。")
            attr, limit = FIELDS[field]
            if field == "AllowPlaylists":
                if type(value) is not bool:
                    fail(400, "AllowPlaylists 必須是是／否。")
            elif type(value) is not int or not 0 <= value <= limit:
                fail(400, f"{field} 必須是 0 至 {limit} 的整數。")
            original_permissions = self.bot.permissions
            if group not in original_permissions.groups:
                fail(400, "只能修改既有的權限群組。")
            old = getattr(original_permissions.groups[group], attr)
            if type(data["old_value"]) is not type(old) or data["old_value"] != old:
                fail(409, "權限值已更新，請重新整理並再次確認。")
            path = Path(self.bot._perms_file)
            raw = path.read_bytes()
            updated = replace_value(raw, group, field, value)
            backup = backup_file(path, self.backup_root / "permissions")
            temp = None
            replaced = False
            phase = "parse"
            try:
                fd, temp = tempfile.mkstemp(prefix=".permissions-web-", dir=path.parent)
                os.fchmod(fd, path.stat().st_mode & 0o777)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(updated)
                    stream.flush()
                    os.fsync(stream.fileno())
                candidate = Permissions(Path(temp))
                if getattr(candidate.groups[group], attr) != value:
                    raise ValueError()
                if self.discord_auth:
                    self.authenticate(request)
                self.require_owner(request)
                # Do not overwrite a simultaneous native/external config edit.
                if path.read_bytes() != raw or self.bot.permissions is not original_permissions:
                    fail(409, "權限檔案或記憶體已更新，請重新整理後再試。")
                phase = "reload"
                os.replace(temp, path)
                replaced = True
                directory = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
                # Exactly the existing cmd_setperms reload sequence.
                loaded = Permissions(path)
                loaded.set_owner_id(self.bot.config.owner_id)
                await loaded.async_validate(self.bot)
                # A reload can await validation; recheck before publishing.
                if self.discord_auth:
                    self.authenticate(request)
                guild, owner = self.require_owner(request)
                self.bot.permissions = loaded
            except BaseException as exc:
                if replaced:
                    try:
                        atomic_write(path, backup.read_bytes())
                        self.bot.permissions = original_permissions
                    except Exception:
                        fail(500, "權限還原失敗，請由管理者檢查備份後復原。")
                if isinstance(exc, asyncio.CancelledError):
                    raise
                from .web_dashboard import APIError
                if isinstance(exc, APIError):
                    raise
                fail(400 if phase == "parse" else 500,
                     "權限檔案驗證失敗，原檔未變動。" if phase == "parse" else "權限重新載入失敗，已還原原檔與記憶體。")
            finally:
                if temp and os.path.exists(temp):
                    os.unlink(temp)
            render = lambda v: ("是" if v else "否") if type(v) is bool else str(v)
            self.admin_records.appendleft({"time": time.time(),
                "detail": f"管理：修改權限 {group} {field} {render(old)}→{render(value)}"})
            return web.json_response(dict(self.permissions_view(guild), message="權限已更新並重新載入。"))
