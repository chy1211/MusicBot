"""Actual SourcePlaybackCounter flow; no external audio, Discord or sleeps."""
import asyncio
import json
import logging
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from discord import AudioSource
from musicbot.player import SourcePlaybackCounter, MusicPlayer
from musicbot.read_cadence_diagnostics import ReadCadenceDiagnostics

logging.Logger.noise = logging.Logger.debug

class Packets(AudioSource):
    def __init__(self, frames=(b'one', b'two', b''), error=None):
        self.frames=iter(frames);self.error=error
    def read(self):
        if self.error:raise self.error
        return next(self.frames,b'')
    def cleanup(self):pass

def cadence(**kwargs):
    return ReadCadenceDiagnostics(session='synthetic',generation=3,track_id='neutral',**kwargs)

class CounterIntegrationTests(unittest.TestCase):
    def test_disabled_diagnostic_does_not_read_clock_or_change_packets(self):
        source=SourcePlaybackCounter(Packets())
        with patch('musicbot.player.time.monotonic',side_effect=AssertionError('disabled clock')):
            self.assertEqual([source.read(),source.read(),source.read()],[b'one',b'two',b''])
        self.assertEqual(source.frames,2)

    def test_observer_failure_preserves_audio_and_disables_instrumentation(self):
        broken=NS(observe=Mock(side_effect=RuntimeError('diagnostic only')))
        source=SourcePlaybackCounter(Packets(),cadence=broken)
        self.assertEqual(source.read(),b'one');self.assertEqual(source.read(),b'two')
        self.assertIsNone(source._cadence)

    def test_clock_failure_preserves_audio(self):
        source=SourcePlaybackCounter(Packets(),cadence=cadence())
        with patch('musicbot.player.time.monotonic',side_effect=RuntimeError('clock only')):
            self.assertEqual(source.read(),b'one')
        self.assertIsNone(source._cadence)

    def test_original_decoder_exception_is_preserved(self):
        error=OSError('decoder failure');source=SourcePlaybackCounter(Packets(error=error),cadence=cadence())
        with self.assertRaises(OSError) as caught:source.read()
        self.assertIs(caught.exception,error)
        self.assertEqual(source.cadence_summary()['source_read_sequence_resets']['read_error'],1)

    def test_control_reset_is_queued_and_drained_by_reader(self):
        monitor=cadence();source=SourcePlaybackCounter(Packets(),cadence=monitor)
        source.read();source.reset_cadence('pause');source.reset_cadence('resume')
        self.assertEqual(monitor.resets,{})
        source.read();summary=source.cadence_summary()
        self.assertEqual(summary['source_read_sequence_resets']['pause'],1)
        self.assertEqual(summary['source_read_sequence_resets']['resume'],1)
        self.assertIsNone(source.cadence_summary())

    def test_eof_is_not_counted_as_audio_and_flushes_pending_run(self):
        source=SourcePlaybackCounter(Packets(),cadence=cadence())
        source.read();source.read();source.read();summary=source.cadence_summary()
        self.assertEqual(summary['read_frames'],2)
        self.assertEqual(summary['source_read_sequence_resets']['eof_or_underrun'],1)

    def test_speed_adjusts_diagnostic_media_progress_only(self):
        monitor=cadence(media_offset_s=12,playback_speed=1.5)
        for frame,stamp in enumerate([0,.02,.04,.042,.044,.046,.066],1):monitor.observe(stamp,stamp,frame=frame)
        self.assertEqual(monitor.summary()['source_read_recent_samples'][0]['at_progress_ms'],12120)

    def test_reset_reason_storage_is_bounded(self):
        monitor=cadence()
        for index in range(100):monitor.break_sequence('unknown'+str(index))
        self.assertEqual(monitor.summary()['source_read_sequence_resets'],{'other':100})

class FinishedSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_or_dead_finished_source_emits_one_summary_without_state_mutation(self):
        for dead in [False,True]:
            source=SourcePlaybackCounter(Packets(),cadence=cadence());source.read()
            current=object();player=NS(loop=asyncio.get_running_loop(),is_dead=dead,_source=current)
            stderr=player.loop.create_future()
            with patch('musicbot.player.log') as log:
                MusicPlayer._playback_finished(player,source=source,stderr_future=stderr)
                MusicPlayer._playback_finished(player,source=source,stderr_future=stderr)
            self.assertTrue(stderr.done());self.assertIs(player._source,current)
            self.assertEqual(log.info.call_count,1)
            summary=json.loads(log.info.call_args.args[1]);self.assertEqual(summary['read_frames'],1)
