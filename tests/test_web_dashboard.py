"""Offline dashboard tests: unittest + aiohttp, no Discord login or credentials."""
import asyncio
import builtins
import datetime
import tempfile
import unittest
from collections import defaultdict, deque
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

# Bot normally installs gettext during startup; tests use deterministic text.
builtins._D = lambda text, _ssd: text
from musicbot.bot import MusicBot
from musicbot.constructs import ErrorResponse
from musicbot.downloader import YtdlpResponseDict
from musicbot.exceptions import PermissionsError
from musicbot.playlist import Playlist
from musicbot.web_dashboard import Dashboard, DashboardConfig, start_dashboard

HEADERS = {"X-MusicBot-Dashboard": "1", "X-Dashboard-Language": "zh-TW"}
BASE = "/api/guilds/1/"


def entry(title="Track", duration=180, author=None, channel=None):
    return NS(title=title, url="https://soundcloud.com/example/" + title,
              thumbnail_url="https://soundcloud.com/example/cover.jpg", duration=duration,
              author=author, channel=channel, is_downloading=False, is_downloaded=True)


class FakePlaylist(Playlist):
    def __init__(self, bot):
        self.bot = bot
        self.entries = deque()

    async def add_entry_from_info(self, info, *, author, channel, head=False, **kwargs):
        item = entry(info.title, info.duration, author, channel)
        if head:
            self.entries.appendleft(item)
        else:
            self.entries.append(item)
        return item, len(self.entries)

    async def estimate_time_until(self, position, player):
        return datetime.timedelta(seconds=0)


class FakePlayer:
    def __init__(self, bot, channel):
        self.playlist = FakePlaylist(bot)
        self.current_entry = entry("Current", author=bot.owner, channel=channel)
        self.voice_client = NS(channel=channel)
        self.is_playing, self.is_paused, self.is_stopped = True, False, False
        self.progress, self.volume = 35.5, 0.15
        self.repeatsong = self.loopqueue = self.karaoke_mode = False

    def pause(self):
        self.is_playing, self.is_paused = False, True

    def resume(self):
        self.is_playing, self.is_paused = True, False

    def play(self):
        self.is_playing, self.is_paused, self.is_stopped = True, False, False

    def skip(self):
        self.current_entry = None


class FakeBot:
    # Real command logic and playlist implementation, fake external boundaries.
    cmd_play = MusicBot.cmd_play
    _cmd_play = MusicBot._cmd_play
    _do_playlist_checks = MusicBot._do_playlist_checks
    _do_cmd_unpause_check = MusicBot._do_cmd_unpause_check
    _check_ignore_non_voice = MusicBot._check_ignore_non_voice
    cmd_pause = MusicBot.cmd_pause
    cmd_resume = MusicBot.cmd_resume
    cmd_skip = MusicBot.cmd_skip
    cmd_volume = MusicBot.cmd_volume
    cmd_repeat = MusicBot.cmd_repeat
    cmd_remove = MusicBot.cmd_remove
    _start_web_dashboard = MusicBot._start_web_dashboard
    _stop_web_dashboard = MusicBot._stop_web_dashboard

    def __init__(self):
        self.config = NS(owner_id=42, bound_channels=set(), unbound_servers=False,
                         auto_unpause_on_play=False, enable_local_media=False,
                         default_search_service="ytsearch", spotify_enabled=False,
                         allow_author_skip=True, legacy_skip=True, use_opus_audio=False,
                         enable_queue_history_global=False, enable_queue_history_guilds=False,
                         song_blocklist_enabled=False)
        self.perms = NS(max_songs=0, max_song_length=0, max_playlist_length=0,
                        allow_playlists=True, bypass_karaoke_mode=True, summonplay=True,
                        remove=True, instaskip=True, skip_looped=True, ignore_non_voice=set(),
                        can_use_command=lambda *args: True,
                        can_use_extractor=lambda *args: True)
        self.owner = NS(id=42, name="Owner", voice=None)
        self.guild = NS(id=1, name="Test Guild", unavailable=False, me=NS(voice=None))
        self.channel = NS(id=10, name="Music", guild=self.guild, typing=AsyncMock(),
                          permissions_for=lambda member: NS(view_channel=True, send_messages=True))
        self.owner.voice = NS(channel=self.channel)
        self.guild.get_member = lambda uid: self.owner if uid == 42 else None
        self.guild.get_channel = lambda cid: self.channel if cid == 10 else None
        self.guild.system_channel = self.channel
        self.guild.channels = self.guild.text_channels = [self.channel]
        self.guilds = [self.guild]
        self.player = FakePlayer(self, self.channel)
        self.player.playlist.entries.extend([
            entry("One", author=self.owner), entry("Two", author=self.owner),
            entry("Three", author=self.owner)])
        self.permissions = NS(for_user=lambda owner: self.perms)
        self.server_data = {1: None}
        self.aiolocks = defaultdict(asyncio.Lock)
        self.info = {"__input_subject": "test", "title": "Added",
                     "webpage_url": "https://soundcloud.com/example/added", "duration": 120,
                     "extractor": "youtube", "id": "added"}
        self.extractions = []
        self.downloader = NS(extract_info=self.extract,
                             get_url_or_none=lambda value: value if value.startswith("https://") else None)
        self._cmd_play_compound_link = AsyncMock()
        self.serialize_queue = AsyncMock()
        self.get_player = AsyncMock(side_effect=lambda *args, **kw: self.player)
        self.get_player_in = lambda guild: self.player
        self.get_guild = lambda gid: self.guild if gid == 1 else None
        self.is_ready = lambda: True
        self.init_ok, self.logout_called = True, False
        self._web_dashboard = None
        self._config_file = Path("config/options.ini")
        self.blocked = set()

    async def extract(self, query, **kwargs):
        self.extractions.append((query, kwargs))
        return YtdlpResponseDict(self.info)

    def _do_song_blocklist_check(self, value):
        if value in self.blocked:
            raise PermissionsError("Blocked")


class DashboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = FakeBot()
        self.dashboard = Dashboard(self.bot, DashboardConfig())
        self.client = TestClient(TestServer(self.dashboard.app), headers={"Accept-Language":"zh-TW"})
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def call(self, path, data=None, method="POST", status=200, headers=None):
        response = await self.client.request(method, path, json=data,
                                             headers=HEADERS if headers is None else headers)
        body = await response.json()
        self.assertEqual(response.status, status, body)
        return body

    async def rev(self):
        return (await self.call(BASE + "state", method="GET"))["revision"]

    async def test_static_page_and_assets(self):
        for path, content_type in (("/", "text/html"), ("/dashboard.css", "text/css"),
                                   ("/dashboard.js", "text/javascript")):
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status, 200)
                self.assertIn(content_type, response.headers["Content-Type"])
                self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
                self.assertEqual(response.headers["Cache-Control"], "no-store")
        page = await (await self.client.get("/")).text()
        self.assertIn('lang="en"', page)
        self.assertIn('data-i18n="m0223"', page)
        self.assertNotIn("cdn", page.lower())

    async def test_guilds_and_state(self):
        body = await self.call("/api/guilds", method="GET")
        self.assertEqual(body["guilds"], [{"id": "1", "name": "Test Guild"}])
        body = await self.call(BASE + "state", method="GET")
        self.assertEqual(body["current"]["title"], "Current")
        self.assertEqual(body["progress"], 35.5)
        self.assertEqual(body["volume"], 15)
        self.assertEqual([song["position"] for song in body["queue"]], [1, 2, 3])
        self.bot.get_player.assert_not_awaited()

    async def test_disconnected_state_does_not_summon(self):
        self.bot.get_player_in = lambda guild: None
        body = await self.call(BASE + "state", method="GET")
        self.assertEqual(body["status"], "disconnected")
        self.assertEqual(body["queue"], [])
        self.bot.get_player.assert_not_awaited()

    async def test_guild_switch_and_no_cross_guild_player(self):
        guild2 = NS(id=2, name="Second", unavailable=False,
                    get_member=lambda uid: self.bot.owner)
        self.bot.guilds.append(guild2)
        self.bot.get_guild = lambda gid: {1: self.bot.guild, 2: guild2}.get(gid)
        self.bot.get_player_in = lambda g: self.bot.player if g.id == 1 else None
        self.assertEqual(len((await self.call("/api/guilds", method="GET"))["guilds"]), 2)
        result = await self.call("/api/guilds/2/state", method="GET")
        self.assertEqual(result["guild_id"], "2")
        self.assertIsNone(result["current"])

    async def test_play_url_real_command_and_owner(self):
        await self.call(BASE + "play", {"query": "https://soundcloud.com/example/song"})
        self.assertEqual(self.bot.extractions[0], ("https://soundcloud.com/example/song",
                                                  {"download": False, "process": True}))
        self.assertIs(self.bot.player.playlist.entries[-1].author, self.bot.owner)
        self.bot.get_player.assert_awaited_with(self.bot.channel, create=True)

    async def test_play_keyword_uses_existing_search(self):
        await self.call(BASE + "play", {"query": "test song"})
        self.assertEqual(self.bot.extractions[0][0], "ytsearch5:test song")

    async def test_play_starts_stopped_queue(self):
        self.bot.player.playlist.entries.clear()
        self.bot.player.is_playing, self.bot.player.is_stopped = False, True
        await self.call(BASE + "play", {"query": "song"})
        self.assertTrue(self.bot.player.is_playing)

    async def test_pause_and_resume_real_commands(self):
        await self.call(BASE + "pause", {})
        self.assertTrue(self.bot.player.is_paused)
        self.bot.get_player.assert_awaited_with(self.bot.channel, create=False)
        await self.call(BASE + "resume", {})
        self.assertTrue(self.bot.player.is_playing)

    async def test_resume_error_response_is_failure(self):
        await self.call(BASE + "resume", {}, status=409)

    async def test_skip_real_command(self):
        self.bot.player.repeatsong = True
        await self.call(BASE + "skip", {})
        self.assertIsNone(self.bot.player.current_entry)
        self.assertFalse(self.bot.player.repeatsong)

    async def test_volume_real_command(self):
        await self.call(BASE + "volume", {"volume": 73})
        self.assertEqual(self.bot.player.volume, .73)

    async def test_repeat_modes_and_idempotence(self):
        for mode, song, queue in (("song", True, False), ("song", True, False),
                                  ("all", False, True), ("off", False, False)):
            await self.call(BASE + "repeat", {"mode": mode})
            self.assertEqual((self.bot.player.repeatsong, self.bot.player.loopqueue),
                             (song, queue))
        self.bot.player.repeatsong = self.bot.player.loopqueue = True
        await self.call(BASE + "repeat", {"mode": "off"})
        self.assertFalse(self.bot.player.repeatsong or self.bot.player.loopqueue)

    async def test_repeat_empty_player(self):
        self.bot.player.current_entry = None
        await self.call(BASE + "repeat", {"mode": "song"}, status=409)

    async def test_remove_real_command_and_persist(self):
        await self.call(BASE + "queue/2", {"revision": await self.rev()}, method="DELETE")
        self.assertEqual([e.title for e in self.bot.player.playlist.entries], ["One", "Three"])
        self.bot.serialize_queue.assert_awaited_once_with(self.bot.guild)

    async def test_move_uses_real_playlist_and_persist(self):
        await self.call(BASE + "queue/move", {"from": 1, "to": 3, "revision": await self.rev()})
        self.assertEqual([e.title for e in self.bot.player.playlist.entries], ["Two", "Three", "One"])
        self.bot.serialize_queue.assert_awaited_once_with(self.bot.guild)

    async def test_shuffle_preserves_entries_and_persists(self):
        original = {id(e) for e in self.bot.player.playlist.entries}
        await self.call(BASE + "queue/shuffle", {"revision": await self.rev()})
        self.assertEqual({id(e) for e in self.bot.player.playlist.entries}, original)
        self.bot.serialize_queue.assert_awaited_once_with(self.bot.guild)

    async def test_stale_and_missing_revisions_on_all_queue_mutations(self):
        for path, method, extra in (("queue/1", "DELETE", {}),
                                     ("queue/move", "POST", {"from": 1, "to": 2}),
                                     ("queue/shuffle", "POST", {})):
            for rev in ("stale", None):
                with self.subTest(path=path, revision=rev):
                    await self.call(BASE + path, dict(extra, revision=rev), method, status=409)
        self.assertEqual(len(self.bot.player.playlist.entries), 3)

    async def test_playback_transition_invalidates_queue_revision(self):
        old = await self.rev()
        self.bot.player.current_entry = entry("Next")
        await self.call(BASE + "queue/1", {"revision": old}, "DELETE", status=409)

    async def test_invalid_payloads_and_positions(self):
        for path, data in (("play", {"query": ""}), ("play", {"query": 2}),
                            ("play", {"query": "a" * 2001}), ("volume", {"volume": 0}),
                            ("volume", {"volume": 101}), ("volume", {"volume": True}),
                            ("volume", {"volume": "10"}), ("repeat", {"mode": "invalid"}),
                            ("pause", [])):
            with self.subTest(path=path, data=data):
                await self.call(BASE + path, data, status=400)
        for path, data, method in (("queue/0", {}, "DELETE"), ("queue/no", {}, "DELETE"),
                                    ("queue/99", {}, "DELETE"),
                                    ("queue/move", {"from": 0, "to": 2}, "POST"),
                                    ("queue/move", {"from": 1, "to": 99}, "POST")):
            await self.call(BASE + path, dict(data, revision=await self.rev()), method, status=400)
        response = await self.client.post(BASE + "pause", data="{", headers=HEADERS)
        self.assertEqual(response.status, 400)
        response = await self.client.post(BASE + "play", data="x" * 17000, headers=HEADERS)
        self.assertEqual(response.status, 413)

    async def test_unknown_guild_route_and_method(self):
        await self.call("/api/guilds/no/state", method="GET", status=400)
        await self.call("/api/guilds/999/state", method="GET", status=404)
        await self.call("/api/absent", method="GET", status=404)
        await self.call(BASE + "pause", method="GET", status=405)

    async def test_not_ready_and_shutting_down(self):
        self.bot.init_ok = False
        await self.call("/api/guilds", method="GET", status=503)
        self.bot.init_ok, self.bot.logout_called = True, True
        await self.call(BASE + "pause", {}, status=503)

    async def test_owner_membership_required(self):
        self.bot.guild.get_member = lambda uid: None
        await self.call(BASE + "state", method="GET", status=403)
        self.assertEqual((await self.call("/api/guilds", method="GET"))["guilds"], [])

    async def test_requires_owner_voice(self):
        self.bot.owner.voice = None
        await self.call(BASE + "pause", {}, status=409)
        self.bot.get_player.assert_not_awaited()

    async def test_ignore_non_voice_permission_is_preserved(self):
        self.bot.perms.ignore_non_voice = {"pause"}
        self.bot.guild.me.voice = NS(channel=object())
        await self.call(BASE + "pause", {}, status=403)
        self.assertTrue(self.bot.player.is_playing)

    async def test_bound_channels_and_channel_permissions(self):
        self.bot.config.bound_channels = {999}
        await self.call(BASE + "pause", {}, status=403)
        self.bot.config.unbound_servers = True
        await self.call(BASE + "pause", {})
        self.bot.channel.permissions_for = lambda member: NS(view_channel=False, send_messages=False)
        await self.call(BASE + "resume", {}, status=403)

    async def test_owner_permissions_song_count(self):
        self.bot.perms.max_songs = 3
        await self.call(BASE + "play", {"query": "song"}, status=403)
        self.assertEqual(self.bot.extractions, [])

    async def test_owner_permissions_song_length(self):
        self.bot.perms.max_song_length = 100
        await self.call(BASE + "play", {"query": "song"}, status=403)
        self.assertEqual(len(self.bot.player.playlist.entries), 3)

    async def test_owner_permissions_playlist_limits(self):
        self.bot.info = dict(self.bot.info, playlist_count=2,
                             entries=[dict(self.bot.info), dict(self.bot.info)])
        for permission, value in (("allow_playlists", False), ("max_playlist_length", 1),
                                   ("max_songs", 4)):
            with self.subTest(permission=permission):
                setattr(self.bot.perms, permission, value)
                await self.call(BASE + "play", {"query": "https://soundcloud.com/example/list"}, status=403)
                setattr(self.bot.perms, permission, True if permission == "allow_playlists" else 0)
        self.assertEqual(len(self.bot.player.playlist.entries), 3)

    async def test_playlist_real_import_filters_long_songs(self):
        short = dict(self.bot.info, title="Short", duration=60,
                     webpage_url="https://soundcloud.com/example/short")
        long = dict(self.bot.info, title="Long", duration=600)
        self.bot.info = dict(self.bot.info, entries=[short, long], playlist_count=2)
        self.bot.perms.max_song_length = 100
        original = self.bot.downloader.extract_info
        async def extract(query, **kwargs):
            if query == short["webpage_url"]:
                return YtdlpResponseDict(short)
            return await original(query, **kwargs)
        self.bot.downloader.extract_info = extract
        await self.call(BASE + "play", {"query": "https://soundcloud.com/example/list"})
        self.assertEqual([e.title for e in self.bot.player.playlist.entries],
                         ["One", "Two", "Three", "Short"])

    async def test_extractor_and_blocklist_restrictions(self):
        self.bot.blocked.add("ytsearch5:blocked")
        await self.call(BASE + "play", {"query": "blocked"}, status=403)
        def deny(*args):
            raise PermissionsError("Extractor denied")
        self.bot.perms.can_use_extractor = deny
        await self.call(BASE + "play", {"query": "song"}, status=403)

    async def test_remove_permissions_are_not_bypassed(self):
        self.bot.perms.remove = False
        self.bot.player.playlist.entries[0].author = NS(id=99)
        await self.call(BASE + "queue/1", {"revision": await self.rev()}, "DELETE", status=403)
        self.assertEqual(len(self.bot.player.playlist.entries), 3)

    async def test_no_summon_without_permission(self):
        self.bot.perms.summonplay = False
        await self.call(BASE + "play", {"query": "song"})
        self.bot.get_player.assert_awaited_with(self.bot.channel, create=False)

    async def test_secret_custom_header_and_origin(self):
        self.dashboard.config = DashboardConfig(shared_secret="unit-test-only")
        await self.call("/api/guilds", method="GET", status=403, headers={})
        await self.call("/api/guilds", method="GET", status=401)
        await self.call("/api/guilds", method="GET", status=401,
                        headers=dict(HEADERS, Authorization="Bearer wrong"))
        good = dict(HEADERS, Authorization="Bearer unit-test-only")
        await self.call("/api/guilds", method="GET", headers=good)
        await self.call("/api/guilds", method="GET", status=403,
                        headers=dict(good, Origin="https://other.test"))
        same = str(self.client.make_url("/")).rstrip("/")
        await self.call("/api/guilds", method="GET", headers=dict(good, Origin=same))
        # Secrets in URLs are deliberately never accepted.
        await self.call("/api/guilds?key=unit-test-only", method="GET", status=401)
        self.assertNotIn("unit-test-only", repr(self.dashboard.config))

    async def test_csrf_protection_without_secret(self):
        await self.call("/api/guilds", method="GET", headers={}, status=403)
        await self.call(BASE + "pause", {}, headers=dict(HEADERS, Origin="null"), status=403)

    async def test_request_exceptions_are_logged_and_bot_continues(self):
        self.bot.cmd_pause = AsyncMock(side_effect=RuntimeError("injected"))
        with self.assertLogs("musicbot.web_dashboard", level="ERROR") as logs:
            body = await self.call(BASE + "pause", {}, status=500)
        self.assertNotIn("injected", body["error"])
        self.assertTrue(logs.output)
        await self.call(BASE + "state", method="GET")
        self.assertTrue(self.bot.player.is_playing)

    async def test_state_and_serialization_errors_are_contained(self):
        self.bot.get_player_in = lambda guild: 1 / 0
        with self.assertLogs("musicbot.web_dashboard", level="ERROR"):
            await self.call(BASE + "state", method="GET", status=500)
        self.bot.get_player_in = lambda guild: self.bot.player
        self.bot.serialize_queue.side_effect = OSError("disk unavailable")
        with self.assertLogs("musicbot.web_dashboard", level="ERROR"):
            await self.call(BASE + "queue/shuffle", {"revision": await self.rev()}, status=500)
        await self.call(BASE + "state", method="GET")


    async def test_error_translation_failure_is_also_contained(self):
        self.bot.cmd_pause = AsyncMock(side_effect=PermissionsError("Denied"))
        with patch("musicbot.web_dashboard.denial_text", side_effect=RuntimeError("translation")), self.assertLogs(
                "musicbot.web_dashboard", level="ERROR"):
            await self.call(BASE + "pause", {}, status=500)
        await self.call(BASE + "state", method="GET")

    async def test_concurrent_queue_mutations_reject_loser(self):
        old = await self.rev()
        results = await asyncio.gather(*[
            self.client.delete(BASE + "queue/1", json={"revision": old}, headers=HEADERS)
            for _ in range(2)])
        self.assertEqual(sorted(r.status for r in results), [200, 409])
        self.assertEqual(len(self.bot.player.playlist.entries), 2)


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_and_disabled_never_start_or_create_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "web_dashboard.ini"
            with patch.object(Dashboard, "start", new_callable=AsyncMock) as start:
                self.assertIsNone(await start_dashboard(FakeBot(), path))
                self.assertFalse(path.exists())
                path.write_text("[WebDashboard]\nEnabled=no\nPort=invalid\n")
                self.assertIsNone(await start_dashboard(FakeBot(), path))
                start.assert_not_awaited()

    async def test_defaults_and_literal_secret(self):
        self.assertEqual(DashboardConfig(), DashboardConfig(False, "127.0.0.1", 8080, ""))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "web_dashboard.ini"
            path.write_text("[WebDashboard]\nEnabled=yes\nSharedSecret=literal%secret\n")
            config = DashboardConfig.load(path)
            self.assertEqual(config.shared_secret, "literal%secret")

    async def test_invalid_configs_fail_closed_without_secret_in_log(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "web_dashboard.ini"
            for text in ("[WebDashboard]\nEnabled=maybe", "[WebDashboard]\nEnabled=yes\nPort=0",
                          "[WebDashboard]\nEnabled=yes\nPort=70000",
                          "[WebDashboard]\nEnabled=yes\nHost=\n",
                          "[WebDashboard]\nEnabled=yes\nSECRET_LINE_DO_NOT_LOG"):
                path.write_text(text)
                with self.assertLogs("musicbot.web_dashboard", level="ERROR") as logs:
                    self.assertIsNone(await start_dashboard(FakeBot(), path))
                self.assertNotIn("SECRET_LINE_DO_NOT_LOG", str(logs.output))

    async def test_start_failure_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "web_dashboard.ini"
            path.write_text("[WebDashboard]\nEnabled=yes\n")
            with patch.object(Dashboard, "start", new_callable=AsyncMock,
                              side_effect=OSError("bind failed")), patch.object(
                    Dashboard, "close", new_callable=AsyncMock) as close:
                with self.assertLogs("musicbot.web_dashboard", level="ERROR"):
                    self.assertIsNone(await start_dashboard(FakeBot(), path))
                close.assert_awaited_once()

    async def test_real_start_stop_releases_listener(self):
        # Port zero is only used directly by the test, not a valid user config.
        dashboard = Dashboard(FakeBot(), DashboardConfig(True, "127.0.0.1", 0))
        await dashboard.start()
        port = dashboard.site._server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()
        await writer.wait_closed()
        await dashboard.close()
        await dashboard.close()
        with self.assertRaises(OSError):
            await asyncio.open_connection("127.0.0.1", port)

    async def test_real_bind_conflict_does_not_escape(self):
        first = Dashboard(FakeBot(), DashboardConfig(True, "127.0.0.1", 0))
        await first.start()
        try:
            port = first.site._server.sockets[0].getsockname()[1]
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "web_dashboard.ini"
                path.write_text(f"[WebDashboard]\nEnabled=yes\nPort={port}\n")
                with self.assertLogs("musicbot.web_dashboard", level="ERROR"):
                    self.assertIsNone(await start_dashboard(FakeBot(), path))
        finally:
            await first.close()

    async def test_bot_start_stop_hooks_and_failure_isolation(self):
        bot = FakeBot()
        close = AsyncMock()
        with patch("musicbot.web_dashboard.start_dashboard", new_callable=AsyncMock,
                   return_value=NS(close=close)) as start:
            await bot._start_web_dashboard()
            start.assert_awaited_once()
            self.assertEqual(start.call_args.args[1].name, "web_dashboard.ini")
            await bot._stop_web_dashboard()
            await bot._stop_web_dashboard()
            close.assert_awaited_once()
        bot._web_dashboard = NS(close=AsyncMock(side_effect=RuntimeError("cleanup")))
        with self.assertLogs("musicbot.bot", level="ERROR"):
            await bot._stop_web_dashboard()
        self.assertIsNone(bot._web_dashboard)

    async def test_bot_start_hook_contains_imported_helper_failure(self):
        bot = FakeBot()
        with patch("musicbot.web_dashboard.start_dashboard", new_callable=AsyncMock,
                   side_effect=RuntimeError("initialization")), self.assertLogs(
                       "musicbot.bot", level="ERROR"):
            await bot._start_web_dashboard()
        self.assertIsNone(bot._web_dashboard)

    async def test_bot_ready_starts_once_and_close_calls_super(self):
        bot = FakeBot()
        bot.on_ready_count = 0
        bot.init_ok = False
        bot._on_ready_once = AsyncMock()
        bot._on_ready_always = AsyncMock()
        bot._start_web_dashboard = AsyncMock()
        await MusicBot.on_ready(bot)
        await MusicBot.on_ready(bot)
        bot._start_web_dashboard.assert_awaited_once()
        self.assertTrue(bot.init_ok)
        # Real class instance with only network close replaced; no __init__/login.
        real = object.__new__(MusicBot)
        real._web_dashboard = NS(close=AsyncMock())
        dashboard_close = real._web_dashboard.close
        with patch("discord.ext.commands.Bot.close", new_callable=AsyncMock) as parent:
            await MusicBot.close(real)
            dashboard_close.assert_awaited_once()
            parent.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
