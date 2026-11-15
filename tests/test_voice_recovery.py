"""Offline voice recovery state-machine and queue durability tests."""
import asyncio
import json
import os
import sys
import types
import tempfile
import time
import unittest
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from musicbot.voice_recovery import (
    VoiceRecoveryPolicy, preserve_voice_queue, recover_after_transport_loss,
    start_voice_recovery, voice_recovery_policy,
)


class RecoveryPolicyTests(unittest.TestCase):
    def test_code_1000_and_unknown_cause_never_auto_rejoin(self):
        policy = VoiceRecoveryPolicy()
        policy.gateway_lost(now=100)
        clean = policy.begin_incident(7, 70, voice_close_code=1000,
                                      queue_saved=True, now=101)
        self.assertIsNotNone(clean)
        self.assertFalse(clean.auto_allowed)
        self.assertTrue(policy.valid(clean, now=102))
        policy.gateway_lost(now=110)
        unknown = policy.begin_incident(7, 70, voice_close_code=None,
                                        queue_saved=True, now=111)
        self.assertFalse(unknown.auto_allowed)
        self.assertFalse(policy.valid(clean, now=112))
        policy.gateway_lost(now=119)
        kicked = policy.begin_incident(7, 70, voice_close_code=4014,
                                       queue_saved=True, now=120)
        self.assertFalse(kicked.auto_allowed)

    def test_abnormal_close_plus_recent_gateway_only(self):
        policy = VoiceRecoveryPolicy()
        self.assertFalse(policy.eligible(7, now=101))
        policy.gateway_lost(now=100)
        self.assertTrue(policy.eligible(7, now=105))
        incident = policy.begin_incident(7, 70, voice_close_code=1006,
                                         queue_saved=True, now=105)
        self.assertTrue(incident.auto_allowed)
        self.assertTrue(policy.valid(incident, now=106))
        self.assertFalse(policy.valid(incident, now=200))
        late = policy.begin_incident(7, 70, voice_close_code=1006,
                                     queue_saved=True, now=120)
        self.assertFalse(late.auto_allowed)
        policy.manual_leave(7, now=120)
        self.assertFalse(policy.valid(late, now=121))
        self.assertFalse(policy.eligible(7, now=121))

    def test_one_guild_manual_leave_does_not_cancel_another_guild(self):
        async def run():
            policy = VoiceRecoveryPolicy()
            policy.gateway_lost()
            first = policy.begin_incident(7, 70, voice_close_code=1006,
                                          queue_saved=True)
            second = policy.begin_incident(8, 80, voice_close_code=1006,
                                           queue_saved=True)
            event = asyncio.Event()
            a = asyncio.create_task(event.wait())
            b = asyncio.create_task(event.wait())
            policy.schedule(first, a)
            policy.schedule(second, b)
            policy.manual_leave(7)
            await asyncio.sleep(0)
            self.assertTrue(a.cancelled())
            self.assertTrue(policy.valid(second))
            self.assertFalse(b.cancelled())
            policy.manual_leave(8)
            await asyncio.sleep(0)
            self.assertTrue(b.cancelled())
        asyncio.run(run())

    def test_snapshot_failure_disables_restore_and_rejoin(self):
        policy = VoiceRecoveryPolicy()
        policy.gateway_lost(now=100)
        incident = policy.begin_incident(7, 70, voice_close_code=1006,
                                         queue_saved=False, now=101)
        self.assertIsNone(incident)
        self.assertFalse(policy.pending_restore)

    def test_incident_dedup_and_manual_leave_cancels_task(self):
        async def exercise():
            policy = VoiceRecoveryPolicy()
            policy.gateway_lost()
            incident = policy.begin_incident(7, 70, voice_close_code=1006,
                                             queue_saved=True)
            parked = asyncio.Event()
            task = asyncio.create_task(parked.wait())
            policy.schedule(incident, task)
            self.assertTrue(policy.has_running_job(7))
            second = policy.begin_incident(7, 70, voice_close_code=1006,
                                           queue_saved=True)
            await asyncio.sleep(0)
            self.assertTrue(task.cancelled())
            self.assertNotEqual(incident.generation, second.generation)
            self.assertFalse(policy.valid(incident))
            another = asyncio.create_task(parked.wait())
            policy.schedule(second, another)
            policy.manual_leave(7)
            await asyncio.sleep(0)
            self.assertTrue(another.cancelled())
            self.assertFalse(policy.valid(second))
            self.assertNotIn(7, policy.pending_restore)
        asyncio.run(exercise())

    def test_policy_is_reused_per_bot(self):
        bot = NS()
        self.assertIs(voice_recovery_policy(bot), voice_recovery_policy(bot))


class QueueSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.TemporaryDirectory(prefix="mb-recovery-")
        self.addCleanup(self.dir.cleanup)
        self.base = Path(self.dir.name)
        (self.base / "7").mkdir()
        self.guild = NS(id=7)
        self.payload = {
            "current_entry": {"entry": {"title": "Track A"}, "progress": 117},
            "entries": [{"title": "Next B"}, {"title": "Next C"}],
        }
        self.player = NS(serialize=Mock(return_value=json.dumps(self.payload)))
        self.bot = NS(
            config=NS(persistent_queue=True, data_path=self.base),
            aiolocks=defaultdict(asyncio.Lock),
            get_player_in=lambda guild: self.player,
        )

    async def test_atomic_queue_preserves_current_song_and_order(self):
        self.assertTrue(await preserve_voice_queue(self.bot, self.guild))
        target = self.base / "7" / "queue.json"
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")),
                         self.payload)
        self.player.serialize.assert_called_once_with(sort_keys=True)
        self.assertFalse(list(target.parent.glob("queue.json.recovery-*")))
        if os.name == 'posix':
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    async def test_two_guilds_snapshots_are_independent(self):
        (self.base / "8").mkdir()
        other = NS(id=8)
        other_player = NS(serialize=Mock(return_value=json.dumps({
            "current_entry": {"entry": {"title": "Track Z"}, "progress": 15},
            "entries": [{"title": "Next D"}],
        })))
        self.bot.get_player_in = lambda guild: (
            self.player if guild.id == 7 else other_player)
        results = await asyncio.gather(
            preserve_voice_queue(self.bot, self.guild),
            preserve_voice_queue(self.bot, other),
        )
        self.assertEqual(results, [True, True])
        a = json.loads((self.base / "7" / "queue.json").read_text(encoding="utf-8"))
        b = json.loads((self.base / "8" / "queue.json").read_text(encoding="utf-8"))
        self.assertEqual(a["current_entry"]["progress"], 117)
        self.assertEqual(b["current_entry"]["progress"], 15)
        self.assertNotEqual(a["entries"], b["entries"])

    async def test_failed_snapshot_does_not_truncate_previous_queue(self):
        target = self.base / "7" / "queue.json"
        target.write_text("old-safe-snapshot", encoding="utf-8")
        with patch("musicbot.voice_recovery.os.replace", side_effect=OSError("disk")):
            self.assertFalse(await preserve_voice_queue(self.bot, self.guild))
        self.assertEqual(target.read_text(encoding="utf-8"), "old-safe-snapshot")
        self.assertFalse(list(target.parent.glob("queue.json.recovery-*")))

    async def test_persistence_disabled_or_missing_player_does_nothing(self):
        self.bot.config.persistent_queue = False
        self.assertFalse(await preserve_voice_queue(self.bot, self.guild))
        self.bot.config.persistent_queue = True
        self.bot.get_player_in = lambda guild: None
        self.assertFalse(await preserve_voice_queue(self.bot, self.guild))
        self.assertFalse((self.base / "7" / "queue.json").exists())


class RecoveryExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.discord = types.ModuleType("discord")
        self.discord.VoiceChannel = type("VoiceChannel", (), {})
        self.discord.StageChannel = type("StageChannel", (), {})
        self.discord.ClientException = type("ClientException", (Exception,), {})
        self.discord.HTTPException = type("HTTPException", (Exception,), {})
        self.fake_exceptions = types.ModuleType("musicbot.exceptions")
        self.fake_exceptions.MusicbotException = type("MusicbotException", (Exception,), {})
        self.patch_modules = patch.dict(sys.modules, {
            "discord": self.discord, "musicbot.exceptions": self.fake_exceptions,
        })
        self.patch_modules.start()
        self.addCleanup(self.patch_modules.stop)

        self.guild = NS(id=7, voice_client=None)
        self.channel = self.discord.VoiceChannel()
        self.channel.guild = self.guild
        self.player = NS(is_stopped=True, playlist=[1, 2], play=Mock())
        self.policy = VoiceRecoveryPolicy()
        self.policy.gateway_lost()
        self.incident = self.policy.begin_incident(
            7, 70, voice_close_code=1006, queue_saved=True)
        self.assertTrue(self.incident.auto_allowed)
        self.bot = NS(
            logout_called=False,
            get_guild=lambda gid: self.guild if gid == 7 else None,
            get_channel=lambda cid: self.channel if cid == 70 else None,
            get_player_in=lambda guild: None,
            get_player=AsyncMock(return_value=self.player),
        )

    async def _run_no_sleep(self):
        async def no_sleep(seconds):
            return None
        with patch("asyncio.sleep", no_sleep):
            return await recover_after_transport_loss(self.bot, self.policy, self.incident)

    async def test_recovery_restores_queue_and_replays(self):
        self.assertTrue(await self._run_no_sleep())
        self.bot.get_player.assert_awaited_once_with(
            self.channel, create=True, deserialize=True)
        self.player.play.assert_called_once()
        self.assertFalse(self.policy.pending_restore)

    async def test_second_attempt_after_transport_failure(self):
        self.bot.get_player.side_effect = [self.discord.ClientException("once"),
                                            self.player]
        self.assertTrue(await self._run_no_sleep())
        self.assertEqual(self.bot.get_player.await_count, 2)

    async def test_manual_disconnect_during_reconnect_prevents_resurrection(self):
        async def manual(_channel, *, create, deserialize):
            self.policy.manual_leave(7)
            return self.player
        self.bot.get_player.side_effect = manual
        self.assertFalse(await self._run_no_sleep())
        self.player.play.assert_not_called()

    async def test_existing_new_player_or_connected_client_blocks_rejoin(self):
        self.bot.get_player_in = lambda guild: self.player
        self.assertFalse(await self._run_no_sleep())
        self.bot.get_player.assert_not_awaited()
        self.bot.get_player_in = lambda guild: None
        self.guild.voice_client = NS(is_connected=lambda: True)
        self.assertFalse(await self._run_no_sleep())
        self.bot.get_player.assert_not_awaited()

    async def test_channel_moved_or_not_visible_blocks_rejoin(self):
        self.channel.guild = NS(id=8)
        self.assertFalse(await self._run_no_sleep())
        self.bot.get_player.assert_not_awaited()

    async def test_restore_without_current_queue_does_not_autoplay(self):
        self.player.playlist = []
        self.assertTrue(await self._run_no_sleep())
        self.player.play.assert_not_called()

    async def test_bounded_retry_and_no_auto_on_clean_close(self):
        self.bot.get_player.side_effect = self.discord.HTTPException("unavailable")
        self.assertFalse(await self._run_no_sleep())
        self.assertEqual(self.bot.get_player.await_count, 2)
        self.bot.get_player.reset_mock()
        clean = self.policy.begin_incident(7, 70, voice_close_code=1000,
                                           queue_saved=True)
        self.assertFalse(await recover_after_transport_loss(self.bot, self.policy, clean))
        self.bot.get_player.assert_not_awaited()

    async def test_schedule_task_can_be_cancelled_by_manual_leave(self):
        logger = Mock()
        start_voice_recovery(self.bot, self.policy, self.incident, logger)
        self.assertTrue(self.policy.has_running_job(7))
        task = self.policy.jobs[7]
        self.policy.manual_leave(7)
        await asyncio.sleep(0)
        self.assertTrue(task.cancelled())
        self.assertNotIn(7, self.policy.jobs)
        self.assertNotIn(7, self.policy.pending_restore)


if __name__ == "__main__":
    unittest.main()
