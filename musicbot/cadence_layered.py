"""Optional R22 source-read timeline and GC correlation.

Does NOT observe VoiceClient.send_audio_packet nor socket.sendall. A successful
source read is not evidence of a successful packet send or audible playback.
No audio data or addresses are stored. Disabled unless explicitly constructed.
"""
from __future__ import annotations

from collections import deque
import gc
import threading
import time

from .read_cadence_diagnostics import ReadCadenceDiagnostics


class GCWindow:
    """Fixed-memory GC timestamps (monotonic), without logging in gc.callbacks."""
    MAX_EVENTS = 64
    MAX_ACTIVE = 32

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.events = deque(maxlen=self.MAX_EVENTS)
        self.active = {}
        self.dropped = 0
        self.installed = False
        self._callback = self._on_gc

    def start(self):
        if not self.installed:
            gc.callbacks.append(self._callback)
            self.installed = True

    def close(self):
        if self.installed:
            # Never remove or clear callbacks owned by any other package.
            try:
                gc.callbacks.remove(self._callback)
            except ValueError:
                pass
            self.installed = False
        self.active.clear()

    def _on_gc(self, phase, info):
        try:
            now = self.clock()
            thread = threading.current_thread()
            thread_kind = ('audio' if thread.name.startswith(('AudioPlayer', 'audio-player')) else 'downloader' if thread.name.startswith('MB_Downloader') else 'event_loop' if thread is threading.main_thread() else 'other')
            key = threading.get_ident()
            if phase == 'start':
                if len(self.active) < self.MAX_ACTIVE:
                    self.active[key] = (now, int(info.get('generation', -1)), thread_kind)
                else:
                    self.dropped += 1
            elif phase == 'stop':
                data = self.active.pop(key, None)
                if data is not None:
                    begin, generation, kind = data
                    if len(self.events) == self.MAX_EVENTS:
                        self.dropped += 1
                    self.events.append((begin, now, generation, kind))
        except Exception:
            # A monitor must never affect the Python garbage collector.
            self.dropped += 1

    def related(self, start, end, *, near_seconds=0.2):
        """Bounded scan: return overlap/near/during-GC information, not a cause."""
        overlap = 0
        nearby = 0
        max_duration_ms = 0.0
        nearest_ms = None
        for begin, stop, generation, kind in self.events.copy():
            if begin <= end and stop >= start:
                overlap += 1
                max_duration_ms = max(max_duration_ms, 1000 * (stop - begin))
                nearest_ms = 0.0
            else:
                distance = min(abs(begin - end), abs(stop - start))
                if distance <= near_seconds:
                    nearby += 1
                    nearest_ms = 1000 * distance if nearest_ms is None else min(nearest_ms, 1000 * distance)
        active = sum(1 for begin, _, _ in tuple(self.active.values()) if begin <= end)
        return {
            'gc_overlap_count': overlap,
            'gc_nearby_count': nearby,
            'gc_active_during_event': active,
            'gc_nearest_distance_ms': None if nearest_ms is None else round(nearest_ms, 3),
            'gc_overlap_max_duration_ms': round(max_duration_ms, 3),
            'gc_dropped': self.dropped,
            'gc_completed_windows': [{'start_mono': a, 'stop_mono': b, 'generation': g, 'thread_kind': t} for a,b,g,t in self.events.copy() if a <= end + near_seconds and b >= start - near_seconds][-12:],
        }


