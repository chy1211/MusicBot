"""Offline preview reuse through real Downloader, HTTP routes and native commands."""
import asyncio
import copy
import json
import time
import unittest
from types import MethodType, SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import test_web_dashboard as base
import test_web_dashboard_discord as discord
from musicbot.bot import MusicBot
from musicbot.downloader import Downloader, YtdlpResponseDict
from musicbot.entry import URLPlaylistEntry
from musicbot.exceptions import PermissionsError
from musicbot.web_dashboard import CONFIRMED_ENTRY_CHECK
from musicbot.web_dashboard_extraction import RESOLUTION_BUDGET, WEB_EXTRACTION
from musicbot.web_dashboard_preview import (
    PREVIEW_EXTRACTION, PreviewExtraction, MAX_EXTRACTION_AGE,
    MAX_SAVED_EXTRACTIONS, MAX_EXTRACTION_BYTES, save_extraction)

URL = "https://www.youtube.com/watch?v=AbcDeFg1234"
LOG = "musicbot.web_dashboard_preview"


def install_downloader(case):
    bot = case.bot
    bot.filecache = NS()
    bot.cmd_playnext = MethodType(MusicBot.cmd_playnext, bot)
    bot.info = dict(bot.info, webpage_url=URL, url="https://media.example.test/audio",
                    _type="video", formats=[{"format_id": "140", "url": "https://media.example.test/audio",
                                            "ext": "m4a"}], ext="m4a", title="Demo track")
    case.provider_calls = []
    downloader = object.__new__(Downloader)
    downloader.bot = bot
    downloader._cookie_clients = NS(snapshot=lambda **kwargs: (client, client))
    client = NS(prepare_filename=lambda data: "demo-track.m4a", sanitize_info=lambda data: data)
    downloader.randomize_user_agent_string = Mock()
    downloader.get_url_headers = AsyncMock(return_value={"CONTENT-TYPE": "audio/mp4"})

    async def provider(subject, *args, **kwargs):
        admitted = asyncio.current_task() in case.dashboard.resolve_tasks.values()
        if WEB_EXTRACTION.get():
            case.assertTrue(admitted, "a real extraction ran without resolution admission")
            case.assertIsNotNone(RESOLUTION_BUDGET.get())
        case.provider_calls.append((subject, admitted, kwargs))
        return copy.deepcopy(bot.info)
    downloader._filtered_extract_info = provider
    bot.downloader = downloader
    playlist = bot.player.playlist

    async def add(info, *, author, channel, head=False, **kwargs):
        item = URLPlaylistEntry(playlist, info, author=author, channel=channel)
        if head:
            playlist.entries.appendleft(item)
        else:
            playlist.entries.append(item)
        return item, len(playlist.entries)
    playlist.add_entry_from_info = add


