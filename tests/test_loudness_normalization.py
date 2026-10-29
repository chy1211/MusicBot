"""Loudness regression and integration tests.

The AST harness exercises filter control flow with lightweight stand-ins.
RealModuleLoudnessTests imports actual entry/player modules with installed
Discord and yt-dlp dependencies, without connecting to a Discord service.
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

    async def prepare(self, timeout=10):
        pass

    def start_streaming(self):
        pass


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

    def is_connected(self):
        return True

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
        FIRST_FRAME_TIMEOUT=10,
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



class RealModuleLoudnessTests(unittest.IsolatedAsyncioTestCase):
    """Import real modules; stub only the external playback boundaries."""

    def setUp(self):
        import musicbot.entry as entry_module
        import musicbot.player as player_module
        self.entry_module = entry_module
        self.player_module = player_module

    def entry(self, kind="URLPlaylistEntry"):
        from musicbot.downloader import YtdlpResponseDict
        bot = SimpleNamespace(config=SimpleNamespace(default_speed=1.0, save_videos=True),
                              downloader=None, filecache=None)
        playlist = SimpleNamespace(bot=bot)
        info = YtdlpResponseDict(dict(
            url="https://example.invalid/demo", webpage_url="https://example.invalid/demo",
            title="DemoUser track", duration=180, extractor="generic",
            __input_subject="https://example.invalid/demo",
            __expected_filename="/tmp/demo.ogg"))
        entry = getattr(self.entry_module, kind)(playlist, info)
        entry.filename = "/tmp/demo.ogg"
        return entry

    async def play(self, entry, player=None, **kwargs):
        from unittest.mock import patch
        player = player or FakePlayer(entry, **kwargs)
        with patch.multiple(self.player_module, log=FakeLog(), Thread=FakeThread,
                            FFmpegOpusAudio=FakeOpus, FFmpegPCMAudio=FakePCM,
                            PCMVolumeTransformer=FakeTransformer,
                            SourcePlaybackCounter=FakePlaybackCounter):
            await self.player_module.MusicPlayer._play(player)
        return player

    async def test_real_import_and_filter_order(self):
        self.assertEqual(self.player_module.URLPlaylistEntry, self.entry_module.URLPlaylistEntry)
        entry = self.entry()
        entry.set_audio_filter("volume", "0.15")
        entry.set_audio_filter("loudnorm", LOUDNORM_TARGET)
        player = await self.play(entry)
        self.assertIn(f"-af loudnorm={LOUDNORM_TARGET},volume=0.15",
                      player.voice_client.last.source.kwargs["options"])

    async def test_real_probe_stream_keeps_volume_and_encodes(self):
        entry = self.entry("StreamPlaylistEntry")
        entry.set_audio_filter("loudnorm", LOUDNORM_TARGET)
        player = await self.play(entry, probe=True)
        source = player.voice_client.last.source
        self.assertIn("-af volume=0.15", source.kwargs["options"])
        self.assertNotIn("loudnorm", source.kwargs["options"])
        self.assertIsNone(source.kwargs["codec"])

    async def test_real_probe_url_still_omits_filters(self):
        player = await self.play(self.entry(), probe=True)
        self.assertNotIn("-af", player.voice_client.last.source.kwargs["options"])

    async def test_real_persistent_queue_old_and_new_aoptions_are_not_reused(self):
        for kind in ("URLPlaylistEntry", "LocalFilePlaylistEntry"):
            entry = self.entry(kind)
            entry._is_downloaded = True
            entry.set_audio_filter("loudnorm", LOUDNORM_TARGET)
            entry.set_audio_filter("volume", "0.15")
            raw = entry.__json__()["data"]
            self.assertIn("aoptions", raw)
            for old in (None, "-af volume=1.9", "-af loudnorm=I=-16,volume=0.99"):
                legacy = dict(raw)
                if old is None:
                    legacy.pop("aoptions")
                else:
                    legacy["aoptions"] = old
                restored = type(entry)._deserialize(legacy, playlist=entry.playlist)
                self.assertIsNotNone(restored)
                self.assertEqual(restored._a_filters, {})
                self.assertFalse(restored.is_downloaded)
                if kind == "LocalFilePlaylistEntry":
                    self.assertEqual(restored.filename, "/tmp/demo.ogg")
                player = await self.play(restored, volume=0.35)
                options = player.voice_client.last.source.kwargs["options"]
                self.assertEqual(options.count("loudnorm="), 1)
                self.assertEqual(options.count("volume="), 1)
                self.assertIn("volume=0.35", options)

    async def test_real_volume_command_restarts_with_new_volume_and_measurements(self):
        from unittest.mock import patch
        from musicbot.bot import MusicBot
        import musicbot.bot as bot_module
        entry = self.entry()
        measured = measured_loudnorm_filter(LoudnessTests.fixture())
        entry.set_audio_filter("loudnorm", measured)
        player = FakePlayer(entry)
        player.current_entry, player.progress, player.is_playing = entry, 17.5, True
        requeued, skips = [], []
        player.playlist.insert_entry_at_index = lambda index, item: requeued.append(item)
        player.skip = lambda: skips.append(True)
        bot = SimpleNamespace(config=SimpleNamespace(use_opus_audio=True))
        with patch.object(bot_module, "_D", lambda text, ssd: text):
            await MusicBot.cmd_volume(bot, None, player, "35")
        self.assertEqual(requeued, [entry])
        self.assertEqual(skips, [True])
        self.assertEqual(entry.start_time, 17.5)
        await self.play(entry, player=player)
        options = player.voice_client.last.source.kwargs
        self.assertIn("-ss 17.5", options["before_options"])
        self.assertIn("volume=0.35", options["options"])
        self.assertEqual(options["options"].count("loudnorm="), 1)
        self.assertEqual(entry._a_filters["loudnorm"], measured)

    async def test_real_seek_reuses_twopass_measurements(self):
        from unittest.mock import patch, AsyncMock
        from musicbot.bot import MusicBot
        import musicbot.bot as bot_module
        entry = self.entry()
        entry._is_downloaded = True
        measured = measured_loudnorm_filter(LoudnessTests.fixture())
        entry.set_audio_filter("loudnorm", measured)
        player = FakePlayer(entry, volume=0.35)
        player.current_entry, player.progress = entry, 12.0
        player.playlist.insert_entry_at_index = lambda index, item: None
        player.skip = lambda: None
        bot = SimpleNamespace(config=SimpleNamespace(
            enable_queue_history_global=False, enable_queue_history_guilds=False))
        with patch.object(bot_module, "_D", lambda text, ssd: text):
            await MusicBot.cmd_seek(bot, None, SimpleNamespace(id=1), player, [], "42.5")
        with patch.object(entry, "get_mean_volume", new_callable=AsyncMock) as analysis:
            self.assertIs(await entry.get_ready_future(), entry)
            await self.play(entry, player=player)
            analysis.assert_not_awaited()
        options = player.voice_client.last.source.kwargs
        self.assertIn("-ss 42.5", options["before_options"])
        self.assertEqual(options["options"].count("loudnorm="), 1)
        self.assertEqual(options["options"].count("volume="), 1)
        self.assertIn("volume=0.35", options["options"])
        self.assertEqual(entry._a_filters["loudnorm"], measured)

    async def test_real_equalization_disabled_clears_retained_filter(self):
        entry = self.entry()
        entry.set_audio_filter("loudnorm", LOUDNORM_TARGET)
        player = await self.play(entry, eq=False)
        self.assertNotIn("loudnorm", player.voice_client.last.source.kwargs["options"])
        self.assertIn("volume=0.15", player.voice_client.last.source.kwargs["options"])

    async def test_real_failed_reanalysis_clears_measurements(self):
        from unittest.mock import patch, AsyncMock
        entry = self.entry()
        entry.set_audio_filter("loudnorm", measured_loudnorm_filter(LoudnessTests.fixture()))
        with patch.object(self.entry_module, "run_command", new_callable=AsyncMock,
                          return_value=b"invalid ffmpeg output"):
            await entry.get_mean_volume(entry.filename)
        self.assertFalse(entry.has_audio_filter("loudnorm"))
        player = await self.play(entry)
        self.assertIn(f"loudnorm={LOUDNORM_TARGET},volume=0.15",
                      player.voice_client.last.source.kwargs["options"])

    async def test_real_analysis_command_ignores_video(self):
        from unittest.mock import patch, AsyncMock
        entry = self.entry()
        raw = LoudnessTests.fixture().encode()
        with patch.object(self.entry_module, "run_command", new_callable=AsyncMock,
                          return_value=raw) as command:
            await entry.get_mean_volume(entry.filename)
        argv = command.call_args.args[0]
        self.assertTrue(all(flag in argv for flag in ("-vn", "-sn", "-dn")))
        self.assertIn("measured_I=", entry._a_filters["loudnorm"])

    async def test_real_nonzero_analysis_exit_discards_even_valid_json(self):
        from unittest.mock import patch, AsyncMock
        entry = self.entry()
        process = SimpleNamespace(
            returncode=1,
            communicate=AsyncMock(return_value=(b"", LoudnessTests.fixture().encode())))
        with patch.object(self.entry_module.asyncio, "create_subprocess_exec",
                          new_callable=AsyncMock, return_value=process), \
                patch.object(self.entry_module, "log", FakeLog()):
            await entry.get_mean_volume(entry.filename)
        self.assertFalse(entry.has_audio_filter("loudnorm"))
        player = await self.play(entry)
        self.assertIn(f"loudnorm={LOUDNORM_TARGET},volume=0.15",
                      player.voice_client.last.source.kwargs["options"])

    async def test_real_analysis_spawn_failure_falls_back(self):
        from unittest.mock import patch, AsyncMock
        entry = self.entry()
        with patch.object(self.entry_module, "run_command", new_callable=AsyncMock,
                          side_effect=OSError("ffmpeg unavailable")):
            await entry.get_mean_volume(entry.filename)
        player = await self.play(entry)
        self.assertIn(f"loudnorm={LOUDNORM_TARGET}", player.voice_client.last.source.kwargs["options"])

    async def test_real_discord_opus_filter_outputs_48khz_packets(self):
        import discord
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "probe.ogg")
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            "sine=frequency=440:duration=4", "-ar", "48000",
                            "-ac", "2", "-c:a", "libopus", path], check=True)
            for filters in (f"loudnorm={LOUDNORM_TARGET},volume=0.15", "volume=0.15"):
                with tempfile.TemporaryFile() as error:
                    source = discord.FFmpegOpusAudio(path, codec=None,
                              options=f"-vn -af {filters}", stderr=error)
                    try:
                        self.assertEqual(source._process.args.count("-ar"), 1)
                        self.assertEqual(source._process.args[source._process.args.index("-ar")+1], "48000")
                        self.assertTrue(source.read(), filters)
                    finally:
                        source.cleanup()


if __name__ == "__main__":
    unittest.main()
