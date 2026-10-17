"""Best-effort, bounded guild activity. Never retain command arguments or errors."""
from __future__ import annotations

import inspect
import logging
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps

from .constructs import ErrorResponse
from .web_dashboard_guild_settings import vote_skip_enabled
from .web_dashboard_i18n import message

log = logging.getLogger(__name__)
ACTIVE = ContextVar("dashboard_native_activity", default=None)
ACTIONS = {
    "play": "m0231", "playnext": "m0463", "playnow": "m0464",
    "shuffleplay": "m0465", "stream": "m0466", "skip": "m0333",
    "undo": "m0122", "remove": "m0467", "move": "m0468", "shuffle": "m0469", "clear": "m0470",
    "pause": "m0108", "resume": "m0109", "volume": "m0337",
    "repeat": "m0114", "seek": "m0471",
}


def player_view(bot, guild):
    player = bot.get_player_in(guild)
    entries = list(player.playlist.entries) if player else []
    current = getattr(player, "current_entry", None)
    return {"entries": {id(item): str(item.title)[:160] for item in entries},
            "order": [id(item) for item in entries],
            "current": (id(current), str(current.title)[:160]) if current else None,
            "votes": (len(getattr(getattr(player, "skip_state", None), "skippers", ()))
                      if vote_skip_enabled(bot, guild) else 0),
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
    target_position: int | None = None

    def finish(self, success=None):
        if success is None:
            success = self.success
        after = player_view(self.dashboard.bot, self.guild)
        before = self.before
        parts = [{"code":ACTIONS[self.action]}]
        label = message(ACTIONS[self.action])
        titles = []
        if self.action in ("play", "playnext", "playnow", "shuffleplay", "stream", "undo"):
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
                label = message("m0472")
                parts = [{"code":"m0472"}]
        if self.action == "volume" and success:
            label += f"：{after['volume']}%"
            parts = [{"code":"activity.volume","params":{"p0":after["volume"]}}]
        elif self.action == "repeat" and success:
            code = {"off":"m0118","song":"m0115","all":"m0119"}[after["repeat"]]
            label += ":" + message(code)
            parts.extend([{"code":"punct.colon"},{"code":code}])
        elif self.action == "seek" and success:
            position = self.target_position if self.target_position is not None else after["progress"]
            label += f"：{position} 秒"
            parts.append({"code":"m0389","params":{"p0":position}})
        # Names only; no query, URL, command arguments, raw exceptions or user IDs.
        detail = "、".join(titles[:8])
        if len(titles) > 8:
            detail += f" 等 {len(titles)} 首"
        if titles:
            parts.append({"code":"punct.colon"})
            for i,title in enumerate(titles[:8]):
                if i:parts.append({"code":"punct.list"})
                parts.append(title)
            if len(titles)>8:parts.append({"code":"m0473","params":{"p0":len(titles)}})
        self.dashboard.record_activity(
            self.guild, self.actor, self.action, self.source,
            label + ("：" + detail if detail else ""),
            message("m0024" if success else "m0474"),
            detail_parts=parts,result_code="m0024" if success else "m0474")


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
