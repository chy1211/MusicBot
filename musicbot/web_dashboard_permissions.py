"""Surgical permissions.ini editing. Never serializes live configuration."""
from __future__ import annotations
from .web_dashboard_i18n import message as _web_text
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
        fail(400, _web_text('m0558'))
    j = matches[0]
    start, end = bounds[j][0] + 1, bounds[j+1][0] if j+1 < len(bounds) else len(lines)
    option = re.compile(r"^([ \t]*" + re.escape(field) + r"[ \t]*[=:][ \t]*)(.*?)([ \t]*(?:[;#].*)?)(\r?\n)?$")
    found = [(i, m) for i in range(start, end) if (m := option.match(lines[i]))]
    rendered = ("yes" if value else "no") if type(value) is bool else str(value)
    if len(found) > 1:
        fail(400, _web_text('m0559'))
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
            values["GrantToRoles"] = [getattr(role, "name", _web_text('m0560')) if role else _web_text('m0560')
                                     for rid in sorted(group.granted_to_roles)
                                     for role in [getattr(guild, "get_role", lambda _: None)(rid)]]
            values["UserList"] = [str(getattr(member, "display_name", None) or getattr(member, "name", _web_text('m0561'))) if member else _web_text('m0561')
                                  for uid in sorted(group.user_list) for member in [guild.get_member(uid)]]
            result.append({"name": label, "values": values,
                           "editable": list(FIELDS) if label in existing else []})
        activity = []
        for stored in self.admin_records:
            row = dict(stored)
            params = row.pop("params", None)
            if params:
                def render(value):
                    return _web_text("m0210" if value else "m0211") if type(value) is bool else str(value)
                row["detail"] = _web_text("m0572", p0=params["group"], p1=params["field"],
                                         p2=render(params["old"]), p3=render(params["new"]))
            activity.append(row)
        return {"groups": result, "limits": {key: limit for key, (_, limit) in FIELDS.items()},
                "activity": activity}

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
                fail(400, _web_text('m0562'))
            group, field, value = data["group"], data["field"], data["value"]
            if not isinstance(group, str) or not isinstance(field, str) or field not in FIELDS:
                fail(400, _web_text('m0563'))
            attr, limit = FIELDS[field]
            if field == "AllowPlaylists":
                if type(value) is not bool:
                    fail(400, _web_text('m0564'))
            elif type(value) is not int or not 0 <= value <= limit:
                fail(400, _web_text('m0565', p0=field, p1=limit))
            original_permissions = self.bot.permissions
            if group not in original_permissions.groups:
                fail(400, _web_text('m0566'))
            old = getattr(original_permissions.groups[group], attr)
            if type(data["old_value"]) is not type(old) or data["old_value"] != old:
                fail(409, _web_text('m0567'))
            path = Path(self.bot._perms_file)
            raw = path.read_bytes()
            updated = replace_value(raw, group, field, value)
            backup = backup_file(path, self.backup_root / "permissions")
            temp = None
            replaced = False
            phase = "parse"
            try:
                fd, temp = tempfile.mkstemp(prefix=".permissions-web-", dir=path.parent)
                stat = path.stat()
                os.fchmod(fd, stat.st_mode & 0o777)
                try:
                    # Keep the host owner so permissions.ini stays editable over ssh.
                    os.fchown(fd, stat.st_uid, stat.st_gid)
                except OSError:
                    pass
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
                    fail(409, _web_text('m0568'))
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
                        fail(500, _web_text('m0569'))
                if isinstance(exc, asyncio.CancelledError):
                    raise
                from .web_dashboard import APIError
                if isinstance(exc, APIError):
                    raise
                fail(400 if phase == "parse" else 500,
                     _web_text('m0570') if phase == "parse" else _web_text('m0571'))
            finally:
                if temp and os.path.exists(temp):
                    os.unlink(temp)
            render = lambda v: (_web_text('m0210') if v else _web_text('m0211')) if type(v) is bool else str(v)
            self.admin_records.appendleft({"time": time.time(),
                "detail": _web_text('m0572', p0=group, p1=field, p2=render(old), p3=render(value)),
                "params":{"group":group,"field":field,"old":old,"new":value}})
            return web.json_response(dict(self.permissions_view(guild), message=_web_text('m0573')))
