"""Private, bounded personal playlists; no Discord identifiers in payloads."""
from __future__ import annotations
import asyncio
import copy
import hashlib
import json
import logging
import math
import os
import secrets
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from aiohttp import web
from . import write_path
from .web_dashboard_auth import USER_KEY
from .web_dashboard_media import media_url, dedupe_favorites
from .web_dashboard_imports import DashboardImports, source_url

log = logging.getLogger(__name__)


def fail(status, message):
    from .web_dashboard import APIError
    raise APIError(status, message)


def song(value):
    from .web_dashboard import public_url
    if not isinstance(value, dict):
        fail(400, "歌曲資料格式不正確。")
    title, url, length = value.get("title"), value.get("url"), value.get("duration")
    if not isinstance(title, str) or not title.strip() or len(title) > 300:
        fail(400, "歌曲標題須為 1 至 300 字。")
    if not isinstance(url, str) or len(url) > 2000 or not public_url(url) or any(c.isspace() for c in url):
        fail(400, "歌曲網址只接受 HTTP／HTTPS，最多 2000 字且不可包含空白。")
    if length is not None and (type(length) not in (int, float) or not 0 <= length <= 31536000 or not math.isfinite(length)):
        fail(400, "歌曲長度須為非負秒數，或留空表示未知。")
    result = {"title": title.strip(), "url": url, "duration": length, "added_at": time.time()}
    cover = public_url(value.get("thumbnail"))
    if cover: result["thumbnail"] = cover
    return result


