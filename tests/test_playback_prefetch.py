"""First-frame preparation uses real player control flow, without Discord I/O."""
import asyncio
import threading
import time
import unittest
from types import MethodType, SimpleNamespace as NS
from unittest.mock import Mock, patch

from discord import AudioSource, PCMVolumeTransformer
import musicbot.player as runtime
import test_loudness_normalization as loudness


class DelayedOpus(AudioSource):
    delay = .3
    empty = False
    fail = False
    block = False

    def __init__(self, *args, **kwargs):
        type(self).last = self
        self.calls = 0
        self.released = threading.Event()
        self.started = threading.Event()
        self.cleaned = threading.Event()

    @staticmethod
    async def probe(*args, **kwargs):
        return "opus", 128

    def is_opus(self):
        return True

    def read(self):
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            if self.block:
                self.released.wait(2)
            else:
                time.sleep(self.delay)
            if self.fail:
                raise OSError("DemoUser source failed")
            return b"" if self.empty else self.packet
        return self.packet if self.calls == 2 else b""

    packet = b"opus"

    def cleanup(self):
        self.released.set()
        self.cleaned.set()


class DelayedPCM(DelayedOpus):
    packet = bytes(3840)

    def is_opus(self):
        return False


class PrefetchTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, **options):
        helper = loudness.RealModuleLoudnessTests()
        helper.setUp()
        entry = helper.entry()
        player = loudness.FakePlayer(entry, **options)
        player._kill_current_player = MethodType(runtime.MusicPlayer._kill_current_player, player)
        player._preparing_source = None
        player.voice_client.stop = Mock()
        player.voice_client.play = Mock()
        self.errors = []
        old_emit = player.emit

        def emit(event, **data):
            old_emit(event, **data)
            if event == "error":
                self.errors.append(data["ex"])
        player.emit = emit
        return player, entry

    async def run_player(self, player):
        with patch.multiple(runtime, log=loudness.FakeLog(), Thread=loudness.FakeThread,
                            FFmpegOpusAudio=DelayedOpus, FFmpegPCMAudio=DelayedPCM):
            await runtime.MusicPlayer._play(player)

    async def test_300ms_first_packet_ready_before_voice_play_in_all_source_modes(self):
        modes = [
            dict(opus=True, probe=True, eq=False),
            dict(opus=True, probe=False, eq=False),
            dict(opus=True, probe=False, eq=True),
            dict(opus=False, probe=False, eq=True),
        ]
        for options in modes:
            with self.subTest(**options):
                player, entry = self.fixture(**options)
                if options["eq"] and options["opus"]:
                    entry.set_audio_filter("loudnorm", "I=-16:measured_I=-19:measured_LRA=3")
                ticks = 0
                running = True

                async def heartbeat():
                    nonlocal ticks
                    while running:
                        ticks += 1
                        await asyncio.sleep(.01)

                packets = []
                def play(source, after):
                    raw = source._source
                    if isinstance(raw, PCMVolumeTransformer):
                        raw = raw.original
                    self.assertTrue(raw.started.is_set())
                    self.assertEqual(raw.calls, 1)
                    self.assertEqual(source.frames, 0)
                    self.assertEqual(source.is_opus(), options["opus"])
                    packets.extend([source.read(), source.read(), source.read()])
                    self.assertEqual(source.frames, 2)
                    self.assertAlmostEqual(source.progress, .04)
                player.voice_client.play.side_effect = play
                beat = asyncio.create_task(heartbeat())
                start = time.perf_counter()
                try:
                    await self.run_player(player)
                finally:
                    running = False
                    await beat
                    if player._source:
                        player._source.cleanup()
                self.assertGreaterEqual(time.perf_counter() - start, .29)
                self.assertGreater(ticks, 5)
                self.assertTrue(packets[0])
                self.assertEqual(packets[0], packets[1])
                self.assertEqual(packets[2], b"")
                player.voice_client.play.assert_called_once()
                self.assertEqual(self.errors, [])

    async def test_timeout_uses_error_path_and_cleans_blocked_source(self):
        player, _ = self.fixture(opus=True)
        with patch.object(DelayedOpus, "block", True), patch.object(runtime, "FIRST_FRAME_TIMEOUT", .03):
            await self.run_player(player)
        player.voice_client.play.assert_not_called()
        self.assertEqual(len(self.errors), 1)
        self.assertIsInstance(self.errors[0], TimeoutError)
        self.assertIsNone(player._preparing_source)
        self.assertIn("error", player.events)
        self.assertTrue(player.is_stopped)
        self.assertTrue(await asyncio.to_thread(DelayedOpus.last.cleaned.wait, .5))

    async def test_empty_and_read_error_use_error_path(self):
        for kind in ("empty", "fail"):
            with self.subTest(kind=kind):
                player, _ = self.fixture(opus=True)
                with patch.object(DelayedOpus, kind, True), patch.object(DelayedOpus, "delay", 0):
                    await self.run_player(player)
                player.voice_client.play.assert_not_called()
                self.assertEqual(len(self.errors), 1)

    async def test_stop_during_prefetch_does_not_start_stale_audio(self):
        player, _ = self.fixture(opus=True)
        task = asyncio.create_task(self.run_player(player))
        async with asyncio.timeout(1):
            while player._preparing_source is None:
                if task.done():
                    await task
                await asyncio.sleep(.001)
        counter = player._preparing_source
        runtime.MusicPlayer.stop(player)
        await task
        player.voice_client.play.assert_not_called()
        self.assertTrue(await asyncio.to_thread(counter._source.cleaned.wait, .5))
        self.assertEqual(self.errors, [])

    async def test_skip_during_prefetch_continues_to_next_queued_entry(self):
        player, _ = self.fixture(opus=True)
        player.play = Mock()
        task = asyncio.create_task(self.run_player(player))
        async with asyncio.timeout(1):
            while player._preparing_source is None:
                if task.done():
                    await task
                await asyncio.sleep(.001)
        runtime.MusicPlayer.skip(player)
        await task
        player.voice_client.play.assert_not_called()
        player.play.assert_called_once_with(_continue=True)

    async def test_task_cancellation_cleans_source_without_playing(self):
        player, _ = self.fixture(opus=True)
        task = asyncio.create_task(self.run_player(player))
        async with asyncio.timeout(1):
            while player._preparing_source is None:
                if task.done():
                    await task
                await asyncio.sleep(.001)
        counter = player._preparing_source
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(await asyncio.to_thread(counter._source.cleaned.wait, .5))
        player.voice_client.play.assert_not_called()

    async def test_paused_seek_rebuild_prereads_and_keeps_pause(self):
        player, entry = self.fixture(opus=False)
        player._pending_seek = dict(entry=entry, paused=True)
        entry.set_start_time(20)
        with patch.object(DelayedPCM, "delay", 0):
            await self.run_player(player)
        self.assertTrue(player.is_paused)
        self.assertEqual(player._source.frames, 0)
        self.assertEqual(player._source.progress, 20)
        player._source.cleanup()
