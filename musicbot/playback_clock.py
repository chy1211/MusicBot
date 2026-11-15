"""Opt-in discord.py 2.7.1 AudioPlayer with bounded packet pacing.

The upstream _run() finalizer, source lock, pause/resume and after callback
remain inherited. A long source-read/GC stall must never cause a burst of
back-to-back packets. Each next send is paced from the *actual previous send
start*, not from a forever-accumulating absolute song clock.

The MIT License (MIT)
Copyright (c) 2015-present Rapptz

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included
in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

import time

import discord
from discord.enums import SpeakingState
from discord.player import AudioPlayer


class RealigningAudioPlayer(AudioPlayer):
    LATE_FRAMES = 3

    def _reset_source_timing(self):
        monitor = getattr(self.source, "monitor", None)
        if monitor is not None:
            monitor.reset_timing()

    def _do_run(self):
        self.loops = 0
        self._start = time.perf_counter()
        next_send = self._start
        self.realignments = 0
        client = self.client
        self._speak(SpeakingState.voice)

        while not self._end.is_set():
            if not self._resumed.is_set():
                self.send_silence()
                self._resumed.wait()
                if self._end.is_set():
                    break
                self._reset_source_timing()
                next_send = time.perf_counter()
                continue

            data = self.source.read()
            if not data:
                if self._current_error is None:
                    self._current_error = getattr(self.source, "_current_error", None)
                self.stop()
                break

            if not client.is_connected():
                connected = client.wait_until_connected(client.timeout)
                if self._end.is_set() or not connected:
                    return
                self._speak(SpeakingState.voice)
                self.loops = 0
                next_send = time.perf_counter()
                self._reset_source_timing()

            now = time.perf_counter()
            if now - next_send > self.LATE_FRAMES * self.DELAY:
                self.realignments += 1
                next_send = now
            if now < next_send:
                time.sleep(next_send - now)

            send_started = time.perf_counter()
            client.send_audio_packet(data, encode=not self.source.is_opus())
            self.loops += 1
            # Never accumulate missed deadlines. This keeps the normal 20ms
            # cadence without adding the source-read time on each frame.
            next_send = send_started + self.DELAY

        if client.is_connected():
            self.send_silence()


def play_realigning(client, source, *, after=None):
    """Equivalent to default VoiceClient.play with a version-gated player."""
    if discord.__version__ != "2.7.1":
        raise RuntimeError("PlaybackClockRealign requires audited discord.py 2.7.1")
    if not client.is_connected():
        raise discord.ClientException("Not connected to voice.")
    if client.is_playing():
        raise discord.ClientException("Already playing audio.")
    if not isinstance(source, discord.AudioSource):
        raise TypeError("source must be an AudioSource")
    if not source.is_opus():
        client.encoder = discord.opus.Encoder()
    client._player = RealigningAudioPlayer(source, client, after=after)
    client._player.start()
