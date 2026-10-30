import asyncio
import io
import json
import logging
import os
import sys
import time
import hashlib
import json
import secrets
from collections import deque
from enum import Enum
from functools import partial
from threading import Condition, Event, Thread
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from discord.player import OPUS_SILENCE

from discord import (
    AudioSource,
    ClientException,
    FFmpegOpusAudio,
    FFmpegPCMAudio,
    PCMVolumeTransformer,
    VoiceClient,
)

from .constants import MUSICBOT_VOICE_MAX_KBITRATE
from .constructs import Serializable, Serializer, SkipState
from .entry import LocalFilePlaylistEntry, StreamPlaylistEntry, URLPlaylistEntry
from .exceptions import FFmpegError, FFmpegWarning
from .lib.event_emitter import EventEmitter
from .loudness import LOUDNORM_TARGET
from .read_cadence_diagnostics import ReadCadenceDiagnostics
from .cadence_layered import LayeredReadCadenceDiagnostics

if TYPE_CHECKING:
    from .bot import MusicBot
    from .playlist import Playlist

    AsyncFuture = asyncio.Future[Any]
else:
    AsyncFuture = asyncio.Future

# Type alias
EntryTypes = Union[URLPlaylistEntry, StreamPlaylistEntry, LocalFilePlaylistEntry]
FFmpegSources = Union[PCMVolumeTransformer[FFmpegPCMAudio], FFmpegOpusAudio]

log = logging.getLogger(__name__)
FIRST_FRAME_TIMEOUT = 10.0
# Buffer the first 10 packets (0.2 s), moving warm-up stalls anywhere in that
# window before the playback clock starts, rather than only packets 2/3.
# Offline measurements at 1 ms/read: N=3 takes ~3.6 ms normally, N=10 ~11.2 ms
# (only ~8 ms more). With packets 2/3 stalled by 200/300/400 ms each, N>=3
# produced zero catch-up sends in every case; N=10 also covers later stalls.
STARTUP_BUFFER_FRAMES = 10
# Keep up to one second of decoded/encoded 20 ms frames ahead of the voice
# sender. Unlike startup-only prefetch, this also covers stalls mid-track.
CONTINUOUS_BUFFER_FRAMES = 50
# Do not play silence indefinitely if FFmpeg stops delivering packets.
MAX_CONSECUTIVE_UNDERRUNS = 500


class MusicPlayerState(Enum):
    STOPPED = 0  # When the player isn't playing anything
    PLAYING = 1  # The player is actively playing music.
    PAUSED = 2  # The player is paused on a song.
    WAITING = (
        3  # The player has finished its song but is still downloading the next one
    )
    DEAD = 4  # The player has been killed.

    def __str__(self) -> str:
        return self.name


