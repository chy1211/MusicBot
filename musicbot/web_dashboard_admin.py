"""Owner-only dashboard administration, using existing playlist/permission objects."""
from __future__ import annotations
from .web_dashboard_i18n import message as _web_text
import asyncio
import hashlib
import logging
import os
import secrets
from collections import deque
from datetime import datetime
from pathlib import Path

from aiohttp import web
from . import write_path
from .web_dashboard_library import fail, song
from .web_dashboard_permissions import DashboardPermissions
from .web_dashboard_notifications import DashboardNotifications

log = logging.getLogger(__name__)


def backup_file(source, root):
    source, root = Path(source), Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    stem = source.name + "." + datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = root / stem
    if dest.exists():
        dest = root / (stem + "-" + secrets.token_hex(4))
    # Read before touching the destination; no config-directory backup ever.
    raw = source.read_bytes()
    with dest.open("xb") as stream:
        os.chmod(dest, 0o600)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    copies = sorted(root.glob(source.name + ".*"), key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    for old in copies[30:]:
        old.unlink()
    return dest


def apl_revision(apl):
    return hashlib.sha256(repr(list(apl)).encode()).hexdigest()


class DashboardAdmin(DashboardPermissions, DashboardNotifications):
    def init_admin(self):
        self.admin_lock = asyncio.Lock()
        self.backup_root = write_path("data/web_dashboard/backups")
        self.admin_records = deque(maxlen=100)
        self.init_permissions_admin()
        self.init_notifications()
        path = "/api/guilds/{guild_id}/admin/autoplaylist"
        self.app.router.add_get(path, self.admin_autoplaylist)
        self.app.router.add_post(path, self.admin_autoplaylist)
        self.app.router.add_delete(path, self.admin_autoplaylist)

    def require_owner(self, request):
        from .web_dashboard_auth import USER_KEY
        uid = int(request[USER_KEY]["id"]) if self.discord_auth else self.bot.config.owner_id
        if uid != self.bot.config.owner_id:
            fail(403, _web_text('m0476'))
        return self.guild_owner(request)

    def current_autoplaylist(self, guild):
        ssd = self.bot.server_data.get(guild.id)
        apl = getattr(ssd, "autoplaylist", None)
        if apl is None:
            fail(409, _web_text('m0477'))
        return apl

    def autoplaylist_page(self, apl, request, guild):
        from .web_dashboard import public_url
        query = request.query.get("q", "").strip()
        if len(query) > 100:
            fail(400, _web_text('m0478'))
        raw_page = request.query.get("page", "1")
        if not raw_page.isascii() or not raw_page.isdigit() or not 1 <= int(raw_page) <= 1000000:
            fail(400, _web_text('m0479'))
        # Enrich only with metadata already held in guild memory; do not
        # extract or issue remote requests when opening the admin page.
        known = {}
        for item in list(self.recent_history.get(guild.id, ()))[:100]:
            url = public_url(item.get("url", ""))
            if url:
                known[url] = item
        player = self.bot.get_player_in(guild)
        if player is not None:
            live_entries = [getattr(player, "current_entry", None)]
            live_entries += list(player.playlist.entries)[:100]
            for entry in live_entries:
                if entry is None:
                    continue
                url = public_url(getattr(entry, "url", ""))
                if url:
                    known[url] = {"title": getattr(entry, "title", ""),
                                  "thumbnail": getattr(entry, "thumbnail_url", ""),
                                  "duration": getattr(entry, "duration", 0)}
        from urllib.parse import urlsplit, parse_qs
        import re

        def public_cover(url):
            # Standard public YouTube video cover, derived without extraction.
            try:
                parts = urlsplit(url)
                host = (parts.hostname or "").lower()
                video_id = ""
                if host in ("youtube.com", "www.youtube.com", "m.youtube.com") and parts.path == "/watch":
                    video_id = parse_qs(parts.query).get("v", [""])[0]
                elif host in ("youtu.be", "www.youtu.be"):
                    video_id = parts.path.strip("/")
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                    return "https://i.ytimg.com/vi/" + video_id + "/hqdefault.jpg"
            except ValueError:
                pass
            return ""

        rows = []
        for i, url in enumerate(apl):
            safe = public_url(url)[:2000]
            meta = known.get(safe, {})
            title = meta.get("title", "") if isinstance(meta, dict) else ""
            valid_title = isinstance(title, str) and bool(title.strip()) and len(title) <= 300
            rows.append({"index": i, "url": safe,
                         "title": title.strip() if valid_title else
                                  _web_text('m0480') if safe else _web_text('m0481'),
                         "known": bool(valid_title),
                         "thumbnail": (public_url(meta.get("thumbnail", "")) if isinstance(meta, dict) else "")
                                      or public_cover(safe)})
        # Only searchable public text, never a legacy local path.
        filtered = [row for row in rows if query.lower() in (row["url"] + row["title"]).lower()]
        page = int(raw_page)
        return {"total": len(rows), "matched": len(filtered), "page": page, "page_size": 50,
                "tracks": filtered[(page-1)*50:page*50], "revision": apl_revision(apl)}

    async def admin_autoplaylist(self, request):
        guild, _owner = self.require_owner(request)
        async with self.admin_lock:
            # Recheck identity, membership and the active list after waiting.
            if self.discord_auth:
                self.authenticate(request)
            guild, _owner = self.require_owner(request)
            apl = self.current_autoplaylist(guild)
            await apl.load()
            if request.method == "GET":
                return web.json_response(self.autoplaylist_page(apl, request, guild))
            data = await self.payload(request)
            if set(data) - {"revision", "url", "current", "index"}:
                fail(400, _web_text('m0482'))
            if data.get("revision") != apl_revision(apl):
                fail(409, _web_text('m0483'))
            if request.method == "POST":
                if data.get("current") is True:
                    player = self.bot.get_player_in(guild)
                    url = getattr(getattr(player, "current_entry", None), "url", "")
                else:
                    url = data.get("url")
                url = song({"title": _web_text('m0480'), "url": url, "duration": None})["url"]
                from .exceptions import MusicbotException
                try:
                    self.bot._do_song_blocklist_check(url)
                except MusicbotException:
                    fail(403, _web_text('m0484'))
                if url in apl:
                    fail(400, _web_text('m0485'))
            else:
                index = data.get("index")
                if type(index) is not int or not 0 <= index < len(apl):
                    fail(400, _web_text('m0486'))
                url = apl[index]
            backup_file(apl._file, self.backup_root / "autoplaylist")
            if request.method == "POST":
                await apl.add_track(url)
            else:
                await apl.remove_track(url, ex=UserWarning(_web_text('m0487')), delete_from_ap=True)
            # Native methods deliberately log and swallow disk errors. Never
            # report success when memory and persisted content disagree.
            try:
                disk = apl._read_playlist()
                if disk != list(apl):
                    raise OSError()
            except OSError:
                await apl.load(force=True)
                fail(500, _web_text('m0488'))
            return web.json_response(dict(self.autoplaylist_page(apl, request, guild), message=_web_text('m0006')))
