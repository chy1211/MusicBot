"""Credential-free dashboard demo. Never creates a Discord client or downloads media."""
from __future__ import annotations

import argparse
import builtins
import asyncio
import signal
import time
from collections import deque
from types import SimpleNamespace as NS

from aiohttp import web

from musicbot.downloader import YtdlpResponseDict
from musicbot.bot import MusicBot
from musicbot.constructs import SkipState
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
            channel.members = [members[uid] for uid in (42, 43, 45)]
            guild.me.voice = NS(channel=channel)
            guild.get_member = members.get
            guild.get_channel = lambda cid, ch=channel: ch if cid == ch.id else None
            guild.system_channel = channel
            guild.channels = guild.text_channels = [channel]
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
            player.current_entry.author, player.current_entry.channel = owner, channel
            for index, song in enumerate(player.playlist.entries):
                song.author, song.channel = members[43] if index == 1 else owner, channel
                if index == 3:
                    song.author, song.channel = None, None
            def skip(p=player):
                p.current_entry = p.playlist.entries.popleft() if p.playlist.entries else None
                p.progress = 0
                p.skip_state.reset()
            player.skip = skip

    def song(self, index, title=None):
        return NS(title=title or TITLES[index % len(TITLES)],
                  url=f"https://example.test/track/{index}",
                  thumbnail_url=f"{self.origin}/demo-cover/{index % 5}.svg",
                  duration=180 + index * 17)

    async def noop(self, *_args, **_kwargs):
        return None

    is_ready = lambda self: True
    get_guild = lambda self, gid: next((g for g in self.guilds if g.id == gid), None)
    serialize_queue = noop

    def get_player_in(self, guild):
        player = self.players[guild.id]
        now = time.monotonic()
        if player.is_playing and player.current_entry:
            player.progress = min(player.current_entry.duration, player.progress + now - player.tick)
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

    async def cmd_play(self, *, player, song_url, author, channel, **_kwargs):
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
            player.playlist.entries.append(NS(
                title=info.title, url=info.webpage_url, author=author, channel=channel,
                thumbnail_url=info.thumbnail_url, duration=info.duration))
            if validator is not None:
                validator.enqueued = True

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


class DemoDashboard(Dashboard):
    """Fake login exists only in this explicit demo executable, never production."""
    def __init__(self, bot, config, fake_login=None):
        self.fake_login = fake_login
        super().__init__(bot, config)
        self.app.router.add_post("/demo-login/{user}", self.fake_callback)

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
