"""Best-effort, bounded guild activity. Never retain command arguments or errors."""
from __future__ import annotations

import inspect
import logging
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps

from .constructs import ErrorResponse

log = logging.getLogger(__name__)
ACTIVE = ContextVar("dashboard_native_activity", default=None)
ACTIONS = {
    "play": "點歌", "playnext": "插播", "playnow": "立即播放",
    "shuffleplay": "隨機點歌", "stream": "串流點歌", "skip": "跳過",
    "remove": "刪除", "move": "移動", "shuffle": "洗牌", "clear": "清空佇列",
    "pause": "暫停", "resume": "繼續", "volume": "音量",
    "repeat": "重複", "seek": "跳轉",
}


def player_view(bot, guild):
    player = bot.get_player_in(guild)
    entries = list(player.playlist.entries) if player else []
    current = getattr(player, "current_entry", None)
    return {"entries": {id(item): str(item.title)[:160] for item in entries},
            "order": [id(item) for item in entries],
            "current": (id(current), str(current.title)[:160]) if current else None,
            "votes": len(getattr(getattr(player, "skip_state", None), "skippers", ())),
            "volume": round(getattr(player, "volume", 0) * 100),
            "repeat": ("song" if getattr(player, "repeatsong", False) else
                       "all" if getattr(player, "loopqueue", False) else "off"),
            "progress": max(0, round(getattr(player, "progress", 0)))}


@dataclass
class Capture:
    dashboard: object
    guild: object
    actor: str
    action: str
    source: str
    before: dict
    success: bool = False

    def finish(self, success=None):
        if success is None:
            success = self.success
        after = player_view(self.dashboard.bot, self.guild)
        before = self.before
        label = ACTIONS[self.action]
        titles = []
        if self.action in ("play", "playnext", "playnow", "shuffleplay", "stream"):
            titles = [name for key, name in after["entries"].items() if key not in before["entries"]]
            if after["current"] and after["current"] != before["current"]:
                titles.append(after["current"][1])
        elif self.action in ("remove", "clear"):
            titles = [name for key, name in before["entries"].items() if key not in after["entries"]]
        elif self.action == "move":
            changed = [key for i, key in enumerate(before["order"])
                       if i >= len(after["order"]) or key != after["order"][i]]
            titles = [before["entries"][key] for key in changed[:3]]
        elif self.action == "skip":
            titles = [before["current"][1]] if before["current"] else []
            if after["current"] == before["current"] and after["votes"]:
                label = "投票跳過"
        if self.action == "volume" and success:
            label += f"：{after['volume']}%"
        elif self.action == "repeat" and success:
            label += "：" + {"off": "關閉", "song": "單曲", "all": "整個佇列"}[after["repeat"]]
        elif self.action == "seek" and success:
            label += f"：{after['progress']} 秒"
        # Names only; no query, URL, command arguments, raw exceptions or user IDs.
        detail = "、".join(titles[:8])
        if len(titles) > 8:
            detail += f" 等 {len(titles)} 首"
        self.dashboard.record_activity(
            self.guild, self.actor, self.action, self.source,
            label + ("：" + detail if detail else ""),
            "成功" if success else "被拒或未完成")


def capture(dashboard, guild, actor, action, source):
    try:
        if dashboard is None or guild is None or action not in ACTIONS:
            return None
        name = str(getattr(actor, "display_name", None) or getattr(actor, "name", "成員"))[:128]
        return Capture(dashboard, guild, name, action, source, player_view(dashboard.bot, guild))
    except Exception as exc:
        log.warning("Activity capture failed (%s)", type(exc).__name__)
        return None


def finish(value, success=None):
    try:
        if value is not None:
            value.finish(success)
    except Exception as exc:
        log.warning("Activity recording failed (%s)", type(exc).__name__)


def begin_text(bot, message, command):
    """Called after alias resolution, before existing permission/argument dispatch."""
    try:
        return capture(getattr(bot, "_web_dashboard", None), message.guild,
                       message.author, command, "discord_text")
    except Exception as exc:
        log.warning("Activity capture failed (%s)", type(exc).__name__)
        return None


def native_result(response):
    """No effect on responses, exceptions, permission checks or command arguments."""
    try:
        value = ACTIVE.get()
        if value is not None:
            value.success = not isinstance(response, ErrorResponse)
    except Exception as exc:
        log.warning("Activity result failed (%s)", type(exc).__name__)


def slash_activity(command):
    """Wrap the callback, not cmd_*; functools.wraps preserves slash signatures."""
    def decorate(callback):
        @wraps(callback)
        async def wrapped(self, interaction, *args, **kwargs):
            value, token = None, None
            try:
                value = capture(getattr(self.bot, "_web_dashboard", None),
                                interaction.guild, interaction.user, command, "discord_slash")
                token = ACTIVE.set(value)
            except Exception as exc:
                log.warning("Activity capture failed (%s)", type(exc).__name__)
            try:
                return await callback(self, interaction, *args, **kwargs)
            finally:
                try:
                    if token is not None:
                        ACTIVE.reset(token)
                    finish(value)
                except Exception as exc:
                    log.warning("Activity recording failed (%s)", type(exc).__name__)
        # discord.py evaluates postponed annotations in the callback's globals.
        # Resolve them in the original module, preserving every slash parameter.
        wrapped.__annotations__ = inspect.get_annotations(callback, eval_str=True)
        wrapped.__signature__ = inspect.signature(callback, eval_str=True)
        return wrapped
    return decorate
