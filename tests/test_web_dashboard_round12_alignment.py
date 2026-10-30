"""Self-synthesized audio only; no YouTube/download/network access."""
import array
import asyncio
import math
import sys
import random
import tempfile
import time
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, AsyncMock, patch
from musicbot.web_dashboard_lyrics_store import LyricsStore
from musicbot.web_dashboard_lyrics_alignment import (
    AlignmentService, envelope, correlate, pcm, parse_silence,
    official_candidate, _worker, UNCERTAIN)

KEY="abcdefghijk"

def synthesis(path, intro=0):
    rng=random.Random(71)
    samples=array.array("h")
    if intro:
        speech=random.Random(93)
        samples.extend(speech.randrange(-10000,10000) for _ in range(8000*intro))
    for frame in range(40*20):
        amplitude=rng.uniform(.03,.65)*22000
        samples.extend(int(amplitude*math.sin(2*math.pi*(220+(frame%7)*70)*i/8000))
                       for i in range(400))
    with wave.open(str(path),"wb") as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(8000);out.writeframes(samples.tobytes())

class SignalTests(unittest.TestCase):
    def test_real_ffmpeg_envelopes_find_seven_seconds_of_non_silent_intro(self):
        with tempfile.TemporaryDirectory(prefix="musicbot-webtest-audio-") as directory:
            ref,mv=Path(directory)/"ref.wav",Path(directory)/"mv.wav"
            synthesis(ref);synthesis(mv,7)
            started=time.process_time()
            value=correlate(envelope(pcm(mv,90)),envelope(pcm(ref,60)))
            self.assertIsNotNone(value)
            self.assertAlmostEqual(value["offset"],7,delta=.1)
            self.assertGreaterEqual(value["confidence"],.82)
            print("SYNTH_ALIGNMENT",value,"python_cpu_seconds",round(time.process_time()-started,4))
    def test_low_correlation_constant_short_and_ambiguous_peaks_rejected(self):
        a,b=random.Random(1),random.Random(2)
        self.assertIsNone(correlate([a.random() for _ in range(1000)],[b.random() for _ in range(1000)]))
        self.assertIsNone(correlate([1]*1000,[1]*1000))
        self.assertIsNone(correlate([1]*40,[1]*40))
        periodic=[math.sin(i/5) for i in range(1000)]
        self.assertIsNone(correlate(periodic,periodic))
    def test_only_actual_opening_silence_is_accepted(self):
        self.assertEqual(parse_silence("silence_start: 0\nsilence_end: 7.01 | silence_duration: 7.01"),7.01)
        for text in ("silence_start: 5\nsilence_end: 7","silence_start: 0","silence_start: 0\nsilence_end: 31","no silence"):
            self.assertIsNone(parse_silence(text))
    def test_official_topic_requires_metadata_and_two_second_duration(self):
        row={"title":"Singer - Song (Official Audio)","channel":"Singer - Topic",
             "duration":180,"webpage_url":"https://www.youtube.com/watch?v="+KEY}
        self.assertIs(official_candidate([row],"Song","Singer",181),row)
        self.assertIsNone(official_candidate([dict(row,channel="Fan")],"Song","Singer",180))
        self.assertIsNone(official_candidate([dict(row,duration=190)],"Song","Singer",180))
        self.assertIsNone(official_candidate([dict(row,title="Other Song")],"Song","Singer",180))
    def test_no_official_audio_falls_to_silence_reusing_cache_without_cookie_file(self):
        instances=[]
        class FakeYDL:
            def __init__(self,params):
                self.params=params;self.constructed=dict(params);instances.append(self)
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def extract_info(self,*_,**__):return {"entries":[]}
        pipe=NS(send=Mock(),close=Mock())
        source=NS(params={"cookiefile":"NEVER_READ","proxy":"configured-exit"})
        with tempfile.TemporaryDirectory(prefix="musicbot-webtest-worker-") as directory:
            file=Path(directory)/"mv.wav";file.write_bytes(b"not needed")
            with patch("yt_dlp.YoutubeDL",FakeYDL),patch("musicbot.web_dashboard_lyrics_alignment.os.setsid"),patch("musicbot.web_dashboard_lyrics_alignment.silence",return_value=7) as silence:
                _worker(pipe,source,{"title":"Song","artist":"Singer","duration":180},str(file),directory)
            self.assertEqual(pipe.send.call_args.args[0]["source"],"silence")
            self.assertEqual(pipe.send.call_args.args[0]["offset"],7)
            silence.assert_called_once_with(file)
        self.assertEqual(source.params["cookiefile"],"NEVER_READ")
        self.assertNotIn("cookiefile",instances[0].constructed)
        self.assertEqual(instances[0].constructed["proxy"],"configured-exit")
        self.assertEqual(instances[0].constructed["max_filesize"],20*1024*1024)
        self.assertFalse(instances[0].constructed["cachedir"])

class JobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="musicbot-webtest-analysis-")
        self.store=LyricsStore(self.temp.name);self.service=AlignmentService(self.store)
        self.bot=NS(config=NS(),downloader=NS(unsafe_ytdl=NS(params={})))
        self.entry=NS(url="https://www.youtube.com/watch?v="+KEY,duration=187,filename="")
        self.lyrics={"title":"Song","artist":"Singer","duration":180}
    async def asyncTearDown(self):
        await self.service.close();self.temp.cleanup()
    async def drain(self):
        tasks=list(self.service.tasks.values())
        if tasks:await asyncio.gather(*tasks)
    async def test_duration_close_is_zero_and_never_runs_analysis(self):
        self.service.run_worker=AsyncMock()
        self.entry.duration=181
        value=await self.service.request(self.bot,self.entry,self.lyrics)
        self.assertEqual(value["source"],"duration_assumed");self.assertEqual(value["offset"],0);self.assertEqual(value["confidence"],0.25)
        self.service.run_worker.assert_not_awaited()
    async def test_timeout_caches_uncertainty_and_allows_event_loop(self):
        self.service.TIMEOUT=.03
        async def slow(*_):await asyncio.sleep(1)
        self.service.run_worker=slow
        value=await self.service.request(self.bot,self.entry,self.lyrics)
        self.assertTrue(value["pending"])
        await self.drain()
        self.assertEqual((await self.store.get(KEY,"analysis"))["source"],"uncertain")
        self.assertFalse((await self.service.request(self.bot,self.entry,self.lyrics))["pending"])
    async def test_parallel_limit_one_and_same_video_coalesces(self):
        active=peak=calls=0
        async def worker(*_):
            nonlocal active,peak,calls
            active+=1;calls+=1;peak=max(peak,active)
            await asyncio.sleep(.02);active-=1
            return {"offset":7,"source":"matched","confidence":1}
        self.service.run_worker=worker
        await self.service.request(self.bot,self.entry,self.lyrics)
        await self.service.request(self.bot,self.entry,self.lyrics)
        other=NS(url="https://www.youtube.com/watch?v=bbbbbbbbbbb",duration=187,filename="")
        await self.service.request(self.bot,other,self.lyrics);await self.drain()
        self.assertEqual(peak,1);self.assertEqual(calls,2)
    async def test_real_worker_process_is_killed_on_timeout(self):
        real=asyncio.create_subprocess_exec
        processes=[]
        async def blocked(*args,**kwargs):
            proc=await real(sys.executable,"-c","import time; time.sleep(10)",**kwargs)
            processes.append(proc);return proc
        # Allow process creation on a loaded runner; still kill the 10s worker.
        self.service.TIMEOUT=.5
        with patch("musicbot.web_dashboard_lyrics_alignment.asyncio.create_subprocess_exec",side_effect=blocked):
            await self.service.request(self.bot,self.entry,self.lyrics)
            await self.drain()
        self.assertEqual(len(processes),1)
        self.assertIsNotNone(processes[0].returncode)
        self.assertEqual((await self.store.get(KEY,"analysis"))["source"],"uncertain")
