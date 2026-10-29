"""Regression coverage for mid-playback FFmpeg stalls.

The producer simulates a blocking FFmpeg read; the consumer simulates Discord's
20 ms audio clock. No voice connection or external media is required.
"""
import asyncio
import threading
import time
import unittest
from unittest.mock import patch

from discord import AudioSource
import musicbot.player as runtime


class PacketSource(AudioSource):
    def __init__(self, *, total=100, stall_at=None, stall_seconds=0, block=False):
        self.total = total
        self.stall_at = stall_at
        self.stall_seconds = stall_seconds
        self.block = block
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()
        self.entered = threading.Event()
        self.release = threading.Event()

    def read(self):
        with self.lock:
            self.calls += 1
            i = self.calls
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if i == self.stall_at:
                self.entered.set()
                if self.block:
                    if not self.release.wait(2):
                        raise TimeoutError("Test did not release the producer")
                elif self.stall_seconds:
                    time.sleep(self.stall_seconds)
            return bytes([i % 256]) if i <= self.total else b""
        finally:
            with self.lock:
                self.active -= 1

    def cleanup(self):
        self.release.set()


class OpusPackets(PacketSource):
    def is_opus(self):
        return True


class ContinuousPlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def test_midplay_300ms_stall_is_absorbed(self):
        source = PacketSource(total=100, stall_at=25, stall_seconds=.30)
        counter = runtime.SourcePlaybackCounter(source, continuous=True)
        try:
            await counter.prepare()
            self.assertEqual(source.calls, runtime.STARTUP_BUFFER_FRAMES)
            self.assertEqual(counter.frames, 0)
            counter.start_streaming()
            self.assertTrue(await asyncio.to_thread(source.entered.wait, 1))
            # The producer has already queued 24 frames, sufficient to hide
            # a 300 ms stall while Discord sends one packet every 20 ms.
            packets = []
            for _ in range(20):
                packets.append(counter.read())
                await asyncio.sleep(.02)
            self.assertEqual(packets, [bytes([i]) for i in range(1, 21)])
            self.assertEqual(counter.underrun_frames, 0)
            self.assertEqual(source.max_active, 1)
        finally:
            counter.cleanup()
            self.assertTrue(await asyncio.to_thread(counter._worker_done.wait, 1))

    async def test_empty_live_buffer_returns_pcm_silence_without_blocking(self):
        source = PacketSource(stall_at=11, block=True)
        counter = runtime.SourcePlaybackCounter(source, continuous=True)
        try:
            await counter.prepare()
            counter.start_streaming()
            self.assertTrue(await asyncio.to_thread(source.entered.wait, 1))
            self.assertEqual(
                [counter.read() for _ in range(10)],
                [bytes([i]) for i in range(1, 11)],
            )
            started = time.perf_counter()
            self.assertEqual(counter.read(), bytes(3840))
            self.assertLess(time.perf_counter() - started, .05)
            self.assertEqual(counter.frames, 10)
            self.assertEqual(counter.underrun_frames, 1)
            self.assertEqual(source.max_active, 1)
            source.release.set()
            await asyncio.sleep(.05)
            self.assertEqual(counter.read(), b"\x0b")
        finally:
            counter.cleanup()
            self.assertTrue(await asyncio.to_thread(counter._worker_done.wait, 1))

    async def test_empty_live_opus_buffer_returns_valid_silence(self):
        source = OpusPackets(stall_at=11, block=True)
        with patch.object(runtime, "FFmpegOpusAudio", OpusPackets):
            counter = runtime.SourcePlaybackCounter(source, continuous=True)
        try:
            await counter.prepare()
            counter.start_streaming()
            self.assertTrue(await asyncio.to_thread(source.entered.wait, 1))
            for _ in range(10):
                counter.read()
            self.assertTrue(counter.is_opus())
            self.assertEqual(counter.read(), runtime.OPUS_SILENCE)
            self.assertEqual(counter.frames, 10)
            self.assertEqual(counter.underrun_frames, 1)
        finally:
            counter.cleanup()
            self.assertTrue(await asyncio.to_thread(counter._worker_done.wait, 1))

    async def test_short_track_ends_without_extra_silence(self):
        source = PacketSource(total=3)
        counter = runtime.SourcePlaybackCounter(source, continuous=True)
        try:
            await counter.prepare()
            counter.start_streaming()
            self.assertEqual([counter.read() for _ in range(3)], [b"\x01", b"\x02", b"\x03"])
            self.assertEqual(counter.read(), b"")
            self.assertEqual(counter.underrun_frames, 0)
        finally:
            counter.cleanup()
            self.assertTrue(await asyncio.to_thread(counter._worker_done.wait, 1))

    async def test_real_discord_sender_no_catch_up_burst(self):
        """Exercise discord.py's actual AudioPlayer clock without Discord I/O."""
        from discord.player import AudioPlayer

        async def run_sender(continuous):
            source = PacketSource(total=55, stall_at=25, stall_seconds=.30)
            counter = runtime.SourcePlaybackCounter(source, continuous=continuous)
            await counter.prepare()
            timestamps = []
            errors = []

            class FakeVoice:
                def is_connected(self):
                    return True

                def send_audio_packet(self, data, *, encode):
                    timestamps.append(time.perf_counter())

            with patch.object(AudioPlayer, "_speak"), patch.object(
                AudioPlayer, "send_silence"
            ):
                sender = AudioPlayer(counter, FakeVoice(), after=errors.append)
                counter.start_streaming()
                sender.start()
                await asyncio.to_thread(sender.join, 4)
                if sender.is_alive():
                    sender.stop()
                    counter.cleanup()
                self.assertFalse(sender.is_alive(), "AudioPlayer did not finish")
            self.assertEqual(errors, [None])
            self.assertEqual(len(timestamps), 55)
            self.assertTrue(await asyncio.to_thread(counter._worker_done.wait, 1))
            return [b - a for a, b in zip(timestamps, timestamps[1:])]

        baseline = await run_sender(False)
        buffered = await run_sender(True)
        # The old synchronous read catches up with several near-zero sleeps
        # after the 300 ms stall. The continuous producer prevents that burst.
        self.assertGreaterEqual(sum(gap < .005 for gap in baseline), 3)
        self.assertLessEqual(sum(gap < .005 for gap in buffered), 1)

    async def test_producer_never_exceeds_bounded_buffer(self):
        source = PacketSource(total=200)
        counter = runtime.SourcePlaybackCounter(source, continuous=True)
        try:
            await counter.prepare()
            counter.start_streaming()
            await asyncio.sleep(.05)
            self.assertLessEqual(source.calls, runtime.CONTINUOUS_BUFFER_FRAMES)
            self.assertEqual(source.max_active, 1)
        finally:
            counter.cleanup()
            self.assertTrue(await asyncio.to_thread(counter._worker_done.wait, 1))


if __name__ == "__main__":
    unittest.main()