def name(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 60 or any(ord(c) < 32 for c in value):
        fail(400, "歌單名稱須為 1 至 60 字，且不可包含控制字元。")
    return value.strip()


def atomic_write(path, content):
    """Temp sibling -> flush/fsync -> replace; preserve the existing mode."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        if path.exists():
            stat = path.stat()
            os.fchmod(fd, stat.st_mode & 0o777)
            try:
                # The bot runs as root; keep host-owned files editable by their owner.
                os.fchown(fd, stat.st_uid, stat.st_gid)
            except OSError:
                pass
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class PlaylistStore:
    def __init__(self, root):
        self.root = Path(root)
        self.locks = defaultdict(asyncio.Lock)

    def path(self, uid):
        # uid always comes from the authenticated server session, never a body.
        if type(uid) is not int or not 0 < uid < 10**20:
            fail(403, "登入身分不正確。")
        return self.root / (str(uid) + ".json")

    @staticmethod
    def fresh():
        return {"version": 1, "playlists": [{"id": "favorites", "name": "收藏", "tracks": []}]}

    def read(self, uid):
        path = self.path(uid)
        if not path.exists():
            return self.fresh()
        try:
            if path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError()
            value = json.loads(path.read_text(encoding="utf-8"))
            if value["version"] != 1 or set(value) != {"version", "playlists"}:
                raise ValueError()
            lists = value["playlists"]
            if not isinstance(lists, list) or not 1 <= len(lists) <= 21:
                raise ValueError()
            ids = set()
            for index, item in enumerate(lists):
                if set(item) not in ({"id", "name", "tracks"}, {"id", "name", "tracks", "source_url", "source_type"}):
                    raise ValueError()
                if "source_url" in item:
                    canonical, kind = source_url(item["source_url"])
                    if index == 0 or canonical != item["source_url"] or kind != item["source_type"]:
                        raise ValueError()
                if not isinstance(item["id"], str) or item["id"] in ids:
                    raise ValueError()
                if not (item["id"] == "favorites" if index == 0 else len(item["id"]) == 24 and all(c in "0123456789abcdef" for c in item["id"])):
                    raise ValueError()
                ids.add(item["id"])
                name(item["name"])
                if not isinstance(item["tracks"], list) or len(item["tracks"]) > 200:
                    raise ValueError()
                for track in item["tracks"]:
                    if set(track) not in ({"title", "url", "duration", "added_at"}, {"title", "url", "duration", "added_at", "thumbnail"}):
                        raise ValueError()
                    song(track)
                    if type(track["added_at"]) not in (int, float) or not 0 < track["added_at"] < 10**12 or not math.isfinite(track["added_at"]):
                        raise ValueError()
            return value
        except Exception as exc:
            # OSError must not be mistaken for corruption (e.g. permissions).
            if isinstance(exc, OSError):
                raise
            path.rename(path.with_name(path.name + ".corrupt-" + str(time.time_ns())))
            log.error("Dashboard personal playlist quarantined (%s)", type(exc).__name__)
            fail(409, "歌單檔案損壞，已保留原檔供復原；請重新整理後再試。")

    @staticmethod
    def revision(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    async def transact(self, uid, change=None, revision=None, authorize=None):
        async with self.locks[uid]:
            if authorize is not None:
                authorize()
            value = self.read(uid)
            if revision is not None and revision != self.revision(value):
                fail(409, "歌單已更新，請重新整理後再操作。")
            if change is not None:
                dedupe_favorites(value)
                change(value)
                dedupe_favorites(value)
                atomic_write(self.path(uid), json.dumps(value, ensure_ascii=False).encode("utf-8"))
            return dict(copy.deepcopy(value), revision=self.revision(value))


class DashboardLibrary(DashboardImports):
    def init_library(self):
        self.playlist_store = PlaylistStore(write_path("data/web_dashboard/user_playlists"))
        self.init_imports()
        self.app.router.add_get("/api/library", self.library)
        self.app.router.add_post("/api/library", self.library)
        for method in ("PATCH", "DELETE"):
            self.app.router.add_route(method, "/api/library/{playlist_id}", self.library)
        self.app.router.add_post("/api/library/{playlist_id}/tracks", self.library)
        self.app.router.add_post("/api/guilds/{guild_id}/library/{playlist_id}/play", self.library_play)

    def library_identity(self, request):
        uid = int(request[USER_KEY]["id"]) if self.discord_auth else self.bot.config.owner_id
        found = False
        for guild in self.bot.guilds:
            member = guild.get_member(uid)
            if member is not None and not getattr(guild, "unavailable", False):
                self.check_blocked(member)
                found = True
        if not found:
            fail(403, "你目前不是機器人所在伺服器的成員。")
        return uid

    async def library(self, request):
        uid = self.library_identity(request)
        def authorize():
            if self.discord_auth:
                self.authenticate(request)
            if self.library_identity(request) != uid:
                fail(403, "登入身分已變更，請重新登入。")
        owner = uid == self.bot.config.owner_id
        if request.method == "GET":
            return web.json_response(dict(await self.playlist_store.transact(uid, authorize=authorize), owner=owner, sources={"spotify": self.spotify_import_enabled(), "youtube": True}))
        data = await self.payload(request)
        if any(key in data for key in ("user_id", "filename", "path")):
            fail(400, "請求包含不支援的欄位。")
        pid = request.match_info.get("playlist_id")
        message = "已更新歌單。"
        def change(value):
            nonlocal message
            if pid is None:
                if set(data) != {"name"}:
                    fail(400, "建立歌單只接受名稱。")
                if len(value["playlists"]) >= 21:
                    fail(400, "自訂歌單最多 20 份。")
                value["playlists"].append({"id": secrets.token_hex(12), "name": name(data.get("name")), "tracks": []})
                return
            target = next((item for item in value["playlists"] if item["id"] == pid), None)
            if target is None:
                fail(404, "找不到你的歌單。")
            if request.method == "DELETE":
                if pid == "favorites":
                    fail(400, "收藏不能刪除。")
                value["playlists"].remove(target)
            elif request.path.endswith("/tracks"):
                candidate = song(data.get("track"))
                if pid == "favorites" and any(media_url(t["url"]) == media_url(candidate["url"]) for t in target["tracks"]):
                    message = "已在收藏中"
                    return
                if len(target["tracks"]) >= 200:
                    fail(400, "每份歌單最多 200 首歌曲。")
                target["tracks"].append(candidate)
                message = "已收藏" if pid == "favorites" else message
            elif pid == "favorites" and data.get("action") == "remove_url":
                key = media_url(data.get("url"))
                if not key: fail(400, "請提供有效的歌曲網址。")
                target["tracks"][:] = [t for t in target["tracks"] if media_url(t["url"]) != key]
                message = "已取消收藏"
            elif "name" in data:
                if pid == "favorites":
                    fail(400, "收藏不能改名。")
                target["name"] = name(data["name"])
            elif data.get("action") in ("remove", "move"):
                tracks = target["tracks"]
                index = data.get("index")
                if type(index) is not int or not 0 <= index < len(tracks):
                    fail(400, "歌曲位置已失效，請重新整理。")
                if data["action"] == "remove":
                    tracks.pop(index)
                else:
                    dest = data.get("to")
                    if type(dest) is not int or not 0 <= dest < len(tracks):
                        fail(400, "歌曲位置不正確。")
                    tracks.insert(dest, tracks.pop(index))
            else:
                fail(400, "不支援這個歌單操作。")
        if pid is not None and not isinstance(data.get("revision"), str):
            fail(400, "請提供歌單版本，重新整理後再操作。")
        result = await self.playlist_store.transact(uid, change, data.get("revision"), authorize=authorize)
        return web.json_response(dict(result, owner=owner, message=message))

    async def library_play(self, request):
        uid = self.library_identity(request)
        guild, member = self.guild_owner(request)
        data = await self.payload(request)
        value = await self.playlist_store.transact(uid)
        if data.get("revision") != value["revision"]:
            fail(409, "歌單已更新，請重新整理後再加入。")
        target = next((item for item in value["playlists"] if item["id"] == request.match_info["playlist_id"]), None)
        if target is None:
            fail(404, "找不到你的歌單。")
        chosen = data.get("selected_items", [str(i) for i in range(len(target["tracks"]))])
        if (not isinstance(chosen, list) or not chosen or len(chosen) > 200
                or any(type(i) is not str or i not in {str(n) for n in range(len(target["tracks"]))} for i in chosen)
                or len(set(chosen)) != len(chosen)):
            fail(400, "請選取有效且不重複的歌曲。")
        self.user_rate_limit(member)
        preview = {"count": len(target["tracks"]), "url": "", "status": "ready",
                   "entries": [dict(item, item_id=str(i)) for i, item in enumerate(target["tracks"])]}
        from .web_dashboard_activity import capture, finish
        async with self.locks[guild.id]:
            value = capture(self, guild, member, "play", "web")
            try:
                result = await self.play_selection(request, {"selected_items": chosen}, preview, guild, member)
            except BaseException:
                finish(value, False)
                raise
            finish(value, result["added"] > 0)
            reasons = list(dict.fromkeys(row["reason"] for row in result["results"] if row["reason"]))
            return web.json_response(dict(result, message=f"已加入 {result['added']} 首，被拒 {result['skipped']} 首。" + "；".join(reasons),
                                          state=self.snapshot(guild, member)))
