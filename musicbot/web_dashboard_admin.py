"""Owner-only dashboard administration, using existing playlist/permission objects."""
from __future__ import annotations
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


class DashboardAdmin(DashboardPermissions):
    def init_admin(self):
        self.admin_lock = asyncio.Lock()
        self.backup_root = write_path("data/web_dashboard/backups")
        self.admin_records = deque(maxlen=100)
        self.init_permissions_admin()
        path = "/api/guilds/{guild_id}/admin/autoplaylist"
        self.app.router.add_get(path, self.admin_autoplaylist)
        self.app.router.add_post(path, self.admin_autoplaylist)
        self.app.router.add_delete(path, self.admin_autoplaylist)

    def require_owner(self, request):
        from .web_dashboard_auth import USER_KEY
        uid = int(request[USER_KEY]["id"]) if self.discord_auth else self.bot.config.owner_id
        if uid != self.bot.config.owner_id:
            fail(403, "只有 OwnerID 本人可以使用管理功能。")
        return self.guild_owner(request)

    def current_autoplaylist(self, guild):
        ssd = self.bot.server_data.get(guild.id)
        apl = getattr(ssd, "autoplaylist", None)
        if apl is None:
            fail(409, "目前沒有可用的自動播放清單。")
        return apl

    @staticmethod
    def autoplaylist_page(apl, request):
        from .web_dashboard import public_url
        query = request.query.get("q", "").strip()
        if len(query) > 100:
            fail(400, "搜尋最多 100 字。")
        raw_page = request.query.get("page", "1")
        if not raw_page.isascii() or not raw_page.isdigit() or not 1 <= int(raw_page) <= 1000000:
            fail(400, "頁碼必須是正整數。")
        rows = [{"index": i, "url": public_url(url)[:2000],
                 "title": "來源網址" if public_url(url) else "無法顯示的來源"}
                for i, url in enumerate(apl)]
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
                return web.json_response(self.autoplaylist_page(apl, request))
            data = await self.payload(request)
            if set(data) - {"revision", "url", "current", "index"}:
                fail(400, "不支援這個自動播放清單操作。")
            if data.get("revision") != apl_revision(apl):
                fail(409, "自動播放清單已更新，請重新整理後再操作。")
            if request.method == "POST":
                if data.get("current") is True:
                    player = self.bot.get_player_in(guild)
                    url = getattr(getattr(player, "current_entry", None), "url", "")
                else:
                    url = data.get("url")
                url = song({"title": "來源網址", "url": url, "duration": None})["url"]
                from .exceptions import MusicbotException
                try:
                    self.bot._do_song_blocklist_check(url)
                except MusicbotException:
                    fail(403, "這個來源已被封鎖清單擋下。")
                if url in apl:
                    fail(400, "這首歌已在自動播放清單中。")
            else:
                index = data.get("index")
                if type(index) is not int or not 0 <= index < len(apl):
                    fail(400, "歌曲位置不正確。")
                url = apl[index]
            backup_file(apl._file, self.backup_root / "autoplaylist")
            if request.method == "POST":
                await apl.add_track(url)
            else:
                await apl.remove_track(url, ex=UserWarning("由音樂控制台管理頁移除"), delete_from_ap=True)
            # Native methods deliberately log and swallow disk errors. Never
            # report success when memory and persisted content disagree.
            try:
                disk = apl._read_playlist()
                if disk != list(apl):
                    raise OSError()
            except OSError:
                await apl.load(force=True)
                fail(500, "自動播放清單寫入失敗；已重新讀取檔案，請檢查備份。")
            return web.json_response(dict(self.autoplaylist_page(apl, request), message="已更新自動播放清單。"))