class PreviewReuseTests(unittest.IsolatedAsyncioTestCase):
    call = base.DashboardTests.call
    asyncTearDown = base.DashboardTests.asyncTearDown

    async def asyncSetUp(self):
        await base.DashboardTests.asyncSetUp(self)
        install_downloader(self)

    async def preview(self, query=URL, action="play"):
        body = await self.call(base.BASE + "resolve", {"query": query, "action": action})
        return body["results"][0]

    def record(self, item):
        return self.dashboard.previews[item["preview_id"]]

    async def add(self, item, action="play", status=200):
        return await self.call(base.BASE + action,
            {"query": item["url"], "preview_id": item["preview_id"]}, status=status)

    async def until(self, predicate):
        async def spin():
            while not predicate():
                await asyncio.sleep(0)
        await asyncio.wait_for(spin(), 2)

    async def fill_slots(self):
        release = asyncio.Event()
        async def blocker():
            await release.wait()
        tasks = [asyncio.create_task(self.dashboard.run_resolution(self.bot.guild,
            blocker(), owner=NS(id=uid))) for uid in (700, 701)]
        await self.until(lambda: len(self.dashboard.resolve_tasks) == 2)
        return release, tasks

    async def test_single_url_query_one_add_zero_preserves_info_and_download_reuse(self):
        item = await self.preview()
        self.assertEqual(len(self.provider_calls), 1)
        saved = json.loads(self.record(item)["extraction"])
        self.assertNotIn("formats", json.dumps(item))
        self.assertNotIn("__extracted_at", json.dumps(item))
        with self.assertLogs(LOG, level="INFO") as logs:
            await self.add(item)
        self.assertEqual(len(self.provider_calls), 1)
        self.assertEqual(logs.output, ["INFO:" + LOG + ":Dashboard add reused preview extraction"])
        queued = self.bot.player.playlist.entries[-1]
        self.assertEqual((queued.title, queued.url), ("Demo track", URL))
        self.assertEqual(queued.info["__extracted_at"], saved["__extracted_at"])
        self.assertEqual(queued.info["formats"], saved["formats"])
        self.assertEqual(queued.info["__expected_filename"], "demo-track.m4a")
        # Feed the real download_from_info boundary without any provider/network.
        self.bot.loop = asyncio.get_running_loop()
        queued.downloader.thread_pool = None
        seen = []
        def process(data, download=True):
            seen.append(data)
            return dict(data, requested_downloads=[{"filepath": "demo-track.m4a"}])
        client = NS(process_ie_result=process, sanitize_info=lambda data: data,
                    prepare_filename=lambda data: "demo-track.m4a")
        queued.downloader._cookie_clients = NS(snapshot=lambda **kwargs: (client, client))
        result = await queued.downloader.download_from_info(queued._reusable_extraction())
        self.assertEqual(result["__extracted_at"], saved["__extracted_at"])
        self.assertEqual(seen[0]["formats"], saved["formats"])
        self.assertEqual(len(self.provider_calls), 1)
        self.assertNotIn("extraction", self.record(item))
        self.assertIsNone(PREVIEW_EXTRACTION.get())
        self.assertIsNone(CONFIRMED_ENTRY_CHECK.get())
        print("R40 CALLS: query=1 add=0 download_from_info=1 fresh_extraction_for_download=0; timestamp preserved")

    async def test_reuse_completes_while_both_resolution_slots_are_busy(self):
        item = await self.preview()
        release, tasks = await self.fill_slots()
        try:
            await asyncio.wait_for(self.add(item), 1)
            self.assertEqual(len(self.dashboard.resolve_tasks), 2)
            self.assertFalse(self.dashboard.resolution_queue.waiting)
            self.assertEqual(len(self.provider_calls), 1)
        finally:
            release.set()
            await asyncio.gather(*tasks)
        print("R40 ADMISSION: two occupied slots; cached add completed; extra provider calls=0")

    async def test_expired_extraction_waits_for_admission_then_extracts_once(self):
        item = await self.preview()
        record = self.record(item)
        data = json.loads(record["extraction"])
        data["__extracted_at"] = time.time() - MAX_EXTRACTION_AGE - 1
        record["extraction"] = json.dumps(data).encode()
        release, tasks = await self.fill_slots()
        pending = asyncio.create_task(self.add(item))
        try:
            await self.until(lambda: len(self.dashboard.resolution_queue.waiting) == 1)
            self.assertEqual(len(self.provider_calls), 1)
            self.assertFalse(pending.done())
            release.set()
            await pending
            self.assertEqual(len(self.provider_calls), 2)
            self.assertTrue(self.provider_calls[-1][1])
        finally:
            release.set()
            await asyncio.gather(pending, *tasks, return_exceptions=True)
        print("R40 FALLBACK: expired add queued; extra provider calls=1 with admission")

    async def test_expires_during_native_lock_wait_falls_back_without_command_replay(self):
        item = await self.preview()
        data = json.loads(self.record(item)["extraction"])
        data["__extracted_at"] = time.time() - MAX_EXTRACTION_AGE + 1
        self.record(item)["extraction"] = json.dumps(data).encode()
        release, tasks = await self.fill_slots()
        entered, proceed = asyncio.Event(), asyncio.Event()
        async def typing():
            entered.set()
            await proceed.wait()
        self.bot.channel.typing = typing
        pending = asyncio.create_task(self.add(item))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            with patch("musicbot.web_dashboard_preview.time.time", return_value=time.time() + 2):
                proceed.set()
                await self.until(lambda: len(self.dashboard.resolution_queue.waiting) == 1)
                self.assertEqual(len(self.provider_calls), 1)
                release.set()
                await pending
            self.assertEqual(len(self.provider_calls), 2)
            self.assertEqual(len(self.bot.player.playlist.entries), 4)
        finally:
            proceed.set()
            release.set()
            await asyncio.gather(pending, *tasks, return_exceptions=True)

    async def test_keyword_playlist_compound_and_spotify_always_reextract(self):
        child = copy.deepcopy(self.bot.info)
        cases = [
            ("demo search", None),
            ("https://www.youtube.com/playlist?list=PLDEMO", "playlist"),
            (URL + "&list=RDDEMO", "playlist"),
            ("https://open.spotify.com/track/0123456789ABCDEFGHIJKL", "spotify"),
        ]
        self.bot.config.spotify_enabled = True
        for query, kind in cases:
            with self.subTest(query=query):
                self.bot.info = copy.deepcopy(child)
                if kind == "spotify":
                    self.bot.info["webpage_url"] = query
                if kind == "playlist":
                    imported = {"title": "Demo list", "count": 1,
                        "tracks": [{"title": "Demo track", "url": URL, "duration": 120}],
                        "source_url": query, "source_type": "youtube", "is_mix": False}
                else:
                    imported = None
                with patch.object(self.dashboard, "import_source", AsyncMock(return_value=imported)):
                    item = await self.preview(query)
                self.assertNotIn("extraction", self.record(item))
                self.bot.info = copy.deepcopy(child)
                before = len(self.provider_calls)
                await self.add(item)
                self.assertEqual(len(self.provider_calls) - before, 1)
                self.assertTrue(self.provider_calls[-1][1])

    async def test_compound_playnext_even_single_result_cannot_reuse(self):
        item = await self.preview(URL + "&list=RDDEMO", action="playnext")
        self.assertEqual(item["kind"], "track")
        self.assertNotIn("extraction", self.record(item))
        before = len(self.provider_calls)
        await self.add(item, action="playnext")
        self.assertEqual(len(self.provider_calls) - before, 1)

    async def test_duration_blocklist_and_command_permission_match_fresh_path(self):
        for gate in ("duration", "blocklist"):
            messages = []
            for reuse in (True, False):
                with self.subTest(gate=gate, reuse=reuse):
                    self.bot.perms.max_song_length = 0
                    self.bot.blocked.clear()
                    self.bot.perms.can_use_command = lambda *args: True
                    item = await self.preview()
                    if not reuse:
                        self.record(item).pop("extraction")
                    if gate == "duration":
                        self.bot.perms.max_song_length = 100
                    elif gate == "blocklist":
                        self.bot.blocked.add("Demo track")
                    before = len(self.provider_calls)
                    response = await self.add(item, status=403)
                    messages.append(response["error"])
                    self.assertEqual(len(self.provider_calls) - before,
                        0 if reuse else 1)
            self.assertEqual(messages[0], messages[1])
        self.assertEqual(len(self.bot.player.playlist.entries), 3)

    async def test_duplicate_preview_is_serialized_and_playnext_keeps_order(self):
        first = await self.preview()
        before = len(self.provider_calls)
        await asyncio.gather(self.add(first), self.add(first))
        self.assertEqual(len(self.bot.player.playlist.entries), 4)
        self.assertEqual(len(self.provider_calls), before)
        second = await self.preview()
        await self.add(second, action="playnext")
        entries = self.bot.player.playlist.entries
        self.assertEqual(entries[0].title, "Demo track")
        self.assertEqual(entries[-1].title, "Demo track")
        # The existing preview JSON still contains the URL used for duplicate UI.
        self.assertEqual(first["url"], entries[-1].url)

    async def test_memory_cap_oversize_and_expiry_cleanup(self):
        for _ in range(MAX_SAVED_EXTRACTIONS + 4):
            await self.preview()
        saved = [p for p in self.dashboard.previews.values() if "extraction" in p]
        self.assertEqual(len(saved), MAX_SAVED_EXTRACTIONS)
        self.assertLessEqual(sum(len(p["extraction"]) for p in saved),
                             MAX_SAVED_EXTRACTIONS * MAX_EXTRACTION_BYTES)
        self.dashboard._complete_info_cache._items.clear()
        self.bot.info["description"] = "x" * (MAX_EXTRACTION_BYTES + 1)
        item = await self.preview()
        self.assertNotIn("extraction", self.record(item))
        self.assertEqual(self.record(item)["extraction_reason"], "result-too-large")
        self.bot.info.pop("description")
        for p in self.dashboard.previews.values():
            p["expires"] = time.monotonic() - 1
        fresh = await self.preview()
        self.assertEqual(sum("extraction" in p for p in self.dashboard.previews.values()), 1)
        self.assertIn("extraction", self.record(fresh))

    async def test_preview_count_cap_and_eviction_release_payloads(self):
        # Exercise issuance, independent of HTTP per-minute admission.
        for _ in range(110):
            results = await self.dashboard.run_resolution(self.bot.guild,
                self.dashboard.resolve_options(self.bot.guild, self.bot.owner, URL),
                owner=self.bot.owner)
            await self.dashboard.issue_previews(self.bot.guild, self.bot.owner, results, URL, "play")
        self.assertEqual(len(self.dashboard.previews), 100)
        self.assertEqual(sum("extraction" in p for p in self.dashboard.previews.values()),
                         MAX_SAVED_EXTRACTIONS)

    async def test_preview_ttl_renewal_extracts_only_once_and_transfers_fresh_data(self):
        item = await self.preview()
        self.record(item)["expires"] = time.monotonic() - 1
        # Simulate real expiry: complete metadata TTL is shorter than preview TTL.
        self.dashboard._complete_info_cache._items.clear()
        before = len(self.provider_calls)
        with self.assertLogs(LOG, level="INFO") as logs:
            await self.add(item)
        self.assertIn("expired-preview", logs.output[0])
        self.assertIn("reused preview extraction", logs.output[1])
        self.assertEqual(len(self.provider_calls) - before, 1)
        self.assertEqual(len(self.bot.player.playlist.entries), 4)
        self.assertNotIn("extraction", self.record(item))

    async def test_native_discord_no_context_still_extracts_and_gets_headers(self):
        self.assertIsNone(PREVIEW_EXTRACTION.get())
        await self.bot.cmd_play(message=None, player=self.bot.player, channel=self.bot.channel,
            guild=self.bot.guild, author=self.bot.owner, permissions=self.bot.perms,
            leftover_args=[], song_url=URL)
        self.assertEqual(len(self.provider_calls), 1)
        self.assertFalse(self.provider_calls[0][1])
        self.bot.downloader.get_url_headers.assert_awaited_once()
        self.assertEqual(len(self.bot.player.playlist.entries), 4)

    async def test_scope_mismatch_options_and_repeat_calls_always_acquire_admission(self):
        item = await self.preview()
        data = json.loads(self.record(item)["extraction"])
        scope = PreviewExtraction(data, lambda operation: self.dashboard.run_resolution(
            self.bot.guild, operation, owner=self.bot.owner, priority="add"))
        token = PREVIEW_EXTRACTION.set(scope)
        web_token = WEB_EXTRACTION.set(True)
        try:
            result = await self.bot.downloader.extract_info(URL, download=False, process=True)
            self.assertEqual(result["__extracted_at"], data["__extracted_at"])
            self.assertEqual(len(self.provider_calls), 1)
            await self.bot.downloader.extract_info(URL, download=False, process=True)
            await self.bot.downloader.extract_info(URL, download=False, process=False)
            await self.bot.downloader.extract_info(URL + "&t=2", download=False, process=True)
        finally:
            scope.active = False
            WEB_EXTRACTION.reset(web_token)
            PREVIEW_EXTRACTION.reset(token)
        self.assertEqual(len(self.provider_calls), 4)
        self.assertTrue(all(call[1] for call in self.provider_calls))

    async def test_inherited_scope_does_not_change_background_download_or_other_tasks(self):
        item = await self.preview()
        scope = PreviewExtraction(json.loads(self.record(item)["extraction"]),
                                  lambda _: self.fail("background download entered add queue"))
        token = PREVIEW_EXTRACTION.set(scope)
        try:
            await asyncio.create_task(self.bot.downloader.extract_info(URL, download=True))
        finally:
            scope.active = False
            PREVIEW_EXTRACTION.reset(token)
        self.assertEqual(len(self.provider_calls), 2)
        self.assertFalse(self.provider_calls[-1][1])
        self.assertFalse(scope.used)

    async def test_missing_timestamp_formats_redirect_and_entries_are_not_cached(self):
        original = copy.deepcopy(self.bot.info)
        for change, reason in [
                ({"formats": []}, "no-download-formats"),
                ({"webpage_url": URL + "&t=10"}, "url-mismatch")]:
            self.bot.info = dict(original, **change)
            item = await self.preview()
            self.assertNotIn("extraction", self.record(item))
            self.assertEqual(self.record(item)["extraction_reason"], reason)
        self.bot.info = original
        data = dict(original, __input_subject=URL, __extracted_at=time.time())
        for stamp in (None, 0, True, "bad", float("nan"), 10 ** 1000, time.time() + 60):
            info = YtdlpResponseDict(dict(data, __extracted_at=stamp))
            blob, reason = save_extraction(info, URL, URL)
            self.assertIsNone(blob)
            self.assertIn(reason, ("invalid-timestamp", "expired-extraction"))
        blob, reason = save_extraction(YtdlpResponseDict(dict(data, entries=[])), URL, URL)
        self.assertIsNone(blob)
        self.assertEqual(reason, "not-single-track")
        self.assertLessEqual(MAX_EXTRACTION_AGE, URLPlaylistEntry.REUSE_EXTRACTION_MAX_AGE)

    async def test_normalized_url_match_and_tampered_confirmation_rejected(self):
        item = await self.preview(" <HTTPS://WWW.YOUTUBE.COM/watch?v=AbcDeFg1234#t=20> ")
        self.assertIn("extraction", self.record(item))
        await self.call(base.BASE + "play",
            {"query": item["url"] + "&t=2", "preview_id": item["preview_id"]}, status=403)
        self.assertEqual(len(self.provider_calls), 1)
        await self.add(item)
        self.assertEqual(len(self.provider_calls), 1)

    async def test_queue_limit_karaoke_and_extractor_revocation_still_reject(self):
        for gate in ("queue", "karaoke", "extractor"):
            with self.subTest(gate=gate):
                self.bot.perms.max_songs = 0
                self.bot.player.karaoke_mode = False
                self.bot.perms.can_use_extractor = lambda *args: True
                item = await self.preview()
                before = len(self.provider_calls)
                if gate == "queue":
                    self.bot.perms.max_songs = 3
                elif gate == "karaoke":
                    self.bot.player.karaoke_mode = True
                    self.bot.perms.bypass_karaoke_mode = False
                else:
                    def blocked_extractor(*args):
                        raise PermissionsError("Demo extractor blocked")
                    self.bot.perms.can_use_extractor = blocked_extractor
                await self.add(item, status=403)
                self.assertEqual(len(self.provider_calls), before)
                self.assertEqual(len(self.bot.player.playlist.entries), 3)

    async def test_missing_saved_result_falls_back_once_under_admission(self):
        item = await self.preview()
        self.record(item).pop("extraction")
        with self.assertLogs(LOG, level="INFO") as logs:
            await self.add(item)
        self.assertIn("no-saved-result", logs.output[0])
        self.assertEqual(len(self.provider_calls), 2)
        self.assertTrue(self.provider_calls[-1][1])

    async def test_scope_cleanup_after_native_error_releases_request_and_data(self):
        item = await self.preview()
        scopes = []
        from musicbot import web_dashboard_preview as module
        original = module.PreviewExtraction
        def capture_scope(*args):
            scope = original(*args)
            scopes.append(scope)
            return scope
        self.bot.blocked.add("Demo track")
        with patch.object(module, "PreviewExtraction", side_effect=capture_scope):
            await self.add(item, status=403)
        self.assertEqual(len(scopes), 1)
        self.assertFalse(scopes[0].active)
        self.assertIsNone(scopes[0].data)
        self.assertIsNone(scopes[0].admit)
        self.assertIsNone(scopes[0].task)
        self.assertNotIn("extraction", self.record(item))
        self.assertEqual(len(self.provider_calls), 1)

    async def test_malformed_private_payload_falls_back_and_logs_no_identity(self):
        item = await self.preview()
        self.record(item)["extraction"] = b"{invalid"
        with self.assertLogs(LOG, level="INFO") as logs:
            await self.add(item)
        self.assertEqual(logs.output,
            ["INFO:" + LOG + ":Dashboard add re-extracting preview: invalid-result"])
        self.assertEqual(len(self.provider_calls), 2)


