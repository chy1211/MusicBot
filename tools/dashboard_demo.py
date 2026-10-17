"""Credential-free dashboard demo. Never creates a Discord client or downloads media."""
from __future__ import annotations

import argparse
import builtins
import asyncio
import signal
import time
import tempfile
from pathlib import Path
from collections import deque
from types import SimpleNamespace as NS

from aiohttp import web

from musicbot.downloader import YtdlpResponseDict
from musicbot.bot import MusicBot, build_play_response
from musicbot.constructs import SkipState
from musicbot.entry import URLPlaylistEntry
from musicbot.web_dashboard import Dashboard, DashboardConfig, CONFIRMED_ENTRY_CHECK


# This executable does not initialize MusicBot/gettext.
if not callable(getattr(builtins, "_D", None)):
    builtins._D = lambda text, _ssd: text

TITLES = ["夜色慢行", "窗邊的午後", "島嶼來信", "凌晨兩點的海", "微風練習曲"]


class DemoPlaylist:
    def __init__(self, songs):
        self.entries = deque(songs)

    def count_for_user(self, owner):
        return sum(getattr(getattr(song, "author", None), "id", None) == owner.id for song in self.entries)

    def get_entry_at_index(self, index):
        return self.entries[index]

    def delete_entry_at_index(self, index):
        song = self.entries[index]
        del self.entries[index]
        return song

    def insert_entry_at_index(self, index, song):
        self.entries.insert(index, song)

    def shuffle(self):
        import random
        songs = list(self.entries)
        random.shuffle(songs)
        self.entries = deque(songs)


