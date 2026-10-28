"""Startup-buffer preparation uses real player control flow, without Discord I/O."""
import asyncio
import json
import logging
import threading
import time
import unittest
from types import MethodType, SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from discord import AudioSource, ClientException, PCMVolumeTransformer
import musicbot.player as runtime
from musicbot.playlist import Playlist
import test_loudness_normalization as loudness

# The application registers this custom level at startup; standalone tests do not.
logging.Logger.noise = logging.Logger.debug


class DelayedOpus(AudioSource):
    delay = .3
    empty = False
    fail = False
    block = False
    packets = 2

    def __init__(self, *args, **kwargs):
        type(self).last = self
        self.stderr = kwargs.get("stderr")
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
        return self.packet if self.calls <= self.packets else b""

    packet = b"opus"

    def cleanup(self):
        self.released.set()
        self.cleaned.set()


class DelayedPCM(DelayedOpus):
    packet = bytes(3840)

    def is_opus(self):
        return False


class PrefetchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        log_patch = patch.object(runtime, "log", loudness.FakeLog())
        log_patch.start()
        self.addCleanup(log_patch.stop)

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
                    self.assertEqual(raw.calls, 3)  # Two packets, then EOF during preparation.
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


    async def test_volume_seek_and_restart_rebuilds_fill_buffer_in_all_modes(self):
        modes = [
            dict(opus=True, probe=True, eq=False),
            dict(opus=True, probe=False, eq=False),
            dict(opus=True, probe=False, eq=True),
            dict(opus=False, probe=False, eq=True),
        ]
        for options in modes:
            for measured in ((False, True) if options['eq'] else (False,)):
                with self.subTest(**options, measured=measured):
                    player, entry = self.fixture(**options)
                    if measured:
                        entry.set_audio_filter('loudnorm', 'I=-16:measured_I=-19:measured_LRA=3')
                    for volume, position in ((.15, 0), (.35, 0), (.35, 20), (.35, 0)):
                        previous = player._source if hasattr(player, '_source') else None
                        if previous:
                            previous.cleanup()
                        player.volume = volume
                        entry.set_start_time(position)
                        with patch.object(DelayedOpus, 'delay', 0), patch.object(DelayedOpus, 'packets', runtime.STARTUP_BUFFER_FRAMES + 2):
                            await self.run_player(player)
                        counter = player._source
                        self.assertIsNot(counter, previous)
                        raw = counter._source
                        if isinstance(raw, PCMVolumeTransformer):
                            self.assertEqual(raw.volume, volume)
                            raw = raw.original
                        self.assertEqual(raw.calls, runtime.STARTUP_BUFFER_FRAMES)
                        self.assertEqual(counter.frames, 0)
                        self.assertEqual(counter.progress, position)
                        self.assertTrue(counter.read())
                        self.assertEqual(raw.calls, runtime.STARTUP_BUFFER_FRAMES)
                        self.assertEqual(counter.frames, 1)
                    player._source.cleanup()
                    self.assertEqual(self.errors, [])


class PacketSource(AudioSource):
    """Ordered packets with observable read ownership and optional stalls."""
    def __init__(self, count=40, delays=None, block_at=None, fail_at=None):
        self.count = count
        self.delays = delays or {}
        self.block_at = block_at
        self.fail_at = fail_at
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()
        self.started = threading.Event()
        self.released = threading.Event()

    def read(self):
        with self.lock:
            self.calls += 1
            index = self.calls
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if index == self.block_at:
                self.started.set()
                if not self.released.wait(2):
                    raise RuntimeError("Test source was not released")
            time.sleep(self.delays.get(index, 0))
            if index == self.fail_at:
                raise OSError("Synthetic packet failure")
            return bytes([index]) if index <= self.count else b""
        finally:
            with self.lock:
                self.active -= 1

    def cleanup(self):
        self.released.set()


