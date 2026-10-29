"""Patch 3+4 regression tests for the MusicBot repository.

Copy to MusicBot/tests/test_patch34_regressions.py and run:
  python -m unittest tests/test_patch34_regressions.py -v
or the repo's standard discovery command (with dependencies installed).
"""
import asyncio
import logging
import threading
import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from musicbot.lib.event_emitter import EventEmitter
from musicbot.bot import MusicBot
import musicbot.bot as bot_module
import test_loudness_normalization as loudness
import test_musicbot_patch2_races as races


class EventEmitterThreadSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_awaitable_from_sync_listener_is_retained_and_completed(self):
        emitter = EventEmitter()
        future = asyncio.get_running_loop().create_future()
        emitter.on("future", lambda: future)
        emitter.emit("future")
        self.assertIn(future, emitter._task_pool)
        future.set_result(None)
        await asyncio.sleep(0)
        self.assertFalse(emitter._task_pool)

    async def test_owner_loop_dispatch_stays_synchronous(self):
        emitter = EventEmitter()
        seen = []
        emitter.once("local", lambda value: seen.append(value))
        emitter.emit("local", 1)
        emitter.emit("local", 2)
        self.assertEqual(seen, [1])

    async def test_sync_and_async_handlers_dispatch_on_owner_loop(self):
        emitter = EventEmitter()
        main_thread = threading.get_ident()
        done = asyncio.Event()
        seen = []

        def listener(value):
            seen.append(("sync", value, threading.get_ident()))

        async def async_listener(value):
            seen.append(("async", value, threading.get_ident()))
            done.set()

        emitter.on("finished", listener)
        emitter.on("finished", async_listener)
        await asyncio.to_thread(emitter.emit, "finished", 17)
        await asyncio.wait_for(done.wait(), 2)
        self.assertEqual([t for t, v, _ in seen], ["sync", "async"])
        self.assertEqual([v for t, v, _ in seen], [17, 17])
        self.assertTrue(all(tid == main_thread for _, _, tid in seen))

    async def test_once_coroutine_from_worker_is_awaited_once(self):
        emitter = EventEmitter()
        done = asyncio.Event()
        received = []

        async def listener(value):
            received.append(value)
            done.set()

        emitter.once("track", listener)
        # Both emissions can arrive before the async callback starts running.
        await asyncio.to_thread(emitter.emit, "track", 7)
        await asyncio.to_thread(emitter.emit, "track", 8)
        await asyncio.wait_for(done.wait(), 2)
        await asyncio.sleep(.01)
        self.assertEqual(received, [7])

    async def test_events_after_loop_is_closed_are_ignored(self):
        emitter = EventEmitter()
        other = asyncio.new_event_loop()
        emitter.loop = other
        other.close()
        values = []
        emitter.on("closed", lambda: values.append(1))
        await asyncio.to_thread(emitter.emit, "closed")
        self.assertEqual(values, [])


class OpusEffectAndRebuildTests(unittest.IsolatedAsyncioTestCase):
    def make_entry(self):
        helper = loudness.RealModuleLoudnessTests()
        helper.setUp()
        return helper.entry()

    async def test_reset_speed_clears_stale_atempo(self):
        entry = self.make_entry()
        entry.set_playback_speed(1.5)
        self.assertIn("atempo=1.500", entry.aoptions)
        entry.set_playback_speed(1.0)
        self.assertNotIn("atempo=", entry.aoptions)

    async def test_paused_opus_volume_restarts_and_keeps_pause(self):
        entry = self.make_entry()
        queue = NS(insert_entry_at_index=Mock())
        player = NS(
            volume=.25, current_entry=entry, is_playing=False,
            is_paused=True, progress=42.5, playlist=queue,
            skip=Mock(), _pending_seek=None,
        )
        config = NS(use_opus_audio=True, use_opus_probe=False,
                    enable_queue_history_global=False,
                    enable_queue_history_guilds=False)
        bot = NS(config=config)
        with patch.object(bot_module, "_D", lambda template, ssd: template):
            await MusicBot.cmd_volume(bot, None, player, "75")
        self.assertEqual(player.volume, .75)
        self.assertEqual(entry.start_time, 42.5)
        self.assertEqual(player._pending_seek,
                         {"entry": entry, "position": 42.5, "paused": True})
        queue.insert_entry_at_index.assert_called_once_with(0, entry)
        player.skip.assert_called_once_with(_seek=True)

    async def test_opus_probe_only_volume_also_rebuilds(self):
        entry = self.make_entry()
        player = NS(volume=.3, current_entry=entry, is_playing=True,
                    is_paused=False, progress=9.0,
                    playlist=NS(insert_entry_at_index=Mock()),
                    skip=Mock(), _pending_seek=None)
        config = NS(use_opus_audio=False, use_opus_probe=True,
                    enable_queue_history_global=False,
                    enable_queue_history_guilds=False)
        with patch.object(bot_module, "_D", lambda template, ssd: template):
            await MusicBot.cmd_volume(NS(config=config), None, player, "60")
        player.skip.assert_called_once_with(_seek=True)
        self.assertEqual(player._pending_seek["position"], 9.0)
        self.assertFalse(player._pending_seek["paused"])

    async def test_paused_stream_volume_rebuild_resets_estimated_position(self):
        helper = loudness.RealModuleLoudnessTests()
        helper.setUp()
        entry = helper.entry("StreamPlaylistEntry")
        player = NS(volume=.2, current_entry=entry, is_playing=False,
                    is_paused=True, progress=47.0,
                    playlist=NS(insert_entry_at_index=Mock()),
                    skip=Mock(), _pending_seek=None)
        config = NS(use_opus_audio=True, use_opus_probe=False,
                    enable_queue_history_global=False,
                    enable_queue_history_guilds=False)
        with patch.object(bot_module, "_D", lambda template, ssd: template):
            await MusicBot.cmd_volume(NS(config=config), None, player, "40")
        self.assertEqual(player._pending_seek["position"], 0.0)
        self.assertTrue(player._pending_seek["paused"])
        player.skip.assert_called_once_with(_seek=True)

    async def test_paused_speed_rebuild_keeps_pause(self):
        entry = self.make_entry()
        player = NS(current_entry=entry, progress=15., is_paused=True,
                    playlist=NS(insert_entry_at_index=Mock()),
                    skip=Mock(), _pending_seek=None)
        config = NS(enable_queue_history_global=False,
                    enable_queue_history_guilds=False)
        with patch.object(bot_module, "_D", lambda template, ssd: template):
            await MusicBot.cmd_speed(NS(config=config), None, NS(id=7), player, "1.25")
        self.assertEqual(entry.playback_speed, 1.25)
        self.assertEqual(player._pending_seek,
                         {"entry": entry, "position": 15., "paused": True})
        player.skip.assert_called_once_with(_seek=True)


