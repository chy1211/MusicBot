"""Round-six offline API, SSE, native-hook and notification regressions."""
import asyncio
import builtins
import inspect
import json
import time
import unittest
from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
import discord
from test_web_dashboard import BASE, HEADERS, FakeBot, entry
import test_web_dashboard_discord as discord_fixtures
from musicbot.bot import MusicBot
from musicbot.constructs import ErrorResponse
from musicbot.slash_commands import SlashCommands
from musicbot.web_dashboard import Dashboard, DashboardConfig
from musicbot.web_dashboard_activity import ACTIVE, capture, finish, native_result, slash_activity
from tools.dashboard_demo import DemoBot, DemoDashboard

class Round6Tests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = discord_fixtures.DiscordTests.asyncSetUp
    asyncTearDown = discord_fixtures.DiscordTests.asyncTearDown
    login_as = discord_fixtures.DiscordTests.login_as
    call = discord_fixtures.DiscordTests.call
    rev = discord_fixtures.DiscordTests.rev
    provider_token = discord_fixtures.DiscordTests.provider_token
    provider_me = discord_fixtures.DiscordTests.provider_me

    async def stream(self, **kwargs):
        self.dashboard.EVENT_INTERVAL = .01
        self.dashboard.HEARTBEAT_INTERVAL = .08
        response = await self.client.get(BASE+"events", **kwargs)
        self.assertEqual(response.status, 200)
        return response

    async def frame(self, response):
        async def read():
            lines = []
            while line := await response.content.readline():
                if line == b"\n":
                    return b"".join(lines).decode()
                lines.append(line)
            return b"".join(lines).decode()
        return await asyncio.wait_for(read(), 1)

    def channel(self, cid, allowed=True, bot_allowed=True):
        return NS(id=cid, name=f"Channel {cid}", guild=self.bot.guild, typing=AsyncMock(),
                  permissions_for=lambda member: NS(view_channel=allowed if member is self.bot.member else bot_allowed,
                                                     send_messages=allowed if member is self.bot.member else bot_allowed))

    async def test_mine_is_per_viewer_without_requester_ids(self):
        self.bot.player.playlist.entries[1].author = self.bot.member
        data = await self.call(BASE+"state", method="GET")
        self.assertEqual([s["mine"] for s in data["queue"]], [False, True, False])
        self.assertEqual(set(data["queue"][0]["requester"]), {"name", "avatar"})
        self.login_as(42)
        data = await self.call(BASE+"state", method="GET")
        self.assertEqual([s["mine"] for s in data["queue"]], [True, False, True])

    async def test_mine_handles_meta_and_missing_authors(self):
        songs = self.bot.player.playlist.entries
        songs[0].author = None
        songs[0].meta = {"member": self.bot.member}
        songs[1].author = None
        data = await self.call(BASE+"state", method="GET")
        self.assertTrue(data["queue"][0]["mine"])
        self.assertFalse(data["queue"][1]["mine"])

    async def test_listeners_exclude_self_and_bots_no_ids(self):
        self.bot.user = NS(id=999)
        self.bot.channel.members += [NS(id=999, bot=False), NS(id=888, bot=True)]
        data = await self.call(BASE+"listeners", method="GET")
        self.assertTrue(data["connected"])
        self.assertEqual(len(data["members"]), 3)
        self.assertTrue(all(set(m) == {"name", "avatar"} for m in data["members"]))

    async def test_disconnected_listeners(self):
        self.bot.guild.me.voice = None
        self.bot.player.voice_client = None
        data = await self.call(BASE+"listeners", method="GET")
        self.assertEqual(data, {"connected": False, "channel": "", "members": []})

    async def test_all_new_reads_require_membership(self):
        self.bot.members.pop(43)
        for path in ("listeners", "activity", "events"):
            self.login_as(43)
            await self.call(BASE+path, method="GET", status=403)

    async def test_web_activity_success_rejection_no_keyword(self):
        await self.call(BASE+"play", {"query": "PRIVATE SEARCH WORDS"})
        await self.call(BASE+"volume", {"volume": 56})
        await self.call(BASE+"volume", {"volume": 999}, status=400)
        rows = (await self.call(BASE+"activity", method="GET"))["activity"]
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["source"] == "web" for row in rows))
        self.assertIn("56%", rows[1]["detail"])
        self.assertEqual(rows[0]["result"], "被拒或未完成")
        self.assertEqual(rows[-1]["result"], "成功")
        self.assertIn("Added", rows[-1]["detail"])
        self.assertNotIn("PRIVATE SEARCH WORDS", json.dumps(rows))
        self.assertTrue(all(set(r) == {"actor", "action", "source", "detail", "result", "time"} for r in rows))

    async def test_activity_cap_and_guild_isolation(self):
        for i in range(105):
            self.dashboard.record_activity(self.bot.guild, "Friend", "play", "web", str(i), "成功")
        self.dashboard.record_activity(NS(id=2), "Other", "pause", "web", "other guild", "成功")
        rows = (await self.call(BASE+"activity", method="GET"))["activity"]
        self.assertEqual(len(rows), 100)
        self.assertEqual(rows[0]["detail"], "104")
        self.assertNotIn("other guild", json.dumps(rows))

    async def test_vote_skip_names_track(self):
        await self.call(BASE+"skip", {})
        row = self.dashboard.activities[1][0]
        self.assertIn("投票跳過", row["detail"])
        self.assertIn("Current", row["detail"])

    async def test_remove_names_removed_song(self):
        self.bot.player.playlist.entries[1].author = self.bot.member
        await self.call(BASE+"queue/2", {"revision": await self.rev()}, method="DELETE")
        self.assertIn("Two", self.dashboard.activities[1][0]["detail"])

    async def test_web_recording_failure_preserves_operation(self):
        with patch.object(self.dashboard, "record_activity", side_effect=RuntimeError("fixture")):
            await self.call(BASE+"volume", {"volume": 61})
        self.assertEqual(self.bot.player.volume, .61)

    async def test_current_request_channel_precedes_system_and_voice(self):
        music = self.channel(101)
        self.bot.player.current_entry.channel = music
        self.assertIs(self.dashboard.channel_for(self.bot.guild, self.bot.member), music)
        await self.call(BASE+"volume", {"volume": 60})
        self.assertIs(self.bot.safe_send_message.await_args.args[0], music)

    async def test_latest_queued_channel_when_current_has_none(self):
        music = self.channel(101)
        self.bot.player.current_entry.channel = None
        self.bot.player.playlist.entries[-1].channel = music
        self.assertIs(self.dashboard.channel_for(self.bot.guild, self.bot.member), music)

    async def test_latest_insertion_survives_playnext_and_reordering(self):
        self.bot.player.current_entry.channel = None
        self.dashboard.snapshot(self.bot.guild, self.bot.member)
        newest = entry("Inserted", channel=self.channel(101))
        self.bot.player.playlist.entries.appendleft(newest)
        self.dashboard.note_queue_entry(self.bot.guild, newest)
        self.bot.player.playlist.entries.rotate(2)
        self.assertIs(self.dashboard.channel_for(self.bot.guild, self.bot.member), newest.channel)

    async def test_current_missing_permission_falls_to_latest(self):
        self.bot.player.current_entry.channel = self.channel(101, allowed=False)
        queued = self.channel(102)
        self.bot.player.playlist.entries[-1].channel = queued
        self.assertIs(self.dashboard.channel_for(self.bot.guild, self.bot.member), queued)

    async def test_bot_missing_permission_falls_back(self):
        self.bot.player.current_entry.channel = self.channel(101, bot_allowed=False)
        self.assertIs(self.dashboard.channel_for(self.bot.guild, self.bot.member), self.bot.channel)

    async def test_unbound_request_channel_falls_to_bound(self):
        music = self.channel(101)
        self.bot.guild.channels.append(music)
        self.bot.player.current_entry.channel = music
        self.bot.config.bound_channels = {10}
        self.assertIs(self.dashboard.channel_for(self.bot.guild, self.bot.member), self.bot.channel)

    async def test_bound_latest_queue_when_current_unbound(self):
        music = self.channel(101)
        self.bot.guild.channels.append(music)
        self.bot.config.bound_channels = {101}
        self.bot.player.playlist.entries[-1].channel = music
        self.assertIs(self.dashboard.channel_for(self.bot.guild, self.bot.member), music)

    async def test_system_and_other_text_precede_voice(self):
        self.bot.player.current_entry.channel = None
        system, text = self.channel(101), self.channel(102)
        self.bot.guild.system_channel, self.bot.guild.text_channels = system, [text]
        self.assertIs(self.dashboard.channel_for(self.bot.guild, self.bot.member), system)
        system.permissions_for = lambda _: NS(view_channel=False, send_messages=False)
        self.assertIs(self.dashboard.channel_for(self.bot.guild, self.bot.member), text)

    async def test_only_voice_available_is_last_fallback(self):
        self.bot.player.current_entry.channel = None
        self.bot.guild.system_channel, self.bot.guild.text_channels = None, []
        self.assertIs(self.dashboard.channel_for(self.bot.guild, self.bot.member), self.bot.channel)

    async def test_voice_cannot_bypass_binding(self):
        self.bot.player.current_entry.channel = None
        self.bot.guild.system_channel, self.bot.guild.text_channels = None, []
        self.bot.config.bound_channels = {999}
        await self.call(BASE+"volume", {"volume": 60}, status=403)

    async def test_foreign_guild_request_channel_rejected(self):
        other = self.channel(101)
        other.guild = NS(id=2)
        self.bot.player.current_entry.channel = other
        self.assertIs(self.dashboard.channel_for(self.bot.guild, self.bot.member), self.bot.channel)

    async def test_web_actions_share_channel_context(self):
        music = self.channel(101)
        self.bot.player.current_entry.channel = music
        self.login_as(42)
        cases = [("pause", {}), ("resume", {}), ("volume", {"volume": 50}),
                 ("repeat", {"mode": "song"}), ("repeat", {"mode": "off"}),
                 ("queue/move", {"from": 1, "to": 2}), ("queue/shuffle", {})]
        for action, data in cases:
            if action.startswith("queue/"):
                data["revision"] = await self.rev()
            await self.call(BASE+action, data)
            self.assertIs(self.bot.safe_send_message.await_args.args[0], music)

    async def test_legacy_entry_voice_chat_does_not_precede_text(self):
        self.bot.channel.type = discord.ChannelType.voice
        system = self.channel(101)
        self.bot.guild.system_channel, self.bot.guild.text_channels = system, [system]
        self.assertIs(self.dashboard.channel_for(self.bot.guild, self.bot.member), system)

    async def test_latest_queued_without_permission_falls_to_system(self):
        self.bot.player.current_entry.channel = None
        self.bot.player.playlist.entries[-1].channel = self.channel(101, allowed=False)
        self.assertIs(self.dashboard.channel_for(self.bot.guild, self.bot.member), self.bot.channel)

    async def test_send_only_permission_is_checked_on_both_sides(self):
        music = self.channel(101)
        self.bot.player.current_entry.channel = music
        for denied in (self.bot.member, self.bot.guild.me):
            music.permissions_for = lambda member: NS(view_channel=True, send_messages=member is not denied)
            self.assertIs(self.dashboard.channel_for(self.bot.guild, self.bot.member), self.bot.channel)

    async def test_play_and_playnext_receive_the_request_text_channel(self):
        self.login_as(42)
        music = self.channel(101)
        self.bot.player.current_entry.channel = music
        for action in ("play", "playnext"):
            command = AsyncMock(return_value=None)
            setattr(self.bot, "cmd_"+action, command)
            await self.call(BASE+action, {"query":"fixture song"})
            self.assertIs(command.await_args.kwargs["channel"], music)

    async def test_notification_rechecks_channel_after_command_await(self):
        music = self.channel(101)
        self.bot.player.current_entry.channel = music
        real = self.bot.cmd_volume
        async def revoke(*args):
            response = await real(*args)
            music.permissions_for = lambda _: NS(view_channel=True, send_messages=False)
            return response
        self.bot.cmd_volume = revoke
        await self.call(BASE+"volume", {"volume":65})
        self.assertIs(self.bot.safe_send_message.await_args.args[0], self.bot.channel)

    async def test_unknown_page_redirect_and_json_errors(self):
        r = await self.client.get("/dashboard/quota", allow_redirects=False)
        self.assertEqual((r.status, r.headers["Location"]), (302, "/"))
        for path in ("/api/unknown", "/auth/missing", "/static/missing", "/missing.js"):
            r = await self.client.get(path, headers=HEADERS)
            self.assertEqual(r.status, 404, path)
            self.assertIn("error", await r.json())
        self.assertIn((await self.client.post("/dashboard/quota")).status, (404, 405))

    async def test_local_favicon_both_paths(self):
        for path in ("/favicon.svg", "/favicon.ico"):
            r = await self.client.get(path)
            self.assertEqual(r.status, 200)
            self.assertIn("image/svg+xml", r.headers["Content-Type"])
            self.assertIn("<svg", await r.text())

    async def test_events_without_header_snapshot_and_no_cors(self):
        r = await self.stream(headers={"Sec-Fetch-Site":"same-origin", "Origin":self.origin})
        self.assertEqual(r.headers["Cache-Control"], "no-cache")
        self.assertEqual(r.headers["X-Accel-Buffering"], "no")
        self.assertNotIn("Access-Control-Allow-Origin", r.headers)
        frame = await self.frame(r)
        self.assertTrue(frame.startswith("event: snapshot"))
        bundle = json.loads(frame.split("data: ",1)[1])
        self.assertEqual(set(bundle), {"state","listeners","activity","history"})
        self.assertEqual(bundle["state"]["guild_id"], "1")
        r.close()

    async def test_events_anonymous_401(self):
        self.client.session.cookie_jar.clear()
        self.assertEqual((await self.client.get(BASE+"events")).status, 401)

    async def test_events_cross_site_same_site_origin_host_rejected(self):
        for headers in ({"Sec-Fetch-Site":"cross-site"}, {"Sec-Fetch-Site":"same-site"},
                        {"Sec-Fetch-Site":"none"}, {"Origin":"https://evil.example"},
                        {"Host":"evil.example"}):
            self.assertEqual((await self.client.get(BASE+"events",headers=headers)).status,403)

    async def test_events_only_get_no_bypass_elsewhere(self):
        for method in ("post","head","options"):
            r = await getattr(self.client,method)(BASE+"events")
            self.assertNotEqual(r.status,200)
        self.assertEqual((await self.client.get(BASE+"state")).status,403)

    async def test_events_expiry_closes_before_new_snapshot(self):
        r = await self.stream()
        await self.frame(r)
        for value in self.dashboard.sessions.values():
            value["expires"] = time.monotonic()-1
        self.bot.player.volume = .99
        frame = await self.frame(r)
        self.assertIn("event: access",frame)
        self.assertIn("401",frame)
        self.assertEqual(await asyncio.wait_for(r.content.read(),1),b"")

    async def test_events_logout_closes(self):
        r = await self.stream()
        await self.frame(r)
        await self.call("/auth/logout",{})
        self.assertIn("401",await self.frame(r))
        self.assertEqual(await asyncio.wait_for(r.content.read(),1),b"")

    async def test_events_membership_removal_closes(self):
        r = await self.stream()
        await self.frame(r)
        self.bot.members.pop(43)
        self.assertIn("403",await self.frame(r))
        self.assertEqual(await asyncio.wait_for(r.content.read(),1),b"")

    async def test_events_blocked_user_closes(self):
        r = await self.stream()
        await self.frame(r)
        self.bot.blocked_users.add(43)
        self.assertIn("403",await self.frame(r))

    async def test_events_per_user_cap_across_sessions(self):
        responses = []
        for _ in range(self.dashboard.STREAMS_PER_USER):
            self.login_as(43)
            r = await self.stream()
            await self.frame(r)
            responses.append(r)
        self.assertEqual((await self.client.get(BASE+"events")).status,429)
        self.assertEqual(len(self.dashboard.stream_users),self.dashboard.STREAMS_PER_USER)
        for r in responses:
            r.close()

    async def test_events_global_cap_across_users(self):
        self.dashboard.STREAMS_GLOBAL = 1
        r = await self.stream()
        await self.frame(r)
        self.login_as(42)
        self.assertEqual((await self.client.get(BASE+"events")).status,429)
        r.close()

    async def test_events_heartbeat_without_progress_polling(self):
        r = await self.stream()
        await self.frame(r)
        self.assertEqual(await self.frame(r),": heartbeat\n")
        r.close()

    async def test_events_push_all_community_changes(self):
        r = await self.stream()
        await self.frame(r)
        self.bot.player.playlist.entries.append(entry("New",author=self.bot.member))
        self.dashboard.record_activity(self.bot.guild,"Friend","play","discord_text","點歌：New","成功")
        self.dashboard.record_play(self.bot.guild,self.bot.player.current_entry)
        self.bot.channel.members.pop()
        bundle = json.loads((await self.frame(r)).split("data: ",1)[1])
        self.assertEqual(bundle["state"]["queue"][-1]["title"],"New")
        self.assertEqual(len(bundle["listeners"]["members"]),2)
        self.assertTrue(bundle["activity"]["activity"])
        self.assertTrue(bundle["history"]["history"])
        r.close()

    async def test_events_seek_jump_pushes_progress(self):
        r = await self.stream()
        await self.frame(r)
        self.bot.player.progress = 90
        self.assertIn('"progress": 90',await self.frame(r))
        r.close()

    async def test_events_bot_shutdown_releases_slots(self):
        r = await self.stream()
        await self.frame(r)
        self.bot.logout_called = True
        self.assertEqual(await asyncio.wait_for(r.content.read(),1),b"")
        self.assertFalse(self.dashboard.stream_users)

    async def test_events_app_shutdown_closes_idle_stream(self):
        r = await self.stream()
        await self.frame(r)
        await self.dashboard.shutdown_events()
        self.assertEqual(await asyncio.wait_for(r.content.read(),1),b"")
        self.assertFalse(self.dashboard.stream_users)

    async def test_events_legacy_shared_secret_cannot_be_bypassed(self):
        self.dashboard.config = replace(self.dashboard.config,auth_mode="owner",shared_secret="fake")
        self.assertEqual((await self.client.get(BASE+"events")).status,403)

    async def test_events_error_after_prepare_closes_cleanly(self):
        r = await self.stream()
        await self.frame(r)
        with patch.object(self.dashboard,"event_snapshot",side_effect=ValueError("private")):
            self.assertEqual(await asyncio.wait_for(r.content.read(),1),b"")
        self.assertFalse(self.dashboard.stream_users)

class NativeActivityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        builtins._L = lambda text: text
        self.bot = FakeBot()
        self.dashboard = Dashboard(self.bot,DashboardConfig())
        self.bot._web_dashboard = self.dashboard

    def test_no_player_capture_still_records(self):
        self.bot.get_player_in = lambda _: None
        finish(capture(self.dashboard,self.bot.guild,self.bot.owner,"play","discord_text"),True)
        self.assertEqual(self.dashboard.activities[1][0]["result"],"成功")

    async def text_command(self,query="!volume 55",denied=False):
        bot = self.bot
        channel = Mock(spec=discord.TextChannel)
        channel.guild,channel.id = bot.guild,10
        member = Mock(spec=discord.Member)
        member.id,member.name,member.display_name = 43,"Friend","Friend"
        member.bot,member.voice = False,NS(channel=channel)
        bot.user = NS(id=999)
        bot.wait_until_ready = AsyncMock()
        bot.server_data[1] = NS(command_prefix="!")
        bot.config.commands_via_mention = bot.config.delete_invoking = bot.config.debug_mode = False
        bot.config.bot_exception_ids,bot.config.usealias = set(),True
        bot.config.user_blocklist = NS(is_blocked=lambda _:False)
        bot.perms.can_use_command = lambda *_:not denied
        bot.perms.name = "Test"
        bot.safe_send_message = AsyncMock()
        message = NS(channel=channel,guild=bot.guild,author=member,content=query,attachments=[])
        await MusicBot.on_message(bot,message)

    async def test_actual_text_dispatch_success_and_denial(self):
        await self.text_command()
        self.assertEqual(self.bot.player.volume,.55)
        self.assertEqual(self.dashboard.activities[1][0]["source"],"discord_text")
        self.assertEqual(self.dashboard.activities[1][0]["result"],"成功")
        await self.text_command("!volume 90",denied=True)
        self.assertEqual(self.bot.player.volume,.55)
        self.assertEqual(self.dashboard.activities[1][0]["result"],"被拒或未完成")

    async def test_text_capture_and_finish_failure_preserve_command_reply(self):
        for helper in ("begin_text","finish_activity"):
            with patch("musicbot.bot."+helper,side_effect=RuntimeError("fixture")):
                await self.text_command()
            self.assertEqual(self.bot.player.volume,.55)
            self.bot.safe_send_message.assert_awaited_once()
            self.assertIn("55",self.bot.safe_send_message.await_args.args[1].content)

    def slash_context(self):
        cog = SlashCommands(self.bot)
        interaction = NS(guild=self.bot.guild,user=self.bot.owner,response=NS(defer=AsyncMock()))
        cog._check_perms = AsyncMock(return_value=True)
        cog._get_player = AsyncMock(return_value=self.bot.player)
        cog._ssd,cog._reply = lambda _:None,AsyncMock()
        return cog,interaction

    async def test_actual_slash_callback_registration_and_signature(self):
        cog,interaction = self.slash_context()
        command = SlashCommands.slash_volume
        self.assertEqual(list(inspect.signature(command.callback).parameters),
                         list(inspect.signature(command.callback.__wrapped__).parameters))
        self.assertEqual(command.parameters[0].name,"level")
        await command.callback(cog,interaction,"63")
        self.assertEqual(self.bot.player.volume,.63)
        cog._reply.assert_awaited_once()
        self.assertEqual(self.dashboard.activities[1][0]["source"],"discord_slash")
        self.assertEqual(self.dashboard.activities[1][0]["result"],"成功")

    async def test_slash_observer_failures_preserve_real_callback_reply(self):
        cog,interaction = self.slash_context()
        for helper in ("capture","finish"):
            cog._reply.reset_mock()
            with patch("musicbot.web_dashboard_activity."+helper,side_effect=RuntimeError("fixture")):
                await SlashCommands.slash_volume.callback(cog,interaction,"67")
            self.assertEqual(self.bot.player.volume,.67)
            cog._reply.assert_awaited_once()
        with patch("musicbot.slash_commands.native_result",side_effect=RuntimeError("fixture")):
            await SlashCommands.slash_volume.callback(cog,interaction,"68")
        self.assertEqual(self.bot.player.volume,.68)

    async def test_slash_error_response_preserved_and_context_reset(self):
        class Cog:
            bot = self.bot
        @slash_activity("play")
        async def callback(cog,interaction):
            response = ErrorResponse("original")
            native_result(response)
            return response
        result = await callback(Cog(),NS(guild=self.bot.guild,user=self.bot.owner))
        self.assertIsInstance(result,ErrorResponse)
        self.assertEqual(self.dashboard.activities[1][0]["result"],"被拒或未完成")
        self.assertIsNone(ACTIVE.get())

    async def test_slash_original_exception_propagates_unchanged(self):
        class Cog:
            bot = self.bot
        error = ValueError("original")
        @slash_activity("pause")
        async def callback(cog,interaction):
            raise error
        with self.assertRaises(ValueError) as raised:
            await callback(Cog(),NS(guild=self.bot.guild,user=self.bot.owner))
        self.assertIs(raised.exception,error)
        self.assertIsNone(ACTIVE.get())

    async def test_queue_observer_failure_preserves_original_event(self):
        self.bot.config.auto_playlist_autoskip = False
        item = entry(author=self.bot.owner,channel=self.bot.channel)
        with patch.object(self.dashboard,"note_queue_entry",side_effect=RuntimeError("fixture")):
            await MusicBot.on_player_entry_added(self.bot,self.bot.player,self.bot.player.playlist,item)
        self.bot.serialize_queue.assert_awaited_once()

    def test_native_action_names_all_supported(self):
        for action in ("play","playnext","playnow","shuffleplay","stream","skip","remove",
                       "move","shuffle","clear","pause","resume","volume","repeat","seek"):
            finish(capture(self.dashboard,self.bot.guild,self.bot.owner,action,"discord_text"),True)
            self.assertEqual(self.dashboard.activities[1][0]["action"],action)

class Round6DemoTests(unittest.IsolatedAsyncioTestCase):
    async def test_demo_unknown_length_sources_and_live_changes_no_network(self):
        bot = DemoBot("http://127.0.0.1")
        dash = DemoDashboard(bot,DashboardConfig())
        self.assertTrue(any(not s.duration for s in bot.players[1].playlist.entries))
        self.assertEqual(len(dash.listener_snapshot(bot.guilds[0])["members"]),11)
        self.assertEqual({r["source"] for r in dash.activities[1]},{"web","discord_text","discord_slash"})
        with patch("aiohttp.ClientSession",side_effect=AssertionError("HTTP forbidden")):
            before = len(bot.players[1].playlist.entries)
            dash.demo_tick()
            self.assertEqual(len(bot.players[1].playlist.entries),before+1)
            dash.demo_tick()
            self.assertTrue(dash.recent_history[1])
            for _ in range(30):
                dash.demo_tick()
                songs = list(bot.players[1].playlist.entries)
                self.assertLessEqual(len(songs), 12)
                self.assertTrue(any(not song.duration for song in songs))
                self.assertTrue(songs[-1].duration)
            await dash.close()