class SourcePlaybackCounter(AudioSource):
    def __init__(
        self,
        source: FFmpegSources,
        start_time: float = 0,
        playback_speed: float = 1.0,
        continuous: bool = False,
        cadence: Optional[ReadCadenceDiagnostics] = None,
    ) -> None:
        """
        Manage playback source and attempt to count progress frames used
        to measure playback progress.

        :param: start_time:  A time in seconds that was used in ffmpeg -ss flag.
        """
        # NOTE: PCMVolumeTransformer will let you set any crazy value.
        # But internally it limits between 0 and 2.0.
        self._source = source
        self._prefetched_frames: deque[bytes] = deque()
        self._prefetch_done = Event()
        self._prefetch_done.set()
        self._prefetch_stop = Event()
        self._prefetch_error: Optional[Exception] = None
        self._source_eof = False
        self._num_reads: int = 0
        self._start_time: float = start_time
        self._playback_speed: float = playback_speed
        self._is_opus_audio: bool = isinstance(source, FFmpegOpusAudio)
        self._continuous = continuous
        self._buffer_cond = Condition()
        self._streaming = Event()
        self._worker_done = Event()
        self._underrun_frames = 0
        self._consecutive_underruns = 0
        self._cadence = cadence
        self._cadence_resets: deque[str] = deque(maxlen=8)
        self._cadence_reported = False

    def is_opus(self) -> bool:
        return self._is_opus_audio

    def _prepare_frames(self) -> None:
        """One worker owns all source reads during preparation and playback."""
        try:
            for _ in range(STARTUP_BUFFER_FRAMES):
                if self._prefetch_stop.is_set():
                    break
                frame = self._source.read()
                if not frame:
                    self._source_eof = True
                    break
                with self._buffer_cond:
                    self._prefetched_frames.append(frame)

            # Continuous sources leave the same reader running after playback
            # starts, so an in-flight read can never race with AudioPlayer.read().
            self._prefetch_done.set()
            if not self._continuous or self._source_eof:
                return

            while not self._prefetch_stop.is_set():
                if not self._streaming.wait(0.05):
                    continue
                with self._buffer_cond:
                    while (
                        len(self._prefetched_frames) >= CONTINUOUS_BUFFER_FRAMES
                        and not self._prefetch_stop.is_set()
                    ):
                        self._buffer_cond.wait(0.05)
                    if self._prefetch_stop.is_set():
                        break
                frame = self._source.read()
                if not frame:
                    self._source_eof = True
                    break
                with self._buffer_cond:
                    self._prefetched_frames.append(frame)
        except Exception as exc:
            self._prefetch_error = exc
        finally:
            self._prefetch_done.set()
            self._worker_done.set()

    async def prepare(self, timeout: float = FIRST_FRAME_TIMEOUT) -> None:
        """Buffer startup packets off-loop under one total timeout."""
        self._prefetch_done.clear()
        worker = asyncio.get_running_loop().run_in_executor(None, self._prepare_frames)
        try:
            if self._continuous:
                # The reader stays alive to fill the live buffer. Only wait
                # for the startup window, not for the worker to terminate.
                await asyncio.wait_for(
                    asyncio.to_thread(self._prefetch_done.wait), timeout=timeout
                )
            else:
                await asyncio.wait_for(worker, timeout=timeout)
        except asyncio.TimeoutError:
            if not self._prefetched_frames or not self._continuous:
                self._prefetch_stop.set()
            if not self._prefetched_frames:
                raise
            log.debug(
                "Startup buffer timed out after %.3fs; playing %d prepared frames.",
                timeout, len(self._prefetched_frames),
            )
            return
        except asyncio.CancelledError:
            self._prefetch_stop.set()
            raise
        if self._prefetch_error is not None:
            raise self._prefetch_error
        if not self._prefetched_frames:
            raise FFmpegError("Audio source returned no first frame.")

    def start_streaming(self) -> None:
        """Allow the single producer to refill after VoiceClient.play()."""
        if self._continuous:
            self._streaming.set()

    @property
    def underrun_frames(self) -> int:
        return self._underrun_frames

    def diagnostics(self) -> dict:
        """Small, lock-protected, content-free snapshot for owner-only health UI."""
        with self._buffer_cond:
            return {"buffered_ms": len(self._prefetched_frames) * 20,
                    "capacity_ms": CONTINUOUS_BUFFER_FRAMES * 20 if self._continuous else STARTUP_BUFFER_FRAMES * 20,
                    "underrun_frames": self._underrun_frames,
                    "read_error": type(self._prefetch_error).__name__ if self._prefetch_error else "",
                    "worker_done": self._worker_done.is_set()}

    def _read_frame(self) -> bytes:
        if self._continuous:
            with self._buffer_cond:
                if self._prefetched_frames:
                    frame = self._prefetched_frames.popleft()
                    self._buffer_cond.notify()
                elif self._prefetch_error is not None:
                    raise self._prefetch_error
                elif self._source_eof or self._prefetch_stop.is_set():
                    return b""
                else:
                    self._underrun_frames += 1
                    self._consecutive_underruns += 1
                    if self._consecutive_underruns > MAX_CONSECUTIVE_UNDERRUNS:
                        raise FFmpegError("Audio source stalled for over 10 seconds.")
                    if self._underrun_frames == 1 or self._underrun_frames % 100 == 0:
                        log.warning(
                            "Audio buffer underrun: %d silent frames sent.",
                            self._underrun_frames,
                        )
                    # A 20 ms silence frame prevents blocking Discord's sender
                    # and the subsequent burst of zero-delay catch-up packets.
                    return OPUS_SILENCE if self._is_opus_audio else bytes(3840)
            self._consecutive_underruns = 0
            return frame
        if self._prefetched_frames:
            return self._prefetched_frames.popleft()
        # A timed-out executor read cannot be cancelled. Let its final packet
        # arrive before reading again, preserving order and single-reader access.
        if not self._prefetch_done.is_set():
            self._prefetch_done.wait()
        if self._prefetched_frames:
            return self._prefetched_frames.popleft()
        if self._prefetch_error is not None:
            raise self._prefetch_error
        if self._source_eof:
            return b""
        return self._source.read()

    def read(self) -> bytes:
        # The timestamp is the source-read *invocation*, NOT a UDP send.
        self._drain_cadence_resets()
        cadence = self._cadence
        try:
            started = time.monotonic() if cadence is not None else 0.0
        except Exception:
            self._cadence = cadence = None
            started = 0.0
        underruns = self._underrun_frames
        try:
            res = self._read_frame()
        except BaseException:
            self.reset_cadence('read_error')
            raise  # Never replace a genuine decoder/player failure.
        # Concealment silence is not part of the media timeline.
        if res and self._underrun_frames == underruns:
            self._num_reads += 1
            if cadence is not None:
                try:
                    cadence.observe(started, time.monotonic(), frame=self._num_reads)
                except Exception:
                    self._cadence = None  # Diagnostic failure must not fail playback.
        else:
            self.reset_cadence('eof_or_underrun')  # No cross-boundary episode.
        return res

    def reset_cadence(self, reason: str = 'boundary') -> None:
        # Control callbacks only enqueue; the audio reader owns live counters.
        if self._cadence is not None:
            self._cadence_resets.append(reason)

    def _drain_cadence_resets(self) -> None:
        while self._cadence_resets:
            reason = self._cadence_resets.popleft()
            if self._cadence is not None:
                try:
                    self._cadence.break_sequence(reason)
                except Exception:
                    self._cadence = None

    def cadence_summary(self):
        # Called after AudioPlayer.after(), once reads have finished.
        if self._cadence_reported or self._cadence is None:
            return None
        self._cadence_reported = True
        self.reset_cadence('finished')
        self._drain_cadence_resets()
        if self._cadence is not None:
            return self._cadence.summary()
        return None

    def cleanup(self) -> None:
        log.noise(  # type: ignore[attr-defined]
            "Cleanup got called on the audio source:  %r", self
        )
        self._prefetch_stop.set()
        self._streaming.set()
        with self._buffer_cond:
            self._buffer_cond.notify_all()
        # Unregister only our optional GC callback on all cleanup paths,
        # including a source abandoned before Discord playback began.
        close_monitor = getattr(self._cadence, 'close', None)
        if close_monitor is not None:
            try:
                close_monitor()
            except Exception:
                pass
        self._source.cleanup()

    @property
    def frames(self) -> int:
        """
        Number of read frames since this source was opened.
        This is not the total playback time.
        """
        return self._num_reads

    @property
    def session_progress(self) -> float:
        """
        Like progress but only counts frames from this session.
        Adjusts the estimated time by playback speed.
        """
        return (self._num_reads * 0.02) * self._playback_speed

    @property
    def progress(self) -> float:
        """Get an approximate playback progress time."""
        return self._start_time + self.session_progress


