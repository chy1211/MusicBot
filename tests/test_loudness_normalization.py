"""Offline tests against the repository's actual entry/player method bodies.

The AST harness supplies Discord substitutes, but the real Python methods are
compiled from entry.py/player.py. No Discord service or downloaded dependency
is needed to exercise their control flow and FFmpeg filter arguments.
"""

import ast
import asyncio
import json
from functools import lru_cache
import math
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import List

from musicbot.loudness import LOUDNORM_TARGET, measured_loudnorm_filter

ROOT = Path(__file__).resolve().parents[1]


class FakeLog:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class FakeOpus:
    def __init__(self, filename, **kwargs):
        self.filename = filename
        self.kwargs = kwargs

    @staticmethod
    async def probe(*args, **kwargs):
        return "libopus", 128


class FakePCM(FakeOpus):
    pass


class FakeTransformer:
    def __init__(self, source, volume):
        self.source = source
        self.volume = volume


class FakePlaybackCounter:
    def __init__(self, source, **kwargs):
        self.source = source
        self.kwargs = kwargs


class FakeThread:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass


def load_source_method(path, class_name, method_name, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)
    target = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    method = next(n for n in target.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == method_name)
    code = compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(ROOT / path), "exec")
    exec(code, namespace)
    return namespace[method_name]


@lru_cache(maxsize=1)
def entry_runtime():
    from musicbot import loudness

    ns = dict(
        List=List,
        os=os,
        asyncio=asyncio,
        shutil=shutil,
        log=FakeLog(),
        LOUDNORM_TARGET=loudness.LOUDNORM_TARGET,
        measured_loudnorm_filter=loudness.measured_loudnorm_filter,
    )
    tree = ast.parse((ROOT / "musicbot/entry.py").read_text(encoding="utf-8"))
    run_command = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_command")
    exec(compile(ast.fix_missing_locations(ast.Module(body=[run_command], type_ignores=[])), "entry.py", "exec"), ns)

    class Entry:
        def __init__(self, filename=""):
            self.filename = str(filename)
            self._a_filters = {}
            self.probed_codec = ""
            self.probed_bitrate = 0
            self.start_time = 0
            self.playback_speed = 1.0
            self.boptions = ""

        @property
        def aoptions(self):
            return self.get_audio_filters()

    for name in ("set_audio_filter", "remove_audio_filter", "has_audio_filter", "get_audio_filters", "get_mean_volume"):
        setattr(Entry, name, load_source_method("musicbot/entry.py", "BasePlaylistEntry", name, ns))

    class URLPlaylistEntry(Entry):
        pass

    class LocalFilePlaylistEntry(Entry):
        pass

    class StreamPlaylistEntry(Entry):
        pass

    return ns, URLPlaylistEntry, LocalFilePlaylistEntry, StreamPlaylistEntry


class FakeVoice:
    def __init__(self):
        self.channel = SimpleNamespace(bitrate=128000)
        self.last = None

    def play(self, source, after):
        self.last = source


class FakePlaylist:
    def __init__(self, entry):
        self.entry = entry

    def peek(self):
        return self.entry

    async def get_next_entry(self):
        return self.entry


def make_player_runtime():
    ns, URL, Local, Stream = entry_runtime()
    import io

    ns.update(
        io=io,
        Thread=FakeThread,
        filter_stderr=lambda *args: None,
        MUSICBOT_VOICE_MAX_KBITRATE=128,
        FFmpegOpusAudio=FakeOpus,
        FFmpegPCMAudio=FakePCM,
        PCMVolumeTransformer=FakeTransformer,
        SourcePlaybackCounter=FakePlaybackCounter,
        MusicPlayerState=SimpleNamespace(PLAYING="playing"),
        URLPlaylistEntry=URL,
        LocalFilePlaylistEntry=Local,
        StreamPlaylistEntry=Stream,
    )
    play = load_source_method("musicbot/player.py", "MusicPlayer", "_play", ns)
    return play, URL, Local, Stream


class FakePlayer:
    def __init__(self, entry, eq=True, opus=True, probe=False, volume=0.15):
        self.bot = SimpleNamespace(config=SimpleNamespace(
            use_experimental_equalization=eq,
            use_opus_audio=opus,
            use_opus_probe=probe,
        ))
        self.playlist = FakePlaylist(entry)
        self.voice_client = FakeVoice()
        self.volume = volume
        self._play_lock = asyncio.Lock()
        self.is_dead = False
        self.guild_or_net_unavailable = False
        self.is_paused = False
        self.is_stopped = True
        self._current_player = None
        self._current_entry = None
        self._pending_seek = None
        self.events = []

    def _kill_current_player(self):
        self._current_player = None

    def _playback_finished(self, *args):
        pass

    def emit(self, event, **data):
        self.events.append(event)

    def pause(self):
        self.is_paused = True

    def stop(self):
        self.is_stopped = True