class DemoBot:
    def __init__(self, origin):
        self.origin = origin.rstrip("/")
        self.config = NS(owner_id=42, bound_channels=set(), unbound_servers=True,
                         default_search_service="ytsearch", spotify_enabled=False,
                         allow_author_skip=True, legacy_skip=True, bot_exception_ids=set(),
                         skips_required=2, skip_ratio_required=.5,
                         enable_queue_history_global=False, enable_queue_history_guilds=False)
        self.perms = NS(max_songs=0, max_song_length=0, max_search_items=5,
                        allow_playlists=True, max_playlist_length=30,
                        bypass_karaoke_mode=True, summonplay=True, ignore_non_voice=set(),
                        remove=True, instaskip=True, skip_looped=True,
                        can_use_command=lambda *_: True, can_use_extractor=lambda _: None)
        self.member_perms = NS(**vars(self.perms))
        self.member_perms.max_song_length = 210
        self.member_perms.max_songs = 3
        self.member_perms.allow_playlists = False
        self.member_perms.remove = self.member_perms.instaskip = False
        self.denied_perms = NS(**vars(self.member_perms))
        self.denied_perms.can_use_command = lambda *_: False
        self.permissions = NS(for_user=lambda member: self.perms if member.id == 42 else
                              self.denied_perms if member.id == 45 else self.member_perms)
        self.filecache = NS(remove_autoplay_cachemap_entry_by_url=lambda *_: None)
        self.discord_messages = []
        self.dashboard = None
        self.members = {}
        self.guilds, self.players, self.server_data = [], {}, {}
        self.init_ok, self.logout_called = True, False
        self.downloader = NS(extract_info=self.extract,
                             get_url_or_none=lambda q: q if q.startswith(("http://", "https://")) else None)
        for gid, name in ((1, "深夜音樂室"), (2, "午後咖啡館")):
            guild = NS(id=gid, name=name, unavailable=False, me=NS(voice=None))
            members = {uid: NS(id=uid, name=name, display_name=name, voice=None, bot=False)
                       for uid, name in ((42, "Owner"), (43, "一般成員"),
                                         (44, "不在語音頻道"), (45, "無指令權限"))}
            self.members[gid] = members
            owner = members[42]
            channel = NS(id=gid * 10, guild=guild, name="示範語音室", typing=self.noop,
                         permissions_for=lambda _: NS(view_channel=True, send_messages=True))
            for uid in (42, 43, 45):
                members[uid].voice = NS(channel=channel, deaf=False, self_deaf=False)
            for uid, member in members.items():
                member.display_avatar = NS(url=f"{self.origin}/demo-cover/{uid % 5}.svg")
            channel.members = [members[uid] for uid in (42, 43, 45)]
            # Include enough listeners to exercise folding, plus bots to exclude.
            channel.members += [NS(id=100+i, name=f"聽眾 {i+1}", display_name=f"聽眾 {i+1}",
                                   display_avatar=NS(url=f"{self.origin}/demo-cover/{i % 5}.svg"),
                                   voice=NS(channel=channel, deaf=False, self_deaf=False),
                                   bot=False) for i in range(8)]
            channel.members += [NS(id=900, name="示範機器人", bot=True)]
            guild.me.voice = NS(channel=channel)
            guild.get_member = members.get
            guild.get_channel = lambda cid, ch=channel: ch if cid == ch.id else None
            text = NS(id=gid * 10 + 1, guild=guild, name="點歌文字頻道", typing=self.noop,
                      permissions_for=lambda _: NS(view_channel=True, send_messages=True))
            guild.get_channel = lambda cid, vc=channel, tc=text: next(
                (ch for ch in (vc, tc) if ch.id == cid), None)
            guild.system_channel = text
            guild.channels, guild.text_channels = [channel, text], [text]
            self.guilds.append(guild)
            self.server_data[gid] = None
            self.players[gid] = NS(
                current_entry=self.song(gid - 1),
                playlist=DemoPlaylist([self.song(i) for i in range(1, 5)]),
                voice_client=NS(channel=channel), progress=37., volume=.35,
                is_playing=True, is_paused=False, is_stopped=False,
                repeatsong=False, loopqueue=False, karaoke_mode=False,
                skip_state=SkipState(), tick=time.monotonic())
            player = self.players[gid]
            player.current_entry.author, player.current_entry.channel = owner, text
            for index, song in enumerate(player.playlist.entries):
                song.author, song.channel = members[43] if index == 1 else owner, text
                if index == 2:
                    song = self.song(20, title="示範直播（長度未知）", duration=0)
                    song.author, song.channel = owner, text
                    player.playlist.entries[index] = song
                if index == 3:
                    song.author, song.channel = None, None
            def skip(p=player, g=guild):
                previous = p.current_entry
                p.current_entry = p.playlist.entries.popleft() if p.playlist.entries else None
                p.progress = p.current_entry.start_time if p.current_entry else 0
                p.tick = time.monotonic()
                p.skip_state.reset()
                if self.dashboard and p.current_entry is not previous:
                    self.dashboard.record_play(g, p.current_entry)
            player.skip = skip

    def song(self, index, title=None, duration=None, url=None):
        # Real entry metadata and seek logic; no downloader/cache operation runs.
        info = YtdlpResponseDict({
            "__input_subject": f"https://example.test/track/{index}",
            "title": title or TITLES[index % len(TITLES)],
            "webpage_url": url or f"https://example.test/track/{index}",
            "thumbnail": f"{self.origin}/demo-cover/{index % 5}.svg",
            "duration": duration if duration is not None else 180 + index * 17,
            "artist": "示範樂團", "extractor": "demo", "id": str(index)})
        return URLPlaylistEntry(NS(bot=self), info)

    async def noop(self, *_args, **_kwargs):
        return None

    is_ready = lambda self: True
    get_guild = lambda self, gid: next((g for g in self.guilds if g.id == gid), None)
    serialize_queue = noop

    def get_player_in(self, guild):
        player = self.players[guild.id]
        now = time.monotonic()
        if player.is_playing and player.current_entry:
            player.progress += now - player.tick
            if (player.current_entry.duration or 0) > 0 and player.progress >= player.current_entry.duration:
                player.skip()
        player.tick = now
        return player

    async def get_player(self, channel, **_kwargs):
        return self.get_player_in(channel.guild)

    def _do_song_blocklist_check(self, value):
        from musicbot.exceptions import PermissionsError
        if "blocked" in value.lower():
            raise PermissionsError("Demo blocklist")

    _do_playlist_checks = MusicBot._do_playlist_checks
    _check_ignore_non_voice = MusicBot._check_ignore_non_voice
    cmd_remove = MusicBot.cmd_remove
    cmd_skip = MusicBot.cmd_skip
    cmd_seek = MusicBot.cmd_seek

    async def extract(self, query, **kwargs):
        assert kwargs == {"download": False, "process": True}
        await asyncio.sleep(.15)
        def info(index):
            song = self.song(index)
            return {"__input_subject": query, "_type": "video", "title": "blocked 範例歌曲" if index % 7 == 6 else song.title + f" {index + 1}",
                    "webpage_url": song.url, "duration": song.duration,
                    "thumbnail": song.thumbnail_url, "extractor": "demo", "id": str(index)}
        if query.startswith("ytsearch"):
            data = {"__input_subject": query, "title": "搜尋結果", "extractor": "demo:search",
                    "entries": [info(i) for i in range(5)]}
        elif "playlist" in query:
            data = {"__input_subject": query, "title": "週末慢慢聽", "extractor": "demo:playlist",
                    "playlist_count": 24, "entries": [info(i) for i in range(24)]}
        else:
            try:
                index = int(query.rsplit("/", 1)[-1])
            except ValueError:
                index = 0
            data = info(index)
        return YtdlpResponseDict(data)

    async def cmd_playnext(self, **kwargs):
        return await self.cmd_play(_head=True, **kwargs)

    async def cmd_play(self, *, player, song_url, author, channel, _head=False, **_kwargs):
        # Fake boundary only: the real Dashboard calls the same cmd_play entry point.
        data = await self.extract(song_url, download=False, process=True)
        permissions = self.permissions.for_user(author)
        validator = CONFIRMED_ENTRY_CHECK.get()
        if validator is not None:
            permissions = validator(data)
        if data.has_entries:
            await self._do_playlist_checks(player, author, data)
        from musicbot.exceptions import PermissionsError
        for info in (data.get_entries_objects() if data.has_entries else [data]):
            self._do_song_blocklist_check(info.title)
            if permissions.max_song_length and info.duration > permissions.max_song_length:
                raise PermissionsError("Song duration exceeds limit.")
            if permissions.max_songs and player.playlist.count_for_user(author) >= permissions.max_songs:
                raise PermissionsError("Queue limit reached.")
            song = self.song(int(info.get("id") or 0), title=info.title,
                             duration=info.duration, url=info.webpage_url)
            song.author, song.channel = author, channel
            if _head:
                player.playlist.entries.appendleft(song)
            else:
                player.playlist.entries.append(song)
            if self.dashboard:
                self.dashboard.note_queue_entry(channel.guild, song)
                await self.dashboard.popularity_store.record(channel.guild, song)
            if validator is not None:
                validator.enqueued = True
        return build_play_response(self.server_data[channel.guild.id], number=1,
            track=song.title, position=str(len(player.playlist.entries)) + " - estimated time until playing: `00:30`")


    async def safe_send_message(self, channel, response, **_kwargs):
        # The demo never connects Discord; expose exactly what would be sent.
        import json
        value = {"channel": channel.name, "response": response.to_dict(),
                 "delete_after": response.delete_after}
        self.discord_messages.append(value)
        print("DEMO Discord notification " + json.dumps(value, ensure_ascii=False), flush=True)
        return None

    async def cmd_pause(self, _ssd, player):
        player.is_playing, player.is_paused = False, True

    async def cmd_resume(self, _ssd, player):
        player.is_playing, player.is_paused = True, False

    async def cmd_volume(self, _ssd, player, volume):
        player.volume = int(volume) / 100

    async def cmd_repeat(self, _ssd, player, mode):
        if mode == "all":
            player.loopqueue = not player.loopqueue
            player.repeatsong = False
        else:
            player.repeatsong = mode == "on"


