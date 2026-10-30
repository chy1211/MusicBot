import unittest
from musicbot.read_cadence_diagnostics import ReadCadenceDiagnostics

class CadenceTests(unittest.TestCase):
    def new(self):
        return ReadCadenceDiagnostics(session='ab1234',generation=7,track_id='f00d')
    def feed(self,m,times):
        for n,t in enumerate(times,1):m.observe(t,t+.001,frame=n)
        m.break_sequence()
        return m.summary()
    def test_regular(self):
        s=self.feed(self.new(),[i*.02 for i in range(40)])
        self.assertEqual(s['source_read_bursts'],0)
        self.assertEqual(s['source_read_interval_histogram']['15to25'],39)
    def test_independent_burst_below_60ms(self):
        s=self.feed(self.new(),[0,.02,.04,.042,.044,.046,.066])
        self.assertEqual(s['source_read_independent_bursts'],1)
        self.assertEqual(s['source_read_after_large_gap_bursts'],0)
        self.assertLess(s['source_read_max_interval_ms'],60)
    def test_after_large_gap(self):
        s=self.feed(self.new(),[0,.02,.11,.112,.114,.116,.136])
        self.assertEqual(s['source_read_after_large_gap_bursts'],1)
        self.assertEqual(s['source_read_independent_bursts'],0)
    def test_single_short_is_not_event(self):
        s=self.feed(self.new(),[0,.02,.022,.042,.062])
        self.assertEqual(s['source_read_bursts'],0)
    def test_break_sequence_prevents_pause_leak(self):
        m=self.new();self.feed(m,[0,.002,.004]);
        s=self.feed(m,[5,5.002,5.004]);self.assertEqual(s['source_read_bursts'],0)
    def test_eof_and_underruns_can_break_sequence(self):
        m=self.new();m.observe(0,.001,frame=1);m.observe(.002,.003,frame=2);m.break_sequence()
        m.observe(.004,.005,frame=3);m.observe(.006,.007,frame=4)
        self.assertEqual(m.summary()['source_read_bursts'],0)
    def test_bounded_event_samples_and_final_count(self):
        m=self.new();t=0
        for _ in range(20):
            for d in (0,.002,.004,.006,.03):
                m.observe(t+d,t+d+.0002,frame=m.frames+1)
            m.break_sequence();t+=.2
        s=m.summary();self.assertEqual(s['source_read_bursts'],20)
        self.assertEqual(len(s['source_read_recent_samples']),12)
        self.assertEqual(s['source_read_dropped_samples'],8)
    def test_read_duration_separate_from_invocation_interval(self):
        m=self.new();m.observe(0,.015,frame=1);m.observe(.02,.0205,frame=2)
        s=m.summary();self.assertEqual(s['source_read_max_duration_ms'],15)
        self.assertEqual(s['source_read_bursts'],0)
        self.assertEqual(s['packet_send_status'],'not_instrumented')
    def test_progress_and_generation(self):
        m=self.new();s=self.feed(m,[0,.02,.04,.042,.044,.046,.066]);
        self.assertEqual(s['source_generation'],7)
        self.assertEqual(s['source_read_recent_samples'][0]['at_progress_ms'],80)
    def test_counter_does_not_change_frame_content(self):
        m=self.new();frame=b'fake-audio';m.observe(0,0,frame=1);self.assertEqual(frame,b'fake-audio')

if __name__=='__main__':unittest.main()
