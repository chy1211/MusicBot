"""Optional, read-side *invocation* cadence diagnostics for Discord audio.

This does not measure UDP transmission or a listener's playback clock.
No logging, I/O, network calls, sleeps or playback decisions occur in observe().
"""
from __future__ import annotations

from collections import deque
import time
import math


class ReadCadenceDiagnostics:
    """O(1) memory/CPU counters for successive valid 20 ms source reads.

    A run of >=3 intervals below 10 ms is an episode. The previous observed
    interval classifies it as either a >=60 ms-gap catchup or an independent
    burst. A lone quick interval is recorded in the histogram, not alerted.
    """

    __slots__ = (
        'session', 'generation', 'track_id', 'frames', 'intervals', 'buckets',
        'min_interval_ms', 'max_interval_ms', 'max_read_ms', 'last_start',
        'run_count', 'run_elapsed_ms', 'run_deficit_ms', 'run_start_frame',
        'run_after_gap', 'recent_gap', 'max_run', 'episodes', 'independent',
        'gap_following', 'total_deficit_ms', 'samples', 'dropped_samples',
        'wall_origin', 'mono_origin', 'run_start_clock', 'resets', 'last_reset_reason',
        'media_offset_ms', 'playback_speed',
    )
    BUCKET_NAMES = ('lt5', '5to10', '10to15', '15to25', '25to60', 'gte60')
    SHORT_MS = 10.0
    LARGE_GAP_MS = 60.0
    MIN_RUN = 3
    SAMPLE_LIMIT = 12

    def __init__(self, *, session: str, generation: int, track_id: str, media_offset_s: float = 0.0, playback_speed: float = 1.0) -> None:
        self.playback_speed = float(playback_speed)
        if not math.isfinite(self.playback_speed) or self.playback_speed <= 0:
            raise ValueError('Invalid diagnostic playback speed')
        self.media_offset_ms = max(0.0, float(media_offset_s)) * 1000
        self.session = session
        self.generation = generation
        self.track_id = track_id
        self.frames = 0
        self.intervals = 0
        self.buckets = [0] * 6
        self.min_interval_ms = None
        self.max_interval_ms = 0.0
        self.max_read_ms = 0.0
        self.last_start = None
        self.run_count = 0
        self.run_elapsed_ms = 0.0
        self.run_deficit_ms = 0.0
        self.run_start_frame = 0
        self.run_after_gap = False
        self.recent_gap = False
        self.max_run = 0
        self.episodes = 0
        self.independent = 0
        self.gap_following = 0
        self.total_deficit_ms = 0.0
        self.samples = deque(maxlen=self.SAMPLE_LIMIT)
        self.dropped_samples = 0
        self.wall_origin = time.time()
        self.mono_origin = time.monotonic()
        self.run_start_clock = None
        self.resets = {}
        self.last_reset_reason = None

    def _finish_run(self) -> None:
        if self.run_count >= self.MIN_RUN:
            self.episodes += 1
            if self.run_after_gap:
                self.gap_following += 1
            else:
                self.independent += 1
            self.total_deficit_ms += self.run_deficit_ms
            if len(self.samples) == self.SAMPLE_LIMIT:
                self.dropped_samples += 1
            self.samples.append({
                'first_frame': self.run_start_frame,
                'at_utc_ms': round((self.wall_origin + (self.run_start_clock - self.mono_origin)) * 1000) if self.run_start_clock is not None else None,
                'preceding_reset': self.last_reset_reason,
                'at_progress_ms': round(self.media_offset_ms + self.run_start_frame * 20 * self.playback_speed, 1),
                'intervals': self.run_count,
                'elapsed_ms': round(self.run_elapsed_ms, 2),
                'shortfall_vs_20ms': round(self.run_deficit_ms, 2),
                'after_large_gap': self.run_after_gap,
            })
        self.run_count = 0
        self.run_elapsed_ms = 0.0
        self.run_deficit_ms = 0.0

    def break_sequence(self, reason: str = "boundary") -> None:
        """Separates pause, resume, EOF, underrun or a new read generation."""
        reason = reason if reason in {'boundary','pause','resume','read_error','eof_or_underrun','finished','clock_reset'} else 'other'
        self._finish_run()
        self.last_start = None
        self.recent_gap = False
        self.last_reset_reason = reason
        self.resets[reason] = self.resets.get(reason, 0) + 1

    def observe(self, start: float, end: float, *, frame: int) -> None:
        """Observe a valid frame using a monotonic source.read call timestamp."""
        self.frames += 1
        self.max_read_ms = max(self.max_read_ms, max(0.0, (end - start) * 1000))
        previous = self.last_start
        self.last_start = start
        if previous is None or start <= previous:
            if start < (previous if previous is not None else start):
                self.break_sequence()
                self.last_start = start
            return
        delta = (start - previous) * 1000
        self.intervals += 1
        self.min_interval_ms = delta if self.min_interval_ms is None else min(self.min_interval_ms, delta)
        self.max_interval_ms = max(self.max_interval_ms, delta)
        bucket = 0 if delta < 5 else 1 if delta < 10 else 2 if delta < 15 else 3 if delta < 25 else 4 if delta < 60 else 5
        self.buckets[bucket] += 1
        if delta < self.SHORT_MS:
            if not self.run_count:
                self.run_start_frame = frame
                self.run_start_clock = start
                self.run_after_gap = self.recent_gap
            self.run_count += 1
            self.run_elapsed_ms += delta
            self.run_deficit_ms += 20.0 - delta
            self.max_run = max(self.max_run, self.run_count)
            self.recent_gap = False
        else:
            self._finish_run()
            self.recent_gap = delta >= self.LARGE_GAP_MS

    def summary(self) -> dict:
        """Bounded copy for logging from the asyncio loop, not audio thread."""
        # Include an active episode at the end without changing counters.
        pending = self.run_count >= self.MIN_RUN
        return {
            'session': self.session, 'source_generation': self.generation,
            'track_hash': self.track_id, 'read_frames': self.frames,
            'playback_speed': self.playback_speed,
            'source_media_offset_ms': round(self.media_offset_ms, 1),
            'source_read_intervals': self.intervals,
            'source_read_min_interval_ms': None if self.min_interval_ms is None else round(self.min_interval_ms, 3),
            'source_read_max_interval_ms': round(self.max_interval_ms, 3),
            'source_read_max_duration_ms': round(self.max_read_ms, 3),
            'source_read_interval_histogram': dict(zip(self.BUCKET_NAMES, self.buckets)),
            'source_read_longest_short_run': self.max_run,
            'source_read_bursts': self.episodes + int(pending),
            'source_read_independent_bursts': self.independent + int(pending and not self.run_after_gap),
            'source_read_after_large_gap_bursts': self.gap_following + int(pending and self.run_after_gap),
            'source_read_shortfall_ms': round(self.total_deficit_ms + (self.run_deficit_ms if pending else 0), 2),
            'source_read_recent_samples': list(self.samples),
            'source_read_dropped_samples': self.dropped_samples,
            'source_read_sequence_resets': dict(self.resets),
            'packet_send_status': 'not_instrumented',
        }