FAKE_USERS = {"owner": (42, "Owner"), "member": (43, "一般成員"),
              "away": (44, "不在語音頻道"), "denied": (45, "無指令權限")}


class FakeLyricsClient:
    """Original demo lyrics only. Never constructs an HTTP client."""
    async def lookup(self, title, artist, duration, query=""):
        subject = query.strip() or title
        if TITLES[0] in subject:
            lines = [
                {"time": 0, "text": "夜色慢慢落在街角"},
                {"time": 15, "text": "把今天的心事輕輕放好"},
                {"time": 30, "text": "沿著燈光走向海的方向"},
                {"time": 45, "text": "每一步都有溫柔回響"},
                {"time": 60, "text": "等微風吹過，明天再出發"},
                {"time": 90, "text": "讓這一刻陪我們慢慢唱"}]
            return {"status": "synced", "title": TITLES[0], "artist": "示範樂團",
                    "plain_lyrics": "\n".join(line["text"] for line in lines), "lines": lines}
        if TITLES[1] in subject:
            return {"status": "plain", "title": TITLES[1], "artist": "示範樂團",
                    "plain_lyrics": "窗邊的午後，留一盞光\n把遠方的問候，寫成一行\n咖啡的香氣，陪風一起晃",
                    "lines": []}
        return {"status": "not_found", "title": subject, "artist": "",
                "plain_lyrics": "", "lines": []}

    async def close(self):
        pass


