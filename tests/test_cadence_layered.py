"""R22 synthetic timeline regressions (no real sleep, Discord or VPS)."""
import unittest
from musicbot.cadence_layered import GCWindow, LayeredReadCadenceDiagnostics


def readings(diagnostic, times):
    for index, start in enumerate(times, 1):
        diagnostic.observe(start, start+0.001, frame=index)
    diagnostic.break_sequence('finished')
    return diagnostic.summary()


def new():
    return LayeredReadCadenceDiagnostics(session='abcdef123456',generation=1,track_id='no-url',gc_enabled=False)


class TimelineTests(unittest.TestCase):
    def test_normal_20ms(self):
        s=readings(new(),[i*.02 for i in range(40)])
        self.assertEqual(s['source_read_bursts'],0)
        self.assertEqual(s['packet_send_status'],'not_instrumented')
        self.assertEqual(s['socket_send_status'],'not_instrumented')

    def test_without_recent_gap(self):
        s=readings(new(),[0,.02,.04,.042,.044,.046,.066])
        self.assertEqual(s['source_read_recent_samples'][-1]['gap_context'],'no_recent_gap')
        self.assertEqual(s['source_read_bursts'],1)

    def test_immediate_gap(self):
        s=readings(new(),[0,.02,.10,.102,.104,.106,.126])
        self.assertEqual(s['source_read_recent_samples'][-1]['gap_context'],'immediately_after_gap')
        self.assertEqual(s['source_read_after_large_gap_bursts'],1)

    def test_gap_then_normal_then_burst(self):
        s=readings(new(),[0,.02,.10,.12,.122,.124,.126,.146])
        event=s['source_read_recent_samples'][-1]
        self.assertEqual(event['gap_context'],'recent_gap')
        self.assertEqual(event['recent_gap_frame_distance'],2)
        self.assertEqual(s['source_read_independent_bursts'],1) # old semantics stay unchanged
        self.assertEqual(event['after_large_gap'],False)

    def test_boundary_prevents_gap_leak(self):
        d=new()
        for n,t in enumerate([0,.02,.1],1): d.observe(t,t+.001,frame=n)
        d.break_sequence('pause')
        for n,t in enumerate([5,5.002,5.004,5.006,5.026],4): d.observe(t,t+.001,frame=n)
        d.break_sequence('finished')
        self.assertEqual(d.summary()['source_read_recent_samples'][-1]['gap_context'],'no_recent_gap')

    def test_event_ids_bounded_and_total_exact(self):
        d=new()
        for i in range(21):
            values=[i, i+.02, i+.022,i+.024,i+.026,i+.046]
            for j,t in enumerate(values):d.observe(t,t+.0001,frame=i*6+j+1)
            d.break_sequence()
        self.assertEqual(d.episodes,21)
        self.assertEqual(len(d.live_events),12)
        self.assertEqual(d.live_dropped,9)
        drained=d.take_events(4)
        self.assertEqual(len(drained),4)
        self.assertEqual(len({x['event_id'] for x in drained}),4)
        self.assertEqual(d.summary()['source_read_bursts'],21)

    def test_event_queue_empty_is_not_a_packet_success(self):
        d=new()
        self.assertEqual(d.take_events(),[])
        self.assertEqual(d.summary()['packet_send_status'],'not_instrumented')


class GCWindowTests(unittest.TestCase):
    def test_actual_gc_start_stop_vs_log_time(self):
        clock=[1.0]
        g=GCWindow(clock=lambda:clock[0]);g._on_gc('start',{'generation':2})
        clock[0]=1.061;g._on_gc('stop',{'generation':2})
        near=g.related(1.04,1.07)
        self.assertEqual(near['gc_overlap_count'],1)
        self.assertGreater(near['gc_overlap_max_duration_ms'],60)
        # No relation to an arbitrarily late log emission timestamp.
        self.assertEqual(g.related(2.0,2.1)['gc_overlap_count'],0)

    def test_active_gc_and_nearby(self):
        clock=[1.0];g=GCWindow(clock=lambda:clock[0]);g._on_gc('start',{'generation':1})
        self.assertEqual(g.related(1.01,1.02)['gc_active_during_event'],1)
        clock[0]=1.03;g._on_gc('stop',{'generation':1})
        self.assertEqual(g.related(1.10,1.11)['gc_nearby_count'],1)

    def test_cleanup_only_own_callback(self):
        import gc
        existing=lambda phase,info:None
        gc.callbacks.append(existing)
        g=GCWindow();g.start();g.start()
        self.assertEqual(gc.callbacks.count(g._callback),1)
        g.close();g.close()
        self.assertIn(existing,gc.callbacks)
        self.assertNotIn(g._callback,gc.callbacks)
        gc.callbacks.remove(existing)

if __name__=='__main__': unittest.main()

class EndWindowTests(unittest.TestCase):
    def test_normal_interval_does_not_extend_event_gc_window(self):
        d=new()
        for n,t in enumerate([0,.02,.022,.024,.026,.046],1):d.observe(t,t+.001,frame=n)
        event=d.take_events()[0]
        self.assertAlmostEqual(event['event_end_mono'],.026)
