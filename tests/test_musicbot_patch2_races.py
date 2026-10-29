"""Exercise real MusicPlayer commands across controlled async boundaries."""
import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

import musicbot.player as runtime
import musicbot.entry as entry_runtime
import musicbot.bot as bot_runtime
from musicbot.bot import MusicBot
import test_playback_prefetch as prefetch
import test_loudness_normalization as loudness


class PlaybackGenerationRaceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        prefetch.PrefetchTests.setUp(self)
        self.enterContext(patch.object(entry_runtime, 'log', loudness.FakeLog()))
        self.enterContext(patch.object(bot_runtime, '_D', lambda message, ssd: message))
        self.players, self.counters, self.tasks = [], [], []
        case = self

        class TrackedCounter(runtime.SourcePlaybackCounter):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                case.counters.append(self)

        class Opus(prefetch.DelayedOpus):
            delay = 0
            packets = 200

        self.opus = Opus
        self.enterContext(patch.multiple(
            runtime, Thread=loudness.FakeThread, FFmpegOpusAudio=Opus,
            FFmpegPCMAudio=prefetch.DelayedPCM, SourcePlaybackCounter=TrackedCounter,
        ))

    async def asyncTearDown(self):
        for player in self.players:
            player.kill()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        for counter in self.counters:
            counter.cleanup()
            self.assertTrue(await asyncio.to_thread(counter._worker_done.wait, 1))

    def fixture(self):
        player, entry, voice = prefetch.DisconnectPlaybackTests.fixture(self)
        self.players.append(player)
        player.bot.config.save_videos = True
        player.bot.config.auto_playlist = False
        player.bot.config.enable_queue_history_global = False
        player.bot.config.enable_queue_history_guilds = False
        create = player.bot.create_task

        def create_task(coro, **kwargs):
            create(coro, **kwargs)
            return None  # Real MusicBot.create_task also returns None.

        player.bot.create_task = create_task
        return player, entry, voice

    async def until(self, predicate):
        async with asyncio.timeout(2):
            while not predicate():
                await asyncio.sleep(.001)

    async def run_player(self, player):
        await runtime.MusicPlayer._play(player)

    async def paused_download(self, player, *, suppress_cancel=False, fail=False):
        selected, release = asyncio.Event(), asyncio.Event()
        original = player.playlist.get_next_entry

        async def get_next_entry():
            entry = await original()
            if not selected.is_set():
                selected.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    if not suppress_cancel:
                        raise
                    await release.wait()
                if fail:
                    raise OSError('late download error')
            return entry

        player.playlist.get_next_entry = AsyncMock(side_effect=get_next_entry)
        task = asyncio.create_task(self.run_player(player))
        self.tasks.append(task)
        await asyncio.wait_for(selected.wait(), 1)
        return task, release

    async def paused_probe(self, player):
        entered, release = asyncio.Event(), asyncio.Event()
        player.bot.config.use_opus_probe = True
        entry = player.playlist.peek()
        entry.probed_codec = entry.probed_bitrate = None

        async def probe(*args, **kwargs):
            if not entered.is_set():
                entered.set()
                await release.wait()
            return 'opus', 128

        self.enterContext(patch.object(self.opus, 'probe', side_effect=probe))
        task = asyncio.create_task(self.run_player(player))
        self.tasks.append(task)
        await asyncio.wait_for(entered.wait(), 1)
        return task, release

    async def test_stop_during_download_never_starts_stale_entry(self):
        player, _, voice = self.fixture()
        task, release = await self.paused_download(player)
        player.stop()
        await asyncio.wait_for(task, 1)
        self.assertFalse(release.is_set())
        voice.play.assert_not_called()
        self.assertTrue(player.is_stopped)
        self.assertIsNone(player.current_entry)
        self.assertIsNone(player._source)
        self.assertEqual(player.playlist.peek().title, 'Following queued track')

    async def test_skip_during_download_starts_next_before_old_download_finishes(self):
        player, _, voice = self.fixture()
        task, release = await self.paused_download(player)
        player.skip()
        await asyncio.wait_for(task, 1)
        await self.until(lambda: voice.play.called)
        self.assertFalse(release.is_set())
        voice.play.assert_called_once()
        self.assertEqual(player.current_entry.title, 'Following queued track')

    async def test_stop_during_probe_never_creates_stale_source(self):
        player, _, voice = self.fixture()
        task, release = await self.paused_probe(player)
        player.stop()
        await asyncio.wait_for(task, 1)
        self.assertFalse(release.is_set())
        voice.play.assert_not_called()
        self.assertEqual(self.counters, [])
        self.assertIsNone(player.current_entry)

    async def test_skip_during_probe_schedules_next_track(self):
        player, _, voice = self.fixture()
        task, release = await self.paused_probe(player)
        player.skip()
        await asyncio.wait_for(task, 1)
        await self.until(lambda: voice.play.called)
        self.assertFalse(release.is_set())
        self.assertEqual(player.current_entry.title, 'Following queued track')
        voice.play.assert_called_once()

    async def test_stop_then_immediate_play_is_not_lost(self):
        player, _, voice = self.fixture()
        task, release = await self.paused_download(player)
        player.stop()
        player.play(_continue=True)
        await asyncio.wait_for(task, 1)
        await self.until(lambda: voice.play.called)
        self.assertFalse(release.is_set())
        self.assertEqual(player.current_entry.title, 'Following queued track')
        voice.play.assert_called_once()

    async def test_skip_then_stop_does_not_pop_next_entry(self):
        player, _, voice = self.fixture()
        task, _ = await self.paused_download(player)
        player.skip()
        player.stop()
        await asyncio.wait_for(task, 1)
        await asyncio.gather(*self.tasks, return_exceptions=True)
        voice.play.assert_not_called()
        self.assertEqual(player.playlist.peek().title, 'Following queued track')
        self.assertTrue(player.is_stopped)

    async def test_two_immediate_skips_do_not_drop_an_extra_entry(self):
        player, _, voice = self.fixture()
        task, _ = await self.paused_download(player)
        player.skip()
        player.skip()
        await asyncio.wait_for(task, 1)
        await self.until(lambda: voice.play.called)
        self.assertEqual(player.current_entry.title, 'Following queued track')
        voice.play.assert_called_once()
        self.assertEqual(list(player.playlist.entries), [])

    async def test_repeated_play_requests_do_not_consume_extra_entries(self):
        player, entry, voice = self.fixture()
        for _ in range(10):
            player.play(_continue=True)
        await self.until(lambda: voice.play.called)
        self.assertIs(player.current_entry, entry)
        self.assertEqual(player.playlist.peek().title, 'Following queued track')
        voice.play.assert_called_once()

    async def test_cancelled_ready_wait_does_not_cancel_underlying_download(self):
        player, entry, voice = self.fixture()
        entered, release, downloaded = asyncio.Event(), asyncio.Event(), asyncio.Event()
        entry._is_downloaded = False

        async def download():
            entered.set()
            await release.wait()
            entry._is_downloaded = True
            entry._for_each_future(lambda future: future.set_result(entry))
            downloaded.set()

        entry._download = download
        player.play()
        await asyncio.wait_for(entered.wait(), 1)
        tasks = list(entry._task_pool)
        player.skip()
        await self.until(lambda: voice.play.called)
        self.assertFalse(downloaded.is_set())
        self.assertTrue(all(not task.cancelled() and not task.done() for task in tasks))
        release.set()
        await asyncio.wait_for(downloaded.wait(), 1)
        await asyncio.gather(*tasks)
        self.assertEqual(player.current_entry.title, 'Following queued track')
        voice.play.assert_called_once()

    async def test_stubborn_old_download_cannot_mutate_new_intent(self):
        player, _, voice = self.fixture()
        task, release = await self.paused_download(player, suppress_cancel=True)
        player.stop()
        player.play(_continue=True)
        await asyncio.sleep(0)
        release.set()
        await asyncio.wait_for(task, 1)
        await self.until(lambda: voice.play.called)
        self.assertEqual(player.current_entry.title, 'Following queued track')
        voice.play.assert_called_once()

    async def test_stale_download_error_is_not_reported_as_new_failure(self):
        player, _, voice = self.fixture()
        task, release = await self.paused_download(player, suppress_cancel=True, fail=True)
        player.stop()
        player.play(_continue=True)
        await asyncio.sleep(0)
        release.set()
        await asyncio.wait_for(task, 1)
        await self.until(lambda: voice.play.called)
        self.assertFalse(any(call.args[0] == 'error' for call in player.emit.call_args_list))
        self.assertEqual(player.current_entry.title, 'Following queued track')

    async def test_stop_during_prepare_joins_continuous_worker(self):
        player, _, voice = self.fixture()
        self.opus.block = True
        player.play()
        await self.until(lambda: player._preparing_source is not None
                         and player._preparing_source._source.started.is_set())
        counter, task = player._preparing_source, player._play_task
        player.stop()
        await asyncio.wait_for(task, 1)
        self.assertTrue(counter._worker_done.is_set())
        self.assertTrue(counter._source.cleaned.is_set())
        self.assertTrue(counter._source.stderr.closed)
        self.assertFalse(player._play_lock.locked())
        voice.play.assert_not_called()

    async def test_disconnect_during_probe_restores_selected_entry(self):
        player, entry, voice = self.fixture()
        task, release = await self.paused_probe(player)
        voice.is_connected.return_value = False
        release.set()
        await asyncio.wait_for(task, 1)
        self.assertEqual(list(player.playlist.entries)[0], entry)
        self.assertEqual(len(player.playlist.entries), 2)
        voice.play.assert_not_called()
        self.assertEqual(self.counters, [])
        player.bot.serialize_queue.assert_awaited_once()
        self.assertIsNone(player._pending_seek)

    async def test_real_download_error_keeps_error_and_next_track_paths(self):
        player, entry, voice = self.fixture()
        entry.author = Mock(id=456)
        original = player.playlist.get_next_entry

        async def fail():
            await original()
            raise OSError('real download failure')

        player.playlist.get_next_entry = fail
        await self.run_player(player)
        error = next(call for call in player.emit.call_args_list if call.args[0] == 'error')
        self.assertIs(error.kwargs['entry'], entry)
        self.assertIsInstance(error.kwargs['ex'], OSError)
        self.assertEqual(player.playlist.peek().title, 'Following queued track')
        player.playlist.get_next_entry = original
        await MusicBot.on_player_error(
            player.bot, player, entry, error.kwargs['ex']
        )
        await self.until(lambda: voice.play.called)
        self.assertEqual(player.current_entry.title, 'Following queued track')

    async def test_late_audio_thread_callback_cannot_stop_replacement(self):
        player, _, voice = self.fixture()
        await self.run_player(player)
        old_after = voice.play.call_args.kwargs['after']
        old_stderr = player._stderr_future
        player.stop()
        player.play(_continue=True)
        await self.until(lambda: voice.play.call_count == 2)
        current, source = player.current_entry, player._source
        await asyncio.to_thread(old_after, None)
        await asyncio.sleep(0)
        self.assertIs(player.current_entry, current)
        self.assertIs(player._source, source)
        self.assertTrue(player.is_playing)
        self.assertTrue(old_stderr.done())
        self.assertFalse(player._stderr_future.done())

    async def test_skip_then_stop_live_callback_does_not_continue(self):
        player, _, voice = self.fixture()
        await self.run_player(player)
        after = voice.play.call_args.kwargs['after']
        player.emit.reset_mock()
        player.skip()
        player.stop()
        await asyncio.to_thread(after, None)
        await self.until(lambda: player.current_entry is None)
        self.assertTrue(player.is_stopped)
        self.assertFalse(any(call.args[0] == 'finished-playing' for call in player.emit.call_args_list))
        self.assertEqual(player.playlist.peek().title, 'Following queued track')

    async def seek(self, player, voice, position):
        await MusicBot.cmd_seek(player.bot, None, voice.guild, player, [], str(position))

    async def test_latest_of_three_seeks_during_probe_retains_pause(self):
        for paused in (False, True):
            with self.subTest(paused=paused):
                player, entry, voice = self.fixture()
                await self.run_player(player)
                if paused:
                    player.pause()
                old_after = voice.play.call_args.kwargs['after']
                await self.seek(player, voice, 20)
                old_after(None)
                self.assertIsNone(player.current_entry)
                entered, release = asyncio.Event(), asyncio.Event()
                player.bot.config.use_opus_probe = True
                entry.probed_codec = entry.probed_bitrate = None

                async def probe(*args, **kwargs):
                    if not entered.is_set():
                        entered.set()
                        await release.wait()
                    return 'opus', 128

                with patch.object(self.opus, 'probe', side_effect=probe):
                    player.play(_continue=True)
                    await asyncio.wait_for(entered.wait(), 1)
                    await self.seek(player, voice, 40)
                    await self.seek(player, voice, 60)
                    await self.until(lambda: voice.play.call_count == 2)
                self.assertIs(player.current_entry, entry)
                self.assertEqual(player._source.progress, 60)
                self.assertEqual(player.is_paused, paused)
                self.assertIsNone(player._pending_seek)
                self.assertEqual(len(player.playlist.entries), 1)
                self.assertNotIn(entry, player.playlist.entries)
                self.assertEqual(player.playlist.peek().title, 'Following queued track')
                player.kill()

    async def test_latest_seek_during_prepare_cleans_old_reader(self):
        player, entry, voice = self.fixture()
        await self.run_player(player)
        old_after = voice.play.call_args.kwargs['after']
        await self.seek(player, voice, 20)
        old_after(None)
        self.opus.block = True
        player.play(_continue=True)
        await self.until(lambda: player._preparing_source is not None
                         and player._preparing_source._source.started.is_set())
        stale = player._preparing_source
        self.opus.block = False
        await self.seek(player, voice, 40)
        await self.seek(player, voice, 60)
        await self.until(lambda: voice.play.call_count == 2)
        self.assertTrue(stale._worker_done.is_set())
        self.assertTrue(stale._source.stderr.closed)
        self.assertIs(player.current_entry, entry)
        self.assertEqual(player.progress, 60)
        self.assertEqual(len(player.playlist.entries), 1)

    async def test_stop_then_play_during_prepare_releases_old_worker(self):
        player, _, voice = self.fixture()
        self.opus.block = True
        player.play()
        await self.until(lambda: player._preparing_source is not None
                         and player._preparing_source._source.started.is_set())
        stale = player._preparing_source
        player.stop()
        self.opus.block = False
        player.play(_continue=True)
        await self.until(lambda: voice.play.called)
        self.assertTrue(stale._worker_done.is_set())
        self.assertEqual(player.current_entry.title, 'Following queued track')
        voice.play.assert_called_once()

    async def test_stop_before_scheduled_task_runs_preserves_entire_queue(self):
        player, entry, voice = self.fixture()
        player.play()
        player.stop()
        await asyncio.gather(*self.tasks)
        voice.play.assert_not_called()
        self.assertEqual(list(player.playlist.entries)[0], entry)
        self.assertEqual(len(player.playlist.entries), 2)

    async def test_natural_audio_thread_finish_still_continues_once(self):
        player, _, voice = self.fixture()
        await self.run_player(player)
        after = voice.play.call_args.kwargs['after']
        emit = player.emit

        def finish(event, **data):
            emit(event, **data)
            if event == 'finished-playing':
                player.play(_continue=True)

        player.emit = finish
        await asyncio.to_thread(after, None)
        await self.until(lambda: voice.play.call_count == 2)
        self.assertEqual(player.current_entry.title, 'Following queued track')
        self.assertEqual(sum(call.args[0] == 'finished-playing'
                             for call in emit.call_args_list), 1)

    async def test_stale_probe_error_does_not_replace_new_request(self):
        player, entry, voice = self.fixture()
        player.bot.config.use_opus_probe = True
        entry.probed_codec = entry.probed_bitrate = None
        entered, release = asyncio.Event(), asyncio.Event()

        async def probe(*args, **kwargs):
            if entered.is_set():
                return 'opus', 128
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            raise OSError('late probe error')

        with patch.object(self.opus, 'probe', side_effect=probe):
            player.play()
            await entered.wait()
            player.stop()
            player.play(_continue=True)
            await asyncio.sleep(0)
            release.set()
            await self.until(lambda: voice.play.called)
        self.assertEqual(player.current_entry.title, 'Following queued track')
        self.assertFalse(any(call.args[0] == 'error' for call in player.emit.call_args_list))

    async def test_cancelled_disconnect_serialization_does_not_clear_new_source(self):
        player, entry, voice = self.fixture()
        entered, release = asyncio.Event(), asyncio.Event()

        async def serialize(guild):
            entered.set()
            await release.wait()

        player.bot.serialize_queue = serialize
        voice.is_connected.return_value = False
        player.play()
        await asyncio.wait_for(entered.wait(), 1)
        player.stop()
        voice.is_connected.return_value = True
        player.play(_continue=True)
        await self.until(lambda: voice.play.called)
        self.assertFalse(release.is_set())
        self.assertIs(player.current_entry, entry)
        self.assertEqual(player.playlist.peek().title, 'Following queued track')
        self.assertTrue(player.is_playing)


if __name__ == '__main__':
    unittest.main()