class StartupBufferTests(unittest.IsolatedAsyncioTestCase):
    setUp = PrefetchTests.setUp

    async def test_second_and_third_300ms_packets_are_ready_before_playback(self):
        source = PacketSource(delays={2: .3, 3: .3})
        counter = runtime.SourcePlaybackCounter(source)
        started = time.perf_counter()
        await counter.prepare()
        self.assertGreaterEqual(time.perf_counter() - started, .59)
        self.assertEqual((counter.frames, counter.progress), (0, 0))
        started = time.perf_counter()
        packets = [counter.read() for _ in range(runtime.STARTUP_BUFFER_FRAMES)]
        self.assertLess(time.perf_counter() - started, .05)
        self.assertEqual(packets, [bytes([i]) for i in range(1, runtime.STARTUP_BUFFER_FRAMES + 1)])
        self.assertEqual(source.calls, runtime.STARTUP_BUFFER_FRAMES)
        self.assertEqual(counter.frames, runtime.STARTUP_BUFFER_FRAMES)
        self.assertAlmostEqual(counter.progress, runtime.STARTUP_BUFFER_FRAMES * .02)

    async def test_sixth_300ms_packet_is_ready_before_playback(self):
        self.assertEqual(runtime.STARTUP_BUFFER_FRAMES, 10)
        source = PacketSource(delays={6: .3})
        counter = runtime.SourcePlaybackCounter(source)
        started = time.perf_counter()
        await counter.prepare()
        self.assertGreaterEqual(time.perf_counter() - started, .29)
        self.assertEqual((counter.frames, counter.progress), (0, 0))
        started = time.perf_counter()
        packets = [counter.read() for _ in range(runtime.STARTUP_BUFFER_FRAMES)]
        self.assertLess(time.perf_counter() - started, .05)
        self.assertEqual(packets, [bytes([i]) for i in range(1, runtime.STARTUP_BUFFER_FRAMES + 1)])
        self.assertEqual(source.calls, runtime.STARTUP_BUFFER_FRAMES)
        self.assertEqual(counter.frames, runtime.STARTUP_BUFFER_FRAMES)
        self.assertAlmostEqual(counter.progress, runtime.STARTUP_BUFFER_FRAMES * .02)

    async def test_five_packet_song_shorter_than_buffer_preserves_order_and_eof(self):
        source = PacketSource(count=5)
        counter = runtime.SourcePlaybackCounter(source, start_time=12, playback_speed=2)
        with patch.object(runtime, "STARTUP_BUFFER_FRAMES", 10):
            await counter.prepare()
        self.assertEqual((counter.frames, counter.session_progress, counter.progress), (0, 0, 12))
        self.assertEqual([counter.read() for _ in range(5)], [bytes([i]) for i in range(1, 6)])
        self.assertEqual((counter.read(), counter.read()), (b"", b""))
        self.assertEqual(source.calls, 6)
        self.assertEqual(counter.frames, 5)
        self.assertAlmostEqual(counter.progress, 12.2)

    async def test_partial_timeout_plays_buffer_then_retains_inflight_packet(self):
        source = PacketSource(block_at=2)
        counter = runtime.SourcePlaybackCounter(source)
        self.addCleanup(source.cleanup)
        with patch.object(runtime, "log") as logger:
            await counter.prepare(timeout=.03)
        logger.debug.assert_called_once()
        self.assertEqual(counter.frames, 0)
        self.assertTrue(source.started.is_set())
        started = time.perf_counter()
        self.assertEqual(counter.read(), b"\x01")
        self.assertLess(time.perf_counter() - started, .02)
        pending = asyncio.create_task(asyncio.to_thread(counter.read))
        await asyncio.sleep(.02)
        self.assertFalse(pending.done())
        self.assertEqual(source.calls, 2)
        source.released.set()
        self.assertEqual(await pending, b"\x02")
        self.assertEqual(counter.read(), b"\x03")
        self.assertEqual((source.max_active, counter.frames), (1, 3))

    async def test_all_packets_share_one_timeout(self):
        source = PacketSource(delays={1: .05, 2: .05, 3: .05})
        counter = runtime.SourcePlaybackCounter(source)
        started = time.perf_counter()
        await counter.prepare(timeout=.08)
        self.assertLess(time.perf_counter() - started, .13)
        self.assertEqual(counter.frames, 0)
        self.assertEqual(counter.read(), b"\x01")
        self.assertEqual(await asyncio.to_thread(counter.read), b"\x02")
        self.assertTrue(counter._prefetch_done.is_set())
        self.assertEqual(source.calls, 2)

    async def test_no_packets_timeout_raises_and_stops_prefetch(self):
        source = PacketSource(block_at=1)
        counter = runtime.SourcePlaybackCounter(source)
        self.addCleanup(source.cleanup)
        with self.assertRaises(TimeoutError):
            await counter.prepare(timeout=.03)
        source.released.set()
        self.assertTrue(await asyncio.to_thread(counter._prefetch_done.wait, .5))
        self.assertEqual(source.calls, 1)
        self.assertEqual(counter.frames, 0)

    async def test_partial_timeout_eof_and_failure_are_not_lost(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                source = PacketSource(count=1, block_at=2, fail_at=2 if fail else None)
                counter = runtime.SourcePlaybackCounter(source)
                self.addCleanup(source.cleanup)
                await counter.prepare(timeout=.03)
                self.assertEqual(counter.read(), b"\x01")
                source.released.set()
                if fail:
                    with self.assertRaises(OSError):
                        await asyncio.to_thread(counter.read)
                else:
                    self.assertEqual(await asyncio.to_thread(counter.read), b"")
                self.assertEqual(counter.frames, 1)
                self.assertEqual(source.max_active, 1)


class PartialTimeoutPlayerTests(unittest.IsolatedAsyncioTestCase):
    setUp = PrefetchTests.setUp
    fixture = PrefetchTests.fixture
    run_player = PrefetchTests.run_player
    async def test_partial_timeout_starts_voice_without_error(self):
        player, _ = self.fixture(opus=True)
        original = DelayedOpus.read
        def delayed_second(source):
            if source.calls == 1:
                source.released.wait(2)
            return original(source)
        player.voice_client.play.side_effect = lambda source, **kw: self.assertEqual(source.read(), b"opus")
        with patch.object(DelayedOpus, "read", delayed_second), patch.object(DelayedOpus, "delay", 0), patch.object(runtime, "FIRST_FRAME_TIMEOUT", .03):
            await self.run_player(player)
        player.voice_client.play.assert_called_once()
        self.assertEqual(self.errors, [])
        self.assertEqual(player._source.frames, 1)
        player._source.cleanup()
        self.assertTrue(await asyncio.to_thread(player._source._prefetch_done.wait, .5))


class DisconnectPlaybackTests(unittest.IsolatedAsyncioTestCase):
    setUp = PrefetchTests.setUp
    run_player = PrefetchTests.run_player

    def fixture(self):
        helper = loudness.RealModuleLoudnessTests()
        helper.setUp()
        entry = helper.entry()
        entry._is_downloaded = True
        entry._download = AsyncMock()
        following = helper.entry()
        following.info["title"] = "Following queued track"
        following.filename = "/tmp/following.ogg"
        following._is_downloaded = True
        voice = Mock(channel=NS(bitrate=128000), guild=NS(id=123))
        voice.is_connected.return_value = True
        self.tasks = []
        self.serialized = []

        def create_task(coro, **kwargs):
            task = asyncio.create_task(coro, **kwargs)
            self.tasks.append(task)
            return task

        bot = NS(loop=asyncio.get_running_loop(), create_task=create_task,
                 config=NS(default_volume=.15, use_opus_audio=True,
                           use_opus_probe=False, use_experimental_equalization=False,
                           pre_download_next_song=False))
        playlist = Playlist(bot)
        playlist.entries.extend((entry, following))
        playlist.get_next_entry = AsyncMock(wraps=playlist.get_next_entry)
        playlist.emit = Mock()
        player = runtime.MusicPlayer(bot, voice, playlist)
        bot.serialize_queue = AsyncMock(
            side_effect=lambda guild: self.serialized.append(player.serialize()))
        player.emit = Mock()
        return player, entry, voice

    def seed_seek(self, player, entry):
        player._pending_seek = dict(entry=entry, position=20, paused=True)
        player._current_entry = entry
        player._source = Mock()

    def assert_abandoned(self, player, *, dead=False, restored=True):
        self.assertEqual(player.state, runtime.MusicPlayerState.DEAD if dead
                         else runtime.MusicPlayerState.STOPPED)
        for name in ('_pending_seek', '_current_entry', '_current_player',
                     '_source', '_preparing_source', '_stderr_future'):
            self.assertIsNone(getattr(player, name), name)
        self.assertFalse(player._skip_preparing)
        player.emit.assert_not_called()
        self.assertFalse(player._play_lock.locked())
        player.playlist.emit.assert_not_called()
        if dead or not restored:
            player.bot.serialize_queue.assert_not_awaited()
            self.assertEqual(self.serialized, [])
        else:
            player.bot.serialize_queue.assert_awaited_once()
            snapshot = json.loads(self.serialized[-1])
            self.assertIsNone(snapshot["data"]["current_entry"]["entry"])
            queued = snapshot["data"]["entries"]["data"]["entries"]
            self.assertEqual(queued[0]["data"]["info"]["title"], "DemoUser track")
            self.assertTrue(queued[0]["data"]["downloaded"])
            self.assertEqual(queued[1]["data"]["info"]["title"], "Following queued track")

    async def assert_can_restart(self, player, entry, voice):
        # The real deque must supply the restored entry before the following song.
        self.assertEqual(list(player.playlist.entries)[0], entry)
        self.assertEqual(len(player.playlist.entries), 2)
        player.voice_client = voice
        voice.is_connected.return_value = True
        voice.play.reset_mock(side_effect=True)
        with patch.multiple(runtime, Thread=loudness.FakeThread,
                            FFmpegOpusAudio=DelayedOpus), patch.object(DelayedOpus, 'delay', 0):
            player.play()
            await self.tasks[-1]
        self.addCleanup(player._source.cleanup)
        voice.play.assert_called_once()
        self.assertEqual(player.state, runtime.MusicPlayerState.PLAYING)
        self.assertIs(player.current_entry, entry)
        self.assertFalse(player.is_paused)
        self.assertIsNone(player._pending_seek)
        player.emit.assert_called_once_with('play', player=player, entry=entry)
        self.assertEqual(len(player.playlist.entries), 1)
        self.assertEqual(player.playlist.peek().title, "Following queued track")
        entry._download.assert_not_awaited()
        player.playlist.emit.assert_not_called()

    async def test_disconnect_during_download_does_not_build_source(self):
        for change in ('disconnect', 'missing_voice', 'dead'):
            with self.subTest(change=change):
                player, entry, voice = self.fixture()
                self.seed_seek(player, entry)

                get_next_entry = player.playlist.get_next_entry

                async def download():
                    result = await get_next_entry()
                    if change == 'dead':
                        player.kill()
                    elif change == 'missing_voice':
                        player.voice_client = None
                    else:
                        voice.is_connected.return_value = False
                    return result

                player.playlist.get_next_entry = AsyncMock(side_effect=download)
                with patch.object(runtime, 'FFmpegOpusAudio') as source:
                    await runtime.MusicPlayer._play(player)
                source.assert_not_called()
                voice.play.assert_not_called()
                self.assert_abandoned(player, dead=change == 'dead')
                if change == 'dead':
                    self.assertNotIn(entry, player.playlist.entries)
                else:
                    player.playlist.get_next_entry = get_next_entry
                    await self.assert_can_restart(player, entry, voice)

    async def test_disconnect_during_prepare_cleans_source_without_play_event(self):
        for change in ('disconnect', 'missing_voice', 'dead'):
            with self.subTest(change=change):
                player, entry, voice = self.fixture()
                self.seed_seek(player, entry)
                with patch.object(DelayedOpus, 'block', True):
                    task = asyncio.create_task(self.run_player(player))
                    try:
                        async with asyncio.timeout(1):
                            while (player._preparing_source is None
                                   or not player._preparing_source._source.started.is_set()):
                                if task.done():
                                    await task
                                await asyncio.sleep(.001)
                        raw = player._preparing_source._source
                        if change == 'dead':
                            player.kill()
                        elif change == 'missing_voice':
                            player.voice_client = None
                        else:
                            voice.is_connected.return_value = False
                    finally:
                        if hasattr(DelayedOpus, 'last'):
                            DelayedOpus.last.released.set()
                        await task
                self.assertTrue(await asyncio.to_thread(raw.cleaned.wait, .5))
                self.assertTrue(raw.stderr.closed)
                voice.play.assert_not_called()
                self.assert_abandoned(player, dead=change == 'dead')
                if change != 'dead':
                    await self.assert_can_restart(player, entry, voice)
                else:
                    self.assertNotIn(entry, player.playlist.entries)

    async def test_voice_play_disconnect_race_cleans_source_and_resets_seek(self):
        player, entry, voice = self.fixture()
        self.seed_seek(player, entry)
        voice.play.side_effect = ClientException('Not connected to voice.')
        with patch.object(DelayedOpus, 'delay', 0):
            await self.run_player(player)
        voice.play.assert_called_once()
        self.assertTrue(await asyncio.to_thread(DelayedOpus.last.cleaned.wait, .5))
        self.assertTrue(DelayedOpus.last.stderr.closed)
        self.assert_abandoned(player)
        await self.assert_can_restart(player, entry, voice)

    async def test_connected_playback_keeps_source_and_emits_play(self):
        player, entry, voice = self.fixture()
        with patch.object(DelayedOpus, 'delay', 0):
            await self.run_player(player)
        self.addCleanup(player._source.cleanup)
        source = player._source
        self.assertFalse(DelayedOpus.last.cleaned.is_set())
        voice.play.assert_called_once_with(source, after=player._playback_finished)
        self.assertIs(player._current_player, voice)
        self.assertIs(player.current_entry, entry)
        self.assertEqual(player.state, runtime.MusicPlayerState.PLAYING)
        self.assertEqual(source.frames, 0)
        self.assertIsNone(player._preparing_source)
        self.assertIsNone(player._pending_seek)
        player.emit.assert_called_once_with('play', player=player, entry=entry)

    async def test_other_play_errors_still_propagate(self):
        for error in (TypeError('Invalid audio source'),
                      ClientException('Already playing audio.')):
            with self.subTest(error=error):
                player, _, voice = self.fixture()
                voice.play.side_effect = error
                with patch.object(DelayedOpus, 'delay', 0):
                    try:
                        with self.assertRaises(type(error)) as raised:
                            await self.run_player(player)
                        self.assertIs(raised.exception, error)
                        player.emit.assert_not_called()
                    finally:
                        DelayedOpus.last.cleanup()

    async def test_continue_disconnect_restores_selected_next_entry(self):
        player, entry, voice = self.fixture()
        player.state = runtime.MusicPlayerState.PLAYING
        voice.is_connected.return_value = False
        await runtime.MusicPlayer._play(player, _continue=True)
        self.assert_abandoned(player)
        await self.assert_can_restart(player, entry, voice)

    async def test_disconnected_empty_queue_does_not_restore_or_serialize(self):
        player, _, voice = self.fixture()
        player.playlist.entries.clear()
        voice.is_connected.return_value = False
        await runtime.MusicPlayer._play(player)
        self.assert_abandoned(player, restored=False)
        self.assertEqual(list(player.playlist.entries), [])

    async def test_disconnect_after_skip_or_stop_does_not_restore_entry(self):
        for action in ("skip", "stop"):
            with self.subTest(action=action):
                player, entry, voice = self.fixture()
                with patch.object(DelayedOpus, "block", True):
                    task = asyncio.create_task(self.run_player(player))
                    try:
                        async with asyncio.timeout(1):
                            while (player._preparing_source is None
                                   or not player._preparing_source._source.started.is_set()):
                                if task.done():
                                    await task
                                await asyncio.sleep(.001)
                        raw = player._preparing_source._source
                        getattr(player, action)()
                        player.emit.reset_mock()
                        voice.is_connected.return_value = False
                    finally:
                        if hasattr(DelayedOpus, "last"):
                            DelayedOpus.last.released.set()
                        await task
                self.assertTrue(await asyncio.to_thread(raw.cleaned.wait, .5))
                self.assert_abandoned(player, restored=False)
                self.assertNotIn(entry, player.playlist.entries)
                self.assertEqual(player.playlist.peek().title, "Following queued track")


    async def test_dead_during_voice_play_disconnect_does_not_restore(self):
        player, entry, voice = self.fixture()

        def disconnect(source, **kwargs):
            player.kill()
            raise ClientException("Not connected to voice.")

        voice.play.side_effect = disconnect
        with patch.object(DelayedOpus, "delay", 0):
            await self.run_player(player)
        self.assertTrue(await asyncio.to_thread(DelayedOpus.last.cleaned.wait, .5))
        self.assertTrue(DelayedOpus.last.stderr.closed)
        self.assert_abandoned(player, dead=True)
        self.assertNotIn(entry, player.playlist.entries)