class DemoDashboard(Dashboard):
    """Fake login exists only in this explicit demo executable, never production."""
    def __init__(self, bot, config, fake_login=None):
        self.fake_login = fake_login
        self.demo_temp = tempfile.TemporaryDirectory(prefix="musicbot-webtest-demo-")
        super().__init__(bot, config)
        # Replace the provider boundary before any request can run.
        self.popularity_store.root = Path(self.demo_temp.name) / "stats"
        import datetime as dt
        for guild in bot.guilds:
            tracks = {}
            for index in range(5):
                url = f"https://example.test/track/{index}"
                today = dt.datetime.now(dt.timezone.utc).date()
                tracks[url] = {"url": url, "title": TITLES[index], "duration": 180 + index * 17,
                    "days": {(today - dt.timedelta(days=index*8)).isoformat(): 15-index,
                             today.isoformat(): 5-index}}
            self.popularity_store.cache[guild.id] = {"version": 1, "tracks": tracks}

        self.lyrics_client = FakeLyricsClient()
        from musicbot.web_dashboard_library import PlaylistStore, song
        self.playlist_store = PlaylistStore(Path(self.demo_temp.name) / "user_playlists")
        async def cleanup_demo(_app):
            self.demo_temp.cleanup()
        self.app.on_cleanup.append(cleanup_demo)
        for uid in (42, 43, 44, 45):
            value = self.playlist_store.fresh()
            value["playlists"].append({"id": "a"*24, "name": "示範歌單", "tracks": [song({"title": TITLES[0], "url": "https://example.test/track/0", "duration": 180})]})
            self.playlist_store.path(uid).parent.mkdir(parents=True, exist_ok=True)
            import json
            self.playlist_store.path(uid).write_text(json.dumps(value), encoding="utf-8")
        from musicbot.autoplaylist import AutoPlaylist
        bot.config.auto_playlist_dir = Path(self.demo_temp.name) / "playlists"
        bot.config.auto_playlist_dir.mkdir()
        apl_path = bot.config.auto_playlist_dir / "default.txt"
        apl_path.write_text("# Demo only\nhttps://example.test/track/0\nhttps://example.test/track/1\n", encoding="utf-8")
        apl = AutoPlaylist(apl_path, bot)
        apl.data = apl._read_playlist()
        apl._is_loaded = True
        for gid in bot.server_data:
            bot.server_data[gid] = NS(autoplaylist=apl)
        self.backup_root = Path(self.demo_temp.name) / "backups"
        from musicbot.permissions import Permissions
        bot._perms_file = Path(self.demo_temp.name) / "permissions.ini"
        bot._perms_file.write_text("[Owner (auto)]\nMaxPlaylistLength = 30\nMaxSearchItems = 5\n"
            "[Default]\nMaxSongs = 3\nMaxSongLength = 210\nAllowPlaylists = no\n"
            "MaxSearchItems = 5\nSummonNoVoice = yes\nBypassKaraokeMode = yes\nExtractors = __\n"
            "[No commands]\nUserList = 45\nCommandWhitelist = __demo_denied__\n", encoding="utf-8")
        bot.permissions = Permissions(bot._perms_file)
        bot.permissions.set_owner_id(bot.config.owner_id)
        bot.perms = bot.permissions.owner_group
        bot.member_perms = bot.permissions.default_group
        for members in bot.members.values():
            for member in members.values():
                member.roles = []

        bot.dashboard = self
        for guild in bot.guilds:
            for index in range(5, -1, -1):
                song = bot.song(index)
                song.author = bot.members[guild.id][42 if index % 2 == 0 else 43]
                song.channel = guild.system_channel
                self.record_play(guild, song, played_at=time.time() - (index + 1) * 180)
            self.record_play(guild, bot.players[guild.id].current_entry)
            for index, source in enumerate(("web", "discord_text", "discord_slash")):
                self.record_activity(guild, "Owner" if index == 0 else "一般成員",
                    "play", source, "點歌：" + TITLES[index], "成功",
                    timestamp=time.time() - 30 * (3-index))
        self.demo_queues = {gid: list(player.playlist.entries) for gid, player in bot.players.items()}
        self.demo_queue_mode = "live"
        self.demo_step = 0
        self.app.cleanup_ctx.append(self.demo_updates)
        self.app.router.add_post("/demo-login/{user}", self.fake_callback)

    async def index(self, request):
        # Demo-only switches; no production API or configuration is involved.
        mode = request.query.get("demo-queue")
        if mode in ("empty", "filled", "live"):
            self.demo_queue_mode = mode
            for gid, player in self.bot.players.items():
                player.playlist.entries = deque() if mode == "empty" else deque(self.demo_queues[gid])
        response = await super().index(request)
        controls = ('<div class="request-mode" aria-label="示範操作">'
                    '<a class="source-link" href="/?demo-queue=empty">示範空佇列</a>'
                    '<a class="source-link" href="/?demo-queue=filled">還原示範佇列</a>'
                    '<a class="source-link" href="/?demo-queue=filled&amp;demo-query=duplicate">重複單曲範例</a>'
                    '<a class="source-link" href="/?demo-queue=filled&amp;demo-query=batch">重複歌單範例</a>'
                    '<a class="source-link" href="/?demo-queue=live">自動更新示範</a></div>')
        query = {"duplicate": "https://example.test/track/1",
                 "batch": "https://example.test/playlist"}.get(request.query.get("demo-query"))
        if query:
            response.text = response.text.replace('id="query" type="text"', 'id="query" type="text" value="' + query + '"', 1)
        response.text = response.text.replace('<h2 id="request-heading">', controls + '<h2 id="request-heading">', 1)
        return response

    def demo_tick(self):
        """Deterministic local simulation, usable without starting its timer."""
        if self.demo_queue_mode != "live":
            return  # Keep manually selected scenarios stable until live is selected.
        self.demo_step += 1
        for guild in self.bot.guilds:
            player = self.bot.players[guild.id]
            if self.demo_step % 2:
                song = self.bot.song(self.demo_step, title=f"即時示範歌曲 {self.demo_step}")
                song.author, song.channel = self.bot.members[guild.id][43], guild.system_channel
                player.playlist.entries.append(song)
                self.note_queue_entry(guild, song)
                while len(player.playlist.entries) > 12:
                    player.playlist.entries.popleft()
                self.record_activity(guild, "一般成員", "play", "discord_slash",
                                     "點歌：" + song.title, "成功")
            else:
                title = getattr(player.current_entry, "title", "")
                player.skip()
                self.record_activity(guild, "Owner", "skip", "web", "跳過：" + title, "成功")
            # Keep the timing edge case visible even in a long-running demo.
            while len(player.playlist.entries) > 10:
                player.playlist.entries.popleft()
            if not any(not song.duration for song in player.playlist.entries):
                unknown = self.bot.song(20, title="示範直播（長度未知）", duration=0)
                unknown.author, unknown.channel = self.bot.members[guild.id][42], guild.system_channel
                player.playlist.entries.insert(max(0, len(player.playlist.entries)-1), unknown)
                self.note_queue_entry(guild, unknown)
            if not player.playlist.entries[-1].duration:
                following = self.bot.song(1)
                following.author, following.channel = self.bot.members[guild.id][42], guild.system_channel
                player.playlist.entries.append(following)
                self.note_queue_entry(guild, following)

    async def demo_updates(self, _app):
        async def run():
            while True:
                await asyncio.sleep(6)
                self.demo_tick()
        task = asyncio.create_task(run())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def fake_response(self, key):
        uid, name = FAKE_USERS[key]
        response = web.HTTPFound(location="/")
        self.set_cookie(response, self.session_cookie,
                        self.new_session({"id": str(uid), "name": name, "avatar": ""}), 3600)
        raise response

    async def auth_login(self, request):
        if not self.discord_auth:
            return await super().auth_login(request)
        if self.fake_login:
            return self.fake_response(self.fake_login)
        forms = "".join(
            f'<form method="post" action="/demo-login/{key}"><button class="primary">{name}</button></form>'
            for key, (_, name) in FAKE_USERS.items())
        return web.Response(content_type="text/html", text=
            '<!doctype html><html lang="zh-Hant-TW"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<link rel="stylesheet" href="/dashboard.css"><title>示範登入</title>'
            '<section class="login-screen"><div class="login-card"><h1>選擇假使用者</h1>'
            '<p>純離線示範，未連線 Discord。</p>' + forms + '</div></section></html>')

    async def fake_callback(self, request):
        key = request.match_info["user"]
        if not self.discord_auth or key not in FAKE_USERS:
            return web.Response(status=404)
        return self.fake_response(key)