class MusicPlayer(EventEmitter, Serializable):
    def __init__(
        self,
        bot: "MusicBot",
        voice_client: VoiceClient,
        playlist: "Playlist",
    ):
        """
        Manage a MusicPlayer with all its bits and bolts.

        :param: bot:  A MusicBot discord client instance.
        :param: voice_client:  a discord.VoiceClient object used for playback.
        :param: playlist:  a collection of playable entries to be played.
        """
        super().__init__()
        self.bot: MusicBot = bot
        self.loop: asyncio.AbstractEventLoop = bot.loop
        self.loopqueue: bool = False
        self.repeatsong: bool = False
        self.voice_client: VoiceClient = voice_client
        self.playlist: Playlist = playlist
        self.autoplaylist: List[str] = []
        self.state: MusicPlayerState = MusicPlayerState.STOPPED
        self.skip_state: SkipState = SkipState()
        self.karaoke_mode: bool = False
        self.guild_or_net_unavailable: bool = False
        self.paused_auto: bool = False

        self._volume = bot.config.default_volume
        self._play_lock = asyncio.Lock()
        self._play_generation = 0
        self._play_task: Optional[asyncio.Task] = None
        self._play_queued_generation: Optional[int] = None
        # Dashboard hint for the track selected but not yet started.
        self._preparing_entry: Optional[EntryTypes] = None
        self._transitioning_to_next = False
        self._stop_requested = False
        self._current_player: Optional[VoiceClient] = None
        self._current_entry: Optional[EntryTypes] = None
        self._stderr_future: Optional[AsyncFuture] = None

        self._source: Optional[SourcePlaybackCounter] = None
        self._pending_seek = None
        self._preparing_source: Optional[SourcePlaybackCounter] = None
        self._skip_preparing = False

        self.playlist.on("entry-added", self.on_entry_added)
        self.playlist.on("entry-failed", self.on_entry_failed)

    @property
    def volume(self) -> float:
        """Get the volume level as last set by config or command."""
        return self._volume

    @volume.setter
    def volume(self, value: float) -> None:
        """
        Set volume to the given `value` and immediately apply it to any
        active playback source.
        """
        self._volume = value
        if self._source:
            if isinstance(self._source._source, PCMVolumeTransformer):
                self._source._source.volume = value
            # if isinstance(self._source._source, FFmpegOpusAudio):

    def on_entry_added(
        self, playlist: "Playlist", entry: EntryTypes, defer_serialize: bool = False
    ) -> None:
        """
        Event dispatched by Playlist when an entry is added to the queue.
        """
        self.emit(
            "entry-added",
            player=self,
            playlist=playlist,
            entry=entry,
            defer_serialize=defer_serialize,
        )

    def on_entry_failed(self, entry: EntryTypes, error: Exception) -> None:
        """
        Event dispatched by Playlist when an entry failed to ready or play.
        """
        self.emit("error", player=self, entry=entry, ex=error)

    def _invalidate_play_request(self) -> None:
        """Invalidate startup without cancelling the entry's download task."""
        self._play_generation += 1
        task = self._play_task
        self._play_task = None
        self._play_queued_generation = None
        if (task is not None and not task.done() and not task.cancelling()
                and task is not asyncio.current_task()):
            task.cancel()
        self._preparing_source = None
        self._preparing_entry = None
        self._transitioning_to_next = False
        self._skip_preparing = False

    def _clear_pending_seek(self) -> None:
        pending = self._pending_seek
        if pending:
            self.playlist.entries = deque(
                entry for entry in self.playlist.entries
                if entry is not pending["entry"]
            )
        self._pending_seek = None

    def skip(self, *, _seek: bool = False) -> None:
        """Discard the selected track, or restart it for an explicit seek."""
        log.noise("MusicPlayer.skip() is called:  %s", repr(self))  # type: ignore[attr-defined]
        pending = self._play_task
        starting = ((pending is not None and not pending.done())
                    or self._play_queued_generation is not None
                    or self._preparing_source is not None
                    or self._pending_seek is not None)
        self._invalidate_play_request()
        self._stop_requested = False
        if not _seek:
            self._clear_pending_seek()
        # A live VoiceClient finishes through its source-bound callback.
        if self._kill_current_player():
            return
        if starting:
            if not _seek:
                self._current_entry = None
                self._source = None
            self.play(_continue=True)

    def stop(self) -> None:
        """Stop current and pending playback without scheduling another track."""
        log.noise("MusicPlayer.stop() is called:  %s", repr(self))  # type: ignore[attr-defined]
        self._stop_requested = True
        self._invalidate_play_request()
        self._clear_pending_seek()
        self.state = MusicPlayerState.STOPPED
        if not self._kill_current_player():
            self._current_entry = None
            self._source = None
        self.emit("stop", player=self)

    def resume(self) -> None:
        """
        Resume the player audio playback if it was paused and we have a
        VoiceClient playback source.
        If MusicPlayer was paused but the VoiceClient player is missing,
        do something odd and set state to playing but kill the player...
        """
        if self.guild_or_net_unavailable:
            log.warning("Guild or network unavailable, cannot resume playback.")
            return

        log.noise(  # type: ignore[attr-defined]
            "MusicPlayer.resume() is called:  %s", repr(self)
        )
        if self.is_paused and self._current_player:
            reset = getattr(getattr(self, '_source', None), 'reset_cadence', None)
            if reset is not None:
                reset('resume')
            self._current_player.resume()
            self.state = MusicPlayerState.PLAYING
            self.emit("resume", player=self, entry=self.current_entry)
            return

        if self.is_paused and not self._current_player:
            self.state = MusicPlayerState.PLAYING
            self._kill_current_player()
            return

        raise ValueError(f"Cannot resume playback from state {self.state}")

    def pause(self) -> None:
        """
        Suspend player audio playback and emit an event, if the player was playing.
        """
        log.noise(  # type: ignore[attr-defined]
            "MusicPlayer.pause() is called:  %s", repr(self)
        )
        if self.is_playing:
            self.state = MusicPlayerState.PAUSED
            reset = getattr(getattr(self, '_source', None), 'reset_cadence', None)
            if reset is not None:
                reset('pause')

            if self._current_player:
                self._current_player.pause()

            self.emit("pause", player=self, entry=self.current_entry)
            return

        if self.is_paused:
            return

        raise ValueError(f"Cannot pause a MusicPlayer in state {self.state}")

    def kill(self) -> None:
        """
        Set the state of the bot to Dead, clear all events and playlists,
        then kill the current VoiceClient source player.
        """
        log.noise(  # type: ignore[attr-defined]
            "MusicPlayer.kill() is called:  %s", repr(self)
        )
        self._stop_requested = True
        self._invalidate_play_request()
        self._pending_seek = None
        self._current_entry = None
        self._source = None
        self.state = MusicPlayerState.DEAD
        self.playlist.clear()
        self._events.clear()
        self._kill_current_player()

    async def _report_cadence_events(self, source: SourcePlaybackCounter) -> None:
        """Periodic bounded logging only on the asyncio loop, never audio thread."""
        while not getattr(source, '_cadence_reported', True) and source is self._source and not self.is_dead:
            await asyncio.sleep(0.5)
            if getattr(source, '_cadence_reported', True) or source is not self._source:
                return
            collector = getattr(getattr(source, '_cadence', None), 'take_events', None)
            if collector is None:
                return
            try:
                for sample in collector(4):
                    logged_at = round(time.time() * 1000)
                    log.info('source_read_cadence_event %s', json.dumps({
                        **sample, 'logged_at_utc_ms': logged_at,
                        'report_delay_ms': (max(0, logged_at - sample['at_utc_ms'])
                                            if sample.get('at_utc_ms') is not None else None),
                    }, sort_keys=True))
            except Exception:
                log.debug('Optional cadence event reporting disabled')
                return

    def _playback_finished(
        self, error: Optional[Exception] = None, *,
        source: Optional[SourcePlaybackCounter] = None,
        stderr_future: Optional[AsyncFuture] = None,
    ) -> None:
        """
        Event fired by discord.VoiceClient after playback has finished
        or when playback stops due to an error.
        This function is responsible tidying the queue post-playback,
        propagating player error or finished-playing events, and
        triggering the media file cleanup task.

        :param: error:  An exception, if any, raised by playback.
        """
        # Discord invokes after() from its audio thread. Serialize all player
        # mutations with commands, and ignore a callback from a replaced source.
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is not self.loop:
            if not self.loop.is_closed():
                self.loop.call_soon_threadsafe(
                    partial(self._playback_finished, error, source=source,
                            stderr_future=stderr_future)
                )
            return
        # The old stderr reader must exit even when its playback callback is
        # stale. It must never complete the replacement source's future.
        if stderr_future is not None and not stderr_future.done():
            stderr_future.set_result(True)
        # Summarize the finished source even after stop/seek replaced it. This
        # does not touch the current source, queue, state or stderr ownership.
        summarize = getattr(source, 'cadence_summary', None)
        if summarize is not None:
            try:
                summary = summarize()
                if summary is not None:
                    log.info("source_read_cadence_summary %s", json.dumps(summary, sort_keys=True))
            except Exception:
                log.debug("Unable to summarize optional read cadence diagnostics")
        if self.is_dead or (source is not None and source is not self._source):
            return
        # Ensure the stderr stream reader for ffmpeg is exited.
        if (
            isinstance(self._stderr_future, asyncio.Future)
            and not self._stderr_future.done()
        ):
            self._stderr_future.set_result(True)

        entry = self._current_entry
        if entry is None:
            log.debug("Playback finished, but _current_entry is None.")
            return

        seeking = self._pending_seek and self._pending_seek['entry'] is entry
        if self.repeatsong and not seeking and not self._stop_requested:
            self.playlist.entries.appendleft(entry)
        elif self.loopqueue and not seeking and not self._stop_requested:
            self.playlist.entries.append(entry)

        # TODO: investigate if this is cruft code or not.
        if self._current_player:
            if hasattr(self._current_player, "after"):
                self._current_player.after = None
            self._kill_current_player()

        self._current_entry = None
        self._source = None
        self.state = MusicPlayerState.STOPPED
        self.emit("stop", player=self)
        if self._stop_requested:
            return

        # if an error was set, report it and return...
        if error:
            self.emit("error", player=self, entry=entry, ex=error)
            return

        # if a exception is found in the ffmpeg stderr stream, report it and return...
        if (
            isinstance(self._stderr_future, asyncio.Future)
            and self._stderr_future.done()
            and self._stderr_future.exception()
        ):
            # I'm not sure that this would ever not be done if it gets to this point
            # unless ffmpeg is doing something highly questionable
            self.emit(
                "error", player=self, entry=entry, ex=self._stderr_future.exception()
            )
            return

        # ensure file cleanup is handled if nothing was wrong with playback.
        if not self.bot.config.save_videos and entry:
            self.bot.create_task(
                self._handle_file_cleanup(entry), name="MB_CacheCleanup"
            )

        # Dashboard can now show the known next track while the bot
        # asynchronously schedules/starts it; never show a phantom track
        # when the queue is actually empty.
        self._transitioning_to_next = self.playlist.peek() is not None
        self._preparing_entry = None
        self.emit("finished-playing", player=self, entry=entry)

    def _kill_current_player(self) -> bool:
        """
        If there is a current player source, attempt to stop it, then
        say "Garbage day!" and set it to None anyway.
        """
        # Invalidate a pending read so stop/skip/seek cannot start stale audio.
        self._preparing_source = None
        if self._current_player:
            try:
                self._current_player.stop()
            except OSError:
                log.noise(  # type: ignore[attr-defined]
                    "Possible Warning from kill_current_player()", exc_info=True
                )

            self._current_player = None
            return True

        return False

    def play(self, _continue: bool = False) -> None:
        """
        Immediately try to gracefully play the next entry in the queue.
        If there is already an entry, but player is paused, playback will
        resume instead of playing a new entry.
        If the player is dead, this will silently return.

        :param: _continue:  Force a player that is not dead or stopped to
            start a new playback source anyway.
        """
        log.noise(  # type: ignore[attr-defined]
            "MusicPlayer.play() is called:  %s", repr(self)
        )
        if self.is_dead:
            return
        pending = self._play_task
        if pending is not None and not pending.done() and not pending.cancelling():
            return
        if self._play_queued_generation == self._play_generation:
            return
        self._stop_requested = False
        if self._current_entry is None:
            # Set before scheduling: there may be a gap before _play() runs.
            self._preparing_entry = self.playlist.peek()
            self._transitioning_to_next = self._preparing_entry is not None
        self._play_queued_generation = self._play_generation
        self.bot.create_task(
            self._play(_continue=_continue, _generation=self._play_generation),
            name="MB_Play",
        )

    async def _play(
        self, _continue: bool = False, *, _generation: Optional[int] = None,
    ) -> None:
        """
        Plays the next entry from the playlist, or resumes playback of the current entry if paused.
        """
        generation = self._play_generation if _generation is None else _generation
        task = asyncio.current_task()
        owner = self._play_task
        if self._play_queued_generation == generation:
            self._play_queued_generation = None
        if generation != self._play_generation:
            return
        if (owner is not None and owner is not task and not owner.done()
                and not owner.cancelling()):
            return
        self._play_task = task
        try:
            if self.is_dead:
                log.voicedebug(  # type: ignore[attr-defined]
                    "MusicPlayer is dead, cannot play."
                )
                return

            if self.guild_or_net_unavailable:
                log.warning("Guild or network unavailable, cannot start playback.")
                return

            if self.is_paused and self._current_player:
                log.voicedebug(  # type: ignore[attr-defined]
                    "MusicPlayer was previously paused, resuming current player."
                )
                return self.resume()

            async with self._play_lock:
                if generation != self._play_generation or self.is_dead:
                    return
                if self.is_stopped or _continue:
                    # Get the entry before we try to ready it, so it can be passed to error callbacks.
                    entry_up_next = self.playlist.peek()
                    # Keep selected metadata visible after get_next_entry()
                    # removes the item from the public playlist queue.
                    self._preparing_entry = entry_up_next
                    self._transitioning_to_next = entry_up_next is not None
                    playback_voice_client = self.voice_client
                    try:
                        entry = await self.playlist.get_next_entry()
                    except IndexError as e:
                        if generation != self._play_generation:
                            return
                        log.warning("Failed to get next entry.", exc_info=e)
                        self.emit("error", player=self, entry=entry_up_next, ex=e)
                        entry = None
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        if generation != self._play_generation:
                            return
                        log.warning("Failed to process entry for playback.", exc_info=e)
                        self.emit("error", player=self, entry=entry_up_next, ex=e)
                        entry = None

                    if generation != self._play_generation:
                        return

                    async def abandon_disconnected_playback(*, restore_entry: bool = True) -> None:
                        if generation != self._play_generation:
                            return
                        self._preparing_source = None
                        self._preparing_entry = None
                        self._transitioning_to_next = False
                        self._pending_seek = None
                        self._current_entry = None
                        self._current_player = None
                        self._source = None
                        self._skip_preparing = False
                        if not self.is_dead:
                            self.state = MusicPlayerState.STOPPED
                            if restore_entry and entry is not None:
                                # Restore this ready entry without entry-added side effects,
                                # round-robin reordering, or starting another download.
                                self.playlist.entries.appendleft(entry)
                                guild = (
                                    playback_voice_client.guild
                                    if playback_voice_client is not None
                                    else entry.channel.guild if entry.channel else None
                                )
                                if guild is not None:
                                    await self.bot.serialize_queue(guild)
                        log.voicedebug(  # type: ignore[attr-defined]
                            "Player stopped or voice disconnected while preparing playback."
                        )

                    # Downloading may outlive the voice connection or the player.
                    if (
                        self.is_dead
                        or self.voice_client is None
                        or not self.voice_client.is_connected()
                    ):
                        await abandon_disconnected_playback()
                        return

                    # If nothing left to play, transition to the stopped state.
                    if not entry:
                        self.stop()
                        return

                    # In-case there was a player, kill it. RIP.
                    self._kill_current_player()

                    boptions = "-nostdin"
                    aoptions = "-vn -sn -dn"  # "-b:a 192k"
                    # Preserve measured two-pass loudnorm on downloaded files,
                    # including with Opus probing. Streams use one-pass loudnorm.
                    if not self.bot.config.use_experimental_equalization:
                        entry.remove_audio_filter("loudnorm")
                    elif not entry.has_audio_filter("loudnorm"):
                        entry.set_audio_filter("loudnorm", LOUDNORM_TARGET)

                    if self.bot.config.use_opus_audio or self.bot.config.use_opus_probe:
                        # At unity gain no filter is necessary; Opus passthrough
                        # can still save CPU if loudnorm and tempo are also off.
                        if self.volume != 1.0:
                            entry.set_audio_filter("volume", f"{self.volume:.2f}")
                        else:
                            entry.remove_audio_filter("volume")
                    else:
                        # PCMVolumeTransformer applies volume after FFmpeg.
                        entry.remove_audio_filter("volume")

                    if isinstance(entry, (URLPlaylistEntry, LocalFilePlaylistEntry)):
                        entry_options = entry.aoptions
                    else:
                        entry_options = entry.get_audio_filters()
                    if entry_options:
                        aoptions += f" {entry_options}"

                    if isinstance(entry, (URLPlaylistEntry, LocalFilePlaylistEntry)):
                        if entry.boptions:
                            boptions += f" {entry.boptions}"

                    stderr_io = io.BytesIO()

                    if self.bot.config.use_opus_probe or self.bot.config.use_opus_audio:
                        # Note: ffmpeg filters require encoding to work.
                        # Filtered output must be encoded, even if the input is Opus.
                        if (
                            self.bot.config.use_opus_probe and not entry.probed_codec
                        ) or not entry.probed_bitrate:
                            try:
                                codec, bitrate = await FFmpegOpusAudio.probe(
                                    entry.filename,
                                    method="native",
                                )
                            except Exception:
                                if generation != self._play_generation:
                                    return
                                raise
                            if generation != self._play_generation:
                                return
                            if self.voice_client is None or not self.voice_client.is_connected():
                                await abandon_disconnected_playback()
                                return
                            log.everything(  # type: ignore[attr-defined]
                                "Probed codec and bitrate: %(name)s at %(rate)s kbps",
                                {"name": codec, "rate": bitrate},
                            )
                        if self.bot.config.use_opus_probe and not entry.probed_codec:
                            # If the probe returned opus, libopus, or copy, copy is used.
                            entry.probed_codec = codec

                        if not entry.probed_bitrate:
                            entry.probed_bitrate = bitrate

                        # Determine bitrate to use based on probe, channel setting, and bot limit.
                        vc_kbitrate = self.voice_client.channel.bitrate / 1000
                        kbitrate = min(vc_kbitrate, entry.probed_bitrate)
                        kbitrate = min(kbitrate, MUSICBOT_VOICE_MAX_KBITRATE)
                        source: FFmpegSources = FFmpegOpusAudio(
                            entry.filename,
                            # FFmpeg cannot stream-copy Opus while applying filters.
                            codec=None if "-af " in aoptions else entry.probed_codec,
                            bitrate=kbitrate,
                            before_options=boptions,
                            options=aoptions,
                            stderr=stderr_io,
                        )
                    else:
                        source = PCMVolumeTransformer(
                            FFmpegPCMAudio(
                                entry.filename,
                                before_options=boptions,
                                options=aoptions,
                                stderr=stderr_io,
                            ),
                            self.volume,
                        )

                    cadence = None
                    if os.environ.get('MUSICBOT_SOURCE_READ_CADENCE') == '1':
                        try:
                            layered = os.environ.get('MUSICBOT_CADENCE_LAYERS') == '1'
                            cadence_class = LayeredReadCadenceDiagnostics if layered else ReadCadenceDiagnostics
                            cadence = cadence_class(
                                session=secrets.token_hex(6), generation=generation,
                                media_offset_s=entry.start_time,
                                playback_speed=entry.playback_speed,
                                track_id=hashlib.sha256(str(entry.url).encode('utf-8')).hexdigest()[:12],
                                **({'gc_enabled': os.environ.get('MUSICBOT_CADENCE_GC') == '1'} if layered else {}),
                            )
                        except Exception:
                            log.debug("Unable to initialize optional read cadence diagnostics")
                    prepared_source = SourcePlaybackCounter(
                        source,
                        start_time=entry.start_time,
                        playback_speed=entry.playback_speed,
                        continuous=True,
                        cadence=cadence,
                    )
                    self._preparing_source = prepared_source
                    self._skip_preparing = False

                    def discard_source() -> None:
                        # FFmpeg cleanup can wait for its process/pipe threads.
                        try:
                            prepared_source.cleanup()
                            worker_done = getattr(prepared_source, "_worker_done", None)
                            if worker_done is not None:
                                worker_done.wait(FIRST_FRAME_TIMEOUT)
                        except Exception:
                            log.exception("Failed to clean up an unstarted audio source.")
                        finally:
                            stderr_io.close()

                    try:
                        await prepared_source.prepare(timeout=FIRST_FRAME_TIMEOUT)
                    except (Exception, asyncio.CancelledError) as exc:
                        active = (generation == self._play_generation
                                  and self._preparing_source is prepared_source)
                        if active:
                            self._preparing_source = None
                        await asyncio.shield(asyncio.get_running_loop().run_in_executor(None, discard_source))
                        if isinstance(exc, asyncio.CancelledError):
                            raise
                        if active and generation == self._play_generation:
                            self.stop()
                            self.emit("error", player=self, entry=entry, ex=exc)
                        return

                    if generation != self._play_generation:
                        await asyncio.shield(asyncio.get_running_loop().run_in_executor(None, discard_source))
                        return

                    voice_client = self.voice_client
                    if (
                        self.is_dead
                        or voice_client is None
                        or not voice_client.is_connected()
                    ):
                        await asyncio.shield(asyncio.get_running_loop().run_in_executor(None, discard_source))
                        # A concurrent stop/skip has already discarded this entry.
                        await abandon_disconnected_playback(
                            restore_entry=self._preparing_source is prepared_source
                        )
                        return

                    if self._preparing_source is not prepared_source:
                        await asyncio.shield(asyncio.get_running_loop().run_in_executor(None, discard_source))
                        return
                    self._preparing_source = None
                    self._source = prepared_source
                    stderr_future = asyncio.Future()
                    log.ffmpeg(  # type: ignore[attr-defined]
                        "Creating player with options: ffmpeg %(before)s -i %(input)s %(after)s",
                        {"before": boptions, "input": entry.filename, "after": aoptions},
                    )
                    log.voicedebug(  # type: ignore[attr-defined]
                        "Playing %(source)r using %(client)r",
                        {"source": self._source, "client": self.voice_client},
                    )
                    try:
                        voice_client.play(
                            self._source,
                            after=partial(self._playback_finished, source=prepared_source,
                                          stderr_future=stderr_future),
                        )
                        # A full startup window protects the tiny gap before the
                        # producer is released to replenish the ongoing buffer.
                        prepared_source.start_streaming()
                        reporter = getattr(self, '_report_cadence_events', None)
                        if cadence is not None and callable(getattr(cadence, 'take_events', None)) and callable(reporter):
                            asyncio.get_running_loop().create_task(reporter(prepared_source))
                    except ClientException as exc:
                        # Discord checks again inside play(), after our connection check.
                        if self._source is prepared_source:
                            self._source = None
                        await asyncio.shield(asyncio.get_running_loop().run_in_executor(None, discard_source))
                        if generation != self._play_generation:
                            return
                        if str(exc) != "Not connected to voice.":
                            raise
                        await abandon_disconnected_playback()
                        return
                    except Exception:
                        # A rejected play() must not strand the continuous producer.
                        if self._source is prepared_source:
                            self._source = None
                        await asyncio.shield(asyncio.get_running_loop().run_in_executor(None, discard_source))
                        if generation != self._play_generation:
                            return
                        raise

                    self._current_player = voice_client

                    # I need to add ytdl hooks
                    self.state = MusicPlayerState.PLAYING
                    self._current_entry = entry
                    self._preparing_entry = None
                    self._transitioning_to_next = False
                    pending = self._pending_seek
                    self._pending_seek = None
                    if pending and pending["entry"] is entry and pending["paused"]:
                        # Recreate the source without silently resuming a paused seek.
                        self.pause()

                    self._stderr_future = stderr_future

                    stderr_thread = Thread(
                        target=filter_stderr,
                        args=(stderr_io, self._stderr_future),
                        name="MB_FFmpegStdErrReader",
                    )

                    stderr_thread.start()

                    self.emit("play", player=self, entry=entry)
        except asyncio.CancelledError:
            # Explicit commands invalidate the generation before cancelling the
            # waiter. External cancellation keeps its normal asyncio semantics.
            if generation == self._play_generation:
                raise
        finally:
            if self._play_task is task:
                self._play_task = None
            # Failure or cancellation must not leave a stale loading card.
            # Old generations must never clear a newer request's hint.
            if (generation == self._play_generation
                    and self._current_entry is None):
                self._preparing_entry = None
                self._transitioning_to_next = False

    async def _handle_file_cleanup(self, entry: EntryTypes) -> None:
        """
        A helper used to clean up media files via call-later, when file
        cache is not enabled.
        """
        if not isinstance(entry, StreamPlaylistEntry):
            if any(entry.filename == e.filename for e in self.playlist.entries):
                log.debug(
                    "Skipping deletion of '%s', found song in queue",
                    entry.filename,
                )
            else:
                log.debug("Deleting file:  %s", os.path.relpath(entry.filename))
                filename = entry.filename
                for _ in range(3):
                    try:
                        os.unlink(filename)
                        log.debug("File deleted:  %s", filename)
                        break
                    except PermissionError as e:
                        if e.errno == 32:  # File is in use
                            log.warning("Cannot delete file, it is currently in use.")
                        else:
                            log.warning(
                                "Cannot delete file due to a permission error.",
                                exc_info=True,
                            )
                    except FileNotFoundError:
                        log.warning(
                            "Cannot delete file, it was not found.",
                            exc_info=True,
                        )
                        break
                    except (OSError, IsADirectoryError):
                        log.warning(
                            "Error while trying to delete file.",
                            exc_info=True,
                        )
                        break
                else:
                    log.debug("Could not delete file, giving up and moving on")

    def __json__(self) -> Dict[str, Any]:
        return self._enclose_json(
            {
                "current_entry": {
                    "entry": self.current_entry,
                    "progress": self.progress if self.progress > 1 else None,
                },
                "entries": self.playlist,
            }
        )

    @classmethod
    def _deserialize(
        cls,
        raw_json: Dict[str, Any],
        bot: Optional["MusicBot"] = None,
        voice_client: Optional[VoiceClient] = None,
        playlist: Optional["Playlist"] = None,
        **kwargs: Any,
    ) -> "MusicPlayer":
        assert bot is not None, cls._bad("bot")
        assert voice_client is not None, cls._bad("voice_client")
        assert playlist is not None, cls._bad("playlist")

        player = cls(bot, voice_client, playlist)

        data_pl = raw_json.get("entries")
        if data_pl and data_pl.entries:
            player.playlist.entries = data_pl.entries

        current_entry_data = raw_json["current_entry"]
        if current_entry_data["entry"]:
            entry = current_entry_data["entry"]
            progress = current_entry_data["progress"]
            if progress and isinstance(
                entry, (URLPlaylistEntry, LocalFilePlaylistEntry)
            ):
                entry.set_start_time(progress)

            # Check if user disabled autoplaylist before re-adding.
            if (
                entry.from_auto_playlist and bot.config.auto_playlist
            ) or not entry.from_auto_playlist:
                player.playlist.entries.appendleft(entry)
        return player

    @classmethod
    def from_json(
        cls,
        raw_json: str,
        bot: "MusicBot",  # pylint: disable=unused-argument
        voice_client: VoiceClient,  # pylint: disable=unused-argument
        playlist: "Playlist",  # pylint: disable=unused-argument
    ) -> Optional["MusicPlayer"]:
        """
        Create a MusicPlayer instance from serialized `raw_json` string data.
        The remaining arguments are made available to the MusicPlayer
        and other serialized instances via call frame inspection.
        """
        try:
            obj = json.loads(raw_json, object_hook=Serializer.deserialize)
            if isinstance(obj, MusicPlayer):
                return obj
            log.error(
                "Deserialize returned an object that is not a MusicPlayer:  %s",
                type(obj),
            )
            return None
        except json.JSONDecodeError:
            log.exception("Failed to deserialize player")
            return None

    @property
    def current_entry(self) -> Optional[EntryTypes]:
        """Get the currently playing entry if there is one."""
        return self._current_entry

    @property
    def is_playing(self) -> bool:
        """Test if MusicPlayer is in a playing state"""
        return self.state == MusicPlayerState.PLAYING

    @property
    def is_paused(self) -> bool:
        """Test if MusicPlayer is in a paused state"""
        return self.state == MusicPlayerState.PAUSED

    @property
    def is_stopped(self) -> bool:
        """Test if MusicPlayer is in a stopped state"""
        return self.state == MusicPlayerState.STOPPED

    @property
    def is_dead(self) -> bool:
        """Test if MusicPlayer is in a dead state"""
        return self.state == MusicPlayerState.DEAD

    @property
    def progress(self) -> float:
        """
        Return a progress value for the media playback.
        """
        if self._pending_seek:
            return self._pending_seek['position']
        if self._source:
            return self._source.progress
        return 0

    @property
    def session_progress(self) -> float:
        """
        Return the estimated playback time of the current playback source.
        Like progress, but does not include any start-time if one was used.
        """
        if self._source:
            return self._source.session_progress
        return 0


