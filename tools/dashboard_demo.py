"""Credential-free dashboard demo. Never creates a Discord client or downloads media."""
from __future__ import annotations

import argparse
import asyncio
import signal
import time
from collections import deque
from types import SimpleNamespace as NS

from aiohttp import web

from musicbot.downloader import YtdlpResponseDict
from musicbot.web_dashboard import Dashboard, DashboardConfig


TITLES = ["夜色慢行", "窗邊的午後", "島嶼來信", "凌晨兩點的海", "微風練習曲"]


class DemoPlaylist:
    def __init__(self, songs):
        self.entries = deque(songs)

    def count_for_user(self, _owner):
        return len(self.entries)

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
                         default_search_service="ytsearch", spotify_enabled=False)
        self.perms = NS(max_songs=0, max_song_length=600, max_search_items=5,
                        allow_playlists=True, max_playlist_length=30,
                        bypass_karaoke_mode=True, summonplay=True, ignore_non_voice=set(),
                        can_use_command=lambda _: True, can_use_extractor=lambda _: None)
        self.permissions = NS(for_user=lambda _: self.perms)
        self.guilds, self.players, self.server_data = [], {}, {}
        self.init_ok, self.logout_called = True, False
        self.downloader = NS(extract_info=self.extract,
                             get_url_or_none=lambda q: q if q.startswith(("http://", "https://")) else None)
        for gid, name in ((1, "深夜音樂室"), (2, "午後咖啡館")):
            guild = NS(id=gid, name=name, unavailable=False, me=NS(voice=None))
            owner = NS(id=42, voice=None)
            channel = NS(id=gid * 10, guild=guild, typing=self.noop,
                         permissions_for=lambda _: NS(view_channel=True, send_messages=True))
            owner.voice = NS(channel=channel)
            guild.get_member = lambda uid, member=owner: member if uid == 42 else None
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
                tick=time.monotonic())

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

    async def _do_playlist_checks(self, _player, _owner, _info):
        return True

    async def extract(self, query, **kwargs):
        assert kwargs == {"download": False, "process": True}
        await asyncio.sleep(.15)
        def info(index):
            song = self.song(index)
            return {"__input_subject": query, "_type": "video", "title": song.title,
                    "webpage_url": song.url, "duration": song.duration,
                    "thumbnail": song.thumbnail_url, "extractor": "demo", "id": str(index)}
        if query.startswith("ytsearch"):
            data = {"__input_subject": query, "title": "搜尋結果", "extractor": "demo:search",
                    "entries": [info(i) for i in range(5)]}
        elif "playlist" in query:
            data = {"__input_subject": query, "title": "週末慢慢聽", "extractor": "demo:playlist",
                    "playlist_count": 5, "entries": [info(i) for i in range(5)]}
        else:
            try:
                index = int(query.rsplit("/", 1)[-1])
            except ValueError:
                index = 0
            data = info(index % 5)
        return YtdlpResponseDict(data)

    async def cmd_play(self, *, player, song_url, **_kwargs):
        # Fake boundary only: the real Dashboard calls the same cmd_play entry point.
        data = await self.extract(song_url, download=False, process=True)
        for info in (data.get_entries_objects() if data.has_entries else [data]):
            player.playlist.entries.append(NS(
                title=info.title, url=info.webpage_url,
                thumbnail_url=info.thumbnail_url, duration=info.duration))

    async def cmd_pause(self, _ssd, player):
        player.is_playing, player.is_paused = False, True

    async def cmd_resume(self, _ssd, player):
        player.is_playing, player.is_paused = True, False

    async def cmd_skip(self, *, player, **_kwargs):
        player.current_entry = player.playlist.entries.popleft() if player.playlist.entries else None
        player.progress = 0

    async def cmd_volume(self, _ssd, player, volume):
        player.volume = int(volume) / 100

    async def cmd_repeat(self, _ssd, player, mode):
        if mode == "all":
            player.loopqueue = not player.loopqueue
            player.repeatsong = False
        else:
            player.repeatsong = mode == "on"

    async def cmd_remove(self, *, player, position, **_kwargs):
        player.playlist.delete_entry_at_index(int(position) - 1)


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
    args = parser.parse_args()
    dashboard = Dashboard(DemoBot(args.public_origin), DashboardConfig(True, args.host, args.port))
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