class LoudnessTests(unittest.TestCase):
    @staticmethod
    def fixture(**overrides):
        values = dict(input_i="-19.3", input_lra="3.1", input_tp="-1.4", input_thresh="-29.0", target_offset="-0.2")
        values.update(overrides)
        return "some ffmpeg messages\n" + json.dumps(values) + "\nend"

    def test_valid_measurements(self):
        opts = measured_loudnorm_filter(self.fixture())
        self.assertIn("measured_I=-19.3", opts)
        self.assertIn("measured_thresh=-29.0", opts)
        self.assertIn("offset=-0.2", opts)
        self.assertIn(LOUDNORM_TARGET, opts)

    def test_missing_or_corrupt_measurements_fallback(self):
        for output in ("", "not JSON", self.fixture(input_i=None), self.fixture(input_i="xyz"), self.fixture(target_offset=None)):
            with self.subTest(output=output[:50]):
                with self.assertRaises(ValueError):
                    measured_loudnorm_filter(output)

    def test_silence_nonfinite_measurements_fallback(self):
        for value in ("-inf", "inf", "NaN"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    measured_loudnorm_filter(self.fixture(input_i=value))

    def test_entry_filters_order_and_replace(self):
        _, URL, _, _ = entry_runtime()
        entry = URL()
        entry.set_audio_filter("volume", "0.15")
        entry.set_audio_filter("loudnorm", LOUDNORM_TARGET)
        entry.set_audio_filter("volume", "0.35")
        self.assertEqual(entry.get_audio_filters(), f"-af loudnorm={LOUDNORM_TARGET},volume=0.35")
        entry.remove_audio_filter("volume")
        self.assertFalse(entry.has_audio_filter("volume"))
        self.assertEqual(entry.get_audio_filters(), f"-af loudnorm={LOUDNORM_TARGET}")

    async def async_run(self, entry, **options):
        play, _, _, _ = make_player_runtime()
        player = FakePlayer(entry, **options)
        await play(player)
        return player

    def test_stream_opus_fallback_and_volume(self):
        _, _, _, Stream = entry_runtime()
        entry = Stream("http://127.0.0.1/media")
        p = asyncio.run(self.async_run(entry))
        self.assertEqual(p.events, ["play"])
        opts = p.voice_client.last.source.kwargs["options"]
        self.assertIn(f"loudnorm={LOUDNORM_TARGET},volume=0.15", opts)

    def test_stream_pcm_fallback_without_double_volume(self):
        _, _, _, Stream = entry_runtime()
        entry = Stream("http://127.0.0.1/media")
        entry.set_audio_filter("volume", "0.05")
        p = asyncio.run(self.async_run(entry, opus=False))
        self.assertIn(f"loudnorm={LOUDNORM_TARGET}", p.voice_client.last.source.source.kwargs["options"])
        self.assertNotIn("volume=", p.voice_client.last.source.source.kwargs["options"])
        self.assertEqual(p.voice_client.last.source.volume, 0.15)

    def test_download_preserves_twopass(self):
        _, URL, _, _ = entry_runtime()
        entry = URL("song.wav")
        entry.set_audio_filter("loudnorm", f"{LOUDNORM_TARGET}:linear=true:measured_I=-19")
        p = asyncio.run(self.async_run(entry))
        self.assertEqual(p.voice_client.last.source.kwargs["options"].count("loudnorm="), 1)
        self.assertIn("measured_I=-19", p.voice_client.last.source.kwargs["options"])

    def test_local_pcm_and_seek(self):
        _, _, Local, _ = entry_runtime()
        entry = Local("song.wav")
        entry.boptions = "-ss 4.0"
        p = asyncio.run(self.async_run(entry, opus=False))
        source = p.voice_client.last.source.source
        self.assertIn("-ss 4.0", source.kwargs["before_options"])
        self.assertIn(f"loudnorm={LOUDNORM_TARGET}", source.kwargs["options"])

    def test_probe_compat_disables_filters(self):
        _, URL, _, _ = entry_runtime()
        entry = URL("song.wav")
        p = asyncio.run(self.async_run(entry, probe=True))
        self.assertNotIn("-af", p.voice_client.last.source.kwargs["options"])
        self.assertFalse(entry.has_audio_filter("loudnorm"))

    def test_equalization_off_default_preserved(self):
        _, URL, _, _ = entry_runtime()
        entry = URL("song.wav")
        p = asyncio.run(self.async_run(entry, eq=False))
        opts = p.voice_client.last.source.kwargs["options"]
        self.assertIn("volume=0.15", opts)
        self.assertNotIn("loudnorm", opts)

    def test_repeat_changes_volume_without_filter_stacking(self):
        _, URL, _, _ = entry_runtime()
        entry = URL("song.wav")
        p1 = asyncio.run(self.async_run(entry, volume=0.15))
        p2 = asyncio.run(self.async_run(entry, volume=0.35))
        opts = p2.voice_client.last.source.kwargs["options"]
        self.assertEqual(opts.count("volume="), 1)
        self.assertEqual(opts.count("loudnorm="), 1)
        self.assertIn("volume=0.35", opts)

    def test_two_guild_players_keep_independent_volumes(self):
        _, URL, _, _ = entry_runtime()
        e1, e2 = URL("a.wav"), URL("b.wav")
        async def run_all():
            return await asyncio.gather(self.async_run(e1, volume=0.15), self.async_run(e2, volume=0.65))
        p1, p2 = asyncio.run(run_all())
        self.assertIn("volume=0.15", p1.voice_client.last.source.kwargs["options"])
        self.assertIn("volume=0.65", p2.voice_client.last.source.kwargs["options"])

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is missing")
    def test_real_local_download_calls_twopass_analysis(self):
        """Execute actual LocalFilePlaylistEntry._download from the repository."""
        import logging
        ns, _, Local, _ = entry_runtime()
        ns.update(pymediainfo=None, logging=logging)
        Local._download = load_source_method("musicbot/entry.py", "LocalFilePlaylistEntry", "_download", ns)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "local.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-y", str(path)], check=True, capture_output=True)
            entry = Local(path)
            entry._is_downloading = False
            entry._is_downloaded = False
            entry.duration = 4.0
            entry.playlist = SimpleNamespace(bot=SimpleNamespace(config=SimpleNamespace(
                use_experimental_equalization=True, use_opus_probe=False,
            )))
            callbacks = []
            entry._for_each_future = lambda callback: callback(SimpleNamespace(set_result=lambda value: callbacks.append(value)))
            asyncio.run(entry._download())
            self.assertTrue(entry._is_downloaded)
            self.assertEqual(callbacks, [entry])
            self.assertIn("measured_I", entry.get_audio_filters())
            self.assertIn("linear=true", entry.get_audio_filters())

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is missing")
    def test_real_url_download_cached_calls_twopass_analysis(self):
        """Execute actual URLPlaylistEntry._download with a cached audio file."""
        import logging
        ns, URL, _, _ = entry_runtime()
        ns.update(pymediainfo=None, logging=logging)
        URL._download = load_source_method("musicbot/entry.py", "URLPlaylistEntry", "_download", ns)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cached.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-y", str(path)], check=True, capture_output=True)
            entry = URL(path)
            entry.expected_filename = str(path)
            entry.duration = 4.0
            entry._is_downloading = False
            entry._is_downloaded = False
            entry.info = SimpleNamespace(http_header=lambda key, default: path.stat().st_size)
            entry.filecache = SimpleNamespace(ensure_cache_dir_exists=lambda: None, get_if_cached=lambda name: str(path))
            async def no_extraction():
                return None
            entry._ensure_entry_info = no_extraction
            entry.playlist = SimpleNamespace(bot=SimpleNamespace(config=SimpleNamespace(
                use_experimental_equalization=True, use_opus_probe=False,
            )))
            callbacks = []
            entry._for_each_future = lambda callback: callback(SimpleNamespace(set_result=lambda value: callbacks.append(value)))
            asyncio.run(entry._download())
            self.assertTrue(entry._is_downloaded)
            self.assertEqual(callbacks, [entry])
            self.assertIn("measured_I", entry.get_audio_filters())

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is missing")
    def test_real_silent_audio_degrades_to_onepass(self):
        _, URL, _, _ = entry_runtime()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "silence.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=sample_rate=48000:channel_layout=mono", "-t", "4", "-y", str(path)], check=True, capture_output=True)
            entry = URL(path)
            asyncio.run(entry.get_mean_volume(str(path)))
            self.assertFalse(entry.has_audio_filter("loudnorm"))
            player = asyncio.run(self.async_run(entry))
            self.assertIn(f"loudnorm={LOUDNORM_TARGET}", player.voice_client.last.source.kwargs["options"])

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is missing")
    def test_actual_file_analysis_and_output(self):
        _, URL, _, _ = entry_runtime()
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            def audio_file(amp, name):
                path = temp / name
                with wave.open(str(path), "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(48000)
                    frames = bytearray()
                    for i in range(48000 * 4):
                        sample = int(amp * 28000 * math.sin(2 * math.pi * 440 * i / 48000))
                        frames.extend(sample.to_bytes(2, "little", signed=True))
                    wav.writeframes(frames)
                return path
            results=[]
            for amp in (0.9, 0.09):
                path = audio_file(amp, f"in_{amp}.wav")
                entry = URL(path)
                asyncio.run(entry.get_mean_volume(str(path)))
                self.assertIn("measured_I", entry.get_audio_filters())
                player = asyncio.run(self.async_run(entry))
                opts = player.voice_client.last.source.kwargs["options"]
                dest = temp / f"out_{amp}.ogg"
                cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(path), *shlex.split(opts), "-c:a", "libopus", str(dest)]
                subprocess.run(cmd, check=True, capture_output=True)
                measure = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(dest), "-af", f"loudnorm={LOUDNORM_TARGET}:print_format=json", "-f", "null", os.devnull], capture_output=True, text=True, check=True)
                data = json.loads(__import__('re').search(r'\{[^{}]*"input_i"[^{}]*\}', measure.stderr, __import__('re').DOTALL).group(0))
                results.append(float(data["input_i"]))
            self.assertLess(abs(results[0] - results[1]), 0.75, results)


if __name__ == "__main__":
    unittest.main()
