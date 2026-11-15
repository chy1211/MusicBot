"""Conservative MusicBot voice recovery after an unexpected voice-state loss.

A Discord channel=None event (including WebSocket close 1000) is ambiguous:
it may be a moderator kick, permission removal, or transport disconnect.
Always preserve a recoverable queue snapshot before the existing player is
destroyed, but never rejoin an ambiguous event automatically.

Only an abnormal voice transport closure *and* a recent gateway outage allow
a bounded two-attempt auto-reconnect. A generation token and one-task-per-guild
limit prevent delayed jobs from undoing explicit disconnects or fresh sessions.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import DATA_GUILD_FILE_QUEUE


@dataclass(frozen=True)
class RecoveryIncident:
    guild_id: int
    channel_id: int
    generation: int
    started_at: float
    auto_allowed: bool


class VoiceRecoveryPolicy:
    GATEWAY_WINDOW_SECONDS = 15.0
    MANUAL_WINDOW_SECONDS = 45.0
    MAX_RECOVERY_SECONDS = 45.0
    RETRY_DELAYS_SECONDS = (1.0, 3.0)
    RECOVERY_TIMEOUT_SECONDS = 12.0

    def __init__(self) -> None:
        self.last_gateway_loss: float | None = None
        self.manual_leaves: dict[int, float] = {}
        self.generations: dict[int, int] = {}
        self.pending_restore: dict[int, RecoveryIncident] = {}
        self.jobs: dict[int, asyncio.Task[bool]] = {}
        self.handling: set[int] = set()

    def begin_handling(self, guild_id: int) -> bool:
        """Coalesce simultaneous voice-state events before any await."""
        if guild_id in self.handling:
            return False
        self.handling.add(guild_id)
        return True

    def end_handling(self, guild_id: int) -> None:
        self.handling.discard(guild_id)

    def gateway_lost(self, now: float | None = None) -> None:
        self.last_gateway_loss = time.monotonic() if now is None else now

    def manual_leave(self, guild_id: int, now: float | None = None) -> None:
        """An intentional leave must invalidate pending retries immediately."""
        self.manual_leaves[guild_id] = time.monotonic() if now is None else now
        self._invalidate(guild_id)

    def _invalidate(self, guild_id: int) -> None:
        self.generations[guild_id] = self.generations.get(guild_id, 0) + 1
        self.pending_restore.pop(guild_id, None)
        task = self.jobs.pop(guild_id, None)
        if task is not None and not task.done():
            try:
                current = asyncio.current_task()
            except RuntimeError:
                current = None
            if task is not current:
                task.cancel()

    def eligible(self, guild_id: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if self.last_gateway_loss is None:
            return False
        since_gateway = now - self.last_gateway_loss
        since_manual = now - self.manual_leaves.get(guild_id, float("-inf"))
        return (0 <= since_gateway <= self.GATEWAY_WINDOW_SECONDS
                and since_manual >= self.MANUAL_WINDOW_SECONDS)

    def context(self, guild_id: int, now: float | None = None) -> dict[str, Any]:
        now = time.monotonic() if now is None else now
        return {
            "recovery_eligible": self.eligible(guild_id, now),
            "gateway_loss_age_ms": (None if self.last_gateway_loss is None else
                                    round((now - self.last_gateway_loss) * 1000)),
            "explicit_manual": now - self.manual_leaves.get(
                guild_id, float("-inf")) < self.MANUAL_WINDOW_SECONDS,
        }

    def begin_incident(self, guild_id: int, channel_id: int, *,
                       voice_close_code: int | None,
                       queue_saved: bool,
                       now: float | None = None) -> RecoveryIncident | None:
        self._invalidate(guild_id)
        if not queue_saved or self.context(guild_id, now)["explicit_manual"]:
            return None
        now = time.monotonic() if now is None else now
        # Close code 1000 cannot distinguish a Discord kick from network
        # trouble. Only unclean 1006 + recent gateway loss qualifies.
        auto_allowed = bool(self.eligible(guild_id, now)
                            and voice_close_code == 1006)
        incident = RecoveryIncident(
            guild_id=guild_id, channel_id=channel_id,
            generation=self.generations[guild_id],
            started_at=now, auto_allowed=auto_allowed,
        )
        self.pending_restore[guild_id] = incident
        return incident

    def valid(self, incident: RecoveryIncident, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        return (self.pending_restore.get(incident.guild_id) is incident
                and self.generations.get(incident.guild_id) == incident.generation
                and 0 <= now - incident.started_at <= self.MAX_RECOVERY_SECONDS)

    def has_running_job(self, guild_id: int) -> bool:
        task = self.jobs.get(guild_id)
        return task is not None and not task.done()

    def restored(self, guild_id: int) -> None:
        """On successful get_player, drop the one-time restore request."""
        self._invalidate(guild_id)

    def schedule(self, incident: RecoveryIncident, task: asyncio.Task[bool]) -> None:
        if not incident.auto_allowed or not self.valid(incident):
            task.cancel()
            return
        old = self.jobs.get(incident.guild_id)
        if old is not None and not old.done() and old is not task:
            old.cancel()
        self.jobs[incident.guild_id] = task
        task.add_done_callback(
            lambda finished: self.jobs.pop(incident.guild_id, None)
            if self.jobs.get(incident.guild_id) is finished else None
        )


def voice_recovery_policy(bot: Any) -> VoiceRecoveryPolicy:
    policy = getattr(bot, "_voice_recovery_policy", None)
    if policy is None:
        policy = VoiceRecoveryPolicy()
        bot._voice_recovery_policy = policy
    return policy


def start_voice_recovery(bot: Any, policy: VoiceRecoveryPolicy,
                         incident: RecoveryIncident, logger: Any) -> None:
    if not incident.auto_allowed or not policy.valid(incident):
        return
    task = asyncio.create_task(recover_after_transport_loss(bot, policy, incident),
                               name=f"MB_VoiceRecovery_{incident.guild_id}")
    policy.schedule(incident, task)

    def finished(done: asyncio.Task[bool]) -> None:
        try:
            restored = done.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Unexpected voice recovery failure guild_id=%s",
                             incident.guild_id)
        else:
            logger.info("voice_recovery_result guild_id=%s restored=%s",
                        incident.guild_id, restored)

    task.add_done_callback(finished)


def _write_atomic(path: Path, data: str) -> None:
    """Avoid truncating the previous snapshot if write is interrupted."""
    temp = path.with_name(path.name + ".recovery-" + secrets.token_hex(6))
    try:
        with open(temp, "x", encoding="utf-8") as output:
            os.chmod(temp, 0o600)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


async def preserve_voice_queue(bot: Any, guild: Any) -> bool:
    """Serialize current song, playback progress, and queue before kill().

    Shares the existing serialization lock with normal persistent queue
    reads/writes. The file format is exactly MusicPlayer.serialize().
    """
    if not bot.config.persistent_queue:
        return False
    player = bot.get_player_in(guild)
    if player is None:
        return False
    path = bot.config.data_path.joinpath(str(guild.id), DATA_GUILD_FILE_QUEUE)
    try:
        async with bot.aiolocks["queue_serialization:" + str(guild.id)]:
            payload = player.serialize(sort_keys=True)
            if not isinstance(json.loads(payload), dict):
                return False
            await asyncio.to_thread(_write_atomic, path, payload)
    except (OSError, ValueError, TypeError):
        return False
    return True


async def recover_after_transport_loss(
    bot: Any, policy: VoiceRecoveryPolicy, incident: RecoveryIncident
) -> bool:
    """Up to two reconnects, with bounded duration and strict incident token."""
    import discord
    from .exceptions import MusicbotException

    if not incident.auto_allowed:
        return False
    for delay in policy.RETRY_DELAYS_SECONDS:
        await asyncio.sleep(delay)
        if not policy.valid(incident) or getattr(bot, "logout_called", False):
            return False
        guild = bot.get_guild(incident.guild_id)
        if guild is None or bot.get_player_in(guild) is not None:
            return False
        vc = guild.voice_client
        if vc is not None and vc.is_connected():
            return False
        channel = bot.get_channel(incident.channel_id)
        if (not isinstance(channel, (discord.VoiceChannel, discord.StageChannel))
                or channel.guild.id != incident.guild_id):
            return False
        try:
            player = await asyncio.wait_for(
                bot.get_player(channel, create=True, deserialize=True),
                timeout=policy.RECOVERY_TIMEOUT_SECONDS,
            )
            if not policy.valid(incident):
                # A newer player or intentional disconnect won the race.
                return False
            if player.is_stopped and len(player.playlist) > 0:
                player.play()
            policy.restored(incident.guild_id)
            return True
        except (asyncio.TimeoutError, discord.ClientException, discord.HTTPException,
                MusicbotException, OSError, TypeError):
            if bot.get_player_in(guild) is not None or not policy.valid(incident):
                return False
    return False