async def cover(request):
    palettes = [("#b67557", "#352748"), ("#709b86", "#153e3a"), ("#7596b0", "#273d5c"),
                ("#a08cab", "#2d234b"), ("#d2ac67", "#514529")]
    a, b = palettes[int(request.match_info["index"]) % len(palettes)]
    # Locally served vector artwork; no remote fonts, images, scripts or CDN.
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="500" height="500" viewBox="0 0 500 500">
    <defs><linearGradient id="g" x2="1" y2="1"><stop stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient></defs>
    <rect width="500" height="500" fill="url(#g)"/><circle cx="320" cy="210" r="180" fill="#ffffff12"/>
    <path d="M0 340 Q140 210 300 345 T600 290V500H0Z" fill="#0003"/>
    <circle cx="250" cy="250" r="116" fill="#151515"/><circle cx="250" cy="250" r="90" fill="none" stroke="#ffffff12" stroke-width="2"/>
    <circle cx="250" cy="250" r="63" fill="none" stroke="#ffffff12"/><circle cx="250" cy="250" r="36" fill="{a}"/>
    <circle cx="250" cy="250" r="8" fill="#151515"/></svg>"""
    return web.Response(text=svg, content_type="image/svg+xml")


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--public-origin", default="http://127.0.0.1:18080")
    parser.add_argument("--auth-mode", choices=("owner", "discord"), default="discord")
    parser.add_argument("--fake-login", choices=tuple(FAKE_USERS),
                        help="Auto-select this fake user after clicking login; otherwise show picker.")
    args = parser.parse_args()
    config = DashboardConfig(True, args.host, args.port, auth_mode=args.auth_mode,
                             public_url=args.public_origin,
                             discord_client_id="1000", discord_client_secret="demo-not-a-credential",
                             session_hours=1)
    dashboard = DemoDashboard(DemoBot(args.public_origin), config, args.fake_login)
    dashboard.app.router.add_get("/demo-cover/{index:[0-4]}.svg", cover)
    await dashboard.start()
    print(f"DEMO ONLY: {args.host}:{args.port}; no Discord client, token or downloads.", flush=True)
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)
    try:
        await stopped.wait()
    finally:
        await dashboard.close()


if __name__ == "__main__":
    asyncio.run(main())