class LayeredReadCadenceDiagnostics(ReadCadenceDiagnostics):
    """R22 schema extensions without changing R18 summary key meanings.

    ``after_large_gap`` remains the old *immediately preceding* classification.
    New ``gap_context`` reports a gap up to 10 frames/500 ms back.
    """
    GAP_FRAMES = 10
    GAP_SECONDS = 0.5
    LIVE_LIMIT = 12

    def __init__(self, *args, gc_enabled=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_large_gap = None
        self.run_gap_context = None
        self.live_events = deque(maxlen=self.LIVE_LIMIT)
        self.live_dropped = 0
        self.live_emitted = 0
        self.live_suppressed = 0
        self.event_sequence = 0
        self.run_end_clock = None
        self.gc_window = GCWindow() if gc_enabled else None
        if self.gc_window:
            self.gc_window.start()

    def observe(self, start, end, *, frame):
        previous = self.last_start
        delta_ms = (start - previous) * 1000 if previous is not None else None
        if delta_ms is not None and delta_ms >= self.LARGE_GAP_MS:
            self.last_large_gap = (start, frame, delta_ms)
        if delta_ms is not None and 0 <= delta_ms < self.SHORT_MS and self.run_count == 0:
            gap = self.last_large_gap
            if gap and (start-gap[0]) <= self.GAP_SECONDS and 0 <= frame-gap[1] <= self.GAP_FRAMES:
                category = 'immediately_after_gap' if self.recent_gap else 'recent_gap'
                self.run_gap_context = (category, round((start-gap[0])*1000, 3), frame-gap[1], round(gap[2], 3))
            else:
                self.run_gap_context = ('no_recent_gap', None, None, None)
        if delta_ms is not None and 0 < delta_ms < self.SHORT_MS:
            self.run_end_clock = start
        super().observe(start, end, frame=frame)

    def _finish_run(self):
        before = self.episodes
        before_count = self.run_count
        onset = self.run_start_clock
        last = self.run_end_clock
        ctx = self.run_gap_context
        super()._finish_run()
        if self.episodes > before and self.samples:
            sample = self.samples[-1]
            category, age_ms, gap_frames, gap_ms = ctx or ('no_recent_gap',None,None,None)
            sample.update({
                'schema_version': 2,
                'gap_context': category,
                'recent_gap_age_ms': age_ms,
                'recent_gap_frame_distance': gap_frames,
                'recent_gap_size_ms': gap_ms,
                'event_id': f'{self.session}:{self.generation}:{self.event_sequence}',
                'stage': 'source_read',
                'event_end_mono': last,
                'event_onset_mono': onset,
                'clock_origin_mono': self.mono_origin,
                'clock_origin_utc_ms': round(self.wall_origin*1000),
            })
            self.event_sequence += 1
            if self.gc_window and onset is not None and last is not None:
                sample.update(self.gc_window.related(onset,last))
            if len(self.live_events) == self.LIVE_LIMIT:
                self.live_dropped += 1
            self.live_events.append(dict(sample))
        self.run_gap_context = None
        self.run_end_clock = None

    def break_sequence(self, reason='boundary'):
        super().break_sequence(reason)
        self.last_large_gap = None
        self.run_gap_context = None

    def take_events(self, limit=4):
        """Called on the asyncio loop; the AudioPlayer thread never logs."""
        output = []
        for _ in range(min(max(0,int(limit)), self.LIVE_LIMIT)):
            if not self.live_events:
                break
            output.append(self.live_events.popleft())
        self.live_emitted += len(output)
        return output

    def close(self):
        if self.gc_window:
            self.gc_window.close()

    def summary(self):
        try:
            base = super().summary()
            base.update({
                'schema_version':2,
                'source_read_recent_gap_window_frames': self.GAP_FRAMES,
                'source_read_recent_gap_window_ms':self.GAP_SECONDS*1000,
                'source_read_live_emitted':self.live_emitted,
                'source_read_live_dropped':self.live_dropped,
                'source_read_live_pending':len(self.live_events),
                'source_read_live_suppressed':self.live_suppressed,
                'gc_status':'instrumented' if self.gc_window else 'not_instrumented',
                'gc_dropped':self.gc_window.dropped if self.gc_window else None,
                'packet_send_status':'not_instrumented',
                'socket_send_status':'not_instrumented',
            })
            return base
        finally:
            self.close()