class RepeatedEffectRebuildTests(unittest.IsolatedAsyncioTestCase):
    setUp = races.PlaybackGenerationRaceTests.setUp
    asyncTearDown = races.PlaybackGenerationRaceTests.asyncTearDown
    fixture = races.PlaybackGenerationRaceTests.fixture
    until = races.PlaybackGenerationRaceTests.until
    run_player = races.PlaybackGenerationRaceTests.run_player

    async def adjust(self, player, voice, kind, value):
        if kind == "volume":
            await MusicBot.cmd_volume(player.bot, None, player, str(value))
        elif kind == "speed":
            await MusicBot.cmd_speed(player.bot, None, voice.guild, player, str(value))
        else:
            await MusicBot.cmd_seek(player.bot, None, voice.guild, player, [], str(value))

    async def test_repeated_volume_speed_and_seek_during_rebuild(self):
        for paused in (False, True):
            with self.subTest(paused=paused):
                player, entry, voice = self.fixture()
                await self.run_player(player)
                if paused:
                    player.pause()
                old_after = voice.play.call_args.kwargs["after"]
                await self.adjust(player, voice, "seek", 30)
                old_after(None)
                self.assertIsNone(player.current_entry)
                entered, release = asyncio.Event(), asyncio.Event()
                player.bot.config.use_opus_probe = True
                entry.probed_codec = entry.probed_bitrate = None

                async def probe(*args, **kwargs):
                    if not entered.is_set():
                        entered.set()
                        await release.wait()
                    return "opus", 128

                with patch.object(self.opus, "probe", side_effect=probe):
                    player.play(_continue=True)
                    await asyncio.wait_for(entered.wait(), 1)
                    for kind, value in [("volume", 40), ("speed", 1.25),
                                        ("seek", 60), ("volume", 75), ("speed", 1.0)]:
                        await self.adjust(player, voice, kind, value)
                    await self.until(lambda: voice.play.call_count == 2)
                self.assertIs(player.current_entry, entry)
                self.assertEqual(player.progress, 60)
                self.assertEqual(player.is_paused, paused)
                self.assertEqual(player.volume, .75)
                self.assertEqual(entry.playback_speed, 1.0)
                self.assertNotIn("atempo=", entry.aoptions)
                self.assertEqual(len(player.playlist.entries), 1)
                self.assertNotIn(entry, player.playlist.entries)
                player.kill()


class RealOpusProbeTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/ffprobe required")
    async def test_real_player_copy_and_filtered_encoding_produce_packets(self):
        import musicbot.player as runtime
        import discord
        from ctypes.util import find_library

        if not discord.opus.is_loaded():
            discord.opus.load_opus(find_library("opus") or "libopus.so.0")

        helper = loudness.RealModuleLoudnessTests()
        helper.setUp()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.ogg"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            "sine=frequency=440:duration=1", "-ar", "48000", "-ac", "2",
                            "-c:a", "libopus", str(path)], check=True, capture_output=True)
            for eq, volume, speed in [(False, 1.0, 1.0), (False, .25, 1.0),
                                       (False, 1.0, 1.25), (True, 1.0, 1.0),
                                       (True, .25, 1.25)]:
                with self.subTest(eq=eq, volume=volume, speed=speed):
                    entry = helper.entry()
                    entry.filename = str(path)
                    entry.set_playback_speed(speed)
                    player = loudness.FakePlayer(entry, eq=eq, probe=True, volume=volume)
                    with patch.multiple(runtime, log=loudness.FakeLog(), Thread=loudness.FakeThread,
                                        SourcePlaybackCounter=loudness.FakePlaybackCounter):
                        await runtime.MusicPlayer._play(player)
                    source = player.voice_client.last.source
                    try:
                        args = source._process.args
                        codec = args[args.index("-c:a") + 1]
                        self.assertEqual(codec, "copy" if not eq and volume == speed == 1.0 else "libopus")
                        # OggStream exposes the container's identification and
                        # comment packets before the first audio packet.
                        packet = await asyncio.to_thread(source.read)
                        while packet.startswith((b"OpusHead", b"OpusTags")):
                            packet = await asyncio.to_thread(source.read)
                        self.assertTrue(packet)
                        self.assertEqual(len(discord.opus.Decoder().decode(packet)), 960 * 2 * 2)
                    finally:
                        source.cleanup()


if __name__ == "__main__":
    unittest.main()