class PreviewOwnershipTests(unittest.IsolatedAsyncioTestCase):
    call = discord.DiscordTests.call
    login_as = discord.DiscordTests.login_as
    provider_me = discord.DiscordTests.provider_me
    provider_token = discord.DiscordTests.provider_token
    asyncTearDown = discord.DiscordTests.asyncTearDown

    async def asyncSetUp(self):
        await discord.DiscordTests.asyncSetUp(self)
        install_downloader(self)

    async def test_other_user_and_guild_cannot_reuse_same_preview(self):
        item = (await self.call(base.BASE + "resolve", {"query": URL}))["results"][0]
        self.assertIn("extraction", self.dashboard.previews[item["preview_id"]])
        payload = {"query": item["url"], "preview_id": item["preview_id"]}
        self.login_as(44)
        await self.call(base.BASE + "play", payload, status=409)
        self.login_as(43)
        guild2 = NS(id=2, unavailable=False, name="Demo guild",
                    get_member=self.bot.members.get)
        self.bot.guilds.append(guild2)
        self.bot.get_guild = lambda gid: {1: self.bot.guild, 2: guild2}.get(gid)
        await self.call("/api/guilds/2/play", payload, status=409)
        self.assertEqual(len(self.provider_calls), 1)
        self.assertEqual(len(self.bot.player.playlist.entries), 3)

    async def test_revoked_command_permission_cannot_reuse(self):
        messages = []
        for reuse in (True, False):
            self.bot.member_perms.can_use_command.return_value = True
            item = (await self.call(base.BASE + "resolve", {"query": URL}))["results"][0]
            if not reuse:
                self.dashboard.previews[item["preview_id"]].pop("extraction")
            self.bot.member_perms.can_use_command.return_value = False
            response = await self.call(base.BASE + "play", {"query": item["url"],
                "preview_id": item["preview_id"]}, status=403)
            messages.append(response["error"])
        self.assertEqual(messages[0], messages[1])
        self.assertEqual(len(self.provider_calls), 1)
        self.assertEqual(len(self.bot.player.playlist.entries), 3)