# TODO: I need to add a check if the event loop is closed?


def filter_stderr(stderr: io.BytesIO, future: AsyncFuture) -> None:
    """
    Consume a `stderr` bytes stream and check it for errors or warnings.
    Set the given `future` with either an error found in the stream or
    set the future with a successful result.
    """
    last_ex = None
    while not future.done():
        data = stderr.readline()
        if data:
            log.ffmpeg(  # type: ignore[attr-defined]
                "Data from ffmpeg: %s",
                repr(data),
            )
            try:
                if check_stderr(data):
                    sys.stderr.buffer.write(data)
                    sys.stderr.buffer.flush()

            except FFmpegError as e:
                log.ffmpeg(  # type: ignore[attr-defined]
                    "Error from ffmpeg: %s", str(e).strip()
                )
                last_ex = e
                if not future.done():
                    future.set_exception(e)

            except FFmpegWarning as e:
                log.ffmpeg(  # type: ignore[attr-defined]
                    "Warning from ffmpeg:  %s", str(e).strip()
                )
        else:
            time.sleep(0.5)

    if not future.done():
        if last_ex:
            future.set_exception(last_ex)
        else:
            future.set_result(True)


def check_stderr(data: bytes) -> bool:
    """
    Inspect `data` from a subprocess call's stderr output for specific
    messages and raise them as a suitable exception.

    :returns:  True if nothing was detected or nothing could be detected.

    :raises: musicbot.exceptions.FFmpegWarning
        If a warning level message was detected in the `data`
    :raises: musicbot.exceptions.FFmpegError
        If an error message was detected in the `data`
    """
    ddata = ""
    try:
        ddata = data.decode("utf8")
    except UnicodeDecodeError:
        log.ffmpeg(  # type: ignore[attr-defined]
            "Unknown error decoding message from ffmpeg", exc_info=True
        )
        return True  # fuck it

    log.ffmpeg("Decoded data from ffmpeg: %s", ddata)  # type: ignore[attr-defined]

    # TODO: Regex
    warnings = [
        "Header missing",
        "Estimating duration from birate, this may be inaccurate",
        "Using AVStream.codec to pass codec parameters to muxers is deprecated, use AVStream.codecpar instead.",
        "Application provided invalid, non monotonically increasing dts to muxer in stream",
        "Last message repeated",
        "Failed to send close message",
        "decode_band_types: Input buffer exhausted before END element found",
    ]
    errors = [
        "Invalid data found when processing input",  # need to regex this properly, its both a warning and an error
    ]

    if any(msg in ddata for msg in warnings):
        raise FFmpegWarning(ddata)

    if any(msg in ddata for msg in errors):
        raise FFmpegError(ddata)

    return True


# if redistributing ffmpeg is an issue, it can be downloaded from here:
#  - http://ffmpeg.zeranoe.com/builds/win32/static/ffmpeg-latest-win32-static.7z
#  - http://ffmpeg.zeranoe.com/builds/win64/static/ffmpeg-latest-win64-static.7z
#
# Extracting bin/ffmpeg.exe, bin/ffplay.exe, and bin/ffprobe.exe should be fine
# However, the files are in 7z format so meh
# I don't know if we can even do this for the user, at most we open it in the browser
# I can't imagine the user is so incompetent that they can't pull 3 files out of it...
# ...
# ...right?

# Get duration with ffprobe
#   ffprobe.exe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 -sexagesimal filename.mp3
# This is also how I fix the format checking issue for now
# ffprobe -v quiet -print_format json -show_format stream

# Normalization filter
# -af dynaudnorm
